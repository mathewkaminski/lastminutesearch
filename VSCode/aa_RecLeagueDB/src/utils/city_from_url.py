"""Extract city name from a URL's path segments.

Used to derive city for leagues scraped from multi-city orgs
(e.g. javelin.com/calgary/vball -> "Calgary").
"""
from __future__ import annotations
from urllib.parse import urlparse

# Canonical city names mapped from their lowercase URL-slug forms.
# Slug form handles hyphens (e.g. "north-york") and alternate spellings.
_CITY_SLUGS: dict[str, str] = {
    # Ontario
    "ottawa": "Ottawa",
    "toronto": "Toronto",
    "guelph": "Guelph",
    "hamilton": "Hamilton",
    "kitchener": "Kitchener",
    "waterloo": "Waterloo",
    "london": "London",
    "windsor": "Windsor",
    "kingston": "Kingston",
    "barrie": "Barrie",
    "sudbury": "Sudbury",
    "thunder-bay": "Thunder Bay",
    "thunderbay": "Thunder Bay",
    "mississauga": "Mississauga",
    "brampton": "Brampton",
    "markham": "Markham",
    "richmond-hill": "Richmond Hill",
    "richmondhill": "Richmond Hill",
    "vaughan": "Vaughan",
    "oakville": "Oakville",
    "burlington": "Burlington",
    "oshawa": "Oshawa",
    "north-york": "North York",
    "northyork": "North York",
    "scarborough": "Scarborough",
    "etobicoke": "Etobicoke",
    "pickering": "Pickering",
    "ajax": "Ajax",
    "whitby": "Whitby",
    "peterborough": "Peterborough",
    "cambridge": "Cambridge",
    "brantford": "Brantford",
    "st-catharines": "St. Catharines",
    "stcatharines": "St. Catharines",
    "niagara": "Niagara",
    "niagara-falls": "Niagara Falls",
    "niagarafalls": "Niagara Falls",
    # Alberta
    "calgary": "Calgary",
    "edmonton": "Edmonton",
    "red-deer": "Red Deer",
    "reddeer": "Red Deer",
    "lethbridge": "Lethbridge",
    "medicine-hat": "Medicine Hat",
    # BC
    "vancouver": "Vancouver",
    "victoria": "Victoria",
    "kelowna": "Kelowna",
    "burnaby": "Burnaby",
    "surrey": "Surrey",
    "richmond": "Richmond",
    "abbotsford": "Abbotsford",
    "coquitlam": "Coquitlam",
    # Quebec
    "montreal": "Montreal",
    "quebec": "Quebec City",
    "quebec-city": "Quebec City",
    "laval": "Laval",
    "longueuil": "Longueuil",
    # Manitoba
    "winnipeg": "Winnipeg",
    # Saskatchewan
    "regina": "Regina",
    "saskatoon": "Saskatoon",
    # Nova Scotia
    "halifax": "Halifax",
    # New Brunswick
    "moncton": "Moncton",
    "fredericton": "Fredericton",
    # US (common rec sports cities)
    "new-york": "New York",
    "newyork": "New York",
    "nyc": "New York",
    "chicago": "Chicago",
    "boston": "Boston",
    "seattle": "Seattle",
    "portland": "Portland",
    "denver": "Denver",
    "austin": "Austin",
    "dallas": "Dallas",
    "houston": "Houston",
    "phoenix": "Phoenix",
    "atlanta": "Atlanta",
    "miami": "Miami",
    "washington": "Washington",
    "dc": "Washington",
    "philadelphia": "Philadelphia",
    "minneapolis": "Minneapolis",
    "pittsburgh": "Pittsburgh",
    "cleveland": "Cleveland",
    "detroit": "Detroit",
    "san-francisco": "San Francisco",
    "sanfrancisco": "San Francisco",
    "los-angeles": "Los Angeles",
    "losangeles": "Los Angeles",
    "la": "Los Angeles",
    "san-diego": "San Diego",
    "sandiego": "San Diego",
}


def extract_city_from_url(url: str | None) -> str | None:
    """Return the first city name found in the URL path segments, or None.

    Checks each path segment (and the hostname) against a known-cities list.
    Handles hyphenated slugs (e.g. "north-york") and case-insensitive matching.

    Examples:
        "https://javelin.com/calgary/vball"      -> "Calgary"
        "https://javelin.com/ottawa/volleyball"  -> "Ottawa"
        "https://torontossc.com/leagues/spring"  -> None  (no city in path)
        "https://ottawavolleysixes.com"          -> None  (city in domain, not path)

    Args:
        url: A URL string, or None.

    Returns:
        Canonical city name string, or None if no city found in path.
    """
    if not url:
        return None

    try:
        parsed = urlparse(url if "://" in url else f"https://{url}")
        # Split path into segments, strip empty strings from leading/trailing slashes
        segments = [s.lower() for s in parsed.path.split("/") if s]
    except Exception:
        return None

    for segment in segments:
        if segment in _CITY_SLUGS:
            return _CITY_SLUGS[segment]

    return None
