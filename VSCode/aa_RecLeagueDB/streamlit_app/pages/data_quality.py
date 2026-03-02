"""Data Quality Dashboard — quality metrics for league records only."""
from __future__ import annotations

import streamlit as st

from src.database.leagues_reader import (
    get_quality_summary,
    get_field_coverage,
    get_leagues,
    add_to_rescrape_queue,
    COVERAGE_FIELDS,
)


def _get_quality_by_org(rows: list[dict]) -> list[dict]:
    from collections import defaultdict
    orgs: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        orgs[row.get("organization_name") or "Unknown"].append(row.get("quality_score") or 0)
    result = []
    for org, scores in orgs.items():
        total = len(scores)
        avg = sum(scores) / total
        pct_good = sum(1 for s in scores if s >= 70) * 100 / total
        result.append({"Organization": org, "Leagues": total,
                        "Avg Score": round(avg, 1), "% >= 70": round(pct_good, 1)})
    return sorted(result, key=lambda x: x["Avg Score"])


def _get_quality_by_sport(rows: list[dict]) -> list[dict]:
    from collections import defaultdict
    sports: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        sports[row.get("sport_season_code") or "Unknown"].append(row.get("quality_score") or 0)
    result = []
    for sport, scores in sports.items():
        total = len(scores)
        avg = sum(scores) / total
        result.append({"Sport Code": sport, "Leagues": total, "Avg Score": round(avg, 1)})
    return sorted(result, key=lambda x: x["Avg Score"])


def render() -> None:
    st.title("Data Quality Dashboard")
    st.caption("League records only. Drop-ins and unknowns are excluded.")

    try:
        summary = get_quality_summary()
        coverage = get_field_coverage()
        all_rows = get_leagues()
    except Exception as e:
        st.error(f"Could not load data: {e}")
        return

    # --- Summary metrics ---
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Leagues", summary["total"])
    c2.metric("Avg Quality Score", summary["avg_score"])
    c3.metric("% Score >= 70", f"{summary['pct_good']}%")
    c4.metric("% Score < 50 (needs attention)", f"{summary['pct_poor']}%")

    st.divider()

    # --- Field coverage ---
    st.subheader("Field Coverage")
    st.caption("% of leagues where each field is populated.")
    for field in COVERAGE_FIELDS:
        pct = coverage.get(field, 0.0)
        col_label, col_bar = st.columns([2, 5])
        col_label.markdown(f"`{field}`")
        col_bar.progress(int(pct), text=f"{pct}%")

    st.divider()

    # --- Breakdown by org ---
    st.subheader("Quality by Organization")
    org_data = _get_quality_by_org(all_rows)
    if org_data:
        st.dataframe(org_data, use_container_width=True)

    # --- Breakdown by sport ---
    st.subheader("Quality by Sport Code")
    sport_data = _get_quality_by_sport(all_rows)
    if sport_data:
        st.dataframe(sport_data, use_container_width=True)

    st.divider()

    # --- Issue queue ---
    st.subheader("Issue Queue (Score < 50)")
    poor = [r for r in all_rows if (r.get("quality_score") or 0) < 50]
    if not poor:
        st.success("No leagues below quality threshold.")
    else:
        st.warning(f"{len(poor)} leagues need attention.")
        issue_display = [
            {
                "org": r.get("organization_name"),
                "sport": r.get("sport_season_code"),
                "score": r.get("quality_score"),
                "url": r.get("url_scraped", "")[:60],
                "league_id": r.get("league_id"),
            }
            for r in poor
        ]
        st.dataframe(issue_display, use_container_width=True)

        if st.button("Add all to re-scrape queue"):
            urls = [r["url_scraped"] for r in poor if r.get("url_scraped")]
            add_to_rescrape_queue(urls)
            st.success(f"Added {len(urls)} URLs to re-scrape queue.")
