"""Record the ARM A (#168) result in docs/cleanroom.md."""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
d = json.load(open(os.path.join(ROOT, "research", "arm_a_results.json")))

L = []
A = L.append
A("\n## Result of ARM A (#168) — recorded 2026-08-28\n")
A("Time-equivalent 1h. SEALED span **2019-09-23 08:00 -> 2026-02-28 04:00**;")
A("lockbox 2026-02-28 -> 2026-08-28 never read, 1h feed sealed at the boundary.")
A("Trades resolved by `research/fast_resolver.py`, which passed the registered")
A("equivalence gate against `pipeline.resolve_on_4h` on 6,611 trades first.")
A("Step 3 applied with the registered one-day lag.\n")

A("| ticker | row | n | eps | win% | net_all | ex_best | folds+/cnt | med stop | med cost_r | totR |")
A("|---|---|---|---|---|---|---|---|---|---|---|")
for tk in ["BTC", "ETH", "SOL"]:
    for nm, k in (("STRONG_BUY", "strong_buy"), ("ALWAYS_LONG", "always_long")):
        s = d[tk][k]
        if not s.get("n"):
            A("| %s | %s | **0** | — | — | — | — | — | — | — | — |" % (tk, nm))
            continue
        eb = s.get("ex_best", float("nan"))
        A("| %s | %s | %d | %d | %.1f | %+.3f | %s | %d/%d | %.3f%% | %.3f | %+.1f |"
          % (tk, nm, s["n"], s["episodes"], s["win_pct"], s["net_all"],
             ("—" if eb != eb else "%+.3f" % eb),
             s.get("folds_pos", 0), s.get("folds_counted", 0),
             s["med_stop_pct"], s["med_cost_r"], s["total_R"]))
A("")
for tk in ["BTC", "ETH", "SOL"]:
    p = d[tk]["placebo"]
    a = d[tk]["ind_age_h"]
    pm = "—" if p["mean"] != p["mean"] else "%+.3f" % p["mean"]
    pp = "—" if p["p95"] != p["p95"] else "%+.3f" % p["p95"]
    A("- **%s** episode-matched placebo (300 seeds, %d valid): mean %s, p95 %s. "
      "Indicator staleness %.0f-%.0fh (median %.0fh)."
      % (tk, p["valid"], pm, pp, a["min"], a["max"], a["median"]))
A("")

b = d["BTC"]
sb, al, pl = b["strong_buy"], b["always_long"], b["placebo"]
c1 = sb["net_all"] - al["net_all"]
c2 = sb["win_pct"] - al["win_pct"]
A("### VERDICT: **FAIL** — 1 of 3 registered conditions met\n")
A("| condition | measured | result |")
A("|---|---|---|")
A("| (a) excess over 1h ALWAYS_LONG > 0, net of costs | %+.3f − (%+.3f) = **%+.3f** | **PASS** |"
  % (sb["net_all"], al["net_all"], c1))
A("| (b) target rate >= +15pp over the 1h base rate | %.1f%% − %.1f%% = **%+.1fpp** | **FAIL** |"
  % (sb["win_pct"], al["win_pct"], c2))
A("| (c) net_all above episode-matched placebo p95 | %+.3f vs **%+.3f** | **FAIL** |"
  % (sb["net_all"], pl["p95"]))
