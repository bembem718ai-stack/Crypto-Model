# Paper facts — System & Data

Compiled 2026-09-01. Lookup only; every line cites its source file. No
number below is restated from prose — each was read from the file named.

---

## 1. Live path — tickers and tiers

| fact | value | source |
|---|---|---|
| Published tickers | `BTC`, `ETH`, `SOL` | `pipeline.py:924` (`DEFAULT_TICKERS`) |
| Frozen-export tickers | `BTC`, `ETH`, `SOL` | `export_data.py:46` (`TICKERS`) |
| Hourly workflow ticker | `BTC` only (`live_tools.py check BTC --log-all --confirm-days 2 --long-only`) | `.github/workflows/signal-check.yml:90` |
| Workflow cadence | hourly, `cron: '0 * * * *'`, plus cron-job.org calling `workflow_dispatch` | `.github/workflows/signal-check.yml:28`, `:4-8` |
| Shadow-basket universe | 26 tickers | `research/basket_tradable.txt` (26 lines) |

### Entry-decision tiers (`_decide_row`)

| tier | threshold | source |
|---|---|---|
| `STRONG_BUY` | score ≥ 75 | `signal_engines.py:1146` (`STRONG_BUY_THRESHOLD`) |
| `BUY` | score ≥ 60 | `signal_engines.py:1147` (`BUY_THRESHOLD`) |
| `WATCH` | score ≥ 45 | `signal_engines.py:1148` (`WATCH_THRESHOLD`) |
| `AVOID` | below 45 | `signal_engines.py:1464-1481` |
| extreme-fear override | `EXTREME_FEAR_MIN_SCORE = 80` | `signal_engines.py:1149` |

### Direction bars (`classify_direction`)

| bar | value | source |
|---|---|---|
| `strong_buy_bar` | 75 | `pipeline.py:401` |
| `buy_bar` | 60 | `pipeline.py:401` |
| `sell_bar` | 40 | `pipeline.py:402` |
| `strong_sell_bar` | 25 | `pipeline.py:402` |

### Published tiers

| fact | value | source |
|---|---|---|
| Tiers eligible for publication | `("BUY", "STRONG_BUY")` | `research/publish.py:51` (`PUBLISHED_TIERS`) |
| Long-only | `--long-only` on the live invocation | `.github/workflows/signal-check.yml:90` |

**NOTE — the published construction changed 2026-09-01.** Step 3 (indicator
blend) and the VIX extreme-fear regime were removed from the published path;
weights are now `PUBLISHED_WEIGHT_PATTERN = 1.0`,
`PUBLISHED_WEIGHT_INDICATORS = 0.0`, `PUBLISHED_USE_VIX_REGIME = False`.
Source: `pipeline.py` (`PUBLISHED_*` constants). The pre-change values
survive as `INCUMBENT_WEIGHT_PATTERN = 0.6`,
`INCUMBENT_WEIGHT_INDICATORS = 0.4`, `INCUMBENT_USE_VIX_REGIME = True`.
So `EXTREME_FEAR_MIN_SCORE` and the extreme-fear override above are **live
only in the incumbent shadow arm**, not in the published path.

---

## 2. Frozen datasets

### 2a. Core 4h + daily — `data/MANIFEST.json`

Written `2026-08-27 18:22:32` UTC; `binance_region: US`;
`rest_base: https://api.binance.us`; `klines_path: /api/v3/klines`;
`target_4h_bars: 20000`; `daily_period: max`.

| ticker | 4h bars | 4h span | 4h years | daily rows | daily span | daily years |
|---|---|---|---|---|---|---|
| BTC | 15,177 | 2019-09-23 08:00 → 2026-08-27 16:00 | 6.93 | 2,502 | 2019-10-16 → 2026-08-22 | 6.85 |
| ETH | 15,177 | 2019-09-23 08:00 → 2026-08-27 16:00 | 6.93 | 2,502 | 2019-10-16 → 2026-08-22 | 6.85 |
| SOL | 13,014 | 2020-09-18 12:00 → 2026-08-27 16:00 | 5.94 | 2,141 | 2020-10-11 → 2026-08-22 | 5.86 |

Direction mix (`data/MANIFEST.json`):

| ticker | WATCH | SELL | BUY | STRONG_SELL | STRONG_BUY |
|---|---|---|---|---|---|
| BTC | 1,021 | 798 | 395 | 258 | 30 |
| ETH | 1,035 | 804 | 382 | 260 | 21 |
| SOL | 877 | 656 | 387 | 213 | 8 |

### 2b. 1h — `data/MANIFEST_1h.json`

Written `2026-08-28 04:42:01` UTC; `interval: 1h`; `target_bars: 70000`;
`binance_region: US`.

