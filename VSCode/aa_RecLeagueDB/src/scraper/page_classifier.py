"""Page classifier - categorize pages by content type and URL patterns."""

import re
from typing import Literal
from urllib.parse import urlparse
from bs4 import BeautifulSoup


PageType = Literal["home", "schedule", "standings", "registration", "specific_league", "other"]


class PageClassifier:
    """Classify web pages into functional categories."""

    # URL patterns for each page type (regex patterns on pathname)
    URL_PATTERNS = {
        "registration": [
            r"(?:register|signup|sign-up|sign_up|registration|enroll|join|register-now)",
        ],
        "schedule": [
            r"(?:schedule|schedules|calendar|times|games|matches|fixtures|calendar)",
        ],
        "standings": [
            r"(?:standings|results|results|teams|roster|scores|leaderboard|ladder)",
        ],
        "specific_league": [
            r"(?:league|division|sport|tournament|competition|season)s?(?:/\d+)?",
        ],
        "home": [
            r"^/$|index|home|^$",
        ],
    }

    # Keywords for each page type (used for content analysis)
    KEYWORDS = {
        "registration": [
            "register",
            "sign up",
            "signup",
            "fee",
            "cost",
            "price",
            "deadline",
            "registration",
            "enroll",
            "join",
            "team registration",
        ],
        "schedule": [
            "schedule",
            "game time",
            "match",
            "day",
            "time",
            "when",
            "fixture",
            "calendar",
            "date",
            "kickoff",
            "start time",
        ],
        "standings": [
            "standings",
            "points",
            "wins",
            "losses",
            "teams",
            "results",
            "record",
            "ranking",
            "position",
            "leaderboard",
        ],
        "specific_league": [
            "league",
            "division",
            "level",
            "competitive",
            "recreational",
            "format",
            "rules",
            "tier",
            "bracket",
        ],
    }

    def classify_page(self, url: str, html: str) -> PageType:
        """
        Classify a page into one of six categories.

        Args:
            url: Full URL of the page
            html: HTML content of the page

        Returns:
            PageType: One of 'home', 'schedule', 'standings', 'registration', 'specific_league', 'other'
        """
        # Score each category
        scores = {
            "registration": 0,
            "schedule": 0,
            "standings": 0,
            "specific_league": 0,
            "home": 0,
        }

        # URL pattern matching (weight: 70 points max per category)
        pathname = urlparse(url).path.lower()
        scores.update(self._score_url_patterns(pathname))

        # Content keyword matching (weight: 30 points max per category)
        text = self._extract_text(html).lower()
        keyword_scores = self._score_keywords(text)
        for category, score in keyword_scores.items():
            scores[category] += score

        # Find category with highest score
        best_category = max(scores, key=scores.get)
        best_score = scores[best_category]

        # Return "other" if no clear winner (score < 20)
        if best_score < 20:
            return "other"

        # Heuristic: if it's the home page, return "home"
        if best_category == "home":
            return "home"

        return best_category  # type: ignore

    def _score_url_patterns(self, pathname: str) -> dict[str, int]:
        """Score URL patterns (0-70 points per category)."""
        scores = {key: 0 for key in self.URL_PATTERNS}

        for category, patterns in self.URL_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, pathname, re.IGNORECASE):
                    scores[category] += 70
                    break  # Only count once per category

        return scores

    def _score_keywords(self, text: str) -> dict[str, int]:
        """Score keyword density (0-30 points per category)."""
        scores = {key: 0 for key in self.KEYWORDS}

        for category, keywords in self.KEYWORDS.items():
            keyword_count = 0
            for keyword in keywords:
                keyword_count += len(re.findall(r"\b" + re.escape(keyword) + r"\b", text))

            # Normalize to 0-30 scale (count up to 6 keywords = max 30 points)
            scores[category] = min(30, keyword_count * 5)

        return scores

    def _extract_text(self, html: str) -> str:
        """Extract clean text from HTML."""
        try:
            soup = BeautifulSoup(html, "html.parser")
            # Remove script and style elements
            for script in soup(["script", "style"]):
                script.decompose()
            # Get text
            text = soup.get_text(separator=" ")
            # Clean up whitespace
            text = " ".join(text.split())
            return text
        except Exception:
            return ""

    def classify_multiple_pages(
        self, pages: dict[str, str]
    ) -> dict[str, PageType]:
        """
        Classify multiple pages at once.

        Args:
            pages: Dict of {url: html}

        Returns:
            Dict of {url: page_type}
        """
        return {url: self.classify_page(url, html) for url, html in pages.items()}
