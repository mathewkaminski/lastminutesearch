"""Project-level pytest configuration."""

collect_ignore = [
    "tests/test_phase3.py",  # Standalone script with top-level sys.exit(); not a pytest test
]
