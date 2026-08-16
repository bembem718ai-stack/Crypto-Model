# Model Audit

Run: 2026-08-16 06:26 UTC · tickers: BTC ETH SOL · window: 4y

| Status | Count |
|---|---|
| FAIL | 8 |
| DEGRADED | 6 |
| INSUFFICIENT | 5 |
| SKIP | 3 |
| PASS | 21 |

| Section | Check | Status | Detail |
|---|---|---|---|
| A. Structural | Unit test suite | **PASS** | 373 tests passed |
| A. Structural | ML stays display-only | **PASS** | score/direction identical across ML 1%/50%/99%/absent; ml_weight defaults to 0 |
| A. Structural | Backtest window not capped | **PASS** | depth scales with period (2y=5037 bars, 5y=12592 bars) |
| A. Structural | Exit level arithmetic | **PASS** | designed R:R holds both sides (plain 2.0, STRONG 2.667); WATCH inapplicable |
| A. Structural | No hardcoded API keys | **PASS** | no sk_live_ pattern in tracked source |
| D. Launch readiness | Long-only publishing enabled in hourly workflow | **PASS** | --long-only present |
| D. Launch readiness | Workflow commit survives missing optional files | **PASS** | existence guard present |
| D. Launch readiness | Outcomes file fresh (updated within 48h) | **PASS** | last resolved 0h ago |
| D. Launch readiness | Enough closed live episodes (>= 15) | **INSUFFICIENT** | 14 closed so far — live-vs-backtest comparison stays silent below 15; this is a waiting requirement, not a coding one |
| D. Launch readiness | Log schema carries raw sentiment columns | **PASS** | sentiment_score/mentions present — the never-fired gate is now evaluable on real data |
| D. Launch readiness | Sentiment cache persisted to repo | **INSUFFICIENT** | absent — every run pays a fresh Adanos call (~1000+/mo at 30-min cadence vs 250 free tier). Appears after the first successful sentiment call post-fix; also consider a 60-min cron-job.org interval |
| C. Deployment | Signal log is fresh | **PASS** | 1086 rows, newest 0.4h old |
| C. Deployment | Audit costs 0 Adanos requests | **PASS** | backtests use the neutral-sentiment assumption; note live hourly checks still need ~720/month per ticker vs a 200/month free tier |
| C. Deployment | Live outcomes tracked | **INSUFFICIENT** | tracking works: 18 episodes, 14 closed — too few for any live-vs-backtest conclusion yet |
| C. Deployment | Sentiment is measurable | **INSUFFICIENT** | columns exist but no readings recorded yet (fills on the next live runs) |
| C. Deployment | Binance route reachable | **PASS** | BINANCE_REGION=US, 5 bars fetched |
| B. Live data | BTC window spans 4y | **PASS** | 1454 rows, 1454d (2022-08-17→2026-08-10) |
| B. Live data | BTC long side stable across halves | **FAIL** | h1 -0.185R (n=67), h2 +0.117R (n=71) — sign differs by half; the edge is regime-conditional, not general |
| B. Live data | BTC edge survives costs | **FAIL** | gross +0.007R, net -0.053R (avg cost 0.060R, n=269) — the entire gross edge is inside the friction |
| B. Live data | BTC data integrity | **SKIP** | AttributeError: module 'signal_engines' has no attribute 'to_yahoo_crypto_symbol' |
| B. Live data | BTC score ranks outcomes | **FAIL** | score does NOT rank outcomes (corr -0.20) — a bar at 60 is arbitrary — 20-30: +0.156R (n=54) / 30-40: -0.052R (n=69) / 60-70: +0.023R (n=84) / 70-80: +0.061R (n=49) |
| B. Live data | BTC persistence filter (confirm_days 1→2) | **FAIL** | off +0.015R (n=516) → on +0.007R (n=269), gain -0.008R — no longer helps on current data |
| B. Live data | BTC short trend filter (SMA50) | **DEGRADED** | off -0.057R (n=324) → on -0.022R (n=131), gain +0.035R — still positive but below the bar that justified it |
| B. Live data | BTC ML holdout AUC | **DEGRADED** | AUC 0.604 clears 0.6 — worth re-testing on other tickers before ANY re-promotion |
| B. Live data | ETH window spans 4y | **PASS** | 1454 rows, 1454d (2022-08-17→2026-08-10) |
| B. Live data | ETH long side stable across halves | **FAIL** | h1 -0.046R (n=67), h2 +0.067R (n=58) — sign differs by half; the edge is regime-conditional, not general |
| B. Live data | ETH edge survives costs | **PASS** | gross +0.046R, net +0.000R (avg cost 0.046R, n=271) |
| B. Live data | ETH data integrity | **SKIP** | AttributeError: module 'signal_engines' has no attribute 'to_yahoo_crypto_symbol' |
| B. Live data | ETH score ranks outcomes | **PASS** | monotone-ish (corr +0.54) — 10-20: -0.733R (n=13) / 20-30: +0.118R (n=67) / 30-40: +0.105R (n=66) / 60-70: +0.016R (n=77) / 70-80: +0.076R (n=43) |
| B. Live data | ETH persistence filter (confirm_days 1→2) | **FAIL** | off +0.063R (n=539) → on +0.046R (n=271), gain -0.017R — no longer helps on current data |
| B. Live data | ETH short trend filter (SMA50) | **PASS** | off -0.027R (n=305) → on +0.036R (n=146), gain +0.063R |
| B. Live data | ETH ML holdout AUC | **DEGRADED** | AUC 0.619 clears 0.6 — worth re-testing on other tickers before ANY re-promotion |
| B. Live data | SOL window spans 4y | **PASS** | 1454 rows, 1454d (2022-08-17→2026-08-10) |
| B. Live data | SOL long side stable across halves | **PASS** | h1 +0.171R vs h2 +0.405R |
| B. Live data | SOL edge survives costs | **PASS** | gross +0.118R, net +0.086R (avg cost 0.032R, n=267) |
| B. Live data | SOL data integrity | **SKIP** | AttributeError: module 'signal_engines' has no attribute 'to_yahoo_crypto_symbol' |
| B. Live data | SOL score ranks outcomes | **PASS** | monotone-ish (corr +0.89) — 20-30: +0.069R (n=66) / 30-40: -0.077R (n=72) / 60-70: +0.258R (n=81) / 70-80: +0.434R (n=40) |
| B. Live data | SOL persistence filter (confirm_days 1→2) | **DEGRADED** | off +0.083R (n=538) → on +0.118R (n=267), gain +0.035R — still positive but below the bar that justified it |
| B. Live data | SOL short trend filter (SMA50) | **FAIL** | off -0.031R (n=282) → on -0.046R (n=146), gain -0.014R — no longer helps on current data |
| B. Live data | SOL ML holdout AUC | **DEGRADED** | AUC 0.673 clears 0.6 — worth re-testing on other tickers before ANY re-promotion |
| B. Live data | VIX regime edge replicates | **INSUFFICIENT** | INSUFFICIENT_DATA across BTC, ETH, SOL |
| B. Live data | Short side viable | **FAIL** | RECOMMEND_LONG_ONLY (0/3 tickers positive in both halves) |
| B. Live data | Kelly band sizing replicates | **DEGRADED** | funded bands or ramp direction differ across tickers — may be fitting per-ticker noise — BTC: 20+ ->1.90x, 60+ ->0.39x, 70+ ->1.05x; ETH: 20+ ->1.58x, 30+ ->1.31x, 60+ ->0.19x, 70+ ->1.06x; SOL: 20+ ->0.32x, 60+ ->1.18x, 70+ ->1.77x |

## How to read this

- **FAIL** needs a decision, not a code tweak. A sign-flipping
  edge is information about the market, not a bug.
- **DEGRADED** means it still works but by less than the margin
  that originally justified keeping it — worth re-deriving.
- **INSUFFICIENT** is not a soft pass. It means the honest answer
  is 'not enough trades yet'. Add tickers or extend the window.
- **SKIP** means the check could not run at all (usually network).
  Never read a SKIP as a PASS.

Nothing in this audit changed a default.
