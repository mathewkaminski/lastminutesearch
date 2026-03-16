"""Unit tests for HTML preprocessor components."""

import pytest
from src.extractors.html_preprocessor import (
    PageTypeIdentifier,
    KeywordScorer,
    StructuredDataExtractor,
    HtmlPreProcessor,
)


class TestPageTypeIdentifier:
    """Test page type identification."""

    def test_registration_url_pattern(self):
        """Test URL-based registration detection."""
        identifier = PageTypeIdentifier()
        result = identifier.identify("https://example.com/registration", "<html></html>")

        assert result.page_type == "registration"
        assert result.confidence >= 0.85

    def test_schedule_url_pattern(self):
        """Test URL-based schedule detection."""
        identifier = PageTypeIdentifier()
        result = identifier.identify("https://example.com/schedule", "<html></html>")

        assert result.page_type == "schedule"
        assert result.confidence >= 0.85

    def test_standings_url_pattern(self):
        """Test URL-based standings detection."""
        identifier = PageTypeIdentifier()
        result = identifier.identify("https://example.com/standings", "<html></html>")

        assert result.page_type == "standings"
        assert result.confidence >= 0.85

    def test_html_registration_keywords(self):
        """Test HTML-based registration detection."""
        identifier = PageTypeIdentifier()
        html = "<html><body>Register now! Fee: $850. Join our league today.</body></html>"
        result = identifier.identify("https://example.com/", html)

        assert result.page_type == "registration"
        assert result.confidence >= 0.70

    def test_html_schedule_keywords(self):
        """Test HTML-based schedule detection."""
        identifier = PageTypeIdentifier()
        html = "<html><body>Game schedule: Monday vs Tuesday, fixtures this week.</body></html>"
        result = identifier.identify("https://example.com/", html)

        assert result.page_type == "schedule"
        assert result.confidence >= 0.70

    def test_unknown_page(self):
        """Test fallback to 'other' type."""
        identifier = PageTypeIdentifier()
        result = identifier.identify("https://example.com/about", "<html><body>About us</body></html>")

        assert result.page_type == "other"
        assert result.confidence < 0.5


class TestKeywordScorer:
    """Test keyword-based element scoring."""

    def test_score_pricing_elements(self):
        """Test scoring of pricing elements."""
        scorer = KeywordScorer()
        html = """
        <html>
            <body>
                <table>
                    <tr><td>Team Fee</td><td>$850</td></tr>
                    <tr><td>Individual Fee</td><td>$120</td></tr>
                </table>
            </body>
        </html>
        """

        scored = scorer.score_elements(html)
        assert len(scored) > 0
        # Tables score highest for pricing
        assert any(elem.element_type == "table" for elem in scored)
        assert any("fee" in elem.keyword.lower() for elem in scored)

    def test_score_team_count_elements(self):
        """Test scoring of team count elements."""
        scorer = KeywordScorer()
        html = "<html><body><div>Teams: 12 divisions</div></body></html>"

        scored = scorer.score_elements(html)
        assert len(scored) > 0
        assert any("teams" in elem.keyword.lower() for elem in scored)

    def test_score_venue_elements(self):
        """Test scoring of venue elements."""
        scorer = KeywordScorer()
        html = "<html><body><p>Venue: Trinity Bellwoods Park</p></body></html>"

        scored = scorer.score_elements(html)
        assert len(scored) > 0
        assert any("venue" in elem.keyword.lower() for elem in scored)

    def test_element_type_weighting(self):
        """Test that table elements score higher than divs."""
        scorer = KeywordScorer()
        html = """
        <html>
            <body>
                <table><tr><td>Fee: $850</td></tr></table>
                <div>Fee: $850</div>
            </body>
        </html>
        """

        scored = scorer.score_elements(html)
        # Find table and div elements
        table_scores = [s.score for s in scored if s.element_type == "table"]
        div_scores = [s.score for s in scored if s.element_type == "div"]

        if table_scores and div_scores:
            assert table_scores[0] > div_scores[0]  # Table scores higher


