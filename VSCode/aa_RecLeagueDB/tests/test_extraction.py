import os
from dotenv import load_dotenv

# Load environment variables from .env file FIRST
load_dotenv()

import requests
from src.extractors.league_extractor import extract_league_data

# Test URL - change this to test different leagues
url = "https://www.ottawavolleysixes.com/home/volleyball"

print(f"Fetching {url}...\n")
response = requests.get(url)
html = response.text

print(f"Fetched {len(html)} bytes of HTML\n")

# Extract leagues
try:
    print("Running extraction with GPT-4o...\n")
    leagues = extract_league_data(html, url, metadata={"method": "test", "pages_visited": 1})
    print(f"Successfully extracted {len(leagues)} leagues:\n")
    print("=" * 80)

    for i, league in enumerate(leagues, 1):
        print(f"\n{i}. {league.get('organization_name')}")
        print(f"   Sport/Season Code: {league.get('sport_season_code')}")
        print(f"   Day of Week: {league.get('day_of_week')}")
        print(f"   Start Time: {league.get('start_time')}")
        print(f"   Venue: {league.get('venue_name')}")
        print(f"   Team Fee: ${league.get('team_fee')}")
        print(f"   Individual Fee: ${league.get('individual_fee')}")
        print(f"   Gender Eligibility: {league.get('gender_eligibility')}")
        print(f"   Competition Level: {league.get('source_comp_level')}")
        print(f"   Season Dates: {league.get('season_start_date')} to {league.get('season_end_date')}")
        print(f"   Completeness: {league.get('identifying_fields_pct')}% ({league.get('completeness_status')})")

    print("\n" + "=" * 80)
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
