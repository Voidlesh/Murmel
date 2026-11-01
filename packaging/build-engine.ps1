# Bundles the Python engine into build/engine-dist/murmel-engine/ with PyInstaller.
# Run from anywhere; needs the project venv (.venv) with requirements.txt and pyinstaller installed.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
$build = Join-Path $root 'build'

& $python -m PyInstaller --noconfirm --clean `
  --distpath (Join-Path $build 'engine-dist') `
  --workpath (Join-Path $build 'pyinstaller') `
  (Join-Path $root 'packaging\engine.spec')
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

Write-Output "Engine bundle: $(Join-Path $build 'engine-dist\murmel-engine')"
