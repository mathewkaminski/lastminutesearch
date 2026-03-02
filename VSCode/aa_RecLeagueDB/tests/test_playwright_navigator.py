from unittest.mock import MagicMock, patch, AsyncMock
from src.checkers.playwright_navigator import PlaywrightNavigator, NavigatedPage


def make_navigator():
    nav = PlaywrightNavigator.__new__(PlaywrightNavigator)
    nav.score_threshold = 0.4
    nav.max_hops = 3
    return nav


def test_score_link_high_for_standings():
    nav = make_navigator()
    score = nav._score_text("Standings")
    assert score >= 0.4


def test_score_link_zero_for_irrelevant():
    nav = make_navigator()
    score = nav._score_text("Contact Us")
    assert score < 0.4


def test_score_link_medium_for_schedule():
    nav = make_navigator()
    score = nav._score_text("View Schedule")
    assert score >= 0.4


def test_has_team_list_detects_multiple_names():
    nav = make_navigator()
    html = "<table><tr><td>Red Devils</td></tr><tr><td>Blue Hawks</td></tr><tr><td>Green Force</td></tr></table>"
    assert nav._has_team_list(html) is True


def test_has_team_list_false_for_short_page():
    nav = make_navigator()
    html = "<p>Register now for the upcoming season!</p>"
    assert nav._has_team_list(html) is False
