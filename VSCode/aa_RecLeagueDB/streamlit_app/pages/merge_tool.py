"""Merge Tool — surface and resolve suspected duplicate league records."""
from __future__ import annotations

import streamlit as st

from src.database.leagues_reader import get_duplicate_groups, archive_league
from src.database.supabase_client import get_client


def _merge(keep_id: str, archive_id: str) -> None:
    """Keep higher-quality record, copy non-null fields from the other, archive duplicate."""
    client = get_client()
    # Fetch both records
    keep_res = client.table("leagues_metadata").select("*").eq("league_id", keep_id).execute()
    arch_res = client.table("leagues_metadata").select("*").eq("league_id", archive_id).execute()
    keep = (keep_res.data or [{}])[0]
    other = (arch_res.data or [{}])[0]

    # Copy non-null fields from other into keep (only where keep is null)
    updates = {
        k: v for k, v in other.items()
        if v is not None and keep.get(k) is None
        and k not in ("league_id", "created_at", "updated_at", "is_archived")
    }
    if updates:
        client.table("leagues_metadata").update(updates).eq("league_id", keep_id).execute()

    # Archive the duplicate
    archive_league(archive_id)


_COMPARE_FIELDS = [
    "organization_name", "sport_season_code", "season_year",
    "day_of_week", "start_time", "venue_name", "competition_level",
    "gender_eligibility", "team_fee", "individual_fee", "num_weeks",
    "quality_score", "url_scraped", "updated_at",
]


def render() -> None:
    st.title("Merge Tool")
    st.caption("Finds suspected duplicate leagues (same org + sport + year + venue + day + level).")

    if st.button("Scan for duplicates"):
        try:
            groups = get_duplicate_groups()
            st.session_state["dup_groups"] = groups
        except Exception as e:
            st.error(f"Scan failed: {e}")
            return

    groups = st.session_state.get("dup_groups")
    if groups is None:
        st.info("Click 'Scan for duplicates' to begin.")
        return

    if not groups:
        st.success("No suspected duplicates found.")
        return

    st.warning(f"Found {len(groups)} suspected duplicate group{'s' if len(groups) != 1 else ''}.")

    for i, group in enumerate(groups):
        records = group["records"]
        # Sort so higher quality score is first
        records = sorted(records, key=lambda r: r.get("quality_score") or 0, reverse=True)
        r1, r2 = records[0], records[1]

        with st.expander(
            f"Group {i + 1}: {r1.get('organization_name')} — {r1.get('sport_season_code')} — "
            f"{r1.get('day_of_week')} ({len(records)} records)"
        ):
            col1, col2 = st.columns(2)
            with col1:
                st.markdown(f"**Record A** (score: {r1.get('quality_score')})")
                for f in _COMPARE_FIELDS:
                    v1, v2 = r1.get(f), r2.get(f)
                    diff = "** " if v1 != v2 else ""
                    st.markdown(f"{diff}`{f}`: {v1}")
            with col2:
                st.markdown(f"**Record B** (score: {r2.get('quality_score')})")
                for f in _COMPARE_FIELDS:
                    v1, v2 = r1.get(f), r2.get(f)
                    diff = "** " if v1 != v2 else ""
                    st.markdown(f"{diff}`{f}`: {v2}")

            st.divider()
            ca, cb, cc = st.columns(3)

            with ca:
                if st.button("Keep Both", key=f"keep_{i}"):
                    # Remove from session state so it doesn't reappear
                    st.session_state["dup_groups"] = [
                        g for j, g in enumerate(groups) if j != i
                    ]
                    st.success("Marked as distinct — removed from list.")
                    st.rerun()

            with cb:
                if st.button("Merge (keep A, archive B)", key=f"merge_{i}"):
                    _merge(r1["league_id"], r2["league_id"])
                    st.session_state["dup_groups"] = [
                        g for j, g in enumerate(groups) if j != i
                    ]
                    st.success(f"Merged. Kept {r1['league_id'][:8]}, archived {r2['league_id'][:8]}.")
                    st.rerun()

            with cc:
                if st.button("Archive B", key=f"del_{i}"):
                    archive_league(r2["league_id"])
                    st.session_state["dup_groups"] = [
                        g for j, g in enumerate(groups) if j != i
                    ]
                    st.success(f"Archived record B ({r2['league_id'][:8]}).")
                    st.rerun()
