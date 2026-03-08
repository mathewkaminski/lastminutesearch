#!/usr/bin/env python3
"""Extract financial tables and notes from PDFs into Excel."""

import sys
import importlib
import anthropic
import json
import os
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


SCAN_PROMPT = """You are analyzing pages from a PDF to identify which contain financial data.

Financial data means: tables or text with dollar amounts, percentages, revenue/profit figures,
cost breakdowns, or other quantitative business metrics organized by year or category.

Here are all the pages from the PDF. For each page, decide if it contains financial data.

Pages:
{pages_summary}

Return ONLY a JSON array, no explanation. Each element:
{{
  "page_number": <int>,
  "tab_name": "<short descriptive name for Excel tab, max 31 chars>",
  "has_financial_data": <true|false>
}}"""


def detect_financial_pages(pages: list[dict]) -> list[dict]:
    """Use Claude to identify which pages contain financial data.

    Returns list of {page_number, tab_name} for financial pages only.
    """
    summaries = []
    for p in pages:
        text_preview = p["text"][:500].replace("\n", " ") if p["text"] else "(no text)"
        has_tables = len(p["tables"]) > 0
        summaries.append(
            f"Page {p['page_number']}: tables={has_tables} | {text_preview}"
        )

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        messages=[{
            "role": "user",
            "content": SCAN_PROMPT.format(pages_summary="\n\n".join(summaries))
        }]
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    results = json.loads(raw)
    return [r for r in results if r.get("has_financial_data")]


if __name__ == "__main__":
    missing = check_deps()
    if missing:
        print("Missing dependencies. Run:")
        for cmd in missing:
            print(f"  {cmd}")
        sys.exit(1)
    print("All dependencies present.")
