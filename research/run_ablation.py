"""#197-#202 — ABLATION. Which components of BTC INC_BUY_ALL carry its behaviour?

Registered in docs/cleanroom.md and LOCKED. Removal scheme is
ONE-AT-A-TIME-FROM-FULL: every rung removes exactly ONE component and
restores everything else to production values, so each delta is a statement
about its own component and no number depends on listing order.

Descriptive only. No pass/fail, no Bonferroni, nothing may be promoted.

THE RECONSTRUCTION GATE. Rungs #198/#199/#201 change the DIRECTION column,
which means recomputing it from its components. That is only legitimate if
the recomputation reproduces the stored column EXACTLY under production
settings -- otherwise the ablated rungs would be measured against a baseline
they do not share a construction with. main() asserts that before scoring a
single rung, and refuses to continue if even one day disagrees.

NOTHING IN THE CORE IS EDITED. #202 needs conviction scaling off, which
lives in signal_engines.compute_exit_levels. Research rule 1 forbids
research touching that file, so it is swapped at RUNTIME by a context
manager that restores the original on exit -- see flat_conviction().
"""
import os
import sys
import json
import contextlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import harness as H
import pipeline as p
import signal_engines as cf

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
G = p.LIVE_GEOMETRY
TIER = {"BUY", "STRONG_BUY"}
EPSILON = 0.05          # registered, derived from BTC's 0.045R median cost_r


# ----------------------------------------------------------------------
# COMPONENT SURGERY
# ----------------------------------------------------------------------
def rebuild_direction(m, w_pattern=0.6, w_ind=0.4, vix_extreme=35.0):
    """Recompute `direction` from its two component scores.

    combined = w_pattern * gated_score + w_ind * final_score, then
    pipeline.classify_direction with production bars. vix_extreme=1e9
    disables the extreme-fear regime without touching the vix data.
    """
    combined = w_pattern * m["gated_score"] + w_ind * m["final_score"]
    vix = m["vix_level"]
    dirs = [p.classify_direction(c, v, vix_extreme=vix_extreme)
            for c, v in zip(combined.to_numpy(), vix.to_numpy())]
    return pd.Series(dirs, index=m.index), combined


@contextlib.contextmanager
def flat_conviction():
    """STRONG_BUY/STRONG_SELL target multiplier 1.333 -> 1.0, at runtime.

    Implemented by asking the ORIGINAL function for the plain-conviction
    label, so every other behaviour of compute_exit_levels (side, rounding,
    NaN handling, the applicable/reason contract) is the untouched
    production code path. Restored unconditionally.
    """
    original = cf.compute_exit_levels
    flatten = {"STRONG_BUY": "BUY", "STRONG_SELL": "SELL"}

    def shim(entry_price, direction, atr, **kw):
        return original(entry_price, flatten.get(direction, direction), atr, **kw)

    cf.compute_exit_levels = shim
    try:
        yield
    finally:
        cf.compute_exit_levels = original


# ----------------------------------------------------------------------
# SCORING — one rung
# ----------------------------------------------------------------------
def episodes_of(trades):
    if not trades:
        return 0
    d = sorted(pd.to_datetime([t["date"] for t in trades]))
    hold = pd.Timedelta(days=G["max_hold_days"])
    return 1 + sum(1 for i in range(1, len(d)) if (d[i] - d[i - 1]) > hold)


def score_rung(mwin, bars, direction=None, confirm_days=None,
               flat_conv=False, folds=4):
    """INC_BUY_ALL through the incumbent's machinery, one thing changed."""
    f = mwin.copy()
    if direction is not None:
        f["direction"] = direction.reindex(f.index).values
    kw = dict(atr_source=G["atr_source"], max_hold_days=G["max_hold_days"],
              stop_mult=G["stop_mult"], target_mult=G["target_mult"],
              confirm_days=G["confirm_days"] if confirm_days is None else confirm_days,
              short_sma_filter=G["short_sma_filter"],
              fee_bps=H.FEE_BPS, slippage_bps=H.SLIPPAGE_BPS, verbose=False)
    ctx = flat_conviction() if flat_conv else contextlib.nullcontext()
    with ctx:
        results = p.evaluate_geometry_folds(f, bars, folds, **kw)
    sub = H._subset_folds(results, TIER)
    tr = [t for r in sub for t in r.get("trades", [])]
    pooled = p.stats_from_trades(tr)
    net_counted, ex_best, n_counted, folds_pos, _ = H._ex_best(sub)
    return {"n": pooled.get("n", 0),
            "episodes": episodes_of(tr),
            "win_pct": 100 * pooled.get("target_rate", float("nan")),
            "net_all": pooled.get("expectancy_r_net", float("nan")),
            "ex_best": ex_best,
            "folds_pos": folds_pos, "folds_counted": n_counted,
            "signal_days": int(f["direction"].isin(TIER).sum())}


