"""Vector store operations for unstructured league data using pgvector.

This module handles:
- Creating embeddings for page content
- Storing embeddings in league_vectors table
- Querying similar content via vector similarity search
"""

import logging
from typing import Dict, List, Optional, Any
from openai import OpenAI

from src.database.supabase_client import get_client
from src.extractors.league_extractor import _clean_html

logger = logging.getLogger(__name__)

# OpenAI embedding model
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMS = 1536  # text-embedding-3-small produces 1536-dim vectors


def create_embeddings(text: str) -> List[float]:
    """Create OpenAI embeddings for text content.

    Args:
        text: Text to embed (will be truncated to ~8000 chars)

    Returns:
        List of floats representing the embedding vector

    Raises:
        Exception: If OpenAI API call fails
    """
    # Limit text to prevent excessive API costs
    text_limited = text[:8000]

    logger.debug(f"Creating embedding for {len(text_limited)} chars of text")

    try:
        client = OpenAI()
        response = client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=text_limited
        )

        embedding = response.data[0].embedding
        logger.debug(f"Successfully created {len(embedding)}-dimensional embedding")

        return embedding

    except Exception as e:
        logger.error(f"Failed to create embeddings: {str(e)}")
        raise


def store_page_content(
    league_id: str,
    url: str,
    page_type: str,
    html: str,
    metadata: Optional[Dict[str, Any]] = None,
    supabase_client=None
) -> Optional[str]:
    """Store page content with embedding in league_vectors table.

    Args:
        league_id: UUID of the league this content belongs to
        url: Source URL of the content
        page_type: Type of page (home, registration, schedule, standings, etc.)
        html: Raw HTML content
        metadata: Additional metadata to store (date scraped, etc.)
        supabase_client: Supabase client instance (optional, will create if None)

    Returns:
        UUID of inserted vector record, or None if failed

    Raises:
        Exception: If insertion fails
    """
    if not supabase_client:
        supabase_client = get_client()

    try:
        # Clean HTML to text
        content = _clean_html(html)
        logger.debug(f"Cleaned HTML to {len(content)} chars of text")

        # Create embedding
        embedding = create_embeddings(content)

        # Prepare metadata
        if not metadata:
            metadata = {}
        metadata["page_type"] = page_type
        metadata["source_url"] = url

        # Build vector record
        vector_record = {
            "league_id": league_id,
            "url_scraped": url,
            "page_type": page_type,
            "content": content,
            "embedding": embedding,
            "metadata": metadata
        }

        # Insert into league_vectors
        result = supabase_client.table("league_vectors").insert(vector_record).execute()

        if result.data and len(result.data) > 0:
            vector_id = result.data[0]["id"]
            logger.info(f"Stored vector {vector_id} for league {league_id[:8]}... ({page_type})")
            return vector_id
        else:
            logger.warning(f"Insert succeeded but no data returned for league {league_id}")
            return None

    except Exception as e:
        logger.error(f"Failed to store vector for league {league_id}: {str(e)}")
        raise


def query_similar_content(
    query_text: str,
    limit: int = 10,
    supabase_client=None
) -> List[Dict[str, Any]]:
    """Query for similar content using vector similarity search.

    Uses pgvector's cosine distance for semantic search.

    Args:
        query_text: Text to search for similar content
        limit: Maximum number of results to return
        supabase_client: Supabase client instance (optional, will create if None)

    Returns:
        List of similar content records with similarity scores

    Raises:
        Exception: If query fails
    """
    if not supabase_client:
        supabase_client = get_client()

    try:
        # Create query embedding
        logger.debug(f"Creating embedding for query: '{query_text[:50]}...'")
        query_embedding = create_embeddings(query_text)

        # Call Supabase RPC function for vector similarity search
        # Note: This requires a Supabase function to be created:
        # CREATE OR REPLACE FUNCTION match_league_vectors (
        #   query_embedding vector,
        #   match_count int DEFAULT 10,
        #   similarity_threshold float DEFAULT 0.0
        # )
        # RETURNS TABLE (
        #   id UUID,
        #   league_id UUID,
        #   url_scraped TEXT,
        #   page_type TEXT,
        #   content TEXT,
        #   similarity FLOAT
        # ) AS $$
        # SELECT
        #   id,
        #   league_id,
        #   url_scraped,
        #   page_type,
        #   content,
        #   1 - (embedding <=> query_embedding) as similarity
        # FROM league_vectors
        # WHERE 1 - (embedding <=> query_embedding) > similarity_threshold
        # ORDER BY embedding <=> query_embedding
        # LIMIT match_count;
        # $$ LANGUAGE SQL STABLE;

        logger.debug(f"Querying similar vectors (limit={limit})")

        result = supabase_client.rpc(
            "match_league_vectors",
            {
                "query_embedding": query_embedding,
                "match_count": limit
            }
        ).execute()

        if result.data:
            logger.info(f"Found {len(result.data)} similar results")
            return result.data
        else:
            logger.info("No similar results found")
            return []

    except Exception as e:
        logger.error(f"Vector similarity search failed: {str(e)}")
        raise


def get_vectors_for_league(league_id: str, supabase_client=None) -> List[Dict[str, Any]]:
    """Retrieve all vector records for a specific league.

    Args:
        league_id: UUID of the league
        supabase_client: Supabase client instance (optional, will create if None)

    Returns:
        List of vector records for the league

    Raises:
        Exception: If query fails
    """
    if not supabase_client:
        supabase_client = get_client()

    try:
        result = supabase_client.table("league_vectors") \
            .select("*") \
            .eq("league_id", league_id) \
            .execute()

        logger.info(f"Retrieved {len(result.data)} vector records for league {league_id[:8]}...")
        return result.data

    except Exception as e:
        logger.error(f"Failed to retrieve vectors for league {league_id}: {str(e)}")
        raise


def delete_vectors_for_league(league_id: str, supabase_client=None) -> int:
    """Delete all vector records for a league (on re-scraping/duplication).

    Args:
        league_id: UUID of the league
        supabase_client: Supabase client instance (optional, will create if None)

    Returns:
        Number of records deleted

    Raises:
        Exception: If deletion fails
    """
    if not supabase_client:
        supabase_client = get_client()

    try:
        # Supabase will cascade delete via FK
        result = supabase_client.table("league_vectors") \
            .delete() \
            .eq("league_id", league_id) \
            .execute()

        deleted_count = len(result.data) if result.data else 0
        logger.info(f"Deleted {deleted_count} vector records for league {league_id[:8]}...")
        return deleted_count

    except Exception as e:
        logger.error(f"Failed to delete vectors for league {league_id}: {str(e)}")
        raise
