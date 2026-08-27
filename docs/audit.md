# Model Audit

Run: 2026-08-27 19:50 UTC · tickers: BTC ETH SOL · window: 4y

| Status | Count |
|---|---|
| FAIL | 2 |
| DEGRADED | 0 |
| INSUFFICIENT | 2 |
| SKIP | 0 |
| PASS | 12 |

| Section | Check | Status | Detail |
|---|---|---|---|
| A. Structural | Unit test suite | **PASS** | 382 tests passed |
| A. Structural | ML stays display-only | **PASS** | score/direction identical across ML 1%/50%/99%/absent; ml_weight defaults to 0 |
| A. Structural | Backtest window not capped | **PASS** | depth scales with period (2y=5037 bars, 5y=12592 bars) |
| A. Structural | Exit level arithmetic | **PASS** | designed R:R holds both sides (plain 2.0, STRONG 2.666); WATCH inapplicable |
| A. Structural | No hardcoded API keys | **PASS** | no sk_live_ pattern in tracked source |
| D. Launch readiness | Long-only publishing enabled in hourly workflow | **PASS** | --long-only present |
| D. Launch readiness | Workflow commit survives missing optional files | **PASS** | existence guard present |
| D. Launch readiness | Outcomes file fresh (updated within 48h) | **PASS** | last resolved 17h ago |
| D. Launch readiness | Enough closed live episodes (>= 15) | **PASS** | 19 closed so far |
| D. Launch readiness | Log schema carries raw sentiment columns | **PASS** | sentiment_score/mentions present — the never-fired gate is now evaluable on real data |
| D. Launch readiness | Sentiment cache persisted to repo | **INSUFFICIENT** | absent — every run pays a fresh Adanos call (~1000+/mo at 30-min cadence vs 250 free tier). Appears after the first successful sentiment call post-fix; also consider a 60-min cron-job.org interval |
| C. Deployment | Signal log is fresh | **FAIL** | newest entry 6.4h old (> 6h) [origin/main] — the trigger may have stopped firing |
| C. Deployment | Sentiment gate not erroring | **FAIL** | 1350 CONSECUTIVE runs ended gate_decision=ERROR [origin/main] — Step 2 is neutral in production and the workflow still reports success. Check the Adanos quota/key; the run log now carries the HTTP status |
| C. Deployment | Audit costs 0 Adanos requests | **PASS** | backtests use the neutral-sentiment assumption; note live hourly checks still need ~720/month per ticker vs a 200/month free tier |
| C. Deployment | Live outcomes tracked | **PASS** | 19 episodes, 19 closed |
| C. Deployment | Sentiment is measurable | **INSUFFICIENT** | columns exist but no readings recorded yet (fills on the next live runs) |

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
