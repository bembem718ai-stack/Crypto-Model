# Crypto-Model — project context

A cryptocurrency trading signal pipeline. Personal/extracurricular project.
Repo is PUBLIC: `bembem718ai-stack/Crypto-Model`.

## Run these commands, don't guess

```powershell
$py = "C:\Users\gubby\AppData\Local\Programs\Python\Python312\python.exe"
$env:BINANCE_REGION="US"          # REQUIRED — see "Binance" below

& $py -m pytest test_signals.py -q        # 545 passed + 1 skipped, must stay green
& $py audit.py --offline                  # structural health, seconds, no network
& $py audit.py BTC ETH SOL --years 4      # full audit, 10-40 min
& $py pipeline.py run BTC                 # live signal — COSTS 1 ADANOS REQUEST
& $py pipeline.py backtest BTC --exits --sizing
& $py pipeline.py robustness BTC ETH SOL --years 4
& $py pipeline.py walkforward BTC ETH SOL --years 4   # fixed config, K folds, lockboxed
& $py live_tools.py outcomes --compare    # score the LIVE system, 0 Adanos
& $py live_tools.py graph BTC             # opens the chart locally
```

## Architecture

Four core files plus the audit, and two directories that support research:

- `signal_engines.py` — Binance klines + Bollinger squeeze detection, Reddit
  sentiment via Adanos, Yahoo Finance technical/macro indicators, ATR exit
  levels, the ML engine.
