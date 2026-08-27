"""Record H-basket-B/C and the tier curve in docs/cleanroom.md."""
import os
import json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
R = json.load(open(os.path.join(ROOT, "research", "basket_bc_results.json")))


def f(v, d=3, plus=True):
    if v is None:
        return "—"
    return ("%+." + str(d) + "f") % v if plus else ("%." + str(d) + "f") % v


L = []
A = L.append
A("\n## Results of H-basket-B (#164), H-basket-C (#165), H-tier-curve (#166)\n")
A("Run on the #167 tradable subset (26 tickers) and, for B, on the full 82")
A("alongside so the filter's effect is visible rather than hidden. Placebo is")
A("the episode-matched draw registered in #167: 300 seeds, random runs")
A("matching each ticker's observed run-length distribution.\n")
A("SEALED 2019-09-24 -> 2026-02-26 | DISCOVERY -> 2023-04-06 | CONFIRMATION")
A("-> 2026-02-26. Every trade produced by `pipeline.backtest_exit_geometry`")
A("with `LIVE_GEOMETRY`; the day->trade lookup used to make 300-seed")
A("placebos tractable was verified to reproduce `harness.incumbent_rows`")
A("trade-for-trade on both tiers before any of this was reported.\n")

A("### H-basket-B — ALL FOUR VARIANTS FAIL\n")
A("Registered direction: `ex_best` > 0 on BOTH windows AND `net_all` above")
A("the placebo p95 on BOTH.\n")
A("| variant | window | n | eps | win% | net_all | ex_best | folds+/cnt | totR | maxDD | plc mean | plc p95 | ex>0 | net>p95 |")
A("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
for key, label in (("B_tradable_26_STRONG_BUY", "tradable 26 / STRONG_BUY"),
                   ("B_FULL_82_STRONG_BUY", "FULL 82 / STRONG_BUY"),
                   ("B_tradable_26_INC_BUY_ALL", "tradable 26 / INC_BUY_ALL"),
                   ("B_FULL_82_INC_BUY_ALL", "FULL 82 / INC_BUY_ALL")):
    for wname in ("DISCOVERY", "CONFIRMATION"):
        s = R[key][wname]
        A("| %s | %s | %d | %d | %s | %s | %s | %d/%d | %s | %s | %s | %s | %s | %s |"
          % (label, wname, s["n"], s["episodes"], f(s["win_pct"], 1, False),
             f(s["net_all"]), f(s["ex_best"]), s["folds_pos"], s["folds_counted"],
             f(s["total_R"], 1), f(s["maxDD_R"], 1, False),
             f(s["placebo_mean"]), f(s["placebo_p95"]),
             "Y" if s["ex_pos"] else "N", "Y" if s["beats_p95"] else "N"))
A("")
for key, label in (("B_tradable_26_STRONG_BUY", "tradable 26 / STRONG_BUY"),
                   ("B_FULL_82_STRONG_BUY", "FULL 82 / STRONG_BUY"),
                   ("B_tradable_26_INC_BUY_ALL", "tradable 26 / INC_BUY_ALL"),
                   ("B_FULL_82_INC_BUY_ALL", "FULL 82 / INC_BUY_ALL")):
    A("- **%s: %s**" % (label, R[key + "_verdict"]))
A("")
A("**Why each failed.**\n")
A("- *tradable 26 / STRONG_BUY* — CONFIRMATION passes BOTH conditions")
A("  cleanly (net +0.815 vs p95 +0.332, `ex_best` +0.424, 4 of 4 folds")
A("  positive). DISCOVERY does not: `ex_best` is UNDEFINED (only 2 folds")
A("  reach 10 trades) and net +0.239 sits below its p95 of +0.570. The rule")
A("  requires both windows. **One good window is not the hypothesis.**")
A("- *FULL 82 / STRONG_BUY* — CONFIRMATION collapses to **-2.016R** with")
A("  totR **-1044R**. That is the illiquidity cost artifact recorded above:")
A("  518 pooled trades against the tradable subset's 87, the extra 431")
A("  coming from pairs whose ATR-derived stop is a fraction of a percent, so")
A("  `cost_r = 8bps / stop_fraction` dominates. This is the filter's effect")
A("  made visible: **+0.815 tradable vs -2.016 unfiltered on the same")
A("  window.**")
A("- *tradable 26 / INC_BUY_ALL* — CONFIRMATION misses by **0.001R**: net")
A("  +0.067 against a placebo p95 of +0.068. Recorded as a FAIL exactly as")
A("  registered. \"Almost\" was pre-declared to be a failure and it is being")
A("  treated as one; it does not get a second look at a looser bar.")
A("  DISCOVERY is negative anyway (-0.011, `ex_best` -0.030).")
A("- *FULL 82 / INC_BUY_ALL* — negative on both windows.\n")
A("Note the placebo is not weak. On DISCOVERY/INC_BUY_ALL the episode-")
A("matched placebo MEAN (+0.209 tradable, +0.136 full) BEATS the incumbent's")
A("observed net (-0.011, -0.031). Random clustered entries did better than")
A("the signal on that window.\n")

A("### H-basket-C — FAIL (3 of 4 quartiles positive, not 4)\n")
A("Registered direction: pooled STRONG_BUY `net_all` AND `ex_best` positive")
A("in ALL FOUR quartiles on SEALED. Quartiles fixed by seed 20260827 before")
A("any scoring; membership here is each quartile intersected with the #167")
A("tradable subset.\n")
A("| quartile | tradable/total | n | eps | win% | net_all | ex_best | folds+/cnt | totR | maxDD |")
A("|---|---|---|---|---|---|---|---|---|---|")
mem = {"Q1": "AAVE ALGO BTC LINK XRP", "Q2": "ATOM AVAX BNB DOGE ETC ETH VTHO",
       "Q3": "ADA BCH FET NEAR ONE SOL TRX XLM", "Q4": "DOT GALA LTC OP UNI VET"}
cnt = {"Q1": "5/22", "Q2": "7/22", "Q3": "8/21", "Q4": "6/21"}
for q in ("Q1", "Q2", "Q3", "Q4"):
    s = R["C"][q]
    A("| %s | %s | %d | %d | %s | %s | %s | %d/%d | %s | %s |"
      % (q, cnt[q], s["n"], s["episodes"], f(s["win_pct"], 1, False),
         f(s["net_all"]), f(s["ex_best"]), s["folds_pos"], s["folds_counted"],
         f(s["total_R"], 1), f(s["maxDD_R"], 1, False)))
A("")
for q in ("Q1", "Q2", "Q3", "Q4"):
    A("- %s: %s" % (q, mem[q]))
A("")
A("**VERDICT: %s.** Q3 is negative (-0.250R on 28 trades). And the deeper"
  % R["C_verdict"])
A("problem is that `ex_best` — the statistic the pass condition names — is")
A("**UNDEFINED in three of the four quartiles**: Q1, Q3 and Q4 never reach 3")
A("folds carrying 10 trades. Only Q2 can produce the number at all. So C does")
A("not fail narrowly; it fails because splitting an already-thin signal four")
A("ways leaves nothing measurable. This is H-basket-A's finding (0 of 82")
A("tickers reach a defined `ex_best`) reappearing one level up.\n")

A("### H-tier-curve (#166) — DESCRIPTIVE, SELECTS NOTHING\n")
A("DISCOVERY, tradable subset, days at or above the score painted STRONG_BUY")
A("so the geometry is constant across the curve and the rows are comparable.\n")
A("| score >= | n | eps | win% | net_all | ex_best | folds+/cnt | totR | maxDD |")
A("|---|---|---|---|---|---|---|---|---|")
for thr in ("75", "70", "65", "60"):
    s = R["tier_curve"][thr]
    A("| %s | %d | %d | %s | %s | %s | %d/%d | %s | %s |"
      % (thr, s["n"], s["episodes"], f(s["win_pct"], 1, False), f(s["net_all"]),
         f(s["ex_best"]), s["folds_pos"], s["folds_counted"],
         f(s["total_R"], 1), f(s["maxDD_R"], 1, False)))
A("")
A("The curve is NOT monotonic in the way a real conviction ladder would be.")
A("The highest tier (>=75) has the best net (+0.239) but only 46 trades and")
A("no computable `ex_best`; >=70 is the WORST row (+0.044, `ex_best`")
A("-0.060); >=65 and >=60 are flat at +0.070/+0.068 with `ex_best` barely")
A("above zero (+0.016/+0.029) on 908 and 1,782 trades. Loosening the score")
A("buys trade count and buys almost no edge.\n")
A("**NOTHING IS SELECTED FROM THIS.** Per #166 no threshold may be promoted")
A("on the strength of this curve; any future use of a score cut is a NEW")
A("hypothesis with its own number, tested on data this curve did not touch.")
A("It is recorded so a later \"we always knew 65 was the level\" is checkable")
A("against what was actually seen, and when.\n")

A("### Program status after #163-#167\n")
A("Every registered hypothesis in the EVENT RATE program has now failed:")
A("#163 (0 of 82 tickers measurable), #164 (all four B variants), #165")
A("(3 of 4 quartiles, and unmeasurable in three). #166 is descriptive and")
A("selects nothing. #167 did what it was for — it made the difference")
A("between +0.815 and -2.016 on the same window visible — but a filter is")
A("not a result.\n")

path = os.path.join(ROOT, "docs", "cleanroom.md")
src = open(path, encoding="utf-8").read()
open(path, "w", encoding="utf-8").write(src.rstrip("\n") + "\n" + "\n".join(L))
print("recorded B/C/tier-curve results")
