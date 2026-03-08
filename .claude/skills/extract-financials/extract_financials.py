#!/usr/bin/env python3
"""Extract financial tables and notes from PDFs into Excel."""

import sys
import importlib
from pathlib import Path


def check_deps(required: list[str] | None = None) -> list[str]:
    """Return list of install instructions for missing packages."""
    if required is None:
        required = ["pdfplumber", "openpyxl", "anthropic"]
    missing = []
    for pkg in required:
        try:
            importlib.import_module(pkg)
        except ImportError:
            missing.append(f"pip install {pkg}")
    return missing


if __name__ == "__main__":
    missing = check_deps()
    if missing:
        print("Missing dependencies. Run:")
        for cmd in missing:
            print(f"  {cmd}")
        sys.exit(1)
    print("All dependencies present.")
