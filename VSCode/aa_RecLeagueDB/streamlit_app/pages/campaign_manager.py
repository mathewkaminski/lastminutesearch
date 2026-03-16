"""Campaign Manager - Simplified search interface."""

import os
import sys
from pathlib import Path

# Add parent directory to Python path so src modules can be imported
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

import streamlit as st
import logging
from src.search import SearchOrchestrator
from src.database.supabase_client import get_client

logger = logging.getLogger(__name__)


def render():
    """Render the Campaign Manager page - simplified for single city/sport search."""

    st.title("🎯 Adult Rec League Search")
    st.markdown("**Find adult recreational sports leagues by city and sport**")
    st.divider()

    # Initialize session state
    if 'campaign_results' not in st.session_state:
        st.session_state.campaign_results = None

    # Simple input: City and Sport
    col1, col2 = st.columns(2)

    with col1:
        city = st.text_input("City", value="Toronto", placeholder="e.g., Toronto")

    with col2:
        sport = st.text_input("Sport", value="Volleyball", placeholder="e.g., Soccer, Volleyball")

    # Execute button
    if st.button("🔍 Search", type="primary", use_container_width=True):
        if city and sport:
            try:
                with st.spinner("Searching for adult rec leagues..."):
                    # Initialize orchestrator
                    serper_key = os.getenv('SERPER_API_KEY')
                    if not serper_key:
                        st.error("❌ SERPER_API_KEY not configured")
                    else:
                        db = get_client()
                        orchestrator = SearchOrchestrator(supabase_client=db)

                        # Execute search
                        campaign_results = orchestrator.execute_search_campaign(
                            cities=[city],
                            sports=[sport],
                            check_duplicates=False
                        )

                        st.session_state.campaign_results = campaign_results

                # Display results
                results = campaign_results

                st.divider()
                st.subheader("📊 Results")

                # Summary metrics
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Total Results", results['total_results'])
                with col2:
                    st.metric("Valid URLs", results['valid_results'])
                with col3:
                    st.metric("Invalid URLs", results['total_results'] - results['valid_results'])
                with col4:
                    st.metric("Pass Rate", f"{results['pass_rate']:.1f}%")

                st.success(f"✅ {results['added_to_queue']} URLs added to scrape queue")

                # Show the URLs in a table
                if results['total_results'] > 0:
                    st.subheader("Found URLs")

                    # Get the results from database
                    query_details = results.get('query_details', [])
                    if query_details:
                        query_text = query_details[0].get('query_text', '')
                        st.caption(f"Query: *{query_text}*")

                    # Fetch detailed results from database
                    db = get_client()
                    search_queries = db.table('search_queries').select('query_id').eq('city', city).eq('sport', sport).order('created_at', desc=True).limit(1).execute()

                    if search_queries.data:
                        query_id = search_queries.data[0]['query_id']
                        search_results = db.table('search_results').select(
                            'url_raw, page_title, validation_status, priority'
                        ).eq('query_id', query_id).execute()

                        # Display as expandable list
                        for i, result in enumerate(search_results.data, 1):
                            status = "✓ VALID" if result['validation_status'] == 'PASSED' else "✗ INVALID"
                            priority_str = f"P{result['priority']}" if result['priority'] else ""

                            with st.expander(f"{i}. {result['page_title'][:60]} {priority_str} [{status}]"):
                                st.write(f"**URL:** {result['url_raw']}")
                                st.write(f"**Title:** {result['page_title']}")
                                st.write(f"**Status:** {result['validation_status']}")
                                if result['priority']:
                                    st.write(f"**Priority:** {result['priority']}")

            except Exception as e:
                error_msg = str(e)
                st.error(f"❌ Error: {error_msg[:200]}")
                logger.error(f"Search error: {error_msg}", exc_info=True)
        else:
            st.warning("Please enter both city and sport")
