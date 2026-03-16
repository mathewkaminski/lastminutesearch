"""HTML pre-processor for improving LLM extraction with structured data hints."""

from dataclasses import dataclass
from typing import List, Optional
import re
from bs4 import BeautifulSoup
from loguru import logger


# ============================================================================
# PageTypeIdentifier: Identify what kind of page we're looking at
# ============================================================================


@dataclass
class PageTypeResult:
    """Result of page type identification."""

    page_type: str  # "registration" | "schedule" | "standings" | "league_list" | "other"
    confidence: float  # 0.0-1.0
    reasoning: str


class PageTypeIdentifier:
    """Identifies page type using URL patterns + HTML structure.

    Inspired by content_page_identifier.py from example scrapers.
    """

    # URL patterns for different page types
    REGISTRATION_PATTERNS = [
        r"/register",
        r"/registration",
        r"/signup",
        r"/sign-up",
        r"/join",
        r"/enroll",
    ]

    SCHEDULE_PATTERNS = [
        r"/schedule",
        r"/schedules",
        r"/matches",
        r"/games",
        r"/fixtures",
    ]

    STANDINGS_PATTERNS = [
        r"/standings",
        r"/rankings",
        r"/points",
        r"/leaderboard",
        r"/results",
    ]

    # HTML keywords for content-based detection
    REGISTRATION_KEYWORDS = ["register", "sign up", "join", "enroll", "fee", "pricing", "cost", "register now"]
    SCHEDULE_KEYWORDS = ["schedule", "game", "match", "vs", "versus", "date", "time", "venue", "fixture"]
    STANDINGS_KEYWORDS = ["standing", "rank", "points", "wins", "losses", "gf", "ga", "draw"]

    def identify(self, url: str, html: str) -> PageTypeResult:
        """Identify page type using URL + HTML analysis.

        Args:
            url: Page URL
            html: HTML content

        Returns:
            PageTypeResult with page type, confidence, and reasoning
        """
        logger.debug(f"Identifying page type for: {url[:50]}...")

        # 1. Check URL patterns (fast, reliable)
        url_lower = url.lower()

        for pattern in self.REGISTRATION_PATTERNS:
            if re.search(pattern, url_lower):
                logger.debug(f"  → registration (URL pattern: {pattern})")
                return PageTypeResult(
                    page_type="registration",
                    confidence=0.85,
                    reasoning=f"URL matches registration pattern: {pattern}",
                )

        for pattern in self.SCHEDULE_PATTERNS:
            if re.search(pattern, url_lower):
                logger.debug(f"  → schedule (URL pattern: {pattern})")
                return PageTypeResult(
                    page_type="schedule",
                    confidence=0.85,
                    reasoning=f"URL matches schedule pattern: {pattern}",
                )

        for pattern in self.STANDINGS_PATTERNS:
            if re.search(pattern, url_lower):
                logger.debug(f"  → standings (URL pattern: {pattern})")
                return PageTypeResult(
                    page_type="standings",
                    confidence=0.85,
                    reasoning=f"URL matches standings pattern: {pattern}",
                )

        # 2. Fallback: Check HTML keywords
        try:
            soup = BeautifulSoup(html, "lxml")
            text = soup.get_text().lower()
        except Exception as e:
            logger.warning(f"Failed to parse HTML for page type detection: {e}")
            return PageTypeResult("other", 0.3, "HTML parse error")

        registration_count = sum(1 for kw in self.REGISTRATION_KEYWORDS if kw in text)
        schedule_count = sum(1 for kw in self.SCHEDULE_KEYWORDS if kw in text)
        standings_count = sum(1 for kw in self.STANDINGS_KEYWORDS if kw in text)

        max_count = max(registration_count, schedule_count, standings_count)

        if max_count >= 3:
            if registration_count == max_count:
                logger.debug(f"  → registration ({registration_count} keywords)")
                return PageTypeResult("registration", 0.70, f"{registration_count} registration keywords")
            elif schedule_count == max_count:
                logger.debug(f"  → schedule ({schedule_count} keywords)")
                return PageTypeResult("schedule", 0.70, f"{schedule_count} schedule keywords")
            elif standings_count == max_count:
                logger.debug(f"  → standings ({standings_count} keywords)")
                return PageTypeResult("standings", 0.70, f"{standings_count} standings keywords")

        # Default: other
        logger.debug("  → other (no specific patterns detected)")
        return PageTypeResult("other", 0.3, "No specific page type detected")


# ============================================================================
# KeywordScorer: Find and score elements containing pricing/team count data
# ============================================================================


@dataclass
class ScoredElement:
    """An HTML element with score and metadata."""

    text: str  # Element text content
    element_type: str  # "table", "tr", "div", "span", etc.
    keyword: str  # Which keyword matched
    score: float  # Combined score
    html_snippet: str  # First 500 chars of raw HTML


