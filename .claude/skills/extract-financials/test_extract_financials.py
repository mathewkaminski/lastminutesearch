import sys
from extract_financials import check_deps


def test_missing_dependency_message():
    """check_deps() prints install instructions for missing packages."""
    missing = check_deps(required=["nonexistent_package_xyz"])
    assert len(missing) == 1
    assert "nonexistent_package_xyz" in missing[0]

def test_no_missing_dependencies():
    """check_deps() returns empty list when all packages present."""
    missing = check_deps(required=["sys", "os"])
    assert missing == []


def test_extract_all_pages_returns_list():
    """extract_pages() returns a list of dicts with page_number, text, tables."""
    from extract_financials import extract_pages
    pdf_path = r"C:\Users\mathe\OneDrive\Documents\Consulting\JAM\JAM - Investor Deck for Mat & Orin.pdf"
    pages = extract_pages(pdf_path)
    assert isinstance(pages, list)
    assert len(pages) > 0
    assert "page_number" in pages[0]
    assert "text" in pages[0]
    assert "tables" in pages[0]

def test_extract_pages_includes_text():
    """Pages with known content return non-empty text."""
    from extract_financials import extract_pages
    pdf_path = r"C:\Users\mathe\OneDrive\Documents\Consulting\JAM\JAM - Investor Deck for Mat & Orin.pdf"
    pages = extract_pages(pdf_path)
    # Page 8 (index 7) has Revenue data in it
    page_8 = next(p for p in pages if p["page_number"] == 8)
    assert "Revenue" in page_8["text"]
