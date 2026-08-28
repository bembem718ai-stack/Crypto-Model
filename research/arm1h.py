"""
research/arm1h.py
=================
The 1h program (#168-#170). Builds the incumbent's construction on 1h bars
under two registered parameter sets and scores it.

NOTHING HERE TOUCHES LIVE_GEOMETRY, pipeline.py, signal_engines.py or
live_tools.py. Trade resolution comes from research/fast_resolver.py, which
passed the registered equivalence gate against pipeline.resolve_on_4h on
6,611 trades before any 1h number was computed. Direction labelling comes
from pipeline.classify_direction, read, not reimplemented.

STEP 3 LAG (registered specification completion). Day D's daily indicator
score and vix_level exist only at D's close, so they are applied to 1h bars
from D+1 00:00 onward. Each bar's Step 3 component is therefore 0-24h old.
That staleness is a registered structural handicap and is reported.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import pipeline as p
import signal_engines as cf
import fast_resolver as FR

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
TICKERS = ["BTC", "ETH", "SOL"]
FEE, SLIP = 2.0, 2.0
LOCKBOX_MONTHS = p.LOCKBOX_MONTHS
DISCOVERY_FRAC = 0.55

# Registered parameter sets. Neither is LIVE_GEOMETRY; LIVE_GEOMETRY is read
# for the dimensionless values only and never written.
ARM_A = {"name": "A", "atr_period": 56, "max_hold_bars": 360,
         "confirm_bars": 48, "bb_period": 80, "percentile_lookback": 480,
         "max_duration": 160, "stop_mult": 1.5, "target_mult": 3.0}
ARM_B = {"name": "B", "atr_period": 14, "max_hold_bars": 90,
         "confirm_bars": 2, "bb_period": 20, "percentile_lookback": 120,
         "max_duration": 40, "stop_mult": 1.5, "target_mult": 3.0}


# ----------------------------------------------------------------------
def load_1h(ticker):
    return pd.read_csv(os.path.join(DATA, "%s_1h.csv" % ticker),
                       index_col=0, parse_dates=True).sort_index()


def load_daily(ticker):
    """The incumbent's merged daily frame: Step 3 score and vix_level."""
    return pd.read_csv(os.path.join(DATA, "%s_merged.csv" % ticker),
                       index_col=0, parse_dates=True).sort_index()


def windows_1h(bars):
    """Common windows on the 1h index, anchored on the dataset's last bar."""
    last = bars.index.max()
    lock = last - pd.DateOffset(months=LOCKBOX_MONTHS)
    avail = bars[bars.index < lock]
    start, end = avail.index.min(), avail.index.max()
    cut = start + (end - start) * DISCOVERY_FRAC
    return {"discovery": (start, cut), "confirmation": (cut, lock),
            "lockbox": (lock, last), "last": last}


def build_scores(ticker, arm, w):
    """1h frame with initial_score, lagged Step 3, combined score, direction."""
    bars = load_1h(ticker)
    bars = bars[bars.index < w["lockbox"][0]]          # SEAL the 1h feed
    daily = load_daily(ticker)

    # --- Step 1: squeeze on 1h bars, arm's parameters
    sq = cf.add_squeeze_features(bars, bb_period=arm["bb_period"],
                                 percentile_lookback=arm["percentile_lookback"])
    coil = (1 - sq["BB_WIDTH_PCTL"]) * 70
    dur = (sq["SQUEEZE_DURATION"] / arm["max_duration"]).clip(upper=1.0) * 30
    f = bars.copy()
    f["initial_score"] = (coil + dur).clip(0, 100)

    # --- Step 3: LAGGED broadcast. Day D's values first apply at D+1 00:00.
    d = daily[["final_score", "vix_level"]].copy()
    d.index = pd.to_datetime(d.index).normalize()
    d = d[~d.index.duplicated(keep="last")].shift(1)    # <- the lag
    key = pd.Series(f.index.normalize(), index=f.index)
    f["ind_score"] = key.map(d["final_score"])
    f["vix_level"] = key.map(d["vix_level"])
    # Staleness: with shift(1), a bar on day D carries day D-1's score, and
    # day D-1's daily bar CLOSES at day D 00:00. So a bar at D 00:00 acts on
    # a 0h-old reading and one at D 23:00 on a 23h-old one. No +24: that
    # would double-count the lag that the shift already represents.
    f["ind_age_h"] = (f.index - f.index.normalize()).total_seconds() / 3600.0

    f = f.dropna(subset=["initial_score", "ind_score", "vix_level"])

    # --- combine, exactly as run_backtest does (neutral sentiment gate)
    f["combined_final_score"] = (0.6 * f["initial_score"]
                                 + 0.4 * f["ind_score"]).clip(0, 100)
    f["direction"] = [p.classify_direction(s, v) for s, v
                      in zip(f["combined_final_score"], f["vix_level"])]
    return f, bars


