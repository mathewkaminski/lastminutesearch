"""4-way Haiku classifier: what kind of page is this?"""

import logging
import anthropic

logger = logging.getLogger(__name__)

MAX_CLASSIFIER_CHARS = 8000

_PROMPT = """\
Classify this rec-sports page. Reply with ONE word only:
LEAGUE_DETAIL - specific league: fees, venue, schedule, registration
SCHEDULE - game matchups with dates/times/teams
LEAGUE_INDEX - overview listing multiple leagues/divisions
OTHER - homepage, login, about, contact, etc.

{yaml_snippet}"""

_VALID = {"LEAGUE_DETAIL", "SCHEDULE", "LEAGUE_INDEX", "OTHER"}


def classify_page(yaml_content: str) -> str:
    """Classify a page's content into one of four types.

    Args:
        yaml_content: YAML accessibility tree string

    Returns:
        One of: "LEAGUE_DETAIL", "SCHEDULE", "LEAGUE_INDEX", "OTHER"
        Defaults to "OTHER" on any API error.
    """
    snippet = yaml_content[:MAX_CLASSIFIER_CHARS]
    prompt = _PROMPT.format(yaml_snippet=snippet)

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=10,
            messages=[{"role": "user", "content": prompt}],
        )
        answer = response.content[0].text.strip().upper()
        # Accept answer even if Haiku added whitespace or punctuation
        for valid in _VALID:
            if answer.startswith(valid):
                logger.debug(f"classify_page -> {valid}")
                return valid
        logger.warning(f"Unexpected classifier answer: {answer!r}, defaulting OTHER")
        return "OTHER"
    except Exception as e:
        logger.warning(f"classify_page failed, defaulting OTHER: {e}")
        return "OTHER"
