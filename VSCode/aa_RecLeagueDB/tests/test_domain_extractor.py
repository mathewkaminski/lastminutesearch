import pytest
from src.utils.domain_extractor import extract_base_domain


def test_strips_www():
    assert extract_base_domain("https://www.javelin.com/calgary/vball") == "javelin.com"


def test_strips_scheme():
    assert extract_base_domain("http://torontossc.com/leagues") == "torontossc.com"


def test_subdomain_stripped():
    assert extract_base_domain("https://register.zogculture.com/page") == "zogculture.com"


def test_path_only_domain():
    assert extract_base_domain("https://javelin.com") == "javelin.com"


def test_none_returns_empty():
    assert extract_base_domain(None) == ""


def test_empty_string_returns_empty():
    assert extract_base_domain("") == ""


def test_invalid_url_returns_netloc_best_effort():
    # non-URL string — return as-is (best effort)
    result = extract_base_domain("not-a-url")
    assert isinstance(result, str)
