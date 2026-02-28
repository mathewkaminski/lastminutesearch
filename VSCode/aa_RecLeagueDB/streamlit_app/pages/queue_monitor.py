"""Queue Monitor — browse, filter, bulk-update, and populate the scrape_queue table."""

import pandas as pd
import streamlit as st

from src.database.queue_viewer import (
    VALID_STATUSES,
    bulk_update_by_filter,
    bulk_update_status,
    get_queue_row_count,
    get_queue_rows,
    get_queue_stats,
)
from src.database.supabase_client import get_client
from src.search import SearchOrchestrator

PAGE_SIZE = 50


def render():
    st.title("📋 Queue Monitor")

    # ── Stats bar ─────────────────────────────────────────────────────────────
    stats = get_queue_stats()
    cols = st.columns(len(VALID_STATUSES))
    for col, status in zip(cols, VALID_STATUSES):
        col.metric(status, stats.get(status, 0))

    st.divider()

    # ── Filters ───────────────────────────────────────────────────────────────
    fc1, fc2, fc3 = st.columns([2, 1, 2])
    with fc1:
        status_filter = st.multiselect(
            "Status", VALID_STATUSES, default=['PENDING', 'FAILED']
        )
    with fc2:
        priority_filter = st.multiselect("Priority", [1, 2, 3])
    with fc3:
        search_text = st.text_input("Search URL / Org", placeholder="e.g. ottawavolley")

    # Normalize empties → None so DB layer skips those filters
    sf = status_filter or None
    pf = priority_filter or None
    st_val = search_text.strip() or None

    # ── Pagination state ──────────────────────────────────────────────────────
    if 'queue_page' not in st.session_state:
        st.session_state.queue_page = 0

    total = get_queue_row_count(sf, pf, st_val)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)

    # Reset to page 0 if current page is beyond new total (filter changed)
    if st.session_state.queue_page >= total_pages:
        st.session_state.queue_page = 0

    offset = st.session_state.queue_page * PAGE_SIZE
    rows = get_queue_rows(sf, pf, st_val, offset=offset, limit=PAGE_SIZE)

    st.caption(
        f"{total} rows total | Page {st.session_state.queue_page + 1} of {total_pages}"
    )

    # ── Table with checkbox selection ─────────────────────────────────────────
    selected_ids = []

    if rows:
        df = pd.DataFrame(rows)
        df.insert(0, 'select', False)

        ordered = [
            'select', 'url', 'status', 'priority',
            'organization_name', 'sport_season_code', 'scrape_attempts', 'created_at',
        ]
        # Guard against missing columns (schema may vary)
        display_cols = [c for c in ordered if c in df.columns or c == 'select']

        edited = st.data_editor(
            df[display_cols],
            column_config={
                'select': st.column_config.CheckboxColumn('✓', default=False),
                'url': st.column_config.TextColumn('URL', width='large'),
                'status': st.column_config.TextColumn('Status', width='small'),
                'priority': st.column_config.NumberColumn('P', width='small'),
                'organization_name': st.column_config.TextColumn('Org', width='medium'),
                'sport_season_code': st.column_config.TextColumn('SSS', width='small'),
                'scrape_attempts': st.column_config.NumberColumn('Tries', width='small'),
            },
            disabled=[c for c in display_cols if c != 'select'],
            hide_index=True,
            use_container_width=True,
        )

        # Merge selection back to get the scrape_ids for checked rows
        if 'scrape_id' in df.columns:
            df['select'] = edited['select']
            selected_ids = df[df['select']]['scrape_id'].tolist()

    else:
        st.info("No rows match the current filters.")

    # ── Pagination controls ───────────────────────────────────────────────────
    pc1, _pc2, pc3 = st.columns([1, 4, 1])
    with pc1:
        if st.session_state.queue_page > 0:
            if st.button("← Prev"):
                st.session_state.queue_page -= 1
                st.rerun()
    with pc3:
        if st.session_state.queue_page < total_pages - 1:
            if st.button("Next →"):
                st.session_state.queue_page += 1
                st.rerun()

    st.divider()

    # ── Actions ───────────────────────────────────────────────────────────────
    st.subheader("Actions")
    ac1, ac2 = st.columns(2)

    with ac1:
        st.write(f"**Selected rows** ({len(selected_ids)} checked on this page)")
        sel_new_status = st.selectbox(
            "Set selected to", VALID_STATUSES, key='sel_status'
        )
        if st.button("Apply to selected", disabled=not selected_ids):
            n = bulk_update_status(selected_ids, sel_new_status)
            st.success(f"Updated {n} rows")
            st.rerun()

    with ac2:
        st.write(f"**All filtered rows** ({total} matching current filters)")
        bulk_new_status = st.selectbox(
            "Set all filtered to", VALID_STATUSES, key='bulk_status'
        )
        if st.button(
            f"Apply to all {total} filtered rows",
            type="primary",
            disabled=total == 0,
        ):
            n = bulk_update_by_filter(sf, pf, st_val, bulk_new_status)
            st.success(f"Updated {n} rows")
            st.rerun()

    st.divider()

    # ── Add via Serper ────────────────────────────────────────────────────────
    with st.expander("➕ Add to queue via Serper search"):
        s1, s2 = st.columns(2)
        with s1:
            city = st.text_input("City", placeholder="e.g. Ottawa")
        with s2:
            sport = st.text_input("Sport", placeholder="e.g. volleyball")

        if st.button("🔍 Search & Add to Queue"):
            if city and sport:
                with st.spinner(f"Searching for {city} {sport} leagues..."):
                    db = get_client()
                    orchestrator = SearchOrchestrator(supabase_client=db)
                    campaign = orchestrator.execute_search_campaign(
                        cities=[city],
                        sports=[sport],
                        check_duplicates=False,
                    )
                st.success(
                    f"Added **{campaign['added_to_queue']}** URLs to queue "
                    f"({campaign['valid_results']} valid / {campaign['total_results']} total results)"
                )
                st.rerun()
            else:
                st.warning("Enter both city and sport.")