| ticker | bars | span | years |
|---|---|---|---|
| BTC | 60,696 | 2019-09-23 08:00 → 2026-08-28 04:00 | 6.93 |
| ETH | 60,696 | 2019-09-23 08:00 → 2026-08-28 04:00 | 6.93 |
| SOL | 52,055 | 2020-09-18 13:00 → 2026-08-28 04:00 | 5.94 |

### 2c. Basket — `data/basket/MANIFEST.json`

Written `2026-08-27 18:33:47` UTC; `period: max`; `target_4h_bars: 20000`;
`min_daily_rows: 200`; `overlap_min_frac: 0.9`; `n_requested: 86`.
**86 tickers requested, 82 with `status: "ok"`.** Tradable subset used by
research is 26 (`research/basket_tradable.txt`).

### 2d. Equities — `data/equities/MANIFEST_equities.json`

`freeze_date: 2026-08-28`; `n_etfs: 21`; `failed: []`;
`adjustment: yfinance auto_adjust=True (splits AND dividends)`.
Requested: XLB XLE XLF XLI XLK XLP XLU XLV XLY SPY QQQ IWM EFA EEM TLT IEF
GLD DBC EWJ EWG EWU. Representative row: **XLB 6,963 rows,
1998-12-22 → 2026-08-28, 27.68 years,
`sha256 740663511626715f369a266411aa6b40284cc402d34668e7c568ff1cab051294`.**
**Per-ETF `sha256` is present for all 21.**

### 2e. Macro — `data/macro/MANIFEST_macro.json`

`frozen_at: 2026-09-01T16:05:52Z`; program `#251-#256 MACRO-OVERLAY`;
permanence: *"PERMANENT FREEZE — never re-pulled, never merged, never
revised for this program"*; excluded: `fear_and_greed`
(*"price-contaminated; built from price and volatility inputs"*).

| series | rows | span | span days | gaps | longest gap | missing days | source | sha256 |
|---|---|---|---|---|---|---|---|---|
| `stablecoin_supply` | 3,199 | 2017-11-29 → 2026-09-01 | 3,198 | 0 | 1 | 0 | `https://stablecoins.llama.fi/stablecoincharts/all` | `0a051a5e6f8f59143ab630950543f5193d7f9981ed2c8da9f111a6613f356103` |
| `dgs10` | 16,150 | 1962-01-02 → 2026-08-28 | 23,614 | 3,599 | 5 | 7,465 | `https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10` | `e25385403d61c34019e819ee33fb5e0ce22a6dba904f4ccf7e12c14184674a26` |

### 2f. Hashes for the core OHLC files

**SUPERSEDED 2026-09-02.** When this document was first compiled,
`data/MANIFEST.json`, `data/MANIFEST_1h.json` and
`data/basket/MANIFEST.json` recorded **no `sha256` field** — only the
equities and macro manifests carried hashes. **All three now record
hashes**, added 2026-09-02 with `hashed_at: "2026-09-02"` and
`hashed_at_freeze: false`, the latter marking them as computed AFTER the
freeze rather than at it. Provenance was verified via `git log`: no commit
touched any of the frozen files between its freeze commit (`acf2f59`,
`33e7333`, `b179ecc`) and the hashing.

Per-file keys are `sha256_bars` and `sha256_daily`, matching the
equities/macro pattern. 173 hashes total: 6 in `data/MANIFEST.json`, 3 in
`data/MANIFEST_1h.json`, 164 in `data/basket/MANIFEST.json` (82 `ok`
tickers × 2; a non-`ok` ticker carries none). Source:
`research/freeze_hash.py`, now the single implementation and called at
freeze time by every export script.

The values below were computed 2026-09-01 for this document and are
**identical to those now recorded in the manifests**:

| file | sha256 |
|---|---|
| `data/BTC_4h.csv` | `9d933a2e3449c50f97eaa3cdc2d25a12769ad97a48014f101381bbabd36dc01b` |
| `data/ETH_4h.csv` | `88b02417b79cd991eadb313b994b75bec377fa3f099f3269def9e91abf74cd42` |
| `data/SOL_4h.csv` | `23a5bbc412a5cff4ed189f780704d8810d221181ffb8e7b19ba187d5dc3300bc` |
| `data/BTC_merged.csv` | `32824b996bf7e03852608b542d3f898e517dfd1c28d084ce07284ff41ddf8fcb` |
| `data/ETH_merged.csv` | `d0a50276665e2fc0671dfe503c7992f909c54639d440966ba664221f1ec31a17` |
| `data/SOL_merged.csv` | `3944ce19a13de7175f654b860297983f24560a9f7ec645826fcf9ba3f39158b5` |
| `data/BTC_1h.csv` | `ae719f7133510051802b4b2e5f25b4a1417ab104104f0aa883c299dd3db97ee7` |
| `data/ETH_1h.csv` | `38a483bc5269a19c593981c9e9572d46e98ab09c5fdfa6962415c40842da52b5` |
| `data/SOL_1h.csv` | `5b8382a38a14350eaa74c66b15a39ed9cd81a9d3894885c47981da53530bfd14` |

