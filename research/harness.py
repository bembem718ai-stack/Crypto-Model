"""
research/harness.py
===================
Score a daily boolean EVENT SERIES through the incumbent's exact trade
machinery. This file owns NO trading logic of its own.

Everything that decides a trade's fate comes from pipeline.py:

    pipeline.LIVE_GEOMETRY          the production geometry (4h ATR, 15d
                                    hold, 1.5x stop, 3.0x target, 2-day
                                    confirm, 50d SMA short filter)
    pipeline.evaluate_geometry_folds  fold splitting + per-fold backtest
    pipeline.backtest_exit_geometry   entry/exit resolution on 4h bars
    pipeline.stats_from_trades        every summary statistic
    pipeline.concentration_report     the ex-best-fold arithmetic
    walkforward's cost defaults       2bps fee + 2bps slippage PER SIDE

What this module adds is only PLUMBING: build a daily frame, paint a
`direction` column onto it from an event series, hand it to the incumbent,
and read the answer back.

WHY THE STRONG_BUY DISTINCTION MATTERS
--------------------------------------
signal_engines.compute_exit_levels scales the target by conviction:
STRONG_BUY reaches 1.333x further than a plain BUY, with the stop
unchanged. So STRONG_BUY trades are R:R 2.667 and BUY trades are R:R 2.0.
A placebo for the incumbent's STRONG_BUY row must therefore be painted
STRONG_BUY too, or it would be a comparison against different geometry
and would flatter or damn the incumbent for the wrong reason.

EVENT CONVENTION
----------------
An event on day E labels BOTH day E and day E+1 as BUY. The incumbent's
confirm_days=2 requires two identical consecutive labels, so the trade
confirms on E+1 and enters at the close of E+1 — one event, one trade,
entered the day after the event. Non-event days are WATCH.

Usage:
    python research/harness.py --self-test   # synthetic random walk, 3 seeds
    python research/harness.py --reference   # reference rows, DISCOVERY
"""

import os
import sys
import argparse
from collections import namedtuple

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pipeline as p  # noqa: E402

try:                      # Windows consoles default to cp1252
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

# Costs: walkforward's defaults, PER SIDE (8bps round trip).
FEE_BPS = 2.0
SLIPPAGE_BPS = 2.0

# concentration_report's rule, restated here only as arguments to it.
MIN_FOLD_N = 10          # a fold "counts" at 10+ trades
MIN_COUNTED_FOLDS = 3    # ex-best needs 3+ counted folds

BARS_PER_DAY = 6         # 4h bars


# ----------------------------------------------------------------------
# 4h ATR MEMOIZATION (Research rule 8)
# ----------------------------------------------------------------------
# pipeline.backtest_exit_geometry rebuilds the 4h ATR on EVERY call
# (pipeline.py:1612), so a 120-rule grid over 3 tickers x 4 folds pays for
# it 1,440 times for 3 distinct answers. It depends only on the feed, never
# on the rule being scored.
#
# Research may not edit pipeline.py (rule 1), so the cache is installed
# around it here. This is a pure memoization: same feed in, same Series
# out. `verify_atr_cache()` proves that rather than asserting it.
_ATR4_CACHE = {}
_ATR4_UNCACHED = p.build_4h_atr


def _atr4_key(bars_4h, period):
    idx = bars_4h.index
    return (period, len(bars_4h), idx[0], idx[-1],
            float(bars_4h["Close"].iloc[0]), float(bars_4h["Close"].iloc[-1]))


def _cached_build_4h_atr(bars_4h, period: int = 14):
    if bars_4h is None or not len(bars_4h):
        return _ATR4_UNCACHED(bars_4h, period)
    key = _atr4_key(bars_4h, period)
    hit = _ATR4_CACHE.get(key)
    if hit is None:
        hit = _ATR4_UNCACHED(bars_4h, period)
        _ATR4_CACHE[key] = hit
    return hit


p.build_4h_atr = _cached_build_4h_atr


def verify_atr_cache(bars_4h, period: int = 14) -> bool:
    """Prove the cache returns exactly what pipeline would have."""
    got = _cached_build_4h_atr(bars_4h, period)
    want = _ATR4_UNCACHED(bars_4h, period)
    return got.equals(want)

