# Model Audit

Run: 2026-09-01 17:12 UTC · tickers: BTC ETH SOL · window: 4y

| Status | Count |
|---|---|
| FAIL | 1 |
| DEGRADED | 0 |
| INSUFFICIENT | 0 |
| SKIP | 3 |
| PASS | 26 |

| Section | Check | Status | Detail |
|---|---|---|---|
| A. Structural | Unit test suite | **PASS** | 581 tests passed |
| A. Structural | ML stays display-only | **PASS** | score/direction identical across ML 1%/50%/99%/absent; ml_weight defaults to 0 |
| A. Structural | Backtest window not capped | **PASS** | depth scales with period (2y=5037 bars, 5y=12592 bars) |
| A. Structural | Exit level arithmetic | **PASS** | designed R:R holds both sides (plain 2.0, STRONG 2.666); WATCH inapplicable |
| A. Structural | No hardcoded API keys | **PASS** | no sk_live_ pattern in tracked source |
| D. Launch readiness | Long-only publishing enabled in hourly workflow | **PASS** | --long-only present |
| D. Launch readiness | Workflow commit survives missing optional files | **PASS** | existence guard present |
| D. Launch readiness | Outcomes file fresh (updated within 48h) | **PASS** | last resolved 11h ago |
| D. Launch readiness | Enough closed live episodes (>= 15) | **PASS** | 19 closed so far |
| D. Launch readiness | Log schema carries raw sentiment columns | **PASS** | sentiment_score/mentions present — the never-fired gate is now evaluable on real data |
| D. Launch readiness | Sentiment cache persisted to repo | **PASS** | present — runs within the TTL reuse it instead of paying Adanos |
| C. Deployment | Signal log is fresh | **PASS** | 1791 rows, newest 1.8h old [origin/main] |
| C. Deployment | Sentiment gate not erroring | **PASS** | most recent run's gate is PROCEED [origin/main] |
| C. Deployment | Derivatives current: deribit_options | **PASS** | newest row 0.5d old (CURRENT-ONLY chain + ~16-day rolling hist-vol) |
| C. Deployment | Derivatives current: kraken_funding | **PASS** | newest row 0.6d old (~365-day rolling) |
| C. Deployment | Derivatives current: kraken_tickers | **PASS** | newest row 0.7d old (CURRENT-ONLY snapshot) |
| C. Deployment | Derivatives current: okx_funding | **PASS** | newest row 0.7d old (~90-day rolling) |
| C. Deployment | Derivatives current: okx_oi | **PASS** | newest row 1.0d old (~180-day rolling) |
| C. Deployment | Derivatives current: okx_rubik | **PASS** | newest row 1.0d old (~180-day rolling) |
| C. Deployment | Publication generators render | **PASS** | post 1802 chars; record 8 long / 19 all, +1.00R published |
| A. Structural | Dependencies match the lockfile | **PASS** | all 8 pinned packages match the installed versions |
| A. Structural | Live fetches retry with backoff | **PASS** | every requests/yfinance call in the live path sits inside a retry loop |
| D. Launch readiness | Both shadow arms accruing | **PASS** | last 100 rows: 100 incumbent / 100 squeeze labels, 100 Step 3 scores; sq_construction=squeeze+vix |
| C. Deployment | Audit costs 0 Adanos requests | **PASS** | backtests use the neutral-sentiment assumption; note live hourly checks still need ~720/month per ticker vs a 200/month free tier |
| C. Deployment | Live outcomes tracked | **PASS** | 19 episodes, 19 closed |
| C. Deployment | Sentiment is measurable | **PASS** | 6 raw sentiment readings recorded |
| C. Deployment | Binance route reachable | **FAIL** | BINANCE_REGION=(unset) → ConnectionError: Binance global request to /fapi/v1/klines failed after 4 attempts. Last error: 451 Client Error:  for url: https://fapi. (set BINANCE_REGION=US) |
| B. Live data | BTC data pull | **SKIP** | ConnectionError: Binance global request to /fapi/v1/klines failed after 4 attempts. Last error: 451 Client Error:  for url: https://fapi.binance.com/fapi/v1/ |
| B. Live data | ETH data pull | **SKIP** | ConnectionError: Binance global request to /fapi/v1/klines failed after 4 attempts. Last error: 451 Client Error:  for url: https://fapi.binance.com/fapi/v1/ |
| B. Live data | SOL data pull | **SKIP** | ConnectionError: Binance global request to /fapi/v1/klines failed after 4 attempts. Last error: 451 Client Error:  for url: https://fapi.binance.com/fapi/v1/ |

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
