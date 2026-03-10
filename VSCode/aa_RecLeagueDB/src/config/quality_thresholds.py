from enum import Enum

AUTO_REPLACE_THRESHOLD = 60   # Below this: super scrape auto-archives old + writes new if contradicted
DEEP_SCRAPE_THRESHOLD = 75    # Below this: League Checker triggers super scrape


class QualityBand(str, Enum):
    THIN       = "THIN"         # 0–59
    BORDERLINE = "BORDERLINE"   # 60–74
    ACCEPTABLE = "ACCEPTABLE"   # 75–89
    SUBSTANTIAL = "SUBSTANTIAL" # 90+


def get_quality_band(score: int | None) -> QualityBand:
    if score is None or score < AUTO_REPLACE_THRESHOLD:
        return QualityBand.THIN
    if score < DEEP_SCRAPE_THRESHOLD:
        return QualityBand.BORDERLINE
    if score < 90:
        return QualityBand.ACCEPTABLE
    return QualityBand.SUBSTANTIAL
