# Forward-collection scoping probe

**Mechanical reconnaissance. Nothing registered, no hypotheses, no price
joins, no collector code.** Run 2026-09-01 from a US machine with the OS
trust store enabled.

**Spend: 39 requests, ~11.6 MB, $0.** Budget was ≤150. All endpoints are
public and unauthenticated; anything requiring signup was skipped rather
than half-tested.

**Geo verdicts follow the Bybit lesson.** A 403/451 is a fact about *this
machine's location*, recorded as **UNKNOWN-BLOCKED**, never as "the venue
does not serve this".

---

## THE MOAT TEST — run first, because it decides everything else

Binance Vision zeroed the moat on funding: the venue archives it publicly
back to 2020, so forward collection added nothing. **The same test on
positioning data:**

| prefix | keys | prefixes |
|---|---|---|
| `data/futures/um/monthly/metrics/` | **0** | **0** |
| `data/futures/um/monthly/metrics/BTCUSDT/` | **0** | **0** |

**Binance Vision does NOT archive positioning metrics.** The precedent that
killed the funding moat does not apply to anything below. Every rolling-window
positioning series probed here is genuinely ephemeral, and an archive of it
becomes the sole copy.

---

## a–e per candidate

### 1. Binance.US spot — `api.binance.us`

| endpoint | verdict | serves | history |
|---|---|---|---|
| `/api/v3/depth` limit=100 | **OK** | 100 bid/ask levels, 6.8 KB | **current-only** |
| `/api/v3/depth` limit=1000 | **OK** | **only 144 levels returned**, 11.7 KB | current-only |
| `/api/v3/ticker/bookTicker` | **OK** | best bid/ask + sizes, 128 B | current-only |
| `/api/v3/aggTrades` | **OK** | last-N aggregated trades | rolling last-N |
| `fapi.binance.us` | **UNREACHABLE (DNS)** | — | — |

**Spot-only from here — there is no Binance.US futures API at all** (the
host does not resolve, which is a fact about the product, not the location).

**A liquidity caveat that matters:** asking for 1,000 levels returned
**144**. The BTCUSD book on Binance.US is thin, so depth/imbalance features
built here describe a venue with poor liquidity rather than the market.

- **Auth:** none. **Cost:** ~7 KB/snapshot. Hourly × 3 symbols = **72 req/day,
  ~0.5 MB/day**; × 26 = 624 req/day, ~4.4 MB/day.

### 2. Kraken Futures — `futures.kraken.com`

| endpoint | verdict | serves | history |
|---|---|---|---|
| `/tickers` | **OK** | **294 instruments in ONE call**, 157 KB | **current-only** |
| `/orderbook` | **OK** | full ladder one symbol, 44 KB | current-only |
| `/instruments` | **OK** | contract specs, 942 KB | static |
| `/history` | **OK** | recent trades | rolling last-N |

**`/tickers` is the find.** One unauthenticated call returns, per instrument:
`openInterest`, `markPrice`, `indexPrice`, `fundingRate`,
`fundingRatePrediction`, `bid`/`ask`/`bidSize`/`askSize`, `vol24h`,
`volumeQuote`, `vwap24h`, `open24h`/`high24h`/`low24h`.

We already collect this venue's funding and have been **discarding OI, mark
and index on every call.**

- **Auth:** none. **Cost:** **1 request** covers BTC/ETH/SOL *and* all 294
  instruments. Hourly = **24 req/day, 3.8 MB/day**; daily = 1 req, 157 KB/day.

### 3. OKX positioning — `www.okx.com/api/v5`

| endpoint | verdict | rows | window measured | history |
|---|---|---|---|---|
| `rubik/stat/contracts/long-short-account-ratio` | **OK** | 180 | **2026-03-05 → 2026-08-31 (179 d)** | **180-day ROLLING** |
| `rubik/stat/taker-volume` | **OK** | 180 | same 179 d | 180-day rolling |
| `rubik/stat/contracts/open-interest-volume` | **OK** | 180 | same 179 d | 180-day rolling |
| `rubik/stat/taker-volume-contract` | **OK** | 100 | — | rolling |
| `rubik/stat/option/open-interest-volume-ratio` | **OK** | 72 | **2026-06-21 → 2026-08-31 (71 d)** | **~72-day ROLLING** |
| `public/liquidation-orders` | **OK** | 1,233 details | **~24 HOURS** | **24h rolling** |
| `public/opt-summary` | **OK** | 1,358 options, 855 KB | — | current-only |

