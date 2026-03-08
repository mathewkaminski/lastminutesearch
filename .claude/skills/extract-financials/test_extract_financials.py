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
