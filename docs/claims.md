# Claims — what this project can and cannot say

Every statement below is traceable to `docs/cleanroom.md`, `signal_outcomes.csv`,
`signal_log.csv`, or a named commit. Nothing here is an estimate, a projection
of future performance, or a rounded-up version of a real number.

Written 2026-08-28. Sources: cleanroom #42–#167, `signal_outcomes.csv`
(19 closed episodes), `signal_log.csv` (1,771 rows, 2026-07-22 → 2026-08-28),
`CLAUDE.md` Known open issues.

### Provenance note — the numbered record is incomplete, and understates itself

**The tested count in this document is a floor, not a total.** `docs/cleanroom.md`
begins at **#42**. An earlier body of work — roughly **#1–#31** — predates the
cleanroom. Those hypotheses exist as registrations in `pipeline.py` code
comments, and their ledger, `docs/findings.md`, sits on an offline machine and
has never been committed. Until it is retrieved, **the total number of
pre-registered tests this project has run is understated by about 31.**

Two caveats on that, both recorded rather than resolved:

- **It cannot be verified from this repository.** `docs/findings.md` is absent
  here, and a search of `pipeline.py` for hypothesis-style registrations
  returned nothing in the form the cleanroom uses. The account above is the
  maintainer's, carried here as an attestation, not as something this repo
  demonstrates.
