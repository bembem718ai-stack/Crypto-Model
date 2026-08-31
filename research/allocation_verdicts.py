"""ALLOCATION — verdict table, placebo percentiles, stability profiles.

Clauses (both windows, all required):
  1  annualised net return > 0
  2  above the block-shuffle placebo's Bonferroni percentile (k=4 -> 98.75)
  3  Sharpe above the MATCHED-EXPOSURE benchmark's Sharpe

#195 is the constant-1.0x control. Block-shuffling a CONSTANT scale path
returns the same path, and its matched-exposure benchmark is itself, so
clauses 2 and 3 are degenerate for it by construction. That is reported as
degenerate rather than dressed up as a pass or a fail.
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import portfolio_harness as PH
import window_stability as WS
import harness as H
import run_rotation as RT
import run_allocation as AL

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WINDOWS = ("DISCOVERY", "CONFIRMATION")


def main():
    uni = [l.strip() for l in
           open(os.path.join(ROOT, "research", "basket_tradable.txt"),
                encoding="utf-8") if l.strip()]
    px = PH.load_daily_closes(uni)
    bars, merged, daily = H.load_ticker("BTC")
    w = H.make_windows(daily)
    with open(os.path.join(ROOT, "research", "allocation_results.json")) as fh:
        res = json.load(fh)

    # ---- placebo fidelity, as the standing rule requires ----------------
    print("BLOCK-SHUFFLE FIDELITY — checked before any draw was scored")
    print("=" * 112)
    print("%-14s %10s %16s %10s %10s %14s"
          % ("window", "real turn", "placebo", "turn", "ratio", "drag pp/yr"),
          "  weight on non-existent assets")
    for wn in WINDOWS:
        f = res["_fidelity"][wn]
        print("%-14s %10.4f %16s %10s %10s %14s   real %.3f%%"
              % (wn, f["real_turnover"], "", "", "", "",
                 100 * f["real_weight_on_nonexistent"]))
        for k, name in (("weight_shuffle", "weight-matrix"),
                        ("scale_shuffle", "scale (USED)")):
            d = f[k]
            print("%-14s %10s %16s %10.4f %9.2fx %13.3f   %.3f%%"
                  % ("", "", name, d["turnover"], d["ratio"], d["drag_pp"],
                     100 * d["weight_on_nonexistent"]))
    print()

    # ---- placebo percentiles (recomputed with the actual stored) --------
    pct = {}
    for wn, win in (("DISCOVERY", w.discovery), ("CONFIRMATION", w.confirmation)):
        seg = px[(px.index >= win[0]) & (px.index < win[1])]
        R = seg.pct_change().fillna(0.0).to_numpy(dtype=float)
        base, _, _ = AL.base_weights(seg)
        vol = AL.realised_vol(base, seg)
        pct[wn] = {}
        for rid, label, target, mode in AL.RULES:
            sc = AL.scale_path(vol, target, mode)
            vals = []
            for s in range(AL.SEEDS):
                W = AL.scaled_weights(base, AL.scale_block_shuffle(sc, seed=s))
                vals.append(RT.ann_from_fast(W.to_numpy(dtype=float), R)[0])
            a = np.array(vals)
            act = res[wn][rid]["ann_return"]
            pct[wn][rid] = {"pctile": float(100.0 * (a < act).mean()),
                            "mean": float(a.mean()),
                            "p50": float(np.percentile(a, 50))}

    print("REGISTERED CLAUSES — both windows required")
    print("=" * 112)
    print("%-6s %-24s %-13s %8s %8s %9s %9s %9s   %s"
          % ("#", "rule", "window", "ann", "sharpe", "plc p_adj", "plc pct",
             "match Sh", "clauses 1/2/3"))
    print("-" * 112)
    verdicts = {}
    for rid, label, target, mode in AL.RULES:
        allpass = True
        for wn in WINDOWS:
            r = res[wn][rid]
            c1 = r["ann_return"] > 0
            c2 = r["ann_return"] > r["placebo"]["p_adj"]
            c3 = r["sharpe"] > r["matched_sharpe"]
            allpass &= (c1 and c2 and c3)
            print("%-6s %-24s %-13s %+8.3f %+8.3f %+9.3f %8.1f%% %+9.3f   %s %s %s"
                  % (rid, label, wn, r["ann_return"], r["sharpe"],
                     r["placebo"]["p_adj"], pct[wn][rid]["pctile"],
                     r["matched_sharpe"],
                     "PASS" if c1 else "FAIL", "PASS" if c2 else "FAIL",
                     "PASS" if c3 else "FAIL"))
        verdicts[rid] = "PASS" if allpass else "FAIL"
        print("       -> %s: %s\n" % (rid, verdicts[rid]))

    print("#195  constant 1.0x equal-weight-26 (control)")
    for wn in WINDOWS:
        r = res[wn]["#195"]
        print("       %-13s ann %+.3f  vol %.3f  sharpe %+.3f  gross %.3f   "
              "clause 1 %s | clauses 2,3 DEGENERATE by construction"
              % (wn, r["ann_return"], r["ann_vol"], r["sharpe"], r["avg_gross"],
                 "PASS" if r["ann_return"] > 0 else "FAIL"))
    print("       (block-shuffling a CONSTANT scale returns the same path, and its\n"
          "        matched-exposure benchmark IS itself -- neither is a test.)\n")

    print("MATCHED-EXPOSURE BENCHMARK — construction verified")
    print("-" * 112)
    for wn in WINDOWS:
        for rid, label, _t, _m in AL.RULES:
            r = res[wn][rid]
            print("  %-13s %-6s c=%.4f  |mean gross(bench) - mean gross(rule)| = %.2e"
                  % (wn, rid, r["matched_c"], r["matched_gap"]))
    print()

    # ---- stability, every rule ------------------------------------------
    print("WINDOW-STABILITY of annualised net return (50 starts, end pinned)")
    print("-" * 112)
    stab = {}
    for wn, win in (("DISCOVERY", w.discovery), ("CONFIRMATION", w.confirmation)):
        stab[wn] = {}
        end = win[1]
        for rid, label, target, mode in AL.RULES + [("#195", "constant 1.0x", None, None)]:
            def stat(start, _end, target=target, mode=mode):
                seg = px[(px.index >= start) & (px.index < end)]
                if len(seg) < 180:
                    return float("nan")
                base, ex, sk = AL.base_weights(seg)
                if ex < 10:
                    return float("nan")
                Rm = seg.pct_change().fillna(0.0).to_numpy(dtype=float)
                if mode is None:
                    W = base
                else:
                    W = AL.scaled_weights(
                        base, AL.scale_path(AL.realised_vol(base, seg), target, mode))
                return RT.ann_from_fast(W.to_numpy(dtype=float), Rm)[0]

            pr = WS.profile(stat, px.index.min(), end, n_starts=50, min_span_frac=0.5)
            stab[wn][rid] = {k: v for k, v in pr.items() if k != "table"}
            print("  %-13s %-6s %-24s defined=%2d/50  sign-stability %3.0f%% (%s)  "
                  "range %+.3f..%+.3f  median %+.3f"
                  % (wn, rid, label, pr["n_defined"], 100 * pr["sign_stability"],
                     pr["modal_sign"], pr["min"], pr["max"], pr["median"]))
        print()

    with open(os.path.join(ROOT, "research", "allocation_verdicts.json"), "w") as fh:
        json.dump({"verdicts": verdicts, "pctiles": pct, "stability": stab},
                  fh, indent=2, default=str)
    print("OVERALL: " + ", ".join("%s %s" % (k, v) for k, v in verdicts.items())
          + ", #195 control (degenerate clauses)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
