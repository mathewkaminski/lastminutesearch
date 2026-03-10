from src.scraper.reconciler import reconcile, ReconcileAction


def _league(quality=80, num_teams=8, day="Monday", venue="Arena"):
    return {
        "league_id": "abc-123",
        "quality_score": quality,
        "num_teams": num_teams,
        "day_of_week": day,
        "venue_name": venue,
    }


def test_no_contradiction_returns_merge():
    extracted = {"num_teams": 8, "day_of_week": "Monday", "venue_name": "Arena"}
    action, _ = reconcile(extracted, _league(quality=80, num_teams=8))
    assert action == ReconcileAction.MERGE


def test_contradiction_thin_returns_replace():
    extracted = {"num_teams": 12, "day_of_week": "Monday", "venue_name": "Arena"}
    action, _ = reconcile(extracted, _league(quality=50, num_teams=8))
    assert action == ReconcileAction.REPLACE


def test_contradiction_borderline_returns_review():
    extracted = {"num_teams": 12, "day_of_week": "Monday", "venue_name": "Arena"}
    action, _ = reconcile(extracted, _league(quality=65, num_teams=8))
    assert action == ReconcileAction.REVIEW


def test_contradiction_acceptable_returns_merge():
    """High-quality existing record: never auto-replace on contradiction."""
    extracted = {"num_teams": 12, "day_of_week": "Monday", "venue_name": "Arena"}
    action, _ = reconcile(extracted, _league(quality=80, num_teams=8))
    assert action == ReconcileAction.MERGE


def test_team_count_tolerance():
    """Difference of exactly 1 is not a contradiction."""
    extracted = {"num_teams": 9, "day_of_week": "Monday", "venue_name": "Arena"}
    action, _ = reconcile(extracted, _league(quality=50, num_teams=8))
    assert action == ReconcileAction.MERGE


def test_contradicting_field_in_reason():
    extracted = {"num_teams": 15, "day_of_week": "Tuesday", "venue_name": "Arena"}
    action, reason = reconcile(extracted, _league(quality=50, num_teams=8))
    assert action == ReconcileAction.REPLACE
    assert "num_teams" in reason or "day_of_week" in reason
