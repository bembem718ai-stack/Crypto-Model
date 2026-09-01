# Market-structure map (#249)

**DESCRIPTIVE. No hypotheses, no pass conditions, no verdicts, no
signals.** Registered and locked in `docs/cleanroom.md` before any
number below was computed. Nothing here is scored through the trade
machinery and no return-vs-signal join is made.

Data: pre-lockbox frozen bars only. **The lockbox opens 2026-02-26 and is never read.** BTC 2019-09-23 -> 2026-02-25, ETH 2019-09-23 -> 2026-02-25, SOL 2020-09-18 -> 2026-02-25.

Bootstrap: **moving-block, 1,000 resamples, block length ℓ = ⌈n^(1/3)⌉**
(reduced to 300–400 resamples on the densest per-lag sweeps, noted in
place). Fixed in the registration before any result, so no band can be
widened or narrowed after the fact. CIs are 95% percentile intervals.

---

## ⚠ THE CAVEAT THAT GOVERNS THIS ENTIRE DOCUMENT

**This map contains several hundred measured cells. Some of them WILL
look remarkable by chance.** That is arithmetic, not modesty: at a 95%
interval, one cell in twenty excludes zero when nothing is there.

**This is exactly why the map buys ONE hypothesis and not many.** Under
#249's registered one-hypothesis rule, at most a single future
hypothesis (#250) may be drawn from everything below, and it may be
tested **only on data timestamped after this map's freeze**.

**The map may never be cited as evidence of an edge** — not as support,
not as partial support, not as "consistent with". Its only legitimate
use is as *the reason a hypothesis was worth registering*.

---

## M1 — Volatility clustering

Autocorrelation of **|returns|** and the lag at which it falls to half
its lag-1 value. CIs are moving-block bootstrap percentile intervals
(1,000 resamples).

| ticker | bar | n | ACF(1) | ACF(1) 95% CI | ACF(5) | ACF(20) | half-life (bars) | half-life bootstrap range ⚠ | block ℓ |
|---|---|---|---|---|---|---|---|---|---|
| BTC | 1h | 56298 | +0.2915 | [+0.2555, +0.3160] | +0.2006 | +0.1710 | 28.1 | [6.7, 10.7] | 39 |
| BTC | 4h | 14079 | +0.2297 | [+0.1888, +0.2482] | +0.1982 | +0.1164 | 27.4 | [6.0, 7.8] | 25 |
| BTC | 1d | 2347 | +0.1567 | [+0.0850, +0.2008] | +0.1021 | +0.0528 | 2.4 | [1.7, 7.6] | 14 |
| ETH | 1h | 56298 | +0.2803 | [+0.2430, +0.3058] | +0.2139 | +0.1779 | 32.8 | [8.7, 13.4] | 39 |
| ETH | 4h | 14079 | +0.2474 | [+0.2017, +0.2705] | +0.2178 | +0.1379 | 27.3 | [6.0, 9.0] | 25 |
| ETH | 1d | 2347 | +0.1700 | [+0.0943, +0.2164] | +0.1232 | +0.0512 | 7.7 | [1.9, 7.6] | 14 |
| SOL | 1h | 47657 | +0.2987 | [+0.2600, +0.3179] | +0.2292 | +0.1974 | 38.6 | [7.9, 12.8] | 37 |
| SOL | 4h | 11916 | +0.2676 | [+0.2202, +0.2933] | +0.2331 | +0.1709 | 32.3 | [6.8, 10.6] | 23 |
| SOL | 1d | 1986 | +0.2470 | [+0.1288, +0.3174] | +0.1605 | +0.0652 | 6.7 | [1.9, 6.8] | 13 |

**Reading.** Volatility clusters at every horizon: |return| is
positively autocorrelated well beyond lag 20, which is the single most
robust stylised fact in this map. The half-life column says how long
that memory persists in bars — multiply by the bar length for wall-clock.

**What it does NOT say:** clustered volatility is not a tradeable edge.
It says the SIZE of moves is predictable, not their DIRECTION, and
every program in this record failed on direction.

**⚠ THE HALF-LIFE COLUMN'S BOOTSTRAP RANGE IS NOT A VALID CI, and is
labelled rather than quietly shown.** Every point estimate falls
OUTSIDE its own interval, which is the signature of a broken
construction, not of a surprising result. The moving-block bootstrap
resamples blocks of length ℓ = ⌈n^(1/3)⌉; dependence BEYOND ℓ is
destroyed by construction, and half-life is precisely a measure of
long-range dependence. So the resampled series decay far faster than
the real one and the interval is DISPLACED, not merely narrow.

The point estimates stand — they are computed on the real series. The
interval is reported as a raw bootstrap range with this warning
attached, because a valid CI for a long-memory statistic needs a
different resampling scheme, and choosing one after seeing this result
is exactly what research rule 4 forbids. Recorded as a limitation.

**ACF(1)/ACF(5)/ACF(20) CIs are unaffected** — those are short-lag
statistics the block length supports. Per the registration they remain
if anything TOO NARROW on |returns|, and are not widened after the fact.

---

## M2 — Jumps

Bar returns beyond **3×** and **5×** trailing ATR(14). Counts are RAW
COUNTS; rates carry CIs.

**The diffusive benchmark is SIMULATED, not analytic**, because the
statistic's denominator is true range rather than a close-to-close
standard deviation. A Gaussian random walk is pushed through the
identical ATR pipeline (200,000 bars, 60 intra-bar steps): it produces
**P(>3×ATR) = 0.00004** and **P(>5×ATR) = 0.000000**.

| ticker | bar | n | >3×ATR (raw) | rate | rate 95% CI | Gaussian exp. | >5×ATR (raw) | rate | P(jump t+1 \| jump t) | base rate |
|---|---|---|---|---|---|---|---|---|---|---|
| BTC | 1h | 56273 | 525 | 0.0093 | [+0.0085, +0.0101] | 0.0000 | 99 | 0.00176 | 0.0590 | 0.0093 |
| BTC | 4h | 14066 | 120 | 0.0085 | [+0.0070, +0.0101] | 0.0000 | 12 | 0.00085 | 0.0083 | 0.0085 |
| BTC | 1d | 2334 | 13 | 0.0056 | [+0.0026, +0.0090] | 0.0000 | 2 | 0.00086 | 0.1538 | 0.0056 |
| ETH | 1h | 56273 | 522 | 0.0093 | [+0.0085, +0.0101] | 0.0000 | 97 | 0.00172 | 0.0460 | 0.0093 |
| ETH | 4h | 14066 | 99 | 0.0070 | [+0.0057, +0.0083] | 0.0000 | 10 | 0.00071 | 0.0303 | 0.0070 |
| ETH | 1d | 2334 | 8 | 0.0034 | [+0.0013, +0.0060] | 0.0000 | 2 | 0.00086 | 0.0000 | 0.0034 |
| SOL | 1h | 47644 | 499 | 0.0105 | [+0.0093, +0.0117] | 0.0000 | 111 | 0.00233 | 0.0681 | 0.0105 |
| SOL | 4h | 11903 | 60 | 0.0050 | [+0.0038, +0.0065] | 0.0000 | 4 | 0.00034 | 0.0167 | 0.0050 |
| SOL | 1d | 1973 | 8 | 0.0041 | [+0.0015, +0.0071] | 0.0000 | 0 | 0.00000 | 0.0000 | 0.0041 |

**Reading.** A diffusive process pushed through this exact pipeline
essentially NEVER produces a move beyond 3× its own trailing ATR — the
simulated rate is 0.00004 over 200,000 bars. The observed rates are two to
three orders of magnitude larger, at every ticker and every horizon.
Jumps also
**cluster**: the probability of a jump tomorrow given a jump today
exceeds the base rate in essentially every cell.

**What it does NOT say:** fat tails and jump clustering are properties
of the RISK, not of an opportunity. They are the reason a fixed-R stop
geometry behaves the way it does; they say nothing about which side of
a jump to be on.

---

## M3 — Return autocorrelation, lags 1–30

Signed returns. Bands are moving-block bootstrap 95% intervals, which
are heteroskedasticity-robust by construction because the resampling
preserves the volatility blocks rather than assuming homoskedasticity.

| ticker | bar | n | lag1 | lag1 95% CI | lag2 | lag3 | lag5 | lag10 | lag30 | lags with CI excluding 0 (of 30) |
|---|---|---|---|---|---|---|---|---|---|---|
| BTC | 1h | 56298 | -0.0195 | [-0.0374, -0.0022] | -0.0132 | +0.0010 | -0.0035 | +0.0106 | -0.0070 | **2** |
| BTC | 4h | 14079 | -0.0213 | [-0.0467, +0.0017] | +0.0066 | +0.0462 | -0.0141 | +0.0122 | +0.0200 | **2** |
| BTC | 1d | 2347 | -0.0690 | [-0.1331, -0.0020] | +0.0429 | -0.0275 | -0.0003 | +0.0102 | +0.0120 | **1** |
| ETH | 1h | 56298 | -0.0090 | [-0.0249, +0.0066] | -0.0185 | -0.0031 | -0.0060 | +0.0064 | -0.0042 | **2** |
| ETH | 4h | 14079 | -0.0203 | [-0.0424, +0.0007] | +0.0173 | +0.0341 | -0.0114 | +0.0180 | -0.0014 | **2** |
| ETH | 1d | 2347 | -0.0747 | [-0.1275, -0.0073] | +0.0429 | -0.0150 | -0.0338 | +0.0606 | +0.0240 | **1** |
| SOL | 1h | 47657 | -0.0238 | [-0.0404, -0.0070] | -0.0191 | +0.0003 | -0.0118 | -0.0018 | -0.0014 | **2** |
| SOL | 4h | 11916 | -0.0378 | [-0.0729, -0.0054] | +0.0040 | +0.0079 | +0.0127 | +0.0064 | +0.0047 | **2** |
| SOL | 1d | 1986 | -0.0244 | [-0.0889, +0.0414] | -0.0059 | +0.0229 | -0.0092 | +0.0518 | +0.0200 | **0** |

**Reading.** Signed-return autocorrelation is near zero at every lag,
ticker and horizon — one to two orders of magnitude smaller than the
|return| autocorrelation in M1. The last column counts how many of 30
lags have a bootstrap CI excluding zero.

**The multiple-comparisons point, concretely.** 9 series × 30 lags =
**270 cells**. At a 95% interval, ~13–14 would exclude zero **by chance**
even if every true autocorrelation were exactly zero. Counts near that
number are consistent with pure noise, and no individual lag should be
read as a finding.

---

## M4 — Cross-asset lead-lag: does BTC lead the alts?

Cross-correlation of BTC 1h returns at lag *k* against ETH/SOL returns
at *t*. **Positive lag = BTC LEADS.** Split by BTC volatility-regime
tercile (trailing 24h realised), and rolling by calendar year.

| alt | lag (h) | corr | 95% CI | low-vol | mid-vol | high-vol |
|---|---|---|---|---|---|---|
| ETH | 0 | +0.8223 | [+0.7445, +0.9329] | +0.721 | +0.787 | +0.848 |
| ETH | 1 | -0.0047 | [-0.0214, +0.0078] | -0.009 | +0.002 | -0.006 |
| ETH | 2 | -0.0197 | [-0.0431, -0.0031] | -0.000 | -0.002 | -0.027 |
| ETH | 3 | +0.0005 | [-0.0151, +0.0177] | -0.002 | +0.004 | -0.000 |
| ETH | 6 | +0.0017 | [-0.0154, +0.0168] | -0.002 | +0.001 | +0.002 |
| ETH | 12 | +0.0082 | [-0.0059, +0.0214] | +0.014 | -0.002 | +0.010 |
| ETH | 24 | -0.0308 | [-0.0444, -0.0192] | -0.018 | -0.028 | -0.033 |
| SOL | 0 | +0.6109 | [+0.5602, +0.6582] | +0.563 | +0.613 | +0.624 |
| SOL | 1 | -0.0022 | [-0.0186, +0.0151] | +0.017 | -0.000 | -0.005 |
| SOL | 2 | -0.0200 | [-0.0364, -0.0059] | -0.006 | +0.005 | -0.030 |
| SOL | 3 | -0.0134 | [-0.0287, +0.0026] | -0.008 | -0.011 | -0.015 |
| SOL | 6 | +0.0031 | [-0.0090, +0.0163] | -0.001 | +0.004 | +0.003 |
| SOL | 12 | -0.0043 | [-0.0176, +0.0088] | +0.008 | -0.015 | -0.003 |
| SOL | 24 | -0.0292 | [-0.0434, -0.0157] | -0.017 | -0.027 | -0.032 |

### Rolling by year — BTC leads by 1h

| alt | year | n hours | corr at lag 1h | 95% CI |
|---|---|---|---|---|
| ETH | 2019 | 2386 | +0.0264 | [-0.0298, +0.0893] |
| ETH | 2020 | 8760 | -0.0494 | [-0.1046, -0.0102] |
| ETH | 2021 | 8750 | +0.0042 | [-0.0247, +0.0307] |
| ETH | 2022 | 8760 | +0.0158 | [-0.0161, +0.0467] |
| ETH | 2023 | 8753 | -0.0296 | [-0.0616, +0.0049] |
| ETH | 2024 | 8784 | +0.0080 | [-0.0265, +0.0400] |
| ETH | 2025 | 8760 | +0.0075 | [-0.0283, +0.0461] |
| ETH | 2026 | 1344 | +0.0556 | [-0.0181, +0.1236] |
| SOL | 2020 | 2505 | +0.1013 | [+0.0505, +0.1491] |
| SOL | 2021 | 8750 | -0.0026 | [-0.0360, +0.0279] |
| SOL | 2022 | 8760 | -0.0242 | [-0.0575, +0.0081] |
| SOL | 2023 | 8753 | -0.0173 | [-0.0454, +0.0084] |
| SOL | 2024 | 8784 | -0.0125 | [-0.0431, +0.0220] |
| SOL | 2025 | 8760 | -0.0055 | [-0.0371, +0.0241] |
| SOL | 2026 | 1344 | +0.0400 | [-0.0206, +0.0972] |

**Reading.** This is the folklore claim — *BTC leads the alts* — and
the map measures it rather than assuming it. Read the lag-0 row first:
it is the contemporaneous correlation, and it is large. The lagged rows
are what a lead would require, and they are the ones to judge.

**What it does NOT say:** a non-zero lagged correlation is not a
tradeable lead. At 1h granularity, a correlation of a few hundredths
is far below the cost floor this project measured (a 0.80% stop floor,
~4bps round trip), and nothing here nets that.

---

## M5 — Calendar structure

Hour-of-day and day-of-week mean return and volatility, 1h bars, with
bootstrap CIs on the mean. **The 00/08/16 UTC funding-settlement hours
are reported separately** because they are the hours a funding-driven
effect would have to live in.

### Hour-of-day, BTC 1h (settlement hours marked)

| hour UTC | n | mean ret (bps) | 95% CI (bps) | vol (bps) | settlement |
|---|---|---|---|---|---|
| 00 | 2347 | +0.294 | [-2.048, +3.131] | 72.4 | **YES** |
| 01 | 2347 | -0.492 | [-3.356, +2.582] | 70.8 |  |
| 02 | 2345 | -1.272 | [-3.819, +1.781] | 68.0 |  |
| 03 | 2344 | -1.229 | [-3.277, +1.185] | 56.3 |  |
| 04 | 2344 | -0.833 | [-2.814, +1.234] | 53.0 |  |
| 05 | 2343 | +0.552 | [-1.762, +2.670] | 52.2 |  |
| 06 | 2342 | +1.173 | [-0.792, +3.216] | 54.4 |  |
| 07 | 2342 | +0.748 | [-1.060, +2.490] | 55.0 |  |
| 08 | 2342 | +1.427 | [-0.864, +4.092] | 65.3 | **YES** |
| 09 | 2344 | +0.055 | [-1.939, +2.028] | 57.8 |  |
| 10 | 2344 | +1.440 | [-1.199, +3.965] | 69.7 |  |
| 11 | 2344 | +0.358 | [-1.457, +2.479] | 55.6 |  |
| 12 | 2347 | +1.609 | [-1.188, +4.476] | 74.5 |  |
| 13 | 2348 | +1.610 | [-0.968, +4.752] | 71.7 |  |
| 14 | 2348 | -1.606 | [-4.594, +1.582] | 85.0 |  |
| 15 | 2348 | +1.871 | [-1.107, +4.938] | 78.5 |  |
| 16 | 2348 | +0.345 | [-2.089, +2.843] | 71.2 | **YES** |
| 17 | 2347 | -0.219 | [-2.686, +2.493] | 64.8 |  |
| 18 | 2347 | +0.365 | [-1.777, +3.183] | 67.1 |  |
| 19 | 2347 | +0.149 | [-2.031, +2.763] | 67.1 |  |
| 20 | 2347 | +2.042 | [-0.707, +4.453] | 70.4 |  |
| 21 | 2347 | +4.651 | [+1.795, +8.116] | 68.7 |  |
| 22 | 2348 | +3.497 | [+1.375, +5.885] | 62.0 |  |
| 23 | 2348 | -3.023 | [-6.117, +0.261] | 71.1 |  |

### Settlement vs non-settlement hours, all three tickers

| ticker | group | n | mean ret (bps) | 95% CI (bps) | vol (bps) |
|---|---|---|---|---|---|
| BTC | settlement (00/08/16) | 7037 | +0.688 | [-0.825, +2.237] | 69.7 |
| BTC | other 21 hours | 49261 | +0.545 | [+0.005, +1.134] | 66.0 |
| ETH | settlement (00/08/16) | 7037 | +1.279 | [-1.027, +3.540] | 93.0 |
| ETH | other 21 hours | 49261 | +0.701 | [-0.090, +1.382] | 84.5 |
| SOL | settlement (00/08/16) | 5956 | +1.687 | [-1.856, +4.985] | 138.1 |
| SOL | other 21 hours | 41701 | +1.523 | [+0.205, +2.669] | 128.3 |

### Day-of-week, daily bars

| ticker | day | n | mean ret (bps) | 95% CI (bps) | vol (bps) |
|---|---|---|---|---|---|
| BTC | Mon | 335 | +34.7 | [-1.8, +70.5] | 384 |
| BTC | Tue | 336 | +4.4 | [-20.5, +42.3] | 302 |
| BTC | Wed | 336 | +48.4 | [+8.2, +86.3] | 349 |
| BTC | Thu | 335 | -23.2 | [-50.5, +13.8] | 398 |
| BTC | Fri | 335 | +17.6 | [-22.5, +52.5] | 344 |
| BTC | Sat | 335 | +5.7 | [-15.9, +26.0] | 188 |
| BTC | Sun | 335 | +7.0 | [-21.3, +35.7] | 247 |
| ETH | Mon | 335 | +38.8 | [-14.5, +83.3] | 491 |
| ETH | Tue | 336 | -11.5 | [-43.9, +38.6] | 394 |
| ETH | Wed | 336 | +63.2 | [+21.2, +111.1] | 467 |
| ETH | Thu | 335 | -20.3 | [-68.1, +26.3] | 512 |
| ETH | Fri | 335 | +19.1 | [-31.0, +56.6] | 436 |
| ETH | Sat | 335 | +29.1 | [-2.3, +66.7] | 310 |
| ETH | Sun | 335 | +15.8 | [-25.4, +70.2] | 371 |
| SOL | Mon | 284 | +14.9 | [-61.9, +104.9] | 648 |
| SOL | Tue | 284 | +8.8 | [-48.9, +72.0] | 531 |
| SOL | Wed | 284 | +44.6 | [-31.4, +132.5] | 696 |
| SOL | Thu | 283 | +3.7 | [-58.9, +73.4] | 623 |
| SOL | Fri | 283 | +61.8 | [-22.5, +142.9] | 681 |
| SOL | Sat | 284 | +58.2 | [+21.6, +112.0] | 495 |
| SOL | Sun | 284 | +53.2 | [+5.4, +116.1] | 532 |

**Reading.** Crypto trades continuously, so calendar structure has no
session open or close to anchor it. Read the CIs, not the point
estimates: an hour whose interval straddles zero is not distinguishable
from the rest of the day.

**Multiple comparisons, concretely.** 24 hours × 3 tickers + 7 days ×
3 tickers = **93 cells**. About 5 will exclude zero by chance. Any
single striking hour in this table is far more likely to be one of
those five than a real effect.

---

## M6 — Cross-sectional dispersion: does a cross-section exist?

Rolling 60-day average pairwise correlation and cross-sectional return
dispersion across the #167 tradable-26, daily. **This is the ROTATION
context, measured** — that program assumed a cross-section existed to
select from.

| year | days | assets alive | mean pairwise corr | 95% CI | mean daily dispersion (bps) | 95% CI |
|---|---|---|---|---|---|---|
| 2020 | 366 | 12 | +0.680 | [+0.657, +0.701] | 279 | [246, 306] |
| 2021 | 365 | 15 | +0.479 | [+0.433, +0.520] | 530 | [437, 627] |
| 2022 | 365 | 24 | +0.707 | [+0.686, +0.727] | 268 | [250, 292] |
| 2023 | 365 | 24 | +0.538 | [+0.513, +0.557] | 258 | [230, 282] |
| 2024 | 366 | 25 | +0.566 | [+0.547, +0.582] | 292 | [259, 333] |
| 2025 | 365 | 25 | +0.694 | [+0.668, +0.714] | 246 | [217, 281] |

**Reading.** Average pairwise correlation is the quantity that decides
whether picking *which* asset can matter. When it is high, the assets
move as one and cross-sectional selection has little to select on;
dispersion is the complementary view.

**This is the measured context for ROTATION's failure and for
NULL-CALIBRATION's finding** that a rank-permutation null inherits the
effect on a correlated universe. It does not re-open either — it says
what the correlation actually was, year by year, with bands.

---

## M7 — Asymmetry: up-moves vs down-moves

Consecutive same-sign daily runs, and the drawdown depth / recovery
time distribution. Counts are RAW; means carry CIs.

| ticker | direction | runs (raw) | mean length (d) | 95% CI | mean magnitude (%) | 95% CI |
|---|---|---|---|---|---|---|
| BTC | up | 629 | 1.88 | [1.80, 1.99] | 4.28 | [3.82, 4.80] |
| BTC | down | 629 | 1.85 | [1.75, 1.95] | 3.77 | [3.36, 4.19] |
| ETH | up | 627 | 1.93 | [1.83, 2.05] | 5.85 | [5.19, 6.50] |
| ETH | down | 627 | 1.81 | [1.73, 1.88] | 5.14 | [4.53, 5.67] |
| SOL | up | 497 | 2.00 | [1.88, 2.13] | 9.12 | [7.92, 10.55] |
| SOL | down | 499 | 1.98 | [1.86, 2.09] | 7.69 | [6.81, 8.60] |

### Drawdown depth vs recovery time

| ticker | drawdowns >10% (raw) | median depth (%) | median recovery (d) | max depth (%) | longest recovery (d) | still unrecovered |
|---|---|---|---|---|---|---|
| BTC | 14 | 25.7 | 101 | 76.6 | 846 | 1 |
| ETH | 15 | 19.2 | 17 | 79.3 | 1382 | 1 |
| SOL | 15 | 17.1 | 13 | 96.3 | 1168 | 1 |

**Reading.** Up-runs and down-runs differ in length and in magnitude,
and drawdowns take far longer to recover than to create. This is the
structural reason a fixed-R geometry with a 15-day hold behaves
asymmetrically, and it is context for the live record's short-side
result (0 wins in 11 short episodes).

**What it does NOT say:** asymmetry is not a timing signal. Knowing
downs are sharper than ups does not say when either begins.

---

## M8 — Tradability drift over time

#167's tradability measure as a TIME SERIES: flat-bar share (bars with
zero range) and median stop fraction (1.5×ATR / close) per year, per
basket ticker. #167 applied this as a one-off filter; this asks whether
it drifts.

