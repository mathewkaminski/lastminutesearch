import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path


NAV_KEYWORDS = [
    "standings", "schedule", "teams", "roster", "divisions",
    "current season", "league", "fall", "winter", "spring", "summer",
    "results", "games",
]
SCORE_THRESHOLD = 0.4
MAX_HOPS = 3
SCREENSHOT_DIR = Path("scrapes/screenshots")


@dataclass
class NavigatedPage:
    html: str
    url: str
    nav_path: list[str]
    screenshot_path: str | None = None


class PlaywrightNavigator:
    def __init__(self, score_threshold: float = SCORE_THRESHOLD, max_hops: int = MAX_HOPS):
        self.score_threshold = score_threshold
        self.max_hops = max_hops

    def _score_text(self, text: str) -> float:
        """Score a link/button text against nav keywords. Returns max score 0-1."""
        text_lower = text.lower().strip()
        best = 0.0
        for kw in NAV_KEYWORDS:
            # Exact substring match → high score
            if kw in text_lower:
                best = max(best, 0.8)
                continue
            ratio = SequenceMatcher(None, text_lower, kw).ratio()
            if ratio >= 0.5:  # Ignore weak coincidental similarity
                best = max(best, ratio)
        return best

    def _has_team_list(self, html: str) -> bool:
        """Heuristic: True if page appears to contain ≥3 distinct team-like names."""
        names = re.findall(r'<(?:td|li)[^>]*>\s*([A-Z][A-Za-z\s&\'.\-]{3,30})\s*</(?:td|li)>', html)
        unique = set(n.strip() for n in names)
        return len(unique) >= 3

    async def navigate(
        self,
        page,  # Playwright Page object
        start_url: str,
        run_id: str,
        league_id: str,
    ) -> list[NavigatedPage]:
        """
        Navigate from start_url, following keyword-matching links up to max_hops deep.
        Takes screenshots at each step. Returns list of NavigatedPage with HTML snapshots.
        """
        screenshot_base = SCREENSHOT_DIR / league_id / run_id
        screenshot_base.mkdir(parents=True, exist_ok=True)

        visited = set()
        results = []

        await page.goto(start_url)
        visited.add(start_url)

        # Screenshot step 0
        step0_path = str(screenshot_base / "step_0.png")
        await page.screenshot(path=step0_path, full_page=True)

        html0 = await page.content()
        if self._has_team_list(html0):
            results.append(NavigatedPage(
                html=html0, url=start_url, nav_path=[], screenshot_path=step0_path
            ))

        await self._explore(page, visited, results, [], screenshot_base, 0)
        return results

    async def _explore(self, page, visited, results, path, screenshot_base, depth):
        if depth >= self.max_hops:
            return

        # Collect all clickable elements with text
        elements = await page.evaluate("""() => {
            const links = Array.from(document.querySelectorAll('a[href], button, [role="tab"]'));
            return links.map(el => ({
                text: el.innerText.trim(),
                href: el.href || null,
                tag: el.tagName.toLowerCase(),
            })).filter(e => e.text.length > 0 && e.text.length < 80);
        }""")

        scored = [
            (el, self._score_text(el["text"]))
            for el in elements
            if self._score_text(el["text"]) >= self.score_threshold
        ]
        scored.sort(key=lambda x: x[1], reverse=True)

        for el, score in scored:
            target_url = el.get("href") or page.url
            if target_url in visited:
                continue
            visited.add(target_url)
            new_path = path + [el["text"]]

            try:
                if el.get("href"):
                    await page.goto(el["href"])
                else:
                    # Button or tab — click it
                    locator = page.locator(f'text="{el["text"]}"').first
                    await locator.click()
                    await page.wait_for_load_state("networkidle", timeout=5000)

                step_n = len(list(screenshot_base.glob("step_*.png")))
                shot_path = str(screenshot_base / f"step_{step_n}.png")
                await page.screenshot(path=shot_path, full_page=True)

                html = await page.content()
                if self._has_team_list(html):
                    results.append(NavigatedPage(
                        html=html,
                        url=page.url,
                        nav_path=new_path,
                        screenshot_path=shot_path,
                    ))

                await self._explore(page, visited, results, new_path, screenshot_base, depth + 1)

            except Exception:
                pass  # Skip elements that can't be navigated
