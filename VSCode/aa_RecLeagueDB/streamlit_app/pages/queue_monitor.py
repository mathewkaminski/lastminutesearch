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
    update_scrape_result,
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

    # ── Run scraper ───────────────────────────────────────────────────────────
    if rows and 'scrape_id' in pd.DataFrame(rows).columns:
        st.markdown("**▶ Scrape selected URLs**")
        if st.button(
            f"▶ Run {len(selected_ids)} Selected",
            disabled=not selected_ids,
            type="primary",
            key="run_scraper",
        ):
            from scripts.smart_scraper import run as scraper_run

            selected_df = df[df['scrape_id'].isin(selected_ids)][['scrape_id', 'url']]
            total_leagues = 0
            total_errors = 0

            with st.status(
                f"Running {len(selected_ids)} URL(s)...", expanded=True
            ) as run_status:
                for _, row in selected_df.iterrows():
                    sid = row['scrape_id']
                    url = row['url']
                    run_status.update(label=f"Running: {url[:70]}...")
                    bulk_update_status([sid], 'IN_PROGRESS')
                    try:
                        result = scraper_run(url, dry_run=False)
                        written = result.get('leagues_written', 0)
                        errors = result.get('errors', [])
                        new_status = (
                            'FAILED' if (written == 0 and errors) else 'COMPLETED'
                        )
                        update_scrape_result(sid, new_status)
                        total_leagues += written
                        if errors:
                            total_errors += len(errors)
                            icon = '✅' if written > 0 else '❌'
                            st.write(
                                f"{icon} **{url}** — "
                                f"{written} league(s) written, {len(errors)} error(s)"
                            )
                            for err in errors:
                                st.caption(f"  ↳ {err[:120]}")
                        else:
                            st.write(
                                f"✅ **{url}** — {written} league(s) written"
                            )
                    except Exception as exc:
                        update_scrape_result(sid, 'FAILED')
                        total_errors += 1
                        st.write(f"❌ **{url}** — {str(exc)[:120]}")

                summary = (
                    f"Done — {total_leagues} league(s) written "
                    f"across {len(selected_ids)} URL(s)"
                )
                if total_errors:
                    summary += f", {total_errors} error(s)"
                run_status.update(
                    label=summary,
                    state="complete" if total_errors == 0 else "error",
                    expanded=True,
                )
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
