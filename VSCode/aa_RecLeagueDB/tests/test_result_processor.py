"""Unit tests for result processor and priority scoring."""

import pytest
from src.search.result_processor import calculate_priority_score


class TestPriorityScoring:
    """Test the priority scoring system with 40+ point threshold."""

    def test_known_org_gets_priority_1(self):
        """Test that known organizations get Priority 1."""
        priority = calculate_priority_score(
            url="https://ossc.ca/volleyball",
            title="OSSC Volleyball League",
            snippet="Register now for adult volleyball",
            rank=8,
            org_name="OSSC",
            validation_reason="valid_league_page"
        )
        # 40 (known org) + 10 (rank 7-10) = 50 pts = Priority 1
        assert priority == 1

    def test_adult_rec_keywords_boost_priority(self):
        """Test that adult rec keywords increase priority."""
        priority = calculate_priority_score(
            url="https://example.com",
            title="Toronto Adult Coed Recreational Volleyball",
            snippet="Social league for adults",
            rank=7,
            org_name="",
            validation_reason="valid_adult_rec_league"
        )
        # 20 (adult keywords) + 10 (rank 7-10) + 10 (league keyword) + 20 (explicit adult rec) = 60 pts
        assert priority == 1

    def test_adult_keywords_alone_sufficient(self):
        """Test that strong adult rec indicators can hit Priority 1."""
        priority = calculate_priority_score(
            url="https://example.org",
            title="Chicago Adult Coed Recreational Soccer",
            snippet="Join our social rec league",
            rank=5,
            org_name="",
            validation_reason="valid_league_page"
        )
        # 20 (adult keywords) + 15 (rank 4-6) + 10 (league keyword) + 10 (domain .org) = 55 pts
        assert priority == 1

    def test_capital_volley_example(self):
        """Test the Capital Volley example from the plan."""
        priority = calculate_priority_score(
            url="https://capitalvolley.ca/activity-type/leagues",
            title="Leagues | Capital Volley",
            snippet="We are one of Ottawa's largest coed adult volleyball clubs",
            rank=8,
            org_name="CAPITALVOLLEY",
            validation_reason="valid_league_page"
        )
        # 40 (known org) + 10 (rank 7-10) = 50 pts = Priority 1
        assert priority == 1

    def test_high_rank_alone_insufficient(self):
        """Test that high rank alone doesn't guarantee Priority 1."""
        priority = calculate_priority_score(
            url="https://example.com",
            title="Volleyball in Toronto",
            snippet="General volleyball information",
            rank=1,
            org_name="",
            validation_reason="valid_league_page"
        )
        # Rank 1 gives only 20 points, need 40+ for Priority 1
        assert priority == 3  # 20 pts = Priority 3

    def test_priority_2_threshold(self):
        """Test Priority 2 threshold (20-39 points)."""
        priority = calculate_priority_score(
            url="https://example.com",
            title="Toronto Soccer League",
            snippet="",
            rank=8,
            org_name="",
            validation_reason="valid_league_page"
        )
        # 10 (rank 7-10) + 10 (league keyword) = 20 pts = Priority 2
        assert priority == 2

    def test_priority_3_below_threshold(self):
        """Test Priority 3 for scores below 20 points."""
        priority = calculate_priority_score(
            url="https://example.com",
            title="Random Page",
            snippet="No league keywords",
            rank=11,
            org_name="",
            validation_reason="valid_league_page"
        )
        # 5 (rank 11+) = 5 pts = Priority 3
        assert priority == 3

    def test_domain_quality_bonus(self):
        """Test that .org and .ca domains get bonus points."""
        # .org domain
        priority_org = calculate_priority_score(
            url="https://example.org",
            title="Soccer League",
            snippet="Register",
            rank=8,
            org_name="",
            validation_reason="valid_league_page"
        )
        # 10 (rank 7-10) + 10 (league keyword) + 10 (domain .org) = 30 pts = Priority 2
        assert priority_org == 2

        # .ca domain
        priority_ca = calculate_priority_score(
            url="https://example.ca",
            title="Soccer League",
            snippet="Register",
            rank=8,
            org_name="",
            validation_reason="valid_league_page"
        )
        # 10 (rank 7-10) + 10 (league keyword) + 10 (domain .ca) = 30 pts = Priority 2
        assert priority_ca == 2

        # .com domain (no bonus)
        priority_com = calculate_priority_score(
            url="https://example.com",
            title="Soccer League",
            snippet="Register",
            rank=8,
            org_name="",
            validation_reason="valid_league_page"
        )
        # 10 (rank 7-10) + 10 (league keyword) = 20 pts = Priority 2
        assert priority_com == 2

    def test_multiple_adult_keywords(self):
        """Test scoring with multiple adult keywords."""
        priority = calculate_priority_score(
            url="https://example.com",
            title="Adult Coed Recreational Soccer",
            snippet="Join our social beer league",
            rank=5,
            org_name="",
            validation_reason="valid_league_page"
        )
        # 30 (adult keywords: adult, coed, rec, social) + 15 (rank 4-6) + 10 (league keyword) = 55 pts
        assert priority == 1

    def test_explicit_adult_rec_validation_bonus(self):
        """Test bonus points for explicit adult rec validation."""
        priority = calculate_priority_score(
            url="https://example.com",
            title="Toronto Adult Volleyball",
            snippet="Adult league",
            rank=8,
            org_name="",
            validation_reason="valid_adult_rec_league"
        )
        # 20 (adult keywords) + 10 (rank 7-10) + 10 (league keyword) + 20 (explicit adult rec) = 60 pts
        assert priority == 1

    def test_rank_scoring_tiers(self):
        """Test the diminishing returns on rank scoring."""
        # Rank 1-3: 20 pts
        p1 = calculate_priority_score("url", "league", "", 1, "", "valid_league_page")
        p3 = calculate_priority_score("url", "league", "", 3, "", "valid_league_page")
        assert p1 == p3  # Both should be Priority 2 (20 pts)

        # Rank 4-6: 15 pts
        p4 = calculate_priority_score("url", "league", "", 4, "", "valid_league_page")
        assert p4 == 2  # 15 pts = Priority 2

        # Rank 7-10: 10 pts
        p7 = calculate_priority_score("url", "league", "", 7, "", "valid_league_page")
        assert p7 == 2  # 10 pts = Priority 2

        # Rank 11+: 5 pts
        p11 = calculate_priority_score("url", "league", "", 11, "", "valid_league_page")
        assert p11 == 3  # 5 pts = Priority 3

    def test_combined_scoring_example(self):
        """Test a realistic combined scoring scenario."""
        priority = calculate_priority_score(
            url="https://ottawa.sportandsocial.ca/volleyball",
            title="Ottawa Sport & Social Club - Adult Coed Volleyball",
            snippet="Join our recreational adult volleyball league. Register now for seasonal play.",
            rank=4,
            org_name="OSSC",
            validation_reason="valid_adult_rec_league"
        )
        # 40 (known org OSSC) + 20 (adult keywords: adult, coed, rec) +
        # 15 (rank 4-6) + 10 (league keyword) + 10 (domain .ca) + 20 (explicit adult rec) = 115 pts
        # But max is capped at various levels, so this should be Priority 1
        assert priority == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
