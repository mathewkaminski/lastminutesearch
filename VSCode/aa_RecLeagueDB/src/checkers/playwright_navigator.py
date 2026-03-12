import asyncio
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path


NAV_KEYWORDS = [
    "standings", "schedule", "teams", "roster", "divisions",
    "regular season", "current season", "season", "league",
    "fall", "winter", "spring", "summer",
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
        # Match td, li, or div/span cells that contain capitalized team-name-like text
        names = re.findall(
            r'<(?:td|li|div|span)[^>]*>\s*([A-Z][A-Za-z0-9\s&\'.\-]{3,40})\s*</(?:td|li|div|span)>',
            html,
        )
        unique = set(n.strip() for n in names if len(n.strip()) >= 4)
        return len(unique) >= 3

    # Tab labels to try in priority order (lower index wins).
    # "Standings" is preferred — it shows teams regardless of date filters.
    _TAB_PRIORITY = ["standings", "teams", "schedule", "results", "divisions"]

    async def _click_sports_tab(self, frame_or_page) -> None:
        """Click the highest-priority sports tab found on the page/frame.

        Silently ignores all failures — best-effort only.
        """
        try:
            tabs = await frame_or_page.evaluate("""() => {
                const els = Array.from(document.querySelectorAll(
                    '[role="tab"], button, [role="button"], a.tab, .tab-link, nav a'
                ));
                return els.map(el => ({
                    text: (el.innerText || el.textContent || '').trim(),
                })).filter(e => e.text.length > 0 && e.text.length < 60);
            }""")
        except Exception:
            return

        best_label = None
        best_priority = len(self._TAB_PRIORITY)
        for tab in tabs:
            text_lower = tab.get("text", "").lower()
            for idx, kw in enumerate(self._TAB_PRIORITY):
                if kw in text_lower and idx < best_priority:
                    best_priority = idx
                    best_label = tab["text"]
                    break

        if best_label is None:
            return

        try:
            locator = frame_or_page.locator(
                f'[role="tab"]:has-text("{best_label}"), '
                f'button:has-text("{best_label}"), '
                f'a:has-text("{best_label}")'
            ).first
            await locator.click(timeout=3000)
            await asyncio.sleep(1.5)  # Frame objects don't have wait_for_timeout
        except Exception:
            pass

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
        await page.wait_for_timeout(2000)
        visited.add(start_url)

        # Click best sports tab on the main page before capturing
        await self._click_sports_tab(page)

        # Screenshot step 0
        step0_path = str(screenshot_base / "step_0.png")
        await page.screenshot(path=step0_path, full_page=True)

        html0 = await page.content()
        if self._has_team_list(html0):
            results.append(NavigatedPage(
                html=html0, url=start_url, nav_path=[], screenshot_path=step0_path
            ))

        await self._iterate_division_selects(page, results, [], screenshot_base)

        # Handle iframes — GameSheet and similar widgets embed via iframe.
        # The outer page.content() does NOT include iframe HTML.
        await self._handle_frames(page, start_url, results, screenshot_base)

        await self._explore(page, visited, results, [], screenshot_base, 0)
        return results

    async def _handle_frames(self, page, url: str, results: list, screenshot_base: Path) -> None:
        """Inspect child frames (iframes) for team/division data.

        For each child frame:
        1. Click best sports tab (Standings preferred)
        2. Run _iterate_division_selects
        3. Capture HTML if team list found
        """
        try:
            frames = page.frames[1:]  # skip main frame (index 0)
        except Exception:
            return

        for frame in frames:
            try:
                # Click sports tab inside the frame
                await self._click_sports_tab(frame)

                # Iterate native <select> division dropdowns inside frame
                await self._iterate_division_selects(frame, results, ["[iframe]"], screenshot_base)

                # Capture frame HTML if it has team names
                html = await frame.content()
                if self._has_team_list(html):
                    step_n = len(list(screenshot_base.glob("step_*.png")))
                    shot_path = str(screenshot_base / f"step_{step_n}.png")
                    try:
                        await page.screenshot(path=shot_path, full_page=True)
                    except Exception:
                        shot_path = None
                    results.append(NavigatedPage(
                        html=html,
                        url=url,
                        nav_path=["[iframe]"],
                        screenshot_path=shot_path,
                    ))
            except Exception:
                continue

    async def _iterate_division_selects(self, page, results, path, screenshot_base) -> None:
        """Find native <select> elements labelled 'Division' and capture each option's page."""
        try:
            selects = await page.evaluate("""() => {
                return Array.from(document.querySelectorAll('select')).map((s, i) => {
                    const label = (
                        document.querySelector('label[for="' + s.id + '"]') ||
                        s.closest('label') || {}
                    ).innerText || s.getAttribute('aria-label') || s.name || '';
                    return {
                        index: i,
                        label: label.toLowerCase(),
                        options: Array.from(s.options).map(o => ({value: o.value, text: o.text.trim()}))
                    };
                });
            }""")
        except Exception:
            return

        division_keywords = ("division", "group", "category", "league")
        for sel in selects:
            if not any(kw in sel.get("label", "") for kw in division_keywords):
                continue
            for opt in sel.get("options", []):
                opt_text = opt.get("text", "").strip()
                if not opt_text or opt_text.lower() in ("all", "all divisions", "all groups", "overall", ""):
                    continue
                try:
                    select_el = page.locator("select").nth(sel["index"])
                    await select_el.select_option(value=opt.get("value", opt_text))
                    await page.wait_for_timeout(1500)
                    html = await page.content()
                    if self._has_team_list(html):
                        step_n = len(list(screenshot_base.glob("step_*.png")))
                        shot_path = str(screenshot_base / f"step_{step_n}.png")
                        await page.screenshot(path=shot_path, full_page=True)
                        results.append(NavigatedPage(
                            html=html,
                            url=page.url,
                            nav_path=path + [f"Division: {opt_text}"],
                            screenshot_path=shot_path,
                        ))
                except Exception:
                    continue

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

                await self._iterate_division_selects(page, results, new_path, screenshot_base)
                await self._explore(page, visited, results, new_path, screenshot_base, depth + 1)

            except Exception:
                pass  # Skip elements that can't be navigated
