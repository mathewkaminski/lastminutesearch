"""Lightweight Claude Haiku classifier: does this page have league data?"""

import logging
import anthropic

logger = logging.getLogger(__name__)

# Truncate YAML to this many chars before sending (keeps Haiku cost near-zero)
MAX_CLASSIFIER_CHARS = 8000

_PROMPT = """\
You are reviewing a page's accessibility tree from a sports league website.
Does this page contain sports league listings with registration info, fees, schedules, or standings?

Answer with ONLY "YES" or "NO". No explanation.

Page content:
{yaml_snippet}"""


def has_league_data(yaml_content: str) -> bool:
    """Return True if the page likely contains league listing data.

    Uses Claude Haiku for cheap, fast YES/NO classification.
    Fails safe — returns False on any API error.

    Args:
        yaml_content: YAML accessibility tree string

    Returns:
        True if page appears to contain league listings
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
        result = answer.startswith("YES")
        logger.debug(f"Classifier → {answer!r} ({result})")
        return result
    except Exception as e:
        logger.warning(f"Classifier failed, defaulting False: {e}")
        return False
