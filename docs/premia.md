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
- The spread below is IMPLIED minus TRAILING realised, in VOL POINTS (annualised percentage points), not variance points. The two nearly coincide at BTC's current level -- iv^2-rv^2 = (iv+rv)(iv-rv) and (iv+rv) is about 0.97 near 48% vol -- so a maintainer who swapped them would see a 3% discrepancy on BTC and a 30% one on ETH. The unit is therefore named on the column, never left bare.
- Deribit's realised series is described everywhere in this repo as a ~16-day window. MEASURED against the chain it is about 356h (~14.8d) with a +/-20h band, so it is labelled ~15d here. The distinction is operational rather than cosmetic: it sets the forward shift once a genuine VRP becomes computable, and shifting by more than the true window inserts a dead gap while shifting by less puts already-realised returns inside the 'subsequent' leg.
- It is a contemporaneous spread, NOT a variance risk premium, and carries no uncertainty at N=1.

What *is* available today — **implied vs TRAILING realised**, which is a contemporaneous spread and **not a risk premium**:

| ccy | as of | OI-wtd mark IV | trailing RV (~15d) | spread | options in chain | put/call OI | label |
|---|---|---|---|---|---|---|---|
| BTC | 2026-09-01 | +47.69% | +49.09% | -1.40% | 978 | 0.564 | **RAW SAMPLE (N=1)** |
| ETH | 2026-09-01 | +62.79% | +67.45% | -4.66% | 838 | 0.542 | **RAW SAMPLE (N=1)** |

### (b) Perp carry yield — funding, annualised

| venue | symbol | mean ann. | median ann. | 95% CI | n | span | interval |
|---|---|---|---|---|---|---|---|
| Binance* | ETHUSDT | +13.95% | +10.95% | [+9.94%, +18.52%] | 7305 | 2020-01-01 -> 2026-08-31 | intervals [8] |
| Binance* | BTCUSDT | +11.80% | +10.16% | [+8.60%, +15.24%] | 7305 | 2020-01-01 -> 2026-08-31 | intervals [8] |
| Binance* | SOLUSDT | +0.17% | +9.50% | [-11.92%, +9.66%] | 6610 | 2020-09-13 -> 2026-08-31 | intervals [2, 4, 8] |
| Kraken | PF_XBTUSD | +3.39% | +3.37% | [+0.94%, +4.90%] | 8874 | 2025-08-27 -> 2026-09-01 | spacing 1h |
| Kraken | PF_ETHUSD | +3.15% | +3.21% | [+1.24%, +4.04%] | 8874 | 2025-08-27 -> 2026-09-01 | spacing 1h |
| Kraken | PF_SOLUSD | -0.16% | +1.00% | [-3.30%, +1.57%] | 8875 | 2025-08-27 -> 2026-09-01 | spacing 1h |
| OKX | BTC-USDT-SWAP | +4.42% | +4.69% | [+2.02%, +5.62%] | 298 | 2026-05-25 -> 2026-09-01 | spacing 8h |
| OKX | ETH-USDT-SWAP | +3.00% | +3.04% | [+0.50%, +3.88%] | 298 | 2026-05-25 -> 2026-09-01 | spacing 8h |
| OKX | SOL-USDT-SWAP | +1.78% | +2.65% | [-0.59%, +3.87%] | 298 | 2026-05-25 -> 2026-09-01 | spacing 8h |

