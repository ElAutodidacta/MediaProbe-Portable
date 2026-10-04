# Compilacion reproducible

MediaProbe usa Python 3.11 o posterior y solamente la biblioteca estandar durante la ejecucion. PyInstaller se usa para crear un archivo autocontenido.

## Windows

Abra PowerShell en la carpeta del proyecto:

```powershell
py -3.12 -m venv .venv-build
.\.venv-build\Scripts\python.exe -m pip install --upgrade pip
.\.venv-build\Scripts\python.exe -m pip install -r requirements-build.txt
.\build_windows.ps1
```

El resultado queda en `dist/MediaProbe-Portable.exe`. El script ejecuta primero las pruebas unitarias.

## Linux

Compile en una distribucion igual o mas antigua que los equipos destino, porque la compatibilidad de `glibc` va hacia adelante:

```bash
python3 -m venv .venv-build
.venv-build/bin/pip install -r requirements-build.txt
chmod +x build_linux.sh
./build_linux.sh
```

El resultado `dist/MediaProbe-Portable-linux-x86_64` es un binario de un solo archivo. PyInstaller no permite compilar el binario Linux desde Windows. Para CID/CSD/OCR se necesita un lector SD/MMC directo; para SMART, instale `smartmontools` o coloque `smartctl` en `tools/` respetando su licencia.

## Pruebas desde el codigo

```text
python -m unittest discover -s tests -v
python main.py --list-json
```

El segundo comando enumera dispositivos sin abrir la interfaz y ayuda a diagnosticar permisos.

