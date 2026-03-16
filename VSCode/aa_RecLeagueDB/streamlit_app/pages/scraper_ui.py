"""Scraper UI — view source YAML, re-scrape with Firecrawl, extract leagues."""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import streamlit as st

from src.database.supabase_client import get_client
from src.utils.domain_extractor import extract_base_domain

logger = logging.getLogger(__name__)

SCRAPES_DIR = Path(__file__).parent.parent.parent / "scrapes"


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def _get_urls_with_leagues() -> list[dict]:
    """Get distinct URLs from leagues_metadata with league count and quality info."""
    result = (
        get_client()
        .table("leagues_metadata")
        .select("url_scraped, base_domain, quality_score, completeness_status, is_archived")
        .neq("is_archived", True)
        .execute()
    )
    rows = result.data or []

    # Aggregate per URL
    url_map: dict[str, dict] = {}
    for r in rows:
        url = r["url_scraped"]
        if url not in url_map:
            url_map[url] = {
                "url": url,
                "base_domain": r.get("base_domain", ""),
                "league_count": 0,
                "min_quality": 999,
                "max_quality": 0,
            }
        url_map[url]["league_count"] += 1
        q = r.get("quality_score") or 0
        url_map[url]["min_quality"] = min(url_map[url]["min_quality"], q)
        url_map[url]["max_quality"] = max(url_map[url]["max_quality"], q)

    return sorted(url_map.values(), key=lambda x: x["min_quality"])


def _get_leagues_for_url(url: str) -> list[dict]:
    result = (
        get_client()
        .table("leagues_metadata")
        .select("league_id, organization_name, day_of_week, source_comp_level, "
                "gender_eligibility, num_teams, quality_score, completeness_status, "
                "sport_season_code, venue_name, team_fee, individual_fee")
        .eq("url_scraped", url)
        .neq("is_archived", True)
        .execute()
    )
    return result.data or []


def _find_cached_yamls(url: str) -> list[Path]:
    """Find cached YAML files for a URL, newest first."""
    domain = extract_base_domain(url)
    domain_dir = SCRAPES_DIR / domain
    if not domain_dir.exists():
        return []
    yamls = sorted(domain_dir.glob("*.yaml"), reverse=True)
    return yamls[:20]  # limit to 20 most recent


def _find_cached_yaml_for_path(url: str, path_slug: str) -> Path | None:
    """Find the most recent cached YAML matching a specific path slug."""
    domain = extract_base_domain(url)
    domain_dir = SCRAPES_DIR / domain
    if not domain_dir.exists():
        return None
    matches = sorted(domain_dir.glob(f"*_{path_slug}.yaml"), reverse=True)
    return matches[0] if matches else None


# ---------------------------------------------------------------------------
# Firecrawl helper
# ---------------------------------------------------------------------------

def _firecrawl_scrape(url: str, wait_ms: int = 3000) -> dict:
    """Scrape a URL with Firecrawl, return {markdown, metadata} or {error}."""
    try:
        from firecrawl import FirecrawlApp
    except ImportError:
        return {"error": "firecrawl-py not installed"}

    api_key = os.environ.get("FIRECRAWL_API_KEY")
    if not api_key:
        return {"error": "FIRECRAWL_API_KEY not set in .env"}

    try:
        app = FirecrawlApp(api_key=api_key)
        doc = app.scrape(
            url,
            formats=["markdown"],
            wait_for=wait_ms,
            only_main_content=True,
        )
        # doc is a Document object — extract markdown
        markdown = getattr(doc, "markdown", None) or ""
        metadata = getattr(doc, "metadata", {}) or {}
        return {
            "markdown": markdown,
            "metadata": metadata,
            "url": url,
            "chars": len(markdown),
        }
    except Exception as e:
        return {"error": str(e)}


def _extract_from_markdown(markdown: str, url: str) -> list[dict]:
    """Run the LLM extractor on Firecrawl markdown (reuses YAML extractor prompt)."""
    from src.extractors.yaml_extractor import extract_league_data_from_yaml
    return extract_league_data_from_yaml(markdown, url)


