"""
research/basket_bc.py
=====================
H-basket-B (#164), H-basket-C (#165), H-tier-curve (#166), on the #167
tradable subset and — for B — on the full 82 alongside, so the filter's
effect is visible.

FIDELITY. Every trade still comes from pipeline.backtest_exit_geometry with
LIVE_GEOMETRY and walkforward's 2+2bps. Nothing is re-implemented.

THE ONE PIECE OF ENGINEERING. A 300-seed episode placebo over 82 tickers
and 2 windows is ~50,000 backtests if scored naively. Instead, per ticker,
backtest_exit_geometry is called ONCE with EVERY day painted STRONG_BUY.
Because that function resolves each confirmed day independently -- its own
row Close, its own ATR, its own forward bars -- the result is a complete
day -> trade lookup. Any labelling pattern is then a SUBSET of those
trades: paint days, take the confirmed ones, look them up. This is exact,
not an approximation, and `verify_lookup()` proves it reproduces
harness.incumbent_rows trade-for-trade before anything is reported.

EPISODE PLACEBO (registered in #167). Draws random runs matching the
incumbent's observed run-length distribution per ticker, because the
incumbent's signal days come in clustered runs and an independent-day
placebo is lower-variance than what it benchmarks.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import harness as H
import basket as B
import pipeline as p

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
G = p.LIVE_GEOMETRY
FEE, SLIP = 2.0, 2.0
SEEDS = 300
FOLDS = 4
MIN_FOLD_N, MIN_FOLDS = 10, 3


# ----------------------------------------------------------------- lookup
def day_trade_lookup(base, window, tier="STRONG_BUY"):
    """day -> trade, from ONE pipeline call with every day painted `tier`."""
    bars, merged = B.load(base)
    w = B.basket_windows()
    bars = bars[bars.index < w.lockbox[0]]
    m = merged[(merged.index >= window[0]) & (merged.index < window[1])].copy()
    if m.empty:
        return {}, m
    f = m[["Open", "High", "Low", "Close", "Volume"]].copy()
    f["direction"] = tier
    r = p.backtest_exit_geometry(
        f, bars, atr_source=G["atr_source"], stop_mult=G["stop_mult"],
        target_mult=G["target_mult"], max_hold_days=G["max_hold_days"],
        short_sma_filter=G["short_sma_filter"], confirm_days=G["confirm_days"],
        fee_bps=FEE, slippage_bps=SLIP)
    return {pd.Timestamp(t["date"]): t for t in r.get("trades", [])}, m


def confirmed_days(flags):
    """Days where this day AND the previous day carry the label."""
    f = flags.astype(bool)
    return f.index[(f & f.shift(1, fill_value=False)).values]


def runs_of(flags):
    """Lengths of maximal runs of consecutive True days."""
    f = flags.astype(bool).values
    out, cur = [], 0
    for v in f:
        if v:
            cur += 1
        elif cur:
            out.append(cur); cur = 0
    if cur:
        out.append(cur)
    return out


def verify_lookup(base, window):
    """The lookup must reproduce harness.incumbent_rows trade-for-trade."""
    lk, m = day_trade_lookup(base, window)
    if m.empty:
        return True
    obs = [lk[d] for d in confirmed_days(m["direction"].eq("STRONG_BUY")) if d in lk]
    bars, merged = B.load(base)
    w = B.basket_windows()
    ref = H.incumbent_rows(m, bars[bars.index < w.lockbox[0]], folds=1)[0]
    ref_tr = [t for r in ref["_results"] for t in r.get("trades", [])]
    if len(obs) != len(ref_tr):
        return False
    a = sorted((str(t["date"]), t["outcome"], round(t["pnl_r_net"], 6)) for t in obs)
    b = sorted((str(t["date"]), t["outcome"], round(t["pnl_r_net"], 6)) for t in ref_tr)
    return a == b


# ------------------------------------------------------------- statistics
def pooled_stats(trades, window, folds=FOLDS):
    """Pooled across tickers; folds cut by TIME over `window`."""
    if not trades:
        return {"n": 0, "episodes": 0, "win_pct": np.nan, "net_all": np.nan,
                "ex_best": np.nan, "folds_pos": 0, "folds_counted": 0,
                "total_R": np.nan, "maxDD_R": np.nan}
    df = pd.DataFrame(trades)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date")
    edges = pd.date_range(window[0], window[1], periods=folds + 1)
    fold = pd.cut(df["date"], edges, labels=False, include_lowest=True)
    res = []
    for k in range(folds):
        sub = df[fold == k]
        res.append(p.stats_from_trades(sub.to_dict("records")) if len(sub) else {"n": 0})
    counted = [r for r in res if r.get("n", 0) >= MIN_FOLD_N]
    folds_pos = sum(1 for r in counted if r.get("expectancy_r_net", 0) > 0)
    ex_best = np.nan
    if len(counted) >= MIN_FOLDS:
        tot_r = sum(r["expectancy_r_net"] * r["n"] for r in counted)
        tot_n = sum(r["n"] for r in counted)
        best = max(counted, key=lambda r: r["expectancy_r_net"] * r["n"])
        rest = tot_n - best["n"]
        if rest:
            ex_best = (tot_r - best["expectancy_r_net"] * best["n"]) / rest
    pnl = df["pnl_r_net"].values.astype(float)
    curve = np.cumsum(pnl)
    eps = 0
    for t, g in df.groupby("ticker") if "ticker" in df.columns else []:
        d = sorted(g["date"])
        eps += 1 + sum(1 for i in range(1, len(d)) if (d[i] - d[i - 1]).days > G["max_hold_days"])
    return {"n": len(df), "episodes": eps,
            "win_pct": 100 * (df["outcome"] == "target").mean(),
            "net_all": float(pnl.mean()),
            "ex_best": float(ex_best) if ex_best == ex_best else np.nan,
            "folds_pos": folds_pos, "folds_counted": len(counted),
            "total_R": float(curve[-1]),
            "maxDD_R": float(np.max(np.maximum.accumulate(curve) - curve))}


# ---------------------------------------------------------------- placebo
def episode_placebo(specs, window, seeds=SEEDS, folds=FOLDS):
    """specs: {ticker: (lookup, eligible_index, [run lengths])}.
    Each seed re-draws every ticker's runs at random start positions."""
    nets, exbs = [], []
    for s in range(seeds):
        rng = np.random.default_rng(500000 + s)
        pool = []
        for base, (lk, idx, runs) in specs.items():
            n = len(idx)
            if n < 3 or not runs:
                continue
            taken = np.zeros(n, dtype=bool)
            for L in runs:
                for _ in range(12):                       # a few placement tries
                    st = int(rng.integers(0, max(1, n - L)))
                    if not taken[st:st + L].any():
                        taken[st:st + L] = True
                        break
            flags = pd.Series(taken, index=idx)
            for d in confirmed_days(flags):
                t = lk.get(d)
                if t is not None:
                    pool.append(dict(t, ticker=base))
        st = pooled_stats(pool, window, folds=folds)
        nets.append(st["net_all"]); exbs.append(st["ex_best"])
    a = np.array([x for x in nets if x == x])
    b = np.array([x for x in exbs if x == x])
    return {"seeds": seeds, "valid": len(a),
            "mean": float(a.mean()) if len(a) else np.nan,
            "p95": float(np.percentile(a, 95)) if len(a) else np.nan,
            "p99": float(np.percentile(a, 99)) if len(a) else np.nan,
            "ex_p95": float(np.percentile(b, 95)) if len(b) else np.nan}