# ----------------------------------------------------------------------
# THE LADDER — every rung is one removal from FULL
# ----------------------------------------------------------------------
def build_rungs(mwin):
    """(id, label, kwargs) for each rung. mwin is the untouched window."""
    d_no3, _ = rebuild_direction(mwin, w_pattern=1.0, w_ind=0.0)
    d_no1, _ = rebuild_direction(mwin, w_pattern=0.0, w_ind=1.0)
    d_novix, _ = rebuild_direction(mwin, vix_extreme=1e9)
    return [
        ("#197", "full construction",     {}),
        ("#198", "no Step 3 (1.0/0.0)",   {"direction": d_no3}),
        ("#199", "no Step 1 (0.0/1.0)",   {"direction": d_no1}),
        ("#200", "no confirm (2->1)",     {"confirm_days": 1}),
        ("#201", "no VIX regime",         {"direction": d_novix}),
        ("#202", "no conviction scaling", {"flat_conv": True}),
    ]


RUNG_IDS = ("#197", "#198", "#199", "#200", "#201", "#202")


def main():
    bars, merged, daily = H.load_ticker("BTC")
    w = H.make_windows(daily)
    bars_sealed = H.seal_bars(bars, w, "discovery")
    print("ABLATION #197-#202 — BTC INC_BUY_ALL, one-at-a-time-from-full")
    print("=" * 100)
    H.print_windows(w, daily, "BTC")

    # ---- reconstruction gate -------------------------------------------
    print("\nRECONSTRUCTION GATE — recomputed direction vs the stored column")
    scored = merged[merged.index < w.lockbox[0]]
    rebuilt, combined = rebuild_direction(scored)
    mism = int((rebuilt.values != scored["direction"].values).sum())
    cmax = float((combined - scored["combined_final_score"]).abs().max())
    print("  combined_final_score  max abs err : %.2e" % cmax)
    print("  direction             mismatches  : %d of %d days" % (mism, len(scored)))
    if mism or cmax > 1e-9:
        print("\n  GATE FAILED — the ablated rungs would not share a construction")
        print("  with #197. Refusing to score. No result is reported.")
        return 1
    print("  GATE PASSED — the rungs are measured against a baseline they share.")

    out = {}
    for wname, win in (("DISCOVERY", w.discovery), ("CONFIRMATION", w.confirmation)):
        mwin = H.slice_window(merged, win)
        print("\n%s  (%s -> %s, %d days)"
              % (wname, win[0].date(), win[1].date(), len(mwin)))
        rows = {}
        for rid, label, kw in build_rungs(mwin):
            r = score_rung(mwin, bars_sealed, **kw)
            r["label"] = label
            rows[rid] = r
            print("  %s %-24s signal_days=%-5d n=%-4d eps=%-4d net_all=%+.3f"
                  % (rid, label, r["signal_days"], r["n"], r["episodes"], r["net_all"]))
        out[wname] = rows

    # ---- table ----------------------------------------------------------
    print("\n" + "=" * 100)
    print("ABLATION — BTC INC_BUY_ALL, each rung = ONE removal from full")
    print("=" * 100)
    hdr = ("%-5s %-24s %7s %6s %5s %6s %8s %8s %8s %8s" %
           ("#", "rung", "sigdays", "n", "eps", "win%", "net_all", "delta",
            "ex_best", "folds"))
    for wname in ("DISCOVERY", "CONFIRMATION"):
        base = out[wname]["#197"]["net_all"]
        print("\n%s   (baseline #197 net_all = %+.3f)" % (wname, base))
        print(hdr)
        print("-" * 100)
        for rid in RUNG_IDS:
            r = out[wname][rid]
            eb = r["ex_best"]
            dl = "—" if rid == "#197" else "%+.3f" % (r["net_all"] - base)
            print("%-5s %-24s %7d %6d %5d %6.1f %+8.3f %8s %8s %4d/%-4d"
                  % (rid, r["label"], r["signal_days"], r["n"], r["episodes"],
                     r["win_pct"], r["net_all"], dl,
                     ("—" if eb != eb else "%+.3f" % eb),
                     r["folds_pos"], r["folds_counted"]))

    # ---- epsilon verdicts ------------------------------------------------
    print("\n" + "=" * 100)
    print("EPSILON RULE — |delta| > %.2fR on BOTH windows in the SAME direction"
          % EPSILON)
    print("=" * 100)
    verdicts = {}
    for rid in RUNG_IDS[1:]:
        dD = out["DISCOVERY"][rid]["net_all"] - out["DISCOVERY"]["#197"]["net_all"]
        dC = out["CONFIRMATION"][rid]["net_all"] - out["CONFIRMATION"]["#197"]["net_all"]
        big = abs(dD) > EPSILON and abs(dC) > EPSILON
        same = (dD > 0) == (dC > 0)
        v = "LOAD-BEARING" if (big and same) else "NO DETECTABLE CONTRIBUTION"
        if big and same:
            why = ""
        elif not big:
            small = " and ".join(x for x, d in (("DISC", dD), ("CONF", dC))
                                 if abs(d) <= EPSILON)
            why = "  (below epsilon on %s)" % small
        else:
            why = "  (opposite signs across windows)"
        verdicts[rid] = {"delta_disc": dD, "delta_conf": dC, "verdict": v}
        print("  %s %-24s dDISC %+.3f  dCONF %+.3f  ->  %s%s"
              % (rid, out["DISCOVERY"][rid]["label"], dD, dC, v, why))

    out["_verdicts"] = verdicts
    with open(os.path.join(ROOT, "research", "ablation_results.json"), "w") as fh:
        json.dump(out, fh, indent=2, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
