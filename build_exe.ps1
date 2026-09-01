$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = [System.IO.Path]::GetFullPath($PSScriptRoot)
Set-Location -LiteralPath $projectRoot

$venv = Join-Path $projectRoot '.venv'
$python = Join-Path $venv 'Scripts\python.exe'

# Require Python 3.12 explicitly. pygame/source-build issues and several native
# dependencies are much less predictable on newer Python versions.
& py -3.12 -c "import sys; print(sys.version)" | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw 'Python 3.12 (64-bit) is required. Install it from python.org, then run this script again.'
}

# Recreate an existing venv if it was made with another Python version.
$recreateVenv = $false
if (Test-Path -LiteralPath $python) {
    & $python -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3,12) else 1)"
    if ($LASTEXITCODE -ne 0) { $recreateVenv = $true }
}
if ($recreateVenv -and (Test-Path -LiteralPath $venv)) {
    Write-Host 'Existing .venv is not Python 3.12; recreating it...'
    Remove-Item -LiteralPath $venv -Recurse -Force
}

if (-not (Test-Path -LiteralPath $python)) {
    Write-Host 'Creating Python 3.12 build environment...'
    & py -3.12 -m venv $venv
    if ($LASTEXITCODE -ne 0) {
        throw 'Could not create the Python 3.12 virtual environment.'
    }
}

Write-Host 'Installing dependencies...'
& $python -m pip install --upgrade pip setuptools wheel
if ($LASTEXITCODE -ne 0) { throw 'Could not update pip/setuptools/wheel.' }
& $python -m pip install -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }

Write-Host 'Building 2KStabilizer.exe...'
& $python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name '2KStabilizer' `
    --paths (Join-Path $projectRoot 'src\2k26') `
    --collect-all pydivert `
    --collect-all cv2 `
    --collect-all numpy `
    --collect-all PIL `
    --collect-all vgamepad `
    --collect-all pydualsense `
    --hidden-import win32gui `
    --hidden-import win32ui `
    --hidden-import win32con `
    --hidden-import hid `
    --hidden-import packet_capture `
    --hidden-import pluto_core `
    --hidden-import runtime_safety `
    --hidden-import setup_wizard `
    --hidden-import stats `
    --hidden-import system_tweaks `
    --hidden-import ui `
    --hidden-import ui_features `
    --hidden-import widgets `
    --hidden-import overlay `
    --add-binary ((Join-Path $projectRoot 'src\2k26\hidapi.dll') + ';.') `
    packet_shaper.py

if ($LASTEXITCODE -ne 0) {
    throw 'PyInstaller build failed.'
}

$exe = Join-Path $projectRoot 'dist\2KStabilizer.exe'
if (-not (Test-Path -LiteralPath $exe)) {
    throw "Build finished but the EXE was not found: $exe"
}

Write-Host ''
Write-Host 'Build complete:'
Write-Host $exe