---

## 3. Forward-collection archives

Collector: `research/collect_derivs.py`, cadence `cron: '20 5 * * *'`
(daily, ~05:20 UTC) — `.github/workflows/derivs-collect.yml:27`.
`binance_funding` is a separate static backfill
(`research/collect_binance_vision.py`), not on that cron.

Row counts and spans read from the CSVs on 2026-09-01.

| archive | source endpoint | cadence | rows | symbols | span | obs. days | rolling window |
|---|---|---|---|---|---|---|---|
| `kraken_funding` | `https://futures.kraken.com/derivatives/api/v4/…` (`collect_derivs.py:151`) | daily 05:20 UTC | 26,623 | 3 | 2025-08-27 → 2026-09-01 | 371 | **~365-day rolling**; a missed day costs 1/365 of the archive (`collect_derivs.py:398`) |
| `kraken_tickers` | `https://futures.kraken.com/derivatives/api/v3/tickers` (`collect_derivs.py:224`) | daily 05:20 UTC | 294 | 294 | 2026-09-01 → 2026-09-01 | **1** | **CURRENT-ONLY snapshot**; a missed day costs *"the whole day — there is no window to recover it from"* (`collect_derivs.py:399`) |
| `okx_funding` | `https://www.okx.com/api/v5/public/funding-rate-history` (`collect_derivs.py:166`) | daily 05:20 UTC | 894 | 3 | 2026-05-25 → 2026-09-01 | 100 | **~90-day rolling**; 1/90 per missed day (`collect_derivs.py:400`) |
| `okx_oi` | `https://www.okx.com/api/v5/rubik/stat` (`collect_derivs.py:260`) | daily 05:20 UTC | 552 | 3 | 2026-03-01 → 2026-08-31 | 184 | **~180-day rolling**; 1/180 per missed day (`collect_derivs.py:401`) |
| `okx_rubik` | `https://www.okx.com/api/v5/rubik/stat/contracts/…` (`collect_derivs.py:190`) | daily 05:20 UTC | 540 | 3 | 2026-03-05 → 2026-08-31 | 180 | **~180-day rolling**; 1/180 per missed day (`collect_derivs.py:402`) |
| `deribit_options` | `https://www.deribit.com/api/v2/public` (`collect_derivs.py:319`) | daily 05:20 UTC | 1,175 | 5 | 2026-08-16 → 2026-09-01 | 17 | **CURRENT-ONLY chain + ~16-day rolling hist-vol**; a missed day costs *"the whole day of chain data, and 1/16 of the hist-vol series"* (`collect_derivs.py:403-404`) |

`SOURCE_WINDOWS` table: `research/collect_derivs.py:397-405`.

### Seventh file — static backfill, not one of the six collected sources

