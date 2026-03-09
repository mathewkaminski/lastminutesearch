---
description: "Extract financial tables and notes from a PDF into a clean Excel file, one tab per financial page."
---

You are running the extract-financials skill. The user has provided a PDF path as an argument.

1. Confirm the file exists and ends with `.pdf`. If not, tell the user and stop.

2. Run the extraction script:
   ```bash
   python "C:\Users\mathe\.claude\skills\extract-financials\extract_financials.py" "$ARGUMENTS"
   ```
   The script requires ANTHROPIC_API_KEY in the environment. If it fails with a KeyError, tell the user to set it or check `C:\Users\mathe\VSCode\aa_RecLeagueDB\.env`.

3. Report results to the user:
   - Which pages were identified as financial (page number + tab name)
   - Where the output file was saved (`<same_directory_as_pdf>/<pdf_name>_financials.xlsx`)
   - If any pages failed to extract, list them