class TestStructuredDataExtractor:
    """Test structured data extraction."""

    def test_extract_pricing_table(self):
        """Test extraction of pricing tables."""
        extractor = StructuredDataExtractor()
        html = """
        <html>
            <body>
                <table>
                    <tr><th>Fee Type</th><th>Amount</th></tr>
                    <tr><td>Team Fee</td><td>$850</td></tr>
                    <tr><td>Individual Fee</td><td>$120</td></tr>
                </table>
            </body>
        </html>
        """

        tables = extractor.extract_tables(html)
        assert len(tables) == 1
        assert tables[0].headers == ["Fee Type", "Amount"]
        assert len(tables[0].rows) == 2

    def test_extract_multiple_tables(self):
        """Test extraction of multiple tables."""
        extractor = StructuredDataExtractor()
        html = """
        <html>
            <body>
                <table><tr><td>Table 1</td></tr></table>
                <table><tr><td>Table 2</td></tr></table>
                <table><tr><td>Table 3</td></tr></table>
            </body>
        </html>
        """

        tables = extractor.extract_tables(html)
        assert len(tables) == 3

    def test_extract_pricing_from_scored_elements(self):
        """Test pricing extraction from scored elements."""
        extractor = StructuredDataExtractor()
        scorer = KeywordScorer()

        html = "<html><body><div>Team registration fee: $850.00</div></body></html>"
        scored = scorer.score_elements(html)
        pricing = extractor.extract_pricing(html, scored)

        assert len(pricing) > 0
        assert pricing[0].type == "team_fee"
        assert pricing[0].value == 850.0

    def test_extract_individual_fee(self):
        """Test individual fee extraction."""
        extractor = StructuredDataExtractor()
        scorer = KeywordScorer()

        html = "<html><body><span>Individual player fee: $120.50</span></body></html>"
        scored = scorer.score_elements(html)
        pricing = extractor.extract_pricing(html, scored)

        assert len(pricing) > 0
        assert pricing[0].type == "individual_fee"
        assert pricing[0].value == 120.5

    def test_extract_team_count_from_standings_table(self):
        """Test team count extraction from standings table."""
        extractor = StructuredDataExtractor()
        html = """
        <html>
            <body>
                <table>
                    <tr><th>Rank</th><th>Team</th><th>Points</th></tr>
                    <tr><td>1</td><td>Team A</td><td>30</td></tr>
                    <tr><td>2</td><td>Team B</td><td>28</td></tr>
                    <tr><td>3</td><td>Team C</td><td>25</td></tr>
                </table>
            </body>
        </html>
        """

        hints = extractor.extract_team_counts(html)
        assert len(hints) > 0
        assert hints[0].source == "standings_table"
        assert hints[0].count == 3
        assert hints[0].confidence >= 0.85

    def test_extract_team_count_from_text(self):
        """Test team count extraction from text mentions."""
        extractor = StructuredDataExtractor()
        html = "<html><body><p>We have 12 teams competing this season</p></body></html>"

        hints = extractor.extract_team_counts(html)
        assert len(hints) > 0
        assert hints[0].source == "text_mention"
        assert hints[0].count == 12
        assert hints[0].confidence >= 0.70

    def test_reject_unreasonable_team_counts(self):
        """Test that unreasonable team counts are rejected."""
        extractor = StructuredDataExtractor()
        html = "<html><body>We have 999 teams or 1 team</body></html>"

        hints = extractor.extract_team_counts(html)
        # Should only get hints within 1-50 range
        for hint in hints:
            assert 1 <= hint.count <= 50


