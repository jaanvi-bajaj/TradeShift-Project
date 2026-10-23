"""Unit tests for batch/metrics.py: shares, HHI, growth, CAGR, event windows.

How to run: pytest tests/test_metrics.py
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from batch.metrics import (
    cagr,
    event_windows,
    hhi,
    hhi_table,
    market_shares,
    shift_month,
    tariffed_set,
    window_shares,
    yoy_growth,
)


def sample_trade() -> pd.DataFrame:
    """Two products, two months, three suppliers (values in US$)."""
    return pd.DataFrame(
        {
            "importer": "US",
            "hs6": ["845020"] * 6 + ["940360"] * 3,
            "month": ["2018-01"] * 3 + ["2018-02"] * 3 + ["2018-01"] * 3,
            "supplier": ["CN", "VN", "KR"] * 3,
            "value_usd": [60.0, 30.0, 10.0, 50.0, 25.0, 25.0, 1.0, 1.0, 2.0],
            "qty": [6.0, 3.0, 1.0, 5.0, 3.0, 2.0, np.nan, np.nan, np.nan],
        }
    )


def test_shares_sum_to_100_percent_per_product_month():
    """Brief, Testing: shares per product-month sum to 100%."""
    df = sample_trade()
    df["share"] = market_shares(df)
    sums = df.groupby(["importer", "hs6", "month"])["share"].sum()
    assert np.allclose(sums.to_numpy(), 1.0)


def test_hhi_hand_worked_example():
    """Shares 60/30/10: HHI = 60^2 + 30^2 + 10^2 = 3600 + 900 + 100 = 4600."""
    assert hhi([0.6, 0.3, 0.1]) == pytest.approx(4600.0)


def test_hhi_bounds():
    """One supplier gives 10,000; many equal suppliers approach 0."""
    assert hhi([1.0]) == pytest.approx(10_000.0)
    assert hhi([0.01] * 100) == pytest.approx(100.0)
    assert 0 <= hhi([0.2] * 5) <= 10_000


def test_hhi_table_matches_by_hand():
    out = hhi_table(sample_trade()).set_index(["hs6", "month"])
    assert out.loc[("845020", "2018-01"), "hhi"] == pytest.approx(4600.0)
    # 2018-02: shares 50/25/25 -> 2500 + 625 + 625 = 3750
    assert out.loc[("845020", "2018-02"), "hhi"] == pytest.approx(3750.0)
    assert out.loc[("940360", "2018-01"), "n_suppliers"] == 3


def test_yoy_growth():
    s = pd.Series([100.0] * 12 + [110.0] * 12)
    g = yoy_growth(s)
    assert math.isnan(g.iloc[0])
    assert g.iloc[12] == pytest.approx(10.0)


def test_cagr():
    assert cagr(100, 121, 2) == pytest.approx(10.0)
    assert math.isnan(cagr(0, 50, 2))


def test_shift_month_and_windows():
    assert shift_month("2018-01", -1) == "2017-12"
    assert shift_month("2018-12", 1) == "2019-01"
    before, after = event_windows("2018-07-06", 12, 2)
    assert before[0] == "2017-07" and before[-1] == "2018-06" and len(before) == 12
    assert after[0] == "2018-09" and after[-1] == "2019-08" and len(after) == 12


def test_window_shares_are_pooled_and_sum_to_one():
    trade = sample_trade()
    ws = window_shares(trade, ["2018-01"], ["2018-02"])
    w = ws[ws["hs6"] == "845020"].set_index("supplier")
    assert w["share_before"].sum() == pytest.approx(1.0)
    assert w.loc["CN", "share_before"] == pytest.approx(0.6)
    assert w.loc["CN", "share_after"] == pytest.approx(0.5)
    assert w.loc["CN", "qshare_before"] == pytest.approx(0.6)
    # The second product has no quantities, so its quantity shares are missing, not zero.
    assert ws[ws["hs6"] == "940360"]["qshare_before"].isna().all()


def test_tariffed_set_handles_all_eu_and_exemptions():
    """Section 232 style: everyone except exempt countries, with EU expanded."""
    event = pd.Series({"tariffed_suppliers": "ALL", "exempt_suppliers": "CA;EU"})
    result = tariffed_set(event, {"CN", "CA", "DE", "JP", "ROW"}, eu={"DE", "FR"})
    assert result == {"CN", "JP"}
    ext = pd.Series({"tariffed_suppliers": "CA;MX;EU", "exempt_suppliers": None})
    assert tariffed_set(ext, set(), eu={"DE"}) == {"CA", "MX", "DE"}