| archive | source | rows | symbols | span | window |
|---|---|---|---|---|---|
| `binance_funding` | `https://s3-ap-northeast-1.amazonaws.com/data.binance.vision` / `https://data.binance.vision/`, prefix `data/futures/um/monthly/fundingRate/%s/` (`collect_binance_vision.py:69-71`) | 21,220 | 3 (`BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `collect_binance_vision.py:72`) | 2020-01-01 → 2026-08-31 | static monthly archive — no rolling window |

### `deribit_options` symbol composition

`DERIBIT_OPT_CCYS = ["BTC", "ETH"]` — *"SOL has no options"*;
`DERIBIT_HV_CCYS = ["BTC", "ETH", "SOL"]` (`collect_derivs.py:320-321`).
5 symbols = `BTC-OPTIONS`, `ETH-OPTIONS`, `BTC-HISTVOL`, `ETH-HISTVOL`,
`SOL-HISTVOL`.

---

## 4. Lockbox

| fact | value | source |
|---|---|---|
| Length | `LOCKBOX_MONTHS = 6` | `pipeline.py:2205` |
| Definition (live) | *"the most recent LOCKBOX_MONTHS of data are sealed"*; cuts at `Timestamp.now() - 6 months` | `pipeline.py:2191`, `pipeline.py:2208` (`apply_lockbox`) |
| Definition (research) | anchored on the **dataset's last date, never the wall clock** — *"which would make results drift with the calendar and be unreproducible from a frozen dataset. Same 6-month rule (pipeline.LOCKBOX_MONTHS), different anchor."* | `research/harness.py:158-173` (`make_windows`) |
| Construction | `lockbox_start = last - pd.DateOffset(months=6)`; `avail = daily[daily.index < lockbox_start]` | `research/harness.py:166-167` |
| Discovery/confirmation split | `DISCOVERY_FRAC = 0.55`, split **in time**: `cut = start + (end - start) * 0.55` | `research/harness.py:114`, `:169` |
| Enforcement | `seal_bars` raises `ValueError("refusing to score the lockbox window")` | `research/harness.py:194-195` |
| Window tuple | `Windows(discovery, confirmation, lockbox, last_date)` | `research/harness.py:116` |

Computed windows (BTC daily frame, `research/harness.py make_windows`):

| window | span | months |
|---|---|---|
| DISCOVERY | 2019-09-24 → 2023-04-06 | 42.4 |
| CONFIRMATION | 2023-04-06 → 2026-02-26 | 34.7 |
| LOCKBOX | 2026-02-26 → 2026-08-26 | 5.9 |
| `last_date` | 2026-08-26 | — |

---

## 5. Test suite

| fact | value | source |
|---|---|---|
| Tests collected | **613** | `pytest test_signals.py --collect-only`, 2026-09-01 |
| Tests passing | **612 passed, 1 skipped** | `pytest test_signals.py`, 2026-09-01 |
| Skipped test | live network smoke test, gated on `RUN_LIVE=1` | `test_signals.py` (`TestLiveSmoke`, `@pytest.mark.skipif`) |
| Stated in project context | *"612 tests covering all decision logic"* | `CLAUDE.md:42` |

Discrepancy note: 613 collected vs 612 passed — the difference is the one
skipped `RUN_LIVE` test.

---

## 6. Registered programs and hypotheses

| fact | value | source |
|---|---|---|
| Highest hypothesis number | **#257** | `docs/cleanroom.md` (`# REGISTRATION — THE PREMIA INSTRUMENT (#257)`, line 6745) |
| Stated registered-hypothesis count | **249** | `README.md:17` — *"registered hypotheses \| **249**, each written to `docs/cleanroom.md` **before it ran**"* |
| `#250` | **never drawn** | `docs/cleanroom.md:5954` — *"## DISPOSITION: no #250 is drawn from this map"* |
| Program-level section headers | **19** | `docs/cleanroom.md`, grep `^# (PRE-)?REGISTRATION|^# CLOSE-OUT|^# CONSTITUTIONAL|^# PROGRAM` |

**Reconciliation, stated rather than asserted:** `README.md`'s 249 was
written when #249 was the highest number. Since then `#251`–`#256`
(MACRO-OVERLAY) and `#257` (PREMIA INSTRUMENT) were registered, and `#250`
was never drawn. **249 + 6 + 1 = 256 registered hypotheses as of
2026-09-01**, with the highest number being #257. `README.md:17` is
therefore stale by 7.

### Program sections in `docs/cleanroom.md`

| line | section |
|---|---|
| 480 | `# PROGRAM: EVENT RATE (basket)` |
| 1863 | `# PROGRAM CLOSE-OUT — 1h PROGRAM (#168-#170)` |
| 2136 | `# PRE-REGISTRATION — FUNDING PROGRAM (#172–#186)` |
| 3494 | `# CLOSE-OUT — THE ARCHITECTURAL SEARCH (#187–#203)` |
| 3746 | `# PRE-REGISTRATION — EQUITIES PROGRAM (#204–#216)` |
| 4399 | `# PRE-REGISTRATION — NULL-CALIBRATION PROGRAM (#217–#219)` |
| 4815 | `# PRE-REGISTRATION — BINANCE FUNDING PROGRAM (#220–#234)` |
| 5344 | `# CLOSE-OUT — BINANCE FUNDING (#220–#234)` |
| 5475 | `# PRE-REGISTRATION — POSITIONING (#235–#242) and OI/BASIS (#243–#248)` |
| 5614 | `# PROGRAM A — POSITIONING (#235–#242), OKX rubik` |
| 5706 | `# PROGRAM B — OPEN INTEREST & BASIS (#243–#248), Kraken tickers` |
| 5813 | `# PRE-REGISTRATION — MARKET-STRUCTURE MAP (#249)` |
| 5946 | `# CLOSE-OUT — MARKET-STRUCTURE MAP (#249)` |
| 6012 | `# REGISTRATION — SIMPLIFICATION & HARDENING PASS` |
| 6152 | `# PRE-REGISTRATION — MACRO-OVERLAY PROGRAM (#251–#256)` |
| 6473 | `# CLOSE-OUT — MACRO-OVERLAY (#251–#256)` |
| 6612 | `# CONSTITUTIONAL AMENDMENT — THE PAYER CLAUSE` |
| 6745 | `# REGISTRATION — THE PREMIA INSTRUMENT (#257)` |
| 6974 | `# CLOSE-OUT — THE PAYER CLAUSE AND THE PREMIA INSTRUMENT (#257)` |

`docs/cleanroom.md` is 7,156 lines as of 2026-09-01.