DISCOVERY_FRAC = 0.55

Windows = namedtuple("Windows", "discovery confirmation lockbox last_date")


# ======================================================================
# DATA
# ======================================================================

def load_ticker(ticker: str):
    """Return (bars_4h, merged, daily).

    bars_4h  the frozen 4h feed — exit resolution and the 4h ATR
    merged   the incumbent's own daily frame, including its `direction`
    daily    daily bars RESAMPLED from the 4h feed (UTC days), which is
             what new models are built on
    """
    bars_4h = pd.read_csv(os.path.join(DATA_DIR, f"{ticker}_4h.csv"),
                          index_col=0, parse_dates=True).sort_index()
    merged = pd.read_csv(os.path.join(DATA_DIR, f"{ticker}_merged.csv"),
                         index_col=0, parse_dates=True).sort_index()
    daily = resample_4h_to_daily(bars_4h)
    return bars_4h, merged, daily


def resample_4h_to_daily(bars_4h: pd.DataFrame) -> pd.DataFrame:
    """UTC calendar days from the 4h feed.

    Partial days are dropped at BOTH ends. The trailing one because it is
    still forming (the spec's requirement); the leading one because a day
    built from 4 of its 6 bars has a wrong Open/High/Low, and letting it
    seed the indicator warm-up would be a silent data error.
    """
    agg = {"Open": "first", "High": "max", "Low": "min",
           "Close": "last", "Volume": "sum"}
    d = bars_4h.resample("1D").agg(agg).dropna(subset=["Close"])
    counts = bars_4h.resample("1D").size().reindex(d.index).fillna(0)
    if len(d) and counts.iloc[-1] < BARS_PER_DAY:
        d, counts = d.iloc[:-1], counts.iloc[:-1]
    if len(d) and counts.iloc[0] < BARS_PER_DAY:
        d = d.iloc[1:]
    return d


def make_windows(daily: pd.DataFrame, discovery_frac: float = DISCOVERY_FRAC) -> Windows:
    """Anchor every window on the DATASET's last date, never the wall clock.

    pipeline.apply_lockbox cuts at `Timestamp.now() - 6 months`, which would
    make results drift with the calendar and be unreproducible from a frozen
    dataset. Same 6-month rule (pipeline.LOCKBOX_MONTHS), different anchor.
    """
    last = daily.index.max()
    lockbox_start = last - pd.DateOffset(months=p.LOCKBOX_MONTHS)
    avail = daily[daily.index < lockbox_start]
    start, end = avail.index.min(), avail.index.max()
    cut = start + (end - start) * discovery_frac      # split in TIME
    return Windows(discovery=(start, cut),
                   confirmation=(cut, lockbox_start),
                   lockbox=(lockbox_start, last),
                   last_date=last)


def seal_bars(bars_4h: pd.DataFrame, w: Windows, window_name: str) -> pd.DataFrame:
    """Truncate the 4h feed at the lockbox boundary.

    WHY THIS EXISTS: exit resolution runs on the 4h feed, and a trade
    entered near the end of a window keeps resolving for up to
    max_hold_days afterwards. Handing pipeline the FULL feed therefore lets
    a CONFIRMATION-tail trade resolve on sealed bars — reading the lockbox,
    which research rule 2 forbids without exception ("not for fitting, not
    for plotting, not just to look").

    Trades that cannot resolve before the seal come back with outcome None
    and pipeline drops them (backtest_exit_geometry line ~1652). That is
    the conservative direction: a trade we are not allowed to see the end
    of is not counted, rather than counted with a guessed ending.

    For DISCOVERY this is a no-op — it ends years before the seal — and
    that is asserted rather than assumed by --prove-seal.
    """
    if window_name == "lockbox":
        raise ValueError("refusing to score the lockbox window")
    return bars_4h[bars_4h.index < w.lockbox[0]]


def slice_window(df: pd.DataFrame, window) -> pd.DataFrame:
    """[lo, hi) — half-open, so DISCOVERY and CONFIRMATION never share a day."""
    lo, hi = window
    return df[(df.index >= lo) & (df.index < hi)]


