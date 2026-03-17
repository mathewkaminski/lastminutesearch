"""4-way page classifier: what kind of page is this?"""

import logging
import anthropic

logger = logging.getLogger(__name__)

_HEAD_CHARS = 3000
_MID_CHARS = 3000
_TAIL_CHARS = 2000

_PROMPT = """\
Classify this web page. Reply with ONE word only:
LEAGUE_INDEX - overview page listing multiple adult rec sports LEAGUES with links to details
LEAGUE_DETAIL - specific adult rec sports LEAGUE page with fees, schedule, registration for a competitive season with games/matches
MEDIUM_DETAIL - standings, statistics, team rosters, team listings, rules, policies
SCHEDULE - game matchups with dates/times/teams
OTHER - everything else including: homepage, login, about, contact, blog, children's/youth programs, swimming lessons, fitness classes, yoga, dance, card/board game clubs (bridge, chess, euchre), camps, training programs, drop-in activities, personal training, facility info

A "league" requires: (a) an adult recreational SPORT, (b) scheduled competitive games/matches over a multi-week season, (c) team or individual registration. Swimming lessons, fitness classes, and social clubs are NOT leagues.

{yaml_snippet}"""

_VALID = {"LEAGUE_DETAIL", "SCHEDULE", "LEAGUE_INDEX", "MEDIUM_DETAIL", "OTHER"}


def _build_snippet(yaml_content: str) -> str:
    """Sample beginning, middle, and end to surface content buried past nav boilerplate.

    Many sites have deep nav trees that consume the first 20-30K chars of the
    accessibility YAML before reaching actual page content.  A single head-only
    window misclassifies those pages as OTHER.
    """
    n = len(yaml_content)
    total = _HEAD_CHARS + _MID_CHARS + _TAIL_CHARS
    if n <= total:
        return yaml_content

    head = yaml_content[:_HEAD_CHARS]
    mid_start = (n - _MID_CHARS) // 2
    mid = yaml_content[mid_start: mid_start + _MID_CHARS]
    tail = yaml_content[-_TAIL_CHARS:]
    return head + "\n[...]\n" + mid + "\n[...]\n" + tail


def classify_page(yaml_content: str) -> str:
    """Classify a page's content into one of four types.

    Args:
        yaml_content: YAML accessibility tree string

    Returns:
        One of: "LEAGUE_DETAIL", "SCHEDULE", "LEAGUE_INDEX", "OTHER"
        Defaults to "OTHER" on any API error.
    """
    snippet = _build_snippet(yaml_content)
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
