# Model Audit

Run: 2026-08-28 05:49 UTC · tickers: BTC ETH SOL · window: 4y

| Status | Count |
|---|---|
| FAIL | 0 |
| DEGRADED | 0 |
| INSUFFICIENT | 0 |
| SKIP | 0 |
| PASS | 17 |

| Section | Check | Status | Detail |
|---|---|---|---|
| A. Structural | Unit test suite | **PASS** | 462 tests passed |
| A. Structural | ML stays display-only | **PASS** | score/direction identical across ML 1%/50%/99%/absent; ml_weight defaults to 0 |
| A. Structural | Backtest window not capped | **PASS** | depth scales with period (2y=5037 bars, 5y=12592 bars) |
| A. Structural | Exit level arithmetic | **PASS** | designed R:R holds both sides (plain 2.0, STRONG 2.666); WATCH inapplicable |
| A. Structural | No hardcoded API keys | **PASS** | no sk_live_ pattern in tracked source |
| D. Launch readiness | Long-only publishing enabled in hourly workflow | **PASS** | --long-only present |
| D. Launch readiness | Workflow commit survives missing optional files | **PASS** | existence guard present |
| D. Launch readiness | Outcomes file fresh (updated within 48h) | **PASS** | last resolved 2h ago |
| D. Launch readiness | Enough closed live episodes (>= 15) | **PASS** | 19 closed so far |
| D. Launch readiness | Log schema carries raw sentiment columns | **PASS** | sentiment_score/mentions present — the never-fired gate is now evaluable on real data |
| D. Launch readiness | Sentiment cache persisted to repo | **PASS** | present — runs within the TTL reuse it instead of paying Adanos |
| C. Deployment | Signal log is fresh | **PASS** | 1771 rows, newest 1.8h old [origin/main] |
| C. Deployment | Sentiment gate not erroring | **PASS** | most recent run's gate is PROCEED [origin/main] |
| C. Deployment | Derivatives collector is current | **PASS** | newest row 0.1d old |
| C. Deployment | Audit costs 0 Adanos requests | **PASS** | backtests use the neutral-sentiment assumption; note live hourly checks still need ~720/month per ticker vs a 200/month free tier |
| C. Deployment | Live outcomes tracked | **PASS** | 19 episodes, 19 closed |
| C. Deployment | Sentiment is measurable | **PASS** | 1 raw sentiment readings recorded |

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
