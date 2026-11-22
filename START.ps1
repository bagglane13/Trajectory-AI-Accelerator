$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
$env:PYTHONUTF8 = '1'
$env:PYTHON_MANAGER_AUTOMATIC_INSTALL = 'false'
$runtimeRoot = Join-Path $PSScriptRoot '.runtime\runtime'
New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null
Set-Location -LiteralPath $PSScriptRoot
function Test-Python([string]$Exe, [string[]]$PrefixArgs) {
    try {
        $output = & $Exe @PrefixArgs -c "import sys,struct;print(sys.executable if sys.version_info[:2] in ((3,12),(3,13),(3,14)) and struct.calcsize('P')==8 and sys.version_info.releaselevel=='final' else '')" 2>$null
        if ($LASTEXITCODE -eq 0 -and $output) { return [string]($output | Select-Object -Last 1) }
    } catch {}
    return $null
}
try {
    Write-Host 'Trajectory AI: automatic local setup. Keep this window open.'
    $pythonExe = $null
    foreach ($candidate in @((Join-Path $runtimeRoot 'python\python.exe'), (Join-Path $PSScriptRoot 'ai-accelerator\.venv\Scripts\python.exe'), 'python')) {
        $pythonExe = Test-Python $candidate @()
        if ($pythonExe) { break }
    }
    if (-not $pythonExe) {
        foreach ($ver in @('-3.14','-3.13','-3.12')) {
            $pythonExe = Test-Python 'py' @($ver)
            if ($pythonExe) { break }
        }
    }
    if (-not $pythonExe) {
        Write-Host 'Downloading Python 3.14.8 from python.org...'
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $installer = Join-Path $runtimeRoot 'python-3.14.8-amd64.exe'
        Invoke-WebRequest -UseBasicParsing -Uri 'https://www.python.org/ftp/python/3.14.8/python-3.14.8-amd64.exe' -OutFile $installer
        $signature = Get-AuthenticodeSignature -LiteralPath $installer
        if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Python Software Foundation') { throw 'Python installer signature could not be verified.' }
        $pythonDir = Join-Path $runtimeRoot 'python'
        $arguments = '/quiet InstallAllUsers=0 Include_launcher=0 PrependPath=0 Include_test=0 Shortcuts=0 AssociateFiles=0 TargetDir="' + $pythonDir + '"'
        $process = Start-Process -FilePath $installer -ArgumentList $arguments -Wait -PassThru
        if ($process.ExitCode -notin @(0,3010)) { throw "Python setup failed: $($process.ExitCode)" }
        $pythonExe = Test-Python (Join-Path $pythonDir 'python.exe') @()
        if (-not $pythonExe) { throw 'Python did not start after installation.' }
    }
    & $pythonExe (Join-Path $PSScriptRoot 'run_local.py')
    if ($LASTEXITCODE -ne 0) { throw 'Startup stopped. Details and the log path are shown above.' }
} catch {
    Write-Host ''
    Write-Host $_.Exception.Message -ForegroundColor Red
    Read-Host 'Press Enter to close this window'
    exit 1
}
