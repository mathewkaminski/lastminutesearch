"""Core venue enrichment orchestrator."""

import logging
from src.enrichers.places_client import PlacesClient, PlacesAPIError
from src.enrichers.confidence_scorer import score as confidence_score, AUTO_SAVE_THRESHOLD
from src.database.venue_store import VenueStore

logger = logging.getLogger(__name__)


class VenueEnricher:
    def __init__(self, places_client: PlacesClient, venue_store: VenueStore):
        self.places = places_client
        self.store = venue_store

    def run(self, progress_callback=None) -> dict:
        """Enrich all unenriched (venue_name, city) pairs.

        Args:
            progress_callback: Optional callable(current_index, total) for UI progress.

        Returns:
            Summary dict: {auto_saved, queued_review, failed}
        """
        names = self.store.get_unenriched_venue_names()
        auto_saved = 0
        queued_review = 0
        failed = 0

        for i, venue_name in enumerate(names):
            if progress_callback:
                progress_callback(i, len(names))

            outcome = self._process_venue(venue_name)
            if outcome == "auto_saved":
                auto_saved += 1
            elif outcome == "queued":
                queued_review += 1
            else:
                failed += 1

        logger.info(
            f"Enrichment complete: {auto_saved} auto-saved, "
            f"{queued_review} queued for review, {failed} failed"
        )
        return {"auto_saved": auto_saved, "queued_review": queued_review, "failed": failed}

    def _process_venue(self, venue_name: str) -> str:
        """Process one venue_name. Returns 'auto_saved', 'queued', or 'failed'."""
        try:
            api_result = self.places.search(venue_name)
        except PlacesAPIError as e:
            logger.error(f"Places API error for '{venue_name}': {e}")
            return "failed"

        if api_result is None:
            logger.debug(f"No Places result for '{venue_name}'")
            return "failed"

        conf = confidence_score(venue_name, None, api_result)

        venue_id = self.store.save_venue(
            venue_name=venue_name,
            google_name=api_result.get("name"),
            address=api_result["formatted_address"],
            lat=api_result["lat"],
            lng=api_result["lng"],
            google_place_id=api_result["place_id"],
            confidence_score=conf,
            raw_api_response=api_result["raw"],
        )

        if conf >= AUTO_SAVE_THRESHOLD:
            self.store.link_leagues(venue_id, venue_name)
            return "auto_saved"

        return "queued"
