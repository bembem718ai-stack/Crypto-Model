"""Write the EVENT RATE (basket) registration into docs/cleanroom.md.
Runs BEFORE any scoring. Research rule 3."""
import os
import sys
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UNI = os.path.join(ROOT, "research", "basket_universe.txt")

syms = [l.strip() for l in open(UNI, encoding="utf-8")
        if l.strip() and not l.startswith("#")]

QUARTILE_SEED = 20260827
rng = np.random.default_rng(QUARTILE_SEED)
order = rng.permutation(len(syms))
quartiles = [sorted(syms[i] for i in order[k::4]) for k in range(4)]

L = []
A = L.append
A("\n---\n")
A("# PROGRAM: EVENT RATE (basket)\n")
A("Registered BEFORE any of it ran. The previous program (#42-#162) tested")
A("151 pre-registered price-only rules on 3 tickers; none replicated, and")
A("the incumbent's STRONG_BUY tier fired ~4x/year so `ex_best` was never")
A("even defined. This program moves on ONE axis: event rate, by widening")
A("the universe from 3 tickers to 86.\n")

A("## Setup changes (done before registration, recorded here)\n")
A("1. **Python TLS fixed, verification never disabled.** This machine runs a")
A("   TLS-intercepting filter driver whose root is in the Windows store but")
A("   not in `certifi`. `research/tls.py` routes verification through the OS")
A("   trust store. TWO transports needed fixing: `truststore` for Python's")
A("   `ssl` (requests), and `CURL_CA_BUNDLE` for `curl_cffi` (yfinance, which")
A("   was silently returning EMPTY dataframes rather than raising). There is")
A("   no `verify=False` anywhere in the repo.")
A("2. **`data/` re-exported at full depth.** N raised 12,600 -> 20,000 (the")
A("   paginator ceiling) and the daily side from `period=\"5y\"` to `\"max\"`.")
A("   BTC/ETH: 15,177 4h bars, 6.93y (was 5.93y); daily 2,502 rows, 6.85y")
A("   (was 1,762 / 4.82y). SOL: 13,014 bars, 5.94y. MANIFEST now records")
A("   region, REST base, spans and provenance. Committed separately.")
A("3. **Three guards added in `research/`, never in `pipeline.py`** (rule 1):")
A("   `fetch_macro` memoized so ^VIX/DXY are pulled ONCE per run instead of")
A("   once per ticker (172 redundant downloads across 86 tickers); tickers")
A("   with <200 daily rows SKIPPED and REPORTED, never truncated, because")
A("   `add_all_indicators` needs 200 for SMA200; and a per-ticker overlap")
A("   assertion on the `how=\"inner\"` join at `pipeline.py:931`, which")
A("   otherwise truncates to the shorter feed in silence.\n")

A("## !! WINDOW CHANGE — #42-#162 are no longer directly comparable\n")
A("Windows are derived from the daily frame's span, so re-exporting at full")
A("depth MOVED them. BTC/ETH DISCOVERY now cuts at **2023-04-06**, not")
A("2023-09-16. Every result recorded above this line was produced on the old")
A("windows. They are not being re-run and they are not being deleted; they")
A("simply describe a different split and must not be compared line-for-line")
A("against anything below.\n")

A("## Definitions, fixed\n")
A("- **SEALED** = the whole usable span, i.e. everything EXCEPT the last 6")
A("  months. The last 6 months are the lockbox and are never read by any")
A("  research script (rule 2). *(The prompt's wording admitted two readings;")
A("  this is the one taken, because H-basket-C scores ON SEALED and so SEALED")
A("  must be readable. Recorded here so the choice is on the record.)*")
A("- **DISCOVERY / CONFIRMATION** = `harness.make_windows`'s existing time")
A("  split of that usable span (first 55% / remaining 45%).")
A("- **COMMON BASKET WINDOWS.** `harness.make_windows` anchors on each")
A("  frame's OWN first date, which after the refresh already makes SOL's cut")
A("  (2023-09-15) differ from BTC/ETH's (2023-04-06). Across 86 tickers with")
A("  86 listing dates that would give 86 different DISCOVERY/CONFIRMATION")
A("  boundaries and pooling would be incoherent. So the basket uses ONE set")
A("  of windows for every ticker, anchored on **BTC** (deepest feed, market")
A("  reference). A ticker simply contributes no trades before it listed.\n")

