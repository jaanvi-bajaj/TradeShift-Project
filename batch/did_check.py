"""Difference-in-differences check: did tariffed products lose more share than similar untariffed ones?

What it does:
    Once per tariff event (not per product), it estimates (Methodology 4.4):

        share(k, t) = a(k) + g(t) + beta x [Tariffed(k) x After(t)] + e

    share(k, t) is the tariffed suppliers' combined share of US imports of product k
    in month t. Treated products are the HS6 codes the event covers; controls are
    untariffed HS6 codes in the same HS4 headings. beta < 0 means the tariffed
    suppliers lost more share in tariffed products than in similar untariffed ones.
    This validates the detector; it is not a per-product causal claim (Known limits).

    Why numpy, not a stats library: the two-way fixed effects are removed by
    repeatedly subtracting product and month means, after which beta is a
    one-variable regression. Every group member can follow that by hand.

Inputs:
    processed/trade/US/*.csv.gz, data/tariff_events.csv, data/tariff_event_products.csv,
    processed/event_products.csv.gz (for HS revision flags).

Outputs:
    processed/did_results.csv.gz, one row per event: beta (points), standard error
    clustered by product, t-statistic, counts of treated and control products.

How to run:
    python -m batch.did_check
"""

from __future__ import annotations

import logging
import math

import pandas as pd

from batch.metrics import event_windows, load_trade, tariffed_set
from batch.storage_io import store
from config.logging_config import setup_logging
from config.settings import settings

log = logging.getLogger("did_check")

# Controls must not be hit by a related action at the same time, or they would not
# be "untariffed". Section 301 lists overlap in time, as do the Section 232 waves.
RELATED_EVENTS = {"Section 301": "S301_", "Section 232": "S232_", "Section 201": "S201_", "Anti-dumping": "AD_"}


def demean_two_way(df: pd.DataFrame, cols: list[str], iters: int = 50, tol: float = 1e-10) -> pd.DataFrame:
    """Remove product and month fixed effects by alternating mean subtraction.

    Why iterate: with an unbalanced panel (some product-months missing), one pass
    of subtracting product and month means is not exact; repeating converges.

    Args:
        df: Panel with columns hs6, month and the variables to transform.
        cols: Variables to demean.
        iters: Maximum passes.
        tol: Stop when the largest adjustment is below this.

    Returns:
        DataFrame of the demeaned columns, same index as df.
    """
    out = df[cols].astype(float).copy()
    for _ in range(iters):
        before = out.copy()
        out -= out.groupby(df["hs6"]).transform("mean")
        out -= out.groupby(df["month"]).transform("mean")
        if (out - before).abs().to_numpy().max() < tol:
            break
    return out


def did_estimate(panel: pd.DataFrame) -> dict[str, float]:
    """Estimate beta with product and month fixed effects and product-clustered errors.

    Args:
        panel: Rows of hs6, month, share (fraction), treated (0/1), after (0/1).

    Returns:
        {"beta_pp", "se_pp", "t_stat", "p_value", "n_obs"}; beta and se in percentage points.
    """
    panel = panel.assign(d=panel["treated"] * panel["after"], y=100 * panel["share"])
    dm = demean_two_way(panel, ["y", "d"])
    x, y = dm["d"].to_numpy(), dm["y"].to_numpy()
    sxx = float(x @ x)
    if sxx == 0:
        return {"beta_pp": math.nan, "se_pp": math.nan, "t_stat": math.nan, "p_value": math.nan, "n_obs": len(panel)}
    beta = float(x @ y) / sxx
    resid = y - beta * x
    # Cluster-robust variance: sum over products of (sum of x*e within product)^2.
    scores = pd.Series(x * resid).groupby(panel["hs6"].to_numpy()).sum().to_numpy()
    g, n = len(scores), len(y)
    correction = g / (g - 1) * (n - 1) / max(n - 2, 1) if g > 1 else 1.0
    se = math.sqrt(correction * float(scores @ scores)) / sxx
    t = beta / se if se > 0 else math.nan
    p = math.erfc(abs(t) / math.sqrt(2)) if not math.isnan(t) else math.nan  # normal approximation
    return {"beta_pp": beta, "se_pp": se, "t_stat": t, "p_value": p, "n_obs": n}


