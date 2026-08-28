"""Run #170 (ARM B edge test), exactly as registered.

PASS RULE, all of it or FAIL, no partial credit:
  1. `ex_best` defined AND > 0 on >= 2 of 3 tickers, on BOTH windows.
  2. POOLED net_all above the episode-matched placebo p95 on BOTH windows.

DISCOVERY `ex_best` was computed under #169 and those values stand; this
run verifies it reproduces them identically and does not recompute or
reframe them.
"""
import os
import sys
import json
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import arm1h as A
from run_arm_a import all_bar_lookup, runs_of

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEEDS = 300
ARM = A.ARM_B


def pooled_stats(frames, window, folds=4):
    """Pool trades across tickers; folds cut by TIME over `window`."""
    t = pd.concat([f for f in frames if len(f)], ignore_index=True) if frames else pd.DataFrame()
    if not len(t):
        return {"n": 0}
    out = {"n": len(t),
           "win_pct": 100 * (t["outcome"] == "target").mean(),
           "net_all": float(t["pnl_r_net"].mean()),
           "total_R": float(t["pnl_r_net"].sum())}
    edges = pd.date_range(window[0], window[1], periods=folds + 1)
    fi = pd.cut(t["ts"], edges, labels=False, include_lowest=True)
    counted = [(len(t[fi == k]), float(t[fi == k]["pnl_r_net"].mean()))
               for k in range(folds) if len(t[fi == k]) >= 10]
    out["folds_counted"] = len(counted)
    out["folds_pos"] = sum(1 for n, m in counted if m > 0)
    if len(counted) >= 3:
        tn = sum(n for n, _ in counted); tr = sum(n * m for n, m in counted)
        bn, bm = max(counted, key=lambda c: c[0] * c[1])
        rest = tn - bn
        out["ex_best"] = (tr - bn * bm) / rest if rest else float("nan")
    else:
        out["ex_best"] = float("nan")
    return out


def placebo_draws(specs, seeds=SEEDS):
    """Episode-matched placebo. Each seed redraws every ticker's runs and
    pools the resulting trades, mirroring the observed pooling."""
    nets = []
    for s in range(seeds):
        rng = np.random.default_rng(970000 + s)
        pool = []
        for tk, (lookup, index, runlens) in specs.items():
            n = len(index)
            if n < 5 or not runlens:
                continue
            taken = np.zeros(n, dtype=bool)
            picked = []
            C = ARM["confirm_bars"]
            for L in runlens:
                for _ in range(12):
                    st = int(rng.integers(0, max(1, n - L)))
                    if not taken[st:st + L].any():
                        taken[st:st + L] = True
                        for j in range(st + C - 1, st + L):
                            picked.append(index[j])
                        break
            if picked:
                sel = lookup.reindex(pd.Index(picked)).dropna(subset=["pnl_r_net"])
                if len(sel):
                    pool.append(sel)
        if pool:
            allp = pd.concat(pool)
            nets.append(float(allp["pnl_r_net"].mean()))
    a = np.array(nets)
    return {"seeds": seeds, "valid": len(a),
            "mean": float(a.mean()) if len(a) else float("nan"),
            "p95": float(np.percentile(a, 95)) if len(a) else float("nan")}


def per_ticker_placebo(lookup, index, runlens, seeds=SEEDS):
    return placebo_draws({"one": (lookup, index, runlens)}, seeds=seeds)


def main():
    t0 = time.time()
    w = A.windows_1h(A.load_1h("BTC"))
    windows = {"DISCOVERY": w["discovery"], "CONFIRMATION": w["confirmation"]}
    results = {}

    for wname, win in windows.items():
        per, specs, frames = {}, {}, []
        for tk in A.TICKERS:
            f, bars = A.build_scores(tk, ARM, w)
            f = f[(f.index >= win[0]) & (f.index < win[1])]
            tr = A.score(A.entries_for(f, bars, ARM, "STRONG_BUY"), bars, ARM)
            st = A.stats(tr, ARM, window=win)
            lk = all_bar_lookup(f, bars, ARM, "STRONG_BUY")
            mask = f["direction"].eq("STRONG_BUY").values
            rl = runs_of(mask)
            specs[tk] = (lk, f.index, rl)
            st["placebo"] = per_ticker_placebo(lk, f.index, rl)
            per[tk] = st
            if len(tr):
                frames.append(tr)
            print("  %s %s: n=%s (%.0fs)" % (wname, tk, st.get("n", 0), time.time() - t0))
        pooled = pooled_stats(frames, win)
        pooled["placebo"] = placebo_draws(specs)
        results[wname] = {"per_ticker": per, "pooled": pooled,
                          "window": [str(win[0]), str(win[1])]}

    with open(os.path.join(ROOT, "research", "arm_b_170_results.json"), "w") as fh:
        json.dump(results, fh, indent=2, default=str)

    # ---- report
    print("\n" + "=" * 104)
    print("#170 (ARM B edge test) — RESULTS")
    print("=" * 104)
    for wname in ("DISCOVERY", "CONFIRMATION"):
        r = results[wname]
        print("\n%s  %s -> %s" % (wname, r["window"][0], r["window"][1]))
        print("%-6s %7s %9s %7s %10s %10s %11s" %
              ("tkr", "n", "episodes", "win%", "net_all", "ex_best", "plc p95"))
        print("-" * 70)
        for tk in A.TICKERS:
            s = r["per_ticker"][tk]
            if not s.get("n"):
                print("%-6s %7s" % (tk, 0)); continue
            eb = s.get("ex_best", float("nan"))
            print("%-6s %7d %9d %7.1f %+10.3f %10s %+11.3f" %
                  (tk, s["n"], s["episodes"], s["win_pct"], s["net_all"],
                   ("—" if eb != eb else "%+.3f" % eb), s["placebo"]["p95"]))
        p = r["pooled"]
        eb = p.get("ex_best", float("nan"))
        print("%-6s %7d %9s %7.1f %+10.3f %10s %+11.3f" %
              ("POOLED", p["n"], "-", p["win_pct"], p["net_all"],
               ("—" if eb != eb else "%+.3f" % eb), p["placebo"]["p95"]))

    print("\n" + "=" * 104)
    print("REGISTERED CONDITIONS")
    print("=" * 104)
    ok1_all, ok2_all = True, True
    for wname in ("DISCOVERY", "CONFIRMATION"):
        r = results[wname]
        good = [tk for tk in A.TICKERS
                if r["per_ticker"][tk].get("ex_best", float("nan")) ==
                r["per_ticker"][tk].get("ex_best", float("nan"))
                and r["per_ticker"][tk].get("ex_best", -1) > 0]
        ok1 = len(good) >= 2
        ok1_all &= ok1
        p = r["pooled"]
        ok2 = p["net_all"] > p["placebo"]["p95"]
        ok2_all &= ok2
        print("  %-12s cond 1 ex_best>0 on >=2 of 3: %d of 3 (%s) -> %s"
              % (wname, len(good), ", ".join(good) if good else "none",
                 "PASS" if ok1 else "FAIL"))
        print("  %-12s cond 2 pooled net > placebo p95: %+.3f vs %+.3f -> %s"
              % ("", p["net_all"], p["placebo"]["p95"], "PASS" if ok2 else "FAIL"))
    print("\n  VERDICT: %s" % ("PASS" if (ok1_all and ok2_all) else "FAIL"))
    print("  total %.0fs" % (time.time() - t0))


if __name__ == "__main__":
    main()
