$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $project
$version = [regex]::Match((Get-Content -LiteralPath (Join-Path $project 'mediaprobe\__init__.py') -Raw), '__version__ = "([^"]+)"').Groups[1].Value
if (-not $version) { throw 'No se pudo determinar la version.' }
$outputs = Join-Path $root 'outputs'
$stage = Join-Path $root "work\MediaProbe-v$version-package-stage"
$source = Join-Path $stage 'source'
$exe = Join-Path $project 'dist\MediaProbe-Portable.exe'
if (-not (Test-Path -LiteralPath $exe)) { throw 'Compile primero el EXE.' }
if (Test-Path -LiteralPath $stage) { throw "La carpeta de etapa ya existe: $stage" }
New-Item -ItemType Directory -Path $stage, $source -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $source 'mediaprobe'), (Join-Path $source 'tests') | Out-Null
foreach ($name in @('main.py', 'README.md', 'README_ES.md', 'AUTHORS.md', 'LIMITACIONES.md', 'COMPILAR.md', 'LICENSE.txt', 'requirements-build.txt', 'build_windows.ps1', 'build_linux.sh', 'package_windows.ps1', 'run_from_source.bat')) {
    Copy-Item -LiteralPath (Join-Path $project $name) -Destination $source
}
Get-ChildItem -LiteralPath (Join-Path $project 'mediaprobe') -File | Where-Object { $_.Extension -in @('.py', '.html') } | Copy-Item -Destination (Join-Path $source 'mediaprobe')
Get-ChildItem -LiteralPath (Join-Path $project 'tests') -File -Filter '*.py' | Copy-Item -Destination (Join-Path $source 'tests')
Copy-Item -LiteralPath (Join-Path $project 'INICIO-RAPIDO.txt') -Destination $stage
Copy-Item -LiteralPath $exe -Destination $stage
$windowsZip = Join-Path $outputs "MediaProbe-Portable-v$version-Windows-y-Codigo.zip"
$sourceZip = Join-Path $outputs "MediaProbe-v$version-Codigo-Fuente.zip"
$exeOutput = Join-Path $outputs "MediaProbe-Portable-v$version.exe"
foreach ($target in @($windowsZip, $sourceZip, $exeOutput)) {
    if (Test-Path -LiteralPath $target) { throw "No se sobrescribira: $target" }
}
Copy-Item -LiteralPath $exe -Destination $exeOutput
Compress-Archive -Path (Join-Path $source '*') -DestinationPath $sourceZip -CompressionLevel Optimal
Compress-Archive -Path (Join-Path $stage 'source'), (Join-Path $stage 'MediaProbe-Portable.exe'), (Join-Path $stage 'INICIO-RAPIDO.txt') -DestinationPath $windowsZip -CompressionLevel Optimal
$hashFile = Join-Path $outputs "SHA256SUMS-v$version.txt"
if (Test-Path -LiteralPath $hashFile) { throw "No se sobrescribira: $hashFile" }
@($windowsZip, $sourceZip, $exeOutput) | ForEach-Object {
    $h = Get-FileHash -Algorithm SHA256 -LiteralPath $_
    "$($h.Hash.ToLowerInvariant())  $(Split-Path -Leaf $_)"
} | Set-Content -LiteralPath $hashFile -Encoding ascii
Write-Host "Paquetes creados en $outputs"