A("## Universe\n")
A("Binance.US spot USDT pairs with >=4y of 4h history AND a Yahoo listing")
A("with >=4y (the incumbent's daily frame comes from Yahoo and is inner-")
A("joined), minus 6 excluded as degenerate for a trend/breakout model:")
A("USDC (stablecoin), PAXG (gold), and the fan tokens LAZIO, PORTO, SANTOS,")
A("ALPINE. **Final count: %d.**\n" % len(syms))
A("```")
for i in range(0, len(syms), 8):
    A("  " + " ".join(s[:-4] for s in syms[i:i + 8]))
A("```\n")

A("## H-basket-A (#163) — MEASURABILITY. *This is the headline number.*\n")
A("Run the incumbent **UNCHANGED** -- same thresholds, same `LIVE_GEOMETRY`,")
A("same 2+2bps costs -- on every ticker in the universe. Per ticker report")
A("STRONG_BUY trades, episodes (trades separated by more than the 15-day max")
A("hold), and whether `ex_best` is DEFINED (>=3 folds with >=10 trades).\n")
A("**Reported outcome:** how many of the %d tickers reach a defined" % len(syms))
A("`ex_best`. No pass/fail threshold -- this measures whether the incumbent's")
A("STRONG_BUY tier is assessable at all once event rate is raised. It is a")
A("measurement, not a hypothesis about edge.\n")

A("## H-basket-B (#164) — EDGE\n")
A("Pool every ticker's STRONG_BUY trades into ONE series, on DISCOVERY and")
A("on CONFIRMATION separately. Report n, episodes, win%, `net_all`,")
A("`ex_best` (folds cut by TIME, pooled across tickers), `total_R`,")
A("`maxDD_R`. Count-matched placebo, **300 seeds**, drawing from the same")
A("ticker mix and the same dates-per-ticker eligibility as the observed set.\n")
A("**REGISTERED PASS DIRECTION:** `ex_best` > 0 on BOTH windows AND `net_all`")
A("above the placebo **p95** on BOTH windows. Anything less is a FAIL,")
A("including \"almost\". Repeated identically for **INC_BUY_ALL** pooled.\n")

A("## H-basket-C (#165) — REPLICATION\n")
A("The universe is split into 4 random ticker quartiles with a fixed seed,")
A("**registered here before any scoring**. Report pooled STRONG_BUY")
A("`net_all` and `ex_best` per quartile on SEALED.\n")
A("**REGISTERED PASS DIRECTION:** positive in ALL FOUR quartiles. This")
A("replaces \"all three tickers\" as this project's replication test -- four")
A("disjoint ticker sets is a stronger claim than three correlated majors.\n")
A("Seed = `%d`, `numpy.random.default_rng(seed).permutation(n)`, " % QUARTILE_SEED)
A("assigned round-robin `order[k::4]`.\n")
for k, q in enumerate(quartiles, 1):
    A("- **Q%d** (%d): %s" % (k, len(q), " ".join(s[:-4] for s in q)))
A("")

A("## H-tier-curve (#166) — DESCRIPTIVE ONLY, SELECTS NOTHING\n")
A("Pooled n, win%, `net_all`, `ex_best` at `combined_final_score` >= 75, 70,")
A("65, 60 on DISCOVERY. **A curve to look at.** No threshold may be chosen")
A("from it, no rule may be promoted on it, and any future hypothesis that")
A("uses a score cut must be registered separately with its own number and")
A("tested on data this curve did not touch. Recorded so that a later")
A("\"we always knew 65 was the level\" is checkable against what was")
A("actually seen and when.\n")

A("## Operating rules for this program\n")
A("Per-ticker daily bars and the 4h ATR are built ONCE per ticker and reused")
A("(rule 8). No placebo anywhere except H-basket-B. Every result, including")
A("every failure and every skipped ticker, is recorded here. Research")
A("commits stay separate from signal-check commits (rule 6).\n")

path = os.path.join(ROOT, "docs", "cleanroom.md")
src = open(path, encoding="utf-8").read()
open(path, "w", encoding="utf-8").write(src.rstrip("\n") + "\n" + "\n".join(L))
print("registered EVENT RATE program: #163-#166, universe %d, seed %d"
      % (len(syms), QUARTILE_SEED))
for k, q in enumerate(quartiles, 1):
    print("  Q%d: %d tickers" % (k, len(q)))
