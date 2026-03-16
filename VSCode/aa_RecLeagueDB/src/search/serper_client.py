"""Serper API client for executing Google searches.

This module provides a thin wrapper around the Serper API to execute
searches and normalize results to our internal format.
"""

import requests
import time
import logging
from typing import List, Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class SerperAPIError(Exception):
    """Raised when Serper API returns an error."""
    pass


class SerperClient:
    """Client for executing searches via Serper API.

    Serper provides Google search results in JSON format.
    This class handles API calls, retries, and response normalization.

    Attributes:
        api_key: Serper API key
        base_url: Serper API endpoint
        num_results: Number of results to return per query (default: 10)
        retry_attempts: Number of retry attempts on failure (default: 3)
        retry_backoff: Exponential backoff multiplier for retries (default: 1.5)
    """

    def __init__(
        self,
        api_key: str,
        num_results: int = 10,
        retry_attempts: int = 3,
        retry_backoff: float = 1.5
    ):
        """Initialize Serper client.

        Args:
            api_key: Serper API key from environment
            num_results: Results per query (1-100)
            retry_attempts: Number of retry attempts
            retry_backoff: Exponential backoff multiplier
        """
        if not api_key:
            raise ValueError("Serper API key is required")

        self.api_key = api_key
        self.base_url = "https://google.serper.dev/search"
        self.num_results = min(100, max(1, num_results))
        self.retry_attempts = retry_attempts
        self.retry_backoff = retry_backoff

        logger.info(f"SerperClient initialized (results_per_query={self.num_results})")

    def search(self, query: str) -> List[Dict]:
        """Execute a Google search via Serper API.

        Args:
            query: Search query string (e.g., "Toronto summer soccer league")

        Returns:
            List of normalized search results with keys:
            - url_raw: Original URL from search result
            - page_title: Title of the page
            - page_snippet: Description/snippet from search result
            - search_rank: 1-indexed position in results (1, 2, 3, ...)

        Raises:
            SerperAPIError: If search fails after all retries

        Examples:
            >>> client = SerperClient("your_api_key")
            >>> results = client.search("Toronto soccer league")
            >>> print(f"Found {len(results)} results")
            >>> print(results[0]['url_raw'])
        """
        for attempt in range(self.retry_attempts):
            try:
                logger.debug(f"Executing search (attempt {attempt + 1}/{self.retry_attempts}): {query}")

                response = requests.post(
                    self.base_url,
                    headers=self._get_headers(),
                    json={"q": query, "num": self.num_results},
                    timeout=10
                )

                response.raise_for_status()

                data = response.json()
                results = self._normalize_results(data, query)

                logger.info(f"Search succeeded: {query} ({len(results)} results)")
                return results

            except requests.exceptions.RequestException as e:
                logger.warning(
                    f"Search attempt {attempt + 1} failed: {str(e)}. "
                    f"Query: {query}"
                )

                if attempt < self.retry_attempts - 1:
                    # Calculate backoff time: 1s, 1.5s, 2.25s, etc.
                    backoff_time = self.retry_backoff ** attempt
                    logger.debug(f"Retrying in {backoff_time:.1f} seconds...")
                    time.sleep(backoff_time)
                else:
                    # All retries exhausted
                    error_msg = f"Serper search failed after {self.retry_attempts} attempts: {str(e)}"
                    logger.error(error_msg)
                    raise SerperAPIError(error_msg) from e

        # Should not reach here, but just in case
        raise SerperAPIError(f"Unexpected error executing search: {query}")

    def _get_headers(self) -> Dict[str, str]:
        """Get HTTP headers for API request.

        Returns:
            Dictionary of headers with API key and content type
        """
        return {
            "X-API-KEY": self.api_key,
            "Content-Type": "application/json"
        }

    def _normalize_results(self, api_response: Dict, query: str) -> List[Dict]:
        """Normalize Serper API response to internal format.

        Serper returns results under the 'organic' key with 'position' field.
        We normalize this to our standard format with 'search_rank' (1-indexed).

        Args:
            api_response: Raw response from Serper API
            query: Original query string (for logging)

        Returns:
            List of normalized result dictionaries

        Raises:
            SerperAPIError: If response structure is unexpected
        """
        try:
            results = []

            # Extract organic search results from API response
            organic_results = api_response.get("organic", [])

            if not organic_results:
                logger.debug(f"No organic results in API response for query: {query}")
                return results

            for result in organic_results:
                try:
                    normalized = self._normalize_result(result)
                    results.append(normalized)
                except ValueError as e:
                    logger.warning(f"Skipping malformed result: {e}")
                    continue

            logger.debug(f"Normalized {len(results)} results from API response")
            return results

        except Exception as e:
            error_msg = f"Failed to normalize Serper API response: {str(e)}"
            logger.error(error_msg)
            raise SerperAPIError(error_msg) from e

    def _normalize_result(self, result: Dict) -> Dict:
        """Normalize a single Serper result to internal format.

        Args:
            result: Single result dict from Serper API organic results

        Returns:
            Normalized result with standard keys

        Raises:
            ValueError: If required fields are missing
        """
        # Extract required fields
        url_raw = result.get("link")
        if not url_raw:
            raise ValueError("Result missing 'link' field")

        position = result.get("position")
        if position is None:
            raise ValueError("Result missing 'position' field")

        # Convert 0-indexed position to 1-indexed search_rank
        search_rank = position + 1

        # Extract optional fields
        page_title = result.get("title", "")
        page_snippet = result.get("snippet", "")

        return {
            "url_raw": url_raw,
            "page_title": page_title,
            "page_snippet": page_snippet,
            "search_rank": search_rank
        }
