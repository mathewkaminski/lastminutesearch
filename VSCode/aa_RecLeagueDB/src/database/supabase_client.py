"""Supabase database client initialization and utilities."""

import os
import logging
from supabase import create_client

logger = logging.getLogger(__name__)

# Global client instance (lazily initialized)
_client = None


def get_client():
    """Get or create Supabase client (singleton pattern).

    Uses environment variables:
    - SUPABASE_URL: Supabase project URL
    - SUPABASE_KEY: Service role key or anon key

    Returns:
        Supabase client instance

    Raises:
        ValueError: If SUPABASE_URL or SUPABASE_KEY not set
    """
    global _client

    if _client is not None:
        return _client

    # Get credentials from environment
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY")

    if not supabase_url:
        raise ValueError("SUPABASE_URL environment variable not set")
    if not supabase_key:
        raise ValueError("SUPABASE_KEY environment variable not set")

    try:
        logger.info(f"Initializing Supabase client: {supabase_url[:30]}...")
        _client = create_client(supabase_url, supabase_key)
        logger.info("Supabase client initialized successfully")
        return _client
    except Exception as e:
        logger.error(f"Failed to initialize Supabase client: {str(e)}")
        raise


def reset_client():
    """Reset the client instance (for testing)."""
    global _client
    _client = None