def print_windows(w: Windows, daily: pd.DataFrame, label: str = ""):
    print(f"\nWindows{(' — ' + label) if label else ''} "
          f"(anchored on dataset last date {w.last_date.date()}):")
    for name, win in (("DISCOVERY", w.discovery), ("CONFIRMATION", w.confirmation),
                      ("LOCKBOX", w.lockbox)):
        s = slice_window(daily, win)
        span = (win[1] - win[0]).days / 365.25
        seal = "  *** SEALED — never read by research ***" if name == "LOCKBOX" else ""
        print(f"  {name:<13} {win[0].date()} -> {win[1].date()}  "
              f"({len(s):>4} days, {span:.2f}y){seal}")


# ======================================================================
# EVENTS -> DIRECTION LABELS
# ======================================================================

def paint_labels(index: pd.DatetimeIndex, events: pd.Series, label: str = "BUY") -> pd.Series:
    """Event day AND the following day carry `label`; everything else WATCH."""
    ev = events.reindex(index).fillna(False).astype(bool)
    painted = ev | ev.shift(1, fill_value=False)
    return pd.Series(np.where(painted.values, label, "WATCH"), index=index)


def eligible_days(frame: pd.DataFrame) -> pd.DatetimeIndex:
    """Days that could carry an event: all but the last, which has no
    following day to confirm on."""
    return frame.index[:-1]


# ======================================================================
# SCORING — everything below defers to pipeline.py
# ======================================================================

def _subset_folds(results: list, wanted: set) -> list:
    """Filter each fold's trade list to `wanted` directions, re-summarised by
    pipeline.stats_from_trades. This is the mechanism evaluate_geometry_folds
    itself uses for direction='buy' — identical arithmetic, just a subset."""
    out = []
    for r in results:
        if not r.get("trades"):
            out.append({"n": 0})
            continue
        out.append(p.stats_from_trades([t for t in r["trades"]
                                        if t["direction"] in wanted]))
    return out


def _ex_best(results: list):
    """(net_counted, ex_best, n_counted_folds, folds_positive, trades_counted).

    NOTE net_counted is concentration_report's "all counted folds" figure,
    which EXCLUDES folds under MIN_FOLD_N and is undefined below
    MIN_COUNTED_FOLDS. The reported `net_all` column is instead the pooled
    net expectancy over every trade in the window, which is always defined
    -- a rule firing ~36 times puts ~9 trades in each of 4 folds, so the
    counted-folds figure would be NaN for most of the grid and could not be
    compared against a placebo at all.

    The arithmetic is concentration_report's, and it is CHECKED against
    concentration_report's own output on every call — if pipeline.py ever
    changes that rule, this raises instead of silently reporting a stale one.
    """
    counted = [r for r in results if r.get("n", 0) >= MIN_FOLD_N]
    folds_pos = sum(1 for r in counted if r.get("expectancy_r_net", 0) > 0)
    if len(counted) < MIN_COUNTED_FOLDS:
        return float("nan"), float("nan"), len(counted), folds_pos, 0

    tot_r = sum(r["expectancy_r_net"] * r["n"] for r in counted)
    tot_n = sum(r["n"] for r in counted)
    best = max(counted, key=lambda r: r["expectancy_r_net"] * r["n"])
    rest_n = tot_n - best["n"]
    net_all = tot_r / tot_n if tot_n else float("nan")
    ex_best = ((tot_r - best["expectancy_r_net"] * best["n"]) / rest_n
               if rest_n else float("nan"))

    _verify(results, net_all, ex_best)
    return net_all, ex_best, len(counted), folds_pos, tot_n


def _verify(results, net_all, ex_best):
    """Cross-check against pipeline.concentration_report's printed numbers."""
    text = p.concentration_report(results, min_n=MIN_FOLD_N)
    try:
        said_all = float(text.split("all counted folds:")[1].split("R over")[0])
        said_ex = float(text.split("excluding best fold:")[1].split("R over")[0])
    except (IndexError, ValueError):
        return  # not the 3-fold form; nothing to check against
    # concentration_report prints at 3dp, so a full-precision value can sit up
    # to half an ulp (0.0005) from the printed one with NOTHING wrong -- an
    # absolute tolerance at that boundary false-positives on exact agreement
    # (-0.4035 vs a printed -0.404 aborted a whole grid run). Round OUR value
    # the same way instead: identical strings mean identical numbers, and any
    # genuine drift of >=0.001 still trips it.
    for mine, theirs, what in ((net_all, said_all, "net_all"), (ex_best, said_ex, "ex_best")):
        if theirs == theirs and f"{mine:+.3f}" != f"{theirs:+.3f}":
            raise AssertionError(
                f"{what} disagrees with pipeline.concentration_report: "
                f"{mine:.6f} vs {theirs:.3f}. The harness is stale.")


