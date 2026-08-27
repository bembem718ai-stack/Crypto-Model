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
