"""
research/basket.py
==================
EVENT RATE (basket) scoring. Registered as #163-#166 in docs/cleanroom.md
BEFORE this ran.

H-basket-A (#163): run the incumbent UNCHANGED on every ticker and report,
per ticker, STRONG_BUY trades / episodes / whether `ex_best` is DEFINED.
Headline = how many tickers reach a defined `ex_best`.

All trade decisions come from pipeline via research/harness.py. Nothing
here re-implements trade logic, and no threshold is touched.

COMMON WINDOWS. harness.make_windows anchors on each frame's own first
date, so 86 tickers would get 86 different DISCOVERY/CONFIRMATION cuts and
pooling would be incoherent. The basket derives ONE set of windows from
BTC and applies it to every ticker; a ticker contributes no trades before
it listed. Registered under "COMMON BASKET WINDOWS".

The lockbox (last 6 months) is never read: the daily frames are cut at the
boundary and the 4h feed is sealed with harness.seal_bars, so a trade near
the edge cannot resolve on sealed bars.
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import harness as H
import pipeline as p

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASKET = os.path.join(ROOT, "data", "basket")
MAX_HOLD_DAYS = p.LIVE_GEOMETRY["max_hold_days"]

_CACHE = {}


def available():
    """Bases with both frozen frames present."""
    if not os.path.isdir(BASKET):
        return []
    b = {f.split("_4h.csv.gz")[0] for f in os.listdir(BASKET) if f.endswith("_4h.csv.gz")}
    m = {f.split("_merged.csv.gz")[0] for f in os.listdir(BASKET) if f.endswith("_merged.csv.gz")}
    return sorted(b & m)


def load(base):
    """(bars_4h, merged) for one basket ticker. Cached per ticker (rule 8)."""
    if base in _CACHE:
        return _CACHE[base]
    bars = pd.read_csv(os.path.join(BASKET, base + "_4h.csv.gz"),
                       index_col=0, parse_dates=True).sort_index()
    merged = pd.read_csv(os.path.join(BASKET, base + "_merged.csv.gz"),
                         index_col=0, parse_dates=True).sort_index()
    _CACHE[base] = (bars, merged)
    return bars, merged


def basket_windows():
    """ONE set of windows for the whole basket, anchored on BTC."""
    bars, _ = load("BTC")
    daily = H.resample_4h_to_daily(bars)
    return H.make_windows(daily)


def episodes(trades, gap_days=MAX_HOLD_DAYS):
    """Trades separated by more than the max hold are independent episodes."""
    if not trades:
        return 0
    d = sorted(pd.Timestamp(t["date"]) for t in trades)
    return 1 + sum(1 for i in range(1, len(d)) if (d[i] - d[i - 1]).days > gap_days)


def score_ticker(base, window, tier="STRONG_BUY", folds=4):
    """The incumbent, unchanged, on one ticker over `window`."""
    bars, merged = load(base)
    w = basket_windows()
    bars = bars[bars.index < w.lockbox[0]]          # seal the 4h feed
    mwin = merged[(merged.index >= window[0]) & (merged.index < window[1])]
    if mwin.empty or "direction" not in mwin.columns:
        return None
    rows = H.incumbent_rows(mwin, bars, folds=folds)
    row = rows[0] if tier == "STRONG_BUY" else rows[1]
    trades = [t for r in row["_results"] for t in r.get("trades", [])]
    return {
        "ticker": base,
        "daily_rows": len(mwin),
        "first": str(mwin.index.min())[:10],
        "last": str(mwin.index.max())[:10],
        "event_days": int(mwin["direction"].eq("STRONG_BUY").sum()) if tier == "STRONG_BUY"
                      else int(mwin["direction"].isin(["BUY", "STRONG_BUY"]).sum()),
        "n": row["n"],
        "episodes": episodes(trades),
        "win_pct": row["win_pct"],
        "net_all": row["net_all"],
        "ex_best": row["ex_best"],
        "ex_best_defined": row["ex_best"] == row["ex_best"],
        "folds_counted": row["folds_counted"],
        "folds_pos": row["folds_pos"],
        "total_R": row["total_R"],
        "trades": trades,
    }


def run_A(tier="STRONG_BUY", folds=4):
    w = basket_windows()
    sealed = (w.discovery[0], w.lockbox[0])          # SEALED = the usable span
    bases = available()
    print("H-basket-A (#163) — incumbent UNCHANGED, %s tier" % tier)
    print("SEALED window %s -> %s (lockbox %s -> %s NEVER read)"
          % (sealed[0].date(), sealed[1].date(), w.lockbox[0].date(), w.lockbox[1].date()))
    print("tickers with frozen frames: %d\n" % len(bases))
    recs = []
    for i, b in enumerate(bases, 1):
        try:
            r = score_ticker(b, sealed, tier=tier, folds=folds)
        except Exception as e:
            print("  %-8s FAILED %s: %s" % (b, type(e).__name__, str(e)[:80]))
            continue
        if r is None:
            print("  %-8s no usable rows" % b)
            continue
        recs.append(r)
        if i % 20 == 0:
            print("  ...%d/%d" % (i, len(bases)))
        _CACHE.pop(b, None)                          # free memory, keep ATR cache
    df = pd.DataFrame([{k: v for k, v in r.items() if k != "trades"} for r in recs])
    df.to_csv(os.path.join(ROOT, "research", "basket_A_%s.csv" % tier.lower()), index=False)
    return df, recs, sealed, w


if __name__ == "__main__":
    tier = sys.argv[1] if len(sys.argv) > 1 else "STRONG_BUY"
    df, recs, sealed, w = run_A(tier=tier)
    df = df.sort_values("n", ascending=False)
    print("\n%-9s %6s %6s %8s %7s %8s %9s %8s" %
          ("ticker", "events", "n", "episodes", "win%", "net_all", "ex_best", "folds"))
    print("-" * 74)
    for _, r in df.iterrows():
        eb = "—" if not r.ex_best_defined else "%+.3f" % r.ex_best
        print("%-9s %6d %6d %8d %7s %8s %9s %8s"
              % (r.ticker, r.event_days, r.n, r.episodes,
                 "%.1f" % r.win_pct if r.n else "—",
                 "%+.3f" % r.net_all if r.n else "—",
                 eb, "%d/%d" % (r.folds_pos, r.folds_counted)))
    n_def = int(df.ex_best_defined.sum())
    print("\n" + "=" * 74)
    print("HEADLINE: %d of %d tickers reach a DEFINED ex_best (>=3 folds with >=10 trades)"
          % (n_def, len(df)))
    print("=" * 74)
    print("  tickers with 0 STRONG_BUY trades : %d" % int((df.n == 0).sum()))
    print("  median trades per ticker         : %.0f" % df.n.median())
    print("  total %s trades across basket : %d" % (tier, int(df.n.sum())))
    print("  total episodes across basket     : %d" % int(df.episodes.sum()))