def _trade_shape(results: list) -> dict:
    """Path statistics the summary dict does not carry: total R, drawdown
    of the net-R curve, and the worst losing streak. Computed from the
    trade records pipeline produced — not a re-simulation."""
    trades = [t for r in results for t in r.get("trades", [])]
    if not trades:
        return {"total_R": float("nan"), "maxDD_R": float("nan"), "worst_streak": 0}
    trades.sort(key=lambda t: t["date"])
    pnl = np.array([t["pnl_r_net"] for t in trades], dtype=float)
    curve = np.cumsum(pnl)
    maxdd = float(np.max(np.maximum.accumulate(curve) - curve)) if len(curve) else 0.0
    streak = worst = 0
    for x in pnl:
        streak = streak + 1 if x < 0 else 0
        worst = max(worst, streak)
    return {"total_R": float(curve[-1]), "maxDD_R": maxdd, "worst_streak": int(worst)}


def score_labels(frame: pd.DataFrame, bars_4h: pd.DataFrame, labels: pd.Series,
                 folds: int = 4, wanted: set = None, name: str = "") -> dict:
    """Score a fully-labelled frame through the incumbent's machinery."""
    # Hand pipeline ONLY the columns it reads. backtest_exit_geometry walks
    # the frame with iterrows(), so every extra column is materialised into
    # every row Series -- and a research feature frame carries ~60 of them.
    # Slimming is behaviour-preserving (proved by verify_slim_equivalence)
    # and is where the per-rule cost actually lives; the 4h ATR rebuild is
    # a rounding error next to it.
    keep = [c for c in ("Open", "High", "Low", "Close", "Volume",
                        "combined_final_score") if c in frame.columns]
    f = frame[keep].copy()
    f["direction"] = labels.reindex(f.index).fillna("WATCH").values
    g = p.LIVE_GEOMETRY
    results = p.evaluate_geometry_folds(
        f, bars_4h, folds,
        atr_source=g["atr_source"], max_hold_days=g["max_hold_days"],
        stop_mult=g["stop_mult"], target_mult=g["target_mult"],
        confirm_days=g["confirm_days"], short_sma_filter=g["short_sma_filter"],
        fee_bps=FEE_BPS, slippage_bps=SLIPPAGE_BPS, verbose=False)
    if wanted is not None:
        results = _subset_folds(results, wanted)

    pooled = p.stats_from_trades([t for r in results for t in r.get("trades", [])])
    net_counted, ex_best, n_counted, folds_pos, n_in_counted = _ex_best(results)
    row = {"name": name,
           "n": pooled.get("n", 0),
           "win_pct": 100 * pooled.get("target_rate", float("nan")),
           "stop_pct": 100 * pooled.get("stop_rate", float("nan")),
           "net_all": pooled.get("expectancy_r_net", float("nan")),
           "net_counted": net_counted,
           "ex_best": ex_best,
           "folds_pos": folds_pos,
           "folds_counted": n_counted,
           "n_counted": n_in_counted}
    row.update(_trade_shape(results))
    row["_results"] = results
    return row


def score_events(frame: pd.DataFrame, bars_4h: pd.DataFrame, events: pd.Series,
                 folds: int = 4, label: str = "BUY", name: str = "") -> dict:
    """Score a boolean event series (the normal entry point for a model)."""
    labels = paint_labels(frame.index, events, label=label)
    out = score_labels(frame, bars_4h, labels, folds=folds,
                       wanted={label}, name=name)
    out["n_events"] = int(events.reindex(frame.index).fillna(False).astype(bool).sum())
    return out


# ======================================================================
# PLACEBO
# ======================================================================

