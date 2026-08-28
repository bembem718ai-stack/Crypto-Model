"""
research/fast_resolver.py
========================
A vectorized re-implementation of pipeline.resolve_on_4h, for the 1h
program (#168-#170).

WHY IT EXISTS. resolve_on_4h walks bars in a Python loop: measured ~2.3ms
per trade. ARM B at 1h, with 300 episode-matched placebo seeds x 3 tickers
x 2 windows, is order 10^6-10^7 resolutions -- hours. This resolves EVERY
candidate bar in one numpy pass, after which a placebo draw is an index
selection rather than a re-simulation.

WHAT IT MUST NOT BE. A faster resolver that disagrees with the incumbent is
not a resolver, it is a different model. `verify_against_pipeline()` is the
registered equivalence gate: it must reproduce resolve_on_4h TRADE FOR
TRADE on the existing 4h data -- date, outcome, pnl_r, pnl_r_net,
bars_held -- before any 1h number is computed. Any mismatch blocks the
program.

RULES PRESERVED EXACTLY (pipeline.py:1565-1595):
  * scan bars STRICTLY AFTER entry_ts, at most max_bars of them;
  * target and stop touched in the SAME bar -> `ambiguous_stop` at -1R
    (pessimistic), checked BEFORE either single-sided hit;
  * target hit -> pnl_r = tgt_dist / stop_dist;
  * stop hit -> -1R;
  * neither, and fewer than max_bars available -> outcome None (DROPPED,
    never counted);
  * neither, with max_bars available -> `timeout` at the last Close;
  * MFE tracked as favourable excursion / target distance.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import pipeline as p


def resolve_many(bars: pd.DataFrame, entries: pd.DataFrame,
                 max_bars: int, is_long: bool = True) -> pd.DataFrame:
    """Resolve many trades at once.

    `entries` needs columns: entry_ts, entry, target, stop. Returns one row
    per entry with outcome / bars / pnl_r / mfe, in the same order.
    """
    if entries is None or len(entries) == 0:
        return pd.DataFrame(columns=["outcome", "bars", "pnl_r", "mfe"])

    idx = bars.index.values
    high = bars["High"].to_numpy(dtype=float)
    low = bars["Low"].to_numpy(dtype=float)
    close = bars["Close"].to_numpy(dtype=float)
    n_bars = len(idx)

    ts = entries["entry_ts"].to_numpy()
    entry = entries["entry"].to_numpy(dtype=float)
    target = entries["target"].to_numpy(dtype=float)
    stop = entries["stop"].to_numpy(dtype=float)

    # First bar strictly after the entry timestamp, per trade.
    start = np.searchsorted(idx, ts, side="right")

    tgt_dist = np.abs(target - entry)
    stop_dist = np.abs(entry - stop)

    outcomes = np.empty(len(entries), dtype=object)
    # EXPLICIT resolved FLAG. pandas turns a None inside a mixed-dtype row
    # into NaN on .iloc, and `NaN is None` is False -- so a downstream
    # `outcome is None` drop-check would silently ADMIT an unresolved trade
    # into the pool. The equivalence gate caught exactly this on the final
    # bar of each ticker. A boolean column cannot be coerced away.
    resolved = np.ones(len(entries), dtype=bool)
    bars_held = np.zeros(len(entries), dtype=int)
    pnl = np.full(len(entries), np.nan)
    mfe = np.zeros(len(entries))

    # Loop over TRADES (thousands), not over bars-per-trade (hundreds of
    # thousands). Each trade's window is handled with vectorised numpy.
    for k in range(len(entries)):
        s = start[k]
        e = min(s + max_bars, n_bars)
        avail = e - s
        if avail <= 0:
            outcomes[k] = None
            resolved[k] = False
            continue
        hi = high[s:e]
        lo = low[s:e]

        if is_long:
            fav = hi - entry[k]
            hit_t = hi >= target[k]
            hit_s = lo <= stop[k]
        else:
            fav = entry[k] - lo
            hit_t = lo <= target[k]
            hit_s = hi >= stop[k]

        touched = hit_t | hit_s
        first = int(np.argmax(touched)) if touched.any() else -1

        if first >= 0:
            # MFE accumulates only up to and including the resolving bar,
            # exactly as the loop does.
            run = fav[:first + 1]
            mfe[k] = float(np.max(run) / tgt_dist[k]) if tgt_dist[k] else 0.0
            mfe[k] = max(mfe[k], 0.0)
            bars_held[k] = first + 1
            if hit_t[first] and hit_s[first]:
                outcomes[k], pnl[k] = "ambiguous_stop", -1.0
            elif hit_t[first]:
                outcomes[k] = "target"
                pnl[k] = (tgt_dist[k] / stop_dist[k]) if stop_dist[k] else np.nan
            else:
                outcomes[k], pnl[k] = "stop", -1.0
            continue

        # Never touched.
        mfe[k] = float(np.max(fav) / tgt_dist[k]) if tgt_dist[k] else 0.0
        mfe[k] = max(mfe[k], 0.0)
        if avail < max_bars:
            outcomes[k] = None                       # still open -> dropped
            resolved[k] = False
            bars_held[k] = avail
            continue
        last = close[e - 1]
        gain = (last - entry[k]) if is_long else (entry[k] - last)
        outcomes[k] = "timeout"
        bars_held[k] = max_bars
        pnl[k] = (gain / stop_dist[k]) if stop_dist[k] else np.nan

    return pd.DataFrame({"outcome": outcomes, "resolved": resolved,
                         "bars": bars_held, "pnl_r": pnl, "mfe": mfe},
                        index=entries.index)


def verify_against_pipeline(bars_4h: pd.DataFrame, merged: pd.DataFrame,
                            max_hold_days: float = 15,
                            bars_per_day: int = 6, limit: int = None) -> dict:
    """THE EQUIVALENCE GATE. Reproduce resolve_on_4h trade for trade.

    Rebuilds exactly the entries pipeline.backtest_exit_geometry would take
    on this frame with LIVE_GEOMETRY, resolves them both ways, and compares
    outcome / bars / pnl_r elementwise.
    """
    import signal_engines as cf
    g = p.LIVE_GEOMETRY
    df = merged.dropna(subset=["High", "Low", "Close"]).copy()
    atr4 = p.build_4h_atr(bars_4h)
    max_bars = max(1, int(max_hold_days * bars_per_day))
    dirs = df["direction"].tolist()

    def confirmed(i):
        c = g["confirm_days"]
        if c <= 1:
            return True
        if i < c - 1:
            return False
        w = dirs[i - c + 1: i + 1]
        return all(d == w[-1] for d in w)

    rows = []
    for i, (day, row) in enumerate(df.iterrows()):
        if not confirmed(i):
            continue
        d = row["direction"]
        if d not in ("BUY", "STRONG_BUY"):           # long side only
            continue
        entry_ts = pd.Timestamp(day).normalize() + pd.Timedelta(hours=24)
        prior = atr4[atr4.index <= entry_ts]
        atr = prior.iloc[-1] if len(prior) else float("nan")
        if not (atr == atr) or atr <= 0:
            continue
        lvl = cf.compute_exit_levels(row["Close"], d, atr,
                                     stop_mult=g["stop_mult"],
                                     target_mult=g["target_mult"])
        if not lvl.get("applicable"):
            continue
        rows.append({"date": day, "entry_ts": entry_ts, "entry": lvl["entry"],
                     "target": lvl["target"], "stop": lvl["stop"]})
        if limit and len(rows) >= limit:
            break

    ent = pd.DataFrame(rows)
    if ent.empty:
        return {"n": 0, "match": True, "mismatches": []}

    fast = resolve_many(bars_4h, ent, max_bars=max_bars, is_long=True)

    mismatches = []
    for k in range(len(ent)):
        ref = p.resolve_on_4h(bars_4h, ent.entry_ts.iloc[k], ent.entry.iloc[k],
                              ent.target.iloc[k], ent.stop.iloc[k], True, max_bars)
        f = fast.iloc[k]
        ref_resolved = ref["outcome"] is not None
        same = (bool(f["resolved"]) == ref_resolved
                and (not ref_resolved or ref["outcome"] == f["outcome"])
                and int(ref["bars"]) == int(f["bars"])
                and (not ref_resolved or _close(ref["pnl_r"], f["pnl_r"]))
                and _close(ref["mfe"], f["mfe"], tol=1e-9))
        if not same:
            mismatches.append({"date": str(ent.date.iloc[k]),
                               "ref": {k2: ref[k2] for k2 in ("outcome", "bars", "pnl_r", "mfe")},
                               "fast": {"outcome": f["outcome"], "resolved": bool(f["resolved"]),
                                        "bars": int(f["bars"]), "pnl_r": f["pnl_r"],
                                        "mfe": f["mfe"]}})
    return {"n": len(ent), "match": not mismatches, "mismatches": mismatches[:10],
            "n_mismatch": len(mismatches)}


def _close(a, b, tol=1e-9):
    if a is None and (b is None or (isinstance(b, float) and np.isnan(b))):
        return True
    if a is None or b is None:
        return False
    if isinstance(a, float) and np.isnan(a):
        return isinstance(b, float) and np.isnan(b)
    if isinstance(b, float) and np.isnan(b):
        return False
    return abs(float(a) - float(b)) <= tol
