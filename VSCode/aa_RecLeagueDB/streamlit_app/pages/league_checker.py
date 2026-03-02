"""League Checker — re-scrape URLs to verify team counts."""
from __future__ import annotations

import streamlit as st
from pathlib import Path
from src.checkers.league_checker import LeagueChecker
from src.database.check_store import CheckStore


def render():
    st.title("League Checker")
    st.caption("Re-scrape existing URLs to verify team counts and detect changes.")

    check_store = CheckStore()

    # --- Summary stats ---
    try:
        urls_data = check_store.get_urls_with_check_age()
    except Exception as e:
        st.error(f"Could not load URL list: {e}")
        return

    if not urls_data:
        st.info("No scraped leagues found. Run the scraper first.")
        return

    total_urls = len(urls_data)
    never_checked = sum(1 for r in urls_data if r.get("last_checked_at") is None)
    col1, col2, col3 = st.columns(3)
    col1.metric("URLs", total_urls)
    col2.metric("Never checked", never_checked)
    col3.metric("With changes", sum(1 for r in urls_data if r.get("has_changes")))

    st.divider()

    # --- URL selection ---
    st.subheader("Select URLs to Check")
    selected_urls = []
    for row in urls_data:
        url = row["url_scraped"]
        org = row.get("org_name", url[:60])
        count = row.get("league_count", "?")
        last_checked = row.get("last_checked_at", "Never")
        has_changes = row.get("has_changes", False)

        badge = "🔴 CHANGES" if has_changes else ("⚪ Never" if last_checked == "Never" else "✅ OK")
        label = f"{org}  ({count} leagues)  {badge}"
        if st.checkbox(label, key=f"check_{url}"):
            selected_urls.append(url)

    st.divider()

    # --- Run button ---
    if st.button("Check Selected URLs", disabled=len(selected_urls) == 0, type="primary"):
        checker = LeagueChecker()
        all_results = []

        progress = st.progress(0, text="Starting...")
        status_placeholder = st.empty()

        for i, url in enumerate(selected_urls):
            status_placeholder.info(f"Checking: {url[:80]}")
            msgs = []

            def callback(msg, _msgs=msgs):
                _msgs.append(msg)
                status_placeholder.info(msg)

            try:
                result = checker.check_url(url, progress_callback=callback)
                all_results.append(result)
            except Exception as e:
                st.error(f"Error checking {url}: {e}")

            progress.progress((i + 1) / len(selected_urls), text=f"{i+1}/{len(selected_urls)} URLs")

        status_placeholder.success(f"Done. Checked {len(all_results)} URL(s).")
        st.session_state["last_check_results"] = all_results

    # --- Results display ---
    if "last_check_results" in st.session_state:
        st.divider()
        st.subheader("Results")

        for run_result in st.session_state["last_check_results"]:
            st.markdown(f"**URL:** `{run_result.url}`")
            if not run_result.checks:
                st.warning("No team data found for this URL.")
                continue

            for chk in run_result.checks:
                status = chk.get("status", "?")
                color = {"MATCH": "✅", "CHANGED": "🔴", "NOT_FOUND": "⚠️", "ERROR": "❌"}.get(status, "?")
                label = chk.get("division_name") or "League"
                old_t = chk.get("old_num_teams", "–")
                new_t = chk.get("new_num_teams", "–")

                with st.expander(f"{color} {label}  |  {old_t} → {new_t} teams  [{status}]"):
                    col_a, col_b = st.columns(2)
                    col_a.metric("DB teams", old_t)
                    delta = None
                    if isinstance(new_t, int) and isinstance(old_t, int):
                        delta = new_t - old_t
                    col_b.metric("Scraped teams", new_t, delta=delta)

                    nav = chk.get("nav_path", [])
                    if nav:
                        st.caption(f"Navigation: {' → '.join(nav)}")

                    teams = chk.get("raw_teams", [])
                    if teams:
                        st.markdown("**Teams found:**")
                        st.write(", ".join(teams))

                    shots = chk.get("screenshot_paths", [])
                    for shot_path in shots:
                        p = Path(shot_path)
                        if p.exists():
                            st.image(str(p), caption=p.name, use_container_width=True)
                        else:
                            st.caption(f"Screenshot: `{shot_path}` (not found locally)")
