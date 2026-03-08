#!/usr/bin/env python3
"""Extract financial tables and notes from PDFs into Excel."""

import sys
import importlib
from pathlib import Path

import pdfplumber


def extract_pages(pdf_path: str) -> list[dict]:
    """Extract text and tables from every page of a PDF.

    Returns list of:
        {page_number: int, text: str, tables: list[list[list]]}
    """
    results = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            tables = page.extract_tables() or []
            results.append({
                "page_number": i + 1,
                "text": text,
                "tables": tables,
            })
    return results


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
