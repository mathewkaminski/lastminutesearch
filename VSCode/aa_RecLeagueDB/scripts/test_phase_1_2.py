#!/usr/bin/env python
"""Test script for Phase 1 & 2 implementation.

Run this to verify all Phase 1 and 2 modules are working correctly.

Usage:
    python scripts/test_phase_1_2.py
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config.sss_codes import (
    validate_sss_code,
    get_sport_name,
    get_season_name,
    build_sss_code,
    parse_sss_code,
)
from src.database.validators import (
    validate_required_fields,
    calculate_quality_score,
    validate_extracted_data,
)
from src.utils.league_id_generator import (
    generate_league_id,
    normalize_for_comparison,
    extract_season_year,
    build_uniqueness_key,
)


def test_sss_codes():
    """Test Phase 2A: SSS Code Utilities."""
    print("\n" + "=" * 60)
    print("PHASE 2A: SSS Code Utilities")
    print("=" * 60)

    tests_passed = 0
    tests_total = 0

    # Test 1: validate_sss_code
    test_cases = [
        ("201", True),
        ("311", True),
        ("999", True),  # 9 = Other season, 99 = Other sport
        ("00", False),  # Too short
        ("10000", False),  # Too long
    ]

    for code, expected in test_cases:
        tests_total += 1
        result = validate_sss_code(code)
        status = "PASS" if result == expected else "FAIL"
        if result == expected:
            tests_passed += 1
        print(f"  validate_sss_code('{code}'): {result} {status}")

    # Test 2: get_sport_name and get_season_name
    print()
    assert get_sport_name("01") == "Soccer"
    tests_passed += 1
    tests_total += 1
    print(f"  get_sport_name('01'): Soccer PASS")

    assert get_season_name("2") == "Summer"
    tests_passed += 1
    tests_total += 1
    print(f"  get_season_name('2'): Summer PASS")

    # Test 3: build_sss_code
    print()
    assert build_sss_code("Summer", "Soccer") == "201"
    tests_passed += 1
    tests_total += 1
    print(f"  build_sss_code('Summer', 'Soccer'): 201 PASS")

    # Test 4: parse_sss_code
    print()
    result = parse_sss_code("201")
    assert result["season"] == "Summer"
    assert result["sport"] == "Soccer"
    tests_passed += 1
    tests_total += 1
    print(f"  parse_sss_code('201'): {{season: Summer, sport: Soccer}} PASS")

    print(f"\nPhase 2A: {tests_passed}/{tests_total} tests passed")
    return tests_passed == tests_total


def test_validators():
    """Test Phase 2B: Data Validators."""
    print("\n" + "=" * 60)
    print("PHASE 2B: Data Validators")
    print("=" * 60)

    tests_passed = 0
    tests_total = 0

    # Test 1: validate_required_fields - valid
    valid_data = {
        "organization_name": "Max Volley",
        "sport_season_code": "220",
        "url_scraped": "https://maxvolley.com",
    }
    is_valid, missing = validate_required_fields(valid_data)
    tests_total += 1
    if is_valid and len(missing) == 0:
        tests_passed += 1
        print(f"  validate_required_fields (valid): PASS")
    else:
        print(f"  validate_required_fields (valid): FAIL")

    # Test 2: validate_required_fields - invalid
    invalid_data = {"organization_name": "Max Volley"}
    is_valid, missing = validate_required_fields(invalid_data)
    tests_total += 1
    if not is_valid and len(missing) == 2:
        tests_passed += 1
        print(f"  validate_required_fields (invalid): PASS")
    else:
        print(f"  validate_required_fields (invalid): FAIL")

    # Test 3: calculate_quality_score - complete data
    print()
    complete_data = {
        "organization_name": "Max Volley",
        "sport_season_code": "220",
        "url_scraped": "https://maxvolley.com",
        "season_start_date": "2024-06-01",
        "season_end_date": "2024-08-31",
        "day_of_week": "Monday",
        "start_time": "18:00:00",
        "venue_name": "Sandpoint Beach",
        "team_fee": 450.00,
        "source_comp_level": "Recreational",
        "gender_eligibility": "CoEd",
        "num_weeks": 12,
    }
    score = calculate_quality_score(complete_data)
    tests_total += 1
    if score >= 95:
        tests_passed += 1
        print(f"  calculate_quality_score (complete): {score} PASS")
    else:
        print(f"  calculate_quality_score (complete): {score} FAIL (expected >=95)")

    # Test 4: calculate_quality_score - sparse data
    sparse_data = {
        "organization_name": "Ottawa Rec",
        "sport_season_code": "201",
        "url_scraped": "https://ottawa.com",
    }
    score = calculate_quality_score(sparse_data)
    tests_total += 1
    if 30 <= score <= 60:
        tests_passed += 1
        print(f"  calculate_quality_score (sparse): {score} PASS")
    else:
        print(f"  calculate_quality_score (sparse): {score} FAIL (expected 30-60)")

    # Test 5: validate_extracted_data
    print()
    is_valid, result = validate_extracted_data(complete_data)
    tests_total += 1
    if is_valid and result["quality_score"] >= 95:
        tests_passed += 1
        print(f"  validate_extracted_data: PASS (score={result['quality_score']})")
    else:
        print(f"  validate_extracted_data: FAIL")

    print(f"\nPhase 2B: {tests_passed}/{tests_total} tests passed")
    return tests_passed == tests_total


def test_league_id_generator():
    """Test Phase 2C: League ID Generator."""
    print("\n" + "=" * 60)
    print("PHASE 2C: League ID Generator")
    print("=" * 60)

    tests_passed = 0
    tests_total = 0

    # Test 1: generate_league_id
    id1 = generate_league_id()
    id2 = generate_league_id()
    tests_total += 1
    if id1 != id2 and len(id1) == 36:  # UUID4 length
        tests_passed += 1
        print(f"  generate_league_id: PASS (generates unique UUIDs)")
    else:
        print(f"  generate_league_id: FAIL")

    # Test 2: normalize_for_comparison
    print()
    test_cases = [
        ("Max Volley", "max volley"),
        ("  max  volley  ", "max volley"),
        ("MAX VOLLEY", "max volley"),
        (None, ""),
        ("", ""),
    ]
    for input_val, expected in test_cases:
        tests_total += 1
        result = normalize_for_comparison(input_val)
        if result == expected:
            tests_passed += 1
            print(f"  normalize({input_val!r}): {result!r} PASS")
        else:
            print(f"  normalize({input_val!r}): {result!r} FAIL (expected {expected!r})")

    # Test 3: extract_season_year
    print()
    data = {"season_start_date": "2024-06-01", "season_end_date": "2024-08-31"}
    year = extract_season_year(data)
    tests_total += 1
    if year == 2024:
        tests_passed += 1
        print(f"  extract_season_year: {year} PASS")
    else:
        print(f"  extract_season_year: {year} FAIL (expected 2024)")

    # Test 4: build_uniqueness_key
    print()
    league_data = {
        "organization_name": "  Max Volley  ",
        "sport_season_code": "220",
        "season_start_date": "2024-06-01",
        "season_end_date": "2024-08-31",
        "venue_name": "Sandpoint Beach",
        "day_of_week": "Monday",
        "source_comp_level": "Recreational",
        "gender_eligibility": "CoEd",
        "num_weeks": 12,
    }
    key = build_uniqueness_key(league_data)
    tests_total += 1
    if (
        key["organization_name"] == "max volley"
        and key["sport_season_code"] == "220"
        and key["season_year"] == 2024
        and key["num_weeks"] == 12
        and len(key) == 8
    ):
        tests_passed += 1
        print(f"  build_uniqueness_key: PASS (8 fields normalized)")
    else:
        print(f"  build_uniqueness_key: FAIL")

    print(f"\nPhase 2C: {tests_passed}/{tests_total} tests passed")
    return tests_passed == tests_total


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("PHASE 1 & 2 TEST SUITE")
    print("=" * 60)

    phase_2a_ok = test_sss_codes()
    phase_2b_ok = test_validators()
    phase_2c_ok = test_league_id_generator()

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Phase 2A (SSS Codes):      {'PASS' if phase_2a_ok else 'FAIL'}")
    print(f"Phase 2B (Validators):     {'PASS' if phase_2b_ok else 'FAIL'}")
    print(f"Phase 2C (League ID Gen):  {'PASS' if phase_2c_ok else 'FAIL'}")

    print()
    print("Phase 1 (Database Schema):")
    print("  SQL file ready: migrations/create_leagues_metadata.sql")
    print("  Execute in Supabase dashboard to complete Phase 1")
    print()

    if phase_2a_ok and phase_2b_ok and phase_2c_ok:
        print("All Phase 2 tests PASSED. Ready for Phase 3!")
        return 0
    else:
        print("Some tests FAILED. Review output above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
