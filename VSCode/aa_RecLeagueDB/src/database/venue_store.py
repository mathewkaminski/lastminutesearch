"""Venue table read/write operations."""

import logging
from datetime import datetime

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
        address: str | None,
        lat: float | None,
        lng: float | None,
        google_place_id: str | None,
        confidence_score: int,
        raw_api_response: dict,
    ) -> str:
        """Upsert a venue record. Returns venue_id."""
        data = {
            "venue_name": venue_name,
            "city": city,
            "address": address,
            "lat": lat,
            "lng": lng,
            "google_place_id": google_place_id,
            "confidence_score": confidence_score,
            "raw_api_response": raw_api_response,
            "updated_at": datetime.utcnow().isoformat(),
        }
        result = (
            self.client.table("venues")
            .upsert(data, on_conflict="google_place_id")
            .execute()
        )
        return result.data[0]["venue_id"]

    def link_leagues(self, venue_id: str, venue_name: str, city: str) -> int:
        """Set venue_id on all leagues with matching venue_name + city."""
        result = (
            self.client.table("leagues_metadata")
            .update({"venue_id": venue_id})
            .eq("venue_name", venue_name)
            .eq("city", city)
            .execute()
        )
        return len(result.data)

    def get_unenriched_pairs(self) -> list[tuple[str, str]]:
        """Return distinct (venue_name, city) pairs not yet linked to a venue."""
        result = (
            self.client.table("leagues_metadata")
            .select("venue_name, city")
            .is_("venue_id", "null")
            .not_()
            .is_("venue_name", "null")
            .execute()
        )
        seen = set()
        pairs = []
        for row in result.data:
            if not row.get("city"):
                continue
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
            {"manually_verified": True, "updated_at": datetime.utcnow().isoformat()}
        ).eq("venue_id", venue_id).execute()

    def update_venue_address(
        self, venue_id: str, address: str, lat: float | None, lng: float | None
    ) -> None:
        """Correct a venue's address (used in Edit flow)."""
        self.client.table("venues").update({
            "address": address,
            "lat": lat,
            "lng": lng,
            "manually_verified": True,
            "updated_at": datetime.utcnow().isoformat(),
        }).eq("venue_id", venue_id).execute()
