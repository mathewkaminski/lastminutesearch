"""HTML aggregator - combine multiple page HTMLs with smart token allocation."""

import logging
import re
from typing import Optional
from bs4 import BeautifulSoup
import tiktoken

logger = logging.getLogger(__name__)


class HtmlAggregator:
    """Aggregate and combine multiple HTML pages with token budgeting."""

    # Page type priorities for token allocation
    PAGE_PRIORITY = {
        "registration": 1,  # Highest priority
        "schedule": 2,
        "standings": 3,
        "specific_league": 4,
        "home": 5,  # Lowest priority
        "other": 6,
    }

    def __init__(self, max_tokens: int = 12000):
        """
        Initialize aggregator.

        Args:
            max_tokens: Total token budget (default 12000)
        """
        self.max_tokens = max_tokens
        self.enc = tiktoken.get_encoding("cl100k_base")  # GPT-4 encoding

    def aggregate_htmls(
        self,
        pages: dict[str, str],
        page_types: Optional[dict[str, str]] = None,
    ) -> str:
        """
        Aggregate multiple HTMLs into single text with section headers.

        Args:
            pages: Dict of {url: html}
            page_types: Optional dict of {url: page_type} from classifier

        Returns:
            Combined text with section headers
        """
        if not pages:
            return ""

        # Convert HTML to text for each page
        page_texts = {}
        for url, html in pages.items():
            text = self._html_to_text(html)
            if text.strip():
                page_texts[url] = text

        if not page_texts:
            return ""

        # Determine page order (by priority if types provided)
        if page_types:
            sorted_urls = sorted(
                page_texts.keys(),
                key=lambda u: (
                    self.PAGE_PRIORITY.get(page_types.get(u, "other"), 99),
                    u,
                ),
            )
        else:
            sorted_urls = list(page_texts.keys())

        # Allocate tokens and combine
        allocated = self._allocate_tokens(
            {u: page_texts[u] for u in sorted_urls},
            self.max_tokens,
        )

        # Build combined text with headers
        combined = []
        for url in sorted_urls:
            page_type = page_types.get(url, "other") if page_types else "other"
            text = allocated.get(url, "")
            if text.strip():
                header = self._format_header(url, page_type)
                combined.append(header)
                combined.append(text)
                combined.append("")  # Blank line separator

        result = "\n".join(combined)
        result_tokens = len(self.enc.encode(result))
        logger.info(
            f"Aggregated {len(pages)} pages into {result_tokens} tokens "
            f"(budget: {self.max_tokens})"
        )

        return result

    def _html_to_text(self, html: str) -> str:
        """Convert HTML to clean text."""
        try:
            soup = BeautifulSoup(html, "html.parser")

            # Remove script, style, footer elements
            for element in soup(["script", "style", "footer"]):
                element.decompose()

            # Remove copyright notices
            text = soup.get_text(separator=" ")
            lines = text.split("\n")
            filtered_lines = []
            for line in lines:
                line = line.strip()
                # Skip very short lines
                if len(line) < 3:
                    continue
                # Skip copyright/legal lines
                if re.search(r"copyright|©|all rights reserved|privacy|terms of service", line, re.IGNORECASE):
                    continue
                # Skip navigation spam
                if re.search(r"^(home|about|contact|login|search)$", line, re.IGNORECASE):
                    continue
                filtered_lines.append(line)

            # Clean up whitespace
            text = " ".join(filtered_lines)
            text = re.sub(r"\s+", " ", text)

            return text.strip()

        except Exception as e:
            logger.warning(f"Error converting HTML to text: {e}")
            return ""

    def _allocate_tokens(
        self,
        page_texts: dict[str, str],
        max_tokens: int,
    ) -> dict[str, str]:
        """
        Allocate token budget across pages.

        Dynamic allocation based on:
        1. Page type priority
        2. Actual content length
        3. Total token budget

        Args:
            page_texts: Dict of {url: text}
            max_tokens: Total budget

        Returns:
            Dict of {url: truncated_text}
        """
        if not page_texts:
            return {}

        # Calculate tokens per page
        page_tokens = {url: len(self.enc.encode(text)) for url, text in page_texts.items()}
        total_tokens = sum(page_tokens.values())

        logger.info(f"Total tokens before truncation: {total_tokens}")

        # If within budget, return as-is
        if total_tokens <= max_tokens:
            return page_texts

        # Otherwise, allocate proportionally
        allocated = {}
        remaining_budget = max_tokens

        for url, text in page_texts.items():
            page_token_count = page_tokens[url]
            proportion = page_token_count / total_tokens
            allocated_tokens = int(proportion * max_tokens)

            # Ensure minimum allocation
            allocated_tokens = max(100, allocated_tokens)

            # Truncate to allocation
            if allocated_tokens < page_token_count:
                truncated = self._truncate_text(text, allocated_tokens)
                allocated[url] = truncated
            else:
                allocated[url] = text

        return allocated

    def _truncate_text(self, text: str, max_tokens: int) -> str:
        """Truncate text to token limit."""
        tokens = self.enc.encode(text)
        if len(tokens) <= max_tokens:
            return text

        truncated_tokens = tokens[:max_tokens]
        truncated_text = self.enc.decode(truncated_tokens)

        return truncated_text.rstrip() + " [truncated]"

    def _format_header(self, url: str, page_type: str) -> str:
        """Format section header."""
        page_label = page_type.upper().replace("_", " ")
        return f"\n=== {page_label} ===\n"
