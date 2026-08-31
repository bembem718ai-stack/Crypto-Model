"""EQUITIES — verdict table, controls, and stability profiles.

Clauses (both windows, all required):
  1  net annualised return > 0
  2  above the placebo's Bonferroni-adjusted percentile (k=6 -> 99.1667)
  3  above #210 (equal-weight eligible) on net annualised return
  4  CS rules only: above #215 random-N p95 for the matching N

A clause whose placebo failed the registered fidelity check is reported
UNMEASURABLE -- not a pass and not a fail -- following the project's standing
ex_best convention. Since every clause must pass on both windows, an
unmeasurable cell is decision-relevant only if nothing else already fails.
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import window_stability as WS
import run_equities as EQ

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WINDOWS = ("DISCOVERY", "CONFIRMATION")
RULES = [("#204", 3), ("#205", 5), ("#206", 3), ("#207", 5), ("#208", None),
         ("#209", None)]
CONTROLS = ("#210", "#211", "#212", "#213", "#214", "#216")


def main():
    with open(os.path.join(ROOT, "research", "equities_results.json")) as fh:
        res = json.load(fh)

    print("PLACEBO FIDELITY — three axes, measured before any draw was scored")
    print("=" * 120)
    print("%-13s %-6s %8s %8s %7s %11s %10s %10s   %s"
          % ("window", "#", "real tn", "plc tn", "ratio", "drag pp/yr",
             "inelig R", "inelig P", "cash-eligible months"))
    for wn in WINDOWS:
        for rid in ("#204", "#205", "#206", "#207", "#208", "#209"):
            f = res["_fidelity"][wn][rid]
            cash = ""
            if "cash_dev" in f:
                cash = ("%d -> %.1f  dev %.2f%%  %s"
                        % (f["real_cash_months"], f["plc_cash_months"],
                           100 * f["cash_dev"], "PASS" if f["cash_ok"] else "FAIL"))
            print("%-13s %-6s %8.4f %8.4f %6.2fx %+11.3f %9.3f%% %9.3f%%   %s"
                  % (wn, rid, f["real_turn"], f["plc_turn"], f["ratio"],
                     f["drag_pp"], 100 * f["real_inelig"], 100 * f["plc_inelig"], cash))
    print()

    print("RESULTS — every registered clause, both windows required")
    print("=" * 120)
    print("%-6s %-22s %-13s %8s %8s %8s %9s %8s %9s %8s   %s"
          % ("#", "rule", "window", "ann", "sharpe", "maxDD", "plc p_adj",
             "plc pct", "eq210", "r5 p95", "1/2/3/4"))
    print("-" * 120)
    verdicts, clause_map = {}, {}
    for rid, n in RULES:
        allpass, anypass = True, False
        clause_map[rid] = {}
        for wn in WINDOWS:
            r = res[wn][rid]
            eq = res[wn]["#210"]["ann_return"]
            fid = res["_fidelity"][wn][rid]
            c = {}
            c["1"] = r["ann_return"] > 0
            measurable = fid.get("cash_ok", True)
            c["2"] = (r["ann_return"] > r["placebo"]["p_adj"]) if measurable else None
            c["3"] = r["ann_return"] > eq
            r5 = float("nan")
            if n is not None:
                r5 = res[wn]["_random"][str(n)]["p95"]
                c["4"] = r["ann_return"] > r5
            marks = " ".join("PASS" if v else ("UNMEAS" if v is None else "FAIL")
                             for v in c.values())
            for v in c.values():
                if v is True:
                    anypass = True
                if v is not True:
                    allpass = False
            clause_map[rid][wn] = c
            print("%-6s %-22s %-13s %+8.4f %+8.3f %+8.3f %+9.4f %7.1f%% %+9.4f %8s   %s"
                  % (rid, r["label"], wn, r["ann_return"], r["sharpe"], r["max_dd"],
                     r["placebo"]["p_adj"], r["placebo"]["pctile"], eq,
                     ("—" if r5 != r5 else "%+.4f" % r5), marks))
        verdicts[rid] = {"verdict": "PASS" if allpass else "FAIL", "any_clause": anypass}
        print("       -> %s: %s\n" % (rid, verdicts[rid]["verdict"]))

    print("CONTROLS — reported beside the rules, never promoted")
    print("-" * 120)
    for wn in WINDOWS:
        for rid in CONTROLS:
            r = res[wn][rid]
            print("  %-13s %-6s %-24s ann %+.4f  sharpe %+.3f  maxDD %+.3f  gross %.3f"
                  % (wn, rid, r["label"], r["ann_return"], r["sharpe"],
                     r["max_dd"], r["avg_gross"]))
        for n in ("3", "5"):
            d = res[wn]["_random"][n]
            print("  %-13s #215   random-%s (%d draws)      p05 %+.4f  p50 %+.4f  p95 %+.4f"
                  % (wn, n, d["draws"], d["p05"], d["p50"], d["p95"]))
        print()

    # ---- TS caveat expiry ------------------------------------------------
    print("TS-MOM CAVEAT — expiry test (registered)")
    print("-" * 120)
    for rid in ("#208", "#209"):
        broad = True
        for wn in WINDOWS:
            r, eq = res[wn][rid], res[wn]["#210"]
            beats_sharpe = r["sharpe"] > eq["sharpe"]
            better_dd = r["max_dd"] > eq["max_dd"]        # less negative = better
            print("  %-6s %-13s sharpe %+.3f vs eq %+.3f -> %-5s | maxDD %+.3f vs %+.3f -> %s"
                  % (rid, wn, r["sharpe"], eq["sharpe"], "BEAT" if beats_sharpe else "lose",
                     r["max_dd"], eq["max_dd"], "BETTER" if better_dd else "worse"))
            if beats_sharpe or better_dd:
                broad = False
        print("  %-6s -> caveat %s\n"
              % (rid, "EXPIRES (fails the descriptive risk-adjusted read too; "
                      "may not be cited)" if broad
                      else "RETAINED (the risk-adjusted read is not a broad failure)"))

    # ---- stability for anything clearing any clause ----------------------
    print("WINDOW-STABILITY of annualised net return (50 starts, end pinned)")
    print("-" * 120)
    px_all, elig_from, freeze = EQ.load()
    me = EQ.month_end_closes(px_all)
    sig12, sig6 = EQ.signal(me, 12), EQ.signal(me, 6)
    elig_all = EQ.eligibility(me, elig_from)
    w = res["_windows"]
    stab = {}
    for wn, lo, hi in (("DISCOVERY", w["start"], w["cut"]),
                       ("CONFIRMATION", w["cut"], w["lock"])):
        stab[wn] = {}
        end = pd.Timestamp(hi)
        for rid, n in RULES:
            if not verdicts[rid]["any_clause"]:
                continue

            def stat(start, _end, rid=rid):
                seg = px_all[(px_all.index >= start) & (px_all.index < end)]
                if len(seg) < 500:
                    return float("nan")
                g = EQ.MonthGrid(seg, {12: sig12, 6: sig6}, elig_all)
                if len(g.months) < 24:
                    return float("nan")
                if rid in EQ.CS_PARAMS:
                    lb, nn = EQ.CS_PARAMS[rid]
                    W, ex, _ = EQ.cs_weights(g, lb, nn)
                elif rid == "#209":
                    W, ex, _ = EQ.ts_weights(g, only_idx=g.cols.index("SPY"))
                else:
                    W, ex, _ = EQ.ts_weights(g)
                if ex < 12:
                    return float("nan")
                R = seg.pct_change().fillna(0.0).to_numpy(dtype=float)
                return EQ.score(W, R)["ann_return"]

            pr = WS.profile(stat, px_all.index.min(), end, n_starts=50,
                            min_span_frac=0.5)
            stab[wn][rid] = {k: v for k, v in pr.items() if k != "table"}
            print("  %-13s %-6s defined=%2d/50  sign-stability %3.0f%% (%s)  "
                  "range %+.4f..%+.4f  median %+.4f"
                  % (wn, rid, pr["n_defined"], 100 * pr["sign_stability"],
                     pr["modal_sign"], pr["min"], pr["max"], pr["median"]))
        print()

    with open(os.path.join(ROOT, "research", "equities_verdicts.json"), "w") as fh:
        json.dump({"verdicts": verdicts, "stability": stab}, fh, indent=2, default=str)
    print("OVERALL: " + ", ".join("%s %s" % (k, v["verdict"]) for k, v in verdicts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
