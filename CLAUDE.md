# Crypto-Model — project context

A cryptocurrency trading signal pipeline. Personal/extracurricular project.
Repo is PUBLIC: `bembem718ai-stack/Crypto-Model`.

## Run these commands, don't guess

```powershell
$py = "C:\Users\gubby\AppData\Local\Programs\Python\Python312\python.exe"
$env:BINANCE_REGION="US"          # REQUIRED — see "Binance" below

& $py -m pytest test_signals.py -q        # 424 passed + 1 skipped, must stay green
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
- `pipeline.py` — 3-step orchestration in ENFORCED order, direction
  classification, backtests, position sizing, robustness validation.
- `live_tools.py` — confluence monitor, three-tab browser chart, local HTTP
  server, GitHub Actions check mode.
- `test_signals.py` — 424 tests covering all decision logic.
- `audit.py` — full-model health check; every known issue re-measured.
- `data/` — the frozen offline dataset: ~5y of Binance.US 4h bars plus the
  incumbent's daily frame per ticker (BTC/ETH/SOL), with `MANIFEST.json`
  recording bar counts, last bar, and the direction mix. Written by
  `export_data.py` (`BINANCE_REGION=US`). Research reads these files
  instead of the network, so a result can be re-run bit-for-bit later.
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

## Known open issues

- **4-year degradation (unresolved).** Extending the backtest to ~4 years
  showed BUY win rate falling toward 50% and SELL expectancy flipping sign
  over 2022–2026. The 2024–2026 validation window may simply have been
  favorable. `pipeline.py robustness` measures this; the decision is open.
- **VIX regime rescue candidate (unproven).** Stressed-VIX trades looked
  strongly positive vs negative for normal VIX. Pre-registered criteria for
  accepting it live in `pipeline.py`'s robustness section. Not yet met.
- **Short side viability (open).** Shorts use a 50-day SMA trend filter.
  Whether they hold up across halves and tickers is what
  `short_side_verdict` decides.
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