def placebo(frame: pd.DataFrame, bars_4h: pd.DataFrame, n_events: int,
            seeds: int = 100, label: str = "BUY", folds: int = 4,
            observed_net: float = None, quiet: bool = True) -> dict:
    """Draw `n_events` random eligible days, paint them with the SAME
    convention, score them through the SAME machinery, repeat.

    Returns the distribution of net expectancy and ex-best, plus where the
    observed value sits inside it.
    """
    pool = eligible_days(frame)
    n_events = int(min(max(n_events, 0), len(pool)))
    nets, exbests = [], []
    for s in range(seeds):
        rng = np.random.default_rng(s)
        pick = rng.choice(len(pool), size=n_events, replace=False) if n_events else []
        ev = pd.Series(False, index=frame.index)
        if n_events:
            ev.iloc[np.sort(pick)] = True
        r = score_labels(frame, bars_4h, paint_labels(frame.index, ev, label),
                         folds=folds, wanted={label}, name=f"placebo{s}")
        nets.append(r["net_all"])
        exbests.append(r["ex_best"])
        if not quiet and (s + 1) % 25 == 0:
            print(f"    placebo {s + 1}/{seeds}")
    nets_a = np.array([x for x in nets if x == x])
    ex_a = np.array([x for x in exbests if x == x])
    out = {"seeds": seeds, "n_events": n_events, "valid": len(nets_a),
           "net": nets_a, "ex_best": ex_a,
           "net_p95": float(np.percentile(nets_a, 95)) if len(nets_a) else float("nan"),
           "net_p99": float(np.percentile(nets_a, 99)) if len(nets_a) else float("nan"),
           "ex_p95": float(np.percentile(ex_a, 95)) if len(ex_a) else float("nan"),
           "ex_p99": float(np.percentile(ex_a, 99)) if len(ex_a) else float("nan")}
    if observed_net is not None and len(nets_a) and observed_net == observed_net:
        out["pctile"] = float(100.0 * (nets_a < observed_net).mean())
    else:
        out["pctile"] = float("nan")
    return out


# ======================================================================
# REFERENCE ROWS
# ======================================================================

def incumbent_rows(merged_win: pd.DataFrame, bars_4h: pd.DataFrame, folds: int = 4) -> list:
    """INC_STRONG_BUY and INC_BUY_ALL, straight from merged's own
    `direction` column, with no relabelling: run the full frame once and
    take direction subsets of the resulting trades, exactly as
    evaluate_geometry_folds does for direction='buy'."""
    g = p.LIVE_GEOMETRY
    results = p.evaluate_geometry_folds(
        merged_win, bars_4h, folds,
        atr_source=g["atr_source"], max_hold_days=g["max_hold_days"],
        stop_mult=g["stop_mult"], target_mult=g["target_mult"],
        confirm_days=g["confirm_days"], short_sma_filter=g["short_sma_filter"],
        fee_bps=FEE_BPS, slippage_bps=SLIPPAGE_BPS, verbose=False)

    rows = []
    for name, wanted in (("INC_STRONG_BUY", {"STRONG_BUY"}),
                         ("INC_BUY_ALL", {"BUY", "STRONG_BUY"})):
        sub = _subset_folds(results, wanted)
        pooled = p.stats_from_trades([t for r in sub for t in r.get("trades", [])])
        net_counted, ex_best, n_counted, folds_pos, n_in_counted = _ex_best(sub)
        row = {"name": name, "n": pooled.get("n", 0),
               "win_pct": 100 * pooled.get("target_rate", float("nan")),
               "stop_pct": 100 * pooled.get("stop_rate", float("nan")),
               "net_all": pooled.get("expectancy_r_net", float("nan")),
               "net_counted": net_counted, "ex_best": ex_best,
               "folds_pos": folds_pos, "folds_counted": n_counted,
               "n_counted": n_in_counted}
        row.update(_trade_shape(sub))
        row["_results"] = sub
        rows.append(row)
    return rows


def incumbent_event_days(merged_win: pd.DataFrame, wanted: set) -> pd.Series:
    """The incumbent's signal days as a boolean series (for overlap work)."""
    return merged_win["direction"].isin(wanted)


