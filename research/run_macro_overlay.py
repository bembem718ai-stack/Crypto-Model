"""#251-#256 — MACRO-OVERLAY. Locked in docs/cleanroom.md before this ran.

Regime gates on POOLED tradable-26 INC_BUY_ALL. Every constant is inherited
from the registration; nothing here is chosen.

TWO STAGES, IN ORDER:
  1. EVENT-COUNT PRECHECK -- a GATE, not a preview. Confirmed-trade counts
     per quartile per window, from signal definitions and calendar structure
     ONLY. No returns are loaded. A rule under 30 trades in any
     quartile-window is UNMEASURABLE-BY-CONSTRUCTION and never runs.
     **Bonferroni k stays at 6 regardless of what the gate removes.**
  2. THE PROGRAM -- fidelity axes first, then all surviving tests.
"""
import os
import sys
import json
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import harness as H
import pipeline as p

warnings.filterwarnings("ignore")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MACRO = os.path.join(ROOT, "data", "macro")
RESULTS = os.path.join(ROOT, "research", "h251_results.json")

TIER = {"BUY", "STRONG_BUY"}
G = p.LIVE_GEOMETRY
SEEDS = 3000                  # registered
K_TESTS = 6                   # registered, FIXED regardless of gate removals
ALPHA = 0.05 / K_TESTS
ADJ_PCTILE = 100.0 * (1.0 - ALPHA)      # 99.1667
FOLDS = 4
MIN_TRADES = 30               # ex_best floor: 3 folds x 10

# H-basket-C's quartiles, seed 20260827, fixed before any basket result and
# REUSED rather than re-drawn (registered precedent).
QUARTILES = {
    "Q1": ["AAVE", "ALGO", "BTC", "LINK", "XRP"],
    "Q2": ["ATOM", "AVAX", "BNB", "DOGE", "ETC", "ETH", "VTHO"],
    "Q3": ["ADA", "BCH", "FET", "NEAR", "ONE", "SOL", "TRX", "XLM"],
    "Q4": ["DOT", "GALA", "LTC", "OP", "UNI", "VET"],
}
TESTS = ["#251", "#252", "#253", "#254", "#255", "#256"]


# ----------------------------------------------------------------------
# MACRO REGIMES — from the frozen, hashed series
# ----------------------------------------------------------------------
def load_regimes():
    """Daily boolean regime series. Broadcast D+1, per the registration."""
    sc = pd.read_csv(os.path.join(MACRO, "stablecoin_supply.csv"),
                     parse_dates=["date"]).set_index("date")["total_circulating_usd"]
    dg = pd.read_csv(os.path.join(MACRO, "dgs10.csv"),
                     parse_dates=["date"]).set_index("date")["dgs10"]

    idx = pd.date_range(min(sc.index.min(), dg.index.min()),
                        max(sc.index.max(), dg.index.max()), freq="D")
    # DGS10 is business-days only: carry the last PUBLISHED value forward.
    # No interpolation, no back-fill -- a carried value is the most recent
    # KNOWN value, which is what a trader would have had.
    dg = dg.reindex(idx).ffill()
    sc = sc.reindex(idx).ffill()

    g30 = sc / sc.shift(30) - 1.0                       # 30-day growth
    terc = g30.rolling(365).rank(pct=True)              # trailing-year rank
    d3m = dg - dg.shift(63)                             # 3-month change
    m200 = dg.rolling(200).mean()

    raw = pd.DataFrame({
        "#251": g30 > 0,
        "#252": terc >= (2.0 / 3.0),
        "#253": terc <= (1.0 / 3.0),
        "#254": d3m < 0,
        "#255": dg < m200,
    }, index=idx)
    raw["#256"] = raw["#251"] & raw["#254"]
    # undefined inputs must EXCLUDE the trade, not default to False-as-known
    defined = pd.DataFrame({
        "#251": g30.notna(), "#252": terc.notna(), "#253": terc.notna(),
        "#254": d3m.notna(), "#255": (dg.notna() & m200.notna()),
    }, index=idx)
    defined["#256"] = defined["#251"] & defined["#254"]

    # THE BROADCAST: a value known at D applies from D+1.
    return raw.shift(1), defined.shift(1)