def entries_for(f, bars, arm, tier):
    """Confirmed entries under the arm's confirm rule. Entry price is the
    confirming bar's CLOSE; entry timestamp is that bar's open_time + 1h."""
    want = {"STRONG_BUY"} if tier == "STRONG_BUY" else {"BUY", "STRONG_BUY"}
    lab = f["direction"]
    ok = lab.isin(want)
    C = arm["confirm_bars"]
    if C <= 1:
        conf = ok
    else:
        same = ok.copy()
        for k in range(1, C):
            same &= (lab.shift(k) == lab) & ok
        conf = same

    atr = cf.compute_atr(bars, period=arm["atr_period"]).reindex(f.index)
    rows = []
    step = pd.Timedelta(hours=1)
    for ts in f.index[conf.values]:
        a = atr.get(ts, np.nan)
        if not (a == a) or a <= 0:
            continue
        d = lab.loc[ts]
        lvl = cf.compute_exit_levels(float(f.loc[ts, "Close"]), d, float(a),
                                     stop_mult=arm["stop_mult"],
                                     target_mult=arm["target_mult"])
        if not lvl.get("applicable"):
            continue
        rows.append({"ts": ts, "entry_ts": ts + step, "direction": d,
                     "entry": lvl["entry"], "target": lvl["target"],
                     "stop": lvl["stop"], "stop_dist": lvl["stop_dist"]})
    return pd.DataFrame(rows)


def score(entries, bars, arm):
    """Resolve and cost. Returns a trade frame."""
    if entries.empty:
        return pd.DataFrame()
    res = FR.resolve_many(bars, entries, max_bars=arm["max_hold_bars"], is_long=True)
    t = entries.join(res)
    t = t[t["resolved"]].copy()                 # unresolved are DROPPED
    if t.empty:
        return t
    stop_frac = (t["stop_dist"] / t["entry"]).astype(float)
    t["stop_pct"] = 100 * stop_frac
    t["cost_r"] = (2.0 * (FEE + SLIP) / 1e4) / stop_frac
    t["pnl_r_net"] = t["pnl_r"] - t["cost_r"]
    return t


def episodes(ts_list, hold_bars):
    if len(ts_list) == 0:
        return 0
    d = sorted(pd.Timestamp(x) for x in ts_list)
    gap = pd.Timedelta(hours=hold_bars)
    return 1 + sum(1 for i in range(1, len(d)) if (d[i] - d[i - 1]) > gap)


def stats(t, arm, window=None, folds=4):
    if t is None or len(t) == 0:
        return {"n": 0}
    out = {"n": len(t), "episodes": episodes(t["ts"], arm["max_hold_bars"]),
           "win_pct": 100 * (t["outcome"] == "target").mean(),
           "net_all": float(t["pnl_r_net"].mean()),
           "total_R": float(t["pnl_r_net"].sum()),
           "med_stop_pct": float(t["stop_pct"].median()),
           "med_cost_r": float(t["cost_r"].median())}
    curve = np.cumsum(t.sort_values("ts")["pnl_r_net"].values)
    out["maxDD_R"] = float(np.max(np.maximum.accumulate(curve) - curve)) if len(curve) else 0.0
    if window is not None:
        edges = pd.date_range(window[0], window[1], periods=folds + 1)
        fi = pd.cut(t["ts"], edges, labels=False, include_lowest=True)
        counted = []
        for k in range(folds):
            sub = t[fi == k]
            if len(sub) >= 10:
                counted.append((len(sub), float(sub["pnl_r_net"].mean())))
        out["folds_counted"] = len(counted)
        out["folds_pos"] = sum(1 for n, m in counted if m > 0)
        if len(counted) >= 3:
            tot_n = sum(n for n, _ in counted)
            tot_r = sum(n * m for n, m in counted)
            bn, bm = max(counted, key=lambda c: c[0] * c[1])
            rest = tot_n - bn
            out["ex_best"] = (tot_r - bn * bm) / rest if rest else float("nan")
        else:
            out["ex_best"] = float("nan")
    return out