**History discrimination, tested explicitly:** passing `after=1600000000000`
(2020) returns the same 180 rows; passing `begin=1600000000000` returns
**0 rows**. The window is a hard 180 days and **cannot be backfilled**.

**Everything before the rolling edge is permanently unrecoverable** — the
Kraken-funding situation, but with a 180-day window instead of 365, so the
loss rate is *twice as fast*.

- **Auth:** none. **Cost:** 4 endpoints × 3 ccy = **12 req/day, ~0.1 MB/day**
  at daily cadence (sufficient: 1D granularity, 180-day window).
  Liquidations need ≥daily (24h window): +3 req/day, ~0.5 MB/day.

### 4. Coinbase Exchange — `api.exchange.coinbase.com`

| endpoint | verdict | serves | history |
|---|---|---|---|
| `/products/BTC-USD/book?level=2` | **OK** | **22,356 levels, 1.3 MB** | current-only |
| `/products/BTC-USD/book?level=3` | **OK** | **63,844 orders, 7.1 MB** | current-only |
| `/products/BTC-USD/trades` | **OK** | last 1,000 trades, 130 KB | rolling last-N |
| `/products/BTC-USD/stats` | **OK** | 24h OHLCV, 210 B | current-only |

Deep, real liquidity — the opposite of Binance.US's 144 levels. **And
correspondingly expensive:** hourly L2 × 3 symbols = **72 req/day but
~93 MB/day**; L3 would be ~512 MB/day.

- **Auth:** none.

### 5. Deribit options — `www.deribit.com/api/v2/public`

| endpoint | verdict | serves | history |
|---|---|---|---|
| `get_book_summary_by_currency` (option) | **OK** | **978 live options**, IV/OI/greeks, 476 KB | current-only |
| `get_historical_volatility` | **OK** | 384 pts, **2026-08-16 → 2026-09-01 (15.9 d, hourly)** | **~16-day ROLLING** |
| `get_index_price` | **OK** | index, 179 B | current-only |
| `get_instruments` | **OK** | 978 contracts, 920 KB | static |

**Reachable from the US** — worth stating, since Deribit is often assumed
blocked. Options positioning is a genuinely different information class from
anything this project holds: IV surface, put/call OI, term structure.

**`get_historical_volatility` has a ~16-day window** — the shortest rolling
window found, and therefore the highest per-day loss rate.

- **Auth:** none. **Cost:** book summary daily × BTC+ETH = **2 req/day,
  ~1 MB/day**; hist-vol +2 req/day, ~30 KB.

### 6. CME crypto futures

| route | verdict | note |
|---|---|---|
| `cmegroup.com/CmeWS/...` widget | **UNREACHABLE (network)** | unofficial, not a stable route |
| **yfinance `BTC=F`** | **OK** | CME front-month daily OHLC |

**Free CME access exists only through an already-archived route.** yfinance
serves `BTC=F` history on demand, so **moat = 0**: nothing is lost by not
collecting it, and it can be pulled the day a hypothesis needs it.

---

## 8. Rolling-window endpoints — where forward collection has maximal value

Flagged specifically, ordered by how fast data is destroyed:

| endpoint | window | data lost per day of not collecting |
|---|---|---|
| **OKX liquidations** | **~24 hours** | a full day, immediately |
| **Deribit historical volatility** | **~16 days** | 1/16 of the archive |
| **OKX option put/call OI ratio** | **~72 days** | 1/72 |
| **OKX long-short / taker / OI-volume** | **~180 days** | 1/180 |
| Kraken funding *(already collected)* | ~365 days | 1/365 |
| **All current-only snapshots** (Kraken tickers, all books, Deribit summary) | **zero** | **everything not sampled is gone** |

Current-only snapshots are the extreme case: there is no window at all, so
the sampling cadence *is* the dataset.

---

## Scoring

**MOAT** — ephemeral/rolling = high, publicly archived = zero.
**COST** — requests + bytes/day for BTC/ETH/SOL at the stated cadence.
**MECHANISM** — the positioning/flow phenomenon measured. No hypothesis.
**TIME-TO-TESTABLE** — months of collection before a #172-style program can
run at 6 lockbox + 4 burn-in + 12 usable = **22 months**.