A("")
A("**The mechanism does not survive the port, and that is the finding.**")
A("Condition (b) is the one that matters: at 4h the STRONG_BUY tier hit target")
A("**78%** against a ~35% base rate, and that hit-rate lift is what")
A("distinguished the phenomenon from geometry (recorded in Attribution). At 1h")
A("the same construction hits **33.3%** against a 34.1% base — **0.7pp BELOW**")
A("chance, not 15pp above. The excess in (a) is +0.170R and is real, but with")
A("no hit-rate edge behind it, on 45 trades from **4 episodes**, it is not")
A("distinguishable from the placebo: (c) misses by a wide margin, +0.114 against")
A("a p95 of +1.221.\n")
A("**`ex_best` is STILL undefined.** BTC reaches **1** counted fold of 4 (45")
A("trades, but clustered into 4 episodes so they land in one fold); ETH reaches")
A("2. Neither makes the 3 required. ARM A does not answer the measurability")
A("question — that is ARM B's job — but it is worth recording that raising")
A("resolution alone did not fix it here either.\n")
A("**SOL produced ZERO STRONG_BUY trades** across 6.4 years of 1h bars. The 48-bar")
A("confirm requires 48 consecutive hourly STRONG_BUY labels, which SOL never")
A("achieved. Its placebo therefore has no observed run-length distribution to")
A("match and is undefined; no number was invented for it.\n")

A("### The two registered handicaps, measured\n")
A("Both were stated before the run and both are confirmed. Neither is offered")
A("as an excuse — they are recorded because a FAIL under a harder test says")
A("less than a FAIL under an equal one, and the reader is entitled to know")
A("which this was.\n")
A("**1. Cost roughly doubled, as predicted.** Median `cost_r`, 4h -> 1h:\n")
A("| ticker | 4h med stop | 1h med stop | ratio | 4h `cost_r` | 1h `cost_r` | ratio |")
A("|---|---|---|---|---|---|---|")
four = {"BTC": (1.776, 0.045), "ETH": (2.003, 0.040), "SOL": (2.116, 0.038)}
for tk in ["BTC", "ETH", "SOL"]:
    al2 = d[tk]["always_long"]; s4, c4 = four[tk]
    A("| %s | %.3f%% | %.3f%% | %.2fx | %.3f | %.3f | **%.2fx** |"
      % (tk, s4, al2["med_stop_pct"], al2["med_stop_pct"] / s4, c4,
         al2["med_cost_r"], al2["med_cost_r"] / c4))
A("")
A("The stop fraction fell to 0.60-0.92x and `cost_r` rose 1.08-1.66x. The")
A("registration said \"roughly half\" and \"roughly doubles\"; the measured")
A("direction is right and the magnitude is somewhat milder than predicted,")
A("least so on SOL. On the STRONG_BUY rows specifically the stops are tighter")
A("still (BTC 0.796%, ETH 0.698%) and `cost_r` reaches 0.101-0.115.\n")
A("**2. Indicator staleness 0-23h, median 12h**, on every ticker — against ~0h")
A("at the daily incumbent's decision moment. 40% of each 1h score was up to a")
A("day old by construction.\n")
A("**Neither handicap explains condition (b).** A stale indicator and a doubled")
A("cost move `net_all`; they do not move the TARGET RATE, which is a property")
A("of where the exit levels sat relative to subsequent price. 33.3% against a")
A("34.1% base is a statement about the signal, not about costs.\n")

A("### What ARM A does and does not establish\n")
A("- It does **not** establish that the 4h phenomenon is fake. The 4h figure it")
A("  was compared against (+1.819R excess, 78% target) is itself an n=18")
A("  quantity this record classifies as unmeasurable.")
A("- It **does** establish that the construction, ported to 1h under")
A("  time-equivalent parameters, produces no hit-rate advantage on BTC and")
A("  nothing separable from an episode-matched placebo.")
A("- **ETH is the tempting row and carries no pass condition.** 60 trades,")
A("  71.7% target, +1.513R — but 4 episodes, `ex_best` undefined (2 counted")
A("  folds), and ARM A registered BTC as the test. Reporting ETH as a result")
A("  would be selecting the ticker after seeing the numbers. It is recorded,")
A("  not claimed.")
A("- Per the registration, ARM A was **never** a replication test. A pass would")
A("  have been robustness-on-one-ticker; a fail is the same scope.\n")

path = os.path.join(ROOT, "docs", "cleanroom.md")
src = open(path, encoding="utf-8").read()
open(path, "w", encoding="utf-8").write(src.rstrip("\n") + "\n" + "\n".join(L))
print("ARM A result recorded")
