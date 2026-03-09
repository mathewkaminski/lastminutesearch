#!/usr/bin/env python3
"""Extract financial tables and notes from PDFs into Excel."""

import sys
import importlib
import anthropic
import json
import os
from pathlib import Path

import pdfplumber
import openpyxl


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


EXTRACT_PROMPT = """You are extracting financial data from one page of an investor deck PDF.

Page text:
{page_text}

Raw tables detected by pdfplumber (may be incomplete or garbled):
{raw_tables}

Instructions:
1. Clean up any garbled characters (replace ? or replacement characters with the correct symbol).
2. For numeric values, strip currency symbols and output plain numbers (e.g., 9470051 for $9,470,051, remove commas too). Preserve percentages as decimals (e.g., 0.54 for 54%). Do NOT abbreviate (e.g., never write 9.47M).
3. Reconstruct the table with proper headers. If there are grouped column headers
   (e.g., "ACTUALS" spanning multiple years), represent them as an extra header row.
4. Capture ALL notes and bullet points found anywhere on the page — even text that
   is not inside a table. These go in the notes list.
5. The tab_name must be 31 characters or fewer.

Return ONLY valid JSON, no explanation:
{{
  "tab_name": "<descriptive name, max 31 chars>",
  "table": [
    ["col1", "col2", ...],
    ["row1val1", "row1val2", ...]
  ],
  "notes": [
    "Note text here.",
    "Another note."
  ]
}}"""


def extract_page_data(page: dict, tab_name: str) -> dict:
    """Use Claude to extract structured table + notes from a single financial page.

    Returns {tab_name, table: list[list[str]], notes: list[str]}
    """
    raw_tables_str = json.dumps(page["tables"], indent=2) if page["tables"] else "none detected"

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        messages=[{
            "role": "user",
            "content": EXTRACT_PROMPT.format(
                page_text=page["text"],
                raw_tables=raw_tables_str,
            )
        }]
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    result = json.loads(raw)
    result["tab_name"] = tab_name
    return result


def write_excel(pages_data: list[dict], output_path: str) -> None:
    """Write extracted financial data to an Excel file.

    Each page gets one worksheet. Layout:
        A1...: table rows
        (blank row)
        "Notes:"
        one note per row
    """
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    for page in pages_data:
        tab_name = page["tab_name"][:31]
        ws = wb.create_sheet(title=tab_name)

        for row in page["table"]:
            ws.append([cell if cell is not None else "" for cell in row])

        ws.append([])

        if page["notes"]:
            ws.append(["Notes:"])
            for note in page["notes"]:
                ws.append([note])

    wb.save(output_path)


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python extract_financials.py <path_to_pdf>")
        sys.exit(1)

    pdf_path = sys.argv[1]

    if not Path(pdf_path).exists():
        print(f"Error: file not found: {pdf_path}")
        sys.exit(1)

    if not pdf_path.lower().endswith(".pdf"):
        print(f"Error: file must be a PDF: {pdf_path}")
        sys.exit(1)

    missing = check_deps()
    if missing:
        print("Missing dependencies. Install with:")
        for cmd in missing:
            print(f"  {cmd}")
        sys.exit(1)

    print(f"Scanning {pdf_path}...")
    pages = extract_pages(pdf_path)
    print(f"  Found {len(pages)} pages total.")

    print("Detecting financial pages with Claude...")
    financial_pages_meta = detect_financial_pages(pages)
    print(f"  Identified {len(financial_pages_meta)} financial pages:")
    for meta in financial_pages_meta:
        print(f"    Page {meta['page_number']}: {meta['tab_name']}")

    pages_data = []
    for meta in financial_pages_meta:
        page_num = meta["page_number"]
        tab_name = meta["tab_name"]
        print(f"Extracting page {page_num}: {tab_name}...")
        page = next(p for p in pages if p["page_number"] == page_num)
        try:
            data = extract_page_data(page, tab_name)
            pages_data.append(data)
        except Exception as e:
            print(f"  Warning: failed to extract page {page_num}: {e}")

    output_path = str(Path(pdf_path).with_name(
        Path(pdf_path).stem + "_financials.xlsx"
    ))
    write_excel(pages_data, output_path)
    print(f"\nDone. Output saved to: {output_path}")
    print(f"Tabs created: {[p['tab_name'] for p in pages_data]}")


if __name__ == "__main__":
    main()