def _save_leagues(leagues: list[dict]) -> dict:
    """Write extracted leagues to DB. Returns {written, errors}."""
    from src.database.writer import insert_league
    written = 0
    errors = []
    for league in leagues:
        try:
            lid, _ = insert_league(league)
            if lid:
                written += 1
        except Exception as e:
            errors.append(str(e))
    return {"written": written, "errors": errors}


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

def render():
    st.title("Scraper UI")
    st.caption("View source YAML, re-scrape with Firecrawl, extract leagues")

    urls_data = _get_urls_with_leagues()
    if not urls_data:
        st.info("No URLs in leagues_metadata yet.")
        return

    # ── Sidebar: URL picker ──────────────────────────────────────────────
    with st.sidebar:
        st.subheader("Select URL")
        url_labels = [
            f"[Q{u['min_quality']}] {u['url']}  ({u['league_count']} leagues)"
            for u in urls_data
        ]
        chosen_idx = st.selectbox(
            "URL", range(len(url_labels)),
            format_func=lambda i: url_labels[i],
            key="scraper_url_idx",
        )
        chosen_url = urls_data[chosen_idx]["url"]

        st.divider()
        st.subheader("Manual URL")
        manual_url = st.text_input("Or enter a URL directly", key="scraper_manual_url")
        if manual_url:
            chosen_url = manual_url.strip()

    # ── Main area ────────────────────────────────────────────────────────
    st.subheader(f"URL: `{chosen_url}`")

    tab_leagues, tab_yaml, tab_firecrawl = st.tabs(["Leagues", "Source YAML", "Firecrawl"])

    # ── Tab 1: Existing leagues ──────────────────────────────────────────
    with tab_leagues:
        leagues = _get_leagues_for_url(chosen_url)
        if leagues:
            st.write(f"**{len(leagues)}** active league(s)")
            for lg in leagues:
                q = lg.get("quality_score", 0)
                day = lg.get("day_of_week") or "?"
                level = lg.get("source_comp_level") or ""
                gender = lg.get("gender_eligibility") or ""
                teams = lg.get("num_teams")
                teams_str = f"{teams} teams" if teams else "no team count"
                st.markdown(
                    f"- **{day}** {level} {gender} — Q{q} — {teams_str} "
                    f"(`{lg['league_id'][:8]}…`)"
                )
        else:
            st.warning("No active leagues for this URL")

    # ── Tab 2: Cached YAML ───────────────────────────────────────────────
    with tab_yaml:
        yamls = _find_cached_yamls(chosen_url)
        if not yamls:
            st.info("No cached YAML found for this domain.")
        else:
            yaml_labels = [f.name for f in yamls]
            chosen_yaml_idx = st.selectbox("Cached file", range(len(yaml_labels)),
                                           format_func=lambda i: yaml_labels[i],
                                           key="yaml_file_idx")
            yaml_path = yamls[chosen_yaml_idx]

            # Show metadata if available
            json_path = yaml_path.with_suffix(".json")
            if json_path.exists():
                meta = json.loads(json_path.read_text(encoding="utf-8"))
                c1, c2, c3 = st.columns(3)
                c1.metric("Size", f"{meta.get('yaml_size_bytes', 0):,} bytes")
                c2.metric("Tokens", f"{meta.get('token_estimate', 0):,}")
                c3.metric("Method", meta.get("method", "unknown"))

            # Show YAML content
            yaml_text = yaml_path.read_text(encoding="utf-8")
            st.text_area("YAML content", yaml_text, height=500, key="yaml_display")

            # Quick search in YAML
            search = st.text_input("Search in YAML", key="yaml_search")
            if search:
                lines = yaml_text.split("\n")
                matches = [f"L{i+1}: {line}" for i, line in enumerate(lines)
                           if search.lower() in line.lower()]
                if matches:
                    st.code("\n".join(matches[:50]))
                else:
                    st.warning(f"'{search}' not found")

    # ── Tab 3: Firecrawl ─────────────────────────────────────────────────
    with tab_firecrawl:
        st.markdown(
            "Firecrawl scrapes a page server-side and returns clean Markdown. "
            "Use this when Playwright YAML misses content (e.g. iframe widgets, "
            "anti-bot pages)."
        )

        # Let user specify the exact page(s) to scrape
        default_pages = chosen_url
        # Suggest sub-pages from cached YAML filenames
        yamls_for_domain = _find_cached_yamls(chosen_url)
        if yamls_for_domain:
            parsed = urlparse(chosen_url)
            slugs = set()
            for y in yamls_for_domain:
                # Extract path slug from filename: {timestamp}_{slug}.yaml
                parts = y.stem.split("_", 2)
                if len(parts) >= 3:
                    slug = parts[2]
                    if slug != "home":
                        path = "/" + slug.replace("_", "/")
                        full = f"{parsed.scheme}://{parsed.netloc}{path}"
                        slugs.add(full)
            if slugs:
                default_pages += "\n" + "\n".join(sorted(slugs))

        pages_input = st.text_area(
            "URLs to scrape (one per line)",
            value=default_pages,
            height=120,
            key="firecrawl_urls",
        )

        fc1, fc2 = st.columns([1, 3])
        with fc1:
            wait_ms = st.number_input("Wait (ms)", min_value=0, max_value=15000,
                                      value=3000, step=1000, key="fc_wait")
        with fc2:
            st.write("")  # spacer

        if st.button("Scrape with Firecrawl", type="primary", key="fc_scrape_btn"):
            target_urls = [u.strip() for u in pages_input.strip().split("\n") if u.strip()]
            if not target_urls:
                st.warning("Enter at least one URL")
            else:
                all_markdown = []
                progress = st.progress(0, text="Starting Firecrawl...")
                for i, target_url in enumerate(target_urls):
                    progress.progress(
                        (i) / len(target_urls),
                        text=f"Scraping {target_url}..."
                    )
                    result = _firecrawl_scrape(target_url, wait_ms=wait_ms)
                    if "error" in result:
                        st.error(f"Error scraping {target_url}: {result['error']}")
                    else:
                        st.success(f"{target_url} — {result['chars']:,} chars")
                        all_markdown.append((target_url, result["markdown"]))

                progress.progress(1.0, text="Done")

                if all_markdown:
                    st.session_state["fc_results"] = all_markdown
                    st.session_state["fc_source_url"] = chosen_url

        # Show Firecrawl results if available
        if "fc_results" in st.session_state:
            st.divider()
            st.subheader("Firecrawl Results")

            for url, md in st.session_state["fc_results"]:
                with st.expander(f"{url} ({len(md):,} chars)", expanded=False):
                    st.text_area("Markdown", md, height=400,
                                 key=f"fc_md_{url}")

            # Extract button
            st.divider()
            if st.button("Extract Leagues from Firecrawl Results", key="fc_extract_btn"):
                combined_md = "\n\n---\n\n".join(
                    f"# Source: {url}\n\n{md}"
                    for url, md in st.session_state["fc_results"]
                )
                source_url = st.session_state.get("fc_source_url", chosen_url)

                with st.spinner("Running LLM extraction..."):
                    try:
                        extracted = _extract_from_markdown(combined_md, source_url)
                        st.session_state["fc_extracted"] = extracted
                        st.success(f"Extracted {len(extracted)} league(s)")
                    except Exception as e:
                        st.error(f"Extraction failed: {e}")

        # Show extracted leagues
        if "fc_extracted" in st.session_state:
            st.divider()
            st.subheader("Extracted Leagues (preview)")
            for i, lg in enumerate(st.session_state["fc_extracted"]):
                day = lg.get("day_of_week") or "?"
                org = lg.get("organization_name") or "Unknown"
                level = lg.get("source_comp_level") or ""
                gender = lg.get("gender_eligibility") or ""
                pct = lg.get("identifying_fields_pct", 0)
                teams = lg.get("num_teams")
                st.markdown(
                    f"**{i+1}.** {org} — {day} {level} {gender} — "
                    f"{pct:.0f}% complete"
                    + (f" — {teams} teams" if teams else "")
                )
                with st.expander("Raw JSON", expanded=False):
                    st.json(lg)

            if st.button("Save to Database", type="primary", key="fc_save_btn"):
                with st.spinner("Writing to leagues_metadata..."):
                    result = _save_leagues(st.session_state["fc_extracted"])
                    if result["written"]:
                        st.success(f"Wrote {result['written']} league(s)")
                    if result["errors"]:
                        for e in result["errors"]:
                            st.error(e)
                # Clear state after save
                del st.session_state["fc_extracted"]
                del st.session_state["fc_results"]
                st.rerun()