- `pipeline.py` — step orchestration in ENFORCED order, direction
  classification, backtests, position sizing, robustness validation.
  **THE PUBLISHED CONSTRUCTION IS SQUEEZE-ONLY as of 2026-09-01**: Step 3
  (the indicator blend) and the VIX extreme-fear regime were removed on
  ablation grounds (#198 harmful, #201 inert). `PUBLISHED_*` and
  `INCUMBENT_*` name both constructions; the published path SKIPS Step 3,
  which is what drops the Yahoo dependency. **NO PERFORMANCE CLAIM IS
  MADE** — adjudication is SHADOW-EVAL's at 30 pooled closed episodes.
  Step 3 remains in the codebase and `shadow_basket.py` still calls it
  every day, which is the precondition that keeps the change reversible.
- `live_tools.py` — confluence monitor, three-tab browser chart, local HTTP
  server, GitHub Actions check mode.
- `test_signals.py` — 612 tests covering all decision logic.
- `audit.py` — full-model health check; every known issue re-measured.
- `research/premia.py` — **#257 THE PREMIA INSTRUMENT.** Descriptive, in
  the #249 style: no hypotheses, no verdicts. Measures crypto variance
  risk premium (currently **NOT COMPUTABLE** — the options archive is one
  day old), annualised perp carry (Binance primary, Kraken/OKX beside),
  and Kraken dated-futures basis from the ~05:20 UTC snapshot. Appends a
  dated table to `docs/premia.md`. **These are risk premia — payment for
  bearing crash and balance-sheet risk — NOT alpha, NOT signals, and NOT
  tradeable by this operator.** Every number carries an interval or is
  labelled a RAW SAMPLE; `--dry-run` enforces that and is wired into the
  weekly audit.
- `data/` — the frozen offline dataset: ~5y of Binance.US 4h bars plus the
  incumbent's daily frame per ticker (BTC/ETH/SOL), with `MANIFEST.json`
  recording bar counts, last bar, and the direction mix. Written by
  `export_data.py` (`BINANCE_REGION=US`). Research reads these files
  instead of the network, so a result can be re-run bit-for-bit later.
- `data/derivatives/` — positioning and funding history collected daily by
  `research/collect_derivs.py` (`derivs-collect.yml`). SIX sources: Kraken
  funding, **Kraken tickers** (OI / mark / index / predicted funding, all
  ~294 instruments in one call), OKX funding, OKX daily OI, **OKX rubik**
  (long-short ratio, taker volume, OI-volume), and **Deribit options**
  (BTC/ETH chain aggregate + BTC/ETH/SOL realised-vol series). Every run
  re-pulls the FULL available window and MERGES on `(symbol, timestamp)` —
  idempotent, existing rows win, revisions counted. Plus
  `binance_funding.csv` from `collect_binance_vision.py` (static archive).
  DATA ONLY: no hypothesis, nothing scored.

  **`collect_derivs.SOURCE_WINDOWS` states, per source, the window and what
  a missed day COSTS**, and `audit.py` quotes it in staleness failures so an
  outage is priced rather than guessed at. Two sources are **CURRENT-ONLY**
  — `kraken_tickers` and the Deribit chain — meaning a day not sampled is
  simply gone, with no window to recover it from. Those rows are point
  SNAPSHOTS at workflow time and are **never a daily mean**.
- `shadow_log.csv` / `shadow_outcomes.csv` — the SHADOW basket: the
  incumbent scored hourly across the #167 tradable-26, logged and NEVER
  published. Separate file, no alerts, no charts, zero Adanos (ungated —
  the gate is dampen-only, so shadow BUY days are a strict SUPERSET of
  gated ones). Written by `shadow_basket.py`; evaluation is pre-registered
  as SHADOW-EVAL and may not be looked at before 30 pooled episodes.
- `research/` — all research and experiment code. Nothing here is imported
  by the live path. See "Research rules".

Pipeline output: final score 0–100, direction (STRONG_BUY…STRONG_SELL),
ATR exit levels (3.0x target / 1.5x stop), and a position size multiplier
from fractional Kelly on backtested outcomes.

## Hard constraints — do not violate these

**Adanos quota is the binding limit.** Free tier is ~200 requests/month.
`pipeline.py run` spends one. Backtests, robustness, and audit spend ZERO
(they use the neutral-sentiment assumption). Never add a sentiment call to
a backtest path. If a change would increase live request frequency, say so
explicitly before making it.

**Binance region.** Global Binance returns HTTP 451 from US IPs and from
Azure-hosted GitHub runners. Everything routes through Binance.US via
`BINANCE_REGION=US`. If klines fail, check this first.

**Never commit secrets.** The repo is public. The Adanos key lives in an
environment variable and in GitHub Secrets, never in source. `audit.py`
checks for this.

**The lockbox is sealed.** The most recent 6 months are holdout: `mlsweep`
and `walkforward` exclude them by default. Never pass `--unlock-lockbox`
without being told to — a config chosen by looking at lockbox data can
never be re-validated on it.

**Backtest numbers now come in gross and net.** `expectancy_r` is
unchanged for comparability with everything previously reported;
`expectancy_r_net` subtracts fees+slippage (default 30bps round trip)
and is the honest number. Verdicts use net.

**ML is display-only.** The XGBoost engine failed cross-ticker replication
(BTC AUC ~0.596, ETH ~0.514). `ml_weight` defaults to 0 and must stay
there. `ml_confidence` may be displayed but must never touch `final_score`
or the direction label. Do not re-promote it without replication on 3+
tickers, and do not sweep configurations until one passes — that's
curve-fitting.

## How decisions get made here

This project's standard is evidence before defaults. Specifically:

1. **Show real test output before changing a default or threshold.** Not a
   prediction of what the numbers will be — the actual numbers.
2. **Replicate across tickers before accepting a finding.** BTC alone is
   not enough. For market-wide variables like VIX, even two tickers isn't
   replication (both see the same VIX days) — that needs 3+ and a
   split-sample check.
3. **Document negative findings rather than papering over them.** The ML
   failure and the 4-year degradation are recorded in the code, not
   quietly removed. Do the same with anything new that fails.
4. **Derive values that encode relationships.** Extreme-fear panic bars are
   computed as (normal ± shift) rather than hardcoded, so the relationship
   survives future threshold changes. Follow that pattern.
5. **A FAIL in `audit.py` is often a finding, not a bug.** If the long side
   flips sign between time halves, that's information about the market. Do
   NOT "fix" it by loosening a threshold until it passes. Report it and let
   me decide on scope (long-only, shorter window, regime gate).

## Research rules

Research is kept separate from the live system, and stays separate.

1. **All research code lives in `research/`.** It never modifies
   `signal_engines.py`, `live_tools.py`, `pipeline.py`, or the workflows.
   Research may import from them read-only. If a finding needs a change in
   a core file, that is a separate decision and a separate commit — the
   research script does not make it.
2. **The lockbox is never read by any research script.** The last 6 months
   are holdout: not for fitting, not for plotting, not for a sanity check,
   not "just to look". A hypothesis that has seen the lockbox can never be
   validated on it. (See "The lockbox is sealed" above.)
3. **Every hypothesis gets a number and is written to `docs/cleanroom.md`
   BEFORE it runs.** The entry states what is being tested, the exact
   parameters, and what result would count as a pass — recorded first, so
   the bar cannot move once the numbers are in.
4. **No parameter is changed after seeing a result.** Tightening a
   threshold, extending a window, or dropping a ticker after the fact
   makes it a NEW hypothesis with a new number; the original result stands
   as recorded. Silently re-running with different parameters is the
   single easiest way to fool this project.
5. **Negatives are reported with the same detail as positives.** A failed
   hypothesis gets the same write-up and the same numbers — not "didn't
   work". Most will fail; that record is exactly what makes the survivors
   mean anything.
6. **Research commits are separate from signal-check commits.** Never fold
   research output into an hourly `Signal check:` commit.
7. **DISCOVERY does not run placebo draws.** Discovery ranks rules against
   each other on the pre-registered metric; it does not need a null
   distribution to do that. Placebo belongs in exactly two places: the
   reference rows (where the incumbent is measured against chance) and
   CONFIRMATION (where a frozen shortlist is). Drawing placebos across a
   whole discovery grid costs thousands of backtests for a number nothing
   in the selection rule reads.
8. **Per-ticker data is built ONCE per ticker and reused by every rule.**
   The resampled daily frame, its indicators, and the 4h ATR depend only
   on the ticker, never on the rule being scored. Rebuilding them inside
   the per-rule loop multiplies the whole grid by the number of rules.
   `pipeline.backtest_exit_geometry` calls `build_4h_atr` on every
   invocation (pipeline.py:1612) — once per fold per rule, 1,440 times for
   a 120-rule grid. `research/harness.py` memoizes it at the harness
   boundary; research does not edit pipeline.py to fix this (rule 1), it
   caches around it.
   MEASURED, so nobody re-litigates it: that cache is worth ~1.0x and the
   frame-slimming beside it ~1.1x. Neither is the cost driver — the full
   120-rule x 3-ticker grid runs in ~45s either way. The 25 minutes in the
   first run were placebo draws, which is what rule 7 removes. Keep both
   as hygiene; do not go hunting further per-rule micro-optimisations
   expecting a win that is not there.

9. **THE RESTLESSNESS RULE.** When the impulse to run a new test arrives,
   the first act is to re-read the market-structure map (#249) and the
   closed-axis list in the research status.

   **A new test requires, in its registration, one sentence naming which
   closed door it does not re-open and what NEW information or structure it
   rests on.** "The itch" is not new information.

   All currently-legitimate future tests already exist, sealed, with dates:

   | test | gate |
   |---|---|
   | SHADOW-EVAL | 30 pooled closed episodes |
   | FUNDING #172-#186 | ~2027-06-27 |
   | POSITIONING #235-#242 | ~2028-01-05 |
   | OI/BASIS #243-#248 | ~2028-07-01 |

10. **THE PAYER CLAUSE.** *(Constitutional amendment, 2026-09-01. Binds
    every registration from this date.)*

    **Every hypothesis must name, in its registration, the STRUCTURAL
    PAYER: who systematically loses to this rule, and why they cannot or
    will not stop.** The reason must be a named constraint --

    | class | what makes it bind |
    |---|---|
    | **forced flow** | a schedule someone must trade on regardless of price (roll, expiry, rebalance, settlement) |
    | **mandate** | a rule that compels holding, hedging or divesting irrespective of expected return |
    | **behavioral constraint** | a documented, persistent bias that survives being pointed out |
    | **hedging demand** | price-insensitive demand for protection, paid for out of a risk budget rather than an alpha budget |

    **"No payer identified" is a PERMITTED answer** and must be written in
    exactly those words. It is not a defect and does not block a
    registration -- but it is **recorded as the weakest class of
    hypothesis**, and that label travels with every result the program
    produces.

    **WHY THIS IS A RULE AND NOT ADVICE.** Every program this project has
    run has been a search over the SHAPE of a rule -- lookback, threshold,
    weighting, window -- with the question of who is on the other side left
    unasked. Nine axes have now been searched and closed with zero
    survivors. That is a large amount of evidence that shape-search alone
    finds nothing, and the cheapest available explanation is that a rule
    with no identified payer has no reason to work in the first place.
    Naming the payer is the one filter that can be applied BEFORE the
    Bonferroni budget is spent rather than after.

    **WHAT THIS RULE MAY NOT BECOME.** A payer story is not evidence. It
    does not raise a percentile, lower a bar, rescue a near-miss, or
    license a re-test of anything already closed (rule 4 is unchanged). A
    beautifully argued payer attached to a failing rule leaves a failing
    rule. The clause can only ever make a hypothesis harder to justify
    writing down -- never easier to pass.

    **THE HONESTY TEST, IN BOTH DIRECTIONS.** A payer that would be
    described the same way whatever the data showed is not a payer, it is
    a story. State the payer BEFORE the result, in the registration, where
    it can be wrong.

    **AND THE SAME TEST APPLIES TO "NO PAYER IDENTIFIED."** That answer is
    permitted, but it may not be reachable *by definition*. Defining
    "payer" narrowly enough -- say, as the contractual counterparty -- makes
    "no payer" derivable for every spot-only program in this repository
    without opening a single file, and a conclusion reachable with zero
    observations is worth exactly as much as a payer story that survives
    any data.

    > **So a "no payer identified" must name WHICH forced flow it looked
    > at and WHERE that flow's rent is actually collected instead.**

    "I could not think of one" is not the finding. "The flow is real, it
    is *this*, and it is paid to *that seat*, which this rule does not
    occupy" is the finding -- and it is a far more useful one, because it
    says what would have to change for the answer to differ.

   Plus the one BANKED hypothesis slot from #249, which may be spent only on
   post-freeze data or on a mechanism argued FIRST and then checked against
   the map.

   **This rule was written on a calm day to bind a restless one.**

## Research status — the architectural search is CLOSED

**Six axes searched, zero survivors.** ROTATION (#187-#192), ALLOCATION
(#193-#196), ABLATION (#197-#202) and SQUEEZE-ONLY (#203) are all run,
reported and closed out in `docs/cleanroom.md`. `docs/claims.md` holds
**zero supported edge claims** and nothing from these programs may be quoted
as support.

Closest calls, so nobody re-opens them casually: **#187** cleared all four
clauses on DISCOVERY and died on CONFIRMATION's placebo (+0.527 vs +0.619);
**#203** posted the project's best `ex_best` (+0.234, 4/4 folds) and died at
the 91.5th placebo percentile against a p95 bar; **#194** cleared "the test"
on CONFIRMATION and died because its **inverted** control cleared it too.

**Do not re-specify any of them.** A different lookback, rebalance day, vol
window, cap, epsilon or placebo is a NEW registration with a new number
(research rule 4). The recorded results stand.

**Still open:** SHADOW-EVAL accrues forward on both arms and may not be
inspected before 30 pooled closed episodes. FUNDING (#172-#186) is
registered, SEALED and DORMANT until its data-depth trigger (~2027-06-27).

**FUNDING-AT-BINANCE-DAILY (#220-#234) is CLOSED: 0 of 15 pass, clause 2
failed in all 30 cells.** Eight rules F1-F8 in both modes, daily
granularity, Binance USD-M, 5.05 usable years -- five times #172-#186's C1
window -- and 24 of 30 cells still carried an undefined ex_best. Depth was
not the binding constraint; EVENT RATE was. Closed means no re-runs, no
looser bar, no partial credit, and NO VARIATIONS of a failed rule.

**#226 is the near-miss and may not be re-specified.** F4 euphoria-fade
suppression on CONFIRMATION: ex_best positive on all three tickers (+0.059 /
+0.131 / +0.121), pooled +0.193 over 434 trades and 52 episodes, at the
92.6th placebo percentile against a 99.67 bar -- and -0.053 at the 46th
percentile on DISCOVERY. It is the best funding result this project has AND
a failure; both are true.

**The funding QUESTION is not closed.** Its closure clause lives in
#172-#186 and triggers on failure at THAT program's C2, on a different
venue, on data that does not yet exist. The inherited cross-venue flag FIRED
on all three symbols (Pearson vs Kraken +0.452 / +0.371 / +0.719 against a
0.80 bar), which is measured grounds for valuing that independence MORE: two
feeds of the same quantity correlating at 0.37-0.72 means a result on one is
not a proxy for the other.

NULL-CALIBRATION (#217-#219) is RUN and CLOSED. It changed no verdict, and
it put the instrument into its final honest form: every null this project
owns is now measured, and every one of them is contaminated in some regime
(see the table above). Two findings bind on everything after it. (1) Crypto
ROTATION's DISCOVERY clause-2 null held ~30% of its gross weight in assets
that did not exist -- axis 2 did not exist yet when ROTATION ran -- so that
bar was far too EASY, and **#187's DISCOVERY clause-2 pass may not be cited
as evidence of anything**; its counterfactual is UNMEASURABLE, because the
time-rotation null is infeasible on both ROTATION windows (T = 42.4 and 34.7
months against a 48-month minimum). Where universes are complete,
inheritance runs the other way -- UPWARD, tracking rho-bar, +0.5 to +3.0
pp/yr. (2) The time-rotation null removes correlation inheritance (-0.14
pp/yr on equities DISCOVERY vs the permutation null's +2.48) but NOT
persistence inheritance (+2.16 on CONFIRMATION). It is available with that
weakness attached.

**MACRO-OVERLAY (#251-#256) is CLOSED: 0 of 6 pass. The MACRO/FLOW AXIS ON
FROZEN DATA IS SEARCHED AND CLOSED.** Six regime gates over two independent
series (DefiLlama stablecoin supply, FRED DGS10), both windows, 3,000 seeds,
every constant fixed before export and the series frozen under sha256.
**#256** (both-easing) cleared all three clauses on CONFIRMATION at the
99.8th percentile and FAILED -- its DISCOVERY twin sits at the 46.0th with a
-0.2590 ex_best, and its percentile rests on **17 runs**. **#255** missed the
bar by 0.17 percentile points (99.0 vs 99.1667) and is a FAIL. Neither may be
re-specified; a different lookback, boundary, series or combination is a NEW
program that must first name which closed door it does not re-open.
**#252 was GATED at 16 DISCOVERY-Q1 trades, which cost the program its
pre-declared two-sided control** -- a control built from a hypothesis pair is
only as available as its weaker member's event count.

**THE PAYER CLAUSE (research rule 10) is CONSTITUTIONAL from
2026-09-01.** Every future hypothesis names its structural payer or
states "no payer identified" and is recorded as the weakest class.
The three sealed programs were annotated post-hoc -- **all three come
back NO PAYER IDENTIFIED, for one shared structural reason**: the
forced flow they detect is settled on the PERPETUAL, and these
programs buy SPOT one to two days later, so the rent is collected by
seats they do not occupy. **Their locked rules are unchanged.** The
annotation also exposed a defect in #235-#242 that nothing else had:
#235/#239 and #236/#238/#240 register OPPOSITE states as the same
BUY, so any payer story for one direction is refuted by its own
registered twin. Noted, not fixed; the rules stay as sealed.

**THE PAYER FINDING IS ALSO A DATED PREDICTION.** The shared reason all
three sealed programs return NO PAYER IDENTIFIED -- the rent settles on the
PERPETUAL and these programs buy SPOT at D+1 -- is registered as a
mechanical prediction that **all three FAIL** at their gates (~2027-06-27,
~2028-01-05, ~2028-07-01). **A PASS BY ANY OF THEM REFUTES THE ANALYSIS**,
and would mean the routing argument was wrong rather than that a payer was
found. It lowers no bar and changes no pass rule; its value is that a pass
would cost it something.

**ROUTING RULE for adversarial-review findings, standing:** a computation
defect in live or instrument code is FIXED, re-rendered, and noted in the
commit; anything bearing on a SEALED registration gets a dated, post-hoc
PAYER-LAYER ANNOTATION ONLY, rules untouched. A wrong number should be
corrected the moment it is known; a sealed rule that now looks
ill-conceived is evidence about our 2026 judgement, and editing it destroys
what pre-registration exists to preserve.

**#257 THE PREMIA INSTRUMENT is RUNNING and does not end.** It is an
instrument, not a test: no hypotheses, no verdicts, no Bonferroni
budget, nothing drawn from it. It measures what professionals
harvest, on data we manufacture. Nothing it prints is tradeable by
this operator or may enter a signal post. **From 2026-09-01 the monthly
transparency post carries #257's summary block** behind a mandatory
preamble -- risk premia, not signals, not tradeable by this operator, VRP
not computable until the archive matures -- which `publish.dry_run()`
refuses to ship without. That adds NO SUPPORTED claim: a measured market
price is not a claim about this system.

**EVERY SEARCH PROGRAM IS RUN AND CLOSED**: the crypto grid, the basket
programs, the architectural search (#187-#203), EQUITIES (#204-#216),
NULL-CALIBRATION (#217-#219), BINANCE FUNDING (#220-#234) and MACRO-OVERLAY
(#251-#256).

**THE STRATEGY IS NOW FORWARD COLLECTION, AND SIX CLOCKS ARE RUNNING.**
Nothing is in flight; everything open is calendar-gated and may not be
inspected before its gate.

| clock | gate | what it is |
|---|---|---|
| **SHADOW-EVAL** | 30 pooled closed episodes | incumbent + squeeze-only arms accruing forward |
| **LIVE RECORD** | continuous | `signal_outcomes.csv`, the only real out-of-sample money-path |
| **FUNDING #172-#186** | span >=22 mo, **~2027-06-27** | SEALED, unmodified, Kraken venue |
| **POSITIONING #235-#242** | span >=22 mo, **~2028-01-05** | OKX rubik; 179 days banked free at first collection |
| **OI/BASIS #243-#248** | span >=22 mo, **~2028-07-01** | Kraken tickers; CURRENT-ONLY, zero banked |
| **(data) six collector sources** | daily | the archives all five of the above eventually read |

**#235-#248 hold the registered-before-the-test-data-exists property**, which
only #172-#186 previously had and which #220-#234 explicitly could not claim.
Their usable windows do not exist anywhere yet -- A's beyond 180 days back,
B's at all -- so tuning to the test set is impossible by construction rather
than by discipline. Quote it in its precise form: registered before the TEST
data exists. (180 days of A's eventual BURN-IN are already on disk; no rule
is scored on them.)

**THE MARKET-STRUCTURE MAP (#249) IS COMPLETE AND THE BOARD IS SEALED.**
`docs/market_structure.md` is the last construction available on frozen data:
descriptive, no hypotheses, no verdicts, and it could not change claims.md.

**Its one-hypothesis slot is BANKED, not spent. NO #250 was drawn.**

- **M4 measured the leading folklore candidate as ABSENT** -- "BTC leads the
  alts" is contemporaneous only (rho +0.822 ETH / +0.611 SOL at lag 0, every
  lag 1h-24h within +/-0.031 of zero, every vol tercile, every year). That is
  the map's most useful output and it is a NEGATIVE.
- **M1 and M2 are real but canonical**, and their monetisations were already
  tested (volatility scaling IS ALLOCATION #193-#196, which failed) or have
  no entry mechanism (fat tails describe the RISK, not a direction or a time).
- **M3 is chance-consistent** -- fewer significant lags than chance alone
  would produce across 270 cells.

Spending the slot on the most interesting-looking cell is precisely what the
one-hypothesis rule exists to prevent, and a slot spent badly is worse than a
slot unspent. **It remains available to exactly two things:** a future map
built on POST-FREEZE data (its own registration), or a mechanism argument
articulated FIRST and then checked against this map. Mechanism-then-map is
legitimate; pattern-then-invented-mechanism is not. The slot does not expire
and does not accumulate -- one remains one.

**M6's measured pairwise correlation (rho-bar 0.479 in 2021 to 0.707 in 2022,
tight non-overlapping CIs) is cross-referenced into NULL-CALIBRATION** as the
empirical input governing inheritance contamination on this universe. It is
not a constant: any future program reporting axis 4 on the tradable-26 must
report rho-bar for its OWN window rather than quoting one project-wide figure.

**THE BOARD IS SEALED AGAINST RE-OPENING CLOSED AXES** -- which is the rule
that matters, and is not the same as "no doors remain".

**LEDGER CORRECTION (#251).** This section previously read "Nothing further
can be learned from the frozen dataset." That was TRUE of every axis the
project had SEARCHED -- price transformations, resolution, architecture,
components, funding-at-daily -- and FALSE in general: exogenous macro/flow
series had never been joined to the frozen basket at all. MACRO-OVERLAY
(#251-#256) is the exception that proves the distinction, and it is
admissible only because research rule 9's sentence is satisfiable: it rests
on information never tested and re-opens no closed door.

**Starting a new search means writing a new registration first.**

**EQUITIES (#204-#216) is closed: all six FAIL, the fail/fail cell.** The
ladder did NOT certify the most replicated anomaly in the equities
literature on 26 years of data, in a universe where the effect is visible
descriptively (rule beats its own mirror in 9 of 10 comparisons). The
instrument is NOT validated, and the crypto zeros carry LESS weight as
evidence about crypto than they appeared to.

### Placebo fidelity — check FOUR axes before a null decides anything

The search found two defects in two placebos, same family: **a null that
differs from the strategy in more than the one thing it claims to isolate.**
Two of them made a registered bar EASIER (pushing toward a false positive);
the fourth axis below catches the opposite failure, a bar made too HARD.
Before any placebo is used for a verdict:

1. **Turnover fidelity** — report the null's turnover as a ratio to the real
   rule's AND convert the gap to **annualised drag in pp/yr**
   (`extra_turnover x cost_per_side x 365`). **The ratio alone is the wrong
   unit:** 1.42x cost ALLOCATION's null 0.23 pp/yr (it trades 0.019/day),
   while ROTATION's 13.6x cost ~42 pp/yr (0.116/day). Judge in pp/yr.
2. **Universe fidelity** — report the fraction of gross weight the null puts
   on assets that did not exist on that date, beside the real rule's figure.
   Missing prices become zero returns silently, so this is invisible in
   returns, turnover and exposure; it must be measured directly.
3. **Cash-eligible-month count** (rules that can stand aside) — the null's
   count of ELIGIBLE asset-months holding nothing must match the real rule's
   within +/-2% relative. A null in cash a different share of the time is
   testing a different exposure budget, not timing. Count over ELIGIBLE cells
   only; counting every zero cell measures the growing universe instead.
4. **Correlation inheritance** — the null's DISTRIBUTION CENTRE minus the
   matched random-N median, in pp/yr, reported beside the universe's average
   pairwise correlation. **A null on a correlated universe can inherit the
   effect it exists to destroy.** Measured on EQUITIES DISCOVERY: the
   rank-permutation null's centre sat at +0.0864 against random-3's +0.0616
   and equal-weight's +0.0709 -- roughly 2.5 pp/yr of inherited effect, so
   the bar was set higher than its construction intended. This is the one
   axis whose failure makes a bar TOO HARD rather than too easy, which is why
   it went unnoticed through five programs: nobody audits a null that is
   producing failures.

   **Report it always. A clause-2 FAIL measured against a null with material
   inheritance must carry the measured inheritance beside it** -- it does not
   void the FAIL, and it does not license a re-test (research rule 4), but a
   bar nobody measured is not a bar anybody can cite. See NULL-CALIBRATION
   (#217-#219) and the time-rotation null registered there.

Repair on the same principle every time: **the null pays what the strategy
pays and is constrained the way the strategy is constrained.** Quantify any
residual and say which side it favours.

#### The standing rule, final form

1. **Every program NAMES its adjudicating null at registration.** Not "a
   placebo" -- which generator, on what quantity, with what parameters. A null
   chosen after seeing results is not a null.
2. **All four axes are measured on it BEFORE any draw scores anything**, and
   the measured numbers are reported with the result, not just the verdict.
3. **Where feasible, the alternate null family is reported beside it** with
   its own measured contamination. Where it is NOT feasible, say so and give
   the number that makes it infeasible -- e.g. the time-rotation null cannot
   run on a window shorter than 48 months, and crypto's ROTATION windows are
   42.4 and 34.7.
4. **NO NULL IS PRESUMED CLEAN.** Not the permutation null, not the
   time-rotation null, not a future one. Every null measured so far is
   contaminated in some regime:

   | null | regime | contamination |
   |---|---|---|
   | rank-permutation (weights) | growing universe | ~30% dead weight -> bar far too EASY (crypto DISC) |
   | rank-permutation (signal) | correlated universe | +0.5 to +2.5 pp/yr inherited -> bar too HARD |
   | time-rotation | persistent regime | +2.2 to +2.4 pp/yr inherited -> bar too HARD (equities CONF) |
   | time-rotation | short window | INFEASIBLE below 48 months |

   **That table is the citation.** A claim that some null is neutral must
   beat it with a measurement, not an argument.
5. **Contamination does not void a verdict and does not license a re-test**
   (research rule 4). It is recorded beside the result so the result can be
   read for what it is.
6. **THE FOUR AXES CERTIFY THE CENTRE, NOT THE TAIL.** Axis 4 compares the
   null's distribution CENTRE against a matched random draw. It cannot say
   whether the null is too NARROW or too WIDE -- and every percentile pass
   condition in this project is decided in the TAIL (99.17th, 98.75th,
   99.6667th), where width is nearly the whole story. #167 chose the
   episode-matched null for lower VARIANCE on clustered signals, and axis 4
   read about zero on #220-#234 while saying nothing about the property the
   choice was made for.

   **So every percentile verdict this project has issued carries an
   UNCHARACTERIZED TAIL-WIDTH CAVEAT.** State it when citing one. A width
   axis would be a methods program with its own registration; inventing one
   after a batch of tail-comparison failures is the move research rule 4
   forbids, so the gap is recorded rather than quietly patched.

### Regime-series gates — the null form, and the mandatory run-count table

**THE REGISTERED NULL FORM FOR ANY BOOLEAN REGIME SERIES.** Decompose the
observed series into its **TRUE-runs** and **FALSE-gaps**, permute each list
independently, and lay them back down end to end from the observed starting
parity. Run **count**, run **lengths**, gap **lengths** and **total
coverage** are preserved by construction; only **where** the runs sit
changes, which is the one thing the null exists to destroy.

The obvious alternative -- place each observed run at a random
non-overlapping position -- **fails axis 1 at high regime density.** #251's
first null used it with 12 placement attempts per run; at 73% density most
runs could not find a free slot and were silently dropped, leaving the null
with **0.22x** the strategy's trades. The run/gap decomposition took axis 1
to 1.13x / 1.02x. Add to the contamination table:

| null | regime | contamination |
|---|---|---|
| random run PLACEMENT | dense regime (>~50% of days) | runs unplaceable and dropped -> 0.22x trades; a thinner strategy, not a timing null |

**SLOW REGIME SERIES ARE NEAR-CALENDAR GATES, AND SEEDS DO NOT FIX IT.** The
null shuffles **runs**, so the run COUNT is the effective sample size behind
every percentile it produces -- not the seed count, and not the trade count.
#251 DISCOVERY covered 73% of days in **11 runs, one of them 777 days**:
effectively a single block. #256's 99.8th percentile rested on **17 blocks**.

> **A run-count table -- runs per window, with the longest run -- is
> MANDATORY beside any percentile computed against a regime-series null.**
> Seeds buy resolution, not independence.

This compounds the axis-4 centre-vs-tail caveat rather than replacing it: few
blocks make the tail both uncharacterized AND coarse.

**THE MONOTONE SLOWER-SERIES -> HIGHER-PERCENTILE GRADIENT IS THE DIAGNOSTIC
SIGNATURE OF A WINDOW EFFECT.** When a family of regime gates comes back
positive in one window and negative-or-flat in the other, with the slowest
series scoring highest, the gate is close to gating on TIME and the test is
mostly reporting which window was kinder. All six of #251-#256 showed it.

**The gradient is computable from run counts alone, with no outcome data, so
it is checkable AT REGISTRATION.** A regime-series program states its run
counts per window in its registration; a series with single-digit-to-teens
runs in a window is disclosed as near-calendar there before anything runs.

### The fixed-k gate law — a gate removes chances, never cheapens them

An **event-count gate** may sit in front of a program: count the confirmed
trades a hypothesis produces from its own definition and the calendar
STRUCTURE ONLY -- never from returns -- and refuse to run any hypothesis
below the ex_best floor of >=30 trades per ticker per window, marking it
UNMEASURABLE-BY-CONSTRUCTION.

> **THE BONFERRONI k STAYS AT THE REGISTERED VALUE, however many hypotheses
> the gate removes.**

The reason is the whole point of the correction. k counts **opportunities
for a false positive**, and registering N hypotheses creates N of them. A
gate that removes some before scoring reduces how many chances are TAKEN; it
does not retroactively reduce how many were CREATED, and it tells you
nothing about the survivors. Shrinking k after a gate would mean a program
could loosen its own bar by including hypotheses it expected to fail --
paying nothing for them and being rewarded with an easier threshold for the
rest.

**So a gate can only ever remove chances at a false positive. It can never
cheapen the remaining ones.** State the registered k, the surviving count,
and the gate's per-hypothesis trade counts side by side, so the difference
is visible rather than absorbed.

### Overlay unmeasurability — refuse at registration, not after

**Overlays on incumbent BUY days are unmeasurable BY CONSTRUCTION.** `ex_best`
needs >=3 folds x >=10 trades = **>=30 trades per ticker per window**.
Measured over #220-#234's 90 ticker-window cells: overlays median **1.0**
trade (mean 4.9, max 36) and **2 of 42 cells reached 30**; standalone tests
median 33.5 and 24 of 48 reached it. Getting from a median of 1 to 30 needs
**30x the data, roughly 75 years per window** -- longer than crypto has
existed.

The mechanism is structural: an overlay fires only where the incumbent
ALREADY signalled AND a conditional state holds, and intersecting sparse BUY
days with a minority condition leaves single digits.

> **A future overlay registration on incumbent BUY days is REFUSED unless it
> demonstrates, from EVENT COUNTS ALONE and BEFORE any scoring, that it
> clears >=30 trades per ticker per window.**

Event counts need no returns, so the check is free. Seven of #220-#234's
fifteen tests were overlays, all seven were unmeasurable before the first
trade was scored, and they still consumed Bonferroni budget -- raising the
bar for the eight tests that could have produced a result. That is the cost
of not having this rule earlier.

## Product status — machinery COMPLETE, launch pending three human items

The Discord service machinery is built, tested and wired. **Nothing in the
code is waiting on anything.**

- `research/publish.py` — OPEN/CLOSE episode alerts and the monthly
  transparency post, rendered as TEXT for a human to post. **No Discord API,
  no tokens, no automation**, and it is READ-ONLY against the live signal
  path: it consumes `signal_log.csv` / `signal_outcomes.csv` and writes
  nothing the signal path reads.
- `docs/claims.md`'s WORDING section is the source of truth. **Disclosures
  are reproduced verbatim; the NUMBERS are computed live**, because a
  template carrying its own frozen tally starts publishing a false one the
  moment an episode resolves.
- **Never publishes:** shorts (long-only path), `REFUSED_UNTRADABLE` /
  `SKIPPED_COST_FLOOR` rows, WATCH/AVOID, and anything from the shadow
  basket. Each is asserted by test; the shadow check is an AST check, not a
  grep, because the docstring legitimately discusses it.
- `audit.check_publication_generators()` dry-runs both generators weekly, so
  format rot fails in CI rather than in front of a subscriber. A human copies
  these posts; nothing else inspects them on the way out.
- `docs/discord_setup.md` is the build sheet: channels, pinned text, and the
  operating rules including the no-DM-advice rule and the requirement that
  the transparency post goes up BEFORE the first signal.

**LAUNCH IS GATED ON THREE HUMAN DECISIONS, none of which is mine to make:**
operator disclosure filled in, a parent conversation if the operator is a
minor, and the open-vs-private decision recorded with one line of reasoning.
They are the checklist at the end of `docs/discord_setup.md`. **Nothing goes
public until all three are done.**

## Known open issues

- **4-year degradation (unresolved).** Extending the backtest to ~4 years
  showed BUY win rate falling toward 50% and SELL expectancy flipping sign
  over 2022–2026. The 2024–2026 validation window may simply have been
  favorable. `pipeline.py robustness` measures this; the decision is open.
- **VIX regime — REMOVED FROM THE PUBLISHED PATH 2026-09-01, criteria never
  met.** Stressed-VIX trades once looked strongly positive against normal
  VIX, and pre-registered criteria for accepting it live sat in
  `pipeline.py`'s robustness section. #201 then measured the regime as
  UNEXERCISED BY CONSTRUCTION on the long side: removing it moved
  expectancy +0.000R on both windows, because BUY-tier membership changed
  on ONE day in 6.42 years and that day was unconfirmed. claims.md lists
  the long-side contribution as NOT SUPPORTED. The code is one flag away
  (`use_vix_regime=True`) and the incumbent shadow arm still exercises it.
- **Short side viability (open), and the filter now only exists in the
  incumbent.** Shorts use a 50-day SMA trend filter, which lived in Step 3
  — so from 2026-09-01 it cannot fire on the published path and logged
  short rows are a different construction from the one that produced the
  0-for-11 quoted in claims.md. No published signal changes (shorts are
  never published), and claims.md carries the dated disclosure. Whether
  shorts hold up across halves and tickers is still what
  `short_side_verdict` decides.
- **Resolution axis — CLOSED for the bar-equivalent construction (#168-#170,
  2026-08-28).** The 1h program is finished. #168 (time-equivalent) FAILED:
  BTC hit target 33.3% against a 34.1% base rate, where the 4h tier ran 78%
  against ~35% — the hit-rate mechanism did not survive the port. #169 PASSED
  its gate and is the program's one affirmative result: the 2-bar confirm
  produced the **first computable `ex_best` in the project's history**, on all
  three tickers, for the structural reason recorded before the run. #170 then
  used that statistic and FAILED all four conditions on both windows —
  `ex_best` negative in 5 of 6 ticker-window cells, pooled net inside the
  placebo distribution on both halves. **This is the project's first fully
  measured negative** rather than another "unmeasurable".
  **It does NOT adjudicate the 4h tier.** That n=18 excess (+1.819R BTC, 2
  independent episodes) remains unmeasurable and unadjudicated: #168 tested a
  rescaled construction registered as robustness on one ticker, and #170 a
  bar-equivalent one running on a 4x shorter timescale. Both are different
  strategies. See the close-out in `docs/cleanroom.md`.
- **Git object write failures on this machine (intermittent).** `git add`
  has failed with `unable to write file .git/objects/...: Permission denied`
  mid-session, leaving the index partially written. A plain retry has always
  succeeded. Almost certainly antivirus or an editor holding a lock on the
  object file. It is benign locally — but if it ever happens on a runner it
  surfaces as a failed commit step with the run otherwise green, so a
  signal-check run could complete its work and silently not push it. If
  `Signal check:` commits stop appearing while runs stay successful, look
  here first.
- **Adanos tier — RESOLVED by gating, no upgrade needed.** Hourly checks
  used to need ~720 requests/month per ticker against a 200/month free
  tier. Two changes fixed it: the call is skipped below the derived cutoff
  (33.3 — below it the dampen-only gate provably cannot change the label),
  and a 12h per-symbol TTL bounds spend by the calendar rather than by the
  candidate rate. Replayed against the real log: **~31 requests/month per
  ticker, ~92 for three**, ceiling 62/186. Comfortably inside the free
  tier. `SENTIMENT_TTL_HOURS` overrides the TTL if the tier changes.

## Deployment

Hourly signal checks run on GitHub Actions under **two triggers on
purpose**: GitHub's native `schedule` cron AND cron-job.org calling
`workflow_dispatch`. Each has failed alone — native cron was dropped once
for unreliability, and dispatch-only left an 11h gap on 2026-08-27 — so
both run and a missed tick from either is covered by the other.

What makes that safe is the **guard step**: `live_tools.py should-run`
reads the newest `signal_log.csv` timestamp and stands down if it is under
50 minutes old, so whichever trigger arrives second does no work. Without
it both simply ran (measured 2026-08-27: 52 `schedule` + 48
`workflow_dispatch` over 100 runs, median gap 0.50h instead of 1h — double
cadence, double Adanos spend). The guard FAILS OPEN: a missing, empty or
unparseable log proceeds, because silently stopping the signal service is
worse than one duplicate run. It always exits 0, and the run summary
records which trigger executed.

Chart is on GitHub Pages at
`https://bembem718ai-stack.github.io/Crypto-Model/BTC.html`.

Workflows: `signal-check.yml` (hourly), `robustness.yml` (manual),
`audit.yml` (manual + weekly).

## Style

Comments explain WHY, especially where a choice looks wrong at first
glance — the conviction scaling that makes STRONG_* signals 2.667 R:R
instead of 2.0 is a good example. Keep test coverage as a first-class
concern; new decision logic gets tests in the same change.