class KeywordScorer:
    """Scores HTML elements containing pricing/team count keywords.

    Inspired by keyword_link_extractor.py from example scrapers.
    """

    # Keyword weights (specificity/importance)
    KEYWORD_WEIGHTS = {
        # Pricing keywords (higher = more specific)
        "team fee": 1.2,
        "registration fee": 1.2,
        "individual fee": 1.1,
        "fee": 1.0,
        "price": 1.0,
        "cost": 0.9,
        "$": 0.8,
        # Team count keywords
        "team count": 1.2,
        "teams": 1.0,
        "divisions": 0.9,
        "spots left": 1.1,
        "openings": 0.9,
        "capacity": 0.8,
        # Venue keywords
        "venue": 1.0,
        "location": 0.9,
        "address": 0.8,
    }

    # Element type weights (structure matters)
    ELEMENT_WEIGHTS = {
        "table": 1.0,  # Tables are best for structured data
        "tr": 0.9,
        "td": 0.8,
        "th": 0.9,
        "div": 0.6,
        "span": 0.5,
        "p": 0.4,
    }

    def score_elements(self, html: str) -> List[ScoredElement]:
        """Find and score all elements containing target keywords.

        Args:
            html: HTML content

        Returns:
            List of ScoredElement sorted by score (highest first)
        """
        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception as e:
            logger.warning(f"Failed to parse HTML for keyword scoring: {e}")
            return []

        scored = []

        # Search all relevant elements
        for element in soup.find_all(["table", "tr", "td", "th", "div", "span", "p"]):
            text = element.get_text(strip=True)
            if not text or len(text) < 5:
                continue

            text_lower = text.lower()

            # Check for keyword matches
            for keyword, keyword_weight in self.KEYWORD_WEIGHTS.items():
                if keyword in text_lower:
                    element_weight = self.ELEMENT_WEIGHTS.get(element.name, 0.3)
                    score = keyword_weight * element_weight

                    scored.append(
                        ScoredElement(
                            text=text[:200],  # Truncate
                            element_type=element.name,
                            keyword=keyword,
                            score=score,
                            html_snippet=str(element)[:500],
                        )
                    )
                    break  # Only count first matching keyword per element

        # Sort by score descending
        scored.sort(key=lambda x: x.score, reverse=True)

        logger.debug(f"Scored {len(scored)} elements, top 20 returned")
        return scored[:20]  # Return top 20


# ============================================================================
# StructuredDataExtractor: Extract tables, pricing, team counts
# ============================================================================


@dataclass
class ExtractedTable:
    """A table extracted from HTML."""

    headers: List[str]
    rows: List[List[str]]
    source_html: str


@dataclass
class PricingElement:
    """Extracted pricing information."""

    type: str  # "team_fee" | "individual_fee" | "unknown"
    value: Optional[float]
    raw_text: str
    source: str  # CSS selector or description


@dataclass
class TeamCountHint:
    """Hint about team count from HTML."""

    source: str  # "standings_table" | "text_mention"
    count: int
    confidence: float


@dataclass
class LeagueListHint:
    """Hint that a table contains a list of leagues (each row = one league)."""

    table_index: int  # Which table in extracted_tables list
    headers: List[str]
    leagues: List[dict]  # Each row parsed as a league dict
    confidence: float  # 0.0-1.0
    source: str  # "table_row_pattern"


