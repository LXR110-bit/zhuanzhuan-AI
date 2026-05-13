#!/usr/bin/env python3
"""Compatibility wrapper for the HTML/CSS browser-screenshot daily renderer."""
import subprocess
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
RENDERER = BASE_DIR / "scripts" / "render_cards_html.py"


def main():
    cmd = [sys.executable, str(RENDERER), *sys.argv[1:]]
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
