$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = [System.IO.Path]::GetFullPath($PSScriptRoot)
$buildRoot = Join-Path $projectRoot 'build'
$distRoot = Join-Path $projectRoot 'dist'
$releaseRoot = Join-Path $projectRoot 'release'
$specPath = Join-Path $projectRoot 'build_config\GameConnectionStabilizer.spec'
$venvRoot = Join-Path $projectRoot '.venv'
$venvPython = Join-Path $venvRoot 'Scripts\python.exe'

function Remove-GeneratedDirectory {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string[]]$AllowedNames
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }

    $resolved = [System.IO.Path]::GetFullPath((Resolve-Path -LiteralPath $Path).Path)
    $requiredPrefix = $projectRoot.TrimEnd('\') + '\'
    $leaf = Split-Path -Leaf $resolved
    if (-not $resolved.StartsWith($requiredPrefix, [StringComparison]::OrdinalIgnoreCase) -or
        $leaf -notin $AllowedNames) {
        throw "Refusing to remove unexpected path: $resolved"
    }

    Remove-Item -LiteralPath $resolved -Recurse -Force
}

Set-Location -LiteralPath $projectRoot

if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host 'Creating isolated build environment...'
    py -3.14 -m venv $venvRoot
    if ($LASTEXITCODE -ne 0) {
        throw 'Could not create .venv with 64-bit Python 3.14.'
    }
}

Write-Host 'Installing pinned application and build dependencies...'
& $venvPython -m pip install --disable-pip-version-check -r requirements-build.txt
if ($LASTEXITCODE -ne 0) {
    throw 'Could not install the pinned dependencies into .venv.'
}

& $venvPython -c "import PyInstaller, pyarmor.cli, pydivert" | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw 'The build environment is missing PyInstaller, PyArmor, or PyDivert.'
}

& $venvPython -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) {
    throw 'Tests failed; release build stopped.'
}

Remove-GeneratedDirectory -Path $buildRoot -AllowedNames @('build')
Remove-GeneratedDirectory -Path $distRoot -AllowedNames @('dist')
Remove-GeneratedDirectory -Path $releaseRoot -AllowedNames @('release')

New-Item -ItemType Directory -Path $buildRoot | Out-Null
New-Item -ItemType Directory -Path $releaseRoot | Out-Null

& $venvPython -m pyarmor.cli gen --pack $specPath -r packet_shaper.py src
if ($LASTEXITCODE -ne 0) {
    throw 'PyArmor/PyInstaller build failed. A paid PyArmor license may be required for larger modules.'
}

$builtExe = Join-Path $projectRoot 'dist\GameConnectionStabilizer.exe'
if (-not (Test-Path -LiteralPath $builtExe)) {
    throw "Expected executable was not created: $builtExe"
}

Move-Item -LiteralPath $builtExe -Destination $releaseRoot
Copy-Item -LiteralPath (Join-Path $projectRoot 'README.md') -Destination $releaseRoot
Copy-Item -LiteralPath (Join-Path $projectRoot 'THIRD_PARTY_NOTICES.md') -Destination $releaseRoot

$hash = Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $releaseRoot 'GameConnectionStabilizer.exe')
$hash.Hash | Set-Content -Encoding ascii -LiteralPath (Join-Path $releaseRoot 'GameConnectionStabilizer.exe.sha256')

Write-Host "Release created: $releaseRoot"
Write-Host "SHA256: $($hash.Hash)"
