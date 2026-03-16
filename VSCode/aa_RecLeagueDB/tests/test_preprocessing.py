import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

import requests
from src.extractors.html_preprocessor import HtmlPreProcessor

url = "https://www.ottawavolleysixes.com/home/volleyball"
response = requests.get(url)
html = response.text

print(f"Fetched {len(html)} bytes\n")

# Pre-process HTML
preprocessor = HtmlPreProcessor()
result = preprocessor.preprocess(url, html)

print(f"=== PRE-PROCESSING RESULTS ===")
print(f"Page Type: {result.page_type}")
print(f"Tables Found: {len(result.extracted_tables)}")
print(f"League Lists Detected: {len(result.league_list_hints)}\n")

if result.extracted_tables:
    print(f"=== EXTRACTED TABLES ===")
    for i, table in enumerate(result.extracted_tables):
        print(f"\nTable {i}: {len(table.rows)} rows")
        print(f"Headers: {table.headers}")
        if table.rows:
            print(f"First row: {table.rows[0]}")

if result.league_list_hints:
    print(f"\n=== LEAGUE LIST HINTS ===")
    for hint in result.league_list_hints:
        print(f"League List (Confidence: {hint.confidence:.2f}): {len(hint.leagues)} leagues")
        for j, league in enumerate(hint.leagues[:3]):
            print(f"  {j+1}. {league}\n")