\* Binance is the PRIMARY series (deepest archive). Kraken and OKX are shown beside it, not pooled with it — two feeds of the same quantity correlate at 0.37–0.72 (#220–#234), so one is not a proxy for another.

**THE SPANS DIFFER, so these rows are NOT a venue comparison.** Binance reaches back to 2020 and Kraken about a year; a lower Kraken number is mostly a different era, not a cheaper venue. Only same-span rows may be read against each other.

- TIME-WEIGHTED: total funding paid over total time elapsed (8760 x sum(rate) / sum(interval_hours)), not a mean of per-row annualised rates. Under mixed intervals a row-mean over-weights the short rows -- it put SOLUSDT's six-year carry at -12.98%/yr against a time-weighted +0.17%/yr, while agreeing to 0.000pp on the all-8h BTC and ETH.
- Arithmetic annualisation, not compounded: funding is paid out per interval and not reinvested.
- Binance interval is taken PER ROW from funding_interval_hours; SOL carries 2h and 4h episodes where a flat 3x/day would overstate by 4x and 2x.
- Kraken uses relative_funding_rate (the FRACTIONAL rate); its funding_rate column is in price units and would misstate carry by roughly the index price.
- CIs are moving-block bootstrap, 30-day blocks, 2000 draws. Funding regimes persist for weeks; an iid bootstrap would report an interval several times too narrow.

### (c) Basis — Kraken dated futures, ~05:20 UTC snapshot

| instrument | expiry | days | premium | annualised | OI | 24h vol | label |
|---|---|---|---|---|---|---|---|
| FF_ETHUSD_260904 | 2026-09-04 | 3 | +0.044% | +5.41% | 88.01 ETH | 136.5 ETH | **RAW SAMPLE** |
| FF_ETHUSD_260925 | 2026-09-25 | 24 | +0.308% | +4.68% | 120 ETH | 64.56 ETH | **RAW SAMPLE** |
| FF_ETHUSD_261225 | 2026-12-25 | 115 | +0.696% | +2.21% | 126.5 ETH | 0.014 ETH | **RAW SAMPLE** |
| FF_SOLUSD_260925 | 2026-09-25 | 24 | -1.100% | -16.73% | 4234 SOL | 0.11 SOL | **RAW SAMPLE** |
| FF_SOLUSD_261225 | 2026-12-25 | 115 | +0.475% | +1.51% | 6.38 SOL | 0.12 SOL | **RAW SAMPLE** |
| FF_XBTUSD_260904 | 2026-09-04 | 3 | +0.022% | +2.63% | 0.4244 BTC | 9.858 BTC | **RAW SAMPLE** |
| FF_XBTUSD_260925 | 2026-09-25 | 24 | +0.243% | +3.69% | 17.78 BTC | 4.493 BTC | **RAW SAMPLE** |
| FF_XBTUSD_261225 | 2026-12-25 | 115 | +1.459% | +4.63% | 13.17 BTC | 0.3262 BTC | **RAW SAMPLE** |

Perpetuals, tracked universe — **un-annualised** mark-vs-index premium. A perpetual has no expiry, so a term rate is undefined; its term economics are the funding above.

| instrument | premium | OI | 24h vol | label |
|---|---|---|---|---|
| PF_XBTUSD | +0.0091% | 1977 BTC | 6615 BTC | **RAW SAMPLE** |
| PF_ETHUSD | +0.0133% | 2.732e+04 ETH | 5.984e+04 ETH | **RAW SAMPLE** |
| PF_SOLUSD | +0.0020% | 2.773e+05 SOL | 6.27e+05 SOL | **RAW SAMPLE** |

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
- Annualisation is ACT/365 simple on dated futures only. Perpetuals have no expiry, so their mark-index gap is reported UN-annualised. Annualising it by the funding interval instead would print PF_XBTUSD at +79.5%/yr, PF_ETHUSD +116.8%/yr and PF_SOLUSD +17.8%/yr -- and +17.8% is an utterly ordinary crypto basis that would be accepted without a second look. PROHIBITED.
- openInterest and vol24h are in DIFFERENT UNITS by prefix: PF_/FF_ (linear) in base units, PI_/FI_ (inverse) in $1 USD contracts. Every size cell carries its unit, and liveness is a unit-free sign test (> 0), never a threshold.
- markPrice and indexPrice are both quote-currency for all four prefixes, so mark/index-1 is dimensionless and prefix-safe. The index is taken FROM THE ROW: FF_/FI_ and PF_/PI_ carry slightly different index values (0.2-1.0 bps apart), and substituting one for the other moves a 3-day annualised basis by ~8% relative.
- 8 instrument(s) excluded as dead (no book; Kraken marks those AT index, which fabricates a 0.0000% basis).