# ----------------------------------------------------------------------
# BASE — pooled tradable-26 INC_BUY_ALL, exactly as #164 built it
# ----------------------------------------------------------------------
def universe():
    return [l.strip() for l in open(os.path.join(ROOT, "research",
            "basket_tradable.txt"), encoding="utf-8") if l.strip()]


def base_trades(ticker, windows, bars_cache):
    """Every INC_BUY_ALL trade for one ticker, per window. No macro yet."""
    b = os.path.join(ROOT, "data", "basket", "%s_4h.csv.gz" % ticker)
    m = os.path.join(ROOT, "data", "basket", "%s_merged.csv.gz" % ticker)
    if not (os.path.exists(b) and os.path.exists(m)):
        return {}
    bars = pd.read_csv(b, index_col=0, parse_dates=True).sort_index()
    merged = pd.read_csv(m, index_col=0, parse_dates=True).sort_index()
    out = {}
    for wname, lo, hi in windows:
        mwin = merged[(merged.index >= lo) & (merged.index < hi)]
        if not len(mwin):
            out[wname] = []
            continue
        sealed = bars[bars.index < hi + pd.Timedelta(days=G["max_hold_days"])]
        r = p.evaluate_geometry_folds(
            mwin, sealed, 1, atr_source=G["atr_source"],
            max_hold_days=G["max_hold_days"], stop_mult=G["stop_mult"],
            target_mult=G["target_mult"], confirm_days=G["confirm_days"],
            short_sma_filter=G["short_sma_filter"],
            fee_bps=H.FEE_BPS, slippage_bps=H.SLIPPAGE_BPS, verbose=False)
        tr = [t for f in H._subset_folds(r, TIER) for t in f.get("trades", [])]
        for t in tr:
            t["ticker"] = ticker
        out[wname] = tr
    return out


# ----------------------------------------------------------------------
# SCORING HELPERS
# ----------------------------------------------------------------------
def _days(lo, hi):
    """Midnight-normalised daily index.

    The window bounds carry a time-of-day (the DISCOVERY/CONFIRMATION cut is
    start + span*0.55), so pd.date_range on them emits stamps at that same
    time. Those never matched the midnight-normalised regime index, reindex
    returned all-NaN, and every CONFIRMATION regime read 0.0% while the gate
    -- which normalises trade dates -- was correctly keeping 1,819 trades.
    A contradiction visible in the output, which is how it was caught.
    """
    return pd.date_range(pd.Timestamp(lo).normalize(),
                         pd.Timestamp(hi).normalize(), freq="D")


def quartile_of(ticker):
    for q, members in QUARTILES.items():
        if ticker in members:
            return q
    return None


def gate(trades, regime, defined, tid):
    """Keep a trade iff its regime is TRUE and DEFINED on its entry day."""
    keep = []
    for t in trades:
        d = pd.Timestamp(t["date"]).normalize()
        if d in defined.index and bool(defined.at[d, tid]) and bool(regime.at[d, tid]):
            keep.append(t)
    return keep


def episodes_of(trades):
    """Episodes counted PER TICKER, then summed.

    The first version pooled every ticker's dates into one series before
    measuring gaps. With 26 tickers trading concurrently a >15-day gap almost
    never occurs, so 1,678 trades collapsed to EIGHT episodes -- a number that
    would have made every episode count in this program meaningless. #164
    recorded 496 and 661 for these windows; reproducing those is the check.
    """
    if not trades:
        return 0
    hold = pd.Timedelta(days=G["max_hold_days"])
    by_ticker = {}
    for t in trades:
        by_ticker.setdefault(t.get("ticker", "?"), []).append(
            pd.Timestamp(t["date"]))
    total = 0
    for dates in by_ticker.values():
        d = sorted(dates)
        total += 1 + sum(1 for i in range(1, len(d))
                         if (d[i] - d[i - 1]) > hold)
    return total


