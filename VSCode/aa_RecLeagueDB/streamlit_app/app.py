"""RecSportsDB - Main Streamlit app entry point."""

import os
import sys
from pathlib import Path

# Add parent directory to Python path so src modules can be imported
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

import streamlit as st
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

st.set_page_config(
    page_title="RecSportsDB",
    page_icon="🏆",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
    <style>
    .main-header { font-size: 2.5rem; color: #1f77b4; margin-bottom: 0.5rem; }
    .stat-card { background-color: #f0f2f6; padding: 1rem; border-radius: 0.5rem; text-align: center; }
    </style>
""", unsafe_allow_html=True)

st.markdown('<div class="main-header">🏆 RecSportsDB</div>', unsafe_allow_html=True)
st.markdown("Adult Recreational Sports League Database")
st.divider()

# Navigation
PAGES = {
    # Search Pipeline
    "🎯 Campaign Manager":       ("search",  "campaign_manager"),
    "📋 Queue Monitor":          ("search",  "queue_monitor"),
    "🕷️ Scraper UI":             ("search",  "scraper_ui"),
    # Data Management
    "🗂️ Leagues Viewer":         ("manage",  "leagues_viewer"),
    "📊 Data Quality":           ("manage",  "data_quality"),
    "🔀 Merge Tool":             ("manage",  "merge_tool"),
    "📍 Venues Enricher":        ("manage",  "venues_enricher"),
}

with st.sidebar:
    st.title("Navigation")
    st.caption("── Search Pipeline ──")
    for label in ["🎯 Campaign Manager", "📋 Queue Monitor", "🕷️ Scraper UI"]:
        if st.button(label, key=f"nav_{label}", use_container_width=True):
            st.session_state.current_page = label
    st.caption("── Data Management ──")
    for label in ["🗂️ Leagues Viewer", "📊 Data Quality", "🔀 Merge Tool", "📍 Venues Enricher"]:
        if st.button(label, key=f"nav_{label}", use_container_width=True):
            st.session_state.current_page = label

if "current_page" not in st.session_state:
    st.session_state.current_page = "🎯 Campaign Manager"

if "searches_executed" not in st.session_state:
    st.session_state.searches_executed = False
if "campaign_results" not in st.session_state:
    st.session_state.campaign_results = None

page = st.session_state.current_page
_, module_name = PAGES.get(page, ("search", "campaign_manager"))

if module_name == "campaign_manager":
    from pages import campaign_manager
    campaign_manager.render()

elif module_name == "queue_monitor":
    from pages import queue_monitor
    queue_monitor.render()

elif module_name == "scraper_ui":
    try:
        from pages import scraper_ui
        scraper_ui.render()
    except ImportError:
        st.info("🕷️ Scraper UI is being built in a separate session. Check back soon.")

elif module_name == "leagues_viewer":
    try:
        from pages import leagues_viewer
        leagues_viewer.render()
    except ImportError:
        st.info("🗂️ **Leagues Viewer** — coming next. Will allow browsing and filtering the leagues_metadata table.")
        st.markdown("See [CLAUDE_MANAGE.md](../docs/agents/CLAUDE_MANAGE.md) for the full spec.")

elif module_name == "data_quality":
    try:
        from pages import data_quality
        data_quality.render()
    except ImportError:
        st.info("📊 **Data Quality Dashboard** — coming next. Will show quality score distribution, field coverage, and issue queue.")
        st.markdown("See [CLAUDE_MANAGE.md](../docs/agents/CLAUDE_MANAGE.md) for the full spec.")

elif module_name == "merge_tool":
    try:
        from pages import merge_tool
        merge_tool.render()
    except ImportError:
        st.info("🔀 **Merge Tool** — coming next. Will surface duplicate leagues for side-by-side review and merge/delete actions.")
        st.markdown("See [CLAUDE_MANAGE.md](../docs/agents/CLAUDE_MANAGE.md) for the full spec.")

elif module_name == "venues_enricher":
    from pages import venues_enricher
    venues_enricher.render()

st.divider()
st.markdown(
    '<div style="text-align: center; color: #666; font-size: 0.8rem;">RecSportsDB | 2026</div>',
    unsafe_allow_html=True
)
