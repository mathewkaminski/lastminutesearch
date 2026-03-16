"""Search orchestration: coordinates the full search workflow."""

import logging
import os
from typing import List, Callable, Dict
from src.database.supabase_client import get_client
from src.search.query_generator import generate_queries_from_input
from src.search.serper_client import SerperClient, SerperAPIError
from src.search.result_processor import process_search_results
from src.search.queue_manager import add_to_scrape_queue

logger = logging.getLogger(__name__)


class SearchOrchestrator:
    """Orchestrate the complete search workflow.

    Coordinates:
    1. Query generation
    2. Serper API searches
    3. Result validation and processing
    4. Queue management
    """

    def __init__(self, supabase_client=None, serper_client=None):
        """Initialize orchestrator with clients.

        Args:
            supabase_client: Supabase client (will create if None)
            serper_client: Serper API client (will create if None)
        """
        self.db = supabase_client or get_client()

        if serper_client:
            self.serper = serper_client
        else:
            api_key = os.getenv('SERPER_API_KEY')
            if not api_key:
                raise ValueError("SERPER_API_KEY environment variable not set")
            self.serper = SerperClient(api_key)

    def execute_search_campaign(
        self,
        cities: List[str],
        sports: List[str],
        seasons: List[str] = None,
        country: str = None,
        state_province: str = None,
        year: int = None,
        progress_callback: Callable = None,
        check_duplicates: bool = True
    ) -> Dict:
        """Execute a full search campaign.

        Workflow:
        1. Generate queries from city/sport/season combinations
        2. Filter out duplicates
        3. Execute Serper searches
        4. Validate and process results
        5. Add to scrape_queue
        6. Return summary

        Args:
            cities: List of city names
            sports: List of sport names
            seasons: Optional list of seasons
            country: Country code (optional - no default, system is country-agnostic)
            state_province: Optional state/province
            year: Optional year
            progress_callback: Optional callback for progress updates
            check_duplicates: Check for duplicate queries (default: True)

        Returns:
            Dict with campaign results
        """
        campaign_results = {
            'total_queries': 0,
            'completed_queries': 0,
            'total_results': 0,
            'valid_results': 0,
            'failed_results': 0,
            'added_to_queue': 0,
            'pass_rate': 0.0,
            'query_details': []
        }

        try:
            # Step 1: Generate queries
            logger.info("Generating search queries...")
            new_queries, dup_queries = generate_queries_from_input(
                cities=cities,
                sports=sports,
                seasons=seasons,
                country=country,
                state_province=state_province,
                year=year,
                check_duplicates=check_duplicates
            )

            total_queries = len(new_queries)
            campaign_results['total_queries'] = total_queries

            if total_queries == 0:
                logger.info("No new queries to execute (all duplicates)")
                return campaign_results

            logger.info(f"Executing {total_queries} searches...")

            # Step 2-5: Execute searches, validate, and queue
            for idx, query_dict in enumerate(new_queries, 1):
                query_id = None
                try:
                    if progress_callback:
                        progress_callback(
                            idx - 1,
                            total_queries,
                            f"Searching: {query_dict['query_text']}"
                        )

                    # Insert query into database
                    query_result = self.db.table('search_queries').insert({
                        'query_text': query_dict['query_text'],
                        'city': query_dict['city'],
                        'sport': query_dict['sport'],
                        'season': query_dict['season'],
                        'country': query_dict['country'],
                        'state_province': query_dict.get('state_province'),
                        'year': query_dict.get('year'),
                        'query_fingerprint': query_dict['query_fingerprint'],
                        'status': 'IN_PROGRESS'
                    }).execute()

                    query_id = query_result.data[0]['query_id']

                    # Execute Serper search
                    logger.debug(f"Executing search: {query_dict['query_text']}")
                    search_results = self.serper.search(query_dict['query_text'])

                    # Process results (validate, store)
                    result_summary = process_search_results(
                        query_id=query_id,
                        results=search_results,
                        city=query_dict['city'],
                        sport=query_dict['sport']
                    )

                    # Add valid results to queue
                    queued_count = 0
                    if search_results:
                        for result in search_results:
                            try:
                                # Get result IDs from DB
                                result_records = self.db.table('search_results').select(
                                    'result_id, organization_name, priority'
                                ).eq('query_id', query_id).eq(
                                    'url_raw', result.get('url_raw')
                                ).execute()

                                if result_records.data:
                                    r = result_records.data[0]
                                    if r.get('priority'):
                                        added = add_to_scrape_queue(
                                            result_id=r['result_id'],
                                            url=result.get('url_raw'),
                                            org_name=r.get('organization_name'),
                                            priority=r.get('priority')
                                        )
                                        if added:
                                            queued_count += 1
                            except Exception as e:
                                logger.debug(f"Could not add result to queue: {str(e)}")

                    # Update query status to COMPLETED
                    self.db.table('search_queries').update({
                        'status': 'COMPLETED',
                        'total_results': result_summary['total_results']
                    }).eq('query_id', query_id).execute()

                    # Track results
                    campaign_results['completed_queries'] += 1
                    campaign_results['total_results'] += result_summary['total_results']
                    campaign_results['valid_results'] += result_summary['valid_results']
                    campaign_results['failed_results'] += result_summary['failed_results']
                    campaign_results['added_to_queue'] += queued_count

                    campaign_results['query_details'].append({
                        'query_text': query_dict['query_text'],
                        'city': query_dict['city'],
                        'sport': query_dict['sport'],
                        'total_results': result_summary['total_results'],
                        'valid_results': result_summary['valid_results'],
                        'status': 'COMPLETED'
                    })

                    logger.info(
                        f"Query {idx}/{total_queries} complete: {query_dict['query_text']} "
                        f"({result_summary['total_results']} total, "
                        f"{result_summary['valid_results']} valid)"
                    )

                except SerperAPIError as e:
                    logger.error(f"Serper search failed: {str(e)}")
                    if query_id:
                        try:
                            self.db.table('search_queries').update({
                                'status': 'FAILED',
                                'error_message': str(e)
                            }).eq('query_id', query_id).execute()
                        except:
                            pass

                    campaign_results['query_details'].append({
                        'query_text': query_dict.get('query_text', 'unknown'),
                        'status': 'FAILED',
                        'error': str(e)
                    })

                except Exception as e:
                    logger.error(f"Unexpected error in search: {str(e)}")
                    campaign_results['query_details'].append({
                        'query_text': query_dict.get('query_text', 'unknown'),
                        'status': 'ERROR',
                        'error': str(e)
                    })

                finally:
                    if progress_callback:
                        progress_callback(
                            idx,
                            total_queries,
                            f"Completed {idx}/{total_queries}"
                        )

        except Exception as e:
            logger.error(f"Campaign failed: {str(e)}")
            raise

        # Calculate metrics
        if campaign_results['total_results'] > 0:
            campaign_results['pass_rate'] = (
                campaign_results['valid_results'] / campaign_results['total_results'] * 100
            )

        logger.info(
            f"Campaign complete: {campaign_results['completed_queries']} queries, "
            f"{campaign_results['total_results']} results, "
            f"{campaign_results['valid_results']} valid, "
            f"{campaign_results['pass_rate']:.1f}% pass rate"
        )

        return campaign_results


__all__ = ['SearchOrchestrator']