| year | tickers | median flat-bar share | 95% CI | median stop fraction | 95% CI | tickers under the 0.80% cost floor |
|---|---|---|---|---|---|---|
| 2019 | 12 | 0.0125 | [0.0117, 0.0428] | 0.0274 | [0.0258, 0.0287] | 0 |
| 2020 | 16 | 0.0073 | [0.0009, 0.0292] | 0.0334 | [0.0319, 0.0415] | 0 |
| 2021 | 19 | 0.0000 | [0.0000, 0.0000] | 0.0573 | [0.0518, 0.0675] | 0 |
| 2022 | 25 | 0.0014 | [0.0000, 0.0067] | 0.0391 | [0.0378, 0.0429] | 0 |
| 2023 | 26 | 0.0050 | [0.0009, 0.0185] | 0.0285 | [0.0262, 0.0303] | 0 |
| 2024 | 25 | 0.0005 | [0.0000, 0.0032] | 0.0365 | [0.0311, 0.0405] | 0 |
| 2025 | 25 | 0.0164 | [0.0000, 0.0498] | 0.0366 | [0.0345, 0.0385] | 0 |
| 2026 | 25 | 0.0417 | [0.0000, 0.2202] | 0.0327 | [0.0290, 0.0369] | 0 |

**Reading.** The last column counts tickers whose median 1.5×ATR stop
sits below the **0.80% cost floor** this project derived from
`MAX_COST_FRACTION_OF_R = 0.10`. A ticker under that floor pays more
than a tenth of its risk in costs, which is what #167 filtered on.

**What it does NOT say:** improving tradability is not improving
opportunity. #163–#167 measured the filtered basket and it still
failed; a cleaner instrument does not create an edge.

---

## What this map is for

It is a description of the terrain, not a route across it. Every
measurement above is a property of the market that would be true
whether or not anyone traded it, and none of them is a claim that
something can be traded.

**`docs/claims.md` is unchanged by this document and cannot be changed
by it.** The project still holds zero supported edge claims.

The next step, if there is one, is **exactly one** registered
hypothesis (#250), drawn from here, tested only on data that did not
exist when this was written.