def stats(trades, window):
    if not trades:
        return {"n": 0, "episodes": 0, "win_pct": float("nan"),
                "net_all": float("nan"), "ex_best": float("nan"),
                "folds_counted": 0, "folds_pos": 0}
    df = pd.DataFrame(trades)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date")
    edges = pd.date_range(window[0], window[1], periods=FOLDS + 1)
    fi = pd.cut(df["date"], edges, labels=False, include_lowest=True)
    counted = [(len(df[fi == k]), float(df[fi == k]["pnl_r_net"].mean()))
               for k in range(FOLDS) if len(df[fi == k]) >= 10]
    ex = float("nan")
    if len(counted) >= 3:
        tn = sum(n for n, _ in counted)
        tr = sum(n * m for n, m in counted)
        bn, bm = max(counted, key=lambda c: c[0] * c[1])
        rest = tn - bn
        ex = (tr - bn * bm) / rest if rest else float("nan")
    return {"n": len(df), "episodes": episodes_of(trades),
            "win_pct": 100 * float((df["outcome"] == "target").mean()),
            "net_all": float(df["pnl_r_net"].mean()), "ex_best": ex,
            "folds_counted": len(counted),
            "folds_pos": sum(1 for n, m in counted if m > 0)}


def runs_of(mask):
    out, cur = [], 0
    for v in mask:
        if v:
            cur += 1
        elif cur:
            out.append(cur)
            cur = 0
    if cur:
        out.append(cur)
    return out



def _run_gap_shuffle(obs, rng):
    """Episode-matched null with EXACT coverage.

    THE FIRST VERSION UNDER-COVERED BADLY AND AXIS 1 CAUGHT IT. It placed
    each observed run at a random non-overlapping position with 12 attempts.
    At 73% regime density most runs cannot find a free slot, so they were
    silently dropped: the null carried 0.22x the strategy's trades. A null
    trading a fifth as often is not the strategy with its timing destroyed --
    it is a different, thinner strategy.

    The repair preserves the alternation exactly. Decompose the observed
    series into its TRUE-runs and FALSE-gaps, permute each list
    independently, and lay them back down end to end. Run COUNT, run
    LENGTHS, gap LENGTHS and TOTAL COVERAGE are all preserved by
    construction; only WHERE the runs sit changes -- which is precisely the
    thing the null is supposed to destroy.
    """
    n = len(obs)
    runs, gaps, cur, val = [], [], 0, obs[0] if n else False
    for v in obs:
        if bool(v) == bool(val):
            cur += 1
        else:
            (runs if val else gaps).append(cur)
            val, cur = v, 1
    if n:
        (runs if val else gaps).append(cur)
    rng.shuffle(runs)
    rng.shuffle(gaps)
    out = np.zeros(n, dtype=bool)
    i, ri, gi = 0, 0, 0
    start_true = bool(obs[0]) if n else False
    turn_true = start_true
    while i < n and (ri < len(runs) or gi < len(gaps)):
        if turn_true and ri < len(runs):
            L = runs[ri]; ri += 1
            out[i:i + L] = True
            i += L
        elif not turn_true and gi < len(gaps):
            i += gaps[gi]; gi += 1
        elif ri < len(runs):
            L = runs[ri]; ri += 1
            out[i:i + L] = True
            i += L
        else:
            i += gaps[gi]; gi += 1
        turn_true = not turn_true
    return out


def placebo(all_trades, regime, defined, tid, window, seeds=SEEDS):
    """Episode-matched: same NUMBER of runs, same LENGTHS, random positions.

    The regime is a daily boolean; its observed run-lengths are redrawn at
    random non-overlapping positions and the same gate applied.
    """
    idx = _days(window[0], window[1])
    ok = defined.reindex(idx)[tid].fillna(False).to_numpy().astype(bool)
    obs = (regime.reindex(idx)[tid].fillna(False).to_numpy().astype(bool)) & ok
    n = len(idx)
    by_day = {}
    for t in all_trades:
        by_day.setdefault(pd.Timestamp(t["date"]).normalize(), []).append(
            t["pnl_r_net"])
    nets = []
    for s in range(seeds):
        rng = np.random.default_rng(251000 + s)
        draw = _run_gap_shuffle(obs, rng)
        vals = []
        for j in np.flatnonzero(draw & ok):
            vals.extend(by_day.get(idx[j], []))
        if vals:
            nets.append(float(np.mean(vals)))
    return np.array(nets)


