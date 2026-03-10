"""Minimal Firecrawl API wrapper for fetching page content as markdown."""
from __future__ import annotations

import logging
import requests

logger = logging.getLogger(__name__)

FIRECRAWL_API_URL = "https://api.firecrawl.dev/v1/scrape"


class FirecrawlClient:
    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("api_key must be a non-empty string")
        self._api_key = api_key

    def scrape(self, url: str) -> str:
        """Fetch a URL via Firecrawl and return its content as markdown."""
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {"url": url, "formats": ["markdown"]}

        try:
            response = requests.post(
                FIRECRAWL_API_URL,
                headers=headers,
                json=payload,
                timeout=30,
            )
            response.raise_for_status()
        except Exception as exc:
            raise RuntimeError(f"Firecrawl request failed for {url}: {exc}") from exc

        body = response.json()
        if not body.get("success"):
            raise RuntimeError(
                f"Firecrawl returned no markdown for {url}: {body.get('error', 'unknown error')}"
            )

        markdown = body.get("data", {}).get("markdown", "")
        if not markdown:
            raise RuntimeError(f"Firecrawl returned no markdown for {url}")

        logger.info("Firecrawl fetched %d chars for %s", len(markdown), url)
        return markdown
