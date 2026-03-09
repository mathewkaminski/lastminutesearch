---
name: extract-financials
description: Use when the user provides a PDF (investor deck, financial report, pitch deck) and wants financial tables, metrics, or data extracted into a structured Excel file with one tab per financial page.
---

# extract-financials

Extracts financial tables and notes from a PDF into a clean Excel file — one tab per financial page, table data at A1, notes below.

## Usage

```
/extract-financials path/to/file.pdf
```

## What Claude Does

1. **Confirm the file exists** and ends with `.pdf`. If not, tell the user and stop.

2. **Run the extraction script**:
   ```bash
   python "C:\Users\mathe\.claude\skills\extract-financials\extract_financials.py" "<pdf_path>"
   ```
   The script loads `ANTHROPIC_API_KEY` from the environment. If it's not set, it will fail — tell the user to set it or check `C:\Users\mathe\VSCode\aa_RecLeagueDB\.env`.

3. **Report results** to the user:
   - Which pages were identified as financial (page number + tab name)
   - Where the output file was saved (`<same_directory_as_pdf>/<pdf_name>_financials.xlsx`)
   - If any pages failed to extract, list them

## Output

- Excel file saved in same directory as PDF: `<pdf_stem>_financials.xlsx`
- One tab per financial page (auto-detected by Claude)
- Table data starting at A1, clean text values
- Notes/bullet text appended below table with a blank row separator

## Requirements

- `ANTHROPIC_API_KEY` must be in environment (or loadable from `.env`)
- Dependencies: `pdfplumber`, `openpyxl`, `anthropic` (install with `pip install pdfplumber openpyxl anthropic`)
