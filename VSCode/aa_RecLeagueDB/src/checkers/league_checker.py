from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from uuid import UUID, uuid4

from src.checkers.team_count_extractor import TeamCountExtractor, TeamExtractionResult
from src.checkers.playwright_navigator import PlaywrightNavigator, NavigatedPage
from src.database.check_store import CheckStore
from src.database.supabase_client import get_client


def compute_status(old: int | None, new: int) -> str:
    if new == 0:
        return "NOT_FOUND"
    if old is None:
        return "CHANGED"
    return "MATCH" if abs(new - old) <= 1 else "CHANGED"


def match_to_db(extraction: TeamExtractionResult, db_leagues: list[dict]) -> dict | None:
    """Fuzzy-match an extraction result to a leagues_metadata record."""
    if not extraction.division_name:
        return db_leagues[0] if len(db_leagues) == 1 else None

    best_score = 0.0
    best_league = None
    for league in db_leagues:
        candidate = (league.get("division_name") or league.get("league_name") or "").lower()
        score = SequenceMatcher(None, extraction.division_name.lower(), candidate).ratio()
        if score > best_score:
            best_score = score
            best_league = league

    return best_league if best_score >= 0.4 else None


@dataclass
class CheckRunResult:
    check_run_id: UUID
    checks: list[dict]
    url: str


class LeagueChecker:
    def __init__(self):
        self.extractor = TeamCountExtractor()
        self.navigator = PlaywrightNavigator()
        self.check_store = CheckStore()
        self.supabase = get_client()

    def _get_leagues_for_url(self, url: str) -> list[dict]:
        result = (
            self.supabase.table("leagues_metadata")
            .select("league_id, organization_name, num_teams, division_name, day_of_week, sport_season_code")
            .eq("url_scraped", url)
            .execute()
        )
        return result.data or []

    def check_url(self, url: str, progress_callback=None) -> CheckRunResult:
        """Synchronous entry point — wraps async navigate."""
        return asyncio.run(self._check_url_async(url, progress_callback))

    async def _check_url_async(self, url: str, progress_callback=None) -> CheckRunResult:
        from playwright.async_api import async_playwright

        check_run_id = uuid4()
        db_leagues = self._get_leagues_for_url(url)

        if progress_callback:
            progress_callback(f"Found {len(db_leagues)} league(s) at URL")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            league_id_for_path = db_leagues[0]["league_id"] if db_leagues else "unknown"
            navigated_pages: list[NavigatedPage] = await self.navigator.navigate(
                page, url, str(check_run_id), league_id_for_path
            )
            await browser.close()

        if progress_callback:
            progress_callback(f"Navigated to {len(navigated_pages)} page state(s)")

        checks = []
        for nav_page in navigated_pages:
            extraction = self.extractor.extract(
                nav_page.html,
                url=nav_page.url,
                nav_path=nav_page.nav_path,
                screenshot_path=nav_page.screenshot_path,
            )
            matched = match_to_db(extraction, db_leagues)
            old_count = matched["num_teams"] if matched else None
            new_count = len(extraction.team_names)

            checks.append({
                "check_run_id": str(check_run_id),
                "league_id": matched["league_id"] if matched else None,
                "old_num_teams": old_count,
                "new_num_teams": new_count,
                "division_name": extraction.division_name,
                "nav_path": extraction.nav_path,
                "screenshot_paths": [extraction.screenshot_path] if extraction.screenshot_path else [],
                "status": compute_status(old_count, new_count),
                "raw_teams": extraction.team_names,
                "url_checked": nav_page.url,
            })

        self.check_store.save_checks(checks)

        if progress_callback:
            progress_callback(f"Saved {len(checks)} check result(s)")

        return CheckRunResult(check_run_id=check_run_id, checks=checks, url=url)
