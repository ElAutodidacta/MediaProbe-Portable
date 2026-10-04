#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
PYTHON=".venv-build/bin/python"
if [ ! -x "$PYTHON" ]; then PYTHON="python3"; fi
"$PYTHON" -m unittest discover -s tests -v
"$PYTHON" -m PyInstaller --noconfirm --clean --onefile --windowed --noupx --add-data 'mediaprobe/frontend.html:mediaprobe' --name MediaProbe-Portable-linux-x86_64 main.py
echo "Creado: dist/MediaProbe-Portable-linux-x86_64"
