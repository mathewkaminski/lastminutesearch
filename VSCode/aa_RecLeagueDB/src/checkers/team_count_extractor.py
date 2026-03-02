import json
import os
from dataclasses import dataclass, field

import openai


SYSTEM_PROMPT = """You extract team names from recreational sports league pages.
Return JSON only: {"team_names": [...], "division_name": "..." or null, "season_identifier": "..." or null}"""

USER_PROMPT = """Extract all unique team names from this HTML.
Look for standings tables, schedule grids, or team lists.
Return team names exactly as shown.

HTML:
{html}"""


@dataclass
class TeamExtractionResult:
    team_names: list[str]
    division_name: str | None
    season_identifier: str | None
    url: str
    nav_path: list[str] = field(default_factory=list)
    screenshot_path: str | None = None


class TeamCountExtractor:
    def __init__(self):
        openai.api_key = os.getenv("OPENAI_API_KEY")

    def extract(
        self,
        html: str,
        url: str,
        nav_path: list[str],
        screenshot_path: str | None = None,
    ) -> TeamExtractionResult:
        # Truncate HTML to avoid token limits
        truncated = html[:12000] if len(html) > 12000 else html

        response = openai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": USER_PROMPT.format(html=truncated)},
            ],
            temperature=0,
        )

        raw = response.choices[0].message.content
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {"team_names": [], "division_name": None, "season_identifier": None}

        return TeamExtractionResult(
            team_names=data.get("team_names", []),
            division_name=data.get("division_name"),
            season_identifier=data.get("season_identifier"),
            url=url,
            nav_path=nav_path,
            screenshot_path=screenshot_path,
        )
