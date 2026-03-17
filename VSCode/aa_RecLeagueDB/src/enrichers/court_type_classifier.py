"""Haiku-based court type classifier for venues."""

import json
import logging

logger = logging.getLogger(__name__)

BROAD_TYPES = {"Indoor", "Outdoor", "Beach", "Ice", "Pool", "Unknown"}
SPECIFIC_TYPES = {
    "Gym/Rec Centre", "Turf Field", "Grass Field", "Beach",
    "Ice Rink", "Tennis-Pickleball", "Baseball Diamond", "Swimming Pool", "Other",
}

_PROMPT = """\
Classify this sports venue by court/facility type.

Venue name: {venue_name}
Google name: {google_name}
Address: {address}

Return ONLY valid JSON with these exact keys:
{{
  "broad": one of ["Indoor", "Outdoor", "Beach", "Ice", "Pool", "Unknown"],
  "broad_conf": integer 0-100,
  "specific": one of ["Gym/Rec Centre", "Turf Field", "Grass Field", "Beach", "Ice Rink", "Tennis-Pickleball", "Baseball Diamond", "Swimming Pool", "Other"],
  "specific_conf": integer 0-100
}}

Use confidence 0 if you cannot determine the type."""


class CourtTypeError(Exception):
    pass


class CourtTypeClassifier:
    MODEL = "claude-haiku-4-5-20251001"

    def __init__(self, client):
        """Args:
            client: anthropic.Anthropic instance.
        """
        self.client = client

    def classify(
        self,
        venue_name: str,
        google_name: str | None,
        address: str | None,
    ) -> dict:
        """Classify a venue into broad and specific court types.

        Returns:
            dict with keys: broad, broad_conf, specific, specific_conf

        Raises:
            CourtTypeError: on API failure or unparseable response.
        """
        prompt = _PROMPT.format(
            venue_name=venue_name,
            google_name=google_name or venue_name,
            address=address or "unknown",
        )
        try:
            response = self.client.messages.create(
                model=self.MODEL,
                max_tokens=128,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()
        except Exception as e:
            raise CourtTypeError(f"Haiku API error for '{venue_name}': {e}") from e

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise CourtTypeError(f"Unparseable response for '{venue_name}': {raw!r}") from e

        # Validate enums; fall back to Unknown/Other if invalid
        if data.get("broad") not in BROAD_TYPES:
            logger.warning(f"Invalid broad type '{data.get('broad')}' for '{venue_name}', defaulting to Unknown")
            data["broad"] = "Unknown"
            data["broad_conf"] = 0
        if data.get("specific") not in SPECIFIC_TYPES:
            logger.warning(f"Invalid specific type '{data.get('specific')}' for '{venue_name}', defaulting to Other")
            data["specific"] = "Other"
            data["specific_conf"] = 0

        return {
            "broad": data["broad"],
            "broad_conf": int(data.get("broad_conf", 0)),
            "specific": data["specific"],
            "specific_conf": int(data.get("specific_conf", 0)),
        }
