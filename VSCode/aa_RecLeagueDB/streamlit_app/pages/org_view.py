# streamlit_app/pages/org_view.py
"""Organization View — browse leagues grouped by base domain."""
from __future__ import annotations

import streamlit as st
from src.database.supabase_client import get_client


_LISTING_OPTIONS = ["league", "drop_in", "unknown"]
_LISTING_LABELS = {"league": "✅ League", "drop_in": "🎯 Drop-in", "unknown": "❓ Unknown"}


def _load_data() -> list[dict]:
    client = get_client()
    result = (
        client.table("leagues_metadata")
        .select("league_id, organization_name, url_scraped, base_domain, listing_type, sport_season_code")
        .eq("is_archived", False)
        .order("base_domain")
        .execute()
    )
    return result.data or []


def _group_by_domain(rows: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for row in rows:
        domain = row.get("base_domain") or "unknown"
        groups.setdefault(domain, []).append(row)
    return dict(sorted(groups.items()))


def _group_by_url(rows: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for row in rows:
        url = row.get("url_scraped") or "unknown"
        groups.setdefault(url, []).append(row)
    return groups


def _update_listing_type_for_url(url: str, new_type: str) -> None:
    client = get_client()
    client.table("leagues_metadata").update({"listing_type": new_type}).eq("url_scraped", url).execute()


def _rename_domain(old_domain: str, new_domain: str) -> None:
    client = get_client()
    client.table("leagues_metadata").update({"base_domain": new_domain}).eq("base_domain", old_domain).execute()


def _merge_domains(source: str, target: str) -> None:
    """Reassign all records from source domain to target domain."""
    client = get_client()
    client.table("leagues_metadata").update({"base_domain": target}).eq("base_domain", source).execute()


def render() -> None:
    st.title("Organization View")
    st.caption("Browse scraped URLs grouped by organization domain.")

    try:
        rows = _load_data()
    except Exception as e:
        st.error(f"Could not load data: {e}")
        return

    if not rows:
        st.info("No records found. Run the scraper first.")
        return

    groups = _group_by_domain(rows)
    all_domains = list(groups.keys())

    # --- Summary metrics ---
    total_leagues = sum(1 for r in rows if r.get("listing_type") == "league")
    total_dropins = sum(1 for r in rows if r.get("listing_type") == "drop_in")
    total_unknown = sum(1 for r in rows if r.get("listing_type") == "unknown")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Organizations", len(groups))
    c2.metric("Leagues", total_leagues)
    c3.metric("Drop-ins", total_dropins)
    c4.metric("Unclassified", total_unknown)

    st.divider()

    # --- Filters ---
    col_search, col_filter = st.columns([3, 1])
    search = col_search.text_input("Search by org name or domain", placeholder="e.g. javelin")
    type_filter = col_filter.selectbox("Filter by type", ["All", "League", "Drop-in", "Unknown"])

    type_map = {"All": None, "League": "league", "Drop-in": "drop_in", "Unknown": "unknown"}
    active_type = type_map[type_filter]

    st.divider()

    # --- Domain merge tool ---
    with st.expander("Merge two domain groups"):
        col_a, col_b = st.columns(2)
        src = col_a.selectbox("Source domain (will be renamed)", all_domains, key="merge_src")
        tgt = col_b.selectbox("Target domain (keep this name)", all_domains, key="merge_tgt")
        if st.button("Merge domains", key="do_merge"):
            if src == tgt:
                st.warning("Source and target are the same.")
            else:
                _merge_domains(src, tgt)
                st.success(f"Merged '{src}' → '{tgt}'. Refresh to see changes.")
                st.rerun()

    st.divider()

    # --- Per-domain groups ---
    for domain, domain_rows in groups.items():
        if search and search.lower() not in domain.lower() and not any(
            search.lower() in (r.get("organization_name") or "").lower() for r in domain_rows
        ):
            continue

        url_groups = _group_by_url(domain_rows)

        # Filter by listing type if active
        if active_type:
            visible_urls = {
                url: urrows for url, urrows in url_groups.items()
                if any(r.get("listing_type") == active_type for r in urrows)
            }
        else:
            visible_urls = url_groups

        if not visible_urls:
            continue

        type_counts = {t: sum(1 for r in domain_rows if r.get("listing_type") == t) for t in _LISTING_OPTIONS}
        league_bar = "█" * type_counts["league"]
        dropin_bar = "█" * type_counts["drop_in"]
        header = (
            f"**{domain}**  ({len(url_groups)} URL{'s' if len(url_groups) != 1 else ''})  "
            f"  League `{league_bar or '–'}` {type_counts['league']}  "
            f"  Drop-in `{dropin_bar or '–'}` {type_counts['drop_in']}"
        )

        with st.expander(header):
            # Rename domain
            with st.form(key=f"rename_{domain}"):
                new_name = st.text_input("Rename this domain group", value=domain, key=f"rename_val_{domain}")
                if st.form_submit_button("Rename"):
                    if new_name and new_name != domain:
                        _rename_domain(domain, new_name)
                        st.success(f"Renamed to '{new_name}'. Refresh to see changes.")
                        st.rerun()

            st.divider()

            for url, url_rows in visible_urls.items():
                current_type = url_rows[0].get("listing_type") or "unknown"
                if current_type not in _LISTING_OPTIONS:
                    current_type = "unknown"
                label = _LISTING_LABELS.get(current_type, current_type)
                col_url, col_type, col_edit = st.columns([5, 2, 2])
                col_url.markdown(f"`{url[:70]}`  ({len(url_rows)} record{'s' if len(url_rows) != 1 else ''})")
                col_type.markdown(label)

                new_type = col_edit.selectbox(
                    "Change type",
                    _LISTING_OPTIONS,
                    index=_LISTING_OPTIONS.index(current_type),
                    key=f"type_{url}",
                    label_visibility="collapsed",
                )
                if new_type != current_type:
                    _update_listing_type_for_url(url, new_type)
                    st.success(f"Updated {url[:50]} → {new_type}")
                    st.rerun()