def build_panel(
    us: pd.DataFrame, treated: set[str], controls: set[str], tariffed: set[str], before: list[str], after: list[str]
) -> pd.DataFrame:
    """Monthly tariffed-supplier share for treated and control products in the windows.

    Args:
        us: US tidy trade rows.
        treated: HS6 codes covered by the event.
        controls: Untariffed HS6 codes in the same HS4 headings.
        tariffed: Supplier codes hit by the event.
        before: Before-window months.
        after: After-window months (the lag months are already left out).

    Returns:
        hs6, month, share, treated, after.
    """
    months = before + after
    sub = us[us["hs6"].isin(treated | controls) & us["month"].isin(months)]
    total = sub.groupby(["hs6", "month"])["value_usd"].sum()
    hit = sub[sub["supplier"].isin(tariffed)].groupby(["hs6", "month"])["value_usd"].sum()
    panel = (hit.reindex(total.index).fillna(0) / total).rename("share").reset_index()
    panel["treated"] = panel["hs6"].isin(treated).astype(int)
    panel["after"] = panel["month"].isin(after).astype(int)
    return panel


def run() -> pd.DataFrame:
    """Run the DiD check for every event and save one row per event."""
    events = pd.read_csv(settings.events_file, dtype=str)
    windows = [event_windows(d, settings.window_months, settings.lag_months) for d in events["effective_date"]]
    us = load_trade("US", min(b[0] for b, _ in windows), max(a[-1] for _, a in windows))
    event_products = pd.read_csv(settings.event_products_file, dtype=str)
    summary = store.read_df(f"{settings.processed_prefix}event_products.csv.gz", dtype={"hs6": str})
    countries = pd.read_csv(settings.country_file, dtype=str, keep_default_na=False)
    eu = set(countries.loc[countries["is_eu"] == "1", "iso2"])

    # Only products big enough to pass the detector's value floor enter the regression,
    # so a handful of tiny lines cannot dominate it.
    # Average over the event-window years only, which is all that is loaded.
    annual = us.groupby(["hs6", us["month"].str[:4]])["value_usd"].sum().groupby("hs6").mean()
    big_enough = set(annual[annual >= settings.min_annual_value_usd].index)

    rows = []
    for _, ev in events.iterrows():
        before, after = event_windows(ev["effective_date"], settings.window_months, settings.lag_months)
        treated = set(event_products.loc[event_products["event_id"] == ev["event_id"], "hs6"])
        changed = set(summary.loc[(summary["event_id"] == ev["event_id"]) & summary["hs_changed"].astype(bool), "hs6"])
        prefix = RELATED_EVENTS.get(ev["measure"], ev["event_id"])
        related = set(event_products.loc[event_products["event_id"].str.startswith(prefix), "hs6"])
        headings = {code[:4] for code in treated}
        controls = {c for c in us["hs6"].unique() if c[:4] in headings and c not in related}
        # Codes that changed at an HS revision inside the windows are left out (Data rules).
        treated = (treated & big_enough) - changed
        controls = (controls & big_enough) - changed
        result = {"event_id": ev["event_id"], "n_treated": len(treated), "n_control": len(controls)}
        if treated and controls:
            panel = build_panel(us, treated, controls, tariffed_set(ev, set(countries["iso2"]), eu), before, after)
            result |= did_estimate(panel)
        else:
            result |= {"beta_pp": math.nan, "se_pp": math.nan, "t_stat": math.nan, "p_value": math.nan, "n_obs": 0}
        log.info(
            "%s: beta=%.2f pp (se %.2f), %d treated vs %d controls",
            ev["event_id"],
            result["beta_pp"],
            result["se_pp"],
            result["n_treated"],
            result["n_control"],
        )
        rows.append(result)

    out = pd.DataFrame(rows)
    store.write_df(f"{settings.processed_prefix}did_results.csv.gz", out)
    return out


if __name__ == "__main__":
    setup_logging()
    run()
