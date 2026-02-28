#!/usr/bin/env python3
"""Vérifie que Tesseract est installé et utilisable pour l'OCR."""
import sys
from pathlib import Path

try:
    import pytesseract
    if sys.platform == "win32":
        for p in [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ]:
            if Path(p).exists():
                pytesseract.pytesseract.tesseract_cmd = p
                break
    pytesseract.get_tesseract_version()
    sys.exit(0)
except Exception:
    sys.exit(1)
