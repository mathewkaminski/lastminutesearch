from uuid import UUID
from src.database.supabase_client import get_client


class CheckStore:
    def __init__(self):
        self.client = get_client()

    def save_checks(self, checks: list[dict]) -> None:
        """Insert one or more league_check rows."""
        self.client.table("league_checks").insert(checks).execute()

    def get_checks_for_run(self, check_run_id: UUID) -> list[dict]:
        result = (
            self.client.table("league_checks")
            .select("*")
            .eq("check_run_id", str(check_run_id))
            .execute()
        )
        return result.data or []

    def get_latest_check_per_league(self) -> list[dict]:
        """Returns the most recent check row per league_id."""
        result = self.client.rpc("get_latest_league_checks").execute()
        return result.data or []

    def get_urls_with_check_age(self) -> list[dict]:
        """Returns each distinct url_scraped with league count and last checked timestamp."""
        result = self.client.rpc("get_urls_with_check_age").execute()
        return result.data or []
