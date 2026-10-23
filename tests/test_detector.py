"""Unit tests for batch/detector.py and batch/did_check.py.

How to run: pytest tests/test_detector.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from batch.detector import Thresholds, confidence, detect
from batch.did_check import did_estimate


def shares_frame() -> pd.DataFrame:
    """One event, two products. Product A: China 60% -> 40%, Vietnam 10% -> 25% (a clear shift).
    Product B: China 50% -> 48% (no shift)."""
    rows = [
        # event, hs6, supplier, tariffed, share_before, share_after, qshare_before, qshare_after
        ("E1", "AAAAAA", "CN", True, 0.60, 0.40, 0.58, 0.39),
        ("E1", "AAAAAA", "VN", False, 0.10, 0.25, 0.11, 0.27),
        ("E1", "AAAAAA", "MX", False, 0.30, 0.35, 0.31, 0.34),
        ("E1", "BBBBBB", "CN", True, 0.50, 0.48, np.nan, np.nan),
        ("E1", "BBBBBB", "VN", False, 0.50, 0.52, np.nan, np.nan),
    ]
    cols = ["event_id", "hs6", "supplier", "tariffed", "share_before", "share_after", "qshare_before", "qshare_after"]
    return pd.DataFrame(rows, columns=cols)


def products_frame(total_a: float = 100e6) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "event_id": ["E1", "E1"],
            "hs6": ["AAAAAA", "BBBBBB"],
            "total_before": [total_a, 100e6],
            "total_after": [110e6, 100e6],
            "hhi_before": [4600, 5000],
            "hhi_after": [3400, 5000],
            "hs_changed": [False, False],
        }
    )


def test_flags_clear_shift_and_picks_biggest_gainer():
    out = detect(shares_frame(), products_frame())
    assert len(out) == 1
    flag = out.iloc[0]
    assert flag["hs6"] == "AAAAAA" and flag["loser"] == "CN" and flag["gainer"] == "VN"
    assert flag["drop_pp"] == pytest.approx(20.0)
    assert flag["gain_pp"] == pytest.approx(15.0)
    # Redirected = min(20, 15) points x average annual imports (100m + 110m) / 2 = 15.75m
    assert flag["value_redirected_usd"] == pytest.approx(0.15 * 105e6)
    assert flag["confidence"] == "higher"
    assert flag["pattern"] == "diversion"


def test_thresholds_are_respected():
    assert detect(shares_frame(), products_frame(), Thresholds(min_drop_pp=25)).empty
    assert detect(shares_frame(), products_frame(), Thresholds(min_gain_pp=16)).empty
    # Below the annual value floor, nothing is flagged.
    assert detect(shares_frame(), products_frame(total_a=5e6), Thresholds(min_annual_value_usd=10e6)).empty


def test_tariffed_supplier_cannot_be_the_gainer():
    s = shares_frame()
    s.loc[s["supplier"] == "VN", "tariffed"] = True
    out = detect(s, products_frame())
    assert (out["gainer"] != "VN").all()


def test_trade_destruction_pattern():
    p = products_frame()
    p.loc[p["hs6"] == "AAAAAA", "total_after"] = 50e6  # imports halved
    out = detect(shares_frame(), p)
    assert out.iloc[0]["pattern"] == "diversion + trade destruction"


def test_confidence_labels():
    assert confidence(5.0, 3.0) == "higher"
    assert confidence(-1.0, 3.0) == "lower"
    assert confidence(np.nan, 3.0) == "value only"


def test_did_recovers_known_effect():
    """Simulated panel: tariffed products lose 10 points after the tariff; controls do not."""
    rng = np.random.default_rng(0)
    rows = []
    for k in range(40):
        treated = k < 20
        base = rng.uniform(0.2, 0.6)
        for t in range(24):
            after = t >= 12
            share = base + 0.002 * t - (0.10 if treated and after else 0) + rng.normal(0, 0.01)
            rows.append(
                {"hs6": f"{k:06d}", "month": f"m{t:02d}", "share": share, "treated": int(treated), "after": int(after)}
            )
    result = did_estimate(pd.DataFrame(rows))
    assert result["beta_pp"] == pytest.approx(-10.0, abs=0.5)
    assert result["se_pp"] > 0
    assert result["t_stat"] < -5
