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
    REVIEW_THRESHOLD = 60

    def __init__(self, client):
        """Args:
            client: Supabase client instance from get_client().
        """
        self.client = client

    def save_venue(
        self,
        venue_name: str,
        google_name: str | None,
        address: str | None,
        lat: float | None,
        lng: float | None,
        google_place_id: str | None,
        confidence_score: int,
        raw_api_response: dict,
    ) -> str:
        """Insert or update a venue record. Returns venue_id.

        Looks up by venue_name first to avoid hitting the idx_venues_name
        unique constraint when re-enriching venues. City is derived from
        the Google Places address, not the campaign city.
        """
        province = self._extract_province(address)
        city = self._extract_city(address)
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
            .limit(1)
            .execute()
        )

        if existing.data:
            venue_id = existing.data[0]["venue_id"]
            # If google_place_id belongs to a different row, don't overwrite it
            if google_place_id:
                by_place = (
                    self.client.table("venues")
                    .select("venue_id")
                    .eq("google_place_id", google_place_id)
                    .limit(1)
                    .execute()
                )
                if by_place.data and by_place.data[0]["venue_id"] != venue_id:
                    data.pop("google_place_id", None)
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

    @staticmethod
    def _extract_city(address: str | None) -> str | None:
        """Extract city from a Google Places formatted address.

        Expects format like '123 Main St, Toronto, ON M5V 2T6, Canada'.
        City is the comma-separated segment immediately before the province.
        """
        if not address:
            return None
        m = _PROVINCE_RE.search(address)
        if not m:
            return None
        before = address[:m.start()]
        parts = [p.strip() for p in before.split(",")]
        return parts[-1] if parts else None

    def link_leagues(self, venue_id: str, venue_name: str) -> int:
        """Set venue_id on all leagues with matching venue_name (any city).

        Also aggregates distinct sports and days_of_week from linked leagues
        and writes them back to the venue record.
        """
        result = (
            self.client.table("leagues_metadata")
            .update({"venue_id": venue_id})
            .eq("venue_name", venue_name)
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

    def get_unenriched_venue_names(self) -> list[str]:
        """Return distinct venue_names not yet linked to a venue."""
        result = (
            self.client.table("leagues_metadata")
            .select("venue_name")
            .is_("venue_id", "null")
            .not_.is_("venue_name", "null")
            .execute()
        )
        seen = set()
        names = []
        for row in result.data:
            name = row["venue_name"]
            if name not in seen:
                seen.add(name)
                names.append(name)
        return names

    def get_enrichment_stats(self) -> dict:
        """Return counts for the Streamlit stats panel."""
        all_rows = (
            self.client.table("leagues_metadata")
            .select("venue_id, venue_name, city")
            .not_.is_("venue_name", "null")
            .execute()
        ).data

        total = len({r["venue_name"] for r in all_rows})
        enriched = len({r["venue_name"] for r in all_rows if r.get("venue_id")})

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

    def get_all_venues(self) -> list[dict]:
        """Return all venues ordered by city then venue_name."""
        result = (
            self.client.table("venues")
            .select(
                "venue_id, venue_name, google_name, city, province, address, "
                "confidence_score, manually_verified, sports, days_of_week"
            )
            .order("city")
            .order("venue_name")
            .execute()
        )
        return result.data

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

    def get_venues_for_classification(self) -> list[dict]:
        """Return enriched venues (has lat) that have not yet been classified."""
        result = (
            self.client.table("venues")
            .select("venue_id, venue_name, google_name, address")
            .not_.is_("lat", "null")
            .is_("court_type_broad", "null")
            .execute()
        )
        return result.data

    def save_court_type(
        self,
        venue_id: str,
        broad: str,
        broad_conf: int,
        specific: str,
        specific_conf: int,
    ) -> None:
        """Write court type classification result for a venue."""
        self.client.table("venues").update({
            "court_type_broad": broad,
            "court_type_broad_conf": broad_conf,
            "court_type_specific": specific,
            "court_type_specific_conf": specific_conf,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("venue_id", venue_id).execute()

    def get_enriched_venues(
        self,
        broad: str | None = None,
        specific: str | None = None,
        province: str | None = None,
        city: str | None = None,
        sport: str | None = None,
    ) -> list[dict]:
        """Return enriched venues (has lat/lng), optionally filtered."""
        query = (
            self.client.table("venues")
            .select(
                "venue_id, venue_name, google_name, city, province, address, "
                "confidence_score, manually_verified, sports, days_of_week, "
                "court_type_broad, court_type_broad_conf, "
                "court_type_specific, court_type_specific_conf"
            )
            .not_.is_("lat", "null")
        )
        if broad:
            query = query.eq("court_type_broad", broad)
        if specific:
            query = query.eq("court_type_specific", specific)
        if province:
            query = query.eq("province", province)
        if city:
            query = query.ilike("city", f"%{city}%")
        if sport:
            query = query.contains("sports", [sport])
        return query.order("city").order("venue_name").execute().data

    def get_league_stats_for_venues(self, venue_ids: list[str]) -> dict:
        """Aggregate league data from leagues_metadata for a list of venue_ids.

        Returns dict keyed by venue_id with:
            num_leagues, avg_team_fee, avg_individual_fee, hours (sorted list)
        """
        if not venue_ids:
            return {}
        result = (
            self.client.table("leagues_metadata")
            .select("venue_id, team_fee, individual_fee, start_time, day_of_week")
            .in_("venue_id", venue_ids)
            .execute()
        )
        stats: dict = {}
        for row in result.data:
            vid = row["venue_id"]
            if vid not in stats:
                stats[vid] = {
                    "num_leagues": 0,
                    "team_fees": [],
                    "individual_fees": [],
                    "hours": set(),
                }
            s = stats[vid]
            s["num_leagues"] += 1
            if row.get("team_fee") is not None:
                s["team_fees"].append(float(row["team_fee"]))
            if row.get("individual_fee") is not None:
                s["individual_fees"].append(float(row["individual_fee"]))
            if row.get("start_time"):
                s["hours"].add(row["start_time"])

        return {
            vid: {
                "num_leagues": s["num_leagues"],
                "avg_team_fee": round(sum(s["team_fees"]) / len(s["team_fees"]), 2) if s["team_fees"] else None,
                "avg_individual_fee": round(sum(s["individual_fees"]) / len(s["individual_fees"]), 2) if s["individual_fees"] else None,
                "hours": sorted(s["hours"]),
            }
            for vid, s in stats.items()
        }

    def update_google_name(self, venue_id: str, google_name: str | None) -> None:
        """Update the display label for a venue."""
        self.client.table("venues").update({
            "google_name": google_name,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("venue_id", venue_id).execute()

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
