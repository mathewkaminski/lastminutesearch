"""RecSportsDB Search - Main Streamlit app entry point."""

import os
import sys
from pathlib import Path

# Add parent directory to Python path so src modules can be imported
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

import streamlit as st
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Page configuration
st.set_page_config(
    page_title="RecSportsDB Search",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
    <style>
    .main-header {
        font-size: 2.5rem;
        color: #1f77b4;
        margin-bottom: 0.5rem;
    }
    .stat-card {
        background-color: #f0f2f6;
        padding: 1rem;
        border-radius: 0.5rem;
        text-align: center;
    }
    </style>
""", unsafe_allow_html=True)

# Title
st.markdown('<div class="main-header">🔍 RecSportsDB Search</div>', unsafe_allow_html=True)
st.markdown("**URL Discovery & League Search Pipeline**")
st.divider()

# Sidebar
with st.sidebar:
    st.title("Navigation")
    page = st.radio(
        "Select a page:",
        [
            "🎯 Campaign Manager",
            "📋 Search Results Review",
            "📊 Overview",
            "📍 Coverage Gaps",
            "✅ Validation Analysis",
            "📋 Queue Monitor"
        ],
        index=0  # Default to Campaign Manager
    )

# Initialize session state
if 'searches_executed' not in st.session_state:
    st.session_state.searches_executed = False
if 'campaign_results' not in st.session_state:
    st.session_state.campaign_results = None

# Route to selected page
if "Campaign Manager" in page:
    from pages import campaign_manager
    campaign_manager.render()

elif "Search Results Review" in page:
    from pages import search_results_review
    search_results_review.render()

elif "Overview" in page:
    st.info("📊 Search Overview page - coming soon")
    st.write("This page will show search metrics and visualizations.")

elif "Coverage Gaps" in page:
    st.info("📍 Coverage Gaps page - coming soon")
    st.write("This page will help identify unsearched city/sport combinations.")

elif "Validation Analysis" in page:
    st.info("✅ Validation Analysis page - coming soon")
    st.write("This page will analyze URL validation pass/fail rates.")

elif "Queue Monitor" in page:
    from pages import queue_monitor
    queue_monitor.render()

# Footer
st.divider()
st.markdown(
    """
    <div style="text-align: center; color: #666; font-size: 0.8rem; margin-top: 2rem;">
    RecSportsDB Search Pipeline | Last updated: 2026-02-13
    </div>
    """,
    unsafe_allow_html=True
)
