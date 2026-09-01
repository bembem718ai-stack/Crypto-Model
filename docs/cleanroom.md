# Cleanroom — pre-registered research log

Every hypothesis in this project is numbered and written down **before** it
runs. Nothing is added retroactively, no parameter is changed after a result
is seen, and negatives are recorded with the same detail as positives. See
"Research rules" in `CLAUDE.md`.

Numbers **#1-#41 are reserved** for the pre-existing findings already recorded
in the code and in `CLAUDE.md` (the ML replication failure, the 4-year
degradation, the VIX regime candidate, short-side viability). New work starts
at #42.

## Dataset and windows

Frozen offline dataset in `data/`, written by `export_data.py`:
13,000 4h Binance.US bars per ticker (2020-09-20 -> 2026-08-27) plus the
incumbent's daily frame (1,762 rows, 2021-10-24 -> 2026-08-21).

Daily bars for new models are resampled from the 4h feed on UTC days, with
partial days dropped at both ends. All windows are anchored on the dataset's
last date rather than the wall clock, so every number here is reproducible
from the frozen files.

| window | range | days | span |
|--------|-------|------|------|
| DISCOVERY | 2020-09-21 -> 2023-09-16 | 1091 | 2.98y |
| CONFIRMATION | 2023-09-16 -> 2026-02-26 | 893 | 2.44y |
| LOCKBOX (SEALED) | 2026-02-26 -> 2026-08-26 | 181 | 0.50y |

The incumbent's `merged` frame starts 2021-10-24, so on DISCOVERY the
incumbent rows cover ~1.9y of the 2.98y window. CONFIRMATION is fully covered
by both frames, so the head-to-head there is like-for-like.

## Baseline measurements — DISCOVERY (not hypotheses, reference rows)

Scored through `pipeline.evaluate_geometry_folds` with `LIVE_GEOMETRY`,
4 folds, 2bps fee + 2bps slippage per side. `net_all` is pooled net
expectancy over every trade; `ex_best` is `concentration_report`'s
excluding-best-fold figure and is undefined ("-") below 3 counted folds.

| ticker | row | n | win% | net_all | ex_best | folds+/counted | placebo p95 | pctile |
|--------|-----|---|------|---------|---------|----------------|-------------|--------|
| BTC | INC_STRONG_BUY | 8 | 100.0 | +2.622 | - | - | +0.628 | 100.0 |
| BTC | INC_BUY_ALL | 58 | 39.7 | +0.237 | +0.207 | 2/3 | +0.628 | - |
| BTC | ALWAYS_LONG | 1087 | 32.0 | -0.060 | -0.118 | 1/4 | +0.628 | - |
| ETH | INC_STRONG_BUY | 3 | 33.3 | +0.167 | - | - | +0.796 | 74.0 |
| ETH | INC_BUY_ALL | 59 | 28.8 | -0.175 | -0.395 | 0/3 | +0.796 | - |
| ETH | ALWAYS_LONG | 1087 | 32.3 | -0.056 | -0.115 | 1/4 | +0.796 | - |
| SOL | INC_STRONG_BUY | 1 | 100.0 | +2.644 | - | - | +1.004 | 99.0 |
| SOL | INC_BUY_ALL | 59 | 27.1 | -0.201 | -0.438 | 1/4 | +1.004 | - |
| SOL | ALWAYS_LONG | 1087 | 34.5 | +0.034 | -0.003 | 2/4 | +1.004 | - |

**Recorded finding:** the incumbent's STRONG_BUY tier is far too rare to
assess on DISCOVERY - 8, 3 and 1 trades. None of the three reaches 3 counted
folds, so `ex_best` cannot be computed for it at all, and the eye-catching
+2.622R / +2.644R come from 8 and 1 trades respectively. INC_BUY_ALL is
net-positive on BTC (+0.237) and net-negative on ETH (-0.175) and SOL
(-0.201). ALWAYS_LONG is slightly negative on BTC/ETH and slightly positive
on SOL, which sets the drift baseline any new rule has to beat.

## Registered hypotheses

### Hypotheses #42-#161 — the enumerated rule grid

Registered BEFORE any rule was scored. The grid is a grammar, not a shortlist: 30 base setups x 4 context filters = 120 rules, every one of which gets scored and reported whatever it does.

**Parameters are conventional and fixed.** Nothing below was chosen by looking at a result, and nothing may be changed after one is seen (rule 4 of the Research rules).

**Windows** (anchored on the dataset's last date, 2026-08-26, never the wall clock): DISCOVERY 2020-09-21 -> 2023-09-16; CONFIRMATION 2023-09-16 -> 2026-02-26; LOCKBOX 2026-02-26 -> 2026-08-26 (SEALED). Features are computed on data strictly before the lockbox boundary, so no rolling window touches a sealed row.

**Protocol.** Each rule produces a daily boolean event series. An event on day E labels day E and day E+1 as BUY; the incumbent's 2-day confirm therefore enters at the close of E+1. Scoring runs through `research/harness.py` into `pipeline.evaluate_geometry_folds` with `LIVE_GEOMETRY`, 4 folds, and walkforward's 2bps fee + 2bps slippage per side. `ex_best` is `pipeline.concentration_report`'s excluding-best-fold expectancy (folds count at >=10 trades; needs >=3 counted folds).

**Discovery selection rule, fixed in advance:** rank by the MINIMUM `ex_best` across the three tickers, with a rarity guard of n >= 20 trades per ticker. The top 5 are then frozen and go to CONFIRMATION unchanged.

| # | rule | base setup | context |
|---|------|-----------|---------|
| 42 | `donchian10+none` | Donchian breakout: close > prior 10-day high | no context filter |
| 43 | `donchian10+above_sma200` | Donchian breakout: close > prior 10-day high | close > SMA200 (own trend) |
| 44 | `donchian10+btc_above_sma200` | Donchian breakout: close > prior 10-day high | BTC close > BTC SMA200 (market regime) |
| 45 | `donchian10+lowvol` | Donchian breakout: close > prior 10-day high | 30-day realized vol below its 100-day median |
| 46 | `donchian20+none` | Donchian breakout: close > prior 20-day high | no context filter |
| 47 | `donchian20+above_sma200` | Donchian breakout: close > prior 20-day high | close > SMA200 (own trend) |
| 48 | `donchian20+btc_above_sma200` | Donchian breakout: close > prior 20-day high | BTC close > BTC SMA200 (market regime) |
| 49 | `donchian20+lowvol` | Donchian breakout: close > prior 20-day high | 30-day realized vol below its 100-day median |
| 50 | `donchian55+none` | Donchian breakout: close > prior 55-day high | no context filter |
| 51 | `donchian55+above_sma200` | Donchian breakout: close > prior 55-day high | close > SMA200 (own trend) |
| 52 | `donchian55+btc_above_sma200` | Donchian breakout: close > prior 55-day high | BTC close > BTC SMA200 (market regime) |
| 53 | `donchian55+lowvol` | Donchian breakout: close > prior 55-day high | 30-day realized vol below its 100-day median |
| 54 | `emacross9_21+none` | EMA9 crosses above EMA21 | no context filter |
| 55 | `emacross9_21+above_sma200` | EMA9 crosses above EMA21 | close > SMA200 (own trend) |
| 56 | `emacross9_21+btc_above_sma200` | EMA9 crosses above EMA21 | BTC close > BTC SMA200 (market regime) |
| 57 | `emacross9_21+lowvol` | EMA9 crosses above EMA21 | 30-day realized vol below its 100-day median |
| 58 | `emacross20_50+none` | EMA20 crosses above EMA50 | no context filter |
| 59 | `emacross20_50+above_sma200` | EMA20 crosses above EMA50 | close > SMA200 (own trend) |
| 60 | `emacross20_50+btc_above_sma200` | EMA20 crosses above EMA50 | BTC close > BTC SMA200 (market regime) |
| 61 | `emacross20_50+lowvol` | EMA20 crosses above EMA50 | 30-day realized vol below its 100-day median |
| 62 | `emacross50_200+none` | EMA50 crosses above EMA200 | no context filter |
| 63 | `emacross50_200+above_sma200` | EMA50 crosses above EMA200 | close > SMA200 (own trend) |
| 64 | `emacross50_200+btc_above_sma200` | EMA50 crosses above EMA200 | BTC close > BTC SMA200 (market regime) |
| 65 | `emacross50_200+lowvol` | EMA50 crosses above EMA200 | 30-day realized vol below its 100-day median |
| 66 | `pullback_sma100_ema10+none` | Trend pullback: close > SMA100 and close crosses above EMA10 | no context filter |
| 67 | `pullback_sma100_ema10+above_sma200` | Trend pullback: close > SMA100 and close crosses above EMA10 | close > SMA200 (own trend) |
| 68 | `pullback_sma100_ema10+btc_above_sma200` | Trend pullback: close > SMA100 and close crosses above EMA10 | BTC close > BTC SMA200 (market regime) |
| 69 | `pullback_sma100_ema10+lowvol` | Trend pullback: close > SMA100 and close crosses above EMA10 | 30-day realized vol below its 100-day median |
| 70 | `pullback_sma100_ema20+none` | Trend pullback: close > SMA100 and close crosses above EMA20 | no context filter |
| 71 | `pullback_sma100_ema20+above_sma200` | Trend pullback: close > SMA100 and close crosses above EMA20 | close > SMA200 (own trend) |
| 72 | `pullback_sma100_ema20+btc_above_sma200` | Trend pullback: close > SMA100 and close crosses above EMA20 | BTC close > BTC SMA200 (market regime) |
| 73 | `pullback_sma100_ema20+lowvol` | Trend pullback: close > SMA100 and close crosses above EMA20 | 30-day realized vol below its 100-day median |
| 74 | `pullback_sma200_ema10+none` | Trend pullback: close > SMA200 and close crosses above EMA10 | no context filter |
| 75 | `pullback_sma200_ema10+above_sma200` | Trend pullback: close > SMA200 and close crosses above EMA10 | close > SMA200 (own trend) |
| 76 | `pullback_sma200_ema10+btc_above_sma200` | Trend pullback: close > SMA200 and close crosses above EMA10 | BTC close > BTC SMA200 (market regime) |
| 77 | `pullback_sma200_ema10+lowvol` | Trend pullback: close > SMA200 and close crosses above EMA10 | 30-day realized vol below its 100-day median |
| 78 | `pullback_sma200_ema20+none` | Trend pullback: close > SMA200 and close crosses above EMA20 | no context filter |
| 79 | `pullback_sma200_ema20+above_sma200` | Trend pullback: close > SMA200 and close crosses above EMA20 | close > SMA200 (own trend) |
| 80 | `pullback_sma200_ema20+btc_above_sma200` | Trend pullback: close > SMA200 and close crosses above EMA20 | BTC close > BTC SMA200 (market regime) |
| 81 | `pullback_sma200_ema20+lowvol` | Trend pullback: close > SMA200 and close crosses above EMA20 | 30-day realized vol below its 100-day median |
| 82 | `rsi14_exit25+none` | RSI14 crosses back above 25 (exit from oversold) | no context filter |
| 83 | `rsi14_exit25+above_sma200` | RSI14 crosses back above 25 (exit from oversold) | close > SMA200 (own trend) |
| 84 | `rsi14_exit25+btc_above_sma200` | RSI14 crosses back above 25 (exit from oversold) | BTC close > BTC SMA200 (market regime) |
| 85 | `rsi14_exit25+lowvol` | RSI14 crosses back above 25 (exit from oversold) | 30-day realized vol below its 100-day median |
| 86 | `rsi14_exit30+none` | RSI14 crosses back above 30 (exit from oversold) | no context filter |
| 87 | `rsi14_exit30+above_sma200` | RSI14 crosses back above 30 (exit from oversold) | close > SMA200 (own trend) |
| 88 | `rsi14_exit30+btc_above_sma200` | RSI14 crosses back above 30 (exit from oversold) | BTC close > BTC SMA200 (market regime) |
| 89 | `rsi14_exit30+lowvol` | RSI14 crosses back above 30 (exit from oversold) | 30-day realized vol below its 100-day median |
| 90 | `rsi14_exit35+none` | RSI14 crosses back above 35 (exit from oversold) | no context filter |
| 91 | `rsi14_exit35+above_sma200` | RSI14 crosses back above 35 (exit from oversold) | close > SMA200 (own trend) |
| 92 | `rsi14_exit35+btc_above_sma200` | RSI14 crosses back above 35 (exit from oversold) | BTC close > BTC SMA200 (market regime) |
| 93 | `rsi14_exit35+lowvol` | RSI14 crosses back above 35 (exit from oversold) | 30-day realized vol below its 100-day median |
| 94 | `rsi7_cross50+none` | RSI7 crosses above 50 | no context filter |
| 95 | `rsi7_cross50+above_sma200` | RSI7 crosses above 50 | close > SMA200 (own trend) |
| 96 | `rsi7_cross50+btc_above_sma200` | RSI7 crosses above 50 | BTC close > BTC SMA200 (market regime) |
| 97 | `rsi7_cross50+lowvol` | RSI7 crosses above 50 | 30-day realized vol below its 100-day median |
| 98 | `rsi14_cross50+none` | RSI14 crosses above 50 | no context filter |
| 99 | `rsi14_cross50+above_sma200` | RSI14 crosses above 50 | close > SMA200 (own trend) |
| 100 | `rsi14_cross50+btc_above_sma200` | RSI14 crosses above 50 | BTC close > BTC SMA200 (market regime) |
| 101 | `rsi14_cross50+lowvol` | RSI14 crosses above 50 | 30-day realized vol below its 100-day median |
| 102 | `roc10_zero+none` | ROC10 crosses above zero | no context filter |
| 103 | `roc10_zero+above_sma200` | ROC10 crosses above zero | close > SMA200 (own trend) |
| 104 | `roc10_zero+btc_above_sma200` | ROC10 crosses above zero | BTC close > BTC SMA200 (market regime) |
| 105 | `roc10_zero+lowvol` | ROC10 crosses above zero | 30-day realized vol below its 100-day median |
| 106 | `roc20_zero+none` | ROC20 crosses above zero | no context filter |
| 107 | `roc20_zero+above_sma200` | ROC20 crosses above zero | close > SMA200 (own trend) |
| 108 | `roc20_zero+btc_above_sma200` | ROC20 crosses above zero | BTC close > BTC SMA200 (market regime) |
| 109 | `roc20_zero+lowvol` | ROC20 crosses above zero | 30-day realized vol below its 100-day median |
| 110 | `roc60_zero+none` | ROC60 crosses above zero | no context filter |
| 111 | `roc60_zero+above_sma200` | ROC60 crosses above zero | close > SMA200 (own trend) |
| 112 | `roc60_zero+btc_above_sma200` | ROC60 crosses above zero | BTC close > BTC SMA200 (market regime) |
| 113 | `roc60_zero+lowvol` | ROC60 crosses above zero | 30-day realized vol below its 100-day median |
| 114 | `ttm_release+none` | TTM squeeze release: BB(20,2) exits Keltner(20,1.5ATR) | no context filter |
| 115 | `ttm_release+above_sma200` | TTM squeeze release: BB(20,2) exits Keltner(20,1.5ATR) | close > SMA200 (own trend) |
| 116 | `ttm_release+btc_above_sma200` | TTM squeeze release: BB(20,2) exits Keltner(20,1.5ATR) | BTC close > BTC SMA200 (market regime) |
| 117 | `ttm_release+lowvol` | TTM squeeze release: BB(20,2) exits Keltner(20,1.5ATR) | 30-day realized vol below its 100-day median |
| 118 | `nr7+none` | NR7: narrowest range of the last 7 days | no context filter |
| 119 | `nr7+above_sma200` | NR7: narrowest range of the last 7 days | close > SMA200 (own trend) |
| 120 | `nr7+btc_above_sma200` | NR7: narrowest range of the last 7 days | BTC close > BTC SMA200 (market regime) |
| 121 | `nr7+lowvol` | NR7: narrowest range of the last 7 days | 30-day realized vol below its 100-day median |
| 122 | `nr4+none` | NR4: narrowest range of the last 4 days | no context filter |
| 123 | `nr4+above_sma200` | NR4: narrowest range of the last 4 days | close > SMA200 (own trend) |
| 124 | `nr4+btc_above_sma200` | NR4: narrowest range of the last 4 days | BTC close > BTC SMA200 (market regime) |
| 125 | `nr4+lowvol` | NR4: narrowest range of the last 4 days | 30-day realized vol below its 100-day median |
| 126 | `bbw_p10_expand+none` | BB bandwidth below its 10th 100-day percentile, then expansion on an up day | no context filter |
| 127 | `bbw_p10_expand+above_sma200` | BB bandwidth below its 10th 100-day percentile, then expansion on an up day | close > SMA200 (own trend) |
| 128 | `bbw_p10_expand+btc_above_sma200` | BB bandwidth below its 10th 100-day percentile, then expansion on an up day | BTC close > BTC SMA200 (market regime) |
| 129 | `bbw_p10_expand+lowvol` | BB bandwidth below its 10th 100-day percentile, then expansion on an up day | 30-day realized vol below its 100-day median |
| 130 | `bbw_p20_expand+none` | BB bandwidth below its 20th 100-day percentile, then expansion on an up day | no context filter |
| 131 | `bbw_p20_expand+above_sma200` | BB bandwidth below its 20th 100-day percentile, then expansion on an up day | close > SMA200 (own trend) |
| 132 | `bbw_p20_expand+btc_above_sma200` | BB bandwidth below its 20th 100-day percentile, then expansion on an up day | BTC close > BTC SMA200 (market regime) |
| 133 | `bbw_p20_expand+lowvol` | BB bandwidth below its 20th 100-day percentile, then expansion on an up day | 30-day realized vol below its 100-day median |
| 134 | `volbreak1+none` | Close > prior close + 1 x ATR14 | no context filter |
| 135 | `volbreak1+above_sma200` | Close > prior close + 1 x ATR14 | close > SMA200 (own trend) |
| 136 | `volbreak1+btc_above_sma200` | Close > prior close + 1 x ATR14 | BTC close > BTC SMA200 (market regime) |
| 137 | `volbreak1+lowvol` | Close > prior close + 1 x ATR14 | 30-day realized vol below its 100-day median |
| 138 | `volbreak1.5+none` | Close > prior close + 1.5 x ATR14 | no context filter |
| 139 | `volbreak1.5+above_sma200` | Close > prior close + 1.5 x ATR14 | close > SMA200 (own trend) |
| 140 | `volbreak1.5+btc_above_sma200` | Close > prior close + 1.5 x ATR14 | BTC close > BTC SMA200 (market regime) |
| 141 | `volbreak1.5+lowvol` | Close > prior close + 1.5 x ATR14 | 30-day realized vol below its 100-day median |
| 142 | `wide_range_up+none` | Wide-range up day: close in top 10% of range, range > 1.5 x ATR14 | no context filter |
| 143 | `wide_range_up+above_sma200` | Wide-range up day: close in top 10% of range, range > 1.5 x ATR14 | close > SMA200 (own trend) |
| 144 | `wide_range_up+btc_above_sma200` | Wide-range up day: close in top 10% of range, range > 1.5 x ATR14 | BTC close > BTC SMA200 (market regime) |
| 145 | `wide_range_up+lowvol` | Wide-range up day: close in top 10% of range, range > 1.5 x ATR14 | 30-day realized vol below its 100-day median |
| 146 | `three_inside_up+none` | Three inside days then an up close | no context filter |
| 147 | `three_inside_up+above_sma200` | Three inside days then an up close | close > SMA200 (own trend) |
| 148 | `three_inside_up+btc_above_sma200` | Three inside days then an up close | BTC close > BTC SMA200 (market regime) |
| 149 | `three_inside_up+lowvol` | Three inside days then an up close | 30-day realized vol below its 100-day median |
| 150 | `vol_thrust+none` | Up close with volume > 2x its 20-day average | no context filter |
| 151 | `vol_thrust+above_sma200` | Up close with volume > 2x its 20-day average | close > SMA200 (own trend) |
| 152 | `vol_thrust+btc_above_sma200` | Up close with volume > 2x its 20-day average | BTC close > BTC SMA200 (market regime) |
| 153 | `vol_thrust+lowvol` | Up close with volume > 2x its 20-day average | 30-day realized vol below its 100-day median |
| 154 | `obv_break20+none` | OBV breaks its own 20-day high | no context filter |
| 155 | `obv_break20+above_sma200` | OBV breaks its own 20-day high | close > SMA200 (own trend) |
| 156 | `obv_break20+btc_above_sma200` | OBV breaks its own 20-day high | BTC close > BTC SMA200 (market regime) |
| 157 | `obv_break20+lowvol` | OBV breaks its own 20-day high | 30-day realized vol below its 100-day median |
| 158 | `weekly_cross10w+none` | Weekly close crosses above its 10-week SMA | no context filter |
| 159 | `weekly_cross10w+above_sma200` | Weekly close crosses above its 10-week SMA | close > SMA200 (own trend) |
| 160 | `weekly_cross10w+btc_above_sma200` | Weekly close crosses above its 10-week SMA | BTC close > BTC SMA200 (market regime) |
| 161 | `weekly_cross10w+lowvol` | Weekly close crosses above its 10-week SMA | 30-day realized vol below its 100-day median |

### Hypothesis #162 — CONFIRMATION of the 5 rules frozen on DISCOVERY

**Registered BEFORE the confirmation run.** Scored ONCE. There is no second
attempt, no parameter change, and no partial credit: a rule that misses on
one ticker fails, and a rule that is "almost" fails.

**The 5 rules, frozen by the DISCOVERY selection rule** (rank by MINIMUM
`ex_best` across tickers, rarity guard n >= 20/ticker):

| # | rule | DISCOVERY min ex_best |
|---|------|----------------------|
| 42 | `donchian10+none` | -0.073 |
| 154 | `obv_break20+none` | -0.114 |
| 102 | `roc10_zero+none` | -0.168 |
| 118 | `nr7+none` | -0.179 |
| 94 | `rsi7_cross50+none` | -0.180 |

**Window.** CONFIRMATION only. The 4h feed is sealed at the lockbox
boundary, which BINDS here (unlike DISCOVERY): a trade entered near the end
of CONFIRMATION cannot resolve without reading sealed bars, so it is dropped
rather than resolved on data research may not see.

**PASS RULE (both conditions, on ALL THREE tickers):**
1. `ex_best` > 0, and
2. `net_all` strictly above the count-matched placebo's 99th percentile.

p99 rather than p95 because 5 rules were selected: a Bonferroni-style
correction for having taken the best of a grid. 200 placebo seeds per rule
per ticker, count-matched and painted with the same event convention.

**Also run, on the identical window and threshold:** `INC_STRONG_BUY`, so
the incumbent is measured against the same bar rather than being assumed to
clear it. Its placebo is painted STRONG_BUY to match the 1.333x conviction
target.

**Gauntlet, for survivors only:** 4y/5-fold and 5y/4-fold over the full
non-lockbox window, requiring `ex_best` > 0 on all three tickers.

**Pre-declared expectation:** all 5 had NEGATIVE minimum `ex_best` on
DISCOVERY, so the honest prior is that none passes. Recording that here so
a null result cannot later be dressed up as a surprise.

#### Result of #162 — recorded 2026-08-27

Scored ONCE on CONFIRMATION 2023-09-16 -> 2026-02-26 (893 days), 4 folds, 2+2bps per side, 4h feed sealed at the lockbox boundary. 200 placebo seeds per row per ticker.

| row | ticker | n | win% | net_all | ex_best | placebo p99 | pctile | ex_best>0 | net>p99 |
|-----|--------|---|------|---------|---------|-------------|--------|-----------|---------|
| `donchian10+none` | BTC | 104 | 35.6 | +0.023 | -0.244 | +0.474 | 31.5 | N | N |
| `obv_break20+none` | BTC | 136 | 41.9 | +0.213 | +0.154 | +0.395 | 77.5 | Y | N |
| `roc10_zero+none` | BTC | 69 | 44.9 | +0.304 | +0.112 | +0.528 | 86.0 | Y | N |
| `nr7+none` | BTC | 143 | 35.0 | +0.000 | -0.031 | +0.379 | 14.5 | N | N |
| `rsi7_cross50+none` | BTC | 75 | 54.7 | +0.598 | +0.458 | +0.540 | 99.0 | Y | Y |
| `INC_STRONG_BUY` | BTC | 10 | 60.0 | +1.146 | - | +1.247 | 98.0 | N | N |
| `donchian10+none` | ETH | 92 | 43.5 | +0.272 | +0.108 | +0.513 | 80.5 | Y | N |
| `obv_break20+none` | ETH | 108 | 37.0 | +0.085 | -0.049 | +0.491 | 37.5 | N | N |
| `roc10_zero+none` | ETH | 65 | 41.5 | +0.213 | +0.167 | +0.583 | 71.5 | Y | N |
| `nr7+none` | ETH | 141 | 34.0 | -0.013 | -0.106 | +0.408 | 9.5 | N | N |
| `rsi7_cross50+none` | ETH | 77 | 33.8 | -0.021 | -0.193 | +0.490 | 20.0 | N | N |
| `INC_STRONG_BUY` | ETH | 5 | 60.0 | +1.160 | - | +1.413 | 97.0 | N | N |
| `donchian10+none` | SOL | 104 | 28.8 | -0.157 | -0.220 | +0.283 | 10.0 | N | N |
| `obv_break20+none` | SOL | 133 | 36.1 | +0.060 | -0.070 | +0.294 | 66.5 | N | N |
| `roc10_zero+none` | SOL | 59 | 33.9 | -0.007 | -0.205 | +0.459 | 43.0 | N | N |
| `nr7+none` | SOL | 147 | 31.3 | -0.085 | -0.157 | +0.300 | 17.5 | N | N |
| `rsi7_cross50+none` | SOL | 71 | 52.1 | +0.539 | +0.504 | +0.394 | 99.5 | Y | Y |
| `INC_STRONG_BUY` | SOL | 0 | nan | - | - | +2.652 | - | N | N |

**VERDICTS — all six FAIL. Nothing survives to the gauntlet.**

| row | verdict | why |
|-----|---------|-----|
| `donchian10+none` | **FAIL** | ex_best negative on BTC (-0.244) and SOL (-0.220); net_all below p99 on all three. |
| `obv_break20+none` | **FAIL** | ex_best positive on BTC only (+0.154); negative on ETH and SOL; net_all below p99 on all three. |
| `roc10_zero+none` | **FAIL** | ex_best positive on BTC/ETH but negative on SOL (-0.205); net_all below p99 on all three. |
| `nr7+none` | **FAIL** | ex_best negative on all three; net_all ~0 or negative; percentiles 9.5-17.5. |
| `rsi7_cross50+none` | **FAIL** | THE NEAR-MISS. Passes BOTH conditions on BTC (net +0.598 > p99 +0.540, ex_best +0.458) and SOL (net +0.539 > p99 +0.394, ex_best +0.504), but fails ETH outright: ex_best -0.193, net -0.021, 20th percentile. Registered rule admits no partial credit. |
| `INC_STRONG_BUY` | **FAIL** | Cannot meet condition 1 anywhere: 0 counted folds on all three tickers, so ex_best is undefined, not positive. Condition 2 also missed - BTC 98.0th pctile (net +1.146 vs p99 +1.247), ETH 97.0th (+1.160 vs +1.413). SOL produced ZERO trades: 2 STRONG_BUY days, no consecutive pair, so confirm_days=2 never fires. |

**Gauntlet (4y/5-fold, 5y/4-fold): NOT RUN — no survivors.**

**Recorded findings.**

1. The DISCOVERY selection carried no signal forward. All 5 rules had negative minimum `ex_best` on DISCOVERY, and none met the CONFIRMATION bar. This is the pre-declared expected outcome (#162), not a surprise.

2. `rsi7_cross50+none` cleared both conditions on 2 of 3 tickers and is recorded here IN FULL precisely because it is the tempting one. Its ETH leg is not marginal (20th percentile, ex_best -0.193), so this is a genuine cross-ticker failure, not noise at the boundary. Under research rule 4 it does not get a second look with a changed threshold, a dropped ticker, or a different window.

3. The incumbent's STRONG_BUY tier does not clear the bar it is being used to judge new rules against, on the same window. It is too rare to evaluate: 10, 5 and 0 trades over 2.4 years, never reaching 3 counted folds on any ticker. On SOL it placed no trade at all. A tier that cannot be measured cannot be said to work.

4. Both incumbent legs that DID trade sit at the 97th-98th percentile of their count-matched placebo - high, but below the p99 bar the 5 rules were held to, and on 10 and 5 trades respectively.

#### Correction to the DISCOVERY baseline table (recorded, not silently edited)

The `ALWAYS_LONG` rows above (n=1087) and the placebo percentiles beside
them were computed before two defects in `research/harness.py` were found.
The original numbers are LEFT IN PLACE above; these are the corrected ones.

1. **Non-comparable baseline.** `ALWAYS_LONG` was scored over the resampled
   daily frame's full span (2020-09-21 ->, 2.98y) while `INC_*` and the
   placebo only spanned merged's warmed-up range (2021-10-24 ->, 1.89y). The
   drift baseline covered 13 months of the 2020-21 run-up the incumbent
   never saw. Corrected by clipping all rows to the shared span.
2. **Borrowed percentile.** Only `INC_STRONG_BUY` ever had a percentile;
   `INC_BUY_ALL` and `ALWAYS_LONG` displayed a `placebo_p95` drawn for a
   different trade count AND a different conviction geometry.

Corrected DISCOVERY reference rows (each with its OWN count-matched placebo,
300 seeds; `INC_BUY_ALL`'s placebo painted with the incumbent's actual
STRONG_BUY/BUY mix so average R:R matches):

| ticker | row | n | win% | net_all | ex_best | placebo p95 | pctile |
|--------|-----|---|------|---------|---------|-------------|--------|
| BTC | INC_STRONG_BUY | 8 | 100.0 | +2.622 | - | +0.627 | 100.0 |
| BTC | INC_BUY_ALL | 58 | 39.7 | +0.237 | +0.207 | +0.013 | 100.0 |
| BTC | ALWAYS_LONG | 689 | 29.0 | -0.148 | -0.182 | - | n/a |
| ETH | INC_STRONG_BUY | 3 | 33.3 | +0.167 | - | +0.824 | 75.0 |
| ETH | INC_BUY_ALL | 59 | 28.8 | -0.175 | -0.395 | +0.031 | 47.7 |
| ETH | ALWAYS_LONG | 689 | 29.0 | -0.159 | -0.184 | - | n/a |
| SOL | INC_STRONG_BUY | 1 | 100.0 | +2.644 | - | +0.912 | 99.7 |
| SOL | INC_BUY_ALL | 59 | 27.1 | -0.201 | -0.438 | +0.099 | 21.0 |
| SOL | ALWAYS_LONG | 689 | 31.2 | -0.078 | -0.103 | - | n/a |

`ALWAYS_LONG` has NO percentile and one was not invented: its count is every
eligible day, so exactly one count-matched draw exists (all of them) and it
equals ALWAYS_LONG itself.

**Clustering caveat, unchanged.** The STRONG_BUY percentiles rest on 2, 2
and 1 independent episodes (8 trades on BTC resolve on 4 distinct exit
bars; SOL's single trade on 1). The placebo scatters its draws and gets
near-independent trades, so it is far lower-variance than the row it
benchmarks - 100.0 and 99.7 are artifacts of that mismatch. `INC_BUY_ALL`
does NOT have this problem (58 trades / 13 episodes / 47 distinct exit bars
on BTC), so its percentiles are real ones.

## Attribution - where does the expectancy come from?

Produced by `research/attribution.py`. Nothing here decides a trade: every
trade dissected was produced by `pipeline.evaluate_geometry_folds` through
`research/harness.py`. The module only measures properties of those trades.

**Scope.** `INC_STRONG_BUY` plus the top 3 DISCOVERY rules - nothing survived
CONFIRMATION (#162), so the fallback applies. Window is the full non-lockbox
span, DISCOVERY + CONFIRMATION (2020-09-21 -> 2026-02-26 for the resampled
daily frame; 2021-10-24 -> 2026-02-26 for the incumbent's merged frame, which
starts later). Pooled because `INC_STRONG_BUY` fires 8/3/1 times on DISCOVERY
and 10/5/0 on CONFIRMATION - split any finer and there is nothing to
attribute. The lockbox stays sealed in both the daily frames and the 4h feed.

**Two notes on how to read the numbers.**

- `best fold share` above 100% is not an error. It means the single best fold
  contributes more R than the strategy made in total, i.e. the other three
  folds are net NEGATIVE. 139% means: remove the best fold and you lose money.
- MFE/MAE are in R. `pipeline` stores only favourable excursion as a fraction
  of TARGET distance and no MAE at all, so MFE_R is rescaled by the R:R (2.0
  for BUY, 2.667 for STRONG_BUY) and MAE is measured directly off the 4h bars
  between pipeline's own entry and exit.

### The headline: for the three rules, the edge IS mostly drift plus geometry

Under this geometry a trade can only end three ways, and timeouts are ~0-1%.
So gross expectancy is almost exactly `2 x P(target) - P(stop)` - a mechanical
function of the hit rate. That makes the comparison below the whole story:

| ticker | row | n | target% | stop% | net exp |
|--------|-----|---|---------|-------|---------|
| BTC | ALWAYS_LONG (drift baseline) | 1979 | 34.9 | 64.4 | +0.016 |
| ETH | ALWAYS_LONG (drift baseline) | 1979 | 35.1 | 64.5 | +0.031 |
| SOL | ALWAYS_LONG (drift baseline) | 1979 | 34.4 | 64.7 | +0.024 |
| BTC | `donchian10+none` | 216 | 37.0 | 61.6 | +0.089 |
| BTC | `obv_break20+none` | 246 | 37.4 | 62.2 | +0.088 |
| BTC | `roc10_zero+none` | 167 | 38.9 | 60.5 | +0.133 |
| ETH | `donchian10+none` | 226 | 37.6 | 62.4 | +0.101 |
| ETH | `obv_break20+none` | 228 | 38.6 | 61.0 | +0.132 |
| ETH | `roc10_zero+none` | 138 | 36.2 | 63.8 | +0.055 |
| SOL | `donchian10+none` | 203 | 33.0 | 65.5 | -0.009 |
| SOL | `obv_break20+none` | 304 | 39.8 | 59.9 | +0.180 |
| SOL | `roc10_zero+none` | 147 | 35.4 | 63.3 | +0.065 |

Being long every single day already hits target ~35% of the time and earns
+0.016 to +0.031R per trade. The three rules hit target 33-40% of the time.
**The entire contribution of the signal is a 2-4 percentage point lift in hit
rate** - everything else in their expectancy is the 2:1 payoff structure
applied to a market that drifted up. On SOL, `donchian10+none` does not even
manage that: 33.0% target vs the 34.4% you get from buying every day, which is
why its expectancy (-0.009R) is BELOW the drift baseline (+0.024R).

And the 2-4pp lift does not hold together across time:

| row | ticker | total R | best fold R | best fold share | excess over drift |
|-----|--------|---------|-------------|-----------------|-------------------|
| `donchian10+none` | BTC | +19.3 | +18.0 | 93% | +0.073 |
| `donchian10+none` | ETH | +22.9 | +18.2 | 80% | +0.070 |
| `donchian10+none` | SOL | -1.8 | +10.1 | n/a (total R <= 0) | -0.033 |
| `obv_break20+none` | BTC | +21.7 | +13.9 | 64% | +0.072 |
| `obv_break20+none` | ETH | +30.1 | +17.8 | 59% | +0.101 |
| `obv_break20+none` | SOL | +54.7 | +22.9 | 42% | +0.156 |
| `roc10_zero+none` | BTC | +22.3 | +19.2 | 86% | +0.117 |
| `roc10_zero+none` | ETH | +7.6 | +10.0 | 131% | +0.024 |
| `roc10_zero+none` | SOL | +9.5 | +13.2 | 139% | +0.041 |

`roc10_zero+none` on ETH (131%) and SOL (139%) makes money in one fold and
loses it in the other three. `donchian10+none` on BTC takes 93% of its total R
from a single fold. This is the same concentration that made `ex_best` negative
on DISCOVERY, now visible as a share of profit rather than a summary statistic.

### Regime and exit detail

| row | ticker | exp above SMA200 | exp below SMA200 | vol lo / mid / hi |
|-----|--------|------------------|------------------|-------------------|
| `donchian10+none` | BTC | +0.070 (n=130) | +0.119 (n=86) | +0.218 / +0.084 / +0.003 |
| `donchian10+none` | ETH | +0.148 (n=125) | +0.043 (n=101) | +0.324 / +0.028 / -0.006 |
| `donchian10+none` | SOL | -0.025 (n=128) | +0.019 (n=75) | -0.097 / -0.079 / +0.148 |
| `obv_break20+none` | BTC | +0.035 (n=157) | +0.181 (n=89) | +0.101 / +0.232 / -0.027 |
| `obv_break20+none` | ETH | +0.041 (n=138) | +0.271 (n=90) | -0.011 / +0.131 / +0.290 |
| `obv_break20+none` | SOL | +0.061 (n=179) | +0.350 (n=125) | +0.036 / +0.230 / +0.276 |
| `roc10_zero+none` | BTC | +0.018 (n=83) | +0.247 (n=84) | +0.250 / +0.185 / -0.100 |
| `roc10_zero+none` | ETH | -0.124 (n=66) | +0.219 (n=72) | -0.000 / -0.095 / +0.216 |
| `roc10_zero+none` | SOL | +0.222 (n=58) | -0.038 (n=89) | -0.169 / +0.205 / +0.158 |

**No consistent regime story.** `obv_break20+none` and `roc10_zero+none` do
better BELOW the 200-day SMA on BTC and ETH (+0.181/+0.271, +0.247/+0.219) -
the opposite of the trend-filter intuition - but `roc10_zero+none` flips to
preferring ABOVE on SOL (+0.222 vs -0.038). The vol terciles disagree across
tickers the same way: `donchian10+none` is best in LOW vol on BTC (+0.218) and
ETH (+0.324) but best in HIGH vol on SOL (+0.148). Three tickers, three
different stories, is what noise looks like.

**The exit mix is almost identical everywhere** - ~37% target / ~62% stop /
~0-1% timeout for every rule on every ticker. The shape of a winner and the
shape of a loser are also stable: winners run to MFE ~2.4-2.5R while only
giving back ~0.33-0.42R against them; losers reach only ~0.52-0.65R in favour
before being stopped at ~1.4R. Stopped trades never got close to target. That
uniformity is the signature of geometry doing the work, not selection.

### Overlap with the incumbent

| row | BTC | ETH | SOL |
|-----|-----|-----|-----|
| `donchian10+none` | 0.015 | 0.007 | 0.010 |
| `obv_break20+none` | 0.025 | 0.029 | 0.028 |
| `roc10_zero+none` | 0.074 | 0.072 | 0.051 |

Jaccard similarity of signal days against the incumbent's BUY/STRONG_BUY days
is 0.007-0.074 - essentially no overlap. **These rules are NOT relabellings of
the incumbent.** They fire on genuinely different days. That is the one
positive finding here: the grid explored new territory. It just did not find
anything in it.

### INC_STRONG_BUY - a different answer: not attributable

| ticker | n | exp | ALWAYS_LONG | excess | target% | best fold share |
|--------|---|-----|-------------|--------|---------|-----------------|
| BTC | 18 | +1.802 | -0.017 | +1.819 | 78 | 40% |
| ETH | 8 | +0.788 | +0.007 | +0.781 | 50 | 92% |
| SOL | 1 | +2.644 | -0.031 | +2.675 | 100 | 100% |

The incumbent's STRONG_BUY tier is **not** drift and **not** geometry. Drift on
its window is ~0 (-0.017 / +0.007 / -0.031), so essentially all of its +1.802 /
+0.788 / +2.644 is excess. And it does not get there through the 2:1 mechanism
the rules rely on: it hits target 78% of the time on BTC and 50% on ETH,
against a ~35% base rate. When it loses, it loses cleanly - stopped BTC trades
reached only 0.10R in favour before dying.

**But this cannot be called an edge, because there is not enough of it.** n =
18, 8 and 1 over five and a half years. The BTC trades are 2 clustered
episodes resolving on 4 distinct exit bars (recorded under the baseline
correction above), so 18 trades are nowhere near 18 independent observations.
ETH takes 92% of its R from one fold; SOL's entire record is a single trade.
`ex_best` is undefined on all three tickers because no ticker reaches 3 folds
with 10+ trades.

The Jaccard figures for this row (0.098 / 0.059 / 0.022) are degenerate and
should not be read as overlap: STRONG_BUY is a strict SUBSET of BUY, so the
ratio just restates how rare the tier is.

**Plain answer: the incumbent's STRONG_BUY expectancy comes from a genuinely
high target-hit rate on a handful of clustered trades. It is not explained
away by drift or geometry - and it is also not established. Too rare to
attribute is the finding, not a verdict either way.**

---

# PROGRAM: EVENT RATE (basket)

Registered BEFORE any of it ran. The previous program (#42-#162) tested
151 pre-registered price-only rules on 3 tickers; none replicated, and
the incumbent's STRONG_BUY tier fired ~4x/year so `ex_best` was never
even defined. This program moves on ONE axis: event rate, by widening
the universe from 3 tickers to 86.

## Setup changes (done before registration, recorded here)

1. **Python TLS fixed, verification never disabled.** This machine runs a
   TLS-intercepting filter driver whose root is in the Windows store but
   not in `certifi`. `research/tls.py` routes verification through the OS
   trust store. TWO transports needed fixing: `truststore` for Python's
   `ssl` (requests), and `CURL_CA_BUNDLE` for `curl_cffi` (yfinance, which
   was silently returning EMPTY dataframes rather than raising). There is
   no `verify=False` anywhere in the repo.
2. **`data/` re-exported at full depth.** N raised 12,600 -> 20,000 (the
   paginator ceiling) and the daily side from `period="5y"` to `"max"`.
   BTC/ETH: 15,177 4h bars, 6.93y (was 5.93y); daily 2,502 rows, 6.85y
   (was 1,762 / 4.82y). SOL: 13,014 bars, 5.94y. MANIFEST now records
   region, REST base, spans and provenance. Committed separately.
3. **Three guards added in `research/`, never in `pipeline.py`** (rule 1):
   `fetch_macro` memoized so ^VIX/DXY are pulled ONCE per run instead of
   once per ticker (172 redundant downloads across 86 tickers); tickers
   with <200 daily rows SKIPPED and REPORTED, never truncated, because
   `add_all_indicators` needs 200 for SMA200; and a per-ticker overlap
   assertion on the `how="inner"` join at `pipeline.py:931`, which
   otherwise truncates to the shorter feed in silence.

## !! WINDOW CHANGE — #42-#162 are no longer directly comparable

Windows are derived from the daily frame's span, so re-exporting at full
depth MOVED them. BTC/ETH DISCOVERY now cuts at **2023-04-06**, not
2023-09-16. Every result recorded above this line was produced on the old
windows. They are not being re-run and they are not being deleted; they
simply describe a different split and must not be compared line-for-line
against anything below.

## Definitions, fixed

- **SEALED** = the whole usable span, i.e. everything EXCEPT the last 6
  months. The last 6 months are the lockbox and are never read by any
  research script (rule 2). *(The prompt's wording admitted two readings;
  this is the one taken, because H-basket-C scores ON SEALED and so SEALED
  must be readable. Recorded here so the choice is on the record.)*
- **DISCOVERY / CONFIRMATION** = `harness.make_windows`'s existing time
  split of that usable span (first 55% / remaining 45%).
- **COMMON BASKET WINDOWS.** `harness.make_windows` anchors on each
  frame's OWN first date, which after the refresh already makes SOL's cut
  (2023-09-15) differ from BTC/ETH's (2023-04-06). Across 86 tickers with
  86 listing dates that would give 86 different DISCOVERY/CONFIRMATION
  boundaries and pooling would be incoherent. So the basket uses ONE set
  of windows for every ticker, anchored on **BTC** (deepest feed, market
  reference). A ticker simply contributes no trades before it listed.

## Universe

Binance.US spot USDT pairs with >=4y of 4h history AND a Yahoo listing
with >=4y (the incumbent's daily frame comes from Yahoo and is inner-
joined), minus 6 excluded as degenerate for a trend/breakout model:
USDC (stablecoin), PAXG (gold), and the fan tokens LAZIO, PORTO, SANTOS,
ALPINE. **Final count: 86.**

```
  BTC LTC IMX BCH BNB ETH XRP ADA
  BAT ETC XLM ZRX DOGE NEO QTUM STORJ
  ZEN MANA ZEC LINK ENJ NMR REQ TRX
  RLC BNT SYS LSK FIL WAXP ONE THETA
  ONT SNX VET VTHO FLUX COMP LPT FET
  ATOM TFUEL CELR OCEAN COTI ALGO CHZ BAND
  UNI KSM OGN SOL CTSI CELO GRT SLP
  AVAX YFI SHIB CRV DOT SUSHI EGLD ACH
  GALA AAVE APE NEAR AUDIO AXS ROSE API3
  SKL 1INCH LDO FLOW RAD ILV TLM ICP
  KNC ENS BICO VOXEL T OP
```

## H-basket-A (#163) — MEASURABILITY. *This is the headline number.*

Run the incumbent **UNCHANGED** -- same thresholds, same `LIVE_GEOMETRY`,
same 2+2bps costs -- on every ticker in the universe. Per ticker report
STRONG_BUY trades, episodes (trades separated by more than the 15-day max
hold), and whether `ex_best` is DEFINED (>=3 folds with >=10 trades).

**Reported outcome:** how many of the 86 tickers reach a defined
`ex_best`. No pass/fail threshold -- this measures whether the incumbent's
STRONG_BUY tier is assessable at all once event rate is raised. It is a
measurement, not a hypothesis about edge.

## H-basket-B (#164) — EDGE

Pool every ticker's STRONG_BUY trades into ONE series, on DISCOVERY and
on CONFIRMATION separately. Report n, episodes, win%, `net_all`,
`ex_best` (folds cut by TIME, pooled across tickers), `total_R`,
`maxDD_R`. Count-matched placebo, **300 seeds**, drawing from the same
ticker mix and the same dates-per-ticker eligibility as the observed set.

**REGISTERED PASS DIRECTION:** `ex_best` > 0 on BOTH windows AND `net_all`
above the placebo **p95** on BOTH windows. Anything less is a FAIL,
including "almost". Repeated identically for **INC_BUY_ALL** pooled.

## H-basket-C (#165) — REPLICATION

The universe is split into 4 random ticker quartiles with a fixed seed,
**registered here before any scoring**. Report pooled STRONG_BUY
`net_all` and `ex_best` per quartile on SEALED.

**REGISTERED PASS DIRECTION:** positive in ALL FOUR quartiles. This
replaces "all three tickers" as this project's replication test -- four
disjoint ticker sets is a stronger claim than three correlated majors.

Seed = `20260827`, `numpy.random.default_rng(seed).permutation(n)`, 
assigned round-robin `order[k::4]`.

- **Q1** (22): AAVE ALGO AXS BICO BTC CELO CELR FIL ICP ILV IMX KNC LINK NEO ONT RLC SNX STORJ SUSHI T XRP YFI
- **Q2** (22): 1INCH ATOM AVAX BAND BAT BNB CHZ COTI CTSI DOGE EGLD ENJ ETC ETH LPT OCEAN QTUM SKL SYS VTHO ZEC ZRX
- **Q3** (21): ADA BCH BNT ENS FET FLUX LDO LSK MANA NEAR ONE RAD ROSE SLP SOL TFUEL THETA TRX VOXEL WAXP XLM
- **Q4** (21): ACH APE API3 AUDIO COMP CRV DOT FLOW GALA GRT KSM LTC NMR OGN OP REQ SHIB TLM UNI VET ZEN

## H-tier-curve (#166) — DESCRIPTIVE ONLY, SELECTS NOTHING

Pooled n, win%, `net_all`, `ex_best` at `combined_final_score` >= 75, 70,
65, 60 on DISCOVERY. **A curve to look at.** No threshold may be chosen
from it, no rule may be promoted on it, and any future hypothesis that
uses a score cut must be registered separately with its own number and
tested on data this curve did not touch. Recorded so that a later
"we always knew 65 was the level" is checkable against what was
actually seen and when.

## Operating rules for this program

Per-ticker daily bars and the 4h ATR are built ONCE per ticker and reused
(rule 8). No placebo anywhere except H-basket-B. Every result, including
every failure and every skipped ticker, is recorded here. Research
commits stay separate from signal-check commits (rule 6).

## Result of H-basket-A (#163) — recorded 2026-08-27

Incumbent UNCHANGED (`LIVE_GEOMETRY`, same thresholds, 2+2bps per side),
STRONG_BUY tier, SEALED window **2019-09-24 -> 2026-02-26**. Windows common
to all tickers, anchored on BTC. Lockbox 2026-02-26 -> 2026-08-26 never read;
4h feed sealed at the boundary.

### Export outcome: 82 of 86 tickers frozen

| symbol | outcome | detail |
|--------|---------|--------|
| COMPUSDT | **excluded** | run_backtest raised: no overlapping dates between squeeze and technical history |
| SHIBUSDT | **excluded** | run_backtest raised: no overlapping dates |
| IMXUSDT | **excluded** | thin-merged guard: 59 rows after the inner join |
| GRTUSDT | **excluded** | thin-merged guard: 44 rows after the inner join |

The overlap assertion (guard 3) flagged three more that were KEPT, since
excluding a ticker after seeing its data would be rule-4 curation:

- `ONEUSDT` — merged 712 rows vs a raw date intersection of 2,192 (**32.5%**).
  A 1,480-day silent truncation by the `how="inner"` join at pipeline.py:931.
- `UNIUSDT` — 1,636 of 2,006 (81.6%); `APEUSDT` — 1,291 of 1,624 (79.5%).
  Both roughly consistent with indicator warm-up plus gaps.

The overlap fraction compares the merged frame to the RAW date intersection,
which ignores ~200 rows of indicator warm-up and any dropna, so it is an
upper bound. ONE at 32.5% is far beyond that; UNI/APE around 80% are not.

### HEADLINE: 0 of 82 tickers reach a defined `ex_best`

`ex_best` needs >=3 folds carrying >=10 trades each, i.e. >=30 trades placed
in the right shape across 6.4 years. **No ticker in the basket reaches it.**
The densest, BICO, fires 32 STRONG_BUY trades — which spread over 4 folds is
8 per fold, under the bar. Raising event rate from 3 tickers to 82 moved the
count from 0 of 3 to **0 of 82**.

- tickers with 0 STRONG_BUY trades: **3** (ENJ, ONE, THETA)
- median trades per ticker: **6**
- total STRONG_BUY trades across the basket: **645**
- total independent episodes (>15d apart): **306**
- best single ticker: BICO, 32 trades / 8 episodes — still 0 counted folds

The tier is not rare because BTC is unusual. It is rare **per ticker,
everywhere**, and widening the universe does not fix that: it produces many
thin per-ticker records rather than one thick one. Pooling (H-basket-B) is
the only route to a defined `ex_best`, and pooling is exactly what breaks
the per-ticker independence `ex_best` assumes.

### DEFECT FOUND — 2-decimal rounding corrupts sub-dollar tickers

**This program surfaced a latent defect in the incumbent.**
`signal_engines.compute_exit_levels` returns `entry`, `target` and `stop`
**rounded to 2 decimals** (signal_engines.py:495-497). At BTC's $78,000 that
is immaterial. For a token trading at $0.00145, entry, target and stop all
round to `0.00`, and then:

- `stop_dist = abs(entry - stop) = 0`, so `resolve_on_4h` returns
  `pnl_r = nan` (pipeline.py:1586, the `if stop_dist else nan` branch);
- `hi >= target` is trivially true against a target of `0.00`, so the trade
  is labelled **`target`** on its first bar — a manufactured 100% win rate;
- `stats_from_trades` averages with `.mean()`, which SKIPS NaN. So `win%`
  is computed over ALL trades while `net_all` is computed over only the
  non-NaN ones. **The two columns describe different trade sets.**

That is why the raw table contains impossible rows: SYS at 75% win and
-1.003R, RAD at 84.2% and -1.000R, and SLP/VTHO/NMR at 100% win with a NaN
expectancy.

Measured contamination on SEALED:

- **185 of 645 STRONG_BUY trades (28.7%) carry `pnl_r = NaN`**
- **35 of 82 tickers** have at least one such trade
- 29 of the 45 tickers under $1 median close are affected — and so are 6
  tickers ABOVE $1 (e.g. RAD, median $1.25, 84% of its trades NaN). The
  trigger is not price alone: it is `1.5 x ATR` falling under half a cent in
  absolute terms, so low volatility reaches it at higher prices too.

**The headline survives this.** On the 44 clean tickers (no NaN trades,
224 trades), the answer is still **0 of 44** with a defined `ex_best`. Trade
COUNTS are unaffected by the rounding; only the P&L columns are.

**Consequence for H-basket-B and H-basket-C: they must not run yet.** Both
pool `net_all` and `ex_best` across tickers, and 28.7% of the pooled trades
would contribute a NaN that `.mean()` silently drops — pooling a biased
subset while reporting a win rate over the full set. The fix belongs in
`signal_engines.compute_exit_levels`, a core file, so under research rule 1
it is a separate decision and a separate commit, not something research
changes on its own. It also alters live behaviour for any sub-dollar asset.

### Per-ticker table (SEALED, STRONG_BUY)

`net_all` / `win%` marked * are contaminated by the rounding defect and
must not be read as results. `ex_best` is `—` for every ticker: none
reached 3 counted folds.

| ticker | events | trades | episodes | win% | net_all | ex_best | folds+/counted |
|--------|--------|--------|----------|------|---------|---------|----------------|
| BICO | 43 | 32 | 8 | 62.5 | -1.004 | — | 0/1 |
| OGN | 51 | 32 | 11 | 56.2 | -0.801 | — | 0/2 |
| VOXEL | 44 | 29 | 9 | 69.0 | -0.161 | — | 0/1 |
| ILV | 36 | 23 | 9 | 21.7 | -0.595 | — | 0/1 |
| T | 38 | 22 | 8 | 4.5 | -1.000 | — | 0/1 |
| SYS | 30 | 20 | 5 | 75.0 | -1.003 | — | 0/1 |
| RAD | 27 | 19 | 2 | 84.2 | -1.000 | — | 0/1 |
| BTC | 30 | 19 | 8 | 73.7 | +1.653 | — | 1/1 |
| OCEAN | 26 | 17 | 4 | 47.1 | -0.371 | — | 0/1 |
| TLM | 26 | 16 | 7 | 56.2 | -1.000 | — | 0/1 |
| LSK | 25 | 15 | 7 | 26.7 | -1.004 | — | 0/0 |
| REQ | 23 | 14 | 3 | 57.1 | -1.000 | — | 0/0 |
| API3 | 23 | 13 | 6 | 53.8 | -0.168 | — | 0/0 |
| BNT | 24 | 13 | 7 | 46.2 | -0.419 | — | 0/0 |
| FLOW | 22 | 12 | 5 | 58.3 | -0.351 | — | 0/0 |
| RLC | 23 | 12 | 6 | 33.3 | -1.010 | — | 0/1 |
| FLUX | 19 | 12 | 5 | 16.7 | -0.342 | — | 0/1 |
| COTI | 23 | 11 | 6 | 36.4 | -1.002 | — | 0/0 |
| WAXP | 21 | 11 | 7 | 45.5 | -0.501 | — | 0/0 |
| ZEC | 16 | 10 | 4 | 0.0 | -1.024 | — | 0/0 |
| SKL | 21 | 10 | 7 | 10.0 | -1.000 | — | 0/0 |
| DOGE | 17 | 10 | 4 | 90.0 | +0.736 | — | 0/0 |
| KSM | 19 | 10 | 4 | 10.0 | -0.692 | — | 0/0 |
| CELR | 21 | 9 | 5 | 77.8 | -0.779 | — | 0/0 |
| KNC | 14 | 9 | 5 | 44.4 | -0.004 | — | 0/0 |
| ETH | 21 | 9 | 6 | 44.4 | +0.587 | — | 0/0 |
| BNB | 21 | 9 | 5 | 66.7 | +1.390 | — | 0/0 |
| XLM | 18 | 8 | 5 | 25.0 | -0.389 | — | 0/0 |
| YFI | 14 | 8 | 5 | 25.0 | -0.131 | — | 0/0 |
| TFUEL | 20 | 8 | 6 | 0.0 | -1.001 | — | 0/0 |
| LINK | 14 | 8 | 5 | 12.5 | -0.577 | — | 0/0 |
| ADA | 15 | 7 | 5 | 28.6 | -0.435 | — | 0/0 |
| BAT | 15 | 7 | 3 | 28.6 | -1.000 | — | 0/0 |
| AXS | 19 | 7 | 5 | 42.9 | +0.539 | — | 0/0 |
| NEO | 16 | 7 | 2 | 42.9 | +0.516 | — | 0/0 |
| APE | 12 | 7 | 4 | 42.9 | +0.658 | — | 0/0 |
| XRP | 15 | 7 | 4 | 42.9 | +0.414 | — | 0/0 |
| VET | 20 | 6 | 5 | 50.0 | -0.930 | — | 0/0 |
| QTUM | 14 | 6 | 4 | 50.0 | +0.469 | — | 0/0 |
| FIL | 13 | 6 | 4 | 16.7 | -0.432 | — | 0/0 |
| CTSI | 12 | 6 | 4 | 66.7 | -1.000 | — | 0/0 |
| ATOM | 14 | 6 | 3 | 83.3 | +2.030 | — | 0/0 |
| ALGO | 10 | 6 | 3 | 33.3 | -0.342 | — | 0/0 |
| SLP | 12 | 6 | 4 | 100.0 | NaN | — | 0/0 |
| ZEN | 9 | 5 | 2 | 0.0 | -1.022 | — | 0/0 |
| CHZ | 12 | 5 | 4 | 0.0 | -1.000 | — | 0/0 |
| ACH | 7 | 5 | 2 | 0.0 | -1.000 | — | 0/0 |
| BAND | 17 | 5 | 3 | 20.0 | -0.350 | — | 0/0 |
| 1INCH | 9 | 5 | 2 | 80.0 | +1.576 | — | 0/0 |
| VTHO | 15 | 5 | 3 | 100.0 | NaN | — | 0/0 |
| EGLD | 14 | 5 | 4 | 40.0 | +0.431 | — | 0/0 |
| MANA | 10 | 5 | 1 | 40.0 | +0.267 | — | 0/0 |
| ICP | 18 | 5 | 3 | 40.0 | +0.434 | — | 0/0 |
| GALA | 13 | 5 | 3 | 40.0 | -1.000 | — | 0/0 |
| ONT | 14 | 5 | 3 | 80.0 | +0.983 | — | 0/0 |
| ROSE | 10 | 4 | 3 | 50.0 | -1.000 | — | 0/0 |
| LTC | 12 | 4 | 3 | 75.0 | +1.726 | — | 0/0 |
| BCH | 13 | 4 | 3 | 0.0 | -1.054 | — | 0/0 |
| ENS | 8 | 4 | 2 | 25.0 | -0.154 | — | 0/0 |
| TRX | 4 | 3 | 1 | 100.0 | -0.006 | — | 0/0 |
| AUDIO | 10 | 3 | 3 | 33.3 | -1.000 | — | 0/0 |
| SUSHI | 10 | 3 | 2 | 66.7 | -1.043 | — | 0/0 |
| DOT | 7 | 3 | 2 | 33.3 | +0.061 | — | 0/0 |
| ETC | 9 | 3 | 1 | 100.0 | +2.644 | — | 0/0 |
| OP | 8 | 3 | 2 | 0.0 | -1.025 | — | 0/0 |
| NEAR | 7 | 3 | 2 | 33.3 | +0.308 | — | 0/0 |
| FET | 8 | 2 | 2 | 0.0 | -1.022 | — | 0/0 |
| AVAX | 8 | 2 | 2 | 50.0 | +0.790 | — | 0/0 |
| STORJ | 5 | 2 | 2 | 0.0 | -1.013 | — | 0/0 |
| UNI | 7 | 2 | 2 | 100.0 | +2.697 | — | 0/0 |
| LDO | 7 | 2 | 1 | 0.0 | -1.000 | — | 0/0 |
| CELO | 7 | 2 | 2 | 0.0 | -1.033 | — | 0/0 |
| AAVE | 8 | 1 | 1 | 100.0 | +2.644 | — | 0/0 |
| LPT | 3 | 1 | 1 | 100.0 | +2.625 | — | 0/0 |
| ZRX | 5 | 1 | 1 | 100.0 | +3.314 | — | 0/0 |
| NMR | 7 | 1 | 1 | 100.0 | NaN | — | 0/0 |
| CRV | 6 | 1 | 1 | 100.0 | +1.933 | — | 0/0 |
| SNX | 5 | 1 | 1 | 100.0 | +2.959 | — | 0/0 |
| SOL | 6 | 1 | 1 | 100.0 | +2.644 | — | 0/0 |
| ENJ | 3 | 0 | 0 | — | — | — | 0/0 |
| ONE | 1 | 0 | 0 | — | — | — | 0/0 |
| THETA | 1 | 0 | 0 | — | — | — | 0/0 |

Full machine-readable table: `research/basket_A_strong_buy.csv`.
Basket frames: `data/basket/` (19MB, gitignored; MANIFEST records every
ticker's status, spans and overlap fraction).

## Exit-level rounding defect — FIXED, and H-basket-A re-run

Commit `ffa3191`, tests first. Recorded here because the H-basket-A
numbers above were produced with the defect present.

### What was wrong

`compute_exit_levels` rounded entry/target/stop to a FIXED 2 decimals.
For an asset at $0.00145 all three collapse onto `0.00`, so `stop_dist`
was 0, `resolve_on_4h` returned NaN `pnl_r`, `high >= target` was
trivially true against a target of 0.00 (a manufactured 100% win rate),
and `stats_from_trades` averaged with `.mean()`, which SKIPS NaN --
reporting a win rate over every trade and an expectancy over only the
survivors. **The live bot has been publishing with this**; BTC/ETH/SOL
were never affected, which is why 5.5 years of reporting never caught it.

### The fix

- `_price_round`: 8 SIGNIFICANT FIGURES relative to the entry price, so
  the geometry is identical at $78,000 and $0.00145. All three levels
  round against the same reference, preserving their spacing.
- `compute_exit_levels` never returns a zero stop distance (falls back to
  unrounded, else `applicable=False`), and now returns `stop_dist`.
- `resolve_on_4h` RAISES on zero stop distance instead of returning NaN.
- `stats_from_trades` RAISES on any NaN P&L instead of averaging around it.
- 8 new tests (`TestExitLevelPrecision`), 6 of which failed on the old
  code. Suite: **381 passed, 2 skipped**.

### Verification after the fix

| check | result |
|-------|--------|
| trades with NaN `pnl_r` | **0** (was 185 of 645, 28.7%) |
| 100%-win rows with NaN expectancy | **0** (was 3: SLP, VTHO, NMR) |
| rows above the 2.667R theoretical max | **0** (ZRX previously showed +3.314R) |
| tickers whose `net_all` changed | 74 of 82 |
| tickers unchanged | 8, including BTC and ETH bit-identical |

| ticker | n | win% before | win% after | net_all before | net_all after |
|--------|---|-------------|------------|----------------|---------------|
| BTC | 19 | 73.7 | 73.7 | +1.653 | +1.653 |
| ETH | 9 | 44.4 | 44.4 | +0.587 | +0.587 |
| BICO | 32 | 62.5 | 65.6 | -1.004 | -3.250 |
| SYS | 20 | 75.0 | 80.0 | -1.003 | -5.671 |
| RAD | 19 | 84.2 | 84.2 | -1.000 | -9.323 |
| SLP | 6 | 100.0 | 33.3 | NaN | +0.165 |
| VTHO | 5 | 100.0 | 20.0 | NaN | -0.301 |

**The H-basket-A headline is unchanged: 0 of 82 tickers reach a defined
`ex_best`**, on 645 trades and 306 episodes — identical counts, because
the defect corrupted P&L columns, never trade selection.

### NEW FINDING — the fix exposed degenerate ATR geometry on illiquid pairs

Removing the NaN mask revealed something underneath. BICO went -1.004 ->
-3.250R, SYS -1.003 -> -5.671R, RAD -1.000 -> **-9.323R**. A stop is -1R,
so a mean of -9.3R looks impossible. It is not, and the arithmetic is now
correct: `pnl_r` is properly bounded (-1.0 to +2.7). The magnitude comes
entirely from `cost_r = 8bps / stop_fraction`. When the stop sits 0.025%
from entry, 8bps of round-trip cost IS 3.2R of risk.

Why the stops are that tight: **these pairs barely trade on Binance.US, so
their 4h bars are flat and the ATR collapses.**

| | flat 4h bars (High==Low) | median stop | median `cost_r` |
|---|---|---|---|
| BTC | 0.0% | 1.776% | 0.045R |
| ETH | 0.0% | 2.003% | 0.040R |
| SOL | 0.4% | 2.116% | 0.038R |
| RAD | **73.3%** | **0.025%** | **3.24R** |
| BICO | 70.9% | 0.050% | 1.61R |
| LSK | **77.2%** | 0.070% | 1.14R |

Across the 79 tickers that placed a trade: median flat-bar share **28.5%**
(worst 79.1%); **46 tickers above 20%**, **20 above 50%**; **18 tickers**
have a median `cost_r` above 0.1R and **9 above 1.0R**, against ~0.04R for
the majors. Per-ticker figures in `research/basket_liquidity_health.csv`.

**This is a real economic result, not an artifact:** on an asset whose ATR
is a rounding error, an ATR-derived stop is not a risk unit, and the trade
is uneconomic before it starts. But it means a pooled `net_all` over the
basket would be dominated by cost artifacts from pairs that cannot
actually be traded at this geometry.

**Open decision before H-basket-B/C.** A liquidity precondition (e.g. a
maximum flat-bar share, or a minimum stop fraction) would be the honest
way to keep the pool tradeable — but the universe was registered at 86
BEFORE any of this was seen, so narrowing it now is a NEW hypothesis
needing its own number and its own pre-registration (research rule 4). It
must not be applied retroactively to #163-#166 as though it had always
been there. Recorded, not decided.

## Hypothesis #167 — TRADABILITY FILTER (registered before B/C ran)

**#163-#166 STAND AS REGISTERED.** They were registered on the full
86-ticker universe and that is the universe they describe. Nothing about
them is being rewritten, narrowed, or re-run under a new definition.
**#167 is a TRADABLE-SUBSET VARIANT** carried alongside them, not a
replacement for them. H-basket-B is reported on BOTH the #167 subset and
the full 82 so the filter's effect is visible rather than hidden.

### The filter, defined on PRICES ONLY and decided now

A ticker is **tradable** if, over SEALED:

1. its share of flat 4h bars (`High == Low`) is **<= 10%**, AND
2. its median `1.5 x ATR` stop is **>= 0.5% of entry**.

Both are properties of the price series alone. Neither looks at a
direction label, a trade outcome, an expectancy, or any result from
#163-#166. The motivation is recorded above: on pairs that barely trade
on Binance.US the 4h bars are flat, the ATR collapses, and the derived
stop lands 0.025% from entry — at which point 8bps of round-trip cost is
3.2R of risk and the trade is uneconomic before it starts. The filter
removes instruments whose ATR is not a usable risk unit. It is NOT a
performance screen.

### Result: 26 of 82 tradable

All 56 exclusions fail on the flat-bar criterion; **0 tickers fail the
stop criterion independently** (the two are near-collinear, as expected —
flat bars are what collapse the ATR).

**TRADABLE (26):**

| ticker | flat 4h bars | median 1.5xATR stop |
|--------|--------------|---------------------|
| BTC | 0.02% | 2.250% |
| ETH | 0.02% | 2.969% |
| ADA | 0.02% | 3.657% |
| BNB | 0.04% | 2.749% |
| XRP | 0.06% | 2.817% |
| LTC | 0.16% | 3.455% |
| VET | 0.19% | 4.382% |
| LINK | 0.21% | 3.588% |
| AVAX | 0.27% | 3.851% |
| SOL | 0.39% | 4.284% |
| XLM | 0.50% | 3.419% |
| DOT | 0.83% | 3.397% |
| ALGO | 1.22% | 3.710% |
| ONE | 1.40% | 5.118% |
| ATOM | 1.49% | 4.158% |
| DOGE | 1.57% | 3.662% |
| BCH | 1.84% | 3.404% |
| TRX | 3.48% | 1.982% |
| VTHO | 3.48% | 4.920% |
| NEAR | 3.53% | 4.134% |
| FET | 4.66% | 4.879% |
| AAVE | 4.67% | 3.947% |
| UNI | 4.68% | 4.301% |
| GALA | 6.53% | 4.476% |
| OP | 7.18% | 4.023% |
| ETC | 7.60% | 3.659% |

**EXCLUDED (56):** APE MANA THETA ZEC NEO ICP BAT FIL CRV ZRX ZEN FLUX ROSE LPT ONT 1INCH EGLD ENS AXS ENJ BAND TFUEL STORJ LDO AUDIO SUSHI ACH QTUM KNC SNX WAXP CHZ OCEAN NMR KSM YFI CTSI API3 COTI SLP CELO FLOW CELR SYS SKL ILV VOXEL OGN RLC TLM T BICO REQ RAD LSK BNT

### Amendment registered now: EPISODE-MATCHED PLACEBO

H-basket-B's placebo draws random **EPISODES matching the incumbent's
observed run-length distribution per ticker**, not independent days.

Why, recorded before the numbers: the incumbent's 19 BTC STRONG_BUY
trades come from only **8 episodes** — consecutive signal days riding one
price move, several of which exit on the same 4h bar. An independent-day
placebo scatters its draws and gets near-independent outcomes, so it is
**lower-variance than the thing it benchmarks**, and the incumbent clears
its p95 far more easily than the percentile implies. That flaw was
already recorded against the Prompt-1 reference rows; this fixes it.

Construction, per ticker: take the observed run-lengths of consecutive
STRONG_BUY signal days; draw the same NUMBER of runs with the same
LENGTHS at random non-overlapping start positions in the same window;
apply the same 2-day confirm, so a run of length L yields L-1 trades
exactly as the observed runs do. **300 seeds.**

Everything else in H-basket-B and H-basket-C is unchanged from #164/#165:
the same pooled statistics, the same time-cut folds, and the same
registered pass directions — `ex_best` > 0 on BOTH windows AND `net_all`
above the placebo p95 on BOTH for B; positive in ALL FOUR quartiles for C.
H-tier-curve (#166) stays DESCRIPTIVE and selects nothing.

## Results of H-basket-B (#164), H-basket-C (#165), H-tier-curve (#166)

Run on the #167 tradable subset (26 tickers) and, for B, on the full 82
alongside so the filter's effect is visible rather than hidden. Placebo is
the episode-matched draw registered in #167: 300 seeds, random runs
matching each ticker's observed run-length distribution.

SEALED 2019-09-24 -> 2026-02-26 | DISCOVERY -> 2023-04-06 | CONFIRMATION
-> 2026-02-26. Every trade produced by `pipeline.backtest_exit_geometry`
with `LIVE_GEOMETRY`; the day->trade lookup used to make 300-seed
placebos tractable was verified to reproduce `harness.incumbent_rows`
trade-for-trade on both tiers before any of this was reported.

### H-basket-B — ALL FOUR VARIANTS FAIL

Registered direction: `ex_best` > 0 on BOTH windows AND `net_all` above
the placebo p95 on BOTH.

| variant | window | n | eps | win% | net_all | ex_best | folds+/cnt | totR | maxDD | plc mean | plc p95 | ex>0 | net>p95 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| tradable 26 / STRONG_BUY | DISCOVERY | 46 | 31 | 34.8 | +0.239 | — | 1/2 | +11.0 | 13.6 | +0.071 | +0.570 | N | N |
| tradable 26 / STRONG_BUY | CONFIRMATION | 87 | 52 | 50.6 | +0.815 | +0.424 | 4/4 | +70.9 | 15.2 | -0.027 | +0.332 | Y | Y |
| FULL 82 / STRONG_BUY | DISCOVERY | 122 | 70 | 38.5 | +0.368 | +0.194 | 2/3 | +44.9 | 34.8 | +0.079 | +0.407 | Y | N |
| FULL 82 / STRONG_BUY | CONFIRMATION | 518 | 240 | 46.9 | -2.016 | -2.614 | 0/4 | -1044.4 | 1072.1 | -0.125 | +0.050 | N | N |
| tradable 26 / INC_BUY_ALL | DISCOVERY | 1678 | 496 | 33.6 | -0.011 | -0.030 | 3/4 | -18.7 | 115.5 | +0.209 | +0.280 | N | N |
| tradable 26 / INC_BUY_ALL | CONFIRMATION | 2414 | 661 | 36.2 | +0.067 | +0.010 | 3/4 | +162.9 | 110.8 | +0.015 | +0.068 | Y | N |
| FULL 82 / INC_BUY_ALL | DISCOVERY | 3639 | 1098 | 33.0 | -0.031 | -0.054 | 1/4 | -111.7 | 383.1 | +0.136 | +0.185 | N | N |
| FULL 82 / INC_BUY_ALL | CONFIRMATION | 8453 | 2185 | 33.7 | -0.195 | -0.234 | 0/4 | -1650.4 | 1701.4 | -0.088 | -0.052 | N | N |

- **tradable 26 / STRONG_BUY: FAIL**
- **FULL 82 / STRONG_BUY: FAIL**
- **tradable 26 / INC_BUY_ALL: FAIL**
- **FULL 82 / INC_BUY_ALL: FAIL**

**Why each failed.**

- *tradable 26 / STRONG_BUY* — CONFIRMATION passes BOTH conditions
  cleanly (net +0.815 vs p95 +0.332, `ex_best` +0.424, 4 of 4 folds
  positive). DISCOVERY does not: `ex_best` is UNDEFINED (only 2 folds
  reach 10 trades) and net +0.239 sits below its p95 of +0.570. The rule
  requires both windows. **One good window is not the hypothesis.**
- *FULL 82 / STRONG_BUY* — CONFIRMATION collapses to **-2.016R** with
  totR **-1044R**. That is the illiquidity cost artifact recorded above:
  518 pooled trades against the tradable subset's 87, the extra 431
  coming from pairs whose ATR-derived stop is a fraction of a percent, so
  `cost_r = 8bps / stop_fraction` dominates. This is the filter's effect
  made visible: **+0.815 tradable vs -2.016 unfiltered on the same
  window.**
- *tradable 26 / INC_BUY_ALL* — CONFIRMATION misses by **0.001R**: net
  +0.067 against a placebo p95 of +0.068. Recorded as a FAIL exactly as
  registered. "Almost" was pre-declared to be a failure and it is being
  treated as one; it does not get a second look at a looser bar.
  DISCOVERY is negative anyway (-0.011, `ex_best` -0.030).
- *FULL 82 / INC_BUY_ALL* — negative on both windows.

Note the placebo is not weak. On DISCOVERY/INC_BUY_ALL the episode-
matched placebo MEAN (+0.209 tradable, +0.136 full) BEATS the incumbent's
observed net (-0.011, -0.031). Random clustered entries did better than
the signal on that window.

### H-basket-C — FAIL (3 of 4 quartiles positive, not 4)

Registered direction: pooled STRONG_BUY `net_all` AND `ex_best` positive
in ALL FOUR quartiles on SEALED. Quartiles fixed by seed 20260827 before
any scoring; membership here is each quartile intersected with the #167
tradable subset.

| quartile | tradable/total | n | eps | win% | net_all | ex_best | folds+/cnt | totR | maxDD |
|---|---|---|---|---|---|---|---|---|---|
| Q1 | 5/22 | 41 | 21 | 48.8 | +0.743 | — | 2/2 | +30.5 | 7.4 |
| Q2 | 7/22 | 44 | 24 | 56.8 | +1.044 | +0.600 | 3/3 | +45.9 | 4.2 |
| Q3 | 8/21 | 28 | 19 | 21.4 | -0.250 | — | 1/2 | -7.0 | 9.9 |
| Q4 | 6/21 | 23 | 17 | 47.8 | +0.723 | — | 1/1 | +16.6 | 6.3 |

- Q1: AAVE ALGO BTC LINK XRP
- Q2: ATOM AVAX BNB DOGE ETC ETH VTHO
- Q3: ADA BCH FET NEAR ONE SOL TRX XLM
- Q4: DOT GALA LTC OP UNI VET

**VERDICT: FAIL.** Q3 is negative (-0.250R on 28 trades). And the deeper
problem is that `ex_best` — the statistic the pass condition names — is
**UNDEFINED in three of the four quartiles**: Q1, Q3 and Q4 never reach 3
folds carrying 10 trades. Only Q2 can produce the number at all. So C does
not fail narrowly; it fails because splitting an already-thin signal four
ways leaves nothing measurable. This is H-basket-A's finding (0 of 82
tickers reach a defined `ex_best`) reappearing one level up.

### H-tier-curve (#166) — DESCRIPTIVE, SELECTS NOTHING

DISCOVERY, tradable subset, days at or above the score painted STRONG_BUY
so the geometry is constant across the curve and the rows are comparable.

| score >= | n | eps | win% | net_all | ex_best | folds+/cnt | totR | maxDD |
|---|---|---|---|---|---|---|---|---|
| 75 | 46 | 31 | 34.8 | +0.239 | — | 1/2 | +11.0 | 13.6 |
| 70 | 256 | 128 | 29.3 | +0.044 | -0.060 | 2/4 | +11.3 | 42.0 |
| 65 | 908 | 349 | 30.0 | +0.070 | +0.016 | 3/4 | +63.8 | 83.5 |
| 60 | 1782 | 503 | 29.7 | +0.068 | +0.029 | 3/4 | +120.4 | 114.5 |

The curve is NOT monotonic in the way a real conviction ladder would be.
The highest tier (>=75) has the best net (+0.239) but only 46 trades and
no computable `ex_best`; >=70 is the WORST row (+0.044, `ex_best`
-0.060); >=65 and >=60 are flat at +0.070/+0.068 with `ex_best` barely
above zero (+0.016/+0.029) on 908 and 1,782 trades. Loosening the score
buys trade count and buys almost no edge.

**NOTHING IS SELECTED FROM THIS.** Per #166 no threshold may be promoted
on the strength of this curve; any future use of a score cut is a NEW
hypothesis with its own number, tested on data this curve did not touch.
It is recorded so a later "we always knew 65 was the level" is checkable
against what was actually seen, and when.

### Program status after #163-#167

Every registered hypothesis in the EVENT RATE program has now failed:
#163 (0 of 82 tickers measurable), #164 (all four B variants), #165
(3 of 4 quartiles, and unmeasurable in three). #166 is descriptive and
selects nothing. #167 did what it was for — it made the difference
between +0.815 and -2.016 on the same window visible — but a filter is
not a result.


---

## Provenance — derivatives data collection (NOT a hypothesis)

`research/collect_derivs.py`, workflow `derivs-collect.yml`, writing to
`data/derivatives/`. **This has no number, no registered direction and no
pass condition, because it is not a test.** It is data collection, recorded
here so that its existence and its limits are on the record before anyone
looks at it.

**The free history is capped, and that is the whole problem.**

| source | window available | granularity |
|--------|------------------|-------------|
| Kraken Futures funding | ~1 year, rolling | hourly |
| OKX funding | ~3 months | 8h settlements |
| OKX open interest | 180 rows (~6 months) | daily |

Binance's futures API, which does hold full history, returns HTTP 451 from
here and from Azure-hosted GitHub runners; Bybit returns 403. Neither is
reachable.

**So this data supports NO testable hypothesis today.** A pre-lockbox window
worth anything needs roughly a year of accumulation from now: the standard
lockbox rule seals the last 6 months at analysis time, so a year collected
leaves ~6 months usable, which is the bare minimum before a fold structure
means anything. Until then there is nothing here to register a hypothesis
against, and none should be registered.

**When it IS eventually tested, the ordinary rules apply unchanged.** The
lockbox is applied at ANALYSIS time, not at collection time -- the last 6
months of whatever exists then are sealed, exactly as for price data
(research rule 2). Collecting a row does not exempt it; a row collected
today will be inside the lockbox when it is finally analysed if it falls in
the last 6 months at that point.

**Why start now anyway.** This series cannot be bought back later. Every day
not collected is a day permanently outside the eventual sample, because the
venues discard it. Starting the clock is the entire point of the exercise.

**Merge, not append.** Each run pulls the FULL available window and merges
on `(symbol, timestamp)`, so the operation is idempotent, a missed run
self-heals as long as the gap is shorter than the venue's window, and the
first run backfills a free year of Kraken funding. On a collision the value
already on disk wins and the collision is counted and printed -- a venue
revising its own history is something to find out about, not to adopt
silently.

---

# DRAFT PRE-REGISTRATION — 1h PROGRAM (#168–#170)

> **STATUS: REGISTERED 2026-08-28, WITH AMENDMENTS. NOTHING RUN YET.**
> Approved by the maintainer with three amendments, all recorded below and
> all made BEFORE any data was exported or any number computed. From this
> commit onward research rule 4 applies: no parameter, threshold or pass
> condition here may be changed on the basis of a result.
>
> **Amendments applied at approval:**
> 1. #168's absolute +0.90R floor **REMOVED** and replaced with a
>    placebo-relative condition. Reasoning recorded in full at #168 below.
> 2. #169's gate **binds per ticker on DISCOVERY**, not on the pooled or
>    full-span count.
> 3. The pagination fix gains a **loud truncation assertion**, not just a
>    raised ceiling.

## The question

Does the squeeze construction replicate at 1h resolution, and does it produce
enough events to make `ex_best` **definable for the first time**?

`ex_best` has never once been computable for the incumbent's STRONG_BUY tier:
not on 3 tickers (#42–#162), not on 82 (#163: 0 of 82), not pooled four ways
(#165: undefined in 3 of 4 quartiles). Event rate by universe width failed.
This tests event rate by **resolution** instead.

Two arms, deliberately answering different questions:

- **ARM A (time-equivalent)** rescales every parameter so the model spans the
  same wall-clock time at 1h as at 4h. If the phenomenon is real it should
  survive being measured on finer bars. This is a **robustness** test.
- **ARM B (bar-equivalent, fractal)** keeps every parameter's BAR count, so
  the identical construction runs on a 4x shorter timescale. This is the
  **measurability** play: 4x the bars in the same calendar span, so ~4x the
  candidate events, which is the only untried route to a defined `ex_best`.

---

## Parameter tables — fully specified, nothing left to choose later

### ARM A — time-equivalent (holds WALL-CLOCK constant)

Derived from the 10-site portability map. Every value is `4h value x 4`,
because one 4h bar is four 1h bars. No value is chosen; all are derived.

| # | site | 4h production | ARM A (1h) | derivation |
|---|------|---------------|------------|------------|
| 1 | `backtest_squeeze_history` interval | `"4h"` | `"1h"` | the change itself |
| 2 | `add_squeeze_features` `bb_period` | 20 | **80** | 20 x 4 |
| 3 | `add_squeeze_features` `percentile_lookback` | 120 | **480** | 120 x 4 |
| 4 | duration scaler (pipeline.py:880) | `/40` | **`/160`** | 40 x 4 |
| 5 | `compute_initial_score` `max_duration_for_scaling` | 40 | **160** | 40 x 4 |
| 6 | ATR period | 14 | **56** | 14 x 4 = 56 hours either way |
| 7 | `bars_per_day` | 6 | **24** | bars in a day |
| 8 | `max_hold_days` → bars | 15d = 90 bars | **360 bars** | 15 x 24 |
| 9 | confirm | 2 days | **48 bars** | 2 x 24 hours |
| 10 | `short_sma_filter` | 50 days | **1200 bars** | 50 x 24 (long-only: inert) |
| — | `stop_mult` / `target_mult` | 1.5 / 3.0 | **1.5 / 3.0** | UNCHANGED — dimensionless |
| — | conviction scale STRONG_* | 1.333 | **1.333** | UNCHANGED — dimensionless |
| — | `buy_bar` / `sell_bar` | 60 / 40 | **60 / 40** | UNCHANGED — score space |

### ARM B — bar-equivalent / fractal (holds BAR COUNT constant)

Every parameter identical to production. Only the bar duration changes, so the
whole construction runs on a timescale 4x shorter.

| # | site | 4h production | ARM B (1h) | effective wall-clock |
|---|------|---------------|------------|----------------------|
| 2 | `bb_period` | 20 | **20** | 80h → 20h |
| 3 | `percentile_lookback` | 120 | **120** | 480h → 120h |
| 4/5 | duration scaler / max_duration | 40 | **40** | 160h → 40h |
| 6 | ATR period | 14 | **14** | 56h → 14h |
| 7 | `bars_per_day` | 6 | **24** | calendar fact, not a parameter |
| 8 | hold | 90 bars (15d) | **90 bars** | 15d → 3.75d |
| 9 | confirm | 2 bars (2d) | **2 bars** | 2d → 2h |
| 10 | `short_sma_filter` | 50 bars | **50 bars** | long-only: inert |
| — | multipliers, conviction, bars | as production | **unchanged** | dimensionless |

### Geometry dicts — `LIVE_GEOMETRY` IS NOT TOUCHED

Both arms define their own dict in `research/`, never in `pipeline.py`
(research rule 1). `LIVE_GEOMETRY` remains the single source of truth for what
the live bot does, and is read, never written.

    # research/geometry_1h.py  (to be written on approval)
    ARM_A = {"atr_source": "1h", "atr_period": 56, "max_hold_bars": 360,
             "stop_mult": 1.5, "target_mult": 3.0, "confirm_bars": 48,
             "short_sma_filter": 1200, "bars_per_day": 24,
             "bb_period": 80, "percentile_lookback": 480, "max_duration": 160}
    ARM_B = {"atr_source": "1h", "atr_period": 14, "max_hold_bars": 90,
             "stop_mult": 1.5, "target_mult": 3.0, "confirm_bars": 2,
             "short_sma_filter": 50, "bars_per_day": 24,
             "bb_period": 20, "percentile_lookback": 120, "max_duration": 40}

Note `atr_source: "1h"` is a THIRD branch. `backtest_exit_geometry` currently
raises on anything but `"daily"`/`"4h"` (pipeline.py:1606), so the 1h path runs
through a research-side resolver rather than by editing that switch.

---

## Entry convention on 1h bars — exact, no ambiguity

Bars are indexed by `open_time`; bar `t` covers `[t, t+1h)` and its close
occurs at `t+1h`.

1. **Signal state.** Each bar `t` carries a direction label computed from data
   through bar `t`'s close. No value from `t+1` onward may enter it.
2. **Confirm.** Bar `t` is CONFIRMED when the labels on bars `t-(C-1) … t` are
   all identical and actionable, where `C` = 48 (ARM A) or 2 (ARM B). This is
   the exact analogue of `confirm_days=2` requiring two identical consecutive
   daily labels (pipeline.py:1616-1622).
3. **Entry.** Entry price is the **Close of the confirming bar `t`**. Entry
   timestamp is `t + 1h` — the moment that close is known. This mirrors the
   4h/daily rule exactly, where `entry_ts = day.normalize() + 24h` is the
   signal day's close (pipeline.py:1637).
4. **Resolution.** Walk bars with `open_time >= t + 1h`, i.e. strictly after
   the entry moment, for at most `max_hold_bars`. Anything earlier is
   lookahead.
5. **Pessimism rule, unchanged.** Target and stop touched within the same bar
   counts as `ambiguous_stop` at −1R. Timeout closes at the last bar's Close.
   Unresolved at the end of history returns `outcome=None` and is DROPPED,
   never counted.

**One event, one trade.** As at 4h, a run of `L` consecutive confirmed bars
yields `L − C + 1` trades; overlapping positions are permitted exactly as the
incumbent permits them, and episode counting (gap > hold horizon) is reported
alongside `n` so clustering stays visible.

---

## Cost model — and the caveat that must be reported per arm

Costs are walkforward's defaults, unchanged: **2bps fee + 2bps slippage per
side = 8bps round trip**, and `cost_r = 8bps / stop_fraction` where
`stop_fraction = 1.5 x ATR / entry`.

**REGISTERED CAVEAT, stated before any result exists.** True range scales
roughly with the square root of bar duration, so a 1h ATR is roughly **half** a
4h ATR. The stop sits at `1.5 x ATR`, so the stop fraction roughly halves and
**`cost_r` roughly DOUBLES at 1h, in BOTH arms.**

This is not avoided by ARM A's longer lookback: ATR-56 on 1h bars averages 56
*hourly* true ranges, which is a smaller quantity than 14 *four-hourly* true
ranges over the same 56 hours. Matching the lookback in time does not match the
magnitude.

Measured 4h baseline to compare against (from #163's liquidity table):

| ticker | median 1.5xATR stop (4h) | median `cost_r` (4h) | expected 1h stop | expected 1h `cost_r` |
|---|---|---|---|---|
| BTC | 1.776% | 0.045R | ~0.9% | **~0.09R** |
| ETH | 2.003% | 0.040R | ~1.0% | **~0.08R** |
| SOL | 2.116% | 0.038R | ~1.1% | **~0.08R** |

**Reporting requirement:** each arm MUST report its own measured median
`stop_fraction` and median `cost_r` per ticker alongside every expectancy
figure. A 1h expectancy is not comparable to a 4h one without them. ARM B is
the more exposed of the two: a 90-bar hold is 3.75 days, so it pays the doubled
cost over a much shorter move.

**No cost parameter may be adjusted to compensate.** If doubled costs sink the
result, that is the result.

---

## Windows on the 1h index

Same rules as every other program, applied to the 1h index:

- **LOCKBOX**: the last 6 months, sealed. Never read, in the daily frames or
  the 1h feed (`harness.seal_bars` analogue).
- **DISCOVERY / CONFIRMATION**: first 55% / remaining 45% of what is left,
  split in TIME.
- **Common to all three tickers, anchored on BTC**, as in the basket program.
  SOL's 1h history starts 2020-09-18 and simply contributes no bars before
  then. Per-ticker windows would make pooling incoherent.
- Anchored on the **dataset's last bar**, never the wall clock.

Expected shape (exact dates computed at export time, never hardcoded):

| window | approx range | approx 1h bars |
|--------|--------------|----------------|
| DISCOVERY | 2019-09-23 → ~2023-04-07 | ~31,000 |
| CONFIRMATION | ~2023-04-07 → ~2026-02-28 | ~25,400 |
| LOCKBOX (SEALED) | ~2026-02-28 → ~2026-08-28 | ~4,340 |

---

## Specification completion — Step 3 on 1h bars (recorded before any result)

The 10-site map covers the squeeze and geometry parameters. It does NOT cover
**Step 3**, the daily technical/macro indicator score, which is 40% of
`final_score` (`0.6 x gated + 0.4 x indicators`) and has no 1h analogue. This
completes the specification. It is recorded as a **completion, not a choice**:
there is exactly one non-lookahead option.

**The lagged broadcast.** Day D's indicator score exists only at **D's close**.
Its first non-lookahead application is therefore **D+1 00:00 onward**. Every 1h
bar on day D+1 carries day D's Step 3 value; `vix_level` is carried with the
same lag, since `classify_direction` reads it from the same daily row.

Using day D's score on day D's own earlier bars would be lookahead and would
inflate every ARM A and ARM B number. The 4h/daily incumbent has no equivalent
problem: it decides once per day AT D's close and enters at D+1's close, so
both inputs are as-of the same instant.

**Squeeze-only was rejected.** Running ARM A on the Step 1 score alone would
answer a different question than #168 registers. The incumbent IS the 0.6/0.4
blend, so the blend is what ports.

**The same lag rule applies to ARM B, unchanged.**

### REGISTERED DISCLOSURE — indicator staleness

ARM A's report **must state indicator staleness explicitly**: each 1h bar's
Step 3 component is **0-24h old**, against **~0h** at the daily incumbent's
decision moment. A bar at 23:00 on day D+1 is acting on an indicator reading
computed 23 hours earlier.

This is a **structural handicap of the port**, and it is stated here BEFORE any
result exists. Together with the cost caveat it gives **two registered reasons
ARM A is a HARDER test than the 4h original**:

1. **Doubled `cost_r`** — 1h ATR is roughly half of 4h ATR, so the stop
   fraction halves and cost per unit risk roughly doubles.
2. **Indicator staleness 0-24h** — 40% of the score is up to a day old, where
   at 4h it was fresh at the decision instant.

Neither may be used after the fact to explain away a failure: they are recorded
now precisely so that a failure cannot later be attributed to them
retrospectively, and so that a PASS is understood to have cleared a bar the 4h
original never had to.

## Placebo — episode-matched, as registered in #167

Unchanged from #167 and for the same reason: the incumbent's signals arrive in
clustered runs, and an independent-bar placebo is lower-variance than the thing
it benchmarks, which makes the observed percentile look better than it is.

Per ticker: take the observed run-lengths of consecutive confirmed bars; draw
the same NUMBER of runs with the same LENGTHS at random non-overlapping start
positions in the same window; apply the same confirm rule, so a run of length
`L` yields `L − C + 1` trades exactly as the observed runs do. **300 seeds.**

---

## Performance plan

### The problem

`resolve_on_4h` iterates bars in Python: measured **~2.3ms per trade
resolution** (373 calls, 0.853s cumulative, from the attribution profile). ARM
B at 1h could plausibly produce thousands of trades per ticker. With 300
placebo seeds x 3 tickers x 2 windows that is order **10^6–10^7 resolutions**,
i.e. **hours**. Unacceptable.

### The fix, in two parts

1. **Vectorized resolver** in `research/`, numpy-based, no per-bar Python loop.
   For each candidate entry it finds first-touch of target/stop within the hold
   horizon, preserving every rule exactly: pessimistic both-touched-in-one-bar
   → `ambiguous_stop` at −1R, timeout at last Close, unresolved → dropped.

2. **Bar → trade lookup.** Resolve EVERY candidate bar once per ticker per arm,
   then a placebo draw is an index selection, not a re-simulation. This is
   exactly the technique already used in `research/basket_bc.py`, which was
   verified to reproduce `harness.incumbent_rows` trade-for-trade on both tiers
   before any of #164/#165 was reported.

### Equivalence gate — MANDATORY, BEFORE ANY 1h RESULT IS TRUSTED

The vectorized resolver must reproduce `pipeline.resolve_on_4h`
**trade-for-trade on the EXISTING 4h data** — BTC, ETH and SOL, full
non-lockbox span, `LIVE_GEOMETRY`, comparing `date`, `outcome`, `pnl_r`,
`pnl_r_net` and `bars_held` on every trade. **Any mismatch blocks the
program.** A faster resolver that disagrees with the incumbent is not a
resolver, it is a different model.

### Estimated runtime

| stage | estimate |
|-------|----------|
| 1h export, 3 tickers | 10–15 min (network-bound) |
| resolver equivalence gate on 4h data | 2–4 min |
| ARM B event-count estimate (gate, see #169) | 2–3 min |
| precompute bar→trade lookup, 3 tickers x 2 arms | 6–12 min |
| scoring + 300-seed episode placebos (lookups) | 4–6 min |
| **total** | **~25–40 min** |

Compare: the same program with the existing per-trade resolver would be **5+
hours**, which is why the vectorized path is a precondition and not an
optimisation.

---

## What a 1h export adds to `data/`

Measured availability from the portability probe (2026-08-27):

| ticker | 1h first bar | span | bars |
|--------|--------------|------|------|
| BTCUSDT | 2019-09-23 | 6.93y | ~60,730 |
| ETHUSDT | 2019-09-23 | 6.93y | ~60,730 |
| SOLUSDT | 2020-09-18 | 5.94y | ~52,061 |

**Full depth is available at 1h — same start dates as 4h, no penalty.**

Size: current 4h files are 0.95 / 0.88 / 0.71 MB for ~15,177 bars. At ~4x the
rows, expect **~3.8 / 3.5 / 2.8 MB, about 10–11 MB total**, roughly 4–5x the
current 4h footprint. `data/` goes from ~8.3MB to ~19MB. Committable, but it
should be a separate commit from any result.

### Export command

    BINANCE_REGION=US python export_data.py --interval 1h

**BLOCKER, and it is not a detail.** `fetch_klines_paginated` defaults to
`max_requests=20`, and Binance.US returns 1000 bars per call — a hard
**20,000-bar ceiling**. 60,730 bars needs **>= 61 requests**. Without raising
this, the export silently returns a truncated ~2.3-year file and every 1h
number would be computed on a third of the available history, with nothing
saying so.

This is an **11th change site, absent from the 10-site portability map**, and
it lives in `signal_engines.py` (a core file). Under research rule 1 it is a
separate decision and a **separate commit** from the research code, tests
first.

**Amendment 3, fixed at approval — the ceiling is raised AND truncation is
made loud.** Raising `max_requests` alone would fix today's export and leave
the failure mode intact for the next one. Two changes, both required:

1. `max_requests` raised to cover **61+ pages** (>= 70 for headroom), so
   60,730 bars is reachable.
2. A **loud assertion in the export path**: if bars returned < **95%** of bars
   requested, the export FAILS with the counts in the message. It must never
   again be possible for a truncated history to be written to `data/` and
   silently become the basis of a result.

The 95% tolerance exists because a legitimately short symbol (SOL starts later
than BTC) returns fewer bars than asked for. That case is distinguished by
reaching the true start of history — the paginator already detects it via an
empty page — so the assertion fires on TRUNCATION, not on a ticker that simply
has less history than requested.

---

## Registered hypotheses

| # | arm | question | registered direction | pass rule |
|---|-----|----------|----------------------|-----------|
| **#168** | A | Does the phenomenon survive being measured at 1h? | BTC shows the same excess-over-drift character as the 4h incumbent | **ALL THREE:** (a) excess over 1h ALWAYS_LONG > 0 net of measured costs; (b) target rate >= 15pp above the 1h ALWAYS_LONG base rate; (c) `net_all` above the episode-matched placebo p95 on the same window. |
| **#169** | B | Is `ex_best` DEFINABLE at 1h? | Reported measurement, no pass/fail | On how many of 3 tickers `ex_best` is defined (>=3 folds x >=10 trades). **GATE: any ticker < 30 trades on DISCOVERY -> #170 does not run**, program reports "still not measurable". |
| **#170** | B | Is there an edge? | `ex_best` defined AND > 0 on **>= 2 of 3** tickers, AND pooled net above the episode-matched placebo p95 on **BOTH** DISCOVERY and CONFIRMATION | All conditions, or FAIL. No partial credit, no "almost". |

### #168 operationalisation — FIXED AT APPROVAL

On BTC, over the full non-lockbox 1h span. **All three required:**

1. **Excess over drift positive** — ARM A STRONG_BUY `net_all` minus 1h
   ALWAYS_LONG `net_all` (same geometry, same window) **> 0**, computed **net
   of measured costs**, using each arm's own measured `cost_r` rather than the
   4h figure.
2. **Mechanism retained** — target rate **>= 15pp above** the 1h ALWAYS_LONG
   base rate. At 4h the tier ran 78% against ~35%; a hit-rate lift is what
   distinguishes the phenomenon from geometry.
3. **Beats chance** — `net_all` above the **episode-matched placebo p95** on
   the same window, constructed exactly as in #167.

#### Why the +0.90R absolute floor was REMOVED (amendment 1)

The draft proposed a third condition: excess **>= +0.90R**, derived as "half
the 4h figure of +1.819R". That is now struck, and the reasoning is recorded
here because it generalises beyond this hypothesis.

**+1.819R is an n=18 quantity that this very record classifies as
unmeasurable.** It comes from 18 BTC trades that are **2 independent episodes
resolving on 4 distinct exit bars**, with `ex_best` undefined on all three
tickers (Attribution, "INC_STRONG_BUY — a different answer: not
attributable"). The record's own verdict on it is "too rare to attribute —
not a verdict either way".

A pass threshold built from that number would **inherit its noise and launder
it into a criterion**. Whatever sampling error sits in +1.819R would silently
become the bar a new result must clear, and any future reader would see a
precise-looking "+0.90R" with no visible trace that its parent quantity was
declared unmeasurable one section earlier. Halving it does not fix that; it
just halves the noise along with the signal.

**Standing rule, generalised: no pass threshold may take its magnitude from a
quantity this record classifies as unmeasurable.** A threshold may be derived
from a relationship (a placebo distribution, a drift baseline, a base rate
computed on thousands of trades) but not from a point estimate whose own
confidence the project has already refused to assert.

Condition 3 replaces it with a bar that is **measured on the same data at run
time** — the episode-matched placebo — so the threshold carries no inherited
error from the 4h estimate at all.

**#168 remains a ROBUSTNESS result on one ticker. It is NOT replication and
must never be reported as such** — this project's bar is 3+ tickers (CLAUDE.md,
"How decisions get made here", rule 2). ETH and SOL are reported alongside for
information; they carry no pass condition in ARM A.

**#168 is a ROBUSTNESS result on one ticker. It is NOT replication and must
never be reported as such** — this project's own bar is 3+ tickers (CLAUDE.md,
"How decisions get made here", rule 2). ETH and SOL are reported alongside for
information; they carry no pass condition in ARM A.

### #169 gate — FIXED AT APPROVAL (amendment 2)

The ARM B event count is estimated FIRST, and it is a **hard gate**.

**The gate binds PER TICKER, ON DISCOVERY.** If **any one** of BTC, ETH or SOL
yields **< 30 trades on the DISCOVERY window**, **#170 does not run** and the
program reports **"still not measurable"**.

30 is not a preference: it is the arithmetic minimum for `ex_best` to exist at
all (3 counted folds x 10 trades each). Binding per ticker and on DISCOVERY
specifically closes two escape hatches:

- **Per ticker, not pooled.** A pooled count can clear 30 while an individual
  ticker has 4, which is exactly how #165 produced `ex_best` undefined in
  three of four quartiles while looking adequate in aggregate.
- **On DISCOVERY, not the full span.** CONFIRMATION is the longer window here;
  measuring the gate on the full span could let a ticker pass on
  CONFIRMATION's density while DISCOVERY — half of #170's pass condition —
  remains uncomputable.

Running an edge test that cannot produce its own statistic is how undefined
results get reported as negative ones. If the gate fails, "still not
measurable" IS the finding, and it is reported with the same detail as a pass.

### Standing rules, unchanged

Registered before any scoring. No parameter changed after a result (rule 4).
Negatives reported with the same detail as positives (rule 5). The lockbox is
never read (rule 2). Research never edits `signal_engines.py`, `pipeline.py`,
`live_tools.py` or the workflows (rule 1) — the `max_requests` and `--interval`
changes above are core-file work, and are a SEPARATE decision and commit, not
part of this program.

## Result of ARM A (#168) — recorded 2026-08-28

Time-equivalent 1h. SEALED span **2019-09-23 08:00 -> 2026-02-28 04:00**;
lockbox 2026-02-28 -> 2026-08-28 never read, 1h feed sealed at the boundary.
Trades resolved by `research/fast_resolver.py`, which passed the registered
equivalence gate against `pipeline.resolve_on_4h` on 6,611 trades first.
Step 3 applied with the registered one-day lag.

| ticker | row | n | eps | win% | net_all | ex_best | folds+/cnt | med stop | med cost_r | totR |
|---|---|---|---|---|---|---|---|---|---|---|
| BTC | STRONG_BUY | 45 | 4 | 33.3 | +0.114 | — | 1/1 | 0.796% | 0.101 | +5.1 |
| BTC | ALWAYS_LONG | 55775 | 1 | 34.1 | -0.056 | -0.084 | 1/4 | 1.069% | 0.075 | -3118.9 |
| ETH | STRONG_BUY | 60 | 4 | 71.7 | +1.513 | — | 2/2 | 0.698% | 0.115 | +90.8 |
| ETH | ALWAYS_LONG | 55779 | 1 | 34.2 | -0.037 | -0.084 | 1/4 | 1.375% | 0.058 | -2086.9 |
| SOL | STRONG_BUY | **0** | — | — | — | — | — | — | — | — |
| SOL | ALWAYS_LONG | 47136 | 1 | 33.4 | -0.040 | -0.059 | 1/4 | 1.943% | 0.041 | -1878.9 |

- **BTC** episode-matched placebo (300 seeds, 300 valid): mean -0.041, p95 +1.221. Indicator staleness 0-23h (median 12h).
- **ETH** episode-matched placebo (300 seeds, 300 valid): mean -0.020, p95 +1.148. Indicator staleness 0-23h (median 12h).
- **SOL** episode-matched placebo (300 seeds, 0 valid): mean —, p95 —. Indicator staleness 0-23h (median 12h).

### VERDICT: **FAIL** — 1 of 3 registered conditions met

| condition | measured | result |
|---|---|---|
| (a) excess over 1h ALWAYS_LONG > 0, net of costs | +0.114 − (-0.056) = **+0.170** | **PASS** |
| (b) target rate >= +15pp over the 1h base rate | 33.3% − 34.1% = **-0.7pp** | **FAIL** |
| (c) net_all above episode-matched placebo p95 | +0.114 vs **+1.221** | **FAIL** |

**The mechanism does not survive the port, and that is the finding.**
Condition (b) is the one that matters: at 4h the STRONG_BUY tier hit target
**78%** against a ~35% base rate, and that hit-rate lift is what
distinguished the phenomenon from geometry (recorded in Attribution). At 1h
the same construction hits **33.3%** against a 34.1% base — **0.7pp BELOW**
chance, not 15pp above. The excess in (a) is +0.170R and is real, but with
no hit-rate edge behind it, on 45 trades from **4 episodes**, it is not
distinguishable from the placebo: (c) misses by a wide margin, +0.114 against
a p95 of +1.221.

**`ex_best` is STILL undefined.** BTC reaches **1** counted fold of 4 (45
trades, but clustered into 4 episodes so they land in one fold); ETH reaches
2. Neither makes the 3 required. ARM A does not answer the measurability
question — that is ARM B's job — but it is worth recording that raising
resolution alone did not fix it here either.

**SOL produced ZERO STRONG_BUY trades** across 6.4 years of 1h bars. The 48-bar
confirm requires 48 consecutive hourly STRONG_BUY labels, which SOL never
achieved. Its placebo therefore has no observed run-length distribution to
match and is undefined; no number was invented for it.

### The two registered handicaps, measured

Both were stated before the run and both are confirmed. Neither is offered
as an excuse — they are recorded because a FAIL under a harder test says
less than a FAIL under an equal one, and the reader is entitled to know
which this was.

**1. Cost roughly doubled, as predicted.** Median `cost_r`, 4h -> 1h:

| ticker | 4h med stop | 1h med stop | ratio | 4h `cost_r` | 1h `cost_r` | ratio |
|---|---|---|---|---|---|---|
| BTC | 1.776% | 1.069% | 0.60x | 0.045 | 0.075 | **1.66x** |
| ETH | 2.003% | 1.375% | 0.69x | 0.040 | 0.058 | **1.45x** |
| SOL | 2.116% | 1.943% | 0.92x | 0.038 | 0.041 | **1.08x** |

The stop fraction fell to 0.60-0.92x and `cost_r` rose 1.08-1.66x. The
registration said "roughly half" and "roughly doubles"; the measured
direction is right and the magnitude is somewhat milder than predicted,
least so on SOL. On the STRONG_BUY rows specifically the stops are tighter
still (BTC 0.796%, ETH 0.698%) and `cost_r` reaches 0.101-0.115.

**2. Indicator staleness 0-23h, median 12h**, on every ticker — against ~0h
at the daily incumbent's decision moment. 40% of each 1h score was up to a
day old by construction.

**Neither handicap explains condition (b).** A stale indicator and a doubled
cost move `net_all`; they do not move the TARGET RATE, which is a property
of where the exit levels sat relative to subsequent price. 33.3% against a
34.1% base is a statement about the signal, not about costs.

### STRUCTURAL NOTE — ARM A could never have fixed measurability

Episode count did **not** scale with bar count. It went DOWN.

| ticker | 4h trades / episodes | ARM A 1h trades / episodes |
|--------|----------------------|----------------------------|
| BTC | 19 / **8** | 45 / **4** |
| ETH | 9 / **6** | 60 / **4** |
| SOL | 1 / **1** | 0 / **0** |

Bars rose 4x (15,177 -> 60,696) and trades rose with them, but the number of
independent occasions FELL. The cause is structural, not empirical: ARM A
rescales the confirm requirement along with everything else, so
`confirm_days=2` becomes **48 consecutive hourly labels**. Two consecutive
daily STRONG_BUY readings is a far weaker condition than an unbroken two-day
streak sampled hourly — a single hour anywhere in the window that drops out of
STRONG_BUY breaks it. SOL never achieved 48 in a row in 6.4 years.

So ARM A **subdivides** occasions rather than multiplying them: each surviving
occasion yields many overlapping hourly entries (45 trades from 4 episodes),
which inflates `n` while leaving the independent-observation count lower than
the 4h original. That is precisely the failure mode `ex_best` exists to catch,
and it is why `ex_best` stayed undefined here (BTC 1 counted fold, ETH 2).

**This was true by construction, and is worth stating plainly: ARM A could not
have fixed measurability whatever the market did.** Holding wall-clock constant
necessarily holds the streak requirement constant in time, so it cannot
generate more independent occasions than the 4h version — only finer slices of
the same ones. ARM A was a robustness test and it is fair as one; it was never
capable of answering the measurability question, and nothing about its result
bears on that question either way.

**ARM B's 2-bar confirm is the only element of this program that multiplies
episodes rather than subdividing them.** Keeping the confirm at 2 BARS means
the streak requirement shrinks from 2 days to 2 hours, so occasions that could
never sustain a 48-hour label can qualify. Whether that produces enough
independent episodes — not merely enough trades — is exactly what #169
measures, and why its gate is written on trade count per ticker with episodes
reported alongside.

### What ARM A does and does not establish

- It does **not** establish that the 4h phenomenon is fake. The 4h figure it
  was compared against (+1.819R excess, 78% target) is itself an n=18
  quantity this record classifies as unmeasurable.
- It **does** establish that the construction, ported to 1h under
  time-equivalent parameters, produces no hit-rate advantage on BTC and
  nothing separable from an episode-matched placebo.
- **ETH is the tempting row and carries no pass condition.** 60 trades,
  71.7% target, +1.513R — but 4 episodes, `ex_best` undefined (2 counted
  folds), and ARM A registered BTC as the test. Reporting ETH as a result
  would be selecting the ticker after seeing the numbers. It is recorded,
  not claimed.
- Per the registration, ARM A was **never** a replication test. A pass would
  have been robustness-on-one-ticker; a fail is the same scope.

## Result of #169 (ARM B event-count estimate) — recorded 2026-08-28

ARM B parameters (bb 20, lookback 120, ATR 14, hold 90 bars, confirm 2
bars), **DISCOVERY ONLY** (2019-09-23 08:00 -> 2023-04-07 17:15). This is a
reported measurement with no pass/fail of its own; its gate governs #170.

| ticker | 1h bars | STRONG_BUY labelled bars | confirmed | trades | **episodes** | med stop | med cost_r |
|---|---|---|---|---|---|---|---|
| BTC | 30409 | 285 | 253 | **253** | **25** | 0.810% | 0.099 |
| ETH | 30409 | 227 | 184 | **184** | **25** | 1.045% | 0.077 |
| SOL | 21769 | 137 | 109 | **109** | **21** | 1.674% | 0.048 |

### GATE: **PASS** — all three tickers clear 30 trades on DISCOVERY

| ticker | trades | gate (>= 30) |
|---|---|---|
| BTC | 253 | **PASS** |
| ETH | 184 | **PASS** |
| SOL | 109 | **PASS** |

### `ex_best` IS DEFINABLE — the first time in this project

| ticker | folds counted | `ex_best` (DISCOVERY) |
|---|---|---|
| BTC | 4 of 4 | -0.228 |
| ETH | 4 of 4 | -0.282 |
| SOL | 3 of 4 | -0.270 |

**This answers #169's actual question.** `ex_best` has never once been
computable for the STRONG_BUY tier: not on 3 tickers (#42-#162), not on 82
(#163: 0 of 82), not pooled into quartiles (#165: undefined in 3 of 4), and
not in ARM A (#168: BTC 1 counted fold, ETH 2). Under ARM B it is defined on
**all three**, with BTC and ETH reaching 4 counted folds of 4 and SOL 3 of 4.
The 2-bar confirm is what did it, exactly as the structural note predicted:
it multiplies occasions instead of subdividing them.

### The caveat that goes with it, stated now

**Trades are not observations.** BTC's 253 trades come from **25 episodes** —
about 10 overlapping entries per occasion inside a 90-bar (3.75-day) hold.
ETH is 184 from 25, SOL 109 from 21. So `ex_best` is now computable because
the TRADE count crossed its threshold, while the independent-occasion count
is 21-25 per ticker. That is more than the 4h tier ever had (BTC 8, ETH 6,
SOL 1) and it is still small.

**The DISCOVERY `ex_best` values are visible above and they are negative on
all three** (-0.228, -0.282, -0.270). They became visible as a by-product of
counting folds, which #169 requires. They are recorded rather than withheld,
because concealing a number already computed is worse than reporting it.
They are DISCOVERY-only: #170 additionally requires CONFIRMATION, which has
NOT been computed, and its pass rule needs `ex_best` > 0 on >= 2 of 3 tickers
plus `net_all` above the episode-matched placebo p95 on BOTH windows.

**#170 has not been run.** The gate is passed and the decision to proceed is
the maintainer's.

## Result of #170 (ARM B edge test) — recorded 2026-08-28

Run once, both windows, exactly as registered. Episode-matched placebo,
300 seeds. DISCOVERY `ex_best` reproduced #169's values identically
(-0.228 / -0.282 / -0.270) and was not recomputed or reframed.

### DISCOVERY  (2019-09-23 08:00:00 -> 2023-04-07 17:15:00)

| ticker | n | **episodes** | win% | net_all | ex_best | placebo p95 |
|---|---|---|---|---|---|---|
| BTC | 253 | **25** | 36.4 | +0.204 | -0.228 | +0.417 |
| ETH | 184 | **25** | 25.5 | -0.167 | -0.282 | +0.499 |
| SOL | 109 | **21** | 31.2 | +0.083 | -0.270 | +0.517 |
| **POOLED** | 546 | — | 31.7 | +0.055 | -0.127 | +0.231 |

### CONFIRMATION  (2023-04-07 17:15:00 -> 2026-02-28 04:00:00)

| ticker | n | **episodes** | win% | net_all | ex_best | placebo p95 |
|---|---|---|---|---|---|---|
| BTC | 737 | **57** | 24.7 | -0.275 | -0.468 | +0.240 |
| ETH | 553 | **48** | 31.6 | +0.015 | -0.282 | +0.238 |
| SOL | 401 | **35** | 34.7 | +0.194 | +0.079 | +0.386 |
| **POOLED** | 1691 | — | 29.3 | -0.069 | -0.266 | +0.145 |

### VERDICT: **FAIL** — all four registered conditions missed

| window | condition | measured | result |
|---|---|---|---|
| DISCOVERY | 1. `ex_best` > 0 on >= 2 of 3 | **0 of 3** | **FAIL** |
| DISCOVERY | 2. pooled net > placebo p95 | +0.055 vs +0.231 | **FAIL** |
| CONFIRMATION | 1. `ex_best` > 0 on >= 2 of 3 | **1 of 3** (SOL) | **FAIL** |
| CONFIRMATION | 2. pooled net > placebo p95 | -0.069 vs +0.145 | **FAIL** |

### Read at its true weight

**DISCOVERY episode counts: 25 / 25 / 21.** CONFIRMATION: 57 / 48 / 35.
Those are the independent-occasion counts behind 253/184/109 and
737/553/401 trades respectively — roughly 10 overlapping entries per
occasion inside a 90-bar hold. The trade counts are what made `ex_best`
computable; the episode counts are what the result actually rests on.

**This is the project's first fully measured negative on the STRONG_BUY
construction.** Every previous attempt returned *unmeasurable*: #163 (0 of
82 tickers reached a defined `ex_best`), #165 (undefined in 3 of 4
quartiles), #168 (BTC 1 counted fold). Here `ex_best` is defined in **5 of
6 ticker-window cells** and is **negative in 5 of them**. The single
positive is SOL on CONFIRMATION (+0.079), one cell of six, and the
registered rule requires two per window.

**Both windows agree, which is the part that matters.** DISCOVERY pooled
+0.055 against a placebo p95 of +0.231; CONFIRMATION pooled -0.069 against
+0.145. Neither window is close, and the direction is consistent. This is
not a near-miss that a longer sample might rescue — the pooled figures sit
well inside the placebo distribution on both halves of the data.

**The measurability question and the edge question got different answers.**
#169 succeeded: the 2-bar confirm did what the structural note said it
would, multiplying occasions instead of subdividing them, and produced the
first computable `ex_best` in the project's history. #170 then used that
statistic and it said no. Being able to measure a thing and the thing being
real are separate results, and this program delivered the first without the
second.

### Program status after #168-#170

| # | arm | result |
|---|-----|--------|
| #168 | A (time-equivalent) | **FAIL** — 1 of 3 conditions; target rate 33.3% vs a 34.1% base |
| #169 | B (measurability) | **Gate PASS** — `ex_best` definable on all three for the first time |
| #170 | B (edge) | **FAIL** — all four conditions, both windows |

**Nothing further runs without a new registration.**

---

# PROGRAM CLOSE-OUT — 1h PROGRAM (#168-#170)

**Closed 2026-08-28. All three registered hypotheses resolved. Nothing
further runs on this axis without a new registration.**

## Outcome

| # | arm | question | outcome |
|---|-----|----------|---------|
| **#168** | A, time-equivalent | Does the phenomenon survive being measured at 1h? | **FAIL** — 1 of 3 conditions |
| **#169** | B, measurability | Is `ex_best` definable at 1h? | **GATE PASS** — definable on all three tickers, a first |
| **#170** | B, edge | Is there an edge? | **FAIL** — all four conditions, both windows |

## #168 — FAIL

BTC, sealed span 2019-09-23 -> 2026-02-28.

| condition | measured | |
|---|---|---|
| (a) excess over 1h ALWAYS_LONG > 0, net of costs | +0.114 − (−0.056) = **+0.170** | PASS |
| (b) target rate >= +15pp over the 1h base rate | 33.3% − 34.1% = **−0.7pp** | **FAIL** |
| (c) net_all above episode-matched placebo p95 | +0.114 vs **+1.221** | **FAIL** |

BTC **45 trades / 4 episodes**; ETH 60 / 4; SOL **0 trades in 6.4 years**.

The hit-rate mechanism did not survive the port. At 4h the tier hit target 78%
against a ~35% base; at 1h it hit 33.3% against 34.1% — below chance, not
15pp above. Both registered handicaps were confirmed and neither explains it:
`cost_r` rose 1.08-1.66x and indicator staleness measured 0-23h (median 12h),
but a stale indicator and a doubled cost move `net_all`, not the target rate.

ARM A also **could not have fixed measurability by construction** — rescaling
the confirm to 48 bars scales the streak requirement with resolution, so it
subdivides occasions rather than multiplying them. Episodes FELL against 4h
(BTC 8 -> 4, ETH 6 -> 4, SOL 1 -> 0) while bars rose 4x.

## #169 — GATE PASS, and the program's one affirmative result

ARM B parameters, DISCOVERY only.

| ticker | trades | **episodes** | folds counted | `ex_best` |
|---|---|---|---|---|
| BTC | 253 | **25** | 4 of 4 | −0.228 |
| ETH | 184 | **25** | 4 of 4 | −0.282 |
| SOL | 109 | **21** | 3 of 4 | −0.270 |

**`ex_best` had never once been computable for the STRONG_BUY tier** — not on
3 tickers (#42-#162), not on 82 (#163: 0 of 82), not pooled into quartiles
(#165: undefined in 3 of 4), not under ARM A (#168: BTC 1 counted fold). Under
ARM B it is defined on all three, **for the predicted structural reason**: the
2-bar confirm shrinks the streak requirement from 2 days to 2 hours, so it
multiplies occasions instead of subdividing them. That mechanism was written
into the record BEFORE the run.

## #170 — FAIL on all four conditions, both windows

Every trade count is given with its episode count, because the trade counts
are what made `ex_best` computable and the episode counts are what the result
rests on — roughly ten overlapping entries per occasion inside a 90-bar hold.

**DISCOVERY** (2019-09-23 -> 2023-04-07)

| ticker | n | **episodes** | win% | net_all | ex_best | placebo p95 |
|---|---|---|---|---|---|---|
| BTC | 253 | **25** | 36.4 | +0.204 | −0.228 | +0.417 |
| ETH | 184 | **25** | 25.5 | −0.167 | −0.282 | +0.499 |
| SOL | 109 | **21** | 31.2 | +0.083 | −0.270 | +0.517 |
| POOLED | 546 | **71** | 31.7 | **+0.055** | −0.127 | **+0.231** |

**CONFIRMATION** (2023-04-07 -> 2026-02-28)

| ticker | n | **episodes** | win% | net_all | ex_best | placebo p95 |
|---|---|---|---|---|---|---|
| BTC | 737 | **57** | 24.7 | −0.275 | −0.468 | +0.240 |
| ETH | 553 | **48** | 31.6 | +0.015 | −0.282 | +0.238 |
| SOL | 401 | **35** | 34.7 | +0.194 | **+0.079** | +0.386 |
| POOLED | 1,691 | **140** | 29.3 | **−0.069** | −0.266 | **+0.145** |

| window | condition | measured | |
|---|---|---|---|
| DISCOVERY | `ex_best` > 0 on >= 2 of 3 | **0 of 3** | **FAIL** |
| DISCOVERY | pooled net > placebo p95 | +0.055 vs +0.231 | **FAIL** |
| CONFIRMATION | `ex_best` > 0 on >= 2 of 3 | **1 of 3** (SOL) | **FAIL** |
| CONFIRMATION | pooled net > placebo p95 | −0.069 vs +0.145 | **FAIL** |

`ex_best` is defined in **5 of 6 ticker-window cells and negative in 5 of
them**. The single positive is SOL on CONFIRMATION (+0.079), one cell of six
against a rule requiring two per window. Both windows agree and neither is
close: the pooled figures sit well inside the placebo distribution on both
halves of the data.

## SCOPE — what this closes, and what it does not

**CLOSED: the resolution axis for the bar-equivalent construction.** #170 is
the project's **first fully measured negative** on the STRONG_BUY
construction. Every previous attempt returned *unmeasurable*. Here the
statistic exists, on both windows and all three tickers, and it says no. The
bar-equivalent 1h construction does not carry an edge, and no further
resolution work on it is warranted without a new hypothesis.

**NOT CLOSED: the 4h tier's original n=18 excess.** It remains
**unmeasurable and unadjudicated**, exactly as recorded in Attribution:
+1.819R excess on BTC from 18 trades / 2 independent episodes / 4 distinct
exit bars, with `ex_best` undefined on all three tickers. Nothing in this
program adjudicates it:

- **#168 does not**, because it tested a DIFFERENT construction — every
  parameter rescaled — and because it was registered as robustness on one
  ticker, never as replication.
- **#170 does not**, because the bar-equivalent construction runs on a 4x
  shorter timescale and is a different strategy that happens to share a
  parameter table. A negative there is a negative about *it*.

The 4h tier's status is unchanged: **too rare to attribute, neither confirmed
nor refuted.** What would move it is unchanged too — `ex_best` defined and
positive on >= 3 tickers at >= 30 trades each, which at ~4 trades per ticker
per year is roughly 7-8 more years of live accumulation per ticker, or a
design change that fires it more often.

**The measurability question and the edge question got different answers, and
both are results.** #169 succeeded at what four prior programs failed to do.
#170 then used the statistic it unlocked, and the answer was no. Being able to
measure a thing and the thing being real are separate findings; this program
delivered the first without the second, which is a better outcome than another
"too rare to tell" — a computable negative closes a question that
#163, #165 and #168 all left open.


---

## Hypothesis #171 — BTC INC_BUY_ALL revalidation on the refreshed dataset

**Registered 2026-08-28, BEFORE running.**

### Why this exists

`claims.md` currently cites, under SUPPORTED, that the incumbent's all-BUY
tier is **positive on BTC and only BTC**: +0.237R at the **100.0th percentile**
of its count-matched placebo (p95 +0.013) on DISCOVERY, against ETH at the
47.7th and SOL at the 21.0th. It is the strongest surviving claim in that
document, and the one a reader is most likely to act on.

**That number was computed on the PRE-REFRESH split.** The dataset has since
been re-exported at full depth (commit `acf2f59`): BTC/ETH 4h went from 13,000
bars / 5.93y to 15,177 / 6.93y, and the daily frame from 1,762 rows / 4.82y to
2,502 / 6.85y. Because windows are anchored on the dataset's span, DISCOVERY's
cut moved from 2023-09-16 to **2023-04-06**. The claim therefore rests on a
split that no longer exists, and it has never been re-derived on the data the
project now ships.

A claim that cannot survive its own dataset being extended is not a claim.

### Registered direction

**BTC alone.** On the CURRENT frozen dataset, INC_BUY_ALL must satisfy BOTH,
on BOTH windows:

1. `ex_best` > 0, and
2. `net_all` above the **episode-matched** placebo p95, 300 seeds.

Episode-matched, not day-matched, per #167: the incumbent's signal days arrive
in runs, and a scattered-day placebo is lower-variance than the thing it
benchmarks. The placebo preserves the observed run-length distribution AND the
observed STRONG_BUY/BUY conviction mix, so the average R:R matches.

ETH and SOL are not tested here. They were measured negative on the old split
(47.7th and 21.0th percentile) and nothing about this hypothesis revisits them.

### Consequence, fixed in advance

**A FAIL here triggers a `claims.md` revision.** The "positive on BTC and only
BTC" entry moves out of SUPPORTED, and the specific figure — +0.237R at the
100.0th percentile — is either restated with its new value or withdrawn. That
consequence is registered now so it cannot be renegotiated after the number
exists.

A PASS leaves the claim standing, with the figures updated to the refreshed
split and the old ones marked superseded.

### Result of #171 — recorded 2026-08-28

BTC INC_BUY_ALL on the refreshed full-depth dataset. The day->trade lookup
was verified against `harness.incumbent_rows` trade-for-trade on both
windows before any placebo ran (93 and 108 trades, MATCH).

| window | n | **episodes** | win% | net_all | ex_best | folds+/cnt | placebo p95 |
|---|---|---|---|---|---|---|---|
| DISCOVERY | 93 | **30** | 28.0 | -0.167 | -0.475 | 1/4 | +0.247 |
| CONFIRMATION | 108 | **23** | 39.8 | +0.195 | +0.097 | 3/4 | +0.330 |

### VERDICT: **FAIL** — 1 of 4 conditions

| window | condition | measured | |
|---|---|---|---|
| DISCOVERY | `ex_best` > 0 | −0.475 | **FAIL** |
| DISCOVERY | net > placebo p95 | −0.167 vs +0.247 | **FAIL** |
| CONFIRMATION | `ex_best` > 0 | +0.097 | **PASS** |
| CONFIRMATION | net > placebo p95 | +0.195 vs +0.330 | **FAIL** |

### The claim did not survive the dataset being extended

`claims.md` asserts, under SUPPORTED: **BTC INC_BUY_ALL +0.237R on
DISCOVERY, at the 100.0th percentile of its placebo (p95 +0.013)**. On the
refreshed dataset the same measurement on the same ticker is **−0.167R,
below a p95 of +0.247**. The sign flipped.

**Nothing broke.** Both numbers are correct for the data they were computed
on. The full-depth re-export (`acf2f59`) added a year of history, which
moved DISCOVERY's cut from 2023-09-16 to 2023-04-06 and grew the sample
from 58 trades to 93. It is a different window over different years, and
the answer changed with it.

### Sharpened 2026-08-28: not window-dependent, BOUNDARY-CONJUNCTION-dependent

`research/window_stability.py` profiled the exact #171 statistic across **50
rolling window starts** with the END pinned at DISCOVERY's current cut:

| | value |
|---|---|
| starts evaluated | 50 (all defined) |
| sign-stability | **88% negative** — 44 negative, 6 positive |
| range | **−0.167 … +0.177**, median −0.046 |

Two things follow, and the second is stronger than what was first recorded.

1. **The negative reading is the typical one.** −0.167 is not an unlucky
   split; it is the earliest start in a sweep that comes out negative at 44
   of 50.
2. **The published +0.237 lies OUTSIDE the entire sweep.** It sits above the
   maximum of +0.177 and is **not reachable by moving the start alone.** That
   window also ENDED earlier (2023-09-16 vs 2023-04-06), so reproducing it
   requires BOTH boundaries in conjunction.

So "window-dependent" understates it. The published figure was
**boundary-conjunction-dependent**: it needed a particular start AND a
particular end together, and no single-boundary perturbation reaches it. A
statistic that survives neither margin of its own window is weaker evidence
than one that merely moves when the window does.

The sweep bounds one degree of freedom. Both moved.

**That is the finding.** The claim was window-dependent, and nothing in the
original measurement disclosed that. A +0.237R at the 100th percentile
reads as robust; it was one split away from −0.167R. This is precisely the
failure mode #171 was registered to detect, and the reason the registration
fixed the consequence in advance.

### Triggered: `claims.md` revision (registered consequence)

Per the registration, this FAIL requires the "positive on BTC and only
BTC" entry to leave SUPPORTED, and the +0.237R / 100.0th-percentile figure
to be restated or withdrawn.

**APPLIED 2026-08-28** (commit `90bc2ff`). The entry is out of SUPPORTED,
with BOTH measurements shown side by side rather than the old one deleted —
+0.237R at the 100.0th percentile on the pre-refresh split, −0.167R against a
p95 of +0.247 on the refreshed one — and the window-dependence stated plainly.
A standing rule was added with it: **SUPPORTED entries are dated to their
dataset freeze, and any refresh of `data/` re-opens every entry derived from
it.** Windows are anchored on the dataset's span, so extending the data moves
the DISCOVERY/CONFIRMATION boundary; a refresh is a different experiment, not
more of the same one.

**The record now holds ZERO supported edge claims.** BTC INC_BUY_ALL was the
last one standing. Everything remaining under SUPPORTED is engineering,
process, or measured absence of edge.

A secondary point for that revision: CONFIRMATION is the only window where
`ex_best` is positive (+0.097 on 108 trades / 23 episodes), and it still
fails the placebo bar. The tier is not rescued by the other window.

---

# PRE-REGISTRATION — FUNDING PROGRAM (#172–#186)

> **STATUS: REGISTERED, DORMANT. Nothing runs until the data-depth trigger
> fires. On the trigger date a future session executes this document
> verbatim — every parameter, threshold, window rule and pass condition is
> fixed below and NONE may be chosen, edited or reinterpreted then.**

## The central property: this is registered before its test data exists

**This is the only program in the project registered before the data it will
be tested on exists.** That is not incidental — it is the design.

Kraken Futures serves a **rolling one-year window** of funding history. Our
archive is a merge-dedupe accumulation of that window (`derivs-collect.yml`,
running daily since 2026-08-28), so it retains what the venue discards. On
the trigger date the archive will span 22 months while Kraken itself serves
only the most recent 12. **Everything visible to us today — the whole
2025-08-27 → 2026-08-28 backfill — will by then exist ONLY in our archive
and nowhere on the venue.**

The consequence is the point:

- **Tuning to the test set is impossible by construction.** The usable
  window at trigger time is data that does not yet exist as of this
  registration. No one can look at it, because there is nothing to look at.
- **The rules below were chosen from published funding literature and from
  the four the maintainer specified, not from inspection of returns.** No
  funding series has been plotted, scored, backtested or correlated with
  price by this project. Not once.
- **The archive is append-only and idempotent.** Existing rows win on a
  collision, so a venue revising history cannot retroactively move the test
  set (see the derivatives provenance note).

Every other program in this record had to be defended against hindsight.
This one is defended by the calendar.

## TRIGGER

**Runnable when `data/derivatives/kraken_funding.csv` spans >= 22 months for
ALL THREE symbols** (PF_XBTUSD, PF_ETHUSD, PF_SOLUSD), measured as
`max(timestamp) - min(timestamp)` per symbol.

22 months decomposes as: **6 months lockbox + 4 months burn-in + 12 months
usable.**

| quantity | value |
|---|---|
| archive earliest (all three symbols) | **2025-08-27** |
| **expected trigger date** | **2027-06-27** |
| second checkpoint (34 months, 24 usable) | **2028-06-27** |

The trigger is ~2 months earlier than a naive estimate because Kraken's
first collector run backfilled a free year on 2026-08-28; the archive began
at 12 months, not zero. **The trigger is on measured span, not on the
calendar date** — if the collector misses days, the date slips and the span
condition still governs. The dates above are expectations, not conditions.

**Nothing in this program runs before the span condition is met.** A partial
run on shallower data is a peek, and the burn-in exists precisely so that
percentile lookbacks are warm before the usable window opens.

## DATA

**Primary: Kraken Futures funding, hourly**, `PF_XBTUSD` / `PF_ETHUSD` /
`PF_SOLUSD`, from `data/derivatives/kraken_funding.csv`.

The field used is **`relative_funding_rate`** — the dimensionless per-interval
rate. `funding_rate` (absolute, quote-currency) is NOT used: it is not
comparable across symbols or price levels.

**OKX funding is a CROSS-VENUE CONSISTENCY CHECK ONLY and is NEVER a signal
input.** At trigger time, report the Pearson correlation between the two
venues' daily mean rates per symbol over the overlapping span. If any symbol
correlates below **0.80**, every result for that symbol is reported with a
venue-disagreement flag attached. The check cannot change a pass or a fail;
it exists so that a result built on one venue's quirk is visible as such.
OKX's own window is ~3 months, so the overlap will be partial by
construction, and that is expected.

### Alignment — the no-lookahead rule, identical to the Step 3 port

**Funding known as of hour H applies to bars H+1 onward.** Concretely:

1. All funding features for UTC day **D** are computed from hourly rows with
   `timestamp <= D 23:00`.
2. Those features are known at **D 24:00 = D+1 00:00**, which is exactly the
   daily close of day D.
3. A rule firing on day D is a daily BUY event on day D, which
   `research/harness.py` labels on D and D+1, confirms at D+1 under
   `confirm_days=2`, and enters at the close of D+1.

This is the same construction registered for the Step 3 lagged broadcast
(#168–#170) and carries the same guarantee: no value from after a decision
point enters that decision.

**The lockbox applies at ANALYSIS time, not collection time.** The last 6
months of whatever the archive holds when the program runs are sealed. A row
collected in 2026 is inside the lockbox if it falls in the final 6 months as
measured on the trigger date.

## HYPOTHESES — #172–#186

Eight rules. **Seven are tested in BOTH modes; F4 is overlay-only.** That is
**15 registered tests** and 15 hypothesis numbers.

- **STANDALONE** — the rule produces a daily boolean BUY event series, scored
  through `research/harness.py` into `pipeline.evaluate_geometry_folds` with
  `LIVE_GEOMETRY` and 2bps fee + 2bps slippage per side, exactly as
  #42–#161 were.
- **OVERLAY** — the rule filters the incumbent's own BUY/STRONG_BUY days:
  the event fires only where the incumbent already signalled AND the funding
  condition holds. Scored identically.

All parameters are conventional and are fixed here. None may be changed.

| # | rule | mode | definition (one sentence, all numbers final) |
|---|------|------|---------------------------------------------|
| **#172** | F1 | standalone | BUY when the trailing **30-day percentile rank** of daily-mean funding is **<= 10** (crowded shorts, contrarian long). |
| **#173** | F1 | overlay | The incumbent's BUY day is kept only when F1's condition holds. |
| **#174** | F2 | standalone | BUY on the first day whose daily-mean funding is **> 0** after **>= 72 consecutive hours** of funding **< 0**. |
| **#175** | F2 | overlay | The incumbent's BUY day is kept only when F2's condition holds. |
| **#176** | F3 | standalone | BUY when the **8-hour-equivalent** funding rate is **<= -0.01%** (absolute extreme; normalization below). |
| **#177** | F3 | overlay | The incumbent's BUY day is kept only when F3's condition holds. |
| **#178** | F4 | **overlay only** | **SUPPRESS** an incumbent BUY when the trailing 30-day percentile rank of daily-mean funding is **>= 90** AND the close is a **20-day high** (euphoria fade). |
| **#179** | F5 | standalone | BUY when **cumulative funding over the trailing 7 days is <= 0** (shorts paid longs, net, across the week). |
| **#180** | F5 | overlay | The incumbent's BUY day is kept only when F5's condition holds. |
| **#181** | F6 | standalone | BUY when the **30-day z-score** of daily-mean funding is **<= -2.0**. |
| **#182** | F6 | overlay | The incumbent's BUY day is kept only when F6's condition holds. |
| **#183** | F7 | standalone | BUY when the close is a **20-day high** AND the **7-day mean funding is <= 0** (rally not driven by leveraged longs). |
| **#184** | F7 | overlay | The incumbent's BUY day is kept only when F7's condition holds. |
| **#185** | F8 | standalone | BUY when funding has been **< 0 for >= 168 consecutive hours** (7 days of sustained short-paying). |
| **#186** | F8 | overlay | The incumbent's BUY day is kept only when F8's condition holds. |

### Fixed definitions — no interpretation left

- **daily-mean funding** for day D = arithmetic mean of `relative_funding_rate`
  over all hourly rows with `timestamp` in `[D 00:00, D 23:59]`. Days with
  fewer than **20 of 24** hourly rows are **excluded** from every rule and
  from every lookback (recorded, not silently dropped).
- **30-day percentile rank** = rank of today's daily-mean funding within the
  trailing 30 daily-mean values INCLUDING today, expressed 0–100
  (`Series.rolling(30).rank(pct=True) * 100`). Same construction as
  `BBW_PCTL` in #42–#161.
- **30-day z-score** = `(x - rolling_30_mean) / rolling_30_std(ddof=0)`,
  computed on daily-mean funding including today. Undefined (NaN) days do
  not fire.
- **8-hour-equivalent rate (F3)** = the **sum of the trailing 8 hourly
  `relative_funding_rate` values**, i.e. `rolling(8).sum()` on the hourly
  series, evaluated at the last hour of day D. Summed rather than
  `hourly x 8` because the sum is the actual cost of holding those 8 hours
  and is less sensitive to a single outlying hour. Threshold: **<= -0.0001**
  (−0.01%). This is the venue normalization: Kraken settles hourly and OKX
  8-hourly, so all absolute thresholds in this program are stated in
  8h-equivalent units and computed from Kraken hourly sums.
- **cumulative 7-day funding (F5)** = sum of `relative_funding_rate` over all
  hourly rows in the trailing 168 hours.
- **20-day high** = close >= the maximum close of the trailing 20 daily
  closes including today, on the incumbent's daily merged frame.
- **consecutive-hour counts (F2, F8)** are counted on the hourly series with
  no gap tolerance: a missing hour **breaks** the run. This is deliberate and
  conservative — an inferred run across a data gap is not an observed run.
- **Long side only**, matching live: shorts are suppressed in production and
  no rule here produces a SELL.

## EVALUATION — the standard ladder, and the depth constraint

### Folds on a ~12-month usable window

The usable window at trigger time is **~52 weeks**. Folds are **4 equal-
duration time splits** of that window — `pd.date_range(start, end,
periods=5)`, the same construction `pipeline.walkforward_folds` uses —
giving **~13 weeks per fold**.

`ex_best` requires **>= 3 folds each carrying >= 10 trades**. On a 4-fold,
13-week structure that means a rule must sustain roughly **one event per 9
days** across at least three quarters of the window.

**This is the hard constraint of the program.** A rule that fires less often
than that produces `ex_best = undefined`, and:

> **An undefined `ex_best` is reported as UNMEASURABLE and CANNOT PASS.** It
> is not a fail and must never be written up as one; it is the absence of a
> result. This is the distinction #163, #165 and #168 all turned on.

### Placebo

**Episode-matched**, exactly as #167: per ticker, take the observed
run-lengths of consecutive event days, draw the same NUMBER of runs with the
same LENGTHS at random non-overlapping start positions in the same window,
and apply the same confirm rule. Independent-day placebos are forbidden
here — funding regimes are persistent by nature, so a scattered placebo
would be structurally lower-variance than what it benchmarks.

**Seeds: 3,000.** Not 300. The Bonferroni-adjusted threshold below sits at
the 99.67th percentile, and a 99.67th percentile estimated from 300 draws is
the single largest draw — an unusable statistic. 3,000 seeds put ~10 draws
above the threshold. The p95 is reported alongside for comparability with
earlier programs, computed from the same 3,000 draws.

### Pass conditions

A rule passes only if, on the single confirmation run:

1. **`ex_best` > 0 on ALL THREE tickers** (and defined on all three — see
   the unmeasurable rule above), AND
2. **pooled `net_all` above the Bonferroni-adjusted placebo percentile.**

**Bonferroni:** 15 registered tests, so alpha = 0.05 / 15 = 0.00333 and the
required percentile is **99.67**, not 95. Every test in this program is an
independent opportunity for a false positive and the correction counts
tests, not rules — #172 and #173 are two chances at the same idea and both
are counted.

**Single confirmation.** One run, one verdict, no re-runs, no second look at
a looser bar, no partial credit. "Almost" is a failure, as it was for
`rsi7_cross50+none` and for `INC_BUY_ALL` at 0.001R.

### Power — stated now so neither checkpoint is a peek

**At 12 usable months this program has limited power, and that is known
before it runs.** A 13-week fold holds ~91 days; a rule firing weekly places
~13 trades in it, barely over the 10-trade bar. Small samples, wide placebo
distributions, and a 99.67th-percentile threshold together mean a real but
modest edge will likely read as unmeasurable or fail.

**Both checkpoints are registered NOW:**

| checkpoint | span | usable | expected date | status |
|---|---|---|---|---|
| **C1** | 22 months | 12 months | 2027-06-27 | registered |
| **C2** | 34 months | 24 months | 2028-06-27 | registered |

C2 doubles the usable window and re-runs **this identical rule list with
these identical parameters** — nothing may be added, dropped or altered
between the two. Because both are registered here, **running C2 after a
failed C1 is not a peek and not a second bite**: it is a pre-declared
increase in sample size on a fixed hypothesis set. Any rule that changes
between C1 and C2 voids C2 entirely.

C1 results are reported in full regardless of outcome and are not
provisional. C2 supersedes nothing; both stand.

## BUDGET AND CLOSURE

**This list is the whole program.** Eight rules, fifteen tests, two
checkpoints.

- **No rule may be added, edited, or re-run after the trigger fires.**
- **No parameter may be tuned** — every number is in this document.
- **No new funding hypothesis may be registered** as a variation of a failed
  one. A genuinely new idea requires a new program with its own
  justification, and inherits the record of this one.
- **If all fifteen tests fail or report unmeasurable at C2, the
  funding-as-signal question is CLOSED at this depth**, and that closure is
  written up with the same detail as a pass would have been.

The point of fixing this now is that in June 2027 there will be a strong
temptation to adjust a threshold that "just missed". This paragraph exists
to make that visibly a violation rather than a judgement call.

## EXECUTION CHECKLIST for the future session

1. Verify the trigger: span >= 22 months for all three symbols. If not, stop.
2. Verify the collector's continuity: report any gap > 3 days in the archive
   and its effect on consecutive-hour rules (F2, F8).
3. Run the OKX cross-venue correlation; flag any symbol below 0.80.
4. Build daily-mean funding, excluding days with < 20 of 24 hourly rows;
   report how many days were excluded per symbol.
5. Apply the lockbox (last 6 months) and the 4-month burn-in; report the
   resulting usable window and its exact dates.
6. Score all 15 tests. Report `n`, **episodes**, win%, `net_all`, `ex_best`,
   folds counted, and the placebo p95 and p99.67 for each.
7. Apply the pass conditions. Report every result, pass, fail or
   unmeasurable, with episode counts beside trade counts.
8. Do not proceed to C2 before its own span condition is met.

## DATA COMPLETENESS — audited 2026-08-28, timestamps only

Run by `research/audit_funding_gaps.py`, which reads the `symbol` and
`timestamp` columns and **nothing else** — not `funding_rate`, not
`relative_funding_rate`, and no join against price. `usecols` enforces it:
the value columns are never loaded. This program's central property is that
it was registered before anyone saw the series it will be tested on, and
counting timestamps is feed behaviour where reading values would be a peek.

| symbol | rows | span (days) | complete% | missing hours | gaps | longest gap | gaps > 8h |
|---|---|---|---|---|---|---|---|
| `PF_ETHUSD` | 8772 | 365.8 | **99.898%** | 9 | 8 | **3.0h** | 0 |
| `PF_SOLUSD` | 8773 | 365.8 | **99.909%** | 8 | 7 | **3.0h** | 0 |
| `PF_XBTUSD` | 8772 | 365.8 | **99.898%** | 9 | 8 | **3.0h** | 0 |

### Why this is registered beside the no-gap-tolerance rule

F2 (72h negative run) and F8 (168h negative run) count consecutive hours with
**no gap tolerance** — a missing hour breaks the run. That rule is only
defensible if the feed's gap behaviour is known in advance, so it is recorded
here rather than discovered at trigger time.

The archived year is **99.90% complete**: 8–9 missing hours per symbol across
7–8 gaps, longest **3.0 hours**, and **zero gaps longer than 8 hours**.

Expected incidence of a gap falling inside a qualifying run, at this rate
(8 gaps in 8,772 hours, treating gaps as uniformly distributed):

- **F2, 72h window:** 1 − (1 − 72/8772)^8 ≈ **6.4%** of candidate runs broken.
- **F8, 168h window:** 1 − (1 − 168/8772)^8 ≈ **14.3%** of candidate runs broken.

**This is accepted, not corrected for.** Breaking a run on a real data gap is
the conservative direction: it under-counts events rather than inferring a
continuity that was never observed. But it is now a KNOWN cost of roughly one
in seven F8 candidates, registered before the fact, so a thin F8 event count
at trigger time is not a surprise and is not grounds for relaxing the rule.

**Re-run this audit at trigger time and report it again.** If completeness has
fallen materially below 99.9%, or any gap exceeds 8 hours, say so beside the
results — the collector staleness check (below) exists to make that unlikely,
not impossible.

## COLLECTOR MONITORING — the archive is the only copy

`audit.py`'s `check_derivatives_collector` FAILs when the newest row in
`data/derivatives/kraken_funding.csv` is more than **3 days** old, and the
weekly audit workflow opens an issue on it.

Three days, where the signal log's threshold is six hours and every other
staleness check here is recoverable. This one is not: **Kraken serves a
one-year rolling window, so a day not collected is dropped by the venue and
is gone from this program's test sample permanently.** There is no backfill.
A silent collector failure today costs test data in 2027 that cannot be
bought back at any price.

---

# REGISTERED PROGRAMS — SHADOW-EVAL, ROTATION (#187-#192), ALLOCATION (#193-#196), ABLATION (#197-#202)

> **LOCKED 2026-08-28.** Approved with two amendments, both incorporated:
> ROTATION gains control #191b (random-5, distributional, Bonferroni
> unchanged at k=6), and ABLATION's removal scheme is pinned to
> one-at-a-time-from-full. From this commit research rule 4 applies: no
> parameter, threshold, control or pass condition below may be changed on
> the basis of a result.

Four programs. Every constant is fixed below. Nothing has been run and no
data has been looked at for any of them.

Standing rules apply throughout: registered before scoring (rule 3), no
parameter changed after a result (rule 4), negatives reported with the same
detail as positives (rule 5), lockbox never read (rule 2).

---

## A. SHADOW-EVAL — evaluating the shadow basket

**Registered before the first shadow row exists.** `shadow_log.csv` was
created empty by commit `49a1245`; this document is written before it has
been read for any purpose.

### Trigger

**30 pooled CLOSED episodes** across the tradable-26 in `shadow_outcomes.csv`.
Episodes, not rows and not trades: the log writes ~26 rows an hour and a
standing signal produces dozens of rows for one tradeable event.

**The shadow log may not be inspected before the trigger.** Not plotted, not
tallied, not "just to see how it's going". A peek at 12 episodes that shapes
what is asked at 30 is the failure this project has spent its whole record
guarding against.

### Scope, and the superset caveat

This evaluates the **UNGATED** construction. The gate is dampen-only, so
shadow BUY days are a strict superset of gated ones. A SHADOW-EVAL result is
therefore evidence about the ungated basket incumbent and is **NOT** a
drop-in estimate of the gated live system. It is expected to coincide
(`gate_multiplier` has been 1.0 on every production row ever logged) but
expected is not verified, and the write-up must say which object was
measured.

### Protocol — run ONCE

| item | value |
|---|---|
| trigger | 30 pooled closed episodes |
| pooling | all 26 tickers pooled; per-ticker reported but not tested |
| statistics | n, **episodes**, win%, `net_all`, `ex_best`, `total_R`, `maxDD_R`, median stop%, median `cost_r` |
| folds | 4 equal-duration time splits of the shadow span |
| placebo | **episode-matched**, 300 seeds, per #167 |
| costs | 2bps fee + 2bps slippage per side (trade-level convention, NOT the portfolio 8bps) |

**Reported outcome, no pass/fail.** At 30 episodes `ex_best` will almost
certainly be undefined (3 folds x 10 trades is the bar, and 30 episodes
spread over 4 folds is ~7 each). **That is the expected result and it is
recorded now** so that "unmeasurable" cannot later be presented as
disappointing news. SHADOW-EVAL answers *how fast is forward evidence
accumulating and what does it look like*, not *is there an edge*.

**A second checkpoint at 100 pooled episodes is registered now**, identical
protocol, so running it is a pre-declared sample increase and not a second
bite. No third checkpoint; if 100 episodes does not settle it, that is the
finding.

---

## B. ROTATION — #187–#192

Cross-sectional momentum on the tradable-26. Scored through
`research/portfolio_harness.py`, which passed its equivalence gate to
machine precision before this was written.

### Fixed parameters

| element | value |
|---|---|
| universe | the #167 tradable-26, fixed, no additions |
| lookbacks | **30d** and **90d**, each with a **3-day skip** (signal uses returns to t−3, avoiding short-horizon reversal) |
| selection | **top-5** and **top-10** by lookback return |
| weighting | equal-weight within the selection |
| rebalance | **weekly**, every Monday 00:00 UTC |
| costs | **8bps per side** on traded notional |
| windows | **BOTH** DISCOVERY and CONFIRMATION, on the current frozen dataset |
| folds | 4 equal-duration time splits per window |
| placebo | **rank-permutation**, 300 seeds |
| k (Bonferroni) | **6** |

### The six hypotheses

2 lookbacks x 2 selection sizes = 4, plus 2 registered controls = **6 tests**,
which is exactly the k the correction uses.

| # | rule |
|---|---|
| **#187** | top-5 by 30d return, skip 3d, weekly |
| **#188** | top-10 by 30d return, skip 3d, weekly |
| **#189** | top-5 by 90d return, skip 3d, weekly |
| **#190** | top-10 by 90d return, skip 3d, weekly |
| **#191** | CONTROL: equal-weight all 26, weekly rebalance (the "did selection do anything" benchmark) |
| **#191b** | CONTROL (distributional): **random-5**, five assets drawn uniformly without replacement at each weekly rebalance, equal-weight, same costs. **1,200 draws**, reported as a DISTRIBUTION, not a point estimate. |
| **#192** | CONTROL: **bottom**-5 by 30d return, skip 3d, weekly (if momentum is real, this should be its mirror; if both win, the result is beta, not selection) |

**#191b is a CONTROL, not a hypothesis.** It is not counted in the Bonferroni
correction, which stays at **k = 6**. It carries no pass rule of its own and
cannot pass or fail; it exists solely to supply a null distribution for
five-asset selection at this turnover.

Why it is needed on top of #191: equal-weight-26 answers "did selecting help
at all", but it is a *different portfolio* — 26 names, near-zero turnover. A
top-5 rule that beats it might be winning on concentration or on turnover
timing rather than on selection. Random-5 holds concentration, position
count, rebalance cadence and cost structure IDENTICAL and randomises only
which five. It is the tightest available null for a five-asset picker.

**Additional condition for the top-5 rules (#187, #189):** annualised net
return must also exceed **#191b's p95**. #188 and #190 are top-10 and are not
subject to it — random-5 is not their matched null, and inventing a random-10
after seeing results would be exactly the move this project forbids.

#191 and #192 are registered as controls and carry the same pass rule as the
rest. #192 exists because a rotation rule that wins while its inverse also
wins has demonstrated exposure, not skill.

### Pass rule

On **BOTH** windows, all required:

1. Annualised net return **> 0**, AND
2. Annualised net return above the **rank-permutation placebo's
   Bonferroni-adjusted percentile**: alpha = 0.05/6 = 0.00833, so the
   **99.17th percentile**. With 300 seeds that percentile is estimated from
   the top ~2.5 draws, so **seeds are raised to 1,200** for the adjusted
   threshold (~10 draws above it); p95 reported alongside from the same
   draws.
3. Beats #191 (equal-weight-26) on annualised net return **on both windows**, AND
4. **For #187 and #189 only:** beats **#191b random-5's p95** on both windows.

Condition 3 is the one that matters most: a rotation rule that cannot beat
holding all 26 has not earned its turnover. Condition 4 closes the remaining
gap — beating equal-weight-26 could be concentration; beating random-5 at the
same concentration and cadence can only be selection.

**Single confirmation, no partial credit, no re-runs.**

---

## C. ALLOCATION — #193–#196

Exposure scaling on a fixed basket. Answers a different question from
ROTATION: not *which* assets, but *how much*.

### Fixed parameters

| element | value |
|---|---|
| universe | tradable-26, equal-weight within the invested portion |
| vol targets | **30%** and **50%** annualised |
| vol estimator | 30-day realised stdev of daily portfolio returns, annualised by sqrt(365) |
| leverage cap | **1.5x** gross, hard |
| floor | 0.0x (fully in cash is permitted) |
| rebalance | weekly, Monday 00:00 UTC |
| costs | 8bps per side on traded notional |
| windows | BOTH DISCOVERY and CONFIRMATION |
| placebo | **block-shuffle**, block = **21 days**, 1,200 seeds |
| k (Bonferroni) | **4** |

### The four hypotheses

| # | rule |
|---|---|
| **#193** | 30% vol target, cap 1.5x |
| **#194** | 50% vol target, cap 1.5x |
| **#195** | CONTROL: constant 1.0x equal-weight-26 (no scaling) |
| **#196** | CONTROL: **inverted** signal — scale UP when realised vol is high (if vol-targeting works, its inverse should not) |

### Matched-exposure benchmark — the condition that makes this honest

A vol-targeted portfolio that happens to run higher average gross exposure
will out-return a 1.0x benchmark **for that reason alone**, and reporting
that as a vol-targeting result would be a category error.

So each of #193/#194 is compared against a **matched-exposure benchmark**:
constant-weight equal-26 scaled by a single constant chosen so its **average
gross exposure over the window equals the tested rule's**. That constant is
computed from the tested rule's own realised exposure — it is not a free
parameter and nothing is chosen by looking at returns.

### Pass rule

On **BOTH** windows, all required:

1. Annualised net return **> 0**, AND
2. Above the block-shuffle placebo's Bonferroni percentile: alpha =
   0.05/4 = 0.0125, the **98.75th percentile**, from 1,200 seeds, AND
3. **Sharpe** above the **matched-exposure benchmark's** Sharpe.

Condition 3 is the test. Vol targeting claims better risk-adjusted return at
comparable exposure; matching exposure is what isolates that claim from
simply holding more.

**Single confirmation, no partial credit, no re-runs.**

---

## D. ABLATION — #197–#202

Which components of the incumbent's BUY_ALL construction carry its behaviour?
BTC only, on the current frozen dataset, both windows.

Not a search for an edge — #171 established BTC INC_BUY_ALL is negative on
DISCOVERY. This asks what the pieces contribute, which is worth knowing
whether the total is positive or not.

### Removal scheme: ONE-AT-A-TIME-FROM-FULL

**Fixed before lock.** Every rung removes **exactly one** component from the
FULL construction and restores everything else to production values. Rungs
are independent of each other and of their listed order.

**Why not cumulative.** Under cumulative removal each rung's delta would
contain every prior removal, so no delta would be attributable to its own
component, every number would depend on an arbitrary listing order, and the
final rung would be "almost everything removed" — a different model, not an
ablation. One-at-a-time is the only scheme where the delta at rung k is a
statement about component k.

**Its limitation, stated now.** One-at-a-time measures MAIN EFFECTS only. A
component that matters solely in combination with another will read as NO
DETECTABLE CONTRIBUTION here, and that is a real blind spot rather than
evidence of irrelevance. Interaction terms are out of scope for this program
and may not be inferred from it; testing one requires its own registered
hypothesis.

| # | rung | change from full |
|---|---|---|
| **#197** | full construction | baseline (= #171's measurement, reproduced) — the reference every delta is taken against |
| **#198** | no Step 3 | weights become 1.0 pattern / 0.0 indicators |
| **#199** | no Step 1 | weights become 0.0 pattern / 1.0 indicators |
| **#200** | no confirm | `confirm_days` 2 → 1 |
| **#201** | no VIX regime | `extreme_fear_mode` disabled, bars fixed at 60/40 |
| **#202** | no conviction scaling | STRONG_BUY target multiplier 1.333 → 1.0 |

### The epsilon rule — fixed now

A rung "matters" if removing it moves `net_all` by more than

**epsilon = 0.05 R**

in absolute terms, on **both** windows in the **same direction**.

0.05R is fixed here and derives from a measured quantity, not taste: the
median `cost_r` on BTC 4h is **0.045R** (recorded in #163's liquidity table).
A component whose removal moves expectancy by less than one round trip's
transaction cost cannot be distinguished from friction, so that is the floor.

**Any rung moving less than epsilon on either window, or moving in opposite
directions across the two, is reported as NO DETECTABLE CONTRIBUTION.** That
is a result, not a failure, and it may not be re-tested at a smaller epsilon.

### Reporting

Every rung reports n, **episodes**, win%, `net_all`, `ex_best`, and the delta
against #197 on both windows, plus a **window-stability profile**
(`research/window_stability.py`, 50 starts) beside each delta — because #171
demonstrated that a single-window delta on this construction can reverse.

**No pass/fail and no Bonferroni.** ABLATION is descriptive: it apportions
behaviour, it does not claim edge. Nothing may be promoted from it, and any
component it flags as load-bearing needs its own registered hypothesis
before it becomes a claim.

---

# ABLATION RESULTS — #197–#202, run 2026-08-30

BTC INC_BUY_ALL, both windows, one-at-a-time-from-full as locked.
Scripts: `research/run_ablation.py`, `research/run_ablation_stability.py`.
Raw: `research/ablation_results.json`, `research/ablation_stability.json`.

Windows (dataset last date 2026-08-26): DISCOVERY 2019-09-24 → 2023-04-06
(1,269 days), CONFIRMATION 2023-04-06 → 2026-02-26 (1,056 days), LOCKBOX
sealed and unread.

## The reconstruction gate — passed before anything was scored

Rungs #198/#199/#201 alter the `direction` column, which means recomputing
it from its components. That is only legitimate if the recomputation
reproduces the stored column exactly under production settings; otherwise
the rungs would be measured against a baseline whose construction they do
not share.

| check | result |
|---|---|
| `combined_final_score` rebuilt vs stored, max abs err | **1.42e-14** |
| `direction` rebuilt vs stored, mismatching days | **0 of 2,325** |

Reproduced as `0.6 × gated_score + 0.4 × final_score` → `classify_direction`.
Zero mismatches across every scored day. The rungs and #197 share a
construction, so the deltas mean what they claim to.

## Results

**DISCOVERY** — baseline #197 `net_all` = **−0.157**

| # | rung | sigdays | n | eps | win% | net_all | delta | ex_best | folds+ |
|---|---|---|---|---|---|---|---|---|---|
| #197 | full construction | 192 | 92 | 30 | 28.3 | −0.157 | — | −0.466 | 1/4 |
| #198 | no Step 3 (1.0/0.0) | 272 | 101 | 33 | 33.7 | +0.018 | **+0.175** | −0.217 | 1/4 |
| #199 | no Step 1 (0.0/1.0) | 247 | 189 | 19 | 34.4 | +0.009 | +0.166 | −0.093 | 2/4 |
| #200 | no confirm (2→1) | 192 | 192 | 28 | 30.2 | −0.113 | +0.045 | −0.287 | 1/4 |
| #201 | no VIX regime | 193 | 92 | 30 | 28.3 | −0.157 | +0.000 | −0.466 | 1/4 |
| #202 | no conviction scaling | 192 | 92 | 30 | 28.3 | −0.194 | −0.036 | −0.466 | 1/4 |

**CONFIRMATION** — baseline #197 `net_all` = **+0.195**

| # | rung | sigdays | n | eps | win% | net_all | delta | ex_best | folds+ |
|---|---|---|---|---|---|---|---|---|---|
| #197 | full construction | 202 | 108 | 23 | 39.8 | +0.195 | — | +0.097 | 3/4 |
| #198 | no Step 3 (1.0/0.0) | 223 | 84 | 24 | 41.7 | +0.314 | **+0.119** | +0.234 | 4/4 |
| #199 | no Step 1 (0.0/1.0) | 360 | 286 | 21 | 36.7 | +0.084 | −0.111 | +0.018 | 3/4 |
| #200 | no confirm (2→1) | 202 | 202 | 20 | 36.1 | +0.079 | −0.116 | −0.008 | 2/4 |
| #201 | no VIX regime | 202 | 108 | 23 | 39.8 | +0.195 | +0.000 | +0.097 | 3/4 |
| #202 | no conviction scaling | 202 | 108 | 23 | 39.8 | +0.146 | −0.049 | +0.065 | 3/4 |

Episode counts are what these rest on: **30 and 23** at the baseline. Every
number in these tables is built on fewer than three dozen occasions per
window, and nothing below should be read as more precise than that allows.

## Window-stability of each delta (50 starts, end pinned)

| # | DISCOVERY | CONFIRMATION |
|---|---|---|
| #198 | **100% positive**, +0.038…+0.185, med +0.123 | **100% positive**, +0.064…+0.175, med +0.100 |
| #199 | 54% negative, −0.189…+0.218, med −0.030 | 92% negative, −0.175…+0.018, med −0.104 |
| #200 | 56% negative, −0.104…+0.054, med −0.003 | 100% negative, −0.153…−0.055, med −0.111 |
| #201 | **100% zero**, +0.000…+0.000 | **100% zero**, +0.000…+0.000 |
| #202 | **100% negative**, −0.064…−0.036, med −0.045 | **100% negative**, −0.068…−0.046, med −0.055 |

All 50 starts defined in every cell. Sign-stability has no registered
threshold and none is invented here.

## Epsilon verdicts (registered: |delta| > 0.05R on both windows, same direction)

| # | rung | dDISC | dCONF | verdict |
|---|---|---|---|---|
| #198 | no Step 3 | +0.175 | +0.119 | **LOAD-BEARING** |
| #199 | no Step 1 | +0.166 | −0.111 | NO DETECTABLE CONTRIBUTION (opposite signs) |
| #200 | no confirm | +0.045 | −0.116 | NO DETECTABLE CONTRIBUTION (below epsilon on DISC) |
| #201 | no VIX regime | +0.000 | +0.000 | NO DETECTABLE CONTRIBUTION (below epsilon, both) |
| #202 | no conviction scaling | −0.036 | −0.049 | NO DETECTABLE CONTRIBUTION (below epsilon, both) |

These verdicts stand exactly as the registration wrote them. No rung is
re-tested at a smaller epsilon.

## What the numbers say

**#198 — Step 3 is load-bearing, and it is load-bearing in the WRONG
DIRECTION.** Deleting the indicator side and running on pattern+sentiment
alone IMPROVES expectancy on both windows: +0.175R on DISCOVERY, +0.119R on
CONFIRMATION, positive at 100 of 100 window starts, and it turns DISCOVERY
from −0.157 to roughly flat. It is the only rung that clears the registered
bar, and it clears it by saying the component subtracts.

This is not a new suspicion. `combine_and_decide`'s own docstring records
that the 0.6/0.4 split "reflects THIS SESSION'S walk-forward finding that
squeeze was more consistent than the RSI/MACD/momentum-style indicators."
The ablation says the weight should have kept going: at 0.4, the indicator
block is still a net drag on both windows.

What it does NOT say: that 1.0/0.0 is a better model worth shipping. This
program cannot promote anything, the epsilon rule is not a significance
test, and 30 and 23 episodes are thin. It says one specific thing — the
indicator block does not pay for its weight — and that is a hypothesis for
its own registration, not a result to trade.

**#199 and #200 fail on the disagreement between windows, and that is the
finding.** Removing Step 1 helps DISCOVERY by +0.166 and hurts CONFIRMATION
by −0.111. Dropping confirmation from 2 days to 1 does the same in
miniature. Either window alone would have supported a confident story; the
pair supports neither. The stability profiles show why the registration
demanded both: #199 is a coin-flip on DISCOVERY (54%) and near-unanimous on
CONFIRMATION (92%), and #200 goes from 56% to 100%. A single-window ablation
would have published a component effect that the other half of the data
contradicts.

**#201 is exactly zero, and the reason is more interesting than the zero.**
The extreme-fear regime is not dormant — VIX ≥ 35 on **80 DISCOVERY days
(6.3%)** and 10 CONFIRMATION days, and the raised bars change **35 labels**
across the two windows. But BUY-tier membership changes on exactly **one
day** (2020-06-21, combined 62.2, VIX 35.1), and that day is unconfirmed, so
it produces no trade. Every other label change is on the SELL side, which
INC_BUY_ALL never trades.

The mechanism: in a panic the composite score is low. Median combined score
on extreme-fear days is **36.9** on DISCOVERY and **22.5** on CONFIRMATION,
against a raised buy bar of 70. Days in [60, 70) — the only band where the
raised bar can bind — number **1** in 3.5 years and **0** in 2.9 years.

So the correct statement is not "the VIX regime does not matter." It is:
**on the long side, this component has never been exercised.** Its
contribution is unmeasured rather than measured-and-small, and it would
first become measurable in a regime where BTC scores highly while equity
volatility is extreme — which has not happened in seven years of this
dataset. Recording it as NO DETECTABLE CONTRIBUTION is right by the letter
of the rule and would be misread without this paragraph.

**#202 is the case where the epsilon rule bites, and it should be allowed
to.** Removing conviction scaling costs −0.036 on DISCOVERY and −0.049 on
CONFIRMATION: same direction, both windows, and **100% sign-stable across
all 100 window starts** with the entire range on one side of zero. Both
readings sit below the 0.05R epsilon — CONFIRMATION by 0.001.

The registration's floor was derived from BTC's 0.045R median `cost_r`: a
move smaller than one round trip's friction cannot be told apart from
friction. That reasoning does not stop applying because the answer landed
just under. The verdict is NO DETECTABLE CONTRIBUTION, the profile is
recorded beside it, and the near-miss is disclosed here rather than resolved
by moving the line. Anyone wanting to claim conviction scaling helps needs a
registration that says so in advance.

## An instrument defect found and fixed

`window_stability.profile` reported the identically-zero #201 series as
"sign-stability 0% (positive)" — its most-unstable label for the most stable
series it can be handed, because `max(pos, neg)` is 0 when every value is
zero. A reader skimming that column would have concluded the opposite of the
truth. Fixed: the all-zero case now reports `modal_sign="zero"` with
stability 1.0, covered by four tests. No registered threshold depends on
sign-stability, so nothing in this program changes; the numbers above were
recomputed after the fix and are identical apart from that label.

## Scope

Descriptive, as registered. No pass/fail, no Bonferroni, nothing promoted.
One-at-a-time measures MAIN EFFECTS only: a component mattering solely in
combination reads as no-detectable-contribution here, and no interaction may
be inferred from this program. #198 in particular is a finding about the
indicator block's weight, not a licence to ship 1.0/0.0.

---

# #203 — SQUEEZE-ONLY PROMOTION

**REGISTERED 2026-08-30, before any leg was run.** Nothing below may change
on the basis of a result (research rule 4).

## Where this came from, and the honest caveat about that

ABLATION #198 found that deleting Step 3 improves BTC INC_BUY_ALL on both
windows (+0.175R DISCOVERY, +0.119R CONFIRMATION, positive at 100 of 100
window starts). ABLATION is descriptive and explicitly cannot promote
anything, so this is the registration that asks the promotion question
properly.

**#203 is NOT independent evidence of #198.** It is the same construction on
the same frozen windows, and it will inherit whatever #198 saw. What it adds
is a *bar*: #198 reported a delta with no null to beat, while #203 must clear
`ex_best > 0` and an episode-matched placebo on both windows — the same bar
#171 set and failed. A construction can improve on the incumbent and still be
worthless, because the incumbent is negative on DISCOVERY. Beating it is not
the test; beating chance is.

The out-of-sample question is answered by the shadow arm below, not here.

## The construction

`SQUEEZE_ONLY` — the incumbent with `weight_pattern = 1.0`,
`weight_indicators = 0.0`. Everything else at production values:

| parameter | value |
|---|---|
| direction rule | `classify_direction`, bars 75/60/40/25 |
| extreme-fear | `symmetric`, `vix_extreme` 35, `panic_shift` 10 |
| geometry | `LIVE_GEOMETRY` — 4h ATR, stop 1.5, target 3.0, hold 15d, SMA 50 |
| confirm_days | 2 |
| conviction scaling | on (STRONG_BUY target ×1.333) |
| costs | 2.0 bps fee + 2.0 bps slippage per side |
| tier scored | BUY_ALL = {BUY, STRONG_BUY} |
| folds | 4 |

Ticker **BTC only**. Both windows of the current frozen dataset (last date
2026-08-26): DISCOVERY 2019-09-24 → 2023-04-06, CONFIRMATION 2023-04-06 →
2026-02-26. **LOCKBOX sealed and unread.**

The direction column is rebuilt from `1.0 × gated_score + 0.0 × final_score`
and must pass the same reconstruction gate ABLATION used — production
weights must reproduce the stored `direction` exactly, 0 mismatches — before
any ablated column is scored.

## Pass conditions — both windows, both clauses

1. **`ex_best` > 0**, on both windows.
2. **`net_all` strictly above the episode-matched placebo p95**, on both
   windows, **1,200 seeds**.

`ex_best` requires ≥3 folds of ≥10 trades each. **Undefined `ex_best` is
UNMEASURABLE, not a pass and not a fail**, and is reported as such — the
project's standing convention.

The placebo is **episode-matched** as registered in #167: draws reproduce the
observed run-length distribution and conviction mix, because independent-day
draws are lower-variance than clustered signals and would make any clustered
signal look strong. 1,200 seeds, fixed here.

**Single hypothesis, no Bonferroni correction.** #203 is one test.

## Reported whatever the outcome

n, **episodes**, win%, `net_all`, `ex_best`, folds counted/positive, placebo
p95 and percentile — both windows — **plus a 50-start window-stability
profile of `net_all`** attached to the result regardless of pass or fail.
That profile is not a pass condition and no threshold may be read off it; it
is attached because #171 demonstrated that a single-window number on this
construction can reverse, and #203 must not repeat that omission.

Negatives are reported with the same detail as positives (research rule 5).

## The shadow arm — effective immediately

`shadow_basket.py` logs **both** label sets per ticker-day, side by side:
`decision`/`direction` for the incumbent 0.6/0.4 construction, and
`sq_decision`/`sq_direction` for SQUEEZE_ONLY 1.0/0.0. Same bar, same price,
same daily indicator pull, zero additional Adanos requests — the second
label is a re-blend of scores already computed, not a second data fetch.

**The superset note applies to BOTH.** Shadow scores are UNGATED, so each
label set is a superset of what the gated pipeline would have marked BUY.
Shadow BUY counts are an upper bound on gated BUY counts for the incumbent
and for SQUEEZE_ONLY alike, and neither is a drop-in estimate of gated live
behaviour.

Each arm carries **its own exit levels** (`sq_target_price`, `sq_stop_price`,
`sq_risk_reward`), because a label with no target and stop cannot become an
episode, and an arm that accrues no episodes cannot answer this question.
Resolution reuses `live_tools.extract_episodes` / `resolve_episode`
**unchanged**: an arm is scored by projecting its columns onto the canonical
names, never by a second copy of the episode logic. Outcomes land in separate
files (`shadow_outcomes.csv`, `shadow_sq_outcomes.csv`) so the two records
cannot be pooled by accident.

**A defect found while building this, disclosed here.** The first version of
`shadow_basket.py` read exit levels off `combine_and_decide`, which does not
return them — `run_full_pipeline` computes them afterwards. Every row would
have logged `target_price=None`, and `extract_episodes` skips rows without
target+stop, so the shadow basket would have accrued labels forever and
**zero resolvable episodes** — while looking healthy, because a log full of
rows reads as a log that is working. It was caught before the first row was
written, so no forward record was lost. Both arms now compute levels the way
the live path does, covered by an end-to-end test that a logged BUY row
actually survives `extract_episodes`.

This accrues toward SHADOW-EVAL's **30 pooled closed episodes** checkpoint.
The log is not inspected before that checkpoint, and this arm does not change
it: the same 30-episode threshold, the same single evaluation, the same
episode-matched placebo.

## Promotion requires BOTH — neither alone

Live promotion of SQUEEZE_ONLY requires:

- **the in-sample pass** — #203 clearing both clauses on both windows, AND
- **shadow agreement at the 30-episode checkpoint** — the forward record
  agreeing with the in-sample direction.

**Neither alone is sufficient, and this is fixed now, before either is
known.** An in-sample pass on a construction discovered by ablating the same
data is exactly the result most likely to be a window artefact — #171 is the
worked example of what that looks like when it goes wrong. A shadow agreement
alone would be 30 episodes with no null and no second window. The conjunction
is the claim; either half on its own is not.

If #203 fails, the shadow arm keeps logging. It costs nothing, and a forward
record of a construction the frozen data rejected is worth having — it is the
only way this project ever learns that a rejection was the window's fault
rather than the model's.


## #203 RESULT — FAIL, run 2026-08-31

`research/run_203.py`, raw in `research/h203_results.json`.

Reconstruction gate passed first: production weights reproduce the stored
`direction` with **0 mismatches in 2,325 days**, `combined_final_score` max
abs err 1.42e-14. The placebo lookup was then verified trade-for-trade
against the scored construction on each window — **101 and 84 trades MATCH**
— before a single draw was taken.

| window | n | episodes | win% | net_all | ex_best | folds+ | placebo p95 | pctile |
|---|---|---|---|---|---|---|---|---|
| DISCOVERY | 101 | 33 | 33.7 | +0.018 | −0.217 | 1/4 | +0.191 | 68.3 |
| CONFIRMATION | 84 | 24 | 41.7 | **+0.314** | **+0.234** | **4/4** | +0.370 | 91.5 |

**Window-stability of `net_all`** (50 starts, end pinned), attached as
registered:

| window | defined | sign-stability | range | median |
|---|---|---|---|---|
| DISCOVERY | 50/50 | **100% positive** | +0.011 … +0.215 | +0.061 |
| CONFIRMATION | 50/50 | **100% positive** | +0.166 … +0.412 | +0.245 |

### Registered conditions

| window | `ex_best` > 0 | `net_all` > placebo p95 |
|---|---|---|
| DISCOVERY | −0.217 → **FAIL** | +0.018 vs +0.191 → **FAIL** |
| CONFIRMATION | +0.234 → PASS | +0.314 vs +0.370 → **FAIL** |

**VERDICT: FAIL.** Three of four clauses fail. No promotion.

### What actually happened, and it is not what #198 suggested

Everything #198 said is confirmed here. Squeeze-only beats the incumbent on
both windows; it is positive on both; its DISCOVERY `ex_best` improves from
−0.466 to −0.217 and its CONFIRMATION `ex_best` of **+0.234 on 4 of 4
positive folds is the strongest this project has ever measured.** It is also
the most sign-stable construction in the record: positive at **100 of 100**
window starts across both windows, where the incumbent was 88% *negative* on
DISCOVERY.

And it fails, because none of that was the test.

**The placebo is what it fails against, and the placebo is high for a
reason.** Episode-matched draws — same run-length distribution, same
conviction mix, same 15-day holds, entering at random — reach a p95 of
**+0.191** on DISCOVERY and **+0.370** on CONFIRMATION. Random clustered
long exposure on BTC over these windows makes money. So does squeeze-only.
Squeeze-only does not make *more* than the top of that range: it sits at the
68th percentile on DISCOVERY and the 91st on CONFIRMATION.

**The distinction that matters: exposure versus selection.** Squeeze-only's
positive expectancy is real and stable. What #203 tested is whether the rule
picks better days than chance picks, holding the shape of the exposure
fixed. It does not. The stability profile measures the same thing the point
estimate does — how reliably this construction is long a rising asset — and
100% sign-stability on an exposure statistic is not evidence of selection
skill. Two instruments agreeing does not make them two pieces of evidence.

**#198 and #203 are both correct and they answer different questions.**
"Better than the incumbent" and "better than chance" are not the same bar,
and on a negative baseline the first is nearly free. This is exactly why
ABLATION was written as descriptive with no promotion path, and why the
registration said in advance that #203 was not independent evidence of #198.

CONFIRMATION at the 91.5th percentile is the closest any construction has
come. It is still a fail, and it is a fail on 24 episodes.

### Consequences, as registered

- **No promotion.** The in-sample half of the conjunction is not satisfied,
  so the promotion question is closed regardless of what the shadow record
  does. It cannot be reopened by shadow agreement alone — that was fixed
  before either half was known.
- **`claims.md` is unchanged.** Nothing here becomes SUPPORTED. It still
  holds zero supported edge claims.
- **The shadow arm keeps logging**, exactly as the registration said it
  would on a failure. A forward record of a construction the frozen data
  rejected is the only way this project ever learns that a rejection was the
  window's fault rather than the model's, and it costs nothing.
- **No re-test at a looser bar.** Not at p90, not on CONFIRMATION alone, not
  with the placebo re-specified. The bar was set before the run.

### What would legitimately move this

A construction that beats the episode-matched placebo needs to differ from
chance in *which days it picks*, not in how much it is exposed. Nothing in
#197–#203 has done that on BTC. Any future attempt is a new registration,
and it starts by explaining what it selects on — because "positive and
stable" has now been demonstrated to be reachable by random entry.

---

# ROTATION RESULT — #187–#192 + control #191b, run 2026-08-31

`research/run_rotation.py`, `research/rotation_verdicts.py`. Raw in
`research/rotation_results.json`, `research/rotation_verdicts.json`.

**VERDICT: #187 FAIL, #188 FAIL, #189 FAIL, #190 FAIL, #192 FAIL.**
Nothing passes. Nothing is promoted.

## Two specification completions, pinned before the first run

The locked text fixes the rules but is silent on two things the data forces.
Both were decided before any number was produced, and both are disclosed
here rather than buried.

**(1) Eligibility.** The tradable-26 did not all exist in 2019 — **6 of 26**
have prices at DISCOVERY's start, 25 by CONFIRMATION. An asset is eligible at
a rebalance if it has a **complete price history over that rule's own
(lookback + skip) window** ending at that date. A rule trades only when it has
strictly **more** eligible candidates than slots — a top-5 rule needs at least
6 to be selecting anything — and otherwise holds cash. Executed/skipped
rebalance counts are reported per rule (they range 166–180 of 184 on
DISCOVERY, 138–146 of 151 on CONFIRMATION).

Chosen over the alternatives deliberately: requiring 2N eligible would leave
the top-10 rules untestable on 72% of DISCOVERY, and ranking N of exactly N
is not a selection at all.

**(2) Matched controls.** #191b randomises *only which five*, so it draws
from the **same eligible set as the rule it nulls** — computed separately for
the 30d and 90d families. #191 equal-weights every asset with a complete
33-day history, one benchmark for all rules as registered.

**Unchanged:** lookbacks, skip, selection sizes, weighting, weekly Monday
cadence, 8bps per side, both windows, k = 6, and every pass clause.

## A placebo defect found before the run, and what it would have done

`rank_permutation_placebo` re-permuted **every row**. ROTATION's weights are
constant between weekly rebalances, so "hold these 5 names for a week" became
"hold 5 **different** random names every day."

Measured on #187/CONFIRMATION before the fix: placebo turnover **1.566
against the real rule's 0.116 — 13.6×** — and **13× the transaction costs**,
which dragged the null to −0.38/yr through fabricated trading alone. Every
rule would have cleared a bar that was crippled by costs it never paid. That
is a false-positive generator, and it was pointed at the answer this program
most wanted to hear.

Two constructions were then available, and the choice was made **before
seeing any rule's result**:

- **Per-rebalance permutation** (the fixed version of the original) destroys
  two things: which assets were picked, *and* the fact that a momentum rule
  keeps its winners week to week. The second is a turnover property, not a
  selection one. It still ran **1.84–2.91×** the real turnover.
- **Fixed whole-window relabelling** — the same weight path pointed at a
  permuted universe — differs from the strategy in **exactly one** respect.
  It ran **0.95–1.02×** the real turnover across all ten rule-window pairs.

The primary null is the **fixed relabelling**, because the contract for a
selection placebo is to destroy selection and nothing else. It is also the
control that stays *informative* next to #191b: random-5 redrawn weekly is
already the "reshuffle every rebalance" null, so a per-rebalance permutation
would largely duplicate it. The per-rebalance figures are reported below for
transparency and were **never used for a verdict**.

| | real | fixed-perm | per-rebalance |
|---|---|---|---|
| DISCOVERY #187 | 0.1088 | 0.1048 (0.96×) | 0.2112 (1.94×) |
| DISCOVERY #190 | 0.0494 | 0.0487 (0.99×) | 0.1270 (2.57×) |
| CONFIRMATION #187 | 0.1155 | 0.1132 (0.98×) | 0.2268 (1.96×) |
| CONFIRMATION #190 | 0.0550 | 0.0545 (0.99×) | 0.1599 (2.91×) |

Scoring also moved to a vectorised path (the reference loops over days, but
its `prev` is just the previous target row, so the loop is removable exactly).
It is **verified against `portfolio_returns` on every window's own weight
paths before a single draw is taken**: max abs err **2.22e-16** on DISCOVERY,
**4.44e-16** on CONFIRMATION.

## Results — every registered clause, both windows

Clauses: **1** ann > 0 · **2** ann > rank-permutation p99.17 (k=6, 1,200
seeds) · **3** ann > #191 · **4** ann > #191b p95 (#187, #189 only).

| # | rule | window | ann | plc p_adj | eq26 | r5 p95 | 1 | 2 | 3 | 4 |
|---|---|---|---|---|---|---|---|---|---|---|
| **#187** | top-5 30d | DISCOVERY | **+1.399** | +1.137 | +1.101 | +1.377 | PASS | PASS | PASS | **PASS** |  ⚠ *(clause 2 UNCITABLE — see the annotation below)*
| | | CONFIRMATION | +0.527 | +0.619 | +0.291 | +0.477 | PASS | **FAIL** | PASS | PASS |
| **#188** | top-10 30d | DISCOVERY | +1.321 | +0.973 | +1.101 | — | PASS | PASS | PASS | — |
| | | CONFIRMATION | +0.340 | +0.482 | +0.291 | — | PASS | **FAIL** | PASS | — |
| **#189** | top-5 90d | DISCOVERY | +1.400 | +1.136 | +1.101 | +1.481 | PASS | PASS | PASS | **FAIL** |
| | | CONFIRMATION | +0.298 | +0.622 | +0.291 | +0.478 | PASS | **FAIL** | PASS | **FAIL** |
| **#190** | top-10 90d | DISCOVERY | +1.170 | +0.914 | +1.101 | — | PASS | PASS | PASS | — |
| | | CONFIRMATION | +0.311 | +0.471 | +0.291 | — | PASS | **FAIL** | PASS | — |
| **#192** | bottom-5 30d | DISCOVERY | +0.749 | +1.072 | +1.101 | — | PASS | **FAIL** | **FAIL** | — |
| | | CONFIRMATION | −0.043 | +0.573 | +0.291 | — | **FAIL** | **FAIL** | **FAIL** | — |

### Controls

| window | #191 equal-weight | #191b random-5 (30d) | #191b random-5 (90d) | #192 bottom-5 |
|---|---|---|---|---|
| DISCOVERY | **+1.101**, turn 0.0254 | p05 +0.731 · p50 **+1.039** · p95 +1.377 | p05 +0.845 · p50 **+1.159** · p95 +1.481 | +0.749 |
| CONFIRMATION | **+0.291**, turn 0.0190 | p05 +0.013 · p50 **+0.233** · p95 +0.477 | p05 +0.010 · p50 **+0.228** · p95 +0.478 | −0.043 |

1,200 draws each, as registered.

### Window-stability of annualised net return (50 starts, end pinned)

| # | DISCOVERY | CONFIRMATION |
|---|---|---|
| #187 | 90% positive, −0.149…+1.607, med +1.457 | **100% positive**, +0.137…+1.072, med +0.560 |
| #188 | 92% positive, −0.115…+1.461, med +1.322 | **100% positive**, +0.037…+0.909, med +0.398 |
| #189 | 88% positive, −0.273…+1.495, med +1.241 | **100% positive**, +0.020…+0.908, med +0.314 |
| #190 | 78% positive, −0.392…+1.399, med +1.166 | 98% positive, −0.002…+0.862, med +0.301 |
| #192 | 82% positive, −0.180…+0.937, med +0.794 | 56% positive, −0.276…+0.426, med +0.048 |

All 50 starts defined everywhere. Profiled for **every** rule, not only those
passing something — choosing which results get an error bar on the basis of
their result is the move this project forbids.

## What actually happened

**Every rule dies on clause 2, on CONFIRMATION, and only there.** All four
momentum rules pass clauses 1 and 3 on both windows. All four clear the
adjusted placebo on DISCOVERY. Not one clears it on CONFIRMATION. That is a
single, sharp failure mode, not a scatter of small ones.


> ### ⚠ ANNOTATION ADDED 2026-08-31 — #187's DISCOVERY clause-2 pass is UNCITABLE
>
> **NULL-CALIBRATION #217 measured the null this comparison was made against.
> On DISCOVERY it held ~31.97% of its gross weight in assets that did not
> exist** (the real rule: 0.000%; only **5 of 26** assets were alive for the
> whole window). That weight earned exactly zero through `fillna(0.0)`,
> dragging the null's centre to **+0.5378 — 50.12 pp/yr BELOW random-5
> selection (+1.0390)** and 56 pp below equal-weight.
>
> Universe fidelity was never checked here because **axis 2 did not exist
> when ROTATION ran** — it was introduced by ALLOCATION, one program later.
>
> **The bar was far too EASY. #187's DISCOVERY clause-2 PASS may not be cited
> as evidence of anything**, here or anywhere.
>
> **Verdicts are unchanged.** #187 is FAIL and always was, on CONFIRMATION,
> whose null held only 3.40% ineligible weight and is unaffected.
>
> **The counterfactual is UNMEASURABLE.** The corrected time-rotation null
> cannot be run on either ROTATION window: its locked offset range
> [24, T−24] months is **empty** at **T = 42.4 months (DISCOVERY)** and
> **T = 34.7 months (CONFIRMATION)**. The bound may not be relaxed to force a
> run (research rule 4), and rotating over the full series to lengthen T
> would pull rows out of the LOCKBOX. Recorded as a data fact: **crypto's
> windows are too short to carry a rotation-based null at all.**

**#187 is the closest this project has come to a pass.** It clears **all four
clauses on DISCOVERY**, including the two that were designed to be hard: it
beats equal-weight-26 (+1.399 vs +1.101) and it beats random-5's p95 (+1.399
vs +1.377, by 0.022). Then CONFIRMATION returns +0.527 against a placebo
p99.17 of +0.619 and it is over. One window is not a result — that is the
entire reason there are two.

**The scale is the thing to hold on to.** Equal-weight-26 returned **+110%/yr
on DISCOVERY**. Random-5's *median* draw returned +104%/yr. Buying the
**worst** 5 performers returned +75%/yr. In that regime "the strategy made
money" carries no information whatsoever, and clause 1 is nearly free — which
is why the registration never let it stand alone.

**#192 is doing real work here.** Momentum's mirror does *not* win: +0.749 on
DISCOVERY against equal-weight's +1.101, and **−0.043 on CONFIRMATION** while
equal-weight made +0.291. Its stability profile is 56% on CONFIRMATION — a
coin flip. So the momentum rules are not simply capturing beta with extra
steps; ranking by past return does order the cross-section in the right
direction. That ordering is real **and it is not large enough to clear its own
null.** Both halves of that sentence are the finding.

**The stability profiles say exposure, not skill — the same lesson as #203.**
100% positive on CONFIRMATION reads as robustness until you notice #191b's
random draws are positive in ~95% of cases too. Sign-stability on a long-only
portfolio in a rising market measures how reliably it was invested. It is
reported because the registration requires it, and it must not be read as
support.

## Consequences

- **No promotion.** Nothing from ROTATION becomes a claim. `claims.md`
  unchanged — still zero supported edge claims.
- **No partial credit.** #187 clearing four of four clauses on DISCOVERY is
  recorded, not banked. "Single confirmation, no partial credit, no re-runs"
  was locked before the run.
- **No re-specification.** Not a longer lookback, not a different rebalance
  day, not top-3, not a per-rebalance placebo because it would have been
  easier to beat. Any of those is a new registration.
- **k stays 6.** #191b remains a control and was never counted as a
  hypothesis.
- **ALLOCATION #193–#196 is unaffected** and runs next as locked. Its
  placebo is `block_shuffle_placebo`, which this defect did not touch — but
  that instrument has now been put on notice: it must be checked against the
  property it claims to preserve before it is used for a verdict.

---

# ALLOCATION RESULT — #193–#196, run 2026-08-31

`research/run_allocation.py`, `research/allocation_verdicts.py`. Raw in
`research/allocation_results.json`, `research/allocation_verdicts.json`.

**VERDICT: #193 FAIL, #194 FAIL, #196 FAIL.** #195 is the constant control
and its clauses 2 and 3 are degenerate by construction (below). Nothing
passes, nothing promoted.

## The standing placebo check, applied first

ROTATION's defect created a standing rule: **a placebo pays what the strategy
pays and is constrained the way the strategy is constrained.**
`block_shuffle_placebo` was checked against it before a single draw was
scored, and it failed on a *different* axis from ROTATION's.

| window | | turnover | ratio | drag pp/yr | weight on **non-existent** assets |
|---|---|---|---|---|---|
| DISCOVERY | real rule | 0.0188 | — | — | 0.013% |
| | weight-matrix shuffle | 0.0333 | 1.77× | 0.423 | **15.414%** |
| | **scale shuffle (used)** | 0.0268 | 1.42× | 0.232 | **0.023%** |
| CONFIRMATION | real rule | 0.0186 | — | — | 0.000% |
| | weight-matrix shuffle | 0.0291 | 1.56× | 0.306 | 0.322% |
| | **scale shuffle (used)** | 0.0276 | 1.49× | 0.264 | **0.000%** |

**Two findings, and they are not the same size.**

**Material — universe fidelity.** Shuffling the whole weight matrix moves
the *cross-section* through time, so a late 21-day block landing on an early
date holds assets that had not listed yet. On DISCOVERY that is **15.4% of
gross weight** parked in assets with no price, against **0.013%** for the
real path. `portfolio_returns` fills missing returns with 0.0, so that weight
sits in a silent zero-return bucket — a drag the strategy never pays and
which appears nowhere in the output. **Repaired**, by the same logic as
ROTATION: shuffle the **scale path** and re-apply it to the time-correct
cross-section. An allocation rule's decision *is* the scale; the
cross-section is not its claim. That destroys exactly what #193/#194 assert —
that exposure was raised and lowered at the right moments — while leaving the
investable universe alone. Non-existent weight drops to 0.023% / 0.000%.

**Not material — turnover.** The residual inflation is 1.42–1.49×, which
*sounds* like ROTATION's problem and is not. This is a low-turnover strategy
(0.019/day), so the inflation costs the null **0.23–0.26 percentage points a
year**. ROTATION's 13.6× sat on a 0.116/day strategy and cost its null ~42
pp/yr. The ratio is the wrong unit; the drag is the right one. No further
repair — and because the residual handicaps the null slightly, every FAIL
below is conservative.

Six tests cover the repair, including an explicit reproduction of the
15%-of-weight defect and the property that a **constant** scale path shuffles
to itself.

## Matched-exposure benchmark — construction verified

| window | # | c | \|mean gross(bench) − mean gross(rule)\| |
|---|---|---|---|
| DISCOVERY | #193 | 0.4159 | **0.00e+00** |
| | #194 | 0.6830 | 1.11e-16 |
| | #196 | 1.4793 | 4.44e-16 |
| CONFIRMATION | #193 | 0.5114 | **0.00e+00** |
| | #194 | 0.8294 | 0.00e+00 |
| | #196 | 1.4491 | 4.44e-16 |

Exposure is matched to machine precision. `c` is computed from the rule's own
realised exposure; nothing was chosen by looking at returns. As a sanity
check the benchmark Sharpes come out ≈ #195's on both windows (+1.188–1.190
DISCOVERY, +0.419–0.421 CONFIRMATION), which is what constant rescaling
should do.

## Results — every registered clause

Clauses: **1** ann > 0 · **2** ann > block-shuffle p98.75 (k=4, 1,200 seeds)
· **3** Sharpe > matched-exposure Sharpe.

| # | rule | window | ann | Sharpe | plc p_adj | plc pct | match Sh | 1 | 2 | 3 |
|---|---|---|---|---|---|---|---|---|---|---|
| **#193** | vol target 30% | DISCOVERY | +0.388 | +1.087 | +0.633 | 30.6% | +1.188 | PASS | **FAIL** | **FAIL** |
| | | CONFIRMATION | +0.176 | +0.512 | +0.373 | 66.7% | +0.420 | PASS | **FAIL** | PASS |
| **#194** | vol target 50% | DISCOVERY | +0.635 | +1.080 | +1.014 | 27.8% | +1.189 | PASS | **FAIL** | **FAIL** |
| | | CONFIRMATION | +0.331 | +0.594 | +0.518 | 78.3% | +0.421 | PASS | **FAIL** | PASS |
| **#196** | INVERTED 30% | DISCOVERY | +1.632 | +1.179 | +1.847 | 63.1% | +1.188 | PASS | **FAIL** | **FAIL** |
| | | CONFIRMATION | +0.460 | +0.449 | +0.725 | 64.3% | +0.419 | PASS | **FAIL** | PASS |

**#195, constant 1.0× equal-weight-26:** DISCOVERY ann +1.101, Sharpe +1.190;
CONFIRMATION ann +0.291, Sharpe +0.421. Clause 1 PASS. **Clauses 2 and 3 are
degenerate by construction** — block-shuffling a constant scale returns the
same path, and its matched-exposure benchmark *is itself*. Neither is a test,
and neither is reported as a pass or a fail.

### Window-stability (50 starts, end pinned) — all four rules

| # | DISCOVERY | CONFIRMATION |
|---|---|---|
| #193 | 94% positive, −0.194…+0.555, med +0.425 | **100% positive**, +0.013…+0.350, med +0.204 |
| #194 | 94% positive, −0.145…+0.857, med +0.674 | **100% positive**, +0.064…+0.585, med +0.340 |
| #196 | 88% positive, −0.286…+1.980, med +1.676 | 96% positive, −0.017…+1.154, med +0.454 |
| #195 | 88% positive, −0.134…+1.284, med +1.142 | 98% positive, −0.022…+0.787, med +0.303 |

## What the numbers say

**Clause 2 fails everywhere, and on DISCOVERY it fails backwards.** The real
vol-targeting timing sits at the **30.6th and 27.8th percentile** of its own
shuffled exposure path — that is, roughly **70% of random reorderings of the
same exposure profile did better than the actual timing.** CONFIRMATION
recovers to the 66.7th and 78.3rd, still nowhere near 98.75. Whatever these
rules are doing, choosing *when* to be exposed is not it.

**Clause 3 is "the test", it splits by window, and the control kills the good
half.** On DISCOVERY every rule loses to matched exposure (#193 +1.087 vs
+1.188). On CONFIRMATION #193 and #194 win (+0.512 vs +0.420; +0.594 vs
+0.421) — and so does **#196, the inverted rule that levers UP into high
volatility** (+0.449 vs +0.419).

The registration wrote #196's job down in advance: *"if vol-targeting works,
its inverse should not."* Its inverse does. The margins differ — #194 +0.173,
#193 +0.092, #196 +0.030 — so the effect is not identical in both
directions, and #196 is the weakest of the three. But a clause that the
opposite prescription also clears cannot be read as evidence for the
prescription. On CONFIRMATION, *varying* exposure beat constant exposure
regardless of which way the signal pointed.

**#196 also has the highest raw return anywhere in the program: +1.632/yr on
DISCOVERY**, from levering up into volatility during 2020–21. It fails
clause 2 by the widest margin (+1.632 vs a placebo p_adj of +1.847). That is
the cleanest illustration in this whole document of why clause 1 was never
allowed to stand alone.

**The stability profiles again measure exposure.** 100% positive for #193/#194
on CONFIRMATION, and 88–98% for the constant control and the inverted control
too. Everything long in a rising market is sign-stable. Reported because the
registration requires it; not evidence.

## Consequences

- **No promotion.** Nothing from ALLOCATION becomes a claim. `claims.md`
  unchanged — still **zero supported edge claims**.
- **No partial credit.** #193 and #194 clearing clause 3 on CONFIRMATION is
  recorded, not banked. Locked before the run: single confirmation, no
  partial credit, no re-runs.
- **No re-specification.** Not a different vol window, not a different
  target, not a different cap, not clause 3 alone because it is "the test".
- **The standing placebo rule has now caught two defects in two programs**
  (`rank_permutation_placebo`, `block_shuffle_placebo`), in the same family:
  a null that differs from the strategy in more than the one thing it claims
  to isolate. Every future placebo is checked for turnover fidelity **and**
  universe fidelity before it is used for a verdict.

---

# CLOSE-OUT — THE ARCHITECTURAL SEARCH (#187–#203)

Closed 2026-08-31. Four programs, registered before any of them ran, all now
executed and reported.

**Six axes searched, zero survivors, and the closest calls died at registered
bars.**

> **Annotated 2026-08-31:** #187's DISCOVERY clause-2 pass, cited below as
> part of "the closest call", was measured against a null holding ~30% dead
> weight (#217). It is **uncitable as evidence**. The FAIL verdicts below are
> unchanged — they rest on CONFIRMATION.

## Verdicts

| program | # | axis searched | verdict |
|---|---|---|---|
| **ROTATION** | #187–#190 | *which* assets, *how many*, *over what horizon* | **FAIL** — all four momentum rules |
| | #191 / #191b / #192 | equal-weight, random-5, inverse-momentum controls | controls behaved; #192 FAIL |
| **ALLOCATION** | #193–#194 | *how much* exposure (vol targets 30% / 50%) | **FAIL** — both |
| | #195 / #196 | constant-1.0×, inverted-signal controls | #195 degenerate by construction; #196 **FAIL** |
| **ABLATION** | #197–#202 | *which components* carry the incumbent's behaviour | descriptive, no pass/fail — one rung load-bearing, **in the wrong direction** |
| **SQUEEZE-ONLY** | #203 | *what blend* of components (1.0 / 0.0) | **FAIL** |

The six axes, enumerated so the count is checkable: **(1)** which assets,
**(2)** how many of them, **(3)** over what lookback, **(4)** how much gross
exposure and when, **(5)** which components of the incumbent contribute, and
**(6)** what weighting those components should carry.

## The closest calls, and exactly where each died

Recording these precisely matters more than recording the failures, because
these are the ones a less disciplined version of this project would have
shipped.


> ### ⚠ ANNOTATION ADDED 2026-08-31 — #187's DISCOVERY clause-2 pass is UNCITABLE
>
> **NULL-CALIBRATION #217 measured the null this comparison was made against.
> On DISCOVERY it held ~31.97% of its gross weight in assets that did not
> exist** (the real rule: 0.000%; only **5 of 26** assets were alive for the
> whole window). That weight earned exactly zero through `fillna(0.0)`,
> dragging the null's centre to **+0.5378 — 50.12 pp/yr BELOW random-5
> selection (+1.0390)** and 56 pp below equal-weight.
>
> Universe fidelity was never checked here because **axis 2 did not exist
> when ROTATION ran** — it was introduced by ALLOCATION, one program later.
>
> **The bar was far too EASY. #187's DISCOVERY clause-2 PASS may not be cited
> as evidence of anything**, here or anywhere.
>
> **Verdicts are unchanged.** #187 is FAIL and always was, on CONFIRMATION,
> whose null held only 3.40% ineligible weight and is unaffected.
>
> **The counterfactual is UNMEASURABLE.** The corrected time-rotation null
> cannot be run on either ROTATION window: its locked offset range
> [24, T−24] months is **empty** at **T = 42.4 months (DISCOVERY)** and
> **T = 34.7 months (CONFIRMATION)**. The bound may not be relaxed to force a
> run (research rule 4), and rotating over the full series to lengthen T
> would pull rows out of the LOCKBOX. Recorded as a data fact: **crypto's
> windows are too short to carry a rotation-based null at all.**

- **#187 (top-5 by 30d momentum)** cleared **all four clauses on
  DISCOVERY** — including the two built to be hard: it beat equal-weight-26
  (+1.399 vs +1.101) and beat random-5's p95 (+1.399 vs +1.377, by 0.022).
  On CONFIRMATION it returned **+0.527 against a Bonferroni-adjusted placebo
  of +0.619**. Died on clause 2, second window.
- **#203 (squeeze-only)** produced the strongest `ex_best` in the project's
  history — **+0.234 on 4 of 4 positive folds** — and was positive at **100
  of 100** window starts across both windows. It sat at the **91.5th
  percentile** of its episode-matched placebo where the bar was p95. Died
  on the placebo, by roughly three and a half percentiles.
- **#194 (50% vol target)** cleared clause 3, *the* test, on CONFIRMATION
  (+0.594 vs matched-exposure +0.421). So did **#196, the inverted rule that
  levers UP into volatility** (+0.449 vs +0.419). The registration had
  written in advance: *"if vol-targeting works, its inverse should not."*
  Died on its own control.
- **#198 (drop Step 3)** was the only ABLATION rung to clear epsilon on both
  windows — and it cleared it by showing the indicator block **subtracts**
  (+0.175 / +0.119 from removing it). The one load-bearing component found
  in the whole search is load-bearing in the wrong direction. #203 then took
  that finding to a real bar and it failed.

Two patterns run through all four. **Everything positive was exposure, not
selection or timing** — random-5's median draw returned +104%/yr on
DISCOVERY, buying the *worst* five returned +75%/yr, and levering into
volatility returned +163%/yr. And **every promising number came from one
window**; not one survived both.

## PERMANENT METHODOLOGY — the two-axis placebo fidelity rule

This search found **two defects in two different placebos**, both of the same
family: *a null that differs from the strategy in more than the one thing it
claims to isolate.* Both would have made a bar easier than registered, and
both were caught before the draws they would have corrupted were scored.

| | defect | measured | effect if unfixed |
|---|---|---|---|
| `rank_permutation_placebo` | re-permuted every **row**, so weekly-held weights became fresh random names **daily** | turnover **1.566 vs 0.116 real — 13.6×** | null dragged to −0.38/yr by fabricated trading; **~42 pp/yr** of costs the strategy never pays |
| `block_shuffle_placebo` | shuffled the whole **weight matrix**, moving the cross-section through time | **15.4% of gross weight** on assets that had not listed, vs 0.013% real | that weight earns exactly 0 through `fillna(0.0)` — an invisible drag, absent from every output column |

**The rule, now standing for every placebo in this project:**

> **Before a placebo decides anything, verify it on two axes.**
>
> **1. Turnover fidelity.** Report the null's average turnover as a ratio to
> the real rule's, *and* convert the difference to **annualised return drag
> in percentage points** — `extra_turnover × cost_per_side × 365`. **The
> ratio alone is the wrong unit.** ALLOCATION's residual 1.42–1.49× looks
> like ROTATION's disaster and costs only **0.23–0.26 pp/yr**, because that
> strategy trades at 0.019/day; ROTATION's 13.6× sat on 0.116/day and cost
> ~42 pp/yr. Judge materiality in pp/yr, never in multiples.
>
> **2. Universe fidelity.** Report the fraction of gross weight the null
> places on assets that did not exist on that date, beside the real rule's
> figure. Missing prices become zero returns silently, so this defect is
> invisible in returns, turnover, and exposure alike — it has to be measured
> directly or it is not seen at all.
>
> **Repair by the same principle both times: the null pays what the strategy
> pays, and is constrained the way the strategy is constrained.** Destroy the
> one property under test and nothing else. Where a repair leaves a residual,
> quantify it and state which side it favours — both residuals here handicap
> the null, so every FAIL above is conservative.

A consequence worth stating plainly: **a placebo that is too weak does not
produce a cautious error, it produces a false positive.** Both defects would
have pushed toward promoting a rule. That is the direction defects tend to
run, because a null is the thing nobody checks when the answer looks good.

## Where this leaves the project

- **`claims.md` still holds zero supported edge claims.** Nothing from
  #187–#203 changes that, and nothing from them may be quoted as support.
- **No re-specification of anything above.** Not a different lookback,
  rebalance day, vol window, cap, epsilon, or placebo. Each is a new
  registration with a new number.
- **The incumbent is unchanged.** ABLATION was descriptive and promoted
  nothing; #203 was the promotion path and it failed.
- **SHADOW-EVAL is the only live research question.** It accrues forward,
  out-of-sample, on both the incumbent and squeeze-only arms, and may not be
  inspected before 30 pooled closed episodes.
- **FUNDING (#172–#186) remains registered and dormant**, awaiting its
  data-depth trigger (~2027-06-27). Nothing in this close-out touches it.

The honest summary of six months of architecture: the search was wide, the
bars were set first, and nothing cleared them. That is a result, and it is
the reason the bars were set first.

---

# Preliminary — NOT REGISTERED: funding quintiles vs forward returns

Run 2026-08-31, `research/funding_look.py`.

**This is a descriptive table and nothing else.** No placebo, no thresholds,
no pass rule, no verdict, nothing promotable. It is recorded so that looking
at the data is on the record, not so that anything can be built on it.

**It does not reduce the Bonferroni burden of #172–#186.** That program's
k is fixed by its registration and is untouched by anything below. Looking at
data before a registered program runs does not buy down its correction — if
anything it is the reason the correction exists.

**It does not move #172–#186's trigger.** The trigger is on *measured span*
(≥ 22 months for all three symbols, expected 2027-06-27) and this changes it
by zero days. The program stays REGISTERED and DORMANT.

## The lockbox halves the archive

The Kraken archive spans **2025-08-27 → 2026-08-30 (12.1 months)**. The
lockbox opens **2026-02-26**. Research rule 2 is absolute — "not for fitting,
not for plotting, not for a sanity check, not just to look" — so this uses
the **pre-lockbox half only: 2025-08-27 → 2026-02-25, 183 days**, about **36
days per quintile per ticker**.

Source: Kraken Futures hourly funding, daily mean, UTC days. Quintiles are
computed **within each ticker**.

## The table

**BTC** — 183 days

| quintile | n | funding lo | funding hi | fwd 1d | fwd 3d | fwd 7d |
|---|---|---|---|---|---|---|
| Q1 | 37 | −1.08164 | +0.19097 | +0.25% | −1.13% | −1.43% |
| Q2 | 36 | +0.19906 | +0.50691 | −0.42% | +0.04% | −0.41% |
| Q3 | 37 | +0.51039 | +0.82643 | −0.42% | −1.03% | −3.24% |
| Q4 | 36 | +0.83382 | +1.08608 | −0.18% | −0.68% | −2.26% |
| Q5 | 37 | +1.09073 | +2.13071 | −0.42% | −1.15% | −1.49% |
| **Q5 − Q1** | | | | **−0.68%** | **−0.02%** | **−0.07%** |

**ETH** — 183 days

| quintile | n | funding lo | funding hi | fwd 1d | fwd 3d | fwd 7d |
|---|---|---|---|---|---|---|
| Q1 | 37 | −0.13225 | −0.00098 | +0.29% | −1.45% | −2.01% |
| Q2 | 36 | −0.00096 | +0.00865 | −1.15% | −1.02% | −1.78% |
| Q3 | 37 | +0.00914 | +0.01630 | −0.44% | −1.72% | −5.52% |
| Q4 | 36 | +0.01634 | +0.02936 | −0.19% | −1.04% | −2.46% |
| Q5 | 37 | +0.02941 | +0.07436 | −0.37% | −0.81% | −2.14% |
| **Q5 − Q1** | | | | **−0.67%** | **+0.64%** | **−0.14%** |

**SOL** — 183 days

| quintile | n | funding lo | funding hi | fwd 1d | fwd 3d | fwd 7d |
|---|---|---|---|---|---|---|
| Q1 | 37 | −0.01824 | −0.00060 | −1.26% | −2.87% | −4.97% |
| Q2 | 36 | −0.00059 | +0.00008 | −0.50% | −2.10% | −4.14% |
| Q3 | 37 | +0.00009 | +0.00077 | +0.91% | +0.02% | −0.64% |
| Q4 | 36 | +0.00077 | +0.00141 | −0.42% | −0.85% | −2.89% |
| Q5 | 37 | +0.00143 | +0.00450 | −0.59% | −0.88% | −2.94% |
| **Q5 − Q1** | | | | **+0.67%** | **+1.99%** | **+2.03%** |

Median daily funding: BTC +0.672871, ETH +0.011639, SOL +0.000425.

## Two things about the table that are not findings

**The levels are not comparable across tickers.** Kraken's `funding_rate` is
an absolute rate, not normalised, which is why BTC's median is +0.67 and
SOL's is +0.0004. Quintiles are within-ticker ranks, so this does not affect
any ordering — but the `funding lo/hi` columns must not be read across rows
of different tables.

**The quintile assignment is sensitive to which rate column is used, and
that is a specification gap in #172–#186.** The file also carries
`relative_funding_rate`. Rank correlation between the two is high (Spearman
0.982–0.990) but **only 78.1% / 86.9% / 80.3% of days (BTC/ETH/SOL) land in
the same quintile**. One fifth of the sample moves.

`#172` is written as "the trailing 30-day percentile rank of daily-mean
funding" and **does not say which column that is**. That is a genuine gap,
found here before the program has run and before any result exists. It is
recorded, not fixed: **#172–#186 is locked and this session does not amend
it.** The trigger-date session must pin the column as its first act, and it
must do so on documented grounds rather than by trying both.

## What may be concluded

Nothing. At ~36 observations per cell with no null distribution, no number
above is distinguishable from noise by anything computed here, and no
ordering in it may be called a finding — including SOL's monotone-looking
Q5 − Q1 spread, which is the sort of pattern that appears readily in 36-day
buckets and is exactly what the registered program's placebo exists to test.

The direction of the whole table is also worth noting only as context: most
cells are negative at every horizon for all three tickers, because the
pre-lockbox half of this archive was a falling market. A quintile table over
a downtrend measures the downtrend first.

---

# PRE-REGISTRATION — EQUITIES PROGRAM (#204–#216)

> **LOCKED 2026-08-31**, approved with three rulings, all incorporated:
> numbering as drafted; the 12-month TS block with its derivation stated;
> and the TS-MOM caveat retained with an expiry clause. A third
> placebo-fidelity axis (cash-eligible-month count) was added on approval.
> Research rule 4 now applies to every constant below: no parameter,
> threshold, control or pass condition may change on the basis of a result.
>
> The data freeze predates this lock and contains no scored hypothesis.

## Why this program exists

**203 registered hypothesis numbers, 15 of them dormant, zero surviving edge
claims.** `docs/claims.md` holds no supported edge claim of any kind. The
architectural search (#187–#203) closed with six axes searched and no
survivors.

That result has two readings and the project cannot currently tell them
apart:

1. **The crypto price data contains no edge the ladder was aimed at.**
2. **The ladder cannot detect an edge that is there.**

Every registered bar, every placebo, every two-window confirmation is an
*instrument*, and an instrument that has only ever returned zero has not been
calibrated. **This program points it at a positive control.**

Cross-sectional and time-series momentum in equities are among the most
documented anomalies in the finance literature, replicated across decades,
markets and asset classes. They are the closest thing available to a known
signal.

- **If the ladder detects them here, the crypto zeros become informative** —
  the instrument works, and its silence on crypto is evidence about crypto.
- **If the ladder cannot detect them here, that is a finding about the
  ladder**, and every prior zero in this project is weakened accordingly.

Either outcome is worth more than another crypto rule. **This is not a search
for something to trade.**

**Isolation.** This program touches nothing in the crypto model: not
`pipeline.py`, `signal_engines.py`, `live_tools.py`, the workflows, the live
path, or any file under `data/` other than the new `data/equities/`. Results
go under `research/`. The crypto lockbox is unrelated to and unaffected by
this program's lockbox.

---

## DATA

### Adjusted close, and what that is worth — measured, not asserted

Export uses `yfinance` with **`auto_adjust=True`** (splits **and**
dividends). Raw close is **disqualifying** for an equities momentum study:
dividends are a material fraction of equity total return, so ranking on raw
close systematically penalises high-yield holdings for paying out — an
artefact with nothing to do with momentum.

Measured at export across the 21 ETFs' full histories:

| | adjusted TR | raw TR | difference |
|---|---|---|---|
| **TLT** | +132.2% | **+1.7%** | **+130.5 pp** |
| **IEF** | +130.5% | +13.6% | +116.9 pp |
| **SPY** | +3090.6% | +1651.0% | +1439.6 pp |
| **XLU** | +637.3% | +186.5% | +450.8 pp |
| **EWU** | +514.3% | +96.2% | +418.1 pp |
| **GLD** | +821.3% | +821.3% | **+0.0 pp** |
| **median across 21** | | | **+331.7 pp** |

TLT is the argument in one line: on raw close a 24-year Treasury ETF returned
**+1.7%**, because essentially its entire return is coupons. Ranking it
against equities on raw close would place it permanently last for reasons
that are pure accounting. GLD's exact **0.0 pp** confirms the adjustment is
not a blanket transform — it moves only what actually distributes.

### ETFs only — and the reason is uncorrectable bias, not convenience

Single stocks via free data carry **survivorship bias that inflates
momentum**: Yahoo serves the tickers that still exist, so companies that
delisted are simply absent. A momentum rule scored on survivors measures
"past winners kept winning" on a sample **selected for not having failed** —
precisely the direction that manufactures a positive momentum result.

**This cannot be repaired after the fact.** It needs a point-in-time
constituent database, which this project does not have. ETFs persist and are
used instead. They carry a smaller version of the same bias (funds do close,
and all 21 here survive to the freeze); that residual is disclosed rather
than eliminated, and the alternative is not a cleaner sample but an
uncorrectable one.

### Universe — 21 ETFs, fixed, no additions

Inception dates are **from the actual downloaded data**, not from memory.
Freeze date **2026-08-28**.

**9 sector SPDRs** (all inception 1998-12-22, 6,963 rows, 27.68y):
XLB, XLE, XLF, XLI, XLK, XLP, XLU, XLV, XLY

**12 broad / regional / asset-class:**

| ETF | first bar | rows | years |
|---|---|---|---|
| SPY | 1993-01-29 | 8,453 | 33.58 |
| EWJ | 1996-03-18 | 7,662 | 30.44 |
| EWG | 1996-03-18 | 7,662 | 30.44 |
| EWU | 1996-03-18 | 7,662 | 30.44 |
| QQQ | 1999-03-10 | 6,911 | 27.47 |
| IWM | 2000-05-26 | 6,603 | 26.26 |
| EFA | 2001-08-27 | 6,288 | 25.00 |
| TLT | 2002-07-30 | 6,060 | 24.08 |
| IEF | 2002-07-30 | 6,060 | 24.08 |
| EEM | 2003-04-14 | 5,882 | 23.37 |
| GLD | 2004-11-18 | 5,478 | 21.77 |
| DBC | 2006-02-06 | 5,173 | 20.56 |

All 21 requested, all 21 exported, none failed. Frozen to
`data/equities/{TICKER}.csv.gz` with `data/equities/MANIFEST_equities.json`
carrying per-ETF first/last date, row count, sha256, and both total-return
figures.

### Eligibility — pinned NOW, before any rule runs

**This is the ROTATION lesson applied in advance.** ROTATION discovered
mid-program that only 6 of 26 crypto assets existed at its window's start and
had to pin an eligibility rule as a disclosed specification completion. Here
it is fixed first:

> **An ETF enters the cross-section the month AFTER its first full month of
> data.** A rule runs at a rebalance only when **≥ 12 ETFs are eligible**;
> below that the rule holds cash and the rebalance is recorded as skipped.
> Executed and skipped counts are reported.

Resulting eligibility:

| eligible from | ETFs | count |
|---|---|---|
| 1993-03-01 | SPY | 1 |
| 1996-05-01 | EWJ, EWG, EWU | 4 |
| **1999-02-01** | **the 9 sector SPDRs** | **13** ← program starts |
| 1999-05-01 | QQQ | 14 |
| 2000-07-01 | IWM | 15 |
| 2001-10-01 | EFA | 16 |
| 2002-09-01 | TLT, IEF | 18 |
| 2003-06-01 | EEM | 19 |
| 2005-01-01 | GLD | 20 |
| 2006-04-01 | DBC | 21 |

Date-eligibility alone first reaches 12 in **1999-02**. That is not the
program start, because **an ETF that is date-eligible may still have no
signal**: a 12-1 momentum figure needs 13 months of month-end history, so the
sector SPDRs cannot be ranked until 2000-01 even though they are eligible
from 1999-02.

> **Effective eligibility at a rebalance = past `eligible_from` AND having a
> defined signal for the rule being scored.** The ≥12 count is taken over
> that set.

Measured on the freeze: ≥12 ETFs carry a defined **6-1** signal from
**1999-07**, and a defined **12-1** signal from **2000-01** (n = 13).

> **Program start = 2000-01, governed by the LONGEST formation horizon in the
> program (12-1), applied to all six rules.** The 6-1 rules could start six
> months earlier and deliberately do not. Rules scored on different spans are
> not comparable to each other or to shared controls, and #210/#215 have to
> be one benchmark for all of them. Six months of extra history is worth less
> than a clean comparison.

A top-5 rule choosing from 13 candidates is making a real selection; that is
the property the threshold is for.

### Windows — anchored on the freeze

Lockbox is the last 6 months of the freeze; the remainder splits at the
project's standard `DISCOVERY_FRAC = 0.55`.

| window | span | length | monthly rebalances |
|---|---|---|---|
| **DISCOVERY** | 2000-01-01 → 2014-05-22 | 14.39y | 173 |
| **CONFIRMATION** | 2014-05-22 → 2026-02-28 | 11.77y | 142 |
| **LOCKBOX** | 2026-02-28 → 2026-08-28 | 0.50y | **SEALED — never read** |

**26 years, 315 rebalances, two windows that each contain multiple full
market cycles.** DISCOVERY spans the dot-com bust and the GFC; CONFIRMATION
spans 2014–2026. This is far deeper than anything the crypto programs had
(6.4 years, 30 episodes at best), which is exactly why it can calibrate the
instrument.

---

## STRUCTURE

| element | value |
|---|---|
| rebalance | **monthly**, first trading day of each month |
| weighting | equal-weight within the selection |
| costs | **5 bps per side** on traded notional |
| scoring | `research/portfolio_harness.py` (equivalence-gated to machine precision) |
| folds | 4 equal-duration splits per window |
| seeds | **1,200** |
| k (Bonferroni) | **6** — the six hypotheses; controls are not counted |

**Monthly, not weekly, and the reason is stated so it cannot be revisited
later.** Monthly rebalancing with monthly-horizon signals is the convention
the entire momentum literature is written in. Weekly rebalancing is a habit
imported from this project's crypto work, where it was chosen for crypto's
24/7 microstructure. Carrying it over would test a construction the
literature never validated and would make a failure uninterpretable — it
could mean "the anomaly is absent" or "you rebalanced four times too often
and paid for it." A positive control must be run in its documented form.

### Signal construction — the canonical skip-a-month form

At the rebalance on the first trading day of month **M**:

- **12-1 momentum** = total return from the close of month **M−13** to the
  close of month **M−2** (11 months, skipping month M−1 entirely).
- **6-1 momentum** = total return from the close of month **M−7** to the
  close of month **M−2** (5 months, skipping month M−1).

Skipping the most recent month is the canonical construction: it avoids the
well-documented short-horizon reversal that otherwise contaminates the
signal. It is **not** a lookahead guard — no lookahead exists either way,
since every price used precedes the holding period — it is the literature's
definition, adopted so the test is of the published anomaly.

---

## THE SIX HYPOTHESES

### Cross-sectional momentum — 4 rules

| # | rule |
|---|---|
| **#204** | rank eligible by **12-1**, hold **top-3** equal-weight |
| **#205** | rank eligible by **12-1**, hold **top-5** equal-weight |
| **#206** | rank eligible by **6-1**, hold **top-3** equal-weight |
| **#207** | rank eligible by **6-1**, hold **top-5** equal-weight |

### Time-series momentum — 2 rules

| # | rule |
|---|---|
| **#208** | each eligible ETF held long if its **12-1 > 0**, else **that slot sits in cash at zero return**; equal-weight 1/n_eligible across the eligible set, so gross exposure floats between 0 and 1 |
| **#209** | **SPY-only absolute momentum**: long SPY if its 12-1 > 0, else cash |

#208 does **not** redistribute the cash of a negative-momentum slot to the
positive ones. That is the standard TS-MOM construction and is what makes it
a *timing* rule rather than a disguised cross-sectional one.

---

## CONTROLS — all of them, reported beside the rules

| # | control | purpose |
|---|---|---|
| **#210** | equal-weight the eligible universe, monthly | did selection do anything at all |
| **#211** | **bottom-3** by 12-1 | momentum's mirror |
| **#212** | **bottom-5** by 12-1 | " |
| **#213** | **bottom-3** by 6-1 | " |
| **#214** | **bottom-5** by 6-1 | " |
| **#215** | **random-N distribution**, N ∈ {3,5}, drawn uniformly from the eligible set at each rebalance, **1,200 draws**, reported as a distribution | matched null for a selection rule |
| **#216** | **inverted TS**: long when 12-1 **< 0** | if TS momentum works, its inverse should not |

**Controls are not hypotheses and are not counted in k**, which stays at
**6**. They cannot pass or fail. #215 is drawn from the **same eligible set**
the rule it nulls uses, per the ROTATION lesson on matched controls.

If a bottom-N control wins while its top-N rule also wins, the result is
market exposure rather than selection, and both are reported as such.

---

## PLACEBO FIDELITY — the two-axis check, before any draw is scored

The standing rule from the architectural close-out applies in full. Two
placebo defects were found in two programs, both of the family *a null that
differs from the strategy in more than the one thing it claims to isolate*,
and both would have made a bar easier — i.e. both pushed toward a **false
positive**.

**Generators:**

- **Cross-sectional rules (#204–#207)** → `rank_permutation_fixed_placebo`
  (one fixed relabelling of the universe for the whole window). Destroys
  *which ETF*, preserves the weight path exactly.
- **Time-series rules (#208, #209)** → **block-shuffle of the SIGNAL path**,
  re-applied to the time-correct cross-section — never a shuffle of the whole
  weight matrix. Destroys *when* exposure was on.

**Block = 12 months, and the derivation is fixed here.** The block must be
**long relative to the 12-1 formation horizon**, so that shuffling breaks
**timing** without destroying **texture**. A momentum signal built from an
11-month formation window is autocorrelated over roughly that horizon; a
block materially shorter than it would chop through the middle of the
signal's own persistence, producing a null whose exposure path is choppier
than any real rule could generate — the ALLOCATION seam problem, in a form
that would attack the very property TS-MOM claims. At 12 months each block
carries at least one full formation horizon intact, so within a block the
signal keeps its shape and only the block's *placement in history* is
destroyed. That is exactly the claim under test: not "does exposure ramp
smoothly" but "did it ramp at the right time."

**All three axes must pass, before a single draw is scored, and the measured
figures are reported in the results:**

1. **Turnover fidelity** — the null's average turnover as a **ratio** to the
   real rule's, **and converted to annualised return drag in percentage
   points** (`extra_daily_turnover × cost_per_side × 252` trading days).
   **The ratio alone is the wrong unit** — ALLOCATION's 1.42× cost 0.23 pp/yr
   while ROTATION's 13.6× cost ~42 pp/yr. Materiality is judged in pp/yr.
2. **Universe / eligibility fidelity** — the fraction of gross weight the
   null places on ETFs that were **not yet eligible** on that date, reported
   beside the real rule's figure. Missing prices become zero returns
   silently, so this defect is invisible in returns, turnover and exposure
   alike and must be measured directly.
3. **Cash-eligible-month fidelity — TS shuffle only (#208, #209, #216).** A
   time-series rule's defining behaviour is *how often it is out of the
   market*. A null that is in cash a different amount of the time is not
   testing timing, it is testing a different exposure budget. So the null's
   count of **cash asset-months** — asset-months in which the rule holds
   nothing — must match the real rule's within a **relative tolerance of
   ±2%**, reported as a measured figure beside the other two axes.

   Block shuffling permutes whole blocks of the signal path, so this count is
   preserved *exactly* except where the series length is not a whole multiple
   of the block and the final partial block is truncated. ±2% is set to
   absorb that truncation and nothing else; a larger deviation means the
   generator is doing something it was not asked to do, and it is repaired
   before any draw.

If either check fails materially, the generator is **repaired before any
draw**, on the same principle both previous repairs used — *the null pays
what the strategy pays and is constrained the way the strategy is
constrained* — and the repair is documented in the results with its measured
before/after. Any residual is quantified with a statement of which side it
favours.

---

## PASS RULES

Per rule, on **BOTH** windows, all required:

1. **Net annualised return > 0**, AND
2. **Above the rank-permutation / block-shuffle placebo's
   Bonferroni-adjusted percentile**: α = 0.05/6 = 0.008333, the **99.1667th
   percentile**, from 1,200 seeds (p95 reported alongside from the same
   draws), AND
3. **Above #210 (equal-weight eligible universe)** on net annualised return,
   AND
4. **Cross-sectional rules (#204–#207) only: above #215 random-N's p95**, for
   the matching N, on both windows.

**No partial credit. Single confirmation. No re-runs.**

**One thing recorded now so it cannot be introduced afterwards:** TS-MOM's
claim in the literature is primarily about **drawdown and risk-adjusted
return**, not raw return, so clause 3 is a demanding bar for #208/#209 in a
26-year period containing two large bull markets. This is stated in advance
so that a clause-3 failure for the TS rules is read for what it is — a
statement about *return* — and it **does not soften the verdict, which is
FAIL, and may not be used to promote anything.** Sharpe and max drawdown are
reported for every rule as description.

**The caveat expires, and the expiry is fixed now.** If #208/#209 fail **all
clauses**, including the descriptive risk-adjusted read — i.e. they also fail
to beat #210's Sharpe and fail to improve max drawdown — then the caveat
**expires and may not be cited**, in this program or any later one. A note
that exists to prevent a narrow failure being over-read has no standing once
the failure is broad. It cannot become a permanent excuse attached to
time-series momentum.

---

## INTERPRETATION MATRIX — worded now, so no result can bend it

| DISCOVERY | CONFIRMATION | reading |
|---|---|---|
| **PASS** | **PASS** | **Instrument validated.** The ladder detects a known anomaly at this granularity and under these costs. The crypto zeros become **informative**: the instrument works, and its silence on crypto is evidence about crypto rather than about the method. |
| **PASS** | **FAIL** | **Edge verdict: FAIL.** No partial credit — the rule does not pass. See the pre-worded descriptive note below, which is a reading about the *instrument* and never a claim about an edge. |
| **FAIL** | **PASS** | **Edge verdict: FAIL.** Recorded as-is. A signal absent in the earlier era and present in the later one is not the published anomaly's shape and gets no special narrative. |
| **FAIL** | **FAIL** | **Two readings, both stated, neither chosen.** (a) The effect is too weak at **ETF granularity** and **these costs** to clear a Bonferroni-adjusted two-window bar. (b) **The ladder is insensitive** — the bars are set where a real, documented anomaly cannot pass them. This program does not adjudicate between them, and no later program may quietly assume either. |

### Pre-worded descriptive note for a DISCOVERY-only pass

*Written now, before any result exists, so it cannot be composed to fit one.*

> Detection in the early era only is **consistent with the published decay of
> ETF-level momentum since the 2000s** — the anomaly's dilution after
> widespread publication and the growth of systematic products is documented
> in the literature. DISCOVERY here ends 2013-12-22, which straddles that
> transition.
>
> **This is a reading about the instrument, not a claim about an edge.** It
> says the ladder demonstrably *can* detect the anomaly where the anomaly was
> strongest, which is exactly the calibration this program was built to
> obtain. It says nothing tradeable, it does not soften the FAIL verdict, and
> it may not be cited as partial support for anything. A decayed anomaly and
> an over-fitted window produce the same table; this note does not
> distinguish them and does not pretend to.

---

## BUDGET AND CLOSURE

- **This list is the whole program.** Six hypotheses, seven controls, two
  lookbacks, two selection sizes, one rebalance frequency, one cost
  assumption.
- **No additions after results exist.** Not a third lookback, not top-10, not
  a different skip, not weekly rebalancing, not a volatility overlay, not
  single stocks. Any of those is a new registration with a new number and its
  own correction.
- **Failure closes equity momentum at this granularity for this project.**
  Not "try again with different parameters" — closed, with the two readings
  above recorded and neither chosen.
- **Nothing here is ever promoted to the live path.** There is no equities
  live path, none is proposed, and a pass would change the *interpretation of
  the crypto record*, not the traded system.

**Reported whatever the outcome:** for every rule and control on both
windows — net annualised return, Sharpe, max drawdown, average turnover,
average gross exposure, executed/skipped rebalances, placebo p95 and adjusted
percentile, the observed percentile within the placebo distribution, both
fidelity ratios, and a **50-start window-stability profile for every rule**
(not only those passing something — selecting which results get an error bar
on the basis of their result is the move this project forbids).

Negatives are reported with the same detail as positives (research rule 5).

---

# EQUITIES RESULT — #204–#216, run 2026-08-31

`research/run_equities.py`, `research/equities_verdicts.py`. Raw in
`research/equities_results.json`, `research/equities_verdicts.json`.

**VERDICT: #204 FAIL, #205 FAIL, #206 FAIL, #207 FAIL, #208 FAIL, #209 FAIL.**
Nothing passes. This is the **fail/fail** cell of the registered
interpretation matrix.

Windows as locked: DISCOVERY 2000-01-03 → 2014-05-22 (3,619 trading days),
CONFIRMATION 2014-05-23 → 2026-02-27 (2,959), LOCKBOX sealed and unread.
Fast scoring path verified against `portfolio_returns` on each window's own
weight paths: max abs err **4.44e-16** both windows.

## Placebo fidelity — two failures caught before any draw, one repaired

**The check did its job on the first program where it was mandatory.**

**Failure 1 — CS universe fidelity, DISCOVERY (material, repaired).** The
registered generator `rank_permutation_fixed_placebo` permutes *output
weights*. On DISCOVERY it placed **7.06–7.86% of gross weight in ETFs that
were not yet eligible** (real rule: 0.000%), because a single fixed
relabelling cannot respect a universe growing from 13 ETFs to 21. That weight
earns exactly zero through `fillna(0.0)` — the ALLOCATION defect in a new
costume, and confined to DISCOVERY (CONFIRMATION measured 0.000%, the
universe being complete), so it would have made **exactly one window's bar
easier**.

**Repaired** under the clause the registration wrote for this: permute the
**decision input** — one fixed relabelling of the signal columns per seed —
and run the real selection rule, so eligibility is enforced by the same code
the rule uses.

| | before (weight-permutation) | after (signal-permutation) |
|---|---|---|
| ineligible weight, DISCOVERY | **7.06 – 7.86%** | **0.000%** |
| turnover ratio, DISCOVERY | 1.00× | 0.85 – 0.87× (drag **−0.05 to −0.08 pp/yr**) |
| turnover ratio, CONFIRMATION | 1.00× | 1.00× (drag ≤ +0.002 pp/yr) |

The residual turnover gap is *negative* — the repaired null trades slightly
less than the rule — so the bar is marginally **harder**, and every FAIL
below is conservative on that axis.

**Failure 2 — TS cash-eligible-month fidelity, #208 on DISCOVERY (not
repairable, declared UNMEASURABLE).** Registered tolerance ±2%; measured
**1,087 → 1,216.9, deviation 11.95%**. Cause: block-shuffling moves a
12-month signal block from a late period (21 eligible) to an early one (13
eligible), and because eligibility and signal sign are both time-dependent on
a growing universe, the count of stand-aside months shifts. No shuffle of a
persistent series can preserve that on a window whose investable universe
grows 62%.

Per the project's standing `ex_best` convention, **clause 2 for #208 on
DISCOVERY is reported UNMEASURABLE — not a pass, not a fail.** It is **not
decision-relevant**: #208 fails clause 3 on *both* windows, so its verdict is
FAIL on evidence that does not touch the unmeasurable cell.

All other cells passed all three axes. #209 passed cash fidelity at **0.00%
deviation on both windows**; #208 passed at 0.00% on CONFIRMATION.

*Measurement correction, disclosed:* the first implementation counted cash
over **all** asset-months including ETFs that had not launched. The registered
axis is the **cash-ELIGIBLE**-month count, so it was masked to eligible cells
before any verdict. Ineligible cells are trivially zero for rule and null
alike and vary with the growing universe rather than with anything either
decides.

## Results — every registered clause

| # | rule | window | ann | Sharpe | maxDD | plc p_adj | plc pct | #210 | r-N p95 | 1 / 2 / 3 / 4 |
|---|---|---|---|---|---|---|---|---|---|---|
| **#204** | CS top-3 12-1 | DISC | +0.0726 | +0.356 | −0.443 | +0.1273 | 20.7% | +0.0709 | +0.0972 | P **F** P **F** |
| | | CONF | +0.1264 | +0.700 | −0.314 | +0.1484 | **89.9%** | +0.1036 | +0.1264 | P **F** P **F** |
| **#205** | CS top-5 12-1 | DISC | +0.0821 | +0.449 | −0.444 | +0.1147 | 35.2% | +0.0709 | +0.0870 | P **F** P **F** |
| | | CONF | +0.1234 | +0.819 | −0.223 | +0.1350 | **95.0%** | +0.1036 | +0.1166 | P **F** P P |
| **#206** | CS top-3 6-1 | DISC | +0.0979 | +0.493 | −0.457 | +0.1231 | 83.1% | +0.0709 | +0.0972 | P **F** P P |
| | | CONF | +0.1092 | +0.593 | −0.334 | +0.1430 | 69.8% | +0.1036 | +0.1264 | P **F** P **F** |
| **#207** | CS top-5 6-1 | DISC | +0.0918 | +0.504 | −0.410 | +0.1114 | 77.6% | +0.0709 | +0.0870 | P **F** P P |
| | | CONF | +0.0960 | +0.579 | −0.335 | +0.1330 | 38.0% | +0.1036 | +0.1166 | P **F** **F** **F** |
| **#208** | TS-MOM 12-1 | DISC | +0.0603 | +0.569 | −0.220 | +0.0922 | 74.0% | +0.0709 | — | P **UNMEAS** **F** |
| | | CONF | +0.0664 | +0.642 | −0.266 | +0.1045 | 13.7% | +0.1036 | — | P **F** **F** |
| **#209** | SPY abs mom | DISC | +0.0652 | +0.494 | −0.245 | +0.0933 | 86.8% | +0.0709 | — | P **F** **F** |
| | | CONF | +0.1214 | +0.752 | −0.337 | +0.1561 | 35.1% | +0.1036 | — | P **F** P |

**Clause 2 fails in all twelve measurable cells.** No rule reaches the
Bonferroni-adjusted 99.1667th percentile of its own null on either window.

### Controls

| window | #210 eq-wt | #211 bot-3 12-1 | #212 bot-5 12-1 | #213 bot-3 6-1 | #214 bot-5 6-1 | #216 inverted TS |
|---|---|---|---|---|---|---|
| DISCOVERY | +0.0709 | +0.0892 | +0.0731 | +0.0798 | +0.0642 | **+0.0096** |
| CONFIRMATION | +0.1036 | +0.0481 | +0.0639 | +0.0765 | +0.0819 | **+0.0357** |

**#215 random-N** (1,200 draws): DISCOVERY random-3 p05/p50/p95
+0.0265/+0.0616/+0.0972, random-5 +0.0373/+0.0622/+0.0870. CONFIRMATION
random-3 +0.0601/+0.0936/+0.1264, random-5 +0.0716/+0.0940/+0.1166.

### Window-stability (50 starts, end pinned) — every rule clearing any clause

All six, all 50 starts defined, **100% positive in all twelve profiles.**
DISCOVERY medians +0.054 to +0.096; CONFIRMATION medians +0.067 to +0.110.
As in every prior program, sign-stability on a long-only portfolio in a
rising market measures how reliably it was invested. Reported because the
registration requires it; not evidence.

## What the numbers say

**The anomaly is visible. It does not clear the bar.**

Momentum's *direction* shows up clearly in the descriptive contrasts:

- **Rule beats its own mirror in 9 of 10 comparisons.** On CONFIRMATION,
  top-3 12-1 returns +0.1264 against bottom-3's +0.0481 — a **+7.8 pp/yr**
  spread. The single exception is top-3 12-1 on DISCOVERY (−1.7 pp).
- **TS-MOM beats inverted TS on both windows**, +0.0603 vs +0.0096 and
  +0.0664 vs +0.0357. The inverted control does what the registration said it
  should: it loses.
- **TS-MOM shows its documented risk profile** — max drawdown −0.220 against
  equal-weight's −0.460 on DISCOVERY, at two-thirds the gross exposure.
- **CS rules beat equal-weight in 7 of 8 rule-windows** (clause 3).

And every one of them fails clause 2. The gap between "clearly ordered" and
"clears a Bonferroni-adjusted permutation bar" is the whole result.

### A measured reason clause 2 is so hard here — evidence on registered reading (b)

The null's *centre*, not just its tail, is informative:

| window | CS placebo mean | #210 equal-weight | #215 random-3 p50 |
|---|---|---|---|
| DISCOVERY | **+0.0864** | +0.0709 | +0.0616 |
| CONFIRMATION | **+0.1001** | +0.1036 | +0.0936 |

**If permuting the labels had destroyed selection, the placebo's centre
should sit near random-N. It sits ~2.5 pp/yr above it on DISCOVERY.** The
reason is structural: 21 equity ETFs are highly correlated, so a rule ranking
a *relabelled* signal still lands on genuinely high-momentum assets a large
fraction of the time. **The null inherits part of the effect it exists to
destroy**, which makes clause 2 a harder bar than its construction intends.

This is measured evidence bearing on the registered fail/fail reading **(b)
the ladder is insensitive** — it is not a new third reading, and it does not
rescue anything. It also **applies to the crypto programs**, whose 26 assets
are at least as correlated: the same contamination was present in ROTATION's
clause 2 and was never measured there. It does not change a single crypto
verdict — nothing passed under either reading — but it does mean the crypto
zeros carry **less** weight as evidence about crypto than they appeared to.
That is the opposite of the comfortable conclusion, and it is what this
program was built to find out.

### The era pattern, recorded without a narrative

CS momentum is at the **20.7th and 35.2nd** placebo percentile on DISCOVERY
(2000–2014) and the **89.9th and 95.0th** on CONFIRMATION (2014–2026). It is
*stronger in the later era*.

That is the reverse of the published post-2000s decay, and the registration's
pre-worded decay note **does not apply** — that note was written for a
DISCOVERY-only pass and this is not one. Per the matrix's own instruction for
a later-era signal, it is **recorded as-is and gets no special narrative.**
No explanation is offered here, and none may be attached later without a new
registration.

### TS-MOM caveat — retained, by the registered expiry test

The caveat expires only if #208/#209 fail the descriptive risk-adjusted read
as well. They do not:

| | Sharpe vs #210 | max drawdown vs #210 |
|---|---|---|
| #208 DISCOVERY | +0.569 vs +0.389 — **beats** | −0.220 vs −0.460 — **better** |
| #208 CONFIRMATION | +0.642 vs +0.754 — loses | −0.266 vs −0.297 — **better** |
| #209 DISCOVERY | +0.494 vs +0.389 — **beats** | −0.245 vs −0.460 — **better** |
| #209 CONFIRMATION | +0.752 vs +0.754 — loses | −0.337 vs −0.297 — worse |

**Caveat RETAINED for both.** The failure is narrow — on *return* — exactly
as the registration anticipated, and TS-MOM's documented drawdown property is
present in three of four cells. This retains a caveat; it promotes nothing
and changes no verdict.

## Interpretation — the registered fail/fail cell, both readings, neither chosen

> **(a)** The effect is too weak at **ETF granularity** and **these costs** to
> clear a Bonferroni-adjusted two-window bar.
>
> **(b)** **The ladder is insensitive** — the bars are set where a real,
> documented anomaly cannot pass them.

**This program does not adjudicate between them, and no later program may
quietly assume either.** The null-contamination measurement above is evidence
bearing on (b); it is not a decision between them, because (a) remains fully
consistent with everything measured — the rules' raw edge over equal-weight
is 1–3 pp/yr before the null is even considered, which is thin enough that
(a) needs no help to be true.

**What this does settle:** the instrument is **not** validated. The original
question — "do the ~200 crypto zeros mean crypto has no edge, or that the
ladder can't see one?" — is **not answered in the direction that would have
made the crypto record stronger.** The ladder failed to certify the most
replicated anomaly in the equities literature, on 26 years of data, in an
asset class where the effect is descriptively visible in this very table.

## Closure

- **The program is closed.** This list was the whole program. Equity momentum
  at this granularity is closed for this project.
- **No additions.** Not a third lookback, not top-10, not a different skip,
  not weekly rebalancing, not single stocks, not a looser placebo because
  this one turned out to be contaminated. Any of those is a new registration
  with a new number and its own correction.
- **Nothing promoted.** There is no equities live path and none is proposed.
  `docs/claims.md` is unchanged and still holds **zero supported edge
  claims**.
- **The crypto record stands as written**, with one addition: the
  null-contamination finding is recorded against it, and any future citation
  of the crypto zeros must carry it.

---

# PRE-REGISTRATION — NULL-CALIBRATION PROGRAM (#217–#219)

> **REGISTERED 2026-08-31, before any number below was produced.** Research
> rule 4 applies to every constant here.
>
> **THIS IS A METHODS PROGRAM. IT MAKES NO EDGE CLAIM AND CANNOT.** It has no
> pass rule, promotes nothing, and cannot move a single prior verdict. Its
> output is a **correction to the instrument** and a calibration fact for
> every future program to register from the start.

## Motivation — the bar was contaminated upward, and by how much is unmeasured

EQUITIES #204–#216 measured something the crypto programs never checked. On a
**correlated universe, the rank-permutation null inherits part of the very
selection effect it exists to destroy**, because a rule ranking a *relabelled*
signal still lands on genuinely high-momentum assets a large fraction of the
time.

Measured on DISCOVERY (2000–2014), 21 equity ETFs:

| quantity | value |
|---|---|
| CS rank-permutation null, **centre** | **+0.0864** |
| #215 random-3, **median** | +0.0616 |
| #210 equal-weight eligible | +0.0709 |
| **null-centre excess over random-3** | **+0.0248 (≈ 2.5 pp/yr)** |

Had permutation destroyed selection, the null's centre would sit near
random-N. It sits ~2.5 pp/yr above it — **above equal-weight too.** The
clause-2 bar was therefore set higher than its construction intends, and every
clause-2 FAIL in this project was measured against a bar carrying an unknown
amount of inherited effect.

**ROTATION's 26-asset crypto universe is at least as correlated and was never
measured.** The size of the contamination on each prior program is unknown.
That is the gap this program closes — **not by re-opening any verdict, but by
recording what the bars actually were.**

---

## #217 — MEASURE the inheritance. Descriptive, table only.

For **crypto ROTATION (#187–#190)** and the **equities CS rules
(#204–#207)**, per window, report:

| column | definition |
|---|---|
| null centre | median of that rule's registered clause-2 null distribution |
| random-N median | median of the matched random-N control |
| equal-weight | the program's equal-weight benchmark |
| **excess over random-N** | null centre − random-N median (**pp/yr**) |
| **excess over equal-weight** | null centre − equal-weight (**pp/yr**) |
| **universe ρ̄** | average pairwise correlation of daily asset returns over that window |

`ρ̄` is the mean of the off-diagonal entries of the return correlation matrix,
computed over assets eligible for the whole window, so the record states the
correlation each contaminated bar was drawn on.

**No verdict is touched. No pass rule exists. This is a table.** It is
reported whatever it shows, including if inheritance turns out to be
negligible on crypto — which would itself be a finding, and would mean the
equities result does not generalise backwards.

---

## #218 — DESIGN: the TIME-ROTATION null

**Defining property: immunity to correlation inheritance.**

> Shift the **entire signal matrix** in time by a random offset, wrapping at
> the ends. Every asset's signal moves together by the same amount.

**What it preserves — exactly, by construction:**

- the **full cross-sectional structure** at every date (a whole row moves as
  a unit, so the correlation between assets' signals is untouched);
- each asset's **own autocorrelation** and the persistence of its signal;
- the **marginal distribution** of every signal series;
- the **number of positions**, cadence, and weighting.

**What it breaks — only this:** the alignment between the signal and the
returns that followed it.

**Why it is immune to inheritance.** The rank-permutation null asks "would a
*different asset* selected by this signal have done as well?" — and on a
correlated universe the answer is partly yes for reasons of correlation alone.
The time-rotation null asks "would the *same selection rule*, run on the same
universe, have done as well *aimed at the wrong dates*?" Correlation between
assets cannot supply that, because the null holds a genuine
top-momentum-of-some-date portfolio and is scored against a different date's
returns. Cross-asset correlation is preserved rather than exploited.

### Fixed parameters

| element | value |
|---|---|
| operation | circular shift of the signal matrix along the time axis |
| offset | drawn uniformly from **[24 months, T − 24 months]** |
| seeds | **1,200**, matching every prior program |
| applied in | **signal space** — the rule then applies its own eligibility mask, exactly as the repaired EQUITIES CS null does |

**The 24-month minimum offset is pinned now and is not free.** A shift shorter
than the signal's own persistence would leave the rotated selection
overlapping the real one, reintroducing inheritance through autocorrelation
instead of correlation. Twenty-four months is **twice the longest formation
horizon in any program using this null** (12-1), so no rotated window shares a
formation period with the real one. Excluding the symmetric tail at the far
end keeps the same guarantee for near-full rotations.

### Fidelity — all four axes, before any draw is scored

1. **Turnover drag (pp/yr).** Rotation preserves the signal path exactly, so
   turnover should match apart from the **single wrap seam** joining the end
   of the series to its start — one rebalance in ~170. Expected negligible;
   **measured and reported regardless**.
2. **Universe / eligibility fidelity.** 0% by construction, because the null
   operates in signal space and the rule applies its own time-correct
   eligibility mask. **Measured and reported anyway** — "by construction" is
   how the last two defects were justified before they were found.
3. **Cash-month count** (where applicable — TS-type rules). Rotation changes
   which months carry positive signals, so this is **not** guaranteed and must
   be measured; where it exceeds the ±2% tolerance the affected cell is
   declared **UNMEASURABLE**, per the standing `ex_best` convention.
4. **Correlation inheritance** (the new axis, see CLAUDE.md). Null centre
   minus matched random-N median, in pp/yr, reported beside `ρ̄`.

### Its known weakness, stated before it is used

**Shared seasonality survives the shift.** If the universe has a calendar
effect — a January pattern, a turn-of-month effect, a recurring risk-on
rhythm — a rotation by a whole number of months preserves it in the null
exactly as in the rule, and the null will be flattered by it. The time-rotation
null therefore **cannot** distinguish a genuine signal from one that is really
a seasonal.

**A second, smaller weakness:** on a universe whose composition changes, a
rotated signal row lands on a date with a different eligible set, which is the
same structural problem that made #208's cash-count fidelity unmeasurable on
DISCOVERY. It is expected to recur and will be reported, not hidden.

Neither weakness is fixable within this construction, and neither is a reason
to prefer the contaminated null. **The correct reading is that the two nulls
fail differently**: rank-permutation is contaminated by cross-asset
correlation, time-rotation by shared seasonality. Reporting both, with the
inheritance measured, is more honest than picking one and calling it clean.

---

## #219 — RE-SCORE, as calibration and not adjudication

Re-run the **clause-2 comparison only** for **#187** (crypto ROTATION top-5
30d) and **#204 / #205** (equities CS top-3 and top-5, 12-1), on **both
windows**, with the **same 1,200 seeds**, against the time-rotation null.

### The framing, worded now so no result can bend it

> **These re-scores change NO verdicts. Every registered FAIL stands.**
>
> Re-testing at a friendlier bar after seeing the result is the exact move
> this record exists to forbid (research rule 4). A rule that failed
> clause 2 against its registered null has failed clause 2. It does not
> become a pass, a partial pass, a "would have passed", or a candidate for
> anything, no matter what the corrected null says.

**The entire permitted output is one sentence per program:**

> *"Under the corrected null, clause 2 would have read X."*

That sentence is a **calibration fact about the instrument**, not a statement
about the rule. It is recorded so that the record says how much of each
historical bar was inherited effect — and so that **every future program
registers the corrected null from the start**, rather than inheriting a bar
nobody had measured.

**Binding on everything after this:** SHADOW-EVAL, FUNDING (#172–#186 at its
trigger), and any program registered from now on must specify its clause-2
null with the four-axis fidelity check including correlation inheritance, and
must state which null it uses and why. FUNDING is registered and dormant; this
requirement attaches to it at trigger time and **does not** otherwise reopen
or amend it.

### Explicitly out of scope

- **No verdict changes.** Not for #187, not for #204/#205, not for anything.
- **No promotion.** Nothing here can make anything tradeable.
- **No re-scoring of clause 1, 3 or 4**, and no re-scoring of any rule not
  named above. Three rules, one clause, two windows. That is the whole
  re-score.
- **No new hypotheses.** A rule that looks better under the corrected null is
  a candidate for a *future registration on future data*, not for a revision
  of this one, and this document does not create such a candidate.

---

## Closure

This list is the whole program: one measurement, one design, one calibration
re-score. Its deliverables are a table, a null, three sentences, and a
permanent amendment to the placebo methodology. **No edge claim is possible
from any of it**, and `docs/claims.md` cannot change as a result.

---

# NULL-CALIBRATION RESULT — #217–#219, run 2026-08-31

`research/run_null_calibration.py`, raw in `research/null_calibration.json`.

**EVERY REGISTERED VERDICT IS UNCHANGED. #187 FAIL. #204 FAIL. #205 FAIL.**
No edge claim is made or possible.

**The headline is not the one this program was registered expecting.** The
motivation assumed the bars were contaminated *upward* everywhere. On crypto
they were contaminated **downward, massively** — the crypto clause-2 bar was
far too **easy**, not too hard.

## #217 — Inheritance measurement (descriptive, table only)

Excesses in **percentage points per year**. `ρ̄` = mean off-diagonal
daily-return correlation over assets present for the whole window.

| program | # | rule | window | null centre | rand-N p50 | eq-wt | **exc rand** | **exc eq** | ρ̄ |
|---|---|---|---|---|---|---|---|---|---|
| ROTATION | #187 | top-5 30d | DISC | +0.5378 | +1.0390 | +1.1011 | **−50.12** | −56.33 | 0.751 |
| ROTATION | #188 | top-10 30d | DISC | +0.5746 | — | +1.1011 | — | −52.65 | 0.751 |
| ROTATION | #189 | top-5 90d | DISC | +0.5827 | +1.1586 | +1.1011 | **−57.59** | −51.84 | 0.751 |
| ROTATION | #190 | top-10 90d | DISC | +0.5361 | — | +1.1011 | — | −56.50 | 0.751 |
| ROTATION | #187 | top-5 30d | CONF | +0.2447 | +0.2331 | +0.2915 | **+1.16** | −4.68 | 0.606 |
| ROTATION | #188 | top-10 30d | CONF | +0.2568 | — | +0.2915 | — | −3.46 | 0.606 |
| ROTATION | #189 | top-5 90d | CONF | +0.2583 | +0.2283 | +0.2915 | **+2.99** | −3.32 | 0.606 |
| ROTATION | #190 | top-10 90d | CONF | +0.2664 | — | +0.2915 | — | −2.51 | 0.606 |
| EQUITIES | #204 | CS top-3 12-1 | DISC | +0.0864 | +0.0616 | +0.0709 | **+2.48** | +1.54 | 0.637 |
| EQUITIES | #205 | CS top-5 12-1 | DISC | +0.0874 | +0.0622 | +0.0709 | **+2.51** | +1.64 | 0.637 |
| EQUITIES | #206 | CS top-3 6-1 | DISC | +0.0806 | +0.0616 | +0.0709 | **+1.90** | +0.97 | 0.637 |
| EQUITIES | #207 | CS top-5 6-1 | DISC | +0.0811 | +0.0622 | +0.0709 | **+1.88** | +1.01 | 0.637 |
| EQUITIES | #204 | CS top-3 12-1 | CONF | +0.1009 | +0.0936 | +0.1036 | **+0.73** | −0.27 | 0.454 |
| EQUITIES | #205 | CS top-5 12-1 | CONF | +0.1008 | +0.0940 | +0.1036 | **+0.68** | −0.28 | 0.454 |
| EQUITIES | #206 | CS top-3 6-1 | CONF | +0.0989 | +0.0936 | +0.1036 | **+0.52** | −0.47 | 0.454 |
| EQUITIES | #207 | CS top-5 6-1 | CONF | +0.1005 | +0.0940 | +0.1036 | **+0.65** | −0.31 | 0.454 |

`#188`/`#190` have no matched random-N: the ROTATION registration refused to
invent a random-10 after seeing results, and that refusal is honoured here
rather than quietly reversed.

### Mechanism — measured, not asserted

Crypto DISCOVERY's −50 to −58 pp/yr is not correlation inheritance in
reverse. It is the **universe-fidelity defect**, applied retroactively to a
null that was never checked for it — axis 2 was introduced by ALLOCATION, one
program *after* ROTATION ran.

| window | # | real ineligible weight | **null ineligible weight** | assets alive all window |
|---|---|---|---|---|
| DISCOVERY | #187 | 0.000% | **31.97%** | **5 of 26** |
| DISCOVERY | #188 | 0.000% | 30.71% | 5 |
| DISCOVERY | #189 | 0.000% | 30.43% | 5 |
| DISCOVERY | #190 | 0.000% | 29.82% | 5 |
| CONFIRMATION | #187 | 0.000% | 3.40% | 24 of 26 |
| CONFIRMATION | #189 | 0.000% | 3.09% | 24 |

**Roughly a third of the crypto null's gross weight sat in assets that did
not exist**, earning exactly zero through `fillna(0.0)`. That is what dragged
its centre 50 pp/yr below random selection. Only **5 of 26** assets were alive
for the whole of DISCOVERY.

### What the table says

1. **The crypto clause-2 bar on DISCOVERY was far too EASY.** Every ROTATION
   rule was compared against a null crippled by holding one-third
   non-existent assets. **#187's DISCOVERY clause-2 PASS — the single
   clause-2 pass anywhere in the crypto record — was measured against that
   null and means nothing.** The verdict was and remains FAIL, on
   CONFIRMATION, which is unaffected.
> ### Cross-reference added 2026-09-01 — #249's M6 is the empirical input here
>
> The inheritance measured in this program is a FUNCTION of the universe's
> pairwise correlation, and #249's M6 measured that quantity directly on the
> tradable-26, year by year, with bands:
>
> | year | assets alive | mean pairwise ρ̄ | 95% CI |
> |---|---|---|---|
> | 2020 | 12 | +0.680 | [+0.657, +0.701] |
> | 2021 | 15 | **+0.479** | [+0.433, +0.520] |
> | 2022 | 24 | **+0.707** | [+0.686, +0.727] |
> | 2023 | 24 | +0.538 | [+0.513, +0.557] |
> | 2024 | 25 | +0.566 | [+0.547, +0.582] |
> | 2025 | 25 | +0.694 | [+0.668, +0.714] |
>
> **ρ̄ ranges 0.479 → 0.707 and the variation is not noise** — the CIs are
> tight and non-overlapping between the extremes. So inheritance
> contamination on THIS universe is not a constant to be quoted once: it is
> materially higher in 2022 and 2025 than in 2021, and any future program
> reporting axis 4 on the tradable-26 should report ρ̄ for its own window
> rather than citing a single project-wide number.
>
> This is a cross-reference, not a new finding, and it changes no verdict in
> #217–#219. It is recorded here so the axis-4 measurement has its empirical
> input attached rather than floating free.

2. **Where universes are complete, inheritance is upward and tracks ρ̄.**
   Equities DISCOVERY ρ̄ 0.637 → +1.9 to +2.5 pp; equities CONFIRMATION
   ρ̄ 0.454 → +0.5 to +0.7 pp; crypto CONFIRMATION ρ̄ 0.606 → +1.2 to +3.0 pp.
   The equities motivation generalises to crypto CONFIRMATION and is roughly
   the same size there.
3. **The two defects push opposite ways and can coexist in one program.**
   ROTATION's DISCOVERY bar was too easy and its CONFIRMATION bar slightly too
   hard. A single "the bars were contaminated upward" story would have been
   wrong.

## #218 — The time-rotation null, own fidelity, all four axes

### Feasibility first — and the crypto legs are INFEASIBLE

| window | T (months) | range [24, T−24] | |
|---|---|---|---|
| crypto ROTATION DISCOVERY | 42.4 | [24, 18.4] | **EMPTY — INFEASIBLE** |
| crypto ROTATION CONFIRMATION | 34.7 | [24, 10.7] | **EMPTY — INFEASIBLE** |
| equities DISCOVERY | 172.6 | [24, 148.6] | feasible |
| equities CONFIRMATION | 141.3 | [24, 117.3] | feasible |

**The crypto windows cannot carry this null.** The 24-month bound is locked
and may not be relaxed to make a run happen (research rule 4), and rotating
over the full crypto series to lengthen T would pull signal rows out of the
**LOCKBOX**. Recorded as a fact about the data: *crypto's windows are too
short to support a correlation-immune null of this design.*

### Measured fidelity, equities, before any draw scored anything

| window | # | 1 turnover | 2 universe | 3 cash-months | 4 **inheritance** |
|---|---|---|---|---|---|
| DISCOVERY | #204 | 1.02×, **+0.007 pp/yr** | 0.000% vs 0.000% | 2847 → 2847.0, **0.00%** PASS | **−0.14 pp/yr** |
| DISCOVERY | #205 | 0.98×, −0.006 pp/yr | 0.000% vs 0.000% | 2501 → 2501.0, 0.00% PASS | **−0.12 pp/yr** |
| CONFIRMATION | #204 | 1.01×, +0.005 pp/yr | 0.000% vs 0.000% | 2556 → 2556.0, 0.00% PASS | **+2.16 pp/yr** |
| CONFIRMATION | #205 | 1.01×, +0.005 pp/yr | 0.000% vs 0.000% | 2272 → 2272.0, 0.00% PASS | **+2.40 pp/yr** |

Offsets drawn 40–143 months (DISCOVERY) and 36–113 (CONFIRMATION).

Axes 1–3 are excellent: turnover within 2% (drag ≤0.007 pp/yr), zero
ineligible weight, and **cash-month counts preserved exactly** — 0.00%
deviation, which is what a whole-block rotation should give and is now
measured rather than assumed.

### Axis 4 — the design's defining property holds on one window and not the other

**This is the finding of #218 and it is a partial refutation of its own
registration.** The null was registered as *immune to correlation
inheritance*. On DISCOVERY it is: inheritance **−0.14 / −0.12 pp/yr**,
essentially zero, against the rank-permutation null's **+2.48 / +2.51** on the
same data. The design works exactly as claimed.

On CONFIRMATION it does not: **+2.16 / +2.40 pp/yr**, no better than the
rank-permutation null it was built to replace (+0.73 / +0.68 — in fact
*worse*).

The mechanism is not cross-asset correlation, which rotation does neutralise.
It is **regime persistence**: over 2014–2026 the same few ETFs led throughout,
so a top-momentum portfolio formed at *any* date overlaps heavily with one
formed at another. Rotation moves the formation date and lands on much the
same holdings. This is the second weakness the registration named — shared
structure surviving the shift — arriving as persistence rather than
seasonality.

**So the corrected null is not a clean instrument either.** It removes
correlation inheritance and remains exposed to persistence inheritance. That
is recorded here, before it is used by anything, so no future program adopts
it believing it is neutral.

## #219 — Calibration re-score. NO VERDICT CHANGES.

> **#187** — *Under the corrected null, clause 2 would have read:*
> **INFEASIBLE — the locked [24, T−24] offset range is empty on both ROTATION
> windows (42.4 and 34.7 months).**
> *(Registered read: DISCOVERY +1.3993 vs p_adj +1.1365 → PASS; CONFIRMATION
> +0.5270 vs p_adj +0.6185 → FAIL.)*

> **#204** — *Under the corrected null, clause 2 would have read:*
> **DISC +0.0723 vs p_adj +0.1308 → FAIL; CONF +0.1267 vs p_adj +0.1614 →
> FAIL.**
> *(Registered read: DISC +0.0726 vs p_adj +0.1273 → FAIL; CONF +0.1264 vs
> p_adj +0.1484 → FAIL.)*

> **#205** — *Under the corrected null, clause 2 would have read:*
> **DISC +0.0818 vs p_adj +0.1082 → FAIL; CONF +0.1239 vs p_adj +0.1493 →
> FAIL.**
> *(Registered read: DISC +0.0821 vs p_adj +0.1147 → FAIL; CONF +0.1234 vs
> p_adj +0.1350 → FAIL.)*

**The corrected null is mostly a HARDER bar, not a friendlier one** — p_adj
rises in three of the four measurable cells (+0.1273→+0.1308,
+0.1484→+0.1614, +0.1350→+0.1493) and falls in one (+0.1147→+0.1082). Nothing
here was a route to an easier test, and nothing changes: every FAIL stands as
registered.

## Consequences

- **No verdict moves.** #187 FAIL, #204 FAIL, #205 FAIL, and every other
  registered verdict in this project stands exactly as written.
- **`docs/claims.md` is unchanged** and still holds zero supported edge
  claims.
- **Binding on every future program.** SHADOW-EVAL, FUNDING at its trigger,
  and anything registered from now on must specify its clause-2 null with the
  four-axis check, must report inheritance in pp/yr beside ρ̄, and must state
  which null it uses and why. The time-rotation null is available **with its
  measured persistence weakness attached** — it is not a default and not a
  clean instrument.
- **One correction to the crypto record, recorded not revised:** ROTATION's
  DISCOVERY clause-2 comparisons were made against a null holding ~30% dead
  weight. That does not change ROTATION's FAIL verdicts, which rest on
  CONFIRMATION, but **#187's DISCOVERY clause-2 pass may not be cited as
  evidence of anything**, and the close-out's description of it as "the
  closest this project has come" should be read with that attached.
- **A design fact worth keeping:** crypto's 6.4-year windows are too short to
  carry a rotation-based null at all. Any future crypto program wanting one
  needs a longer history than this project has.

---

# PRE-REGISTRATION — BINANCE FUNDING PROGRAM (#220–#234)

> **LOCKED 2026-08-31.** §6's coverage clause signed off as proposed
> (**≥ 2 of 3**). An EXECUTION ORDER clause was added before lock at the
> maintainer's instruction. Research rule 4 now applies to every constant
> below: nothing may change on the basis of a result.

## What this program is, and what it is not

**Every hypothesis, rule, threshold, definition and pass condition is
inherited VERBATIM from the locked #172–#186.** Nothing is chosen here.
This is the same eight rules and fifteen tests, run on a deeper archive from
a different venue.

**Six things change, and they are exhaustively listed in §1–§6.** Anything
not in that list is inherited unchanged, and where the inherited text and
this document appear to disagree, **#172–#186 governs.**

**Why inheritance matters procedurally.** The reconciliation record
(`research/funding_reconciliation.md`) was read before this was drafted. If
any threshold here were choosable, that read could have anchored it. Because
every constant is inherited verbatim, **there is nothing for it to anchor.**
That is the whole reason the program is built this way rather than
re-derived.

---

## §0. Inheritance map — every test, original number beside its new one

| new # | orig # | rule | mode | definition (inherited verbatim) |
|---|---|---|---|---|
| **#220** | #172 | F1 | standalone | BUY when the trailing **30-day percentile rank** of daily-mean funding is **≤ 10**. |
| **#221** | #173 | F1 | overlay | Incumbent BUY kept only when F1 holds. |
| **#222** | #174 | F2 | standalone | BUY on the first day whose daily-mean funding is **> 0** after **≥ 72 consecutive hours** of funding **< 0**. |
| **#223** | #175 | F2 | overlay | Incumbent BUY kept only when F2 holds. |
| **#224** | #176 | F3 | standalone | BUY when the **8-hour-equivalent** funding rate is **≤ −0.01%**. |
| **#225** | #177 | F3 | overlay | Incumbent BUY kept only when F3 holds. |
| **#226** | #178 | F4 | **overlay only** | **SUPPRESS** an incumbent BUY when the 30-day percentile rank is **≥ 90** AND the close is a **20-day high**. |
| **#227** | #179 | F5 | standalone | BUY when **cumulative funding over the trailing 7 days is ≤ 0**. |
| **#228** | #180 | F5 | overlay | Incumbent BUY kept only when F5 holds. |
| **#229** | #181 | F6 | standalone | BUY when the **30-day z-score** of daily-mean funding is **≤ −2.0**. |
| **#230** | #182 | F6 | overlay | Incumbent BUY kept only when F6 holds. |
| **#231** | #183 | F7 | standalone | BUY when the close is a **20-day high** AND the **7-day mean funding is ≤ 0**. |
| **#232** | #184 | F7 | overlay | Incumbent BUY kept only when F7 holds. |
| **#233** | #185 | F8 | standalone | BUY when funding has been **< 0 for ≥ 168 consecutive hours**. |
| **#234** | #186 | F8 | overlay | Incumbent BUY kept only when F8 holds. |

**Inherited unchanged and not restated in full:** the 30-day percentile-rank
construction (`rolling(30).rank(pct=True) * 100`), the 30-day z-score
(`ddof=0`, including today), cumulative-7-day funding, the 20-day-high
definition on the incumbent's daily merged frame, **no-gap-tolerance
consecutive-hour counting** (a missing settlement breaks the run), long-side
only, STANDALONE vs OVERLAY semantics, `LIVE_GEOMETRY`, 2bps fee + 2bps
slippage per side, scoring through `research/harness.py`, the no-lookahead
alignment rule (funding known as of the last settlement of day D applies to
day D's daily close, entering at D+1), 4 equal-duration folds, `ex_best`
requiring ≥3 folds of ≥10 trades, **an undefined `ex_best` is UNMEASURABLE
and CANNOT PASS**, episode-matched placebo at **3,000 seeds**, pass condition
`ex_best > 0 on ALL THREE tickers` AND pooled `net_all` above the adjusted
placebo percentile, single confirmation, no re-runs, no partial credit.

---

## §1. CHANGE — data and primary venue

**Data: `data/derivatives/binance_funding.csv`.** Binance USD-M perpetuals
`BTCUSDT` / `ETHUSDT` / `SOLUSDT`, from the Binance Vision monthly archive.
**20,941 rows**, BTC/ETH 2020-01-01 → 2026-07-31, SOL 2020-09-13 → 2026-07-31.

**Field used: `funding_rate`** — the dimensionless per-interval rate as
published (`last_funding_rate` in the source files). This is the direct
analogue of Kraken's `relative_funding_rate`, which #172–#186 selected for
exactly the same reason: it is dimensionless and therefore comparable across
symbols and price levels.

**Binance is primary on measured grounds, cited, not asserted** — see
`research/funding_reconciliation.md` and `research/funding_source_probe.md`:

| ground | measurement |
|---|---|
| depth | **5.05 usable years** after burn-in and lockbox, against 1.00 at #172–#186's C1 |
| structure | **zero** gaps beyond the stated interval; **100%** of settlements on 00/08/16 UTC; all 12 overlap months fully covered |
| comparison | Kraken over the same overlap: 8 gaps/symbol, longest 3.0h, ~9 hours missing |
| archive form | monthly files are **immutable once published** — re-running is idempotent and history cannot be silently revised under us |

**The archive floor is 2020-01 and is an ARCHIVE floor, not contract
inception** (2019 months verified HTTP 404 for both `fundingRate` and
`klines/1d`; the first klines month is a full 31-row January). Nothing before
2020-01 exists in this source. This bounds the program and is not a defect.

---

## §2. CHANGE — units, mapped mechanically

#172–#186's normalization clause: *"all absolute thresholds in this program
are stated in 8h-equivalent units"*, computed from Kraken by summing 8 hourly
rates, **summed rather than scaled because the sum is the actual cost of
holding those 8 hours**.

**Binance settles natively at 8h, so the mapping is mechanical:**

- Where `funding_interval_hours == 8`, the **row value IS the 8h-equivalent**.
  No transformation.
- Where the interval is shorter (stress schedule), **consecutive rows are
  SUMMED to 8 hours**. Identical holding-cost logic to F3's original
  normalization — the sum is what a position actually paid.

**The known instance, measured:** `SOLUSDT` ran a **2-hour** interval from
**2022-11-09 20:00Z to 2022-11-18 08:00Z** (the FTX window; Binance shortens
intervals under stress), plus two 4-hour rows. **101 non-8h rows in the whole
archive, all SOL, all inside that window.** BTCUSDT and ETHUSDT are 8h for
every one of their 7,212 rows.

Every threshold inherited from #172–#186 is therefore applied to a series
already in the units those thresholds were written in. **F3's −0.0001
threshold is unchanged.**

---

## §3. CHANGE — the adjudicating null, named at registration

Per standing law, the null is **named here** and its four fidelity axes are
**measured before any draw is scored**.

**Adjudicating null: the episode-matched placebo, inherited from #167 and
#172–#186. 3,000 seeds.** Per ticker: take the observed run-lengths of
consecutive event days, draw the same NUMBER of runs with the same LENGTHS at
random non-overlapping start positions in the same window, apply the same
confirm rule. Independent-day placebos remain **forbidden** — funding regimes
are persistent, so a scattered placebo is structurally lower-variance than
what it benchmarks.

### The four axes, and how they map to a single-ticker event series

The axes were derived on portfolio rules. Two map directly, one by analogue,
one does not apply — stated rather than forced:

| axis | mapping | expected |
|---|---|---|
| **1. Turnover** | same event count and run-lengths by construction → same trade count; report mean `cost_r` real vs null | ratio ≈ 1.00 by construction; **measured anyway**, because "by construction" is how the last three defects were justified before they were found |
| **2. Universe / eligibility** | placebo runs may land **only on eligible days** — days not excluded by §6's coverage rule and able to carry a confirmed entry; report the fraction landing on excluded days | **0.000%** expected; if not, the null is trading days the rule cannot |
| **3. Cash-month count** | **NOT APPLICABLE.** An event series has no exposure budget to hold aside. Reported as N/A with this reason, not silently omitted | — |
| **4. Inheritance** | no cross-section exists, so the analogue is: null centre vs an **independent-day draw of the same event count**. The gap measures how much of the bar comes from run-length clustering rather than from funding | **expected non-zero and material** — see below |

### Expected weaknesses on THIS data, stated before use

1. **Axis 4 will show inheritance, and that is by design, not a defect.** The
   episode-matched null deliberately preserves clustering because #167
   established that an independent-day null is too easy here. So it is a
   **timing null, not a mechanism null**: it asks "would runs of this shape,
   placed at random, have done as well", and cannot distinguish a funding
   signal from any other signal producing the same run-length structure. The
   inheritance number is reported so the size of that is on record.
2. **Persistence inheritance over 5 years.** The window spans 2021–2026,
   including a sustained bull and a sustained bear. A drawn run lands in some
   regime, and regimes are long relative to run lengths, so the null inherits
   regime exposure the same way NULL-CALIBRATION found the time-rotation null
   did on equities CONFIRMATION.
3. **No alternate null family is feasible.** The time-rotation null requires
   ≥48 months per window; DISCOVERY is 2.78y (33 months) and CONFIRMATION
   2.27y (27 months). **Both are below the bound**, exactly as the crypto
   ROTATION windows were. It is therefore not reported beside — stated with
   the number that makes it infeasible, per standing law.

---

## §4. CHANGE — its own Bonferroni

**k is computed for THIS program, not inherited as a number.** #220–#234 is
**15 registered tests**, so:

**alpha = 0.05 / 15 = 0.003333 → required percentile 99.6667**

This equals #172–#186's figure because the test count is identical, **not
because the number was carried over**. The correction counts tests, not
rules: #220 and #221 are two chances at the same idea and both are counted.
3,000 seeds put ~10 draws above the threshold; p95 is reported alongside from
the same draws for comparability.

---

## §5. CHANGE — windows anchored on the funding freeze

**Freeze = the archive's last timestamp, `2026-07-31 16:00Z`.** Lockbox is
the last 6 months; the remainder splits at the project standard
`DISCOVERY_FRAC = 0.55`. The inherited **4-month burn-in** is applied per
symbol before the usable window opens.

| | date | length |
|---|---|---|
| BTC/ETH data start | 2020-01-01 | |
| SOL data start | 2020-09-13 | |
| burn-in ends (BTC/ETH) | 2020-05-01 | |
| burn-in ends (SOL) | **2021-01-13** | |
| **common usable start** | **2021-01-13** | governed by SOL |
| **DISCOVERY** | 2021-01-13 → 2023-10-24 | **2.78 y** |
| **CONFIRMATION** | 2023-10-24 → 2026-01-31 | **2.27 y** |
| **LOCKBOX** | 2026-01-31 → 2026-07-31 | 0.50 y — **SEALED** |
| **total usable** | | **5.05 y** |

**The common start is governed by SOL** because the inherited pass condition
requires `ex_best > 0` on **all three tickers**, which requires one shared
window. BTC and ETH individually reach back to 2020-05-01; that extra
0.70y is deliberately **not used**, because scoring three tickers on
different spans would make the pooled statistic incoherent.

**5.05 usable years against #172–#186's 1.00 at C1.** The power limitation
that registration recorded — "a real but modest edge will likely read as
unmeasurable or fail" — is **substantially relaxed here**. That is the
substantive reason this program is worth running at all, and it is why the
DISCOVERY/CONFIRMATION split is available where C1 had only a single window.

---

## §6. ⚠ THE ONE CLAUSE REQUIRING JUDGMENT — daily-mean coverage

**This is the only clause in the document not mechanically determined.
Explicit sign-off requested.**

**Inherited (#172–#186):** *daily-mean funding for day D = arithmetic mean
over all hourly rows in `[D 00:00, D 23:59]`; days with fewer than **20 of
24** hourly rows are excluded from every rule and every lookback.*

Kraken settles **hourly** (24/day). Binance settles **8-hourly** (3/day).
20-of-24 is **83.3%** coverage, and 3 does not divide into that: **≥2 of 3 is
66.7%** (more permissive) and **≥3 of 3 is 100%** (stricter). Neither
reproduces 83.3%. A choice is unavoidable.

**FIXED (signed off 2026-08-31): `≥ 2 of 3 settlements, or the day is
excluded.`**

**Rationale.** The inherited clause's *purpose* is to exclude days whose mean
is computed from too little of the day to represent it — not to enforce a
particular percentage. 20-of-24 tolerates losing up to 4 hours, i.e. **one
Binance settlement interval's worth of time**. ≥2 of 3 tolerates losing one
settlement. Requiring 3 of 3 would make a single missing settlement void a
day, which is stricter than the inherited rule ever was and would let one
dropped file delete a day the rule could have used.

**What it actually costs, measured (counts only, no values):**

| symbol | days | 3 settlements | excluded at ≥2 of 3 | excluded at ≥3 of 3 |
|---|---|---|---|---|
| BTCUSDT | 2,404 | **2,404 (100.00%)** | **0** | **0** |
| ETHUSDT | 2,404 | **2,404 (100.00%)** | **0** | **0** |
| SOLUSDT | 2,148 | 2,137 (99.49%) | **1 (0.047%)** | **1 (0.047%)** |

*(SOL's 10 days with more than 3 settlements are the FTX stress window; they
are denser, not deficient, and are excluded by neither rule.)*

**The two candidate rules differ on exactly ONE day of 6,956.** The clause
needed a decision because it cannot be derived, but the decision is
near-costless either way, and that is stated so the sign-off is not mistaken
for a consequential choice. **≥2 of 3 is now fixed and may not be revisited.**

---

## §7. EXECUTION ORDER — the one residual freedom, foreclosed

Inheritance fixes every parameter, but it does not by itself fix the ORDER
and GRANULARITY of execution, and that is a real degree of freedom: a session
that ran #220, looked, then decided whether to run #221 could shape the
program by stopping early, reordering, or abandoning a line that looked
unpromising. None of that changes a threshold, so none of it is caught by
research rule 4.

**Therefore:**

> **All fifteen tests run in a SINGLE BATCH from ONE script invocation, and
> ALL results are written to disk BEFORE ANY of them is read.**

- **No early result may gate, reorder, or abort a later one.** The batch runs
  to completion or it fails as a whole; a partial batch is not a result and
  is not reported as one.
- **No test may be run individually first** "to check the plumbing" on the
  real data. Plumbing is verified on the fidelity axes (§3), which are
  measured before any test is scored.
- **A crash mid-batch voids the run.** It is fixed and the whole batch is
  re-run from the start; the fifteen results must come from one execution so
  that none of them could have been informed by another.
- **The read happens once, on the complete written output.**

This closes the last thing inheritance leaves open. It costs nothing — the
tests are independent by construction — and it removes the only remaining
route by which a human decision could enter between registration and result.

---

## RELATIONSHIP TO #172–#186

**#172–#186 stays SEALED and UNMODIFIED.** Its trigger is unchanged (span ≥
22 months on `kraken_funding.csv`, expected 2027-06-27), its rules are
unchanged, its C1/C2 checkpoints are unchanged. **This program neither opens
nor amends it, and running #220–#234 does not consume, satisfy, or
substitute for it.**

The two are **independent cross-venue tests of the same eight rules**:
different venue, different settlement grid, different span, non-overlapping
usable windows except where the archives coincide. #172–#186 remains the
**independent cross-venue confirmation**, and its value depends on staying
untouched by whatever #220–#234 reports.

**A result here does not license editing #172–#186 in either direction.** Not
to narrow it after a pass, not to abandon it after a failure.

**Inherited cross-venue check, with its expected outcome disclosed.**
#172–#186 requires reporting Pearson correlation of daily means against the
secondary venue, flagging any symbol below **0.80**. Inherited verbatim with
Kraken now secondary. **On the measured evidence this flag is LIKELY TO FIRE
for all three symbols:** the reconciliation report's Spearman on pre-lockbox
daily means is **+0.595 / +0.512 / +0.492** (BTC/ETH/SOL). The threshold is
**not** relaxed to avoid that. The flag cannot change a pass or a fail — it
is disclosure — and a fired flag is the honest reading of two genuinely
different contracts, which §RECONCILIATION framing said to expect.

---

## PRIOR EXPOSURE — disclosed, because omitting it would overstate blindness

**#172–#186's central property does not transfer to this program, and
claiming it would be false.** That registration was made before its test data
existed. This one is made on an archive that exists now and could in
principle have been inspected.

What has actually been looked at, in full:

1. **The preliminary quintile table (2026-08-31, `docs/cleanroom.md`).**
   Kraken funding quintiles vs forward 1/3/7-day returns, three tickers,
   **pre-lockbox only**, 183 days, ~36 per cell. Marked "Preliminary — NOT
   registered", no placebo, no thresholds, and explicitly recorded as
   establishing nothing.
2. **The reconciliation record (2026-08-31).** Binance-vs-Kraken structural
   agreement, values pre-lockbox only.

**Why this does not compromise #220–#234:**

- **Different venue and different granularity.** The quintile look was
  Kraken hourly; this program is Binance 8-hourly.
- **No threshold here was chosen from it — because no threshold here is
  chosen at all.** Every constant is inherited verbatim from a registration
  locked before either look happened. **Inheritance forecloses the choice**,
  which is a structurally stronger guarantee than a promise not to have been
  influenced.
- **The sealed span was never read.** Both looks cut at the lockbox for
  values.

**What it does cost, stated plainly:** this program cannot claim
#172–#186's "registered before the data existed" property. It claims the
weaker but still meaningful one — **registered with no free parameters**. The
distinction is recorded here so no later write-up can quietly upgrade it.

---

## BUDGET AND CLOSURE

- **This list is the whole program.** Eight rules, fifteen tests, one run.
- **No rule may be added, edited or re-run.** No parameter may be tuned —
  every number is inherited or listed above.
- **Single confirmation, no partial credit, no second look at a looser bar.**
- **A failure here does not close the funding question**, because #172–#186
  remains pending as the independent cross-venue test. A failure *there* as
  well, at C2, is what closes it — per that registration's own closure
  clause, which is not amended by this document.

**Reported whatever the outcome:** per test and per ticker — `n`,
**episodes**, win%, `net_all`, `ex_best`, folds counted/positive, placebo p95
and p99.6667, the observed percentile, all four fidelity-axis measurements
(with axis 3 marked N/A and axis 4's inheritance quantified), the
cross-venue flag state, and days excluded by §6 per symbol. Negatives get the
same detail as positives (research rule 5).

---

# BINANCE FUNDING RESULT — #220–#234, run 2026-08-31

`research/run_220.py`, raw in `research/h220_results.json`.

**VERDICT: 0 of 15 pass. All fifteen FAIL.**

Executed as registered §7: **one batch, one invocation, all thirty cells
written to disk before any was read.** No result gated, reordered or aborted
another.

Windows as locked: DISCOVERY 2021-01-13 → 2023-10-24, CONFIRMATION
2023-10-24 → 2026-01-31, LOCKBOX from 2026-01-31 **sealed and unread**.
k = 15 → 99.6667th percentile, 3,000 seeds.

## Cross-venue flag — FIRED on all three, as disclosed in advance

| symbol | Pearson vs Kraken | n days | flag |
|---|---|---|---|
| BTC | **+0.452** | 157 | **FIRED** |
| ETH | **+0.371** | 157 | **FIRED** |
| SOL | **+0.719** | 157 | **FIRED** |

The registration predicted this from the reconciliation record's Spearman
(+0.595/+0.512/+0.492) and refused to relax the inherited 0.80 bar to avoid
it. Pearson comes in **lower still** than Spearman — the two venues agree on
ranks more than on levels, which is what cross-venue framing predicted. The
flag is disclosure and changes no verdict.

Days excluded by the signed-off ≥2-of-3 coverage rule: **BTC 0, ETH 0,
SOL 1**, exactly as the sign-off table said.

## Fidelity axes — measured before any test was scored

| axis | DISCOVERY | CONFIRMATION |
|---|---|---|
| **1 turnover** | 385 real trades, null mean **385.0 (ratio 1.000)**; `cost_r` real 0.0237 vs null 0.0281 | 357 vs **357.0 (1.000)**; 0.0309 vs 0.0327 |
| **2 eligibility** | **0** of 77,000 null events on excluded days | **0** of 71,400 |
| **3 cash-months** | N/A — event series has no exposure budget | N/A |
| **4 inheritance** | −0.0635 vs −0.0606 → **−0.0029** | +0.0850 vs +0.0872 → **−0.0022** |

Axis 1 is exactly 1.000 by construction and was measured anyway — "by
construction" is how the last three defects were justified before they were
found. The null pays *slightly more* cost per trade than the rule does, so
the bar is marginally conservative rather than flattered.

**Axis 4 needs an honest caveat.** It reads ≈ 0, and that does **not**
vindicate episode-matching. #167 chose episode-matching because independent-
day placebos are structurally lower-**variance**; axis 4 as defined measures
**centre** displacement. The centres coincide here because both draws sample
the same window's return distribution — the difference episode-matching makes
is in the tail, which is where the 99.67th percentile actually lives, and
this axis does not see it. So the reading is "no centre inflation", not "the
null choice was unnecessary".

## Results — every cell, both clauses

| # | rule | mode | window | n | eps | pooled | plc p95 | plc adj | pctile | clause 1 | clause 2 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| #220 | F1 | standalone | DISC | 385 | 61 | −0.034 | +0.074 | +0.163 | 63.5% | FAIL | FAIL |
| #220 | F1 | standalone | CONF | 357 | 45 | +0.141 | +0.236 | +0.333 | 71.8% | FAIL | FAIL |
| #221 | F1 | overlay | DISC | 20 | 18 | +0.347 | +0.462 | +0.766 | 90.6% | UNMEAS (3/3) | FAIL |
| #221 | F1 | overlay | CONF | 43 | 27 | +0.290 | +0.499 | +0.731 | 76.9% | UNMEAS (3/3) | FAIL |
| #222 | F2 | standalone | DISC | 5 | 5 | −0.420 | +0.788 | +1.980 | 24.4% | UNMEAS (3/3) | FAIL |
| #222 | F2 | standalone | CONF | 2 | 2 | +0.468 | +1.966 | +1.978 | 73.1% | UNMEAS (3/3) | FAIL |
| #223 | F2 | overlay | DISC | 1 | 1 | −1.020 | +1.991 | +1.995 | 18.9% | UNMEAS (3/3) | FAIL |
| #223 | F2 | overlay | CONF | **0** | 0 | — | — | — | — | UNMEAS (3/3) | FAIL |
| #224 | F3 | standalone | DISC | 228 | 34 | −0.002 | +0.202 | +0.315 | 51.0% | UNMEAS (2/3) | FAIL |
| #224 | F3 | standalone | CONF | 40 | 12 | −0.421 | +0.475 | +0.702 | 4.4% | UNMEAS (3/3) | FAIL |
| #225 | F3 | overlay | DISC | 16 | 8 | −0.159 | +0.742 | +1.133 | 29.7% | UNMEAS (3/3) | FAIL |
| #225 | F3 | overlay | CONF | 4 | 3 | −1.026 | +1.094 | +1.978 | 1.7% | UNMEAS (3/3) | FAIL |
| **#226** | F4 | suppress | DISC | 528 | 69 | −0.053 | +0.066 | +0.142 | 46.1% | FAIL | FAIL |
| **#226** | F4 | suppress | CONF | 434 | 52 | **+0.193** | +0.211 | +0.305 | **92.6%** | **PASS** | FAIL |
| #227 | F5 | standalone | DISC | 500 | 32 | −0.090 | +0.114 | +0.219 | 25.5% | FAIL | FAIL |
| #227 | F5 | standalone | CONF | 209 | 17 | +0.035 | +0.276 | +0.394 | 50.5% | UNMEAS (3/3) | FAIL |
| #228 | F5 | overlay | DISC | 55 | 16 | −0.502 | +0.370 | +0.575 | 0.7% | UNMEAS (3/3) | FAIL |
| #228 | F5 | overlay | CONF | 42 | 11 | +0.186 | +0.473 | +0.690 | 70.2% | UNMEAS (3/3) | FAIL |
| #229 | F6 | standalone | DISC | 155 | 45 | −0.121 | +0.186 | +0.311 | 27.1% | FAIL | FAIL |
| #229 | F6 | standalone | CONF | 100 | 35 | +0.178 | +0.370 | +0.526 | 70.1% | UNMEAS (2/3) | FAIL |
| #230 | F6 | overlay | DISC | 6 | 5 | −0.031 | +0.970 | +1.616 | 57.1% | UNMEAS (3/3) | FAIL |
| #230 | F6 | overlay | CONF | 11 | 10 | +0.599 | +0.822 | +1.264 | 87.8% | UNMEAS (3/3) | FAIL |
| #231 | F7 | standalone | DISC | 35 | 8 | +0.351 | +0.605 | +0.936 | 86.1% | UNMEAS (3/3) | FAIL |
| #231 | F7 | standalone | CONF | 14 | 4 | −0.613 | +0.892 | +1.322 | 4.0% | UNMEAS (3/3) | FAIL |
| #232 | F7 | overlay | DISC | 1 | 1 | +1.990 | +1.991 | +1.995 | 93.6% | UNMEAS (3/3) | FAIL |
| #232 | F7 | overlay | CONF | 1 | 1 | +1.945 | +1.971 | +1.983 | 69.4% | UNMEAS (3/3) | FAIL |
| #233 | F8 | standalone | DISC | 18 | 5 | +0.415 | +0.818 | +1.320 | 77.9% | UNMEAS (3/3) | FAIL |
| #233 | F8 | standalone | CONF | **0** | 0 | — | — | — | — | UNMEAS (3/3) | FAIL |
| #234 | F8 | overlay | DISC | 6 | 2 | +0.277 | +1.478 | +1.987 | 61.6% | UNMEAS (3/3) | FAIL |
| #234 | F8 | overlay | CONF | **0** | 0 | — | — | — | — | UNMEAS (3/3) | FAIL |

`UNMEAS (k/3)` = `ex_best` undefined on k of 3 tickers; per the inherited
rule that is **UNMEASURABLE and cannot pass — it is the absence of a result,
not a failure.** The FAIL verdict in those rows is carried by **clause 2**,
which is measurable everywhere the cell has trades at all.

## What actually happened

**Clause 2 fails in all thirty cells. Not one cell reaches its adjusted
percentile.** The best is #232's 93.6% on a single trade, and the best
non-degenerate is **#226 CONFIRMATION at 92.6%** against a 99.67 bar.

**The closest call, and the only clause-1 pass anywhere in the program:**

> **#226 (F4 euphoria-fade suppression), CONFIRMATION** — `ex_best` positive
> on **all three** tickers (BTC +0.059, ETH +0.131, SOL +0.121; folds 3/4,
> 4/4, 3/4), pooled **+0.193 across 434 trades / 52 episodes**. It clears
> clause 1 outright and lands at the **92.6th** placebo percentile. It needed
> 99.67. **It fails, and its DISCOVERY half is −0.053 at the 46th
> percentile** — so even the near-miss does not survive both windows.

**Depth did not fix what depth was supposed to fix.** #172–#186 registered a
power warning for its 12-month C1 window: *"a real but modest edge will
likely read as unmeasurable or fail."* This program ran on **5.05 usable
years — five times C1** — and **24 of 30 cells still have at least one
undefined `ex_best`.** Only six cells are fully computable: #220 both
windows, #226 both windows, #227 DISCOVERY, #229 DISCOVERY.

The binding constraint is not window length. It is **event rate**:

| | median pooled trades per cell |
|---|---|
| standalone tests | **100** |
| overlay tests | **6** |

**Overlays are structurally starved, and that is a property of the design,
not of the data.** An overlay fires only where the incumbent already
signalled AND the funding condition holds. The incumbent's BUY days are
sparse; intersecting them with a conditional funding state leaves single
digits — #223 CONFIRMATION and #232 both windows produced **one trade or
none**. Five more years would not repair this; a 5× longer window multiplies
6 trades into 30, still under the 10-per-fold × 3-fold bar. **The overlay
half of this program was unmeasurable by construction, and that is now
measured rather than suspected.**

**Three cells produced literally zero events:** #223, #233 and #234 on
CONFIRMATION. F8 requires funding negative for 168 consecutive hours; across
2023-10 → 2026-01 that never once occurred on any of the three symbols. That
is a factual statement about the regime, not a defect.

## Consequences, as registered

- **No promotion. `docs/claims.md` unchanged** — still zero supported edge
  claims.
- **No re-runs, no looser bar, no partial credit.** #226's 92.6% is recorded,
  not banked. "Almost" is a failure, as the inherited text says.
- **No new funding hypothesis may be registered as a variation of a failed
  one.** That inherited clause binds here.
- **This does NOT close the funding question.** #172–#186 remains **sealed,
  unmodified and pending**, trigger unchanged at ~2027-06-27, as the
  independent cross-venue test. Its own closure clause — failure at *its* C2
  — is what closes funding, and this document does not amend it.
- **A result here does not license editing #172–#186 in either direction**,
  and the cross-venue flag firing on all three symbols is a reason to value
  that independence more, not less.

---

# CLOSE-OUT — BINANCE FUNDING (#220–#234)

Closed 2026-08-31. **0 of 15 pass.** Full verdict table above, under
*BINANCE FUNDING RESULT — #220–#234*; raw in `research/h220_results.json`.

Three findings outlive the program and are recorded as permanent record.

## Finding 1 — axis 4 measures the centre, and the verdict lives in the tail

Axis 4 (correlation inheritance) read **−0.0029 / −0.0022** — effectively
zero on both windows. That is **not** a clean bill of health for the null,
and recording it as one would be the comfortable mistake.

The axis compares the null's **distribution CENTRE** against a matched
random draw. #167 chose the episode-matched null for a different reason
entirely: independent-day placebos are structurally lower-**VARIANCE** on
clustered signals. Centre and width are different properties, and **every
pass condition in this project that cites a percentile is decided in the
TAIL** — here the 99.6667th, where width is nearly the whole story.

So the four axes as they stand can certify that a null is not *displaced*,
and cannot certify that it is not *too narrow or too wide*. A percentile
verdict therefore carries an **uncharacterized tail-width caveat**, on every
program run so far, not just this one.

**This is a limitation of the instrument, recorded, not repaired here.**
Building a width axis is a methods program with its own registration, and
inventing one now — after seeing that fifteen tests failed on tail
comparisons — would be exactly the move this record forbids. Added to the
standing methodology in `CLAUDE.md` so no future program cites a percentile
as if the tail were validated.

## Finding 2 — THE OVERLAY-UNMEASURABILITY LAW

**Overlays on incumbent BUY days are unmeasurable by construction, and the
arithmetic settles it rather than the sample.**

`ex_best` requires **≥3 folds each carrying ≥10 trades**, i.e. **≥30 trades
per ticker per window**. Measured across this program's 90 ticker-window
cells:

| mode | cells | median trades | mean | max | cells reaching 30 |
|---|---|---|---|---|---|
| **overlay** | 42 | **1.0** | 4.9 | 36 | **2 (5%)** |
| standalone | 48 | 33.5 | 62.7 | 285 | 24 (50%) |

**The overlay median is ONE trade per ticker per window.** Reaching the
30-trade floor from a median of 1 requires **30× the data — roughly 75 years
per window.** No crypto asset has existed that long, and Binance's archive
floor is 2020-01.

The mechanism is structural, not incidental. An overlay fires only where the
incumbent **already** signalled **AND** a conditional state holds. The
incumbent's BUY days are sparse; a funding condition that is true a minority
of the time intersects them to near-nothing. Three cells produced **zero**
events; six produced **one**.

> **THE LAW: a future overlay registration on incumbent BUY days is REFUSED
> on measurability grounds unless it first demonstrates, from event counts
> alone and before any scoring, that it clears ≥30 trades per ticker per
> window.**

This is a refusal at registration time, not a verdict after the fact. It
costs nothing to check — event counts need no returns — and it prevents
spending a Bonferroni allocation on tests that cannot produce a result. Seven
of this program's fifteen tests were overlays, and **all seven were
unmeasurable before the first trade was scored.** They still consumed
correction budget, raising the bar for the eight that could have been
measured. That is the concrete cost of not having this law earlier.

## Finding 3 — #226's near-miss, preserved with its numbers

**#226 — F4 euphoria-fade suppression, CONFIRMATION window.** The only
clause-1 pass in the entire program:

| ticker | events | n | episodes | win% | net | `ex_best` | folds |
|---|---|---|---|---|---|---|---|
| BTC | 147 | 141 | 17 | 39.0 | +0.167 | **+0.059** | 3/4 |
| ETH | 146 | 142 | 18 | 42.3 | +0.247 | **+0.131** | 4/4 |
| SOL | 149 | 151 | 17 | 39.7 | +0.167 | **+0.121** | 3/4 |

Pooled **+0.193** over **434 trades / 52 episodes**, at the **92.6th**
placebo percentile (p95 +0.211, adjusted bar **+0.305**).

**It fails.** And its DISCOVERY half is **−0.053 at the 46.1st percentile** —
so it does not merely miss a threshold, it fails to survive its other window.

> **The no-variations rule binds here, inherited verbatim from #172–#186: no
> new funding hypothesis may be registered as a variation of a failed one.**
> Not F4 at percentile 85 instead of 90. Not F4 on CONFIRMATION alone. Not F4
> with a different high-water lookback. A genuinely new idea needs a new
> program with its own justification, and inherits this record.

The numbers are preserved precisely so the temptation is legible. #226 is the
best funding result this project has, it is a failure, and both statements
are true at once.

## The cross-venue flag — measured grounds for #172–#186's independence

The inherited flag **fired on all three symbols**: Pearson against Kraken
**+0.452 / +0.371 / +0.719**, bar 0.80. It came in **below** the Spearman
(+0.595/+0.512/+0.492) that prompted the advance disclosure — the venues
agree on ranks more than on levels.

**This is the strongest available argument for leaving #172–#186 sealed.**
Two feeds of "the same" quantity correlate at 0.37–0.72 on daily means. A
result measured on one is therefore **not** a proxy for the other, which is
precisely what an independent cross-venue confirmation is for. Had the
correlation been 0.95, running the Kraken program later would have been
largely redundant; at 0.37 it is not.

**#172–#186 stays SEALED and UNMODIFIED**, trigger unchanged (span ≥ 22
months, expected **~2027-06-27**), C1/C2 unchanged. **This program neither
opens, amends, consumes, satisfies nor substitutes for it**, and a failure
here does not license narrowing it or abandoning it.

## Status

**Funding-at-Binance-daily is CLOSED for this rule family** — the eight
rules F1–F8 in both modes, at daily granularity, on Binance USD-M, over
5.05 usable years. Closed means: no re-runs, no looser bar, no partial
credit, no variations.

**The funding QUESTION is not closed.** Its closure clause lives in
#172–#186 and is triggered by failure at *that* program's C2, on a different
venue, on data that does not yet exist.

`docs/claims.md` is unchanged and still holds **zero supported edge claims**.

---

# PRE-REGISTRATION — POSITIONING (#235–#242) and OI/BASIS (#243–#248)

> **LOCKED 2026-09-01, approved as drafted with no amendments.** Research
> rule 4 now applies to every constant below: no parameter, threshold,
> control or pass condition may change on the basis of a result.
>
> **Both programs are DORMANT.** Neither may run before its own measured-span
> trigger, and neither trigger can fire before 2028.

---

## §0. THE MIXED-DEPTH DECISION — made now

The two sources have **different clocks**. OKX rubik arrived with **180 days
already banked** (its archive reaches back to 2026-03-05, six months before
collection started); Kraken tickers has **zero banked** and begins at
2026-09-01. Pooling them into one program would force a single fold grid,
and the youngest source would govern.

> **DECISION: SEPARATE PROGRAMS — own Bonferroni, own trigger, own windows.**
>
> **Why, in one sentence:** pooling would make the older source wait six
> months for the younger and discard banked days that cannot be re-bought,
> for no statistical gain, because the two measure different mechanism
> classes and share no hypothesis.

Consequences, stated so neither is discovered later:

- **Neither program's result may be cited as confirmation of the other.**
  They are separate families with separate corrections, not two windows on
  one claim.
- **Running A first cannot inform B.** B's constants are fixed in this
  document, before A has produced anything.

---

## §1. SHARED CLAUSES — identical in both programs

### 1.1 The event-count precheck — A GATE, NOT A PREVIEW

Both programs run a precheck **before any scoring**, whose entire output is
a gate.

**What it computes.** For every hypothesis, per ticker, per window: the
number of **confirmed trade days** the rule's own definition produces —
derived from the **signal definitions and the calendar structure ONLY**.

**What it may touch:** the collected positioning series, the daily calendar,
the eligibility mask, `confirm_days = 2`, and the fold boundaries.

**What it may NOT touch:** prices, returns, `pnl_r`, `pnl_r_net`, exit
levels, or any join to the incumbent's outcome data. **No return series is
loaded.** If implementing it requires a price column, the implementation is
wrong.

**The gate:**

> A hypothesis producing **fewer than 30 confirmed trades per ticker per
> window** (the `ex_best` floor: ≥3 folds × ≥10 trades) is marked
> **UNMEASURABLE-BY-CONSTRUCTION** and **NEVER RUNS.** It is reported as
> such, with its counts, and it is not scored, not placebo-drawn, and not
> assigned a verdict.

**This is a gate, not a preview.** Its output is binary per hypothesis:
runs, or does not. It produces no expectancy, no ranking, no ordering, and
nothing from it may inform how a surviving hypothesis is scored.

**The correction does NOT shrink when the gate removes hypotheses.**
Bonferroni uses the **registered k below, unchanged**, however many survive.
Removing an unmeasurable hypothesis must never loosen the bar for the
survivors, and this clause exists so that it cannot.

*Origin: #220–#234 measured overlays at a median of ONE trade per ticker per
window, 2 of 42 cells reaching 30. Seven of its fifteen tests were
unmeasurable before the first trade was scored and still consumed correction
budget. This gate is that lesson made procedural.*

### 1.2 The adjudicating null — NAMED NOW

**Episode-matched placebo, 3,000 seeds**, per the #167 construction: per
ticker, take the observed run-lengths of consecutive event days, draw the
same NUMBER of runs with the same LENGTHS at random non-overlapping start
positions in the same window, apply the same confirm rule. Independent-day
placebos are **forbidden** — positioning regimes are persistent, so a
scattered placebo is structurally lower-variance than what it benchmarks.

**All four fidelity axes are measured before any draw is scored**, with axis
3 marked N/A (an event series has no exposure budget) and axis 4 quantified.

**The axis-4 caveat, carried verbatim from the standing methodology:**

> **THE FOUR AXES CERTIFY THE CENTRE, NOT THE TAIL.** Axis 4 compares the
> null's distribution CENTRE against a matched random draw. It cannot say
> whether the null is too NARROW or too WIDE — and every percentile pass
> condition in this project is decided in the TAIL, where width is nearly
> the whole story. So every percentile verdict this project has issued
> carries an **UNCHARACTERIZED TAIL-WIDTH CAVEAT.** State it when citing
> one.

**Alternate null family: time-rotation is INFEASIBLE at these windows and is
not substituted.** It requires a circular shift drawn from `[24 months,
T − 24 months]`, which is empty for any window under 48 months. Both
programs run a **12-month usable window** split into DISCOVERY and
CONFIRMATION, so every window here is far below the bound. Stated with the
number that makes it infeasible, per standing law, rather than quietly
replaced with something that would run.

### 1.3 Window construction

**22 months of measured span = 6 lockbox + 4 burn-in + 12 usable.** The
lockbox is the last 6 months of whatever the archive holds at trigger time.
The usable remainder splits DISCOVERY / CONFIRMATION at the project standard
`DISCOVERY_FRAC = 0.55`. Folds are **4 equal-duration time splits** per
window.

### 1.4 Standing rules inherited unchanged

`ex_best` requires ≥3 folds of ≥10 trades; **undefined `ex_best` is
UNMEASURABLE and CANNOT PASS** — the absence of a result, never a failure.
Scoring through `research/harness.py` into
`pipeline.evaluate_geometry_folds` with `LIVE_GEOMETRY`, 2 bps fee + 2 bps
slippage per side. **Long side only.** Single confirmation, no re-runs, no
partial credit, no looser bar. Negatives reported with the same detail as
positives.

**STANDALONE ONLY. No overlays in either program** — excluded by the
overlay-unmeasurability law rather than spending correction budget on tests
that cannot produce a result.

### 1.5 Alignment — the no-lookahead rule

A positioning value stamped at or before day **D**'s last observation is
known at D's daily close. A rule firing on day D is a daily BUY event on D,
which the harness labels on D and D+1, confirms at D+1 under
`confirm_days = 2`, and enters at the close of D+1. Identical to the Step 3
lagged broadcast and to #220–#234.

---

# PROGRAM A — POSITIONING (#235–#242), OKX rubik

> **LOCKED and DORMANT.** Trigger ~2028-01-05.

## A1. Data

`data/derivatives/okx_rubik.csv`, currencies **BTC / ETH / SOL**, columns
`long_short_ratio`, `taker_buy_vol`, `taker_sell_vol`, `open_interest`,
`volume`.

**These are OKX's OWN published 1D buckets, stamped 16:00 UTC** — a
venue-computed daily series, **not** a sample we take. The snapshot caveat
in DRAFT B does **not** apply to this program, and the two must not be
described in the same terms.

**Window: a hard 180 days, verified not assumed.** `after=<2020>` returns
the same 180 rows; `begin=<2020>` returns zero. Nothing older is
back-fillable at any price. Collection re-pulls the full window daily and
merge-dedupes on `(symbol, timestamp)` with existing rows winning.

## A2. Trigger — measured span on THIS source

> **Runnable when `okx_rubik.csv` spans ≥ 22 months for all three currencies**,
> measured `max(timestamp) − min(timestamp)` per currency.

| quantity | value |
|---|---|
| archive earliest (all three) | **2026-03-05** |
| banked at first collection | **179 days**, free |
| **expected trigger** | **2028-01-05** |

**Its clock started six months before ours.** The 180 banked days are why
this program triggers roughly six months ahead of DRAFT B, and they are the
concrete reason the sources were not pooled.

**The trigger is on measured span, not the calendar date.** If the collector
misses days the date slips and the span condition still governs.

## A3. Hypotheses — #235–#242, 8 rules, standalone only, every constant fixed

Definitions are conventional positioning constructions. **None may be
changed.**

| # | rule | definition |
|---|---|---|
| **#235** P1 | crowded long | BUY when the trailing **30-day percentile rank** of `long_short_ratio` is **≥ 90** *(contrarian: the crowd is long)* |
| **#236** P2 | crowded short | BUY when that percentile rank is **≤ 10** |
| **#237** P3 | taker capitulation | BUY when the 30-day percentile rank of **taker sell share** = `taker_sell_vol / (taker_buy_vol + taker_sell_vol)` is **≥ 90** |
| **#238** P4 | OI unwind | BUY when the **7-day change in OKX's published 1D `open_interest`** is **≤ −10%** |
| **#239** P5 | OI build | BUY when that 7-day change is **≥ +10%** |
| **#240** P6 | ratio z-score | BUY when the **30-day z-score** of `long_short_ratio` is **≤ −2.0** |
| **#241** P7 | put/call extreme | BUY when the 30-day percentile rank of the OKX option **put/call OI ratio** is **≥ 90** |
| **#242** P8 | divergence | BUY when `open_interest` rises **≥ 5%** over 7 days **AND** `long_short_ratio` falls over the same 7 days |

**Fixed definitions.** Percentile rank = `rolling(30).rank(pct=True) * 100`
including today. Z-score = `(x − rolling_30_mean) / rolling_30_std(ddof=0)`,
including today; NaN days do not fire. 7-day change = `x / x.shift(7) − 1`
on the daily series. A day missing any input is **excluded** from every rule
and from every lookback, and the count of excluded days is reported per
currency.

**#241 (P7) depends on a shorter series.** The OKX put/call OI ratio window measured
**~72 days**, not 180, so P7's usable history is shorter than P1–P6's. It is
**expected to be the first hypothesis the §1.1 gate removes**, and that is
recorded now rather than discovered at trigger time.

## A4. Bonferroni

**8 registered tests** → alpha = 0.05 / 8 = **0.00625** → required percentile
**99.375**. 3,000 seeds put ~19 draws above it; p95 reported alongside from
the same draws.

**k stays 8 regardless of how many survive the §1.1 gate.**

## A5. Pass conditions

On the single confirmation run, **both required**:

1. **`ex_best` > 0 on ALL THREE currencies**, and defined on all three.
2. **Pooled `net_all` above the Bonferroni-adjusted placebo percentile
   (99.375th).**

## A6. Reported whatever the outcome

Per test and per currency: `n`, **episodes**, win%, `net_all`, `ex_best`,
folds counted/positive, placebo p95 and p99.375, the observed percentile,
all four fidelity-axis measurements with the axis-4 caveat attached, days
excluded per currency, and the §1.1 gate table with every hypothesis's
confirmed-trade counts.

---

# PROGRAM B — OPEN INTEREST & BASIS (#243–#248), Kraken tickers

> **LOCKED and DORMANT.** Trigger ~2028-07-01.

## B1. Data — and the snapshot caveat that governs every OI clause

`data/derivatives/kraken_tickers.csv`, symbols **PF_XBTUSD / PF_ETHUSD /
PF_SOLUSD** (all ~294 instruments are stored; only these three are used
here).

> **EVERY ROW IS A ONCE-DAILY POINT SNAPSHOT taken at collector run time —
> nominally ~05:20 UTC via `derivs-collect.yml`. It is NOT a daily mean,
> close, median or VWAP of anything.**

The merge key is the snapshot **day**; the true instant is preserved in
`observed_utc`. The endpoint is **current-only** — there is no history and
no public archive — so what is not sampled is gone, and a daily average of
these quantities **cannot be recovered from this file at any later date**.

**Consequently every hypothesis below is worded against "the ~05:20 UTC
snapshot" and never against "daily OI".** If a future write-up describes any
result here as a statement about daily open interest, it is misdescribing
the data.

## B2. Trigger — measured span on THIS source

> **Runnable when `kraken_tickers.csv` spans ≥ 22 months for all three
> symbols**, measured `max(timestamp) − min(timestamp)` per symbol.

| quantity | value |
|---|---|
| archive earliest | **2026-09-01** |
| banked at first collection | **0 days** — current-only, nothing to bank |
| **expected trigger** | **2028-07-01** |

**Six months later than DRAFT A**, because this source had nothing to
backfill. That gap is the whole content of the §0 decision.

## B3. Hypotheses — #243–#248, 6 rules, standalone only, every constant fixed

**Basis** = `(markPrice − indexPrice) / indexPrice`, computed **from the
~05:20 UTC snapshot**.

| # | rule | definition |
|---|---|---|
| **#243** B1 | basis extreme low | BUY when the trailing **30-day percentile rank** of the **snapshot basis** is **≤ 10** |
| **#244** B2 | basis extreme high | BUY when that percentile rank is **≥ 90** *(contrarian)* |
| **#245** B3 | basis sign flip | BUY on the first day the **snapshot basis** is **> 0** after **≥ 5 consecutive daily snapshots < 0** |
| **#246** B4 | OI unwind | BUY when the 7-day change in **the ~05:20 UTC `openInterest` snapshot** is **≤ −10%** |
| **#247** B5 | OI + basis divergence | BUY when **the ~05:20 UTC `openInterest` snapshot** falls **≥ 5%** over 7 days **AND** the snapshot-basis 30-day percentile rank is **≤ 25** |
| **#248** B6 | predicted-funding extreme | BUY when the 30-day percentile rank of **the snapshot `fundingRatePrediction`** is **≤ 10** |

**Fixed definitions.** Percentile rank, z-score and 7-day change
constructions identical to DRAFT A §A3. A day with **no snapshot** is
excluded from every rule and every lookback, and the excluded count is
reported per symbol. **Consecutive-snapshot counts (B3) have no gap
tolerance:** a missing day **breaks** the run, because an inferred run
across a collection gap is not an observed run.

## B4. Bonferroni

**6 registered tests** → alpha = 0.05 / 6 = **0.008333** → required
percentile **99.1667**. **k stays 6 regardless of gate survivors.**

## B5. Pass conditions

Identical to DRAFT A §A5: `ex_best` > 0 on all three symbols **AND** pooled
`net_all` above the 99.1667th placebo percentile, both windows.

## B6. Known weaknesses, recorded before collection matures

1. **Sampling, not averaging.** Stated above and repeated here because it is
   the program's central limitation: one observation per day of a
   continuously varying quantity. Aggregation noise is real and
   uncharacterised, and cannot be estimated from this file.
2. **A missed day is a hole, not a delay.** Unlike every rolling-window
   source, there is no next-run self-heal. B3's no-gap-tolerance rule makes
   that cost explicit rather than hiding it.
3. **`fundingRatePrediction` is a venue forecast, not a realised rate.** B6
   tests the venue's own published expectation, which is a different object
   from the settled funding in `kraken_funding.csv`, and results must not be
   compared across the two as though they measured the same thing.

---

## §2. BUDGET AND CLOSURE — both programs

- **These lists are the whole programs.** A: #235–#242, 8 rules. B: #243–#248, 6 rules. No
  additions, no variations of a failed rule, no re-runs, no second look at a
  looser bar.
- **No parameter may be tuned.** Every number is in this document.
- **Nothing here is promoted to the live path.** There is no positioning
  live path and none is proposed.
- **Both inherit the strongest property this project can confer —
  REGISTERED BEFORE THE DATA EXISTS.** Only #172–#186 currently holds it;
  #220–#234 explicitly could not claim it. The usable windows of both
  programs do not yet exist anywhere: A's beyond 180 days back, B's at all.
  **Tuning to the test set is impossible by construction, not by
  discipline** — there is nothing to tune against.
- **One honest limit on that claim:** 180 days of A's eventual burn-in
  already exist on disk today. They fall inside the **burn-in**, not the
  usable window, and no rule is scored on them — but the claim is
  "registered before the *test* data exists", and that is the precise form
  it should be quoted in.

---

# PRE-REGISTRATION — MARKET-STRUCTURE MAP (#249)

> **LOCKED 2026-09-01, before any measurement was computed.**
>
> **DESCRIPTIVE PROGRAM. No hypotheses, no pass conditions, no verdicts, no
> thresholds, no signals.** Nothing here can pass or fail. Its sole product
> is a map.

## What this is, and why it is the last of its kind

Every search program on the frozen data is run and closed. This is **the last
construction available on data that already exists** — and it is deliberately
not a search. It measures **structural properties of the market**, with
uncertainty attached, and stops.

**Why bother, given the record.** Every failed program searched for an edge
directly. None asked what this market's structure actually *is* — whether
volatility clusters and for how long, whether a cross-section exists to
select from, whether BTC leads the alts at any horizon. Those are facts about
the market, not claims about a strategy, and they are measurable without any
return-vs-signal join.

**The catch, stated first because it governs everything below.** A document
with hundreds of measured cells **will contain chance patterns**. That is
arithmetic, not pessimism. It is precisely why this map buys **exactly one**
hypothesis and not many.

## THE ONE-HYPOTHESIS RULE

> **At most ONE future registered hypothesis (#250) may be drawn from this
> map**, and it may be tested **only on data timestamped AFTER this map's
> freeze** — the forward archives, accrued shadow episodes, or a future
> dataset refresh.

Consequences, all binding:

- **#250 inherits the registered-before-the-test-data-exists property
  automatically**, because its test data does not exist on the day the map is
  read. That is the entire architecture of this program: a map on old data,
  buying a hypothesis on data not yet collected.
- **The map may NEVER be cited as evidence of an edge.** Not as support, not
  as partial support, not as "consistent with". Its only legitimate use is as
  **the reason a hypothesis was worth registering.**
- **One is a hard budget, not a starting allowance.** A second interesting
  pattern is not a second hypothesis. If two look compelling, one is chosen
  and the other is recorded as forgone.
- **#250 must be registered before it is scored**, with full discipline: named
  null, four fidelity axes, its own Bonferroni, the event-count gate, fixed-k.
  Nothing about being map-derived relaxes anything.

## SCOPE — these eight measurements and no others

**Adding a measurement is an AMENDMENT made before running, never during.**
Discovering mid-run that a ninth cut would be interesting is exactly the
move this clause forbids.

All on **pre-lockbox frozen data only**. The lockbox opens **2026-02-26** and
**is never read** — not for fitting, not for plotting, not for a sanity
check.

| data | span used |
|---|---|
| BTC / ETH 1h + 4h | 2019-09-23 → 2026-02-25 |
| SOL 1h + 4h | 2020-09-18 → 2026-02-25 |
| daily basket, tradable-26 | to 2026-02-25 |

| # | measurement |
|---|---|
| **M1** | **Volatility clustering** — autocorrelation decay of \|returns\| at 1h/4h/1d; half-life per ticker with block-bootstrap CIs. |
| **M2** | **Jumps** — frequency and size of bar returns beyond 3× and 5× trailing ATR against a diffusive expectation; clustering of jump days. |
| **M3** | **Return autocorrelation** — lags 1–30 at 1h/4h/1d with heteroskedasticity-robust bands from a block bootstrap. |
| **M4** | **Cross-asset lead-lag** — BTC-leads-alt cross-correlation at 1h, lags 0–24, per volatility-regime tercile and rolling by year. |
| **M5** | **Calendar structure** — hour-of-day and day-of-week return and volatility with CIs; the **00/08/16 UTC funding-settlement hours reported separately**. |
| **M6** | **Cross-sectional dispersion** — rolling average pairwise correlation and return dispersion of the tradable-26: when does a cross-section exist to select from. |
| **M7** | **Asymmetry** — up-move vs down-move size and duration; drawdown depth vs recovery-time distributions. |
| **M8** | **Tradability drift** — flat-bar share and median stop fraction over time per basket ticker (#167's measure, as a time series). |

**M4 is the classic niche-root candidate and is measured, not assumed.** "BTC
leads the alts" is folklore this project has never tested; the map states
what the correlation actually is, at which lags, in which regimes, with
bands.

**M6 is the ROTATION context, measured.** ROTATION assumed a cross-section
existed to select from. M6 measures when one did.

## RULES — binding on every cell

1. **Every number carries a CI, or is explicitly labelled a RAW COUNT.** No
   bare point estimate is permitted anywhere in the output.
2. **No threshold is tuned toward significance.** Every cutoff (3×/5× ATR,
   terciles, lag ranges, block lengths) is fixed in this registration and
   stated in the output with its rationale.
3. **No return-vs-signal joins.** This is structure, not signals. Nothing
   here is scored through the trade machinery, no rule is evaluated, no
   expectancy is computed.
4. **The block bootstrap's block length is stated with its reason** wherever
   used, and the same choice is applied consistently.
5. **The multiple-comparisons caveat is carried on the document itself**, not
   buried per table: this map contains hundreds of cells and some will look
   remarkable by chance.

## Bootstrap specification — fixed here

**Moving-block bootstrap, 1,000 resamples**, block length
**ℓ = ⌈n^(1/3)⌉** on the series being resampled.

`n^(1/3)` is the rate-optimal block length for a sample mean under weak
dependence (Hall–Horowitz–Jing). It is fixed **before** seeing any result so
that no band can be widened or narrowed after the fact. Where a statistic is
computed on |returns| — whose dependence decays slowly — the same rule
applies and the resulting bands are, if anything, **too narrow**; that
direction is stated beside those cells rather than corrected by choosing a
more flattering ℓ.

CIs are **percentile intervals at 95%** (2.5th / 97.5th) unless a cell says
otherwise.

## Output

`docs/market_structure.md` — tables plus **a plain-language reading per
measurement**, stating what was measured, what the numbers say, and what they
do not say.

## Closure

- **This list is the whole program.** Eight measurements, one document.
- **No verdicts.** Nothing here passes, fails, or is promoted.
- **`docs/claims.md` cannot change as a result of this program.**
- **The budget is one hypothesis, #250**, drawn afterwards, tested only on
  post-freeze data, and registered with full discipline before it is scored.

---

# CLOSE-OUT — MARKET-STRUCTURE MAP (#249)

Closed 2026-09-01. The map stands as committed, **with its three defect
corrections and their labels intact** — the simulated M2 benchmark, M1's
half-life column labelled a raw bootstrap range rather than a CI, and M8's
restored intervals. Those corrections are part of the record, not errata to
be tidied away.

## DISPOSITION: no #250 is drawn from this map

**The one-hypothesis slot is NOT spent. It is BANKED.**

Taken measurement by measurement, against the standard that a hypothesis must
have a plausible entry mechanism this project has not already tested:

| measurement | what it showed | why no hypothesis follows |
|---|---|---|
| **M4** lead-lag | **The leading candidate, measured as ABSENT.** Contemporaneous ρ = +0.822 (ETH) / +0.611 (SOL); every lag 1h–24h within ±0.031 of zero, in every vol tercile and every year. | There is nothing to build on. A contemporaneous correlation is not a lead, and a lead is what a rule would need. This is the cleanest negative in the map. |
| **M1** vol clustering | Real, strong, and canonical: \|return\| ACF +0.16…+0.30 at lag 1, still positive at lag 20. | **Its monetisation was already tested and failed.** Scaling exposure to predicted volatility is ALLOCATION #193–#196, which failed on both windows, and whose inverted control cleared the same clause. Re-entering through M1 would be a variation of a failed rule. |
| **M2** jumps | Real and large: observed rates 2–3 orders of magnitude above a matched diffusive benchmark, and jumps cluster. | **No entry mechanism.** It says the SIZE distribution has fat tails and that tails cluster — a property of the risk, not a signal about direction or timing. Nothing here says which side of a jump to be on, or when. |
| **M3** return autocorrelation | 0–3 of 30 lags exclude zero per series, against **~13–14 expected by chance** across 270 cells. | **Chance-consistent.** Fewer significant lags than chance alone would produce. There is no pattern to register. |
| **M5** calendar | Reported with CIs; 93 cells, ~5 expected to exclude zero by chance. | Nothing survives that arithmetic as a candidate. |
| **M6** dispersion | ρ̄ 0.479–0.707, varying materially by year. | **Context, not a signal.** Cross-referenced into NULL-CALIBRATION as the empirical input governing inheritance contamination — which is what it is for. |
| **M7** asymmetry | Up/down runs differ; drawdowns recover slower than they form. | Structural context for the geometry and for the short-side record. Not a timing rule. |
| **M8** tradability | Zero tickers under the 0.80% cost floor in any year; the #167 filter's measure is stable. | Confirms an instrument property. #163–#167 already scored the filtered basket and it failed. |

**The honest summary: the map found one thing worth knowing that it did not
already know — that the BTC-leads-alts folklore is false at 1h — and that
finding is a NEGATIVE.** Everything else is either canonical structure whose
monetisation this record has already tested and rejected, or chance.

## Why banking is the right disposition, not a failure of nerve

The one-hypothesis rule exists because a map of several hundred cells will
contain chance patterns. **Spending the slot on the most interesting-looking
cell is exactly the behaviour the rule was written to prevent.** A slot spent
badly is worse than a slot unspent: it consumes the single opportunity this
map confers, on a hypothesis with no mechanism behind it.

**The slot remains available to either of two things, and to nothing else:**

1. **A future map built on POST-FREEZE data** — the forward archives, accrued
   shadow episodes, or a dataset refresh. Such a map is a new descriptive
   program requiring its own registration.
2. **A mechanism argument that survives checking against THIS map.** If a
   reason to expect an effect is articulated first — from theory,
   microstructure, or a venue-behaviour argument — this map can be consulted
   to see whether it is consistent with what was measured. That direction is
   legitimate: mechanism first, map as a check. The forbidden direction is
   pattern first, mechanism invented afterwards.

**The slot does not expire, and it does not accumulate.** One remains one.

## What may and may not be said about this map

- **It may never be cited as evidence of an edge.** Not as support, not as
  partial support, not as "consistent with".
- **M4's negative MAY be cited** — as a measured absence, which is what it
  is, and which is the map's most useful output.
- **`docs/claims.md` is unchanged** and could not have been changed by this
  program. The project holds **zero supported edge claims**.
- **No measurement here may be re-cut.** A ninth measurement, a different
  lag range, another tercile split: each is a new registration.

---

# REGISTRATION — SIMPLIFICATION & HARDENING PASS

> **ENGINEERING CHANGE. EXPLICITLY PERFORMANCE-SILENT.**
>
> **This registration makes no claim that the simplified model is better.**
> Not "expected to improve", not "should reduce drag", not "cleaner and
> therefore stronger". **No performance claim of any kind is made, implied,
> or may be quoted from this document.**
>
> **Adjudication belongs to SHADOW-EVAL's registered checkpoint at 30 pooled
> closed episodes, and nowhere else.** That checkpoint was registered before
> this change was contemplated and is not amended by it.

## Grounds — measured, and cited

Two ablation findings, both already in this record:

**#198 — Step 3 is measured HARMFUL.** Removing the indicator blend improved
BTC INC_BUY_ALL on **both** windows (+0.175R DISCOVERY, +0.119R CONFIRMATION)
and was positive at **100 of 100** window starts. It is the only ABLATION rung
that cleared the registered epsilon, and it cleared it by showing the
component **subtracts**.

**#201 — the VIX regime is UNEXERCISED BY CONSTRUCTION.** Removing it changed
expectancy by **+0.000R on both windows**, identically zero at all 50 rolling
starts in each. Not because it is dormant: VIX ≥ 35 on 80 DISCOVERY days and
10 CONFIRMATION days, changing 35 labels — but **BUY-tier membership changed
on exactly ONE day in 6.42 years** (2020-06-21), and that day was unconfirmed
so it produced no trade. Every other change was on the SELL side, which the
published long-only path never trades.

**What these grounds do NOT establish.** #198 says the component subtracts
*relative to the incumbent*; **#203 then took squeeze-only to a real bar and
FAILED** — pooled net at the 68th and 91.5th placebo percentile against a p95
bar. **Squeeze-only is not a validated edge and this change does not make it
one.** It is a simplification of a construction that has no supported edge
claim either way, on the grounds that one of its components was measured to
subtract and another was measured to do nothing.

## 1. THE CHANGE — published construction only

**Removed from the PUBLISHED signal computation:**

- **Step 3, the indicator blend.** `weight_pattern` 0.6 → **1.0**,
  `weight_indicators` 0.4 → **0.0**. The published construction becomes
  **squeeze-only**.
- **The VIX extreme-fear regime.** Direction bars are fixed at 75/60/40/25
  with no panic shift.

**Explicitly NOT removed:**

- `confirm_days = 2`, `LIVE_GEOMETRY` (4h ATR, stop 1.5, target 3.0, 15-day
  hold, SMA 50), conviction scaling, the sentiment gate, the tradability
  filter, the cost floor, the publication guards, long-only.
- **Step 3 itself, from the codebase.** It remains, and the shadow logger
  keeps calling it — see §2.

## 2. THE OLD MODEL STAYS FULLY TRACKED — the condition that makes this reversible

`shadow_basket.py` already logs **both** constructions per ticker-day:
`decision`/`direction` for the incumbent 0.6/0.4 blend, and
`sq_decision`/`sq_direction` for squeeze-only, each with its own exit levels.

> **The incumbent-blend arm MUST keep logging. Verifying that is a
> precondition of this change, not a consequence of it.**

Concretely: the shadow logger continues to call `apply_indicator_step`, so it
retains the Yahoo dependency the published path is dropping. **That is
deliberate.** If the incumbent arm stopped logging, the promotion/demotion
question would become unanswerable the moment the live path changed, and this
would be an irreversible change dressed as a reversible one.

**SHADOW-EVAL is unchanged**: same 30-episode threshold, same single
evaluation, same episode-matched placebo, same prohibition on inspecting the
log beforehand. This registration does not amend it, accelerate it, or add a
condition to it.

## 3. What changes in the LOG, stated because it affects a published document

- `indicator_final_score` and `vix_level` become **null** on new rows. The
  columns remain; `extract_episodes` already NaN-guards both, so outcome
  resolution degrades safely.
- **The short trend filter disappears from logged short rows.** It lives in
  Step 3 (`below_trend_sma`) and downgrades SELL → WATCH when price is above
  its 50-day SMA. Shorts are **never published**, so no signal changes — but
  the logged short record becomes a **different construction** from the one
  that produced the existing 0-for-11.

  **This matters because claims.md quotes that record.** From this date the
  transparency post's SHORT row mixes two constructions, and the change must
  be disclosed there rather than allowed to blur. Recorded here so it is a
  known cost, not a discovery.

## 4. claims.md gains exactly one line

> *Published construction simplified on ablation grounds [DATE]: Step 3 and
> the VIX regime removed. **No performance claim is made.** Both
> constructions remain publicly logged; adjudication is SHADOW-EVAL's at 30
> episodes.*

**No SUPPORTED entry is added, edited or removed.** The project continues to
hold **zero supported edge claims**, and this change cannot alter that.

## 5. Hardening — same pass, no performance claim either

1. **Dependency pinning**, one lockfile shared by CI and local. *(The pandas-3
   lesson: an unpinned major bumped under us and behaviour moved.)*
2. **The `mentions: None` wart** — vestigial key alongside the live
   `sentiment_mentions`.
3. **Retry-with-backoff on every external fetch in the live path that lacks
   it.**
4. **A weekly dependency-drift check in `audit.py`** — installed versus
   pinned.

## 6. What would make this change wrong, and how it would be caught

**It could be wrong.** #203 failed, so squeeze-only has no demonstrated edge;
the grounds are that one removed component was measured harmful and the other
measured inert, not that what remains works.

The catch is already registered: **SHADOW-EVAL at 30 pooled closed episodes,
evaluating both arms.** If the incumbent blend outperforms squeeze-only
there, that is the signal to revert — and it is answerable **only** because
the incumbent arm keeps logging. That is why §2 is a precondition.

**No interim read.** The shadow log may not be inspected before 30 episodes,
and this change does not create an exception.

## 7. Scope and closure

- **This is not a hypothesis and carries no hypothesis number.** It is an
  engineering change recorded for the same reason everything else here is:
  so a future reader can see what changed, when, and on what grounds.
- **No parameter below is tunable.** A different weight, a different bar, a
  partial removal — each would be a new decision requiring its own record.
- **Nothing here may be cited as evidence of anything.** Not the ablation
  numbers, not the simplification, not a subsequent good month.

---

# PRE-REGISTRATION — MACRO-OVERLAY PROGRAM (#251–#256)

> **LOCKED 2026-09-01, approved as drafted with no amendments.** Research
> rule 4 now applies to every constant below.
>
> **Two departures were explicitly endorsed and are noted as PRECEDENT:**
> (1) a provenance claim not in the written record is recorded as
> RECOLLECTION, never dressed as a citation; (2) where a partition already
> exists, fixed by seed before any result, it is REUSED rather than
> re-drawn — a new split invented later could be chosen to flatter.
>
> At lock time the overlay series did **not yet exist in this repository**.

---

## §0. THE RESTLESSNESS-RULE SENTENCE (research rule 9)

> **This program rests on macro/flow information never tested (stablecoin
> supply, rates); it does not re-open price-transformation,
> per-ticker-information, or sparse-overlay doors.**

Each clause is checkable against the record:

- **Price-transformation** — every closed program derived its signal from
  price or from a transform of price. Neither series here is a price.
- **Per-ticker information** — #163's finding was that per-ticker records are
  too thin. This program uses **one market-wide series applied to a POOLED
  construction**, which is the opposite failure mode.
- **Sparse overlays** — the overlay-unmeasurability law refuses overlays that
  cannot reach 30 trades. §3 answers it with the measured base counts, by
  arithmetic, before anything runs.

---

## §1. PROVENANCE — recorded honestly, including what is NOT in the record

**The maintainer's account:** these series were considered in an early plan
and deferred on replication grounds — one macro series cannot be replicated
across tickers the way a per-ticker signal can.

> **⚠ THAT DEFERRAL IS NOT IN THIS REPOSITORY'S WRITTEN RECORD.** Searching
> `docs/cleanroom.md`, `docs/claims.md` and `CLAUDE.md` for *stablecoin*,
> *DGS10*, *Fear & Greed*, *DefiLlama* and *FRED* returns nothing but USDC
> appearing as a basket ticker. The deferral is recorded here as **the
> maintainer's recollection, not as a citation**, because inventing a
> reference to a note that does not exist would be exactly the kind of
> tidying this project forbids.

**What later answered the objection.** The basket program (#163–#166) built a
**pooled** construction across the tradable-26. Pooling is what makes a
single market-wide series testable at all: replication moves from
*cross-ticker* to *cross-quartile within one pooled sample*. That design did
not exist when the deferral was made.

### The ledger correction

`CLAUDE.md` currently states:

> *"**THE BOARD IS SEALED.** … **Nothing further can be learned from the
> frozen dataset.**"*

**That is an overstatement and this registration corrects it.** It was true
of every axis the project had *searched* — price transformations, resolution,
architecture, components, funding-at-daily. It was not true in general:
**exogenous macro/flow series had never been joined to the frozen basket at
all.** The board was sealed against re-opening closed doors, which is the
right rule; it was written as though no doors remained, which was wrong.

On lock, `CLAUDE.md` is amended to say the board is sealed **against
re-opening closed axes**, with this program named as the exception that
proves the distinction.

---

## §2. DATA

### 2.1 Base — the frozen basket

`data/basket/*.csv.gz`, the **#167 tradable-26**, daily frames, already
frozen. Construction: **pooled INC_BUY_ALL** (the incumbent's own
BUY/STRONG_BUY days), scored through `research/harness.py` into
`pipeline.evaluate_geometry_folds` with `LIVE_GEOMETRY` and 2bps fee + 2bps
slippage per side — identical to #164.

### 2.2 Overlay series — TO BE EXPORTED AND FROZEN BEFORE ANY RULE RUNS

| series | source | endpoint | key |
|---|---|---|---|
| **(a) Stablecoin total supply** | DefiLlama | `https://stablecoins.llama.fi/stablecoincharts/all` | none |
| **(b) DGS10** — 10-year Treasury constant maturity | FRED | `https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10` | none |

**Fear & Greed is EXCLUDED and the exclusion is registered**, per the
original deferral note's reasoning: the index is **constructed from price and
volatility inputs**, so joining it to price-derived trades would be a
partially circular test. It is not a macro/flow series and does not belong in
this program.

### 2.3 EXPORT AND FREEZE PLAN — executed before any rule is scored

1. `research/export_macro.py` pulls both series **once**, full available
   history, and writes:
   - `data/macro/stablecoin_supply.csv` — `date, total_circulating_usd`
   - `data/macro/dgs10.csv` — `date, dgs10`
   - `data/macro/MANIFEST_macro.json` — per series: source URL, first date,
     last date, row count, **sha256**, and the export timestamp.
2. **The freeze is permanent for this program.** The series are never
   re-pulled, never merged, never revised. If DefiLlama restates history
   later, this program keeps the frozen copy and the sha256 proves which one
   was used. *(DefiLlama's supply series is a reconstruction and can move;
   FRED revises rarely but does revise.)*
3. **Lockbox.** The frozen macro series are truncated at the basket's lockbox
   boundary at analysis time, exactly as every other series is. **The lockbox
   is never read.**
4. **A gap census is reported before scoring** — missing days per series,
   longest gap — and stated beside the results.

### 2.4 Alignment — the standard no-lookahead broadcast

> **A series value known at day D applies from D+1 onward.**

Identical to the Step 3 lagged broadcast (#168–#170) and to #220–#234.

**DGS10 needs one extra rule, fixed here.** FRED publishes business days
only; crypto trades every day. **The last published value is carried forward
across weekends and US holidays, then broadcast D+1.** No interpolation, no
back-fill. A carried-forward value is the most recent *known* value, which is
what a trader would have had.

**Stablecoin supply is daily and needs no carry-forward**; any genuinely
missing day is carried forward under the same rule and counted in the census.

---

## §3. THE OVERLAY-UNMEASURABILITY LAW, ANSWERED BY ARITHMETIC

The law refuses any overlay that cannot reach `ex_best`'s floor of **≥3 folds
× ≥10 trades = 30 trades**. Here are the **measured** base counts, from
#164's recorded results (tradable-26 / INC_BUY_ALL):

| window | pooled trades | pooled episodes |
|---|---|---|
| **DISCOVERY** | **1,678** | 496 |
| **CONFIRMATION** | **2,414** | 661 |

**A regime gate must retain 30 of those to stay measurable:**

- DISCOVERY: **30 / 1,678 = 1.79%**
- CONFIRMATION: **30 / 2,414 = 1.24%**

**Every rule in §4 is a binary regime gate that is true on well over half its
window by construction** (a sign condition, a tercile, a level-vs-mean). None
is remotely near a 1.8% retention rate. **The law is satisfied by arithmetic,
not by hope** — which is exactly what it demands, and exactly what #220–#234's
seven unmeasurable overlays failed to demonstrate.

**The quartile replication condition is the tighter constraint.** Each of the
four quartiles must also clear 30 trades. Pooled quartiles are roughly
1,678/4 ≈ 420 (DISCOVERY) and 2,414/4 ≈ 600 (CONFIRMATION) **before** gating,
so a gate retaining ~7% keeps every quartile measurable — but quartiles are
unequal and this is an approximation.

> **Therefore the event-count precheck is MANDATORY and runs first**, per the
> standing gate rule: confirmed-trade counts per quartile per window per
> rule, computed from **signal definitions and calendar structure only, never
> from returns**. Any rule below 30 in any quartile-window is marked
> **UNMEASURABLE-BY-CONSTRUCTION and does not run.**
>
> **Bonferroni k stays at the registered value regardless** (the fixed-k gate
> law): a gate removes chances at a false positive, it never cheapens the
> remaining ones.

---

## §4. HYPOTHESES — six regime gates, every constant fixed

Each is a **regime gate on pooled INC_BUY_ALL**: *the trade is taken **iff**
the regime is true on its entry day.* No rule changes entry, exit, sizing or
geometry — only whether the pooled trade is included.

| # | rule | definition — all numbers final |
|---|---|---|
| **#251** | stablecoin expansion | Take the trade **iff** the **30-day change in total stablecoin supply is > 0**. *(Liquidity expanding.)* |
| **#252** | stablecoin top tercile | Take **iff** the 30-day stablecoin growth rate is in the **top tercile of its trailing 365 days**. |
| **#253** | stablecoin bottom tercile | Take **iff** it is in the **bottom tercile of its trailing 365 days**. *(Registered as the mirror of #252: if expansion helps, contraction should not.)* |
| **#254** | rates easing | Take **iff** the **3-month change in DGS10 is < 0**. |
| **#255** | rates below trend | Take **iff** the **DGS10 level is below its trailing 200-day mean**. |
| **#256** | both easing | Take **iff** #251 **AND** #254 both hold. *(The conventional joint liquidity condition.)* |

**Fixed definitions.** 30-day change = `x / x.shift(30) − 1` on the daily
series. Tercile rank = `rolling(365).rank(pct=True)`, top = **≥ 2/3**, bottom
= **≤ 1/3**, including today. 3-month change in DGS10 = `x − x.shift(63)`
(63 carried-forward daily observations). 200-day mean = `rolling(200).mean()`.
A day whose regime value is undefined (NaN, warm-up) **excludes the trade**
and is counted. **Long side only.**

**#253 is a control in hypothesis clothing and is counted as a test.** If
both #252 and #253 pass, the result is exposure or regime persistence, not
liquidity — and that reading is registered now.

---

## §5. EVALUATION

**Windows:** BOTH, the basket program's own DISCOVERY and CONFIRMATION.
**Folds:** 4 equal-duration splits per window.

**Adjudicating null — named here:** **episode-matched placebo, 3,000 seeds**,
per #167: draw the same NUMBER of runs with the same LENGTHS at random
non-overlapping positions, same confirm rule. Independent-day placebos
forbidden — macro regimes are persistent, so a scattered placebo is
structurally lower-variance than what it benchmarks.

**All four fidelity axes measured BEFORE any draw is scored**, with axis 3
marked N/A (no exposure budget) and axis 4 quantified against the tradable-26
ρ̄ measured in #249's M6 (**0.479–0.707, varying by year — report ρ̄ for this
program's own windows, not one project-wide figure**).

**The axis-4 caveat, verbatim:**

> **THE FOUR AXES CERTIFY THE CENTRE, NOT THE TAIL.** Axis 4 compares the
> null's distribution CENTRE against a matched random draw. It cannot say
> whether the null is too NARROW or too WIDE — and every percentile pass
> condition in this project is decided in the TAIL, where width is nearly
> the whole story. So every percentile verdict this project has issued
> carries an **UNCHARACTERIZED TAIL-WIDTH CAVEAT.** State it when citing
> one.

**Alternate null:** time-rotation requires `[24, T−24]` months, empty below
48. Basket DISCOVERY and CONFIRMATION are both under that. **INFEASIBLE, and
stated with the number rather than substituted.**

**Bonferroni: k = 6** (the final registered test count) → α = 0.05/6 =
**0.008333** → required percentile **99.1667**. p95 reported alongside from
the same draws.

---

## §6. PASS RULES — #172 style, no partial credit

On the single confirmation run, **on BOTH windows, all required**:

1. **Pooled `net_all` > 0**, AND
2. **Pooled `net_all` above the Bonferroni-adjusted placebo percentile
   (99.1667th)**, AND
3. **REPLICATION: `ex_best` positive in ALL FOUR registered ticker quartiles,
   where defined.**

**The quartiles are the ones already registered by H-basket-C** (seed
20260827, fixed before any scoring, membership already public in this
document):

| quartile | members (∩ tradable-26) |
|---|---|
| Q1 | AAVE ALGO BTC LINK XRP |
| Q2 | ATOM AVAX BNB DOGE ETC ETH VTHO |
| Q3 | ADA BCH FET NEAR ONE SOL TRX XLM |
| Q4 | DOT GALA LTC OP UNI VET |

Reusing them is deliberate: they were fixed by seed before any basket result
existed, they are already published, and **a new split invented now could be
chosen to flatter.**

**An undefined `ex_best` is UNMEASURABLE and CANNOT PASS** — the absence of a
result, never a failure. **Single confirmation, no re-runs, no partial
credit, no second look at a looser bar.** "Almost" is a failure, as it was
for tradable-26 / INC_BUY_ALL at **0.001R**.

---

## §7. THE KNOWN WEAKNESS — stated up front, and binding anyway

> **One macro series serves all 26 tickers. Quartile replication therefore
> tests BREADTH OF EFFECT, not INDEPENDENCE.**

Cross-ticker replication in earlier programs asked whether an effect appeared
in *separately-derived* signals. Here every quartile sees **the identical
regime series on the identical days**. If the regime coincides with a good
period for crypto generally, all four quartiles go positive together —
because they were all long the same market at the same time, not because the
effect replicated.

**This is strictly weaker than cross-ticker replication, and it is the best
available for a market-wide series.** It is binding anyway:

- A market-wide regime that helps only one quartile is *worse* evidence, not
  better, so the condition still has teeth against a narrow fluke.
- The episode-matched placebo draws from the same windows, so a regime that
  is merely "a good stretch of market" competes against random stretches of
  the same market.
- **#253 is the sharper control:** if the mirror regime also passes, breadth
  has told us nothing and the registration says so in advance.

**No result from this program may be described as "replicated across
tickers."** The permitted phrasing is **"positive in all four quartiles of a
single pooled sample under one shared regime series."**

---

## §8. BUDGET AND CLOSURE

- **This list is the whole program.** Six tests, one run, both windows.
- **No rule added, edited or re-run.** No parameter tuned — every number is
  in this document.
- **No new macro hypothesis as a variation of a failed one.** A different
  lookback, tercile boundary or series is a new program with its own
  justification.
- **Nothing here is promoted to the live path** regardless of outcome.
- **This program does NOT inherit the registered-before-the-test-data-exists
  property.** The basket frames exist and have been scored before. It rests
  on the weaker guarantee: **the overlay series do not yet exist in this
  repository, and every constant is fixed before they are exported.**

**Reported whatever the outcome:** per rule and per window — pooled `n`,
**episodes**, win%, `net_all`, `ex_best`, folds counted/positive, per-quartile
`ex_best`, placebo p95 and p99.1667, observed percentile, all four
fidelity-axis measurements with the axis-4 caveat attached, the gap census,
the precheck's per-quartile trade counts, and the registered k beside the
surviving count. Negatives get the same detail as positives.
