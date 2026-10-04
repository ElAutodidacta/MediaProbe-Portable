from __future__ import annotations

import argparse
import json

from mediaprobe import __version__
from mediaprobe.browserui import run_browser_ui
from mediaprobe.discovery import discover_devices


def main() -> int:
    parser = argparse.ArgumentParser(description="MediaProbe Portable")
    parser.add_argument("--list-json", action="store_true", help="Enumera volumenes como JSON y no abre la interfaz")
    parser.add_argument("--no-browser", action="store_true", help="Inicia el servidor local sin abrir el navegador")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args()
    if args.list_json:
        print(json.dumps([d.to_dict() for d in discover_devices()], ensure_ascii=False, indent=2))
        return 0
    run_browser_ui(no_browser=args.no_browser)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
