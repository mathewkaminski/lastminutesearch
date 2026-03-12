"""Leagues Viewer — browse and filter active league records."""
from __future__ import annotations

import csv
import io

import streamlit as st

from src.database.leagues_reader import get_leagues, archive_league, add_to_rescrape_queue

_DISPLAY_COLS = [
    "organization_name", "sport_season_code", "day_of_week", "start_time",
    "venue_name", "team_fee", "individual_fee", "quality_score", "updated_at",
]

_ALL_FIELDS = [
    "league_id", "organization_name", "url_scraped", "base_domain",
    "sport_season_code", "season_year", "season_start_date", "season_end_date",
    "day_of_week", "start_time", "num_weeks", "venue_name",
    "competition_level", "gender_eligibility",
    "team_fee", "individual_fee", "registration_deadline",
    "num_teams", "slots_left", "has_referee", "requires_insurance",
    "quality_score", "created_at", "updated_at",
]


def _build_filters() -> dict:
    """Render sidebar filter controls and return active filters dict."""
    filters = {}
    with st.sidebar:
        st.header("Filters")

        listing_types = st.multiselect(
            "Listing type",
            options=["league", "dropin", "unknown"],
            default=["league"],
            help="Include 'unknown' to inspect unclassified records.",
        )
        filters["listing_types"] = listing_types or ["league"]

        org = st.text_input("Org name contains", placeholder="e.g. TSSC")
        if org.strip():
            filters["org_search"] = org.strip()

        sport_codes = st.multiselect(
            "Sport/Season code",
            options=["V10", "V11", "S10", "S11", "B10", "B11", "U10", "U11",
                     "F10", "F11", "T10", "T11", "H10", "H11", "K10", "K11"],
        )
        if sport_codes:
            filters["sport_season_codes"] = sport_codes

        days = st.multiselect(
            "Day of week",
            options=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
        )
        if days:
            filters["days_of_week"] = days

        genders = st.multiselect(
            "Gender eligibility",
            options=["Mens", "Womens", "CoEd", "Other", "Unsure"],
        )
        if genders:
            filters["genders"] = genders

        qmin, qmax = st.slider("Quality score range", 0, 100, (0, 100))
        if qmin > 0:
            filters["quality_min"] = qmin
        if qmax < 100:
            filters["quality_max"] = qmax

    return filters


def _to_csv(rows: list[dict]) -> str:
    """Serialize rows to CSV string."""
    if not rows:
        return ""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_ALL_FIELDS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def render() -> None:
    st.title("Leagues Viewer")
    st.caption("Active (non-archived) records. Use the Listing Type filter to include unknowns.")

    filters = _build_filters()

    try:
        rows = get_leagues(filters)
    except Exception as e:
        st.error(f"Could not load data: {e}")
        return

    if not rows:
        st.info("No leagues match the current filters.")
        return

    st.metric("Leagues shown", len(rows))

    # --- CSV export ---
    csv_data = _to_csv(rows)
    st.download_button(
        "Download CSV",
        data=csv_data,
        file_name="leagues_export.csv",
        mime="text/csv",
    )

    st.divider()

    # --- Table (key columns only) ---
    display_rows = [{col: r.get(col) for col in _DISPLAY_COLS} for r in rows]
    st.dataframe(display_rows, use_container_width=True)

    st.divider()

    # --- Detail expand ---
    st.subheader("Record Detail")
    league_options = {
        f"{r.get('organization_name')} — {r.get('sport_season_code')} — {r.get('day_of_week')} — {r.get('league_id', '')[:8]}": r
        for r in rows
    }
    selected_label = st.selectbox("Select a league to inspect", options=list(league_options.keys()))
    if selected_label:
        record = league_options[selected_label]
        col1, col2 = st.columns(2)
        items = [(k, record.get(k)) for k in _ALL_FIELDS]
        mid = len(items) // 2
        with col1:
            for k, v in items[:mid]:
                st.markdown(f"**{k}:** {v}")
        with col2:
            for k, v in items[mid:]:
                st.markdown(f"**{k}:** {v}")

        st.divider()
        col_arch, col_rescrape = st.columns(2)
        with col_arch:
            if st.button("Archive this league", key=f"arch_{record['league_id']}"):
                archive_league(record["league_id"])
                st.success("Archived. Refresh to see updated list.")
                st.rerun()
        with col_rescrape:
            if st.button("Add to re-scrape queue", key=f"rescrape_{record['league_id']}"):
                add_to_rescrape_queue([record["url_scraped"]])
                st.success(f"Added {record['url_scraped'][:60]} to queue.")
