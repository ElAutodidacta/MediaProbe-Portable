$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $project '.venv-build\Scripts\python.exe'
if (-not (Test-Path $python)) {
    $python = (Get-Command python -ErrorAction Stop).Source
}
Push-Location $project
try {
    & $python -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw 'Las pruebas fallaron.' }
    & $python -m PyInstaller --noconfirm --clean --onefile --windowed --noupx --add-data 'mediaprobe/frontend.html;mediaprobe' --name MediaProbe-Portable main.py
    if ($LASTEXITCODE -ne 0) { throw 'La compilacion fallo.' }
    Write-Host "Creado: $project\dist\MediaProbe-Portable.exe"
} finally {
    Pop-Location
}
