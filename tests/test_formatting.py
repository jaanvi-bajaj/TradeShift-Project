"""Unit tests for app/formatting.py (Feature 1: no raw values like 4.07e+09).

How to run: pytest tests/test_formatting.py
"""

from __future__ import annotations

import math

from app.formatting import format_value, hhi, hs_label, month_label, pct, points, signed_pct, usd_millions


def test_usd_millions_never_shows_scientific_notation():
    assert usd_millions(4.07e9) == "US$4,070.0m"
    assert "e+" not in usd_millions(1.23e12)
    assert usd_millions(None) == "–"
    assert usd_millions(math.nan) == "–"


def test_percentages_and_points():
    assert pct(41.234) == "41.2%"
    assert pct(0.412, fraction=True) == "41.2%"
    assert signed_pct(-12.34) == "-12.3%"
    assert signed_pct(4) == "+4.0%"
    assert points(-21) == "-21.0 pts"


def test_hhi_is_whole_number_with_commas():
    assert hhi(3821.7) == "3,822"
    assert hhi(10000) == "10,000"


def test_labels():
    assert month_label("2018-07") == "Jul 2018"
    assert month_label("2018-07-06") == "Jul 2018"
    assert hs_label("845020") == "8450.20"
    assert format_value(2.5e6, "usd_m") == "US$2.5m"
    assert format_value(None, "unknown") == "–"