class StructuredDataExtractor:
    """Extracts structured data from HTML (tables, pricing, team counts)."""

    def extract_tables(self, html: str) -> List[ExtractedTable]:
        """Extract all tables from HTML, including deeply nested ones.

        Args:
            html: HTML content

        Returns:
            List of ExtractedTable objects
        """
        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception as e:
            logger.warning(f"Failed to parse HTML for table extraction: {e}")
            return []

        tables = []

        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            if not rows:
                continue

            # Extract headers (try thead first, then first tr if it has <th> tags)
            headers = []
            thead = table.find("thead")
            if thead:
                header_row = thead.find("tr")
                if header_row:
                    headers = [th.get_text(strip=True) for th in header_row.find_all(["th", "td"])]

            # If no thead, try first tr only if it has <th> tags
            if not headers and rows:
                first_row = rows[0]
                # Only treat as header if it contains <th> tags (not just <td>)
                th_cells = first_row.find_all("th")
                if th_cells:
                    headers = [cell.get_text(strip=True) for cell in th_cells]

            # Extract data rows (skip header row if detected)
            data_rows = []
            start_index = 1 if headers else 0

            # Also check for tbody
            tbody = table.find("tbody")
            if tbody:
                rows = tbody.find_all("tr")
                start_index = 0  # tbody rows are already data rows

            for row in rows[start_index:]:
                cells = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
                if cells and any(cell for cell in cells):  # At least one non-empty cell
                    data_rows.append(cells)

            if data_rows:
                tables.append(
                    ExtractedTable(
                        headers=headers,
                        rows=data_rows,
                        source_html=str(table)[:1000],
                    )
                )

        logger.debug(f"Extracted {len(tables)} tables")
        return tables

    def extract_pricing(self, html: str, scored_elements: List[ScoredElement]) -> List[PricingElement]:
        """Extract pricing information from scored elements.

        Args:
            html: HTML content (for additional context)
            scored_elements: Pre-scored elements from KeywordScorer

        Returns:
            List of PricingElement objects
        """
        pricing = []
        price_pattern = r"\$?\s*(\d+(?:,\d{3})*(?:\.\d{2})?)"

        for element in scored_elements:
            if element.keyword in [
                "fee",
                "price",
                "cost",
                "registration fee",
                "team fee",
                "individual fee",
                "$",
            ]:
                # Try to extract numeric value
                matches = re.findall(price_pattern, element.text)
                for match in matches:
                    try:
                        value = float(match.replace(",", ""))

                        # Determine type based on context
                        if "team" in element.text.lower():
                            pricing_type = "team_fee"
                        elif "individual" in element.text.lower() or "player" in element.text.lower():
                            pricing_type = "individual_fee"
                        else:
                            pricing_type = "unknown"

                        pricing.append(
                            PricingElement(
                                type=pricing_type,
                                value=value,
                                raw_text=element.text,
                                source=f"{element.element_type}.{element.keyword}",
                            )
                        )
                    except ValueError:
                        continue

        logger.debug(f"Extracted {len(pricing)} pricing elements")
        return pricing

    def extract_team_counts(self, html: str) -> List[TeamCountHint]:
        """Extract team count hints from HTML.

        Uses two strategies:
        1. Count rows in standings/ranking tables
        2. Look for "X teams" text patterns

        Args:
            html: HTML content

        Returns:
            List of TeamCountHint objects
        """
        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception as e:
            logger.warning(f"Failed to parse HTML for team count extraction: {e}")
            return []

        hints = []

        # Strategy 1: Count rows in standings tables
        for table in soup.find_all("table"):
            table_text = table.get_text().lower()
            if any(kw in table_text for kw in ["standing", "rank", "team", "division"]):
                rows = table.find_all("tr")
                if len(rows) > 1:  # Exclude header
                    team_count = len(rows) - 1
                    if 1 <= team_count <= 50:  # Reasonable range
                        hints.append(
                            TeamCountHint(
                                source="standings_table",
                                count=team_count,
                                confidence=0.85,
                            )
                        )

        # Strategy 2: Look for "X teams" or "X spots left" text
        text = soup.get_text()
        team_pattern = r"(\d+)\s*(?:teams?|divisions?|spots?|openings?)"
        matches = re.findall(team_pattern, text, re.IGNORECASE)
        for match in matches:
            try:
                count = int(match)
                if 1 <= count <= 50:  # Reasonable range
                    hints.append(
                        TeamCountHint(
                            source="text_mention",
                            count=count,
                            confidence=0.70,
                        )
                    )
            except ValueError:
                continue

        logger.debug(f"Extracted {len(hints)} team count hints")
        return hints

    def extract_league_lists(self, extracted_tables: List[ExtractedTable]) -> List[LeagueListHint]:
        """Detect if any tables represent league lists (each row = one league).

        A table is a "league list" if it has columns for:
        - Scheduling info (day, time, date)
        - Venue/location
        - Pricing (team fee, individual fee, or cost)
        - League details (format, division, level)

        Args:
            extracted_tables: Tables extracted from HTML

        Returns:
            List of LeagueListHint objects
        """
        league_lists = []

        # Keywords that indicate league list columns
        SCHEDULE_KEYWORDS = ["day", "time", "date", "when", "schedule", "start"]
        VENUE_KEYWORDS = ["venue", "location", "gym", "field", "park", "address", "where"]
        PRICING_KEYWORDS = ["fee", "price", "cost", "team", "individual", "player"]
        LEAGUE_KEYWORDS = ["division", "format", "level", "league", "type", "coed", "mens", "womens"]

        for idx, table in enumerate(extracted_tables):
            if not table.headers or len(table.rows) < 2:
                continue

            # Count header matches
            headers_lower = [h.lower() for h in table.headers]

            schedule_match = any(kw in h for h in headers_lower for kw in SCHEDULE_KEYWORDS)
            venue_match = any(kw in h for h in headers_lower for kw in VENUE_KEYWORDS)
            pricing_match = any(kw in h for h in headers_lower for kw in PRICING_KEYWORDS)
            league_match = any(kw in h for h in headers_lower for kw in LEAGUE_KEYWORDS)

            # Need at least 2 of these categories to consider it a league list
            match_count = sum([schedule_match, venue_match, pricing_match, league_match])

            if match_count >= 2:
                # This looks like a league list!
                confidence = min(0.5 + (match_count * 0.15), 0.95)

                # Parse each row as a league
                leagues = []
                for row in table.rows:
                    league_dict = {}
                    for header, cell in zip(table.headers, row):
                        league_dict[header] = cell
                    leagues.append(league_dict)

                league_lists.append(
                    LeagueListHint(
                        table_index=idx,
                        headers=table.headers,
                        leagues=leagues,
                        confidence=confidence,
                        source="table_row_pattern",
                    )
                )

                logger.info(f"Detected league list table with {len(leagues)} leagues (confidence: {confidence:.2f})")

        return league_lists


