"""Google Places API client for venue address lookup."""

import logging
import time
import requests

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = {"ZERO_RESULTS", "NOT_FOUND"}
ERROR_STATUSES = {"REQUEST_DENIED", "INVALID_REQUEST", "OVER_QUERY_LIMIT", "UNKNOWN_ERROR"}


class PlacesAPIError(Exception):
    pass


class PlacesClient:
    BASE_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
    MAX_RETRIES = 3

    def __init__(self, api_key: str):
        self.api_key = api_key

    def search(self, venue_name: str, city: str | None = None) -> dict | None:
        """Search for a venue by name, optionally scoped to a city.

        Args:
            venue_name: Venue name from leagues_metadata.
            city: Optional city context (appended to query if provided).

        Returns:
            Normalized result dict, or None if no results found.

        Raises:
            PlacesAPIError: On API-level errors (bad key, quota exceeded).
        """
        query = f"{venue_name} {city}" if city else venue_name
        params = {"query": query, "key": self.api_key}

        for attempt in range(self.MAX_RETRIES):
            try:
                response = requests.get(self.BASE_URL, params=params, timeout=10)
                response.raise_for_status()
                data = response.json()
            except requests.RequestException as e:
                if attempt == self.MAX_RETRIES - 1:
                    raise PlacesAPIError(f"Request failed after {self.MAX_RETRIES} retries: {e}") from e
                wait = 2 ** attempt
                logger.warning(f"Places API request failed (attempt {attempt + 1}), retrying in {wait}s: {e}")
                time.sleep(wait)
                continue

            status = data.get("status")

            if status == "OK":
                return self._normalize(data["results"][0], data)

            if status in TERMINAL_STATUSES:
                logger.debug(f"No results for '{query}': {status}")
                return None

            if status in ERROR_STATUSES:
                raise PlacesAPIError(f"Places API error for '{query}': {status}")

            raise PlacesAPIError(f"Unexpected Places API status '{status}' for '{query}'")

        return None

    def _normalize(self, result: dict, raw_response: dict) -> dict:
        location = result.get("geometry", {}).get("location", {})
        return {
            "place_id": result.get("place_id"),
            "name": result.get("name"),
            "formatted_address": result.get("formatted_address"),
            "lat": location.get("lat"),
            "lng": location.get("lng"),
            "types": result.get("types", []),
            "user_ratings_total": result.get("user_ratings_total", 0),
            "raw": raw_response,
        }
