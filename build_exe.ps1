$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = [System.IO.Path]::GetFullPath($PSScriptRoot)
Set-Location -LiteralPath $projectRoot

$venv = Join-Path $projectRoot '.venv'
$python = Join-Path $venv 'Scripts\python.exe'

if (-not (Test-Path -LiteralPath $python)) {
    Write-Host 'Creating Python build environment...'
    try {
        py -3.12 -m venv $venv
    } catch {
        py -m venv $venv
    }
}

if (-not (Test-Path -LiteralPath $python)) {
    throw 'Could not create .venv. Install 64-bit Python 3.12 and try again.'
}

Write-Host 'Installing dependencies...'
& $python -m pip install --upgrade pip
& $python -m pip install -r requirements-build.txt

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
    --collect-all mss `
    --collect-all dxcam `
    --collect-all vgamepad `
    --collect-all pydualsense `
    --collect-all pygame `
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
