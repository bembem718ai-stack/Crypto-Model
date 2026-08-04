# Crypto-Model — project context

A cryptocurrency trading signal pipeline. Personal/extracurricular project.
Repo is PUBLIC: `bembem718ai-stack/Crypto-Model`.

## Run these commands, don't guess

```powershell
$py = "C:\Users\gubby\AppData\Local\Python\pythoncore-3.14-64\python.exe"
$env:BINANCE_REGION="US"          # REQUIRED — see "Binance" below

& $py -m pytest test_signals.py -q        # 203 tests, must stay green
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

Four core files plus the audit:

- `signal_engines.py` — Binance klines + Bollinger squeeze detection, Reddit
  sentiment via Adanos, Yahoo Finance technical/macro indicators, ATR exit
  levels, the ML engine.
- `pipeline.py` — 3-step orchestration in ENFORCED order, direction
  classification, backtests, position sizing, robustness validation.
- `live_tools.py` — confluence monitor, three-tab browser chart, local HTTP
  server, GitHub Actions check mode.
- `test_signals.py` — 203 tests covering all decision logic.
- `audit.py` — full-model health check; every known issue re-measured.

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
- **Adanos tier.** Hourly checks on one ticker need ~720 requests/month
  against a 200/month free tier. Upgrade pending.

## Deployment

Hourly signal checks run on GitHub Actions, triggered by cron-job.org via
`workflow_dispatch` (GitHub's native cron is too unreliable). Chart is on
GitHub Pages at
`https://bembem718ai-stack.github.io/Crypto-Model/BTC.html`.

Workflows: `signal-check.yml` (hourly), `robustness.yml` (manual),
`audit.yml` (manual + weekly).

## Style

Comments explain WHY, especially where a choice looks wrong at first
glance — the conviction scaling that makes STRONG_* signals 2.667 R:R
instead of 2.0 is a good example. Keep test coverage as a first-class
concern; new decision logic gets tests in the same change.