# ----------------------------------------------------------------------
# FIDELITY AXES
# ----------------------------------------------------------------------
def fidelity(all_trades, regime, defined, tid, window, dist, seeds=200):
    idx = _days(window[0], window[1])
    ok = defined.reindex(idx)[tid].fillna(False).to_numpy().astype(bool)
    obs = (regime.reindex(idx)[tid].fillna(False).to_numpy().astype(bool)) & ok
    real = gate(all_trades, regime, defined, tid)
    by_day = {}
    for t in all_trades:
        by_day.setdefault(pd.Timestamp(t["date"]).normalize(), []).append(t)
    n = len(idx)
    counts, costs, off, total_ev = [], [], 0, 0
    for s in range(seeds):
        rng = np.random.default_rng(777000 + s)
        draw = _run_gap_shuffle(obs, rng)
        c, cost = 0, []
        for j in np.flatnonzero(draw):
            total_ev += 1
            if not ok[j]:
                off += 1
            for t in by_day.get(idx[j], []):
                c += 1
                cost.append(t["cost_r"])
        counts.append(c)
        costs += cost
    rc = [t["cost_r"] for t in real]
    # axis 4: episode-matched centre vs an independent-day draw of same count
    ind = []
    k = int(obs.sum())
    for s in range(400):
        rng = np.random.default_rng(888000 + s)
        pick = rng.choice(n, size=min(k, n), replace=False)
        vals = []
        for j in pick:
            if ok[j]:
                vals.extend(t["pnl_r_net"] for t in by_day.get(idx[j], []))
        if vals:
            ind.append(float(np.mean(vals)))
    return {"axis1_real_trades": len(real),
            "axis1_null_trades_mean": float(np.mean(counts)) if counts else 0.0,
            "axis1_ratio": (float(np.mean(counts)) / len(real)) if real else float("nan"),
            "axis1_real_cost_r": float(np.mean(rc)) if rc else float("nan"),
            "axis1_null_cost_r": float(np.mean(costs)) if costs else float("nan"),
            "axis2_off_defined_days": int(off), "axis2_null_days": int(total_ev),
            "axis3": "N/A - regime gate on an event series has no exposure budget",
            "axis4_episode_centre": float(np.median(dist)) if len(dist) else float("nan"),
            "axis4_independent_centre": float(np.median(ind)) if ind else float("nan"),
            "axis4_inheritance": (float(np.median(dist)) - float(np.median(ind)))
            if len(dist) and ind else float("nan"),
            "regime_true_days": int(obs.sum()), "window_days": n,
            "regime_true_pct": 100.0 * obs.mean()}