# ============================================================================
# Orchestrator: Tie it all together
# ============================================================================


@dataclass
class HtmlPreprocessingResult:
    """Complete result of HTML pre-processing."""

    page_type: str
    page_confidence: float
    extracted_tables: List[ExtractedTable]
    pricing_elements: List[PricingElement]
    team_count_hints: List[TeamCountHint]
    top_scored_elements: List[ScoredElement]
    league_list_hints: List[LeagueListHint]


class HtmlPreProcessor:
    """Orchestrates all pre-processing components.

    Combines PageTypeIdentifier, KeywordScorer, and StructuredDataExtractor
    to provide GPT-4 with high-quality structured hints before extraction.
    """

    def __init__(self):
        """Initialize components."""
        self.page_identifier = PageTypeIdentifier()
        self.keyword_scorer = KeywordScorer()
        self.data_extractor = StructuredDataExtractor()

    def preprocess(self, url: str, html: str) -> HtmlPreprocessingResult:
        """Pre-process HTML to extract structured hints.

        Args:
            url: Page URL
            html: HTML content

        Returns:
            HtmlPreprocessingResult with all extracted hints
        """
        logger.info(f"Pre-processing HTML from: {url[:50]}...")

        # Step 1: Identify page type
        page_type_result = self.page_identifier.identify(url, html)
        logger.debug(f"Page type: {page_type_result.page_type} (confidence: {page_type_result.confidence})")

        # Step 2: Score elements by keywords
        scored_elements = self.keyword_scorer.score_elements(html)
        logger.debug(f"Scored {len(scored_elements)} elements")

        # Step 3: Extract structured data
        extracted_tables = self.data_extractor.extract_tables(html)
        pricing_elements = self.data_extractor.extract_pricing(html, scored_elements)
        team_count_hints = self.data_extractor.extract_team_counts(html)

        # Step 4: Detect league lists
        league_list_hints = self.data_extractor.extract_league_lists(extracted_tables)

        logger.info(
            f"Pre-processing complete: {page_type_result.page_type}, "
            f"{len(extracted_tables)} tables, "
            f"{len(pricing_elements)} pricing hints, "
            f"{len(team_count_hints)} team count hints, "
            f"{len(league_list_hints)} league lists"
        )

        return HtmlPreprocessingResult(
            page_type=page_type_result.page_type,
            page_confidence=page_type_result.confidence,
            extracted_tables=extracted_tables,
            pricing_elements=pricing_elements,
            team_count_hints=team_count_hints,
            top_scored_elements=scored_elements,
            league_list_hints=league_list_hints,
        )

    def to_context_dict(self, result: HtmlPreprocessingResult) -> dict:
        """Convert preprocessing result to a dictionary suitable for GPT-4 prompt context.

        Args:
            result: HtmlPreprocessingResult

        Returns:
            Dictionary with structured context for GPT-4
        """
        return {
            "page_type": result.page_type,
            "page_confidence": result.page_confidence,
            "extracted_tables": [
                {
                    "headers": table.headers,
                    "rows": table.rows[:5],  # First 5 rows only
                }
                for table in result.extracted_tables[:3]  # Top 3 tables
            ],
            "pricing_hints": [
                {
                    "type": p.type,
                    "value": p.value,
                    "source": p.source,
                }
                for p in result.pricing_elements
            ],
            "team_count_hints": [
                {
                    "source": h.source,
                    "count": h.count,
                    "confidence": h.confidence,
                }
                for h in result.team_count_hints
            ],
            "league_list_hints": [
                {
                    "headers": ll.headers,
                    "num_leagues": len(ll.leagues),
                    "leagues": ll.leagues,
                    "confidence": ll.confidence,
                    "source": ll.source,
                }
                for ll in result.league_list_hints
            ],
        }