| rank | candidate | MOAT | COST (3 symbols) | MECHANISM | TTT |
|---|---|---|---|---|---|
| **1** | **OKX rubik positioning suite** | **HIGH** — 180d/72d rolling, not archived anywhere found | **12 req/day, ~0.1 MB/day** | Crowd positioning imbalance and taker aggression: who is long vs short, and which side is lifting | **22 mo** |
| **2** | **Kraken Futures `/tickers`** | **HIGH** — current-only, nothing archived | **1 req/day** (24 hourly), 0.16–3.8 MB/day | Open interest change = position building vs unwinding; mark−index = basis, the cost of leveraged exposure | **22 mo** |
| **3** | Deribit options | **HIGH** — 16d rolling + current-only | 4 req/day, ~1 MB/day | Options positioning: IV level/skew and put/call OI = hedging demand and tail pricing | 22 mo |
| **4** | OKX liquidations | **VERY HIGH** — 24h window | 3 req/day, ~0.5 MB/day | Forced deleveraging: where leverage actually broke | 22 mo, but lumpy — see caveat |
| **5** | Coinbase book | HIGH — current-only | 72 req/day, **~93 MB/day** hourly L2 | Resting-liquidity imbalance on a deep venue | 22 mo |
| **6** | Binance.US depth | HIGH — current-only | 72 req/day, ~0.5 MB/day | Same class as 5, **but the book is thin (144 levels)** | 22 mo |
| **7** | CME basis | **ZERO** — yfinance archives it | 0 — pull on demand | Institutional futures basis vs spot | **available now** |
| **8** | Binance.US futures | n/a | n/a | **does not exist** | n/a |

### Why 1 and 2 rank above 3–6

**Cost per unit of moat.** #1 destroys 1/180 of an unrecoverable series every
day it is not collected, for **12 requests and 0.1 MB**. #5 costs ~900× the
bytes for a phenomenon (book imbalance) that is also the most microstructural
— the least likely to survive the project's daily-bar, 15-day-hold geometry.

**#2 is nearly free and we are already there.** The collector calls Kraken
Futures daily and discards `openInterest`, `markPrice` and `indexPrice` on
every call.

**#4's caveat, stated now:** liquidations are lumpy and zero-inflated. Under
the **overlay-unmeasurability law** and #220–#234's event-rate finding, a
sparse event series risks being unmeasurable by construction. It ranks 4th on
moat but carries the highest risk of producing no computable `ex_best`, and
any registration must clear the ≥30-trades-per-ticker-per-window precheck
from event counts alone.

---

## Draft registration skeletons — TOP TWO

Both are **DRAFT, NOT LOCKED, NOT REGISTERED.** Nothing runs. Nothing enters
the daily workflow.

**Both would inherit the strongest property this project can confer:
REGISTERED BEFORE THE DATA EXISTS.** Only #172–#186 currently holds it.
#220–#234 explicitly could not claim it, because its archive already existed
and had been looked at. These two would be registered against series whose
usable windows **do not yet exist anywhere** — OKX's beyond 180 days back,
Kraken's snapshot series at all — so tuning to the test set is impossible by
construction, not by discipline.

---

### DRAFT A — POSITIONING (OKX rubik suite)

> **DRAFT. Not locked, not registered, nothing collected.**

**Data.** OKX `rubik/stat` daily series, `ccy` ∈ {BTC, ETH, SOL}:
long-short account ratio, taker buy/sell volume, open-interest-volume, and
option put/call OI ratio. Collected daily, full 180-day window re-pulled and
**merge-deduped on (ccy, endpoint, timestamp) with existing rows winning** —
the idempotent contract already proven by `collect_derivs.py`.

**Trigger.** Runnable when the archive spans **≥ 22 months for all three
symbols**, measured as `max(timestamp) − min(timestamp)` per symbol.
22 = 6 lockbox + 4 burn-in + 12 usable. **Trigger is on measured span, not a
calendar date.** From a collection start of 2026-09, expected ~**2028-07**.