- **The numbering does not reconcile yet.** The cleanroom reserves **#1–#41**
  ("for the pre-existing findings already recorded in the code and in
  `CLAUDE.md`"), while the earlier work is described as **#1–#31** — a gap of
  ten numbers that are either unused or unaccounted for. Which it is should be
  settled when the ledger is retrieved.

**This cuts one way only.** Recovering those 31 would make the search *larger*
and the "zero cross-ticker survivors" record *stronger*, not weaker — the four
pre-existing findings the cleanroom names (ML replication failure, 4-year
degradation, VIX regime candidate, short-side viability) are all negative or
unproven. No claim in this document depends on them, and none should be made
from them until the ledger is in the repo and its numbers can be read.

**The one-line summary: this is a research project with a documented record of
mostly negative findings and a small, currently losing live record. It is not a
product with a win rate.**

**As of 2026-08-28 this record holds ZERO supported edge claims.** The last one
standing — BTC INC_BUY_ALL — was withdrawn by #171 when it reversed sign on the
refreshed dataset. Everything remaining under SUPPORTED is about engineering,
process, or measured absence of edge.

### Standing rule: SUPPORTED entries are dated to their dataset freeze

Every claim in SUPPORTED is a statement about a **specific frozen dataset**, not
a timeless fact, and each carries the freeze it was computed on. Consequently:

**Any refresh of `data/` re-opens every SUPPORTED entry derived from it.** A
claim must be re-validated on the new freeze before it may continue to be
quoted, and until it is, it is quotable only with its original freeze named.

This is not bureaucracy. Windows here are anchored on the dataset's span, so
extending the data MOVES the DISCOVERY/CONFIRMATION boundary — a refresh is not
"more of the same data", it is a different experiment. #171 is the worked
example: a 100th-percentile result became negative for exactly this reason, and
nothing about the original computation was wrong.

---

## 1. SUPPORTED

Statements the record backs, with the numbers and where they come from.

### Production engineering

**Exit levels are computed correctly at every price scale.** As of commit
`385f1c4`. Before it, `compute_exit_levels` rounded entry/target/stop to a
fixed 2 decimals, so any asset whose `1.5 × ATR` distance fell under half a
cent had all three levels collapse onto the same number — producing a zero stop
distance, NaN P&L, and a manufactured 100% win rate on the first bar. Measured
contamination: **185 of 645 STRONG_BUY trades (28.7%) across 35 of 82 tickers**.
After the fix: **0 NaN trades of 645**, 0 rows above the 2.667R theoretical
maximum, and BTC/ETH bit-identical before and after (19 trades / 73.7% /
+1.653R and 9 / 44.4% / +0.587R unchanged). 8 new tests, 6 of which failed
against the old code.
*Source: cleanroom "Exit-level rounding defect — FIXED".*

**BTC, ETH and SOL were never affected by that defect.** Their levels are
hundreds of dollars apart. Every number previously reported for those three
stands.
*Source: same section — "tickers unchanged: 8, including BTC and ETH bit-identical".*

**The sentiment gate is live again.** Run
[33140451699](https://github.com/bembem718ai-stack/Crypto-Model/actions/runs/33140451699),
2026-08-28 03:59 UTC: `mentions=12675 sentiment_score=-0.006 bullish_pct=20
bearish_pct=21 buzz_score=79.8`, first attempt, no retries. It had returned
`gate_decision=ERROR` for **1,351 consecutive log rows over 24.4 days**
(last good reading 2026-08-03 19:01 UTC). The first ~1.2 days were HTTP 429
quota exhaustion; the remaining ~23 days were an `InvalidHeader` raised
client-side because the API key carried a trailing newline — the request never
reached the API, which is why there was no HTTP status to diagnose. Fixed by
`.strip()` in `get_api_key_from_env()` (`71927d2`).
*Source: `signal_log.csv`, run logs, cleanroom is silent on this (production, not research).*

**Every workflow run reported success throughout that outage.** The gate
errors, falls back to a neutral 1.0 multiplier, and the pipeline continues by
design — a dead sentiment provider must not take the signal service down. The
consequence is that **Step 2 contributed nothing to any score between
2026-08-03 and 2026-08-28**, and `gated_score == initial_score` on all 1,351
of those rows.
*Source: `signal_log.csv`.*

**Signal checks run under two independent triggers with a de-duplication
guard.** GitHub native cron plus cron-job.org `workflow_dispatch` (`803f457`).
Before the guard, both fired: measured over 100 runs on 2026-08-27, **52
`schedule` + 48 `workflow_dispatch`**, median gap 0.50h instead of the intended
1h. The guard reads the newest `signal_log.csv` timestamp and stands down under
50 minutes; verified live in run 33140451699 — `[guard]
trigger=workflow_dispatch should_run=true: newest entry is 273.7 min old
(>= 50) — proceeding`. It fails open (missing/empty/unparseable log all
proceed) and always exits 0.

**Adanos quota is inside the free tier.** The call is skipped below the derived
cutoff of 33.3 (below it the dampen-only gate provably cannot change the label)
and a 12h per-symbol TTL bounds the rest. Replayed against the real 1,769-row
log normalised to hourly cadence: **~31 requests/month per ticker, ~92 for
three**, against a 200/month tier. Ceiling if every hour qualified: 62 and 186.
*Source: replay in `71927d2`'s commit message; `CLAUDE.md` Known open issues.*

**`audit.py --offline` currently reports 0 checks FAILED.** Both deployment
checks that were failing now pass: log freshness (measured against
`origin/main`, not the local clone) and "Sentiment gate not erroring".

### Research findings

**The trade geometry is not free money.** On DISCOVERY, buying every single day
and applying the production geometry loses money on all three tickers:
**BTC −0.148R, ETH −0.159R, SOL −0.078R** per trade. Over the longer
DISCOVERY+CONFIRMATION span it is marginally positive (+0.016 / +0.031 /
+0.024) on a ~35% target rate. Either way, the 2:1 payoff structure by itself
does not produce an edge — any claimed edge has to beat that baseline.
*Source: cleanroom corrected DISCOVERY table; Attribution "The headline".*

**Liquidity, not signal, dominates the wide-universe result.** The #167
tradability filter (flat 4h bars ≤ 10% AND median 1.5×ATR stop ≥ 0.5% of
entry — both defined on prices alone, neither looking at any outcome) passes
**26 of 82** tickers. All 56 exclusions fail on the flat-bar criterion. Same
window, same tier, same machinery: **+0.815R on the tradable 26 vs −2.016R on
all 82**, the difference being 431 extra trades on pairs whose ATR-derived stop
is a fraction of a percent, where `cost_r = 8bps / stop_fraction` dominates.
Across the 79 tickers that traded, median flat-bar share is 28.5% (worst
79.1%); 20 tickers exceed 50%.
*Source: cleanroom #167 and H-basket-B results.*

**A large pre-registered search found nothing that replicates across tickers.**
**126 numbered hypotheses (#42–#167)**, of which #42–#161 are 120 individual
rules each scored on 3 tickers — **360 rule×ticker scorings** — every one
registered in writing before it ran, every result recorded pass or fail.
Survivors that replicate across tickers: **zero**. The closest was
`rsi7_cross50+none`, which cleared both CONFIRMATION conditions on BTC (net
+0.598 vs p95 +0.540) and SOL (+0.539 vs +0.394) and failed ETH outright
(net −0.021, `ex_best` −0.193, 20th percentile). Under the pre-registered rule
that is a failure, and it was recorded as one.
*Source: cleanroom #42–#161 registration table, #162 verdicts, #163–#167 results.*

**The rules that were tested are genuinely new signals, not relabelled
incumbent days.** Jaccard similarity of signal days against the incumbent's
BUY/STRONG_BUY days is **0.007–0.074** across the top three rules and all three
tickers. The search explored new territory; it just found nothing there.
*Source: cleanroom Attribution "Overlap with the incumbent".*

**WITHDRAWN 2026-08-28 — moved to NOT SUPPORTED by #171.** This section
previously claimed the incumbent's all-BUY tier was positive on BTC. It did
not survive the dataset being extended. See "BTC INC_BUY_ALL is positive"
under NOT SUPPORTED.

**Negative findings are recorded with the same detail as positive ones.** Every
failure above is written into `docs/cleanroom.md` with its numbers, including
the near-misses that were most tempting to keep (`rsi7_cross50+none` at 2 of 3
tickers; `INC_BUY_ALL` on CONFIRMATION missing the placebo p95 by 0.001R).

---

### Construction change — 2026-09-01

> **The published construction was simplified on 2026-09-01 on ablation
> grounds: Step 3 (the indicator blend) and the VIX extreme-fear regime were
> removed. NO PERFORMANCE CLAIM IS MADE.** Both constructions remain publicly
> logged (`shadow_log.csv`, arms 1 and 2); adjudication is SHADOW-EVAL's at 30
> pooled closed episodes and nowhere else.

Grounds are #198 (Step 3 measured harmful) and #201 (the VIX regime measured
inert on the long side). **Neither is evidence that what remains works** —
#203 took squeeze-only to a registered bar and FAILED. This is a
simplification of a construction with no supported edge claim either way.

**No SUPPORTED entry was added, edited or removed by this change, and the
project still holds ZERO supported edge claims.**

## 2. NOT SUPPORTED

Claims the project has been tempted to make that the record does not back. For
each: why not, and exactly what would have to become true.

### "72–74% win rate"

**Why not.** The number is real but it describes 19 BTC trades, and BTC's
STRONG_BUY row reads 73.7% because 14 of 19 hit target. Those 19 trades are
**2 independent episodes** resolving on **4 distinct exit bars** — consecutive
signal days riding the same price move, several exiting on the same 4h bar. On
the other two tickers the same tier gives **44.4% on 9 trades (ETH)** and
**100% on 1 trade (SOL)**. `ex_best` — the project's own concentration test —
is **undefined on all three**, because no ticker reaches 3 folds carrying 10
trades. A win rate computed over 2 independent events is not a win rate.

**What would move it.** `ex_best` defined and positive for the STRONG_BUY tier
on **≥3 tickers**, which requires **≥30 trades per ticker spread so that ≥3 of
4 folds each carry ≥10** — against the current 19/9/1. At the observed rate of
~4 STRONG_BUY trades per ticker per year, that is roughly **7–8 more years per
ticker**, or a design change that fires the tier more often. The win rate quoted
would then have to be the pooled figure across those tickers, not BTC's.

### "STRONG_BUY is a validated edge"

**Why not.** It is genuinely *not* explained away by drift or geometry — the
excess over an always-long baseline is **+1.819R (BTC), +0.781R (ETH),
+2.675R (SOL)**, and it hits target 78% of the time on BTC against a ~35% base
rate. That is the strongest-looking signal in the whole record. But n = **18,
8 and 1** over five and a half years; ETH takes **92% of its R from one fold**;
SOL's entire history is a single trade. It also failed its own pre-registered
CONFIRMATION test (#162): 0 counted folds on all three tickers, and **0 trades
on SOL in 2.4 years** because two consecutive STRONG_BUY days never occurred.
Widening to 82 tickers did not help — **0 of 82 reach a defined `ex_best`**.
The honest verdict recorded in the cleanroom is *"too rare to attribute"*,
which is neither a pass nor a fail.

**Live evidence points the other way.** Exactly **one** live episode has ever
reached STRONG_BUY at its peak (2026-08-06, BTC, entry score 62.99). It
**stopped out at −1.0R**.

**The 1h version of it now has a MEASURED negative (#170).** This is new, and
it is the first time any version of the STRONG_BUY construction has been
refuted rather than merely left unmeasured. Ported to 1h bars keeping every
parameter's bar count (ARM B), the construction produced enough trades for
`ex_best` to be computable for the first time in the project's history — and
the answer was no, on **all four registered conditions, on both windows**:

| window | n (BTC/ETH/SOL) | **episodes** | `ex_best` > 0 on ≥2 of 3 | pooled net vs placebo p95 |
|---|---|---|---|---|
| DISCOVERY | 253 / 184 / 109 | **25 / 25 / 21** | **0 of 3** | +0.055 vs +0.231 |
| CONFIRMATION | 737 / 553 / 401 | **57 / 48 / 35** | **1 of 3** (SOL +0.079) | −0.069 vs +0.145 |

`ex_best` is defined in 5 of 6 ticker-window cells and **negative in 5 of
them**. Both windows agree and neither is close.

The time-equivalent port (ARM A, #168) failed separately: BTC hit target
**33.3% against a 34.1% base rate** — below chance, where the 4h tier ran 78%
against ~35%. The hit-rate mechanism did not survive the change of resolution.

**What this does NOT settle.** #170 refutes the *bar-equivalent 1h
construction*, which runs on a 4x shorter timescale and is a different strategy
sharing a parameter table. #168 tested a *rescaled* construction and was
registered as robustness on one ticker, never as replication. **Neither
adjudicates the original 4h tier**, whose n=18 excess remains exactly where it
was: unmeasurable, neither confirmed nor refuted.

**What would move the 4h claim** is unchanged: `ex_best > 0` on **≥3 tickers**
with **≥30 trades each**, AND pooled `net_all` above the episode-matched
placebo p95 on **both** DISCOVERY and CONFIRMATION. At ~4 STRONG_BUY trades per
ticker per year that is roughly **7–8 more years per ticker**, or a design
change that fires the tier more often. The pooled tradable-26 run (#164)
cleared exactly that bar on CONFIRMATION (+0.815R vs p95 +0.332, `ex_best`
+0.424, 4/4 folds) and failed DISCOVERY (`ex_best` undefined, +0.239 vs p95
+0.570) — so **one window of two has been reached once; the other has not.**

### "The score measures conviction"

**Why not.** If the score were a conviction ladder, expectancy would rise with
it. It does not. On DISCOVERY, tradable subset, geometry held constant:

| score ≥ | n | win% | net_all | ex_best |
|---|---|---|---|---|
| 75 | 46 | 34.8 | +0.239 | undefined |
| 70 | 256 | 29.3 | **+0.044** | **−0.060** |
| 65 | 908 | 30.0 | +0.070 | +0.016 |
| 60 | 1,782 | 29.7 | +0.068 | +0.029 |

**≥70 is the worst row of the four.** The top tier has the best net but only 46
trades and no computable `ex_best`. Loosening from 65 to 60 doubles the trade
count and moves expectancy by 0.002R. This curve is registered as **descriptive
only (#166)** and no threshold may be selected from it.

**What would move it.** A monotonic relationship between score band and
`ex_best` — each band's `ex_best` defined (≥30 trades, ≥3 counted folds) and
strictly increasing with the band — demonstrated on data this curve did not
touch, registered as a new numbered hypothesis before it runs.

### Anything implying ETH or SOL replication

**Why not.** Every cross-ticker test to date has failed on ETH or SOL:

- `INC_BUY_ALL`: BTC 100.0th percentile, **ETH 47.7th, SOL 21.0th**.
- `rsi7_cross50+none` (#162): passed BTC and SOL, **failed ETH** at the 20th
  percentile with `ex_best` −0.193.
- `INC_STRONG_BUY` (#162): **SOL produced 0 trades** over 2.4 years.
- H-basket-C (#165): **Q3 negative (−0.250R)**, and `ex_best` undefined in 3 of
  4 quartiles. 3 of 4 is not 4 of 4.
- Attribution: the three best rules disagree on regime across tickers —
  `donchian10+none` is best in low vol on BTC/ETH and best in high vol on SOL.

**What would move it.** The same statistic, same sign, with `ex_best > 0` and
**n ≥ 30 per ticker**, on **BTC and ETH and SOL** simultaneously, pre-registered.
No result to date has achieved this on two tickers, let alone three.

### "BTC INC_BUY_ALL is positive" — WITHDRAWN from SUPPORTED, 2026-08-28

**Why not.** This was the strongest surviving claim in this document until
#171 re-derived it on the refreshed dataset. It reversed sign.

| | DISCOVERY window | n | episodes | net_all | vs placebo |
|---|---|---|---|---|---|
| **old split** (pre-refresh) | 2021-10-24 → 2023-09-16 | 58 | 13 | **+0.237R** | **100.0th pctile**, p95 +0.013 |
| **refreshed** (#171) | 2019-09-24 → 2023-04-06 | 93 | 30 | **−0.167R** | below p95 **+0.247** |

**Nothing broke, and neither number is wrong.** Each is correct for the data
it was computed on. The full-depth re-export (`acf2f59`) added a year of
history, which moved DISCOVERY's cut from 2023-09-16 to 2023-04-06 and grew
the sample from 58 trades to 93. Different window, different years, different
answer.

**The claim was window-dependent, and the original measurement disclosed
nothing about that.** "+0.237R at the 100th percentile" reads as robust. It
was one dataset refresh away from negative. That is the whole lesson.

CONFIRMATION is the only window where `ex_best` is positive (+0.097 on 108
trades / 23 episodes) and it still fails the placebo bar (+0.195 vs p95
+0.330). The tier is not rescued by the other window.

**What would move it back.** `ex_best` > 0 AND `net_all` above the
episode-matched placebo p95 on **both** windows of whatever dataset is current
at the time — the same bar #171 set. And per the dating rule below, any such
result carries the freeze it was computed on.

*Source: cleanroom #171.*

### "The extreme-fear (VIX) regime protects the long side"

**Why not.** Not because it was tested and failed. Because on the long side
it has never been exercised, and #201 measured that as an exact zero.

Removing the regime entirely — `extreme_fear_mode` disabled, bars held at
60/40 — changed BTC INC_BUY_ALL's expectancy by **+0.000R on both windows**,
identically zero at all 50 rolling window starts in each. That is not a
small effect. It is the absence of any effect at all, across 6.42 years.

**The component is not dormant, which is what makes this worth stating.**

| | DISCOVERY (3.53y) | CONFIRMATION (2.89y) |
|---|---|---|
| days with VIX ≥ 35 | 80 (6.3%) | 10 (0.9%) |
| labels the raised bars changed | 29 | 6 |
| **BUY-tier membership changed** | **1** | **0** |
| trades that produced | **0** (unconfirmed) | 0 |
| median composite score on those days | 36.9 | 22.5 |
| days in [60, 70) — the only band the raised buy bar can bind in | **1** | **0** |

The regime fires often and rewrites 35 labels. Every one of them except a
single day is on the SELL side, which INC_BUY_ALL never trades. The one
exception — 2020-06-21, composite 62.2, VIX 35.1 — is unconfirmed under
`confirm_days=2` and produced no trade.

**The mechanism is structural, not a small sample.** The extreme-fear rule
raises the buy bar from 60 to 70, so it can only change a long decision on a
day whose composite score lands in [60, 70). But the composite score is *low*
precisely when equity volatility is extreme — median 36.9 and 22.5 against a
bar of 70. The band the rule acts in and the scores the model produces in a
panic barely overlap. One day in seven years.

**So the honest status is UNMEASURED, not validated and not refuted.** No
claim may be made in either direction: not "it protects the long side" (never
demonstrated) and not "it does nothing" (never given the chance). The
`classify_direction` docstring's reasoning — that a panic should demand more
conviction to buy — remains a design argument, and it has never been put to a
test this data could answer.

**What would make it measurable.** A regime where BTC scores above 60 while
equity volatility is extreme. That combination has not occurred in this
dataset. Until it does, any statement about the buy-side extreme-fear bars is
an argument about design, and must be worded as one.

*Source: cleanroom #201 (ABLATION), 2026-08-30.*

### Also not supported

- **"Backtested and profitable."** The pre-registered searches failed. The only
  positive pooled result (tradable-26 STRONG_BUY on CONFIRMATION) failed its own
  two-window test.
- **"The sentiment gate improves signals."** It has never once changed a score.
  `gate_multiplier` is 1.0 on every row of the log, and the gate was returning
  ERROR for 1,351 consecutive rows. It is instrumented, not validated.
- **"The ML model adds accuracy."** Display-only by decision; failed
  cross-ticker replication at BTC AUC ~0.596 / ETH ~0.514. `ml_weight` is 0.
- **"Short signals work."** Suppressed in live mode. The live record below
  shows why: **0 wins in 11 short episodes.**

---

## 3. LIVE RECORD

From `signal_outcomes.csv`, resolved against 4h bars with the same rules as the
backtest. **19 episodes, all closed, none open.** Entries span
2026-07-23 → 2026-08-18.

### Everything logged

| | value |
|---|---|
| closed episodes | **19** |
| wins (target) / losses (stop) | **3 / 16** |
| win rate | **15.8%** |
| net R | **−10.00R** (mean −0.526R per episode) |
| longest losing streak | **8** |
| BTC | **18 of 19** (1 ETH) |

### Split by side — this matters

11 of the 19 are SHORT episodes. The live path runs `--long-only`, so those were
**logged but never published as signals**. Both numbers are given because only
one of them describes what a follower would have traded.

| | n | wins | losses | win% | net R | worst streak |
|---|---|---|---|---|---|---|
| **LONG (published)** | **8** | 3 | 5 | **37.5%** | **+1.00R** | 3 |
| SHORT (logged, not published) | 11 | 0 | 11 | 0.0% | −11.00R | 11 |
| ALL | 19 | 3 | 16 | 15.8% | −10.00R | 8 |

> **DISCLOSURE — the SHORT row spans two constructions from 2026-09-01.**
> The short trend filter (SELL downgraded to WATCH when price is above its
> 50-day SMA) lived in Step 3. With Step 3 removed from the published path it
> no longer fires, so short rows logged from 2026-09-01 are produced by a
> **different construction** from the one that produced the 0-for-11 above.
>
> No published signal changes — shorts are never published (`--long-only`).
> But this table quotes the logged short record, so from that date the SHORT
> row **mixes two constructions** and the ALL row inherits the mix. The LONG
> row is unaffected: the filter only ever touched SELL/STRONG_SELL.
>
> Recorded here as a **known cost of the simplification, decided in advance**,
> not as something discovered later. Any future citation of the short record
> must state which side of 2026-09-01 it is drawn from.

### Which number is *your* number

**A follower's experience matches the LONG row: 8 episodes, 3 winners, 5
losers, +1.00R.** That is the only line in this table describing signals the
system actually published. Short signals are suppressed on the live path
(`--long-only`), so nobody was ever told to take one; the 11 short episodes
were recorded by the outcome tracker because it reads every direction in the
log, not because they were issued.

**So why show the full log at all?** Three reasons, and none of them is
padding:

1. **The suppression is a decision, and decisions should be auditable.** The
   0-for-11 short record is the evidence that switching shorts off was right.
   Deleting it would delete the justification.
2. **It is the honest denominator for "how often is the model wrong".** The
   model formed a directional opinion 19 times and 16 of those resolved
   against it. A reader who only sees the long row learns that the published
   subset went 3–5; they do not learn that the unpublished subset went 0–11.
3. **Publishing only the filtered row is how selective reporting starts.** The
   filter here is defensible and pre-existing. It would stop being defensible
   the moment the filter were chosen *because* it improved the number.

**The published long record is 8 episodes and +1.00R.** Three winners at +2.0R
each, five losers at −1.0R each. Entry scores ranged 60.11–62.99 — all just
above the 60 bar. One episode peaked at STRONG_BUY and stopped out.

**This sample is far too small to mean anything.** Eight episodes over four
weeks, on essentially one ticker, is not evidence of an edge in either
direction. The short record (0 for 11) is the more striking number and is
consistent with the short-side suppression already in force.

**Cross-check:** of 1,771 log rows, direction was WATCH 1,173 times, BUY 491,
SELL 99, STRONG_BUY 8. The last 200 rows are all WATCH, with final scores
31.1–49.5 — the system has been quiet, not signalling.

---

## 4. WORDING

Draft text using only SUPPORTED statements.

### (a) Discord service description

> **Crypto-Model — a public research log, not a signal service**
>
> This is an open research project on whether a Bollinger-squeeze + technical
> indicator model can find a tradeable edge in crypto. Everything it has tested
> is written down before it runs and reported afterwards whether it worked or
> not. The repo is public.
>
> **What has actually been found so far: nothing that replicates.** 126
> pre-registered hypotheses, 360 rule-by-ticker scorings across BTC, ETH and
> SOL. Zero survivors that hold up on more than one ticker. The closest
> candidate passed on BTC and SOL and failed on ETH, and was recorded as a
> failure because that is what the pre-registered rule says.
>
> **The live record is 8 published long episodes: 3 winners, 5 losers, +1.00R
> net.** That is four weeks of data on one ticker and it proves nothing yet. A
> further 11 short episodes were logged and not published; they went 0 for 11,
> which is why shorts are switched off.
>
> **What you get here:** every signal the model publishes, the exit levels it
> computed, and the resolved outcome of each one added to a public tally that
> includes the losses. Plus the research log, including the failures.
>
> **What this is not:** a win rate, a profit claim, or financial advice. If a
> number in this project ever looks impressive, check how many independent
> trades it came from — usually the answer is "not enough".

### (b) Signal post template — BUY

```
BTC — BUY
Score 61.3 / 100   (bar is 60)
Entry 78,420   Target 80,910   Stop 77,175
Risk:reward 2.0 : 1   |   ATR-derived, 15-day max hold

This is a research signal, published as-is and tracked publicly.
Live record to date: 8 closed long episodes, 3 target / 5 stop, +1.00R net.
That is not enough trades to establish an edge, in either direction.
No claim is made that this trade will work.
Outcome will be added to the public tally either way.
```

### (c) Signal post template — STRONG_BUY

```
BTC — STRONG_BUY
Score 63.0 / 100   (bar is 60)
Entry 78,420   Target 81,740   Stop 77,175
Risk:reward 2.667 : 1   |   wider target, same stop, 15-day max hold

STRONG_BUY is the model's rarest tier and it is NOT a validated edge.
Read this before treating it as a stronger signal:
  - It has fired 8 times in the entire live log.
  - Exactly one live episode has ever peaked at STRONG_BUY. It stopped out
    at -1.0R.
  - In backtest it looks strong (78% target rate on BTC against a ~35%
    baseline) but that is 18 trades from 2 independent episodes, and the
    project's own concentration test cannot be computed on it at all.
  - Across 82 tickers, zero reach enough trades to measure this tier.

The wider target is a geometry choice, not a confidence measurement.
Outcome will be added to the public tally either way.
```

---

## Standing rule for anything published

Before any number goes out, it must answer three questions:

1. **How many trades, and how many *independent* episodes?** 19 trades from 2
   episodes is 2 observations.
2. **Is `ex_best` defined, and is it positive?** If it cannot be computed, the
   honest word is "unmeasured", not "strong".
3. **Does it hold on BTC *and* ETH *and* SOL?** One ticker is a hypothesis.

If any answer is missing, the claim does not ship.
