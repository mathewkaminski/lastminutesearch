from src.database.consolidator import find_within_url_duplicates, ConsolidationGroup


def _row(league_id, org="Org A", sss="V01", year=2026, venue="Park",
         day="Monday", level="Rec", quality=70):
    return {
        "league_id": league_id,
        "organization_name": org,
        "sport_season_code": sss,
        "season_year": year,
        "venue_name": venue,
        "day_of_week": day,
        "source_comp_level": level,
        "quality_score": quality,
    }


def test_identical_six_fields_flagged():
    rows = [_row("A", quality=80), _row("B", quality=60)]
    groups = find_within_url_duplicates(rows)
    assert len(groups) == 1
    g = groups[0]
    assert g.keep_id == "A"   # higher quality
    assert g.archive_id == "B"
    assert g.confidence == "AUTO"


def test_five_of_six_with_one_null_flagged():
    r1 = _row("A", quality=80)
    r2 = _row("B", quality=60)
    r2["source_comp_level"] = None  # one null — still AUTO
    groups = find_within_url_duplicates([r1, r2])
    assert len(groups) == 1
    assert groups[0].confidence == "AUTO"


def test_four_of_six_flagged_as_review():
    r1 = _row("A", quality=80)
    r2 = _row("B", quality=60, day="Wednesday", level="Intermediate")
    groups = find_within_url_duplicates([r1, r2])
    assert len(groups) == 1
    assert groups[0].confidence == "REVIEW"


def test_clearly_distinct_not_flagged():
    # 3/6 fields match — below REVIEW threshold of 4
    r1 = _row("A", day="Monday", venue="Park Arena")
    r2 = _row("B", day="Friday", level="Intermediate", venue="Community Centre")
    groups = find_within_url_duplicates([r1, r2])
    assert len(groups) == 0


def test_three_records_two_dupes():
    rows = [_row("A", quality=90), _row("B", quality=60), _row("C", day="Wednesday")]
    groups = find_within_url_duplicates(rows)
    # A and B are dupes; C is distinct
    assert len(groups) == 1
    assert groups[0].keep_id == "A"