class TestHtmlPreProcessor:
    """Test the complete HTML preprocessor."""

    def test_preprocess_registration_page(self):
        """Test preprocessing of a registration page."""
        preprocessor = HtmlPreProcessor()
        html = """
        <html>
            <body>
                <h1>Register for Soccer</h1>
                <p>Team registration fee: $850</p>
                <p>Individual fee: $120</p>
                <table>
                    <tr><th>Division</th><th>Teams</th></tr>
                    <tr><td>CoEd A</td><td>12</td></tr>
                    <tr><td>Mens B</td><td>10</td></tr>
                </table>
            </body>
        </html>
        """

        result = preprocessor.preprocess("https://example.com/register", html)

        assert result.page_type == "registration"
        assert len(result.extracted_tables) > 0
        assert len(result.pricing_elements) > 0
        assert len(result.team_count_hints) > 0

    def test_to_context_dict(self):
        """Test conversion to GPT-4 context dict."""
        preprocessor = HtmlPreProcessor()
        html = """
        <html>
            <body>
                <table><tr><td>Fee: $850</td></tr></table>
                <p>12 teams registered</p>
            </body>
        </html>
        """

        result = preprocessor.preprocess("https://example.com/register", html)
        context = preprocessor.to_context_dict(result)

        assert "page_type" in context
        assert "extracted_tables" in context
        assert "pricing_hints" in context
        assert "team_count_hints" in context
        assert isinstance(context["extracted_tables"], list)
        assert isinstance(context["pricing_hints"], list)
        assert isinstance(context["team_count_hints"], list)

    def test_preprocess_handles_malformed_html(self):
        """Test that preprocessor handles malformed HTML gracefully."""
        preprocessor = HtmlPreProcessor()
        html = "<html><body>Incomplete HTML"  # Missing closing tags

        # Should not crash
        result = preprocessor.preprocess("https://example.com/", html)

        assert result.page_type is not None  # Should still have a page type


class TestLeagueListDetection:
    """Test league list detection from tables."""

    def test_extract_league_list_table(self):
        """Test extraction of league list table (each row = one league)."""
        extractor = StructuredDataExtractor()

        html = """
        <table>
            <thead>
                <tr>
                    <th>Day/Time</th>
                    <th>Format</th>
                    <th>Venue</th>
                    <th>Team Fee</th>
                    <th>Individual Fee</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td>MON 6:30 PM</td>
                    <td>Co-Ed 6v6</td>
                    <td>Gloucester High School Gym</td>
                    <td>$1,350</td>
                    <td>$135</td>
                </tr>
                <tr>
                    <td>MON 7:30 PM</td>
                    <td>Men's 6v6</td>
                    <td>Gloucester High School Gym</td>
                    <td>$1,350</td>
                    <td>$135</td>
                </tr>
                <tr>
                    <td>TUE 6:30 PM</td>
                    <td>Women's 6v6</td>
                    <td>Merivale High School Gym</td>
                    <td>$1,350</td>
                    <td>$135</td>
                </tr>
            </tbody>
        </table>
        """

        # Extract tables
        tables = extractor.extract_tables(html)
        assert len(tables) == 1
        assert len(tables[0].rows) == 3  # 3 leagues

        # Detect league lists
        league_lists = extractor.extract_league_lists(tables)
        assert len(league_lists) == 1
        assert league_lists[0].confidence >= 0.7
        assert len(league_lists[0].leagues) == 3

    def test_nested_table_extraction(self):
        """Test extraction of deeply nested tables."""
        extractor = StructuredDataExtractor()

        html = """
        <form>
            <div class="wrapper">
                <div class="inner">
                    <table>
                        <tbody>
                            <tr><td>League 1</td><td>$850</td></tr>
                            <tr><td>League 2</td><td>$900</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </form>
        """

        tables = extractor.extract_tables(html)
        assert len(tables) == 1
        assert len(tables[0].rows) == 2

    def test_table_with_thead_and_tbody(self):
        """Test table extraction with explicit thead/tbody."""
        extractor = StructuredDataExtractor()

        html = """
        <table>
            <thead>
                <tr><th>Division</th><th>Fee</th></tr>
            </thead>
            <tbody>
                <tr><td>CoEd A</td><td>$850</td></tr>
                <tr><td>Mens B</td><td>$900</td></tr>
            </tbody>
        </table>
        """

        tables = extractor.extract_tables(html)
        assert len(tables) == 1
        assert tables[0].headers == ["Division", "Fee"]
        assert len(tables[0].rows) == 2

    def test_league_list_not_detected_for_simple_table(self):
        """Test that league lists are not falsely detected for simple tables."""
        extractor = StructuredDataExtractor()

        html = """
        <table>
            <tr><th>Name</th><th>Value</th></tr>
            <tr><td>Item 1</td><td>100</td></tr>
            <tr><td>Item 2</td><td>200</td></tr>
        </table>
        """

        tables = extractor.extract_tables(html)
        league_lists = extractor.extract_league_lists(tables)

        # Should not detect as league list (lacks required keywords)
        assert len(league_lists) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
