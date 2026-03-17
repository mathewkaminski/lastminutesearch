"""Orchestrates court type classification over all unclassified venues."""

import logging
from src.enrichers.court_type_classifier import CourtTypeClassifier, CourtTypeError
from src.database.venue_store import VenueStore

logger = logging.getLogger(__name__)


class CourtTypeEnricher:
    def __init__(self, classifier: CourtTypeClassifier, venue_store: VenueStore):
        self.classifier = classifier
        self.store = venue_store

    def run(self, progress_callback=None) -> dict:
        """Classify all enriched venues missing court_type_broad.

        Args:
            progress_callback: Optional callable(current_index, total).

        Returns:
            {classified: int, failed: int}
        """
        venues = self.store.get_venues_for_classification()
        classified = 0
        failed = 0

        for i, venue in enumerate(venues):
            if progress_callback:
                progress_callback(i, len(venues))
            try:
                result = self.classifier.classify(
                    venue_name=venue["venue_name"],
                    google_name=venue.get("google_name"),
                    address=venue.get("address"),
                )
                self.store.save_court_type(
                    venue_id=venue["venue_id"],
                    broad=result["broad"],
                    broad_conf=result["broad_conf"],
                    specific=result["specific"],
                    specific_conf=result["specific_conf"],
                )
                classified += 1
            except CourtTypeError as e:
                logger.error(f"Court type classification failed for '{venue['venue_name']}': {e}")
                failed += 1

        logger.info(f"Court type enrichment: {classified} classified, {failed} failed")
        return {"classified": classified, "failed": failed}