def always_long(daily_win: pd.DataFrame, bars_4h: pd.DataFrame, folds: int = 4) -> dict:
    """Every day is BUY — the drift baseline."""
    labels = pd.Series("BUY", index=daily_win.index)
    return score_labels(daily_win, bars_4h, labels, folds=folds,
                        wanted={"BUY"}, name="ALWAYS_LONG")


def reference_rows(ticker: str, window_name: str = "discovery",
                   folds: int = 4, seeds: int = 100, quiet: bool = True,
                   unsealed: bool = False) -> list:
    """INC_STRONG_BUY, INC_BUY_ALL, ALWAYS_LONG, and a count-matched
    placebo for the incumbent under STRONG_BUY geometry."""
    bars_4h, merged, daily = load_ticker(ticker)
    w = make_windows(daily)
    win = getattr(w, window_name)
    if not unsealed:
        bars_4h = seal_bars(bars_4h, w, window_name)
    merged_win, daily_win = slice_window(merged, win), slice_window(daily, win)

    # COMPARABILITY: the resampled daily frame starts at the 4h feed's first
    # full day (2020-09-21), but the incumbent's merged frame only starts
    # once its indicators have warmed up (2021-10-24). Scored on the raw
    # window, ALWAYS_LONG would cover 2.98y while INC_* covered 1.89y — a
    # drift baseline measured over a DIFFERENT period than the thing it is
    # supposed to baseline, including 13 months of the 2020-21 run-up the
    # incumbent never saw. Clip every row to the span they share.
    if len(merged_win):
        daily_win = daily_win[daily_win.index >= merged_win.index.min()]

    rows = incumbent_rows(merged_win, bars_4h, folds=folds)
    rows.append(always_long(daily_win, bars_4h, folds=folds))

    # Count-matched placebo for the incumbent. Painted STRONG_BUY so the
    # 1.333x conviction target matches what it is being compared against,
    # and drawn on the incumbent's OWN frame so the eligible-day pool is
    # the same one the incumbent chose from.
    inc = rows[0]
    n_ev = int(incumbent_event_days(merged_win, {"STRONG_BUY"}).sum())
    pl = placebo(merged_win, bars_4h, n_ev, seeds=seeds, label="STRONG_BUY",
                 folds=folds, observed_net=inc["net_all"], quiet=quiet)
    rows.append({"name": f"PLACEBO_x{pl['seeds']} (STRONG_BUY, n_ev={n_ev})",
                 "n": float("nan"), "win_pct": float("nan"), "stop_pct": float("nan"),
                 "net_all": float(np.nanmean(pl["net"])) if len(pl["net"]) else float("nan"),
                 "ex_best": float(np.nanmean(pl["ex_best"])) if len(pl["ex_best"]) else float("nan"),
                 "folds_pos": 0, "folds_counted": 0, "n_counted": 0,
                 "total_R": float("nan"), "maxDD_R": float("nan"), "worst_streak": 0,
                 "_placebo": pl})
    for r in rows[:3]:
        r["placebo_p95"] = pl["net_p95"]
    inc["placebo_p95"] = pl["net_p95"]
    inc["pctile"] = pl["pctile"]
    return rows, pl, w


# ======================================================================
# RENDERING
# ======================================================================

HDR = (f"{'row':<34}{'n':>5}{'win%':>7}{'stop%':>7}{'net_all':>9}{'ex_best':>9}"
       f"{'folds':>8}{'totR':>8}{'maxDD':>8}{'lose':>6}{'plc95':>8}{'pct':>7}")


def fmt_row(r: dict) -> str:
    folds = (f"{r.get('folds_pos', 0)}/{r.get('folds_counted', 0)}"
             if r.get("folds_counted") else "—")
    def num(k, w, d=2, plus=False):
        v = r.get(k, float("nan"))
        if v is None or (isinstance(v, float) and v != v):
            return f"{'—':>{w}}"
        return f"{v:>{'+' if plus else ''}{w}.{d}f}"
    return (f"{r['name']:<34}"
            f"{(str(int(r['n'])) if r.get('n') == r.get('n') else '—'):>5}"
            f"{num('win_pct', 7, 1)}{num('stop_pct', 7, 1)}"
            f"{num('net_all', 9, 3, True)}{num('ex_best', 9, 3, True)}"
            f"{folds:>8}{num('total_R', 8, 1, True)}{num('maxDD_R', 8, 1)}"
            f"{(str(r.get('worst_streak', 0)) or '—'):>6}"
            f"{num('placebo_p95', 8, 3, True)}{num('pctile', 7, 1)}")


