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

