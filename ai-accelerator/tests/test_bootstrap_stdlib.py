"""Launcher regression tests: standard library only, no pip or server required."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('bootstrap',Path(__file__).resolve().parents[1]/'scripts'/'bootstrap.py')
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
GOOD={'version':[3,12,14],'bits':64,'release':'final','path':'python'}

class BootstrapTests(unittest.TestCase):
    def test_supported_versions(self):
        for minor in (12,13,14):self.assertTrue(b.supported({**GOOD,'version':[3,minor,0]}))
    def test_reject_old_preview_and_32bit(self):
        self.assertFalse(b.supported({**GOOD,'version':[3,8,18]}))
        self.assertFalse(b.supported({**GOOD,'bits':32}))
        self.assertFalse(b.supported({**GOOD,'release':'alpha'}))
    def test_missing_interpreter(self):
        with patch.object(b.subprocess,'run',side_effect=FileNotFoundError):self.assertIsNone(b.probe('missing'))
    def test_reuse_existing_venv(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=b.env_python(root);p.parent.mkdir(parents=True);p.touch()
            with patch.object(b,'probe',return_value=GOOD),patch.object(b,'execute') as run:
                self.assertEqual(b.ensure_environment(root)[0],p);run.assert_not_called()
    def test_broken_environment_is_backed_up(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=b.env_python(root);p.parent.mkdir(parents=True);p.touch()
            (root/'.venv'/'keep.txt').write_text('preserve')
            with patch.object(b,'probe',side_effect=[None,GOOD]),patch.object(b,'execute'):
                b.ensure_environment(root)
            copies=list(root.glob('.venv.backup-*/keep.txt'));self.assertEqual(len(copies),1)
            self.assertEqual(copies[0].read_text(),'preserve')
    def test_failed_creation_stops(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(b,'execute',side_effect=b.SetupError('venv failed')):
                with self.assertRaises(b.SetupError):b.ensure_environment(Path(d))
    def test_successful_install_is_cached(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'.venv').mkdir();(root/'requirements.txt').write_text('fastapi==0.142.2')
            with patch.object(b.subprocess,'run',return_value=subprocess.CompletedProcess([],0)),patch.object(b,'execute') as run:
                b.install_dependencies('python',GOOD,root)
                self.assertTrue((root/'.venv'/'.trajectory-dependencies').exists())
                self.assertEqual(run.call_count,2)
                run.reset_mock();b.install_dependencies('python',GOOD,root);run.assert_not_called()
    def test_failed_install_has_no_success_marker(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'.venv').mkdir();(root/'requirements.txt').write_text('fastapi==0.142.2')
            with patch.object(b.subprocess,'run',return_value=subprocess.CompletedProcess([],0)),patch.object(b,'execute',side_effect=b.SetupError('pip failed')):
                with self.assertRaises(b.SetupError):b.install_dependencies('python',GOOD,root)
            self.assertFalse((root/'.venv'/'.trajectory-dependencies').exists())
    def test_check_does_not_install_or_run_server(self):
        with patch.object(b,'probe',return_value=GOOD),patch.object(b,'available_port',return_value=True),patch.object(b,'ensure_environment') as create:
            self.assertEqual(b.main(['--check']),0);create.assert_not_called()

if __name__=='__main__':unittest.main()