# ======================================================================
# SELF-TEST — synthetic random walk
# ======================================================================

def synthetic(seed: int, days: int = 900, start: str = "2021-01-01") -> pd.DataFrame:
    """A driftless random walk on 4h bars. Nothing here is predictable, so
    a working harness must report ~nothing on it."""
    rng = np.random.default_rng(seed)
    n = days * BARS_PER_DAY
    idx = pd.date_range(start, periods=n, freq="4h")
    step = rng.normal(0, 0.006, n)
    close = 100 * np.exp(np.cumsum(step))
    hi = close * (1 + np.abs(rng.normal(0, 0.003, n)))
    lo = close * (1 - np.abs(rng.normal(0, 0.003, n)))
    op = np.concatenate([[100.0], close[:-1]])
    return pd.DataFrame({"Open": op, "High": np.maximum.reduce([hi, op, close]),
                         "Low": np.minimum.reduce([lo, op, close]), "Close": close,
                         "Volume": rng.lognormal(3, 1, n)}, index=idx)


def self_test(seeds=(0, 1, 2), placebo_seeds: int = 30):
    print("=" * 108)
    print("SELF-TEST — synthetic driftless random walk (no edge exists by construction)")
    print("=" * 108)
    for s in seeds:
        bars = synthetic(s)
        daily = resample_4h_to_daily(bars)
        w = make_windows(daily)
        print_windows(w, daily, label=f"synthetic seed {s}")
        disc = slice_window(daily, w.discovery)

        # A deliberately arbitrary event: every 11th day.
        ev = pd.Series(False, index=disc.index)
        ev.iloc[::11] = True
        r = score_events(disc, bars, ev, folds=4, name=f"synthetic_seed{s}")
        pl = placebo(disc, bars, int(ev.sum()), seeds=placebo_seeds, folds=4,
                     observed_net=r["net_all"])
        r["placebo_p95"], r["pctile"] = pl["net_p95"], pl["pctile"]
        al = always_long(disc, bars, folds=4)
        print(f"\n{HDR}")
        print("-" * 108)
        print(fmt_row(r))
        print(fmt_row(al))
        print(f"  events={r['n_events']}  placebo seeds={pl['seeds']} "
              f"valid={pl['valid']}  placebo mean net="
              f"{np.nanmean(pl['net']):+.3f}R  p95={pl['net_p95']:+.3f}R")
    print("\nSelf-test complete: the harness ran end to end on all seeds.")


# ======================================================================
# CLI
# ======================================================================

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--reference", action="store_true")
    ap.add_argument("--tickers", nargs="+", default=["BTC", "ETH", "SOL"])
    ap.add_argument("--window", default="discovery",
                    choices=("discovery", "confirmation"))
    ap.add_argument("--folds", type=int, default=4)
    ap.add_argument("--seeds", type=int, default=100)
    ap.add_argument("--unsealed", action="store_true",
                    help="Do NOT truncate the 4h feed at the lockbox "
                         "boundary. Only for proving the seal is a no-op "
                         "on DISCOVERY; never for reporting a result.")
    a = ap.parse_args()

    if a.self_test:
        self_test()
    if a.reference:
        for t in a.tickers:
            bars_4h, merged, daily = load_ticker(t)
            w = make_windows(daily)
            print_windows(w, daily, label=t)
            rows, pl, _ = reference_rows(t, window_name=a.window, folds=a.folds,
                                         seeds=a.seeds, unsealed=a.unsealed)
            print(f"\n=== {t} — {a.window.upper()} window, {a.folds} folds, "
                  f"net of {2 * (FEE_BPS + SLIPPAGE_BPS):g}bps round trip ===")
            print(HDR)
            print("-" * 108)
            for r in rows:
                print(fmt_row(r))


if __name__ == "__main__":
    main()
