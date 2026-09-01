# Premia — what the market paid

**A DESCRIPTIVE INSTRUMENT (#257).** No hypotheses, no verdicts, no pass
rules. It measures risk premia from this project's own archives and
publishes them.

**THESE ARE NOT ALPHA AND NOT SIGNALS.** A risk premium is a fee for a
risk actually borne — crash risk, balance-sheet risk — not a mispricing.
**Nothing measured here is tradeable by this operator**, and nothing here
enters the published signal path. The instrument exists to measure what
professionals harvest, on data we manufacture ourselves.

**Every number carries an uncertainty interval or is explicitly labelled a
RAW SAMPLE** (the #249 rule). There is no third category.

Appended dated, newest last. Nothing here is ever revised.

## 2026-09-01

*Risk premia, measured from this project's own archives. **Not alpha, not signals, not tradeable by this operator.** Every number carries an interval or is labelled a RAW SAMPLE.*

### (a) Variance risk premium — BTC, ETH

> **STATUS: NOT COMPUTABLE.** A VRP compares implied vol at *t* with vol realised **after** *t*. The option-chain archive is too young for any observation to have a subsequent realisation.

- VRP needs implied at t vs realised AFTER t. The option-chain archive holds 1 distinct observation day(s) per currency, so no observation has a subsequent realisation yet.
- oi_weighted_mark_iv is OI-weighted across ALL strikes AND ALL expiries, so it has no single horizon to realise against. A true matched-horizon VRP additionally requires a per-expiry IV term structure the collector does not yet store.
- The spread below is IMPLIED minus TRAILING realised (Deribit's ~16-day backward-looking series). It is a contemporaneous spread, NOT a variance risk premium, and carries no uncertainty at N=1.

What *is* available today — **implied vs TRAILING realised**, which is a contemporaneous spread and **not a risk premium**:

| ccy | as of | OI-wtd mark IV | trailing 16d RV | spread | options in chain | put/call OI | label |
|---|---|---|---|---|---|---|---|
| BTC | 2026-09-01 | +47.69% | +49.09% | -1.40% | 978 | 0.564 | **RAW SAMPLE (N=1)** |
| ETH | 2026-09-01 | +62.79% | +67.45% | -4.66% | 838 | 0.542 | **RAW SAMPLE (N=1)** |

### (b) Perp carry yield — funding, annualised

| venue | symbol | mean ann. | median ann. | 95% CI | n | span | interval |
|---|---|---|---|---|---|---|---|
| Binance* | ETHUSDT | +13.95% | +10.95% | [+9.94%, +18.52%] | 7305 | 2020-01-01 -> 2026-08-31 | intervals [8] |
| Binance* | SOLUSDT | -12.98% | +9.50% | [-50.28%, +9.20%] | 6610 | 2020-09-13 -> 2026-08-31 | intervals [2, 4, 8] ⚠ mean driven by extremes |
| Binance* | BTCUSDT | +11.80% | +10.16% | [+8.60%, +15.24%] | 7305 | 2020-01-01 -> 2026-08-31 | intervals [8] |
| Kraken | PF_XBTUSD | +3.39% | +3.37% | [+0.94%, +4.90%] | 8874 | 2025-08-27 -> 2026-09-01 | spacing 1h |
| Kraken | PF_ETHUSD | +3.15% | +3.21% | [+1.24%, +4.04%] | 8874 | 2025-08-27 -> 2026-09-01 | spacing 1h |
| Kraken | PF_SOLUSD | -0.16% | +1.00% | [-3.30%, +1.57%] | 8875 | 2025-08-27 -> 2026-09-01 | spacing 1h |
| OKX | BTC-USDT-SWAP | +4.42% | +4.69% | [+2.02%, +5.62%] | 298 | 2026-05-25 -> 2026-09-01 | spacing 8h |
| OKX | ETH-USDT-SWAP | +3.00% | +3.04% | [+0.50%, +3.88%] | 298 | 2026-05-25 -> 2026-09-01 | spacing 8h |
| OKX | SOL-USDT-SWAP | +1.78% | +2.65% | [-0.59%, +3.87%] | 298 | 2026-05-25 -> 2026-09-01 | spacing 8h |

\* Binance is the PRIMARY series (deepest archive). Kraken and OKX are shown beside it, not pooled with it — two feeds of the same quantity correlate at 0.37–0.72 (#220–#234), so one is not a proxy for another.

**THE SPANS DIFFER, so these rows are NOT a venue comparison.** Binance reaches back to 2020 and Kraken about a year; a lower Kraken number is mostly a different era, not a cheaper venue. Only same-span rows may be read against each other.

- Arithmetic annualisation (rate x intervals/year), not compounded: funding is paid out per interval and not reinvested.
- Binance interval is taken PER ROW from funding_interval_hours; SOL carries 2h and 4h episodes where a flat 3x/day would overstate by 4x and 2x.
- Kraken uses relative_funding_rate (the FRACTIONAL rate); its funding_rate column is in price units and would misstate carry by roughly the index price.
- WHERE FLAGGED, THE MEAN IS DRIVEN BY A FEW EXTREME OBSERVATIONS AND THE MEDIAN IS THE ROBUST NUMBER. Annualising a short funding interval multiplies it hard: Binance's FTX-window SOL rows are 2-hourly and scale by 4,380 rather than 1,095, so a handful of days can move a six-year mean by tens of percent. Both are shown; neither is dropped.
- CIs are moving-block bootstrap, 30-day blocks, 2000 draws. Funding regimes persist for weeks; an iid bootstrap would report an interval several times too narrow.

### (c) Basis — Kraken dated futures, ~05:20 UTC snapshot

| instrument | expiry | days | premium | annualised | OI | 24h vol | label |
|---|---|---|---|---|---|---|---|
| FF_ETHUSD_260904 | 2026-09-04 | 3 | +0.044% | +5.41% | 88.01 | 136.5 | **RAW SAMPLE** |
| FF_ETHUSD_260925 | 2026-09-25 | 24 | +0.308% | +4.68% | 120 | 64.56 | **RAW SAMPLE** |
| FF_ETHUSD_261225 | 2026-12-25 | 115 | +0.696% | +2.21% | 126.5 | 0.014 | **RAW SAMPLE** |
| FF_SOLUSD_260925 | 2026-09-25 | 24 | -1.100% | -16.73% | 4234 | 0.11 | **RAW SAMPLE** |
| FF_SOLUSD_261225 | 2026-12-25 | 115 | +0.475% | +1.51% | 6.38 | 0.12 | **RAW SAMPLE** |
| FF_XBTUSD_260904 | 2026-09-04 | 3 | +0.022% | +2.63% | 0.4244 | 9.858 | **RAW SAMPLE** |
| FF_XBTUSD_260925 | 2026-09-25 | 24 | +0.243% | +3.69% | 17.78 | 4.493 | **RAW SAMPLE** |
| FF_XBTUSD_261225 | 2026-12-25 | 115 | +1.459% | +4.63% | 13.17 | 0.3262 | **RAW SAMPLE** |

Perpetuals, tracked universe — **un-annualised** mark-vs-index premium. A perpetual has no expiry, so a term rate is undefined; its term economics are the funding above.

| instrument | premium | OI | 24h vol | label |
|---|---|---|---|---|
| PF_XBTUSD | +0.0091% | 1977 | 6615 | **RAW SAMPLE** |
| PF_ETHUSD | +0.0133% | 2.732e+04 | 5.984e+04 | **RAW SAMPLE** |
| PF_SOLUSD | +0.0020% | 2.773e+05 | 6.27e+05 | **RAW SAMPLE** |

Across all 278 live perpetuals in the same snapshot the premium runs -0.111% (25th) / -0.022% (median) / +0.029% (75th), min -0.844%, max +1.000%. **The tails are illiquid alts, not a market-wide signal** — they are given as the cross-sectional shape, and this project has no other measurement of any of them.

**Excluded as dead, reported not dropped** — Kraken marks a bookless instrument AT index, fabricating a 0.0000% basis:

- `FI_ETHUSD_260925` (2026-09-25): no book: openInterest=0.0 vol24h=0.0, mark marked AT index
- `FI_ETHUSD_261225` (2026-12-25): no book: openInterest=0.0 vol24h=0.0, mark marked AT index
- `FI_LTCUSD_260925` (2026-09-25): no book: openInterest=0.0 vol24h=0.0, mark marked AT index
- `FI_LTCUSD_261225` (2026-12-25): no book: openInterest=0.0 vol24h=0.0, mark marked AT index
- `FI_XBTUSD_260925` (2026-09-25): no book: openInterest=0.0 vol24h=0.0, mark marked AT index
- `FI_XBTUSD_261225` (2026-12-25): no book: openInterest=0.0 vol24h=0.0, mark marked AT index
- `FI_XRPUSD_260925` (2026-09-25): no book: openInterest=0.0 vol24h=0.0, mark marked AT index
- `FI_XRPUSD_261225` (2026-12-25): no book: openInterest=0.0 vol24h=0.0, mark marked AT index

- SNAPSHOT LAW (#243-#248): a point sample at ~05:20 UTC, not a daily average. Observed 2026-09-01T02:41:53Z.
- The archive holds 1 distinct observation day(s), so every number here is a RAW SAMPLE with no uncertainty attached. It stays that way until the archive is deep enough to resample.
- Annualisation is ACT/365 simple on dated futures only. Perpetuals have no expiry, so their mark-index gap is reported UN-annualised.
- 8 instrument(s) excluded as dead (no book; Kraken marks those AT index, which fabricates a 0.0000% basis).
