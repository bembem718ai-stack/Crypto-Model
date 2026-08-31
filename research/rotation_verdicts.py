"""ROTATION — verdict table and stability profiles, from rotation_results.json.

Every registered clause evaluated per rule per window, then a 50-start
window-stability profile of annualised net return for every rule (not only
the ones that pass something -- selecting which rules get an error bar on the
basis of their result is the move this project forbids).
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
import run_rotation as R

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WINDOWS = ("DISCOVERY", "CONFIRMATION")
LB_OF = {"#187": "30", "#188": "30", "#189": "90", "#190": "90", "#192": "30"}


def clauses(res, rid, wname):
    r = res[wname][rid]
    eq = res[wname]["#191"]["ann_return"]
    ann = r["ann_return"]
    c = {"1_positive": ann > 0,
         "2_above_placebo_adj": ann > r["placebo"]["p_adj"],
         "3_beats_eq26": ann > eq}
    if r["is_top5"] and rid in ("#187", "#189"):
        c["4_beats_random5_p95"] = ann > res[wname]["_random5"][LB_OF[rid]]["p95"]
    return c


def main():
    with open(os.path.join(ROOT, "research", "rotation_results.json")) as fh:
        res = json.load(fh)

    print("ROTATION #187-#192 — REGISTERED CLAUSES, both windows required")
    print("=" * 118)
    hdr = ("%-6s %-18s %-13s %8s %9s %9s %9s %9s   %s"
           % ("#", "rule", "window", "ann", "plc p_adj", "eq26", "r5 p95",
              "turn", "clauses 1/2/3/4"))
    print(hdr)
    print("-" * 118)
    verdicts = {}
    for rid in ("#187", "#188", "#189", "#190", "#192"):
        allpass = True
        for wname in WINDOWS:
            r = res[wname][rid]
            c = clauses(res, rid, wname)
            allpass &= all(c.values())
            r5 = res[wname]["_random5"][LB_OF[rid]]["p95"] if "4_beats_random5_p95" in c else float("nan")
            marks = " ".join(("PASS" if c[k] else "FAIL") for k in sorted(c))
            print("%-6s %-18s %-13s %+8.3f %+9.3f %+9.3f %9s %9.4f   %s"
                  % (rid, r["label"], wname, r["ann_return"],
                     r["placebo"]["p_adj"], res[wname]["#191"]["ann_return"],
                     ("—" if r5 != r5 else "%+.3f" % r5),
                     r["avg_turnover"], marks))
        verdicts[rid] = "PASS" if allpass else "FAIL"
        print("       -> %s: %s\n" % (rid, verdicts[rid]))

    print("CONTROLS (reported beside the rules, never promoted)")
    print("-" * 118)
    for wname in WINDOWS:
        e = res[wname]["#191"]
        print("  %-13s #191  equal-weight all eligible   ann %+.3f  turn %.4f  rebal %d/%d"
              % (wname, e["ann_return"], e["avg_turnover"],
                 e["rebal_executed"], e["rebal_executed"] + e["rebal_skipped"]))
        for lb in ("30", "90"):
            d = res[wname]["_random5"][lb]
            print("  %-13s #191b random-5 (%s-day eligible set, %d draws)  "
                  "p05 %+.3f  p50 %+.3f  p95 %+.3f  turn %.4f"
                  % (wname, lb, d["draws"], d["p05"], d["p50"], d["p95"],
                     d["avg_turnover"]))
        m = res[wname]["#192"]
        print("  %-13s #192  bottom-5 by 30d (momentum's mirror)  ann %+.3f"
              % (wname, m["ann_return"]))
        print()

    print("PLACEBO TURNOVER FIDELITY — primary null vs the real rule")
    print("-" * 118)
    for wname in WINDOWS:
        for rid in ("#187", "#188", "#189", "#190", "#192"):
            r = res[wname][rid]
            print("  %-13s %-6s real %.4f   fixed-perm %.4f (%.2fx)   "
                  "per-rebalance %.4f (%.2fx)"
                  % (wname, rid, r["avg_turnover"], r["placebo"]["avg_turnover"],
                     r["placebo"]["avg_turnover"] / r["avg_turnover"],
                     r["placebo_secondary"]["avg_turnover"],
                     r["placebo_secondary"]["avg_turnover"] / r["avg_turnover"]))
    print()

    # ---- stability profiles, every rule, both windows --------------------
    uni = [l.strip() for l in
           open(os.path.join(ROOT, "research", "basket_tradable.txt"),
                encoding="utf-8") if l.strip()]
    px = PH.load_daily_closes(uni)
    bars, merged, daily = H.load_ticker("BTC")
    w = H.make_windows(daily)

    print("WINDOW-STABILITY of annualised net return (50 starts, end pinned)")
    print("-" * 118)
    stab = {}
    for wname, win in (("DISCOVERY", w.discovery), ("CONFIRMATION", w.confirmation)):
        stab[wname] = {}
        end = win[1]
        for rid, label, kw, _t in R.RULES:
            def stat(start, _end, kw=kw):
                seg = px[(px.index >= start) & (px.index < end)]
                if len(seg) < 180:
                    return float("nan")
                W, ex, sk = R.momentum_weights(seg, **kw)
                if ex < 10:
                    return float("nan")
                Rm = seg.pct_change().fillna(0.0).to_numpy(dtype=float)
                return R.ann_from_fast(W.to_numpy(dtype=float), Rm)[0]

            pr = WS.profile(stat, px.index.min(), end, n_starts=50, min_span_frac=0.5)
            stab[wname][rid] = {k: v for k, v in pr.items() if k != "table"}
            print("  %-13s %-6s %-18s defined=%2d/50  sign-stability %3.0f%% (%s)  "
                  "range %+.3f..%+.3f  median %+.3f"
                  % (wname, rid, label, pr["n_defined"],
                     100 * pr["sign_stability"], pr["modal_sign"],
                     pr["min"], pr["max"], pr["median"]))
        print()

    out = {"verdicts": verdicts, "stability": stab}
    with open(os.path.join(ROOT, "research", "rotation_verdicts.json"), "w") as fh:
        json.dump(out, fh, indent=2, default=str)
    print("OVERALL: " + ", ".join("%s %s" % (k, v) for k, v in verdicts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
