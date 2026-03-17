"""Venue table read/write operations."""

import logging
import re
from datetime import datetime, timezone

from src.config.sss_codes import SPORT_CODES

_PROVINCE_RE = re.compile(
    r",\s*(AB|BC|MB|NB|NL|NS|NT|NU|ON|PE|QC|SK|YT)\s+"
)

logger = logging.getLogger(__name__)


class VenueStore:
    REVIEW_THRESHOLD = 75

    def __init__(self, client):
        """Args:
            client: Supabase client instance from get_client().
        """
        self.client = client

    def save_venue(
        self,
        venue_name: str,
        city: str,
        google_name: str | None,
        address: str | None,
        lat: float | None,
        lng: float | None,
        google_place_id: str | None,
        confidence_score: int,
        raw_api_response: dict,
    ) -> str:
        """Insert or update a venue record. Returns venue_id.

        Looks up by (venue_name, city) first to avoid hitting the
        idx_venues_name_city unique constraint when re-enriching unlinked venues
        that already have a row (e.g. previously queued for review).
        """
        province = self._extract_province(address)
        data = {
            "venue_name": venue_name,
            "city": city,
            "google_name": google_name,
            "province": province,
            "address": address,
            "lat": lat,
            "lng": lng,
            "google_place_id": google_place_id,
            "confidence_score": confidence_score,
            "raw_api_response": raw_api_response,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        existing = (
            self.client.table("venues")
            .select("venue_id")
            .ilike("venue_name", venue_name)
            .ilike("city", city)
            .limit(1)
            .execute()
        )

        if existing.data:
            venue_id = existing.data[0]["venue_id"]
            self.client.table("venues").update(data).eq("venue_id", venue_id).execute()
            return venue_id

        # Fallback: same google_place_id under a different name/city spelling
        if google_place_id:
            by_place = (
                self.client.table("venues")
                .select("venue_id")
                .eq("google_place_id", google_place_id)
                .limit(1)
                .execute()
            )
            if by_place.data:
                venue_id = by_place.data[0]["venue_id"]
                self.client.table("venues").update(data).eq("venue_id", venue_id).execute()
                return venue_id

        result = self.client.table("venues").insert(data).execute()
        return result.data[0]["venue_id"]

    @staticmethod
    def _extract_province(address: str | None) -> str | None:
        """Extract 2-letter Canadian province code from a formatted address."""
        if not address:
            return None
        m = _PROVINCE_RE.search(address)
        return m.group(1) if m else None

    def link_leagues(self, venue_id: str, venue_name: str, city: str) -> int:
        """Set venue_id on all leagues with matching venue_name + city.

        Also aggregates distinct sports and days_of_week from linked leagues
        and writes them back to the venue record.
        """
        result = (
            self.client.table("leagues_metadata")
            .update({"venue_id": venue_id})
            .eq("venue_name", venue_name)
            .eq("city", city)
            .execute()
        )
        linked = result.data or []

        # Aggregate sports (human-readable) and days from linked leagues
        sports = sorted({
            SPORT_CODES.get((r.get("sport_season_code") or "")[-2:], "")
            for r in linked
            if r.get("sport_season_code") and len(r["sport_season_code"]) == 3
        } - {""})

        days = sorted({
            r["day_of_week"] for r in linked
            if r.get("day_of_week")
        })

        if sports or days:
            self.client.table("venues").update({
                "sports": sports or None,
                "days_of_week": days or None,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("venue_id", venue_id).execute()

        return len(linked)

    def get_unenriched_pairs(self) -> list[tuple[str, str]]:
        """Return distinct (venue_name, city) pairs not yet linked to a venue."""
        result = (
            self.client.table("leagues_metadata")
            .select("venue_name, city")
            .is_("venue_id", "null")
            .not_.is_("venue_name", "null")
            .not_.is_("city", "null")
            .execute()
        )
        seen = set()
        pairs = []
        for row in result.data:
            key = (row["venue_name"], row["city"])
            if key not in seen:
                seen.add(key)
                pairs.append(key)
        return pairs

    def get_enrichment_stats(self) -> dict:
        """Return counts for the Streamlit stats panel."""
        all_rows = (
            self.client.table("leagues_metadata")
            .select("venue_id, venue_name, city")
            .not_.is_("venue_name", "null")
            .execute()
        ).data

        total = len({(r["venue_name"], r.get("city")) for r in all_rows})
        enriched = len({(r["venue_name"], r.get("city")) for r in all_rows if r.get("venue_id")})

        review_queue = (
            self.client.table("venues")
            .select("venue_id", count="exact")
            .eq("manually_verified", False)
            .lt("confidence_score", self.REVIEW_THRESHOLD)
            .execute()
        ).count or 0

        return {
            "total": total,
            "enriched": enriched,
            "pending": max(total - enriched, 0),
            "needs_review": review_queue,
        }

    def get_review_queue(self, limit: int = 50) -> list[dict]:
        """Return venues needing human review (low confidence, not verified)."""
        result = (
            self.client.table("venues")
            .select("*")
            .eq("manually_verified", False)
            .lt("confidence_score", self.REVIEW_THRESHOLD)
            .order("confidence_score", desc=False)
            .limit(limit)
            .execute()
        )
        return result.data

    def accept_venue(self, venue_id: str) -> None:
        """Mark a venue as manually verified."""
        self.client.table("venues").update(
            {"manually_verified": True, "updated_at": datetime.now(timezone.utc).isoformat()}
        ).eq("venue_id", venue_id).execute()

    def update_venue_address(
        self, venue_id: str, address: str, lat: float | None, lng: float | None
    ) -> None:
        """Correct a venue's address (used in Edit flow)."""
        payload = {
            "address": address,
            "manually_verified": True,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if lat is not None:
            payload["lat"] = lat
        if lng is not None:
            payload["lng"] = lng
        self.client.table("venues").update(payload).eq("venue_id", venue_id).execute()