def gather(bases, window, tier="STRONG_BUY"):
    """Observed pooled trades + placebo specs for one window.

    INC_BUY_ALL mixes two CONVICTIONS, and conviction changes the geometry
    (STRONG_BUY targets reach 1.333x further -- R:R 2.667 vs 2.0). So it
    needs TWO lookups per ticker, and each confirmed day is resolved with
    the lookup matching the label it actually carried. Using one lookup for
    both would silently re-price every plain BUY as a STRONG_BUY.
    """
    trades, specs = [], {}
    mixed = (tier == "INC_BUY_ALL")
    for base in bases:
        lk_s, m = day_trade_lookup(base, window, tier="STRONG_BUY")
        if m.empty:
            continue
        lk_b = day_trade_lookup(base, window, tier="BUY")[0] if mixed else None
        want = {"BUY", "STRONG_BUY"} if mixed else {"STRONG_BUY"}
        lbl = m["direction"]
        # confirm_days=2 requires two IDENTICAL consecutive labels. A plain
        # BUY preceded by a STRONG_BUY does NOT confirm, so an isin() mask
        # would over-count. Match pipeline's `all(d == w[-1] for d in w)`.
        same = lbl.eq(lbl.shift(1)) & lbl.isin(want)
        flags = lbl.isin(want)
        for d in m.index[same.values]:
            src = lk_s if (not mixed or lbl.get(d) == "STRONG_BUY") else lk_b
            t = src.get(d) if src else None
            if t is not None:
                trades.append(dict(t, ticker=base))
        specs[base] = (lk_s, m.index, runs_of(flags))
        B._CACHE.pop(base, None)
    return trades, specs