**Hypotheses — conventional definitions, constants fixed now, STANDALONE
ONLY.** Eight rules. Overlays are **excluded by the overlay-unmeasurability
law** (median 1 trade/ticker/window in #220–#234); admitting them would spend
Bonferroni budget on tests that cannot produce a result.

| # | rule | definition |
|---|---|---|
| P1 | crowded long | BUY when 30-day percentile rank of long/short account ratio is **≥ 90** *(contrarian)* |
| P2 | crowded short | BUY when that percentile rank is **≤ 10** |
| P3 | taker capitulation | BUY when 30-day percentile of taker **sell** share is **≥ 90** |
| P4 | OI unwind | BUY when 7-day change in open interest is **≤ −10%** |
| P5 | OI build | BUY when 7-day change in open interest is **≥ +10%** |
| P6 | ratio z-score | BUY when 30-day z-score of long/short ratio is **≤ −2.0** |
| P7 | put/call extreme | BUY when 30-day percentile of put/call OI ratio is **≥ 90** |
| P8 | divergence | BUY when OI rises ≥ 5% over 7 days **AND** long/short ratio falls (position building on the short side) |

**Fixed definitions:** percentile rank = `rolling(30).rank(pct=True)*100`
including today; z-score `ddof=0`; a day with a missing observation is
**excluded** from every rule and lookback and recorded; **long side only**.

**Adjudicating null — NAMED NOW:** **episode-matched placebo, 3,000 seeds**,
per the #167 construction. All four fidelity axes measured before any draw,
with the **axis-4 centre-vs-tail caveat** recorded beside any percentile
verdict. Alternate null family: time-rotation requires ≥48 months per window;
a 12-month usable window at C1 is **infeasible**, so it is reported as such
rather than substituted.

**Bonferroni.** 8 tests → alpha = 0.05/8 = 0.00625 → **99.375th percentile**.

**Pass conditions (both required):** `ex_best` > 0 on all three tickers
*(undefined = UNMEASURABLE, cannot pass)*, AND pooled `net_all` above the
adjusted placebo percentile. Single confirmation, no partial credit.

**Precheck required before lock:** demonstrate from **event counts alone**
that each rule clears **≥30 trades per ticker per window**.

---

### DRAFT B — OPEN INTEREST & BASIS (Kraken Futures `/tickers`)

> **DRAFT. Not locked, not registered, nothing collected.**

**Data.** One daily snapshot of `futures.kraken.com/derivatives/api/v3/tickers`,
retaining per instrument: `openInterest`, `markPrice`, `indexPrice`,
`fundingRatePrediction`, `bid`, `ask`, `vol24h`. Primary symbols
`PF_XBTUSD` / `PF_ETHUSD` / `PF_SOLUSD`. **One request covers all 294
instruments**, so the tradable-26 come free and are stored from day one even
though no rule below uses them.

**This series has NO window: it is current-only.** Whatever is not sampled is
gone. That is the moat and the risk in one sentence.

**Trigger.** ≥ 22 months of measured span for all three symbols. From a
collection start of 2026-09, expected ~**2028-07**.

**Hypotheses — six rules, standalone only, constants fixed now.**

| # | rule | definition |
|---|---|---|
| B1 | basis extreme low | BUY when 30-day percentile of `(mark − index)/index` is **≤ 10** |
| B2 | basis extreme high | BUY when that percentile is **≥ 90** *(contrarian)* |
| B3 | basis sign flip | BUY on the first day `(mark − index)` turns **> 0** after **≥ 5 consecutive days < 0** |
| B4 | OI unwind | BUY when 7-day change in `openInterest` is **≤ −10%** |
| B5 | OI + basis divergence | BUY when OI falls ≥ 5% over 7 days **AND** basis percentile ≤ 25 |
| B6 | predicted-funding extreme | BUY when 30-day percentile of `fundingRatePrediction` is **≤ 10** |

**Fixed definitions:** basis = `(markPrice − indexPrice)/indexPrice` from the
daily snapshot; percentile and z-score constructions identical to DRAFT A;
missing-snapshot days excluded and recorded; long side only.

**Adjudicating null — NAMED NOW:** episode-matched placebo, 3,000 seeds, four
axes measured first, axis-4 caveat attached. Time-rotation infeasible at
12 usable months; stated, not substituted.

**Bonferroni.** 6 tests → alpha = 0.05/6 = 0.00833 → **99.1667th percentile**.

**Pass conditions:** identical to DRAFT A. Same precheck requirement.

**Known weakness, recorded before collection:** a once-daily snapshot of a
continuous quantity is a **sample, not an average**. Snapshot time is fixed at
the collector's daily slot and any registration must state it, because
`openInterest` at 05:20 UTC is not the day's mean OI and must never be
described as one.

---

## Constraints honoured

- **Nothing entered the daily workflow.** `derivs-collect.yml` is untouched.
- **No collector code was written.** This probe is scratch; only this report
  is committed.
- **Nothing registered.** Both skeletons are marked DRAFT and neither has a
  hypothesis number.
- **Rate limits respected:** 350 ms between calls, 39 requests total against
  a 150 budget, $0.