# ----------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------
def main():
    bars, merged, daily = H.load_ticker("BTC")
    w = H.make_windows(daily)
    windows = [("DISCOVERY", w.discovery[0], w.discovery[1]),
               ("CONFIRMATION", w.confirmation[0], w.confirmation[1])]
    wmap = {"DISCOVERY": w.discovery, "CONFIRMATION": w.confirmation}
    regime, defined = load_regimes()

    print("MACRO-OVERLAY #251-#256 — pooled tradable-26 INC_BUY_ALL")
    print("=" * 108)
    H.print_windows(w, daily, "basket windows")
    print("\nBuilding pooled base (this is the #164 construction)...")
    pooled = {"DISCOVERY": [], "CONFIRMATION": []}
    for t in universe():
        bt = base_trades(t, windows, None)
        for wn in pooled:
            pooled[wn].extend(bt.get(wn, []))
    for wn in pooled:
        print("  %-13s pooled base: %5d trades, %4d episodes"
              % (wn, len(pooled[wn]), episodes_of(pooled[wn])))

    # ---------- STAGE 1: EVENT-COUNT PRECHECK (structure only) ----------
    print("\n" + "=" * 108)
    print("STAGE 1 — EVENT-COUNT PRECHECK. A GATE, NOT A PREVIEW.")
    print("Confirmed-trade counts from signal definitions and calendar")
    print("structure only. No return is read. Floor = %d per quartile-window."
          % MIN_TRADES)
    print("=" * 108)
    print("%-6s %-13s %8s %7s %7s %7s %7s %7s   %s"
          % ("#", "window", "pooled", "Q1", "Q2", "Q3", "Q4", "regime%", "gate"))
    print("-" * 108)
    precheck, survivors = {}, []
    for tid in TESTS:
        ok_all = True
        precheck[tid] = {}
        for wn, lo, hi in windows:
            kept = gate(pooled[wn], regime, defined, tid)
            byq = {q: sum(1 for t in kept if quartile_of(t["ticker"]) == q)
                   for q in QUARTILES}
            idx = _days(lo, hi)
            okd = defined.reindex(idx)[tid].fillna(False).to_numpy().astype(bool)
            obs = (regime.reindex(idx)[tid].fillna(False).to_numpy().astype(bool)) & okd
            passes = all(v >= MIN_TRADES for v in byq.values())
            ok_all &= passes
            precheck[tid][wn] = {"pooled": len(kept), "quartiles": byq,
                                 "regime_true_pct": 100.0 * obs.mean(),
                                 "passes": passes}
            print("%-6s %-13s %8d %7d %7d %7d %7d %6.1f%%   %s"
                  % (tid, wn, len(kept), byq["Q1"], byq["Q2"], byq["Q3"],
                     byq["Q4"], 100.0 * obs.mean(),
                     "OK" if passes else "**UNMEASURABLE-BY-CONSTRUCTION**"))
        if ok_all:
            survivors.append(tid)
    print("\n  registered k = %d (UNCHANGED). Surviving tests: %d — %s"
          % (K_TESTS, len(survivors), ", ".join(survivors) or "none"))
    print("  Removing a hypothesis reduces chances TAKEN, never chances CREATED.")

    out = {"_windows": {wn: [str(lo.date()), str(hi.date())]
                        for wn, lo, hi in windows},
           "_base": {wn: {"n": len(pooled[wn]), "episodes": episodes_of(pooled[wn])}
                     for wn in pooled},
           "_precheck": precheck, "_k": K_TESTS, "_survivors": survivors,
           "_tests": {}, "_fidelity": {}}

    # ---------- STAGE 2: FIDELITY, THEN THE PROGRAM ----------
    print("\n" + "=" * 108)
    print("STAGE 2 — FIDELITY AXES FIRST, then all surviving tests")
    print("=" * 108)
    for tid in survivors:
        out["_tests"][tid] = {}
        for wn, lo, hi in windows:
            kept = gate(pooled[wn], regime, defined, tid)
            dist = placebo(pooled[wn], regime, defined, tid, (lo, hi))
            if tid == survivors[0]:
                f = fidelity(pooled[wn], regime, defined, tid, (lo, hi), dist)
                out["_fidelity"][wn] = f
                print("  %-13s axis1 trades %d vs null %.1f (%.2fx) cost_r %.4f/%.4f"
                      % (wn, f["axis1_real_trades"], f["axis1_null_trades_mean"],
                         f["axis1_ratio"], f["axis1_real_cost_r"],
                         f["axis1_null_cost_r"]))
                print("  %-13s axis2 null days on UNDEFINED regime: %d of %d"
                      % ("", f["axis2_off_defined_days"], f["axis2_null_days"]))
                print("  %-13s axis3 %s" % ("", f["axis3"]))
                print("  %-13s axis4 episode %+.4f vs independent %+.4f -> %+.4f"
                      % ("", f["axis4_episode_centre"],
                         f["axis4_independent_centre"], f["axis4_inheritance"]))
            st = stats(kept, wmap[wn])
            st["quartiles"] = {}
            for q in QUARTILES:
                qt = [t for t in kept if quartile_of(t["ticker"]) == q]
                st["quartiles"][q] = stats(qt, wmap[wn])
            st["placebo_p95"] = float(np.percentile(dist, 95)) if len(dist) else float("nan")
            st["placebo_adj"] = float(np.percentile(dist, ADJ_PCTILE)) if len(dist) else float("nan")
            st["placebo_pctile"] = (float(100.0 * (dist < st["net_all"]).mean())
                                    if len(dist) and st["net_all"] == st["net_all"]
                                    else float("nan"))
            st["regime_true_pct"] = precheck[tid][wn]["regime_true_pct"]
            out["_tests"][tid][wn] = st

    with open(RESULTS, "w") as fh:
        json.dump(out, fh, indent=2, default=str)
    print("\nwrote %s" % RESULTS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
