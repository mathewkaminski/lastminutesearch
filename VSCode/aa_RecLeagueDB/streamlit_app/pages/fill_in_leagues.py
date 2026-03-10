"""Fill In Leagues — multi-mode enrichment for existing league records."""
from __future__ import annotations

import streamlit as st
from src.database.supabase_client import get_client


def _get_url_rows() -> list[dict]:
    """Return distinct URLs with org name, league count, avg quality from leagues_metadata."""
    client = get_client()
    result = (
        client.table("leagues_metadata")
        .select("url_scraped, organization_name, quality_score, base_domain")
        .eq("is_archived", False)
        .execute()
    )
    rows = result.data or []

    # Group by url_scraped
    seen: dict[str, dict] = {}
    for row in rows:
        url = row["url_scraped"]
        if url not in seen:
            seen[url] = {
                "url": url,
                "org_name": row.get("organization_name") or row.get("base_domain") or url[:60],
                "league_count": 0,
                "quality_scores": [],
            }
        seen[url]["league_count"] += 1
        if row.get("quality_score") is not None:
            seen[url]["quality_scores"].append(row["quality_score"])

    result_rows = []
    for url, data in seen.items():
        scores = data["quality_scores"]
        data["avg_quality"] = round(sum(scores) / len(scores)) if scores else 0
        result_rows.append(data)

    return sorted(result_rows, key=lambda r: r["avg_quality"])


def _run_deep_dive(url: str, progress_callback) -> dict:
    from scripts.super_scraper import run as super_run
    progress_callback(f"Running super scrape for {url}...")
    return super_run(url, dry_run=False)


def _run_teams(url: str, progress_callback) -> dict:
    from src.checkers.league_checker import LeagueChecker
    progress_callback(f"Running team count refresh for {url}...")
    checker = LeagueChecker()
    result = checker._standard_check(url, db_leagues=None, progress_callback=progress_callback)
    return {"checks": result.checks}


def _run_fill_fields(url: str, progress_callback) -> list:
    from src.enrichers.field_enricher import FieldEnricher
    progress_callback(f"Running field enrichment for {url}...")
    enricher = FieldEnricher()
    return enricher.enrich_url(url)


def render():
    st.title("Fill In Leagues")
    st.caption("Enrich existing league records with missing data.")

    mode = st.radio(
        "Mode",
        options=["Fill Fields", "Teams", "Deep-dive"],
        horizontal=True,
    )

    mode_descriptions = {
        "Fill Fields": "Fills null fields (venue, cost, schedule, policies) from cached snapshots. Falls back to Firecrawl if no cached content is found.",
        "Teams": "Navigates standings pages to refresh num_teams counts.",
        "Deep-dive": "Full re-crawl of the site. Reconciles extracted leagues against existing DB records. Use for low-quality or stale records.",
    }
    st.caption(mode_descriptions[mode])
    st.divider()

    st.subheader("Select URLs")
    try:
        url_rows = _get_url_rows()
    except Exception as e:
        st.error(f"Could not load league URLs: {e}")
        return

    if not url_rows:
        st.info("No scraped leagues found. Run the scraper first.")
        return

    selected_urls: list[str] = []
    for row in url_rows:
        label = f"{row['org_name']}  ({row['league_count']} leagues)  · avg quality {row['avg_quality']}"
        if st.checkbox(label, key=f"fill_{row['url']}"):
            selected_urls.append(row["url"])

    st.divider()

    if st.button("Run Selected", disabled=len(selected_urls) == 0, type="primary"):
        progress = st.progress(0, text="Starting...")
        status = st.empty()
        all_results = []

        for i, url in enumerate(selected_urls):
            status.info(f"Processing: {url[:80]}")

            def cb(msg, _s=status):
                _s.info(msg)

            try:
                if mode == "Deep-dive":
                    r = _run_deep_dive(url, cb)
                    all_results.append({"url": url, "mode": mode, "data": r})
                elif mode == "Teams":
                    r = _run_teams(url, cb)
                    all_results.append({"url": url, "mode": mode, "data": r})
                else:
                    r = _run_fill_fields(url, cb)
                    all_results.append({"url": url, "mode": mode, "data": r})
            except Exception as e:
                st.error(f"Error processing {url}: {e}")
                all_results.append({"url": url, "mode": mode, "data": None, "error": str(e)})

            progress.progress((i + 1) / len(selected_urls), text=f"{i + 1}/{len(selected_urls)}")

        status.success(f"Done. Processed {len(all_results)} URL(s).")
        st.session_state["fill_results"] = all_results

    if "fill_results" in st.session_state:
        st.divider()
        st.subheader("Results")
        for run in st.session_state["fill_results"]:
            url = run["url"]
            mode_label = run["mode"]
            data = run.get("data")
            err = run.get("error")

            with st.expander(f"`{url[:70]}`  [{mode_label}]", expanded=True):
                if err:
                    st.error(f"Error: {err}")
                    continue

                if mode_label == "Deep-dive" and isinstance(data, dict):
                    st.success(
                        f"Super scrape complete — "
                        f"{data.get('leagues_written', 0)} written, "
                        f"{data.get('archived', 0)} archived, "
                        f"{data.get('review_queued', 0)} queued for review"
                    )
                    for e in data.get("errors", []):
                        st.caption(f"Error: {e}")

                elif mode_label == "Teams" and isinstance(data, dict):
                    for chk in data.get("checks", []):
                        status_icon = {"MATCH": "✅", "CHANGED": "🔴", "NOT_FOUND": "⚠️"}.get(
                            chk.get("status", ""), "?"
                        )
                        label = chk.get("division_name") or "League"
                        old_t = chk.get("old_num_teams", "–")
                        new_t = chk.get("new_num_teams", "–")
                        st.write(f"{status_icon} {label} — {old_t} → {new_t} teams")

                elif mode_label == "Fill Fields" and isinstance(data, list):
                    for res in data:
                        source_badge = {"cache": "Cache", "firecrawl": "Firecrawl", "none": "No data"}.get(
                            res.source, res.source
                        )
                        filled = res.filled_fields
                        skipped = res.skipped_fields

                        if res.error:
                            st.warning(f"{res.org_name} — Error: {res.error}")
                        elif filled:
                            st.success(
                                f"{res.org_name} — filled {len(filled)} field(s) "
                                f"via **{source_badge}**: `{'`, `'.join(filled)}`"
                            )
                        else:
                            st.info(f"{res.org_name} — no new data found ({source_badge})")

                        if skipped:
                            st.caption(f"Still missing: {', '.join(skipped)}")
