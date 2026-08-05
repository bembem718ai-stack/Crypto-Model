"""
pipeline.py
===========
CONSOLIDATED: unified_model.py + backtest_direction.py + run_multi_ticker.py,
merged into one "orchestration + strategy" module. Depends on signal_engines.py
for the actual data/scoring (Steps 1/2/3); this file is the STRICT ORDERING,
the BUY/SELL/WATCH labelling (including the sell-side extreme_fear_mode
choice), the batch runner, and the historical backtest.

SECTIONS:
  1. UNIFIED PIPELINE   (from unified_model.py) - Step1 -> Step2 -> Step3 ->
                         combine, in enforced order. classify_direction()
                         is the bidirectional (BUY..SELL) signal; see its
                         docstring for the extreme_fear_mode choice.
  2. BATCH RUNNER        (from run_multi_ticker.py) - runs the full pipeline
                         across a ticker list, prints a summary table.
  3. DIRECTION BACKTEST  (from backtest_direction.py) - backtests Steps 1+3
                         historically (no historical Adanos sentiment on the
                         free tier, see its docstring), including
                         --compare-modes to A/B the two extreme_fear_mode
                         stances on real history before choosing one live.

CLI (subcommands; run `python pipeline.py <command> --help` for details):
    python pipeline.py run BTC [--extreme-fear-mode symmetric|risk_off] ...
    python pipeline.py multi BTC ETH SOL
    python pipeline.py backtest BTC [--compare-modes] ...

Requires: pip install requests vaderSentiment pandas numpy yfinance
"""

import sys
import time
import argparse
import math
from datetime import datetime, timezone

import pandas as pd

import signal_engines as ads   # adanos_sentiment.* lives in signal_engines
import signal_engines as cf    # crypto_features.* lives in signal_engines
import signal_engines as epm   # entry_point_model2.* lives in signal_engines


# ======================================================================
# SECTION 1 — unified_model.py (the 3-step pipeline + decision/direction)
# ======================================================================

# ======================================================================
# STEP 1 — INITIAL SCORING (squeeze/pattern detection)
# ======================================================================

def compute_initial_score(ticker: str, interval: str = "4h", klines_limit: int = 500,
                           bb_period: int = 20, percentile_lookback: int = 120,
                           squeeze_threshold: float = 0.2, max_duration_for_scaling: int = 40) -> dict:
    """
    STEP 1. Pulls recent klines (no funding/long-short-ratio needed here —
    those aren't part of the validated squeeze pattern), computes the
    squeeze features, and converts the latest reading into a 0-100 score.

    Formula (documented, tunable):
        coil_component     = (1 - BB_WIDTH_PCTL) * 70   -> tighter coil = higher
        duration_component = min(SQUEEZE_DURATION / max_duration_for_scaling, 1) * 30
        initial_score       = coil_component + duration_component, clipped 0-100

    A price that's both unusually tight (low BB_WIDTH_PCTL) AND has been
    that way for a while (high SQUEEZE_DURATION) scores highest — the
    "coiled spring, been coiling a while" setup.
    """
    symbol = cf.to_binance_symbol(ticker)
    klines = cf.fetch_klines_paginated(symbol, interval=interval, target_bars=klines_limit)
    squeezed = cf.add_squeeze_features(
        klines, bb_period=bb_period, percentile_lookback=percentile_lookback,
        squeeze_threshold=squeeze_threshold,
    )

    valid = squeezed.dropna(subset=["BB_WIDTH_PCTL"])
    if valid.empty:
        raise ValueError(f"Not enough klines history to compute squeeze features for {ticker}. "
                          f"Try a larger klines_limit.")

    latest = valid.iloc[-1]
    bb_pctl = float(latest["BB_WIDTH_PCTL"])
    duration = float(latest["SQUEEZE_DURATION"])

    coil_component = (1 - bb_pctl) * 70
    duration_component = min(duration / max_duration_for_scaling, 1.0) * 30
    initial_score = max(0.0, min(100.0, coil_component + duration_component))

    # ATR (volatility) from the same klines — used later to derive exit levels.
    atr_series = cf.compute_atr(squeezed, period=14)
    atr_latest = float(atr_series.iloc[-1]) if not atr_series.dropna().empty else float("nan")

    return {
        "step": 1,
        "step_name": "initial_scoring",
        "timestamp": datetime.now(timezone.utc),
        "ticker": ticker,
        "bar_time": valid.index[-1],
        "bb_width_pctl": bb_pctl,
        "squeeze_duration": duration,
        "initial_score": round(initial_score, 2),
        "close": float(latest["Close"]),
        "atr": atr_latest,
    }


# ======================================================================
# STEP 2 — REDDIT DATA (sentiment gate, applied to Step 1's score)
# ======================================================================

# ----------------------------------------------------------------------
# LAZY SENTIMENT — skip the Adanos call when it provably cannot matter
# ----------------------------------------------------------------------
# DERIVED, NOT HARDCODED. The gate can at worst multiply the Step 1 score
# by max_dampening (0.5 on a VETO). Step 1's score enters the final score
# with weight_pattern, so the largest drop the gate can cause is
#   weight_pattern * (1 - max_dampening) * initial_score.
# Even with PERFECT indicators (100), a Step 1 score below
#   (buy_bar - weight_indicators * 100) / weight_pattern
# cannot reach the buy bar at all, so dampening it changes no BUY.
# Deriving it this way means the relationship survives future changes to
# the bar or the weights, instead of rotting into a stale constant.
#
# HONEST LIMITATION — read before enabling. This bound is sound for the
# BUY side only. On the SELL side, dampening can PUSH a score down
# across the sell bar, and whether that is possible depends on the
# indicator score, which by design is not known yet at Step 2. Measured
# against signal_log.csv (373 runs), skipping below the cutoff left
# 0.8% of runs where a maximally-bearish reading could in principle have
# created a SELL. The actual number of missed flips in that window was
# zero, because the gate never fired at all. That is a real if small
# exposure, which is why this defaults to OFF and caching (which skips
# nothing) is the default saving instead.


def sentiment_call_cutoff(buy_bar: float = 60.0, weight_pattern: float = 0.6,
                           weight_indicators: float = 0.4,
                           max_dampening: float = 0.5) -> float:
    """Step 1 score below which the sentiment gate cannot change a BUY.
    Returns 0.0 (never skip) if the weights make the bound meaningless."""
    if weight_pattern <= 0:
        return 0.0
    cutoff = (buy_bar - weight_indicators * 100.0) / weight_pattern
    return max(0.0, cutoff)


def should_call_sentiment(initial_score: float, lazy: bool = False,
                           buy_bar: float = 60.0, weight_pattern: float = 0.6,
                           weight_indicators: float = 0.4,
                           max_dampening: float = 0.5) -> tuple:
    """Returns (should_call, reason). With lazy=False always calls."""
    if not lazy:
        return True, "lazy sentiment disabled — always calling"
    cutoff = sentiment_call_cutoff(buy_bar, weight_pattern, weight_indicators,
                                    max_dampening)
    if initial_score < cutoff:
        return False, (f"Step 1 score {initial_score:.1f} is below the derived "
                       f"cutoff {cutoff:.1f}; even perfect indicators could not "
                       f"reach the buy bar {buy_bar:g}, so the gate cannot change "
                       f"a BUY. Skipped to preserve Adanos quota.")
    return True, f"Step 1 score {initial_score:.1f} >= cutoff {cutoff:.1f}"


def apply_reddit_step(ticker: str, step1_result: dict, subreddits: list = None,
                       limit_per_sub: int = 100, min_mentions: int = 15,
                       ttl_hours: float = None, lazy: bool = False,
                       buy_bar: float = 60.0, cache_path: str = None) -> dict:
    """
    STEP 2. Takes STEP 1's initial_score and runs it through the Reddit
    sentiment gate. Requires step1_result to already exist — this is
    not callable meaningfully on its own, by design, to keep the order
    honest in code as well as in principle.

    NOTE: this runs on Adanos's Reddit Crypto Sentiment API now — see
    adanos_sentiment.py's docstring for the full backstory (Reddit
    direct access, LunarCrush, and ApeWisdom were all tried first).
    This restores genuine bullish/bearish sentiment scoring (not just
    mention volume) using the same gate thresholds as the original
    design. FREE TIER IS 250 REQUESTS/MONTH — fine for occasional
    single runs, but avoid tight --loop intervals or you'll exhaust it
    fast. The `subreddits` and `limit_per_sub` params are kept for
    backwards-compat call sites but are unused by the Adanos path.
    """
    if step1_result.get("step") != 1:
        raise ValueError("apply_reddit_step() requires a valid Step 1 result — "
                          "run compute_initial_score() first.")

    initial = step1_result["initial_score"]
    call, why = should_call_sentiment(initial, lazy=lazy, buy_bar=buy_bar)
    if not call:
        print(f"  [sentiment] {why}")
        gate = {"decision": "SKIPPED", "gate_multiplier": 1.0, "reason": why,
                "cache_hit": True, "cache_age_hours": None, "stale_fallback": False}
    else:
        gate = ads.cached_sentiment_check(
            ticker, ttl_hours=ttl_hours,
            min_mentions_for_confidence=min_mentions, cache_path=cache_path)

    gated_score = ads.apply_gate_to_score(gate, initial)

    return {
        "step": 2,
        "step_name": "reddit_data",
        "timestamp": datetime.now(timezone.utc),
        "ticker": ticker,
        "gate_decision": gate["decision"],
        "gate_multiplier": gate["gate_multiplier"],
        "gate_reason": gate["reason"],
        "gate_cache_hit": gate.get("cache_hit", False),
        "gate_cache_age_hours": gate.get("cache_age_hours"),
        "gate_stale_fallback": gate.get("stale_fallback", False),
        "sentiment_score": gate.get("sentiment_score"),
        "sentiment_mentions": gate.get("sentiment_mentions"),
        "score_before_reddit": step1_result["initial_score"],
        "gated_score": round(gated_score, 2),
    }


# ======================================================================
# STEP 3 — INDICATORS/INDEXES (full technical + macro model)
# ======================================================================

def to_yahoo_crypto_symbol(ticker: str) -> str:
    """
    Yahoo Finance needs the explicit spot pair format (e.g. 'BTC-USD')
    for crypto. Bare symbols like 'BTC' or 'ETH' are NOT crypto on
    Yahoo — they're real but unrelated tickers (bare 'BTC' is the
    Grayscale Bitcoin Mini Trust ETF, bare 'ETH' is the Grayscale
    Ethereum Mini Trust ETF: correlated with spot price but NOT the
    same instrument — different hours, NAV premium/discount, expense
    drag). Passing the bare symbol doesn't error, it just silently
    fetches the wrong instrument, which is worse than a clean failure.
    Bare 'SOL' has no such accidental match and correctly 404s instead.
    """
    if "-" in ticker:
        return ticker.upper()
    return f"{ticker.upper()}-USD"


def apply_indicator_step(ticker: str, step2_result: dict, period: str = "2y",
                          use_ml: bool = False, trend_sma_period: int = 50) -> dict:
    """
    STEP 3. Runs entry_point_model2.py's full daily technical (RSI, MACD,
    moving averages, etc.) + macro (VIX, DXY) pipeline. Requires
    step2_result to already exist, same ordering-enforcement pattern as
    Step 2 requiring Step 1.

    If use_ml=True, ALSO trains an XGBoost classifier (honest chronological
    holdout) on the Yahoo-derived technical features and attaches its
    out-of-sample probability + accuracy. This is DISPLAY-ONLY — it does
    not change technical_score or final_score.
    """
    if step2_result.get("step") != 2:
        raise ValueError("apply_indicator_step() requires a valid Step 2 result — "
                          "run apply_reddit_step() first.")

    yahoo_ticker = to_yahoo_crypto_symbol(ticker)
    result_df = epm.analyze(yahoo_ticker, period=period, use_ml=use_ml)
    valid = result_df.dropna(subset=["final_score"])
    if valid.empty:
        raise ValueError(f"Not enough daily data to compute indicators for {yahoo_ticker}.")

    latest = valid.iloc[-1]

    # ML confidence (out-of-sample). May be absent if use_ml=False or if
    # training failed (too little history / xgboost missing).
    # --- Short trend filter (validated in backtest_exits) -------------
    # Shorting a low composite score means "no bullish setup", NOT "bearish
    # setup" — taken counter-trend it bleeds to drift. Requiring price below
    # its N-day SMA lifted short expectancy from +0.01R to +0.10R (BTC) and
    # +0.24R (ETH). Computed from the SAME daily closes the backtest used.
    trend_sma = None
    below_trend = None
    if trend_sma_period and trend_sma_period > 0:
        sma_series = valid["Close"].rolling(trend_sma_period).mean()
        if pd.notna(sma_series.iloc[-1]):
            trend_sma = float(sma_series.iloc[-1])
            below_trend = bool(float(latest["Close"]) < trend_sma)

    ml_info = {"ml_enabled": use_ml, "ml_ok": bool(result_df.attrs.get("ml_ok", False))}
    if use_ml:
        if result_df.attrs.get("ml_ok"):
            ai_conf = latest.get("ai_confidence_score")
            ml_info.update({
                "ai_confidence_score": float(ai_conf) if pd.notna(ai_conf) else None,
                "ml_accuracy": result_df.attrs.get("ml_accuracy"),
                "ml_roc_auc": result_df.attrs.get("ml_roc_auc"),
                "ml_test_n": result_df.attrs.get("ml_test_n"),
                "ml_lookahead_days": result_df.attrs.get("ml_lookahead_days"),
                "ml_threshold_pct": result_df.attrs.get("ml_threshold_pct"),
            })
        else:
            ml_info["ml_error"] = result_df.attrs.get("ml_error", "unknown")

    return {
        "step": 3,
        "step_name": "indicators_indexes",
        "timestamp": datetime.now(timezone.utc),
        "ticker": ticker,
        "technical_score": float(latest["technical_score"]),
        "macro_multiplier": float(latest["macro_multiplier"]),
        "indicator_final_score": float(latest["final_score"]),
        "vix_level": float(latest["vix_level"]),
        "date": valid.index[-1],
        "trend_sma": trend_sma,
        "below_trend_sma": below_trend,
        "trend_sma_period": trend_sma_period,
        **ml_info,
    }


# ======================================================================
# COMBINE — blend Step 1+2's pattern-based score with Step 3's
# indicator-based score into one final decision
# ======================================================================

EXTREME_FEAR_MODES = ("symmetric", "risk_off")


# Position size multipliers by score band, from the exit backtest.
# REPLICATED on both tickers (trade-weighted average of BTC and ETH):
#     60-70:  BTC 0.63x / ETH 0.19x  -> 0.4x
#     70-80:  BTC 1.94x / ETH 2.00x  -> 1.9x
# Derived at quarter-Kelly from measured per-trade R outcomes. These are
# ESTIMATES from ~110 (60-70) and ~56 (70-80) overlapping-window trades.
# REGENERATE PERIODICALLY:
#     pipeline.py backtest BTC --sizing --side long --buy-bar 60
# and re-check that the bands still rank the same way. If the 70-80 band
# degrades, this table will keep over-betting it until you update it.
POSITION_SIZE_BANDS = [
    (80.0, 999.0, None, "insufficient historical trades above 80 to size"),
    (70.0,  80.0, 1.9,  ""),
    (60.0,  70.0, 0.4,  ""),
]


def lookup_position_size(final_score: float):
    """Returns (multiplier, note). multiplier None = no sized guidance."""
    if final_score is None or final_score != final_score:
        return None, "no score"
    for lo, hi, mult, note in POSITION_SIZE_BANDS:
        if lo <= final_score < hi:
            return mult, note
    return None, "below the 60 entry bar"


def classify_direction(final_score: float, vix_level: float,
                        strong_buy_bar: float = 75, buy_bar: float = 60,
                        sell_bar: float = 40, strong_sell_bar: float = 25,
                        extreme_fear_mode: str = "symmetric",
                        vix_extreme: float = 35, panic_shift: float = 10) -> str:
    """
    Mirrors entry_point_model2.py's validated BUY/STRONG_BUY logic onto a
    SELL/STRONG_SELL side, so the model can express bearish conviction,
    not just "not bullish enough to buy."

    NORMAL-REGIME BARS are symmetric around the 50 (neutral) midpoint:
        STRONG_BUY >= 75   mirrors   STRONG_SELL <= 25
        BUY        >= 60   mirrors   SELL        <= 40
    WATCH is the 40-60 band in between. The mirror is exact:
    strong_buy_bar + strong_sell_bar == 100 and buy_bar + sell_bar == 100.

    EXTREME FEAR (VIX >= vix_extreme). entry_point_model2.py's own logic
    RAISES the buy bars in a panic (STRONG_BUY 75->80, BUY 60->70): it
    demands MORE conviction to buy into fear. There are two coherent ways
    to carry that onto the sell side, chosen with `extreme_fear_mode`:

      "symmetric" (DEFAULT) — the exact geometric reflection of the
          raised buy bars about 50: STRONG_SELL 25->20, SELL 40->30. Both
          bars move AWAY from neutral, so a panic demands more conviction
          in EITHER direction and the WATCH band widens symmetrically.
          This preserves the core design property that the SELL side is
          the validated BUY side reflected about 50.

          (NOTE — this is the honest description of what the code does. A
          previous version of this docstring claimed the sell bar "rises
          toward neutral / easier to sell" in a panic. It did not, in this
          default mode — the code was the correct mirror; the prose was
          wrong. That documentation mismatch was the "sell-side lapse.")

      "risk_off" — an asymmetric risk-management stance: still HARDER to
          buy in a panic (bars raised as above), but EASIER to SELL
          (STRONG_SELL 25->30, SELL 40->45; sell bars rise toward
          neutral). Pick this if you want the model to flag downside
          faster once fear is already elevated. This is a momentum/
          trend-following stance on the sell side, NOT the contrarian
          mirror, and it deliberately breaks left-right symmetry.

    This is NOT investment advice or a literal short/exit instruction —
    it's a label for which direction this composite score currently
    leans, the same epistemic status the original BUY/AVOID labels had.
    """
    if pd.isna(final_score):
        return "INSUFFICIENT_DATA"
    if extreme_fear_mode not in EXTREME_FEAR_MODES:
        raise ValueError(f"extreme_fear_mode must be one of {EXTREME_FEAR_MODES}, "
                          f"got {extreme_fear_mode!r}")

    extreme_fear = pd.notna(vix_level) and vix_level >= vix_extreme

    if extreme_fear:
        # Panic bars are DERIVED from the normal bars (+/- panic_shift away
        # from neutral), not hardcoded. They used to be literal 80/70, which
        # silently broke when buy_bar was raised to 70 — the "extreme fear"
        # bar became identical to the normal one and stopped doing anything.
        # Deriving them keeps the relationship intact through any future
        # threshold change.
        # STRONG bars shift half as far as the regular bars — reproducing
        # the original validated 80/70/30/20 at the default thresholds,
        # while still scaling correctly if a bar is moved later.
        strong_shift = panic_shift / 2.0
        sb_bar = strong_buy_bar + strong_shift
        b_bar = buy_bar + panic_shift
        if extreme_fear_mode == "risk_off":
            # Sell EASIER in a panic: bars move TOWARD neutral.
            ss_bar = strong_sell_bar + strong_shift
            s_bar = sell_bar + panic_shift
        else:
            # "symmetric": bars move AWAY from neutral, mirroring the buys.
            ss_bar = strong_sell_bar - strong_shift
            s_bar = sell_bar - panic_shift
    else:
        sb_bar, b_bar = strong_buy_bar, buy_bar
        ss_bar, s_bar = strong_sell_bar, sell_bar

    if final_score >= sb_bar:
        return "STRONG_BUY"
    if final_score >= b_bar:
        return "BUY"
    if final_score <= ss_bar:
        return "STRONG_SELL"
    if final_score <= s_bar:
        return "SELL"
    return "WATCH"


def combine_and_decide(step2_result: dict, step3_result: dict,
                        weight_pattern: float = 0.6, weight_indicators: float = 0.4,
                        extreme_fear_mode: str = "symmetric",
                        ml_weight: float = 0.0, buy_bar: float = 60,
                        sell_bar: float = 40, ml_veto: float = 25.0,
                        ml_confirm: float = 55.0) -> dict:
    """
    Blends the pattern+sentiment score (Steps 1-2) with the indicator
    score (Step 3). Default weighting favors the pattern side (0.6) over
    indicators (0.4) — this reflects THIS SESSION'S walk-forward finding
    that squeeze was more consistent than the RSI/MACD/momentum-style
    indicators, not a universal truth. Change these weights freely once
    you've validated your own numbers; they're deliberately exposed as
    parameters, not hardcoded.
    """
    gated_score = step2_result["gated_score"]
    indicator_score = step3_result["indicator_final_score"]

    base_score = weight_pattern * gated_score + weight_indicators * indicator_score
    base_score = max(0.0, min(100.0, base_score))

    # --- ML as a CONFIDENCE SCALER (not an average) --------------------
    # A flat blend fails the obvious sanity test: a 99 score with 1% ML
    # would average to ~74 and still read BUY, even though the two signals
    # flatly contradict each other. Instead the ML scales how far the score
    # is ALLOWED to sit from neutral (50):
    #
    #     final = 50 + (base - 50) * multiplier
    #
    # For a BULLISH base (>50), ML is P(up-move), so:
    #     ML >= ml_confirm (55) -> factor 1.0  (full strength)
    #     ML <= ml_veto    (25) -> factor 0.0  (collapses to 50 = WATCH)
    #     in between            -> linear ramp
    # For a BEARISH base (<50) it mirrors: a LOW ML confirms bearishness,
    # a HIGH ML vetoes it.
    #
    # ml_weight controls how much of this scaling to apply: 0 = off
    # (score untouched), 1.0 = full kill power. At 1.0, a 99/1% signal
    # lands exactly on 50 — nowhere near qualifying, which is the point.
    ml_conf = step3_result.get("ai_confidence_score")
    ml_applied = False
    final_score = base_score
    if ml_weight and ml_weight > 0 and ml_conf is not None and ml_conf == ml_conf:
        ml_conf = float(ml_conf)
        deviation = base_score - 50.0
        span = max(1e-9, ml_confirm - ml_veto)
        if deviation >= 0:                      # bullish base
            factor = (ml_conf - ml_veto) / span
        else:                                   # bearish base (mirrored)
            factor = ((100.0 - ml_conf) - ml_veto) / span
        factor = max(0.0, min(1.0, factor))
        multiplier = (1.0 - ml_weight) + ml_weight * factor
        final_score = 50.0 + deviation * multiplier
        ml_applied = True
    final_score = max(0.0, min(100.0, final_score))
    vix_level = step3_result["vix_level"]

    # entry_point_model2's own entry-only threshold logic — unchanged,
    # so "BUY"/"WATCH"/"AVOID" mean exactly the same thing here as
    # everywhere else in the project (backtest scripts, grid search, etc.)
    pseudo_row = pd.Series({"final_score": final_score, "vix_level": vix_level})
    decision = epm._decide_row(pseudo_row)

    # New: bidirectional signal (adds SELL/STRONG_SELL on the bearish
    # side, mirroring BUY/STRONG_BUY) — see classify_direction()'s
    # docstring for the thresholds and the important caveat that this
    # still isn't a literal trade/short instruction.
    direction = classify_direction(final_score, vix_level,
                                    buy_bar=buy_bar, sell_bar=sell_bar,
                                    extreme_fear_mode=extreme_fear_mode)

    return {
        "final_score": round(final_score, 2),
        "decision": decision,
        "direction": direction,
        "base_score": round(base_score, 2),
        "ml_weight": ml_weight,
        "ml_applied": ml_applied,
        "ml_veto": ml_veto,
        "ml_confirm": ml_confirm,
        "weight_pattern": weight_pattern,
        "weight_indicators": weight_indicators,
        "gated_score_contribution": round(gated_score * weight_pattern, 2),
        "indicator_score_contribution": round(indicator_score * weight_indicators, 2),
    }


# ======================================================================
# ORCHESTRATOR — runs all 3 steps in enforced order
# ======================================================================

def run_full_pipeline(ticker: str, interval: str = "4h", klines_limit: int = 500,
                       daily_period: str = "2y", subreddits: list = None,
                       weight_pattern: float = 0.6, weight_indicators: float = 0.4,
                       extreme_fear_mode: str = "symmetric",
                       stop_mult: float = 1.5, target_mult: float = 3.0,
                       use_ml: bool = False, ml_weight: float = 0.0,
                       ml_veto: float = 25.0, ml_confirm: float = 55.0,
                       buy_bar: float = 60, sell_bar: float = 40,
                       short_trend_filter: bool = True,
                       trend_sma_period: int = 50,
                       verbose: bool = True) -> dict:
    """
    Runs Step 1 -> Step 2 -> Step 3 -> combine, in that exact order,
    every time. The order is enforced two ways:
      1. Structurally: each step function requires the previous step's
         result dict as an argument, so you can't call Step 3 without
         having already produced a real Step 2 result.
      2. At the end here: the step log's timestamps are asserted to be
         strictly increasing in the correct step order, so even a future
         refactor that accidentally calls things out of sequence will
         raise loudly instead of silently producing a wrong answer.
    """
    step_log = []

    if verbose:
        print(f"\n{'=' * 70}\n  UNIFIED PIPELINE: {ticker}\n{'=' * 70}")
        print("\n[STEP 1/3] Initial scoring (squeeze/pattern detection)...")
    step1 = compute_initial_score(ticker, interval=interval, klines_limit=klines_limit)
    step_log.append(step1)
    if verbose:
        print(f"  BB_WIDTH_PCTL={step1['bb_width_pctl']:.3f}  "
              f"SQUEEZE_DURATION={step1['squeeze_duration']:.0f}  "
              f"-> initial_score={step1['initial_score']}")

    if verbose:
        print("\n[STEP 2/3] Reddit data (sentiment gate)...")
    step2 = apply_reddit_step(ticker, step1, subreddits=subreddits)
    step_log.append(step2)
    if verbose:
        print(f"  Gate: {step2['gate_decision']} (x{step2['gate_multiplier']}) — {step2['gate_reason']}")
        print(f"  {step2['score_before_reddit']} -> {step2['gated_score']} after Reddit gate")

    if verbose:
        print("\n[STEP 3/3] Indicators/indexes (technical + macro)...")
    step3 = apply_indicator_step(ticker, step2, period=daily_period, use_ml=use_ml,
                                 trend_sma_period=trend_sma_period)
    step_log.append(step3)
    if verbose:
        print(f"  technical_score={step3['technical_score']:.1f}  "
              f"macro_multiplier={step3['macro_multiplier']:.2f}  "
              f"-> indicator_final_score={step3['indicator_final_score']:.1f}")
        if step3.get("ml_enabled"):
            if step3.get("ml_ok") and step3.get("ai_confidence_score") is not None:
                acc = step3.get("ml_accuracy")
                auc = step3.get("ml_roc_auc")
                acc_str = f"{acc*100:.1f}%" if acc is not None else "n/a"
                auc_str = f"{auc:.3f}" if auc is not None and auc == auc else "n/a"
                print(f"  ML confidence={step3['ai_confidence_score']:.1f}%  "
                      f"(XGBoost prob. of +{step3['ml_threshold_pct']*100:.0f}% avg move "
                      f"over next {step3['ml_lookahead_days']} days)")
                print(f"     -> out-of-sample holdout: accuracy={acc_str}, "
                      f"ROC-AUC={auc_str}, tested on {step3.get('ml_test_n')} days")
                if auc is not None and auc == auc and auc < 0.55:
                    print(f"     -> CAUTION: ROC-AUC {auc:.3f} is close to coin-flip (0.50). "
                          f"Treat this probability as weak evidence.")
            else:
                print(f"  ML confidence: unavailable ({step3.get('ml_error', 'training failed')})")

    # --- Enforce the order actually happened correctly ---
    assert [s["step"] for s in step_log] == [1, 2, 3], \
        f"Step order violated! Got {[s['step'] for s in step_log]}, expected [1, 2, 3]"
    timestamps = [s["timestamp"] for s in step_log]
    assert timestamps == sorted(timestamps), \
        "Step timestamps are not strictly increasing — steps ran out of order!"

    # Blending ML into the score requires the ML to actually be computed.
    if ml_weight and ml_weight > 0 and not use_ml:
        raise ValueError("ml_weight > 0 requires use_ml=True (the ML score must be "
                         "computed before it can be blended into the final score).")
    combined = combine_and_decide(step2, step3, weight_pattern=weight_pattern,
                                   weight_indicators=weight_indicators,
                                   extreme_fear_mode=extreme_fear_mode,
                                   ml_weight=ml_weight, buy_bar=buy_bar,
                                   sell_bar=sell_bar, ml_veto=ml_veto,
                                   ml_confirm=ml_confirm)

    # --- Exit levels: ATR-based profit target + stop-loss for the ---
    # --- direction we just produced. Volatility bands, not predictions. ---
    exit_levels = cf.compute_exit_levels(
        entry_price=step1["close"], direction=combined["direction"],
        atr=step1.get("atr"), stop_mult=stop_mult, target_mult=target_mult,
    )
    # --- Apply the short trend filter to the live direction -----------
    if (short_trend_filter and combined["direction"] in ("SELL", "STRONG_SELL")
            and step3.get("below_trend_sma") is False):
        combined["direction_before_trend_filter"] = combined["direction"]
        combined["direction"] = "WATCH"
        combined["trend_filter_note"] = (
            f"{combined['direction_before_trend_filter']} suppressed: price is ABOVE its "
            f"{step3.get('trend_sma_period')}-day SMA ({step3.get('trend_sma'):.2f}), so this "
            f"would be a counter-trend short (backtested at ~0R). Downgraded to WATCH.")
        # Exit levels must be recomputed for the new (non-actionable) direction.
        exit_levels = cf.compute_exit_levels(
            entry_price=step1["close"], direction=combined["direction"],
            atr=step1.get("atr"), stop_mult=stop_mult, target_mult=target_mult)

    combined["exit_levels"] = exit_levels
    if combined["direction"] in ("BUY", "STRONG_BUY"):
        _mult, _note = lookup_position_size(combined["final_score"])
        combined["position_size"] = _mult
        combined["position_size_note"] = _note
    # ML confidence rides along in the output (display-only; not in final_score)
    combined["ml_confidence"] = step3.get("ai_confidence_score") if step3.get("ml_ok") else None
    combined["ml_accuracy"] = step3.get("ml_accuracy") if step3.get("ml_ok") else None

    if verbose:
        print(f"\n{'-' * 70}")
        print(f"  COMBINED: {combined['gated_score_contribution']} (pattern+reddit, "
              f"weight={weight_pattern}) + {combined['indicator_score_contribution']} "
              f"(indicators, weight={weight_indicators})")
        if combined.get("ml_applied"):
            _mlc = step3.get('ai_confidence_score', 0)
            _killed = combined['final_score'] < combined['base_score'] - 5 if combined['base_score'] > 50 else False
            print(f"  ML SCALING: base {combined['base_score']} x ML {_mlc:.1f}% "
                  f"(veto<={combined['ml_veto']:.0f}, confirm>={combined['ml_confirm']:.0f}, "
                  f"weight {combined['ml_weight']}) -> {combined['final_score']}"
                  f"{'   <- ML SUPPRESSED THIS SIGNAL' if _killed else ''}")
        print(f"  FINAL SCORE: {combined['final_score']}  ->  ENTRY DECISION: {combined['decision']}  "
              f"|  DIRECTION: {combined['direction']}")
        if combined.get("trend_filter_note"):
            print(f"  TREND FILTER: {combined['trend_filter_note']}")
        if combined.get("direction") in ("BUY", "STRONG_BUY"):
            _m = combined.get("position_size")
            if _m:
                print(f"  POSITION SIZE: {_m:.2f}x normal  (score {combined['final_score']} "
                      f"band; quarter-Kelly from backtested outcomes)")
            else:
                print(f"  POSITION SIZE: no guidance — {combined.get('position_size_note','')}")
        if exit_levels.get("applicable"):
            print(f"  EXIT LEVELS ({exit_levels['side'].upper()}, ATR={exit_levels['atr']}, "
                  f"R:R={exit_levels['risk_reward']}):")
            print(f"    Entry  ~{exit_levels['entry']}")
            print(f"    Target  {exit_levels['target']}  ({exit_levels['target_pct']:+.2f}%)")
            print(f"    Stop    {exit_levels['stop']}  ({exit_levels['stop_pct']:+.2f}%)")
        else:
            print(f"  EXIT LEVELS: n/a ({exit_levels.get('reason', 'not actionable')})")
        print(f"{'=' * 70}\n")

    return {
        "ticker": ticker,
        "step1_initial_scoring": step1,
        "step2_reddit_data": step2,
        "step3_indicators": step3,
        "combined": combined,
        "order_verified": True,
    }


# ======================================================================
# CLI — single run, or continuous loop for live monitoring
# ======================================================================

def main_run():
    parser = argparse.ArgumentParser(description="Unified 3-step pipeline: pattern -> Reddit -> indicators")
    parser.add_argument("ticker")
    parser.add_argument("--interval", default="4h")
    parser.add_argument("--klines-limit", type=int, default=500)
    parser.add_argument("--daily-period", default="2y")
    parser.add_argument("--weight-pattern", type=float, default=0.6)
    parser.add_argument("--weight-indicators", type=float, default=0.4)
    parser.add_argument("--extreme-fear-mode", choices=("symmetric", "risk_off"),
                         default="symmetric",
                         help="Sell-side behavior during a VIX panic. 'symmetric' (default) "
                              "mirrors the raised buy bars (harder to act either way); "
                              "'risk_off' keeps buying harder but makes selling easier.")
    parser.add_argument("--stop-mult", type=float, default=1.5,
                         help="Stop-loss distance in ATR multiples (default 1.5)")
    parser.add_argument("--target-mult", type=float, default=3.0,
                         help="Profit-target distance in ATR multiples (default 3.0 = 2:1 R:R)")
    parser.add_argument("--no-short-trend-filter", action="store_true",
                         help="Disable the validated short trend filter (allows "
                              "counter-trend shorts, which backtested at ~0R)")
    parser.add_argument("--trend-sma-period", type=int, default=50)
    parser.add_argument("--ml-weight", type=float, default=0.0,
                         help="How much the ML probability scales the score, 0-1. "
                              "0=off (display-only), 1.0=full kill power (a high "
                              "score with very low ML collapses to neutral). Implies --ml.")
    parser.add_argument("--ml-veto", type=float, default=25.0,
                         help="ML%% at or below which a bullish signal is fully "
                              "suppressed (default 25)")
    parser.add_argument("--ml-confirm", type=float, default=55.0,
                         help="ML%% at or above which a bullish signal keeps full "
                              "strength (default 55)")
    parser.add_argument("--buy-bar", type=float, default=60,
                         help="BUY threshold (default 60). RAISE this for fewer, "
                              "higher-conviction signals.")
    parser.add_argument("--sell-bar", type=float, default=40)
    parser.add_argument("--ml", action="store_true",
                         help="Also train + show the XGBoost ML confidence score "
                              "(Yahoo-derived features, honest holdout; display-only, "
                              "does not affect the final score). Needs xgboost + scikit-learn.")
    parser.add_argument("--loop", action="store_true", help="Keep rerunning continuously")
    parser.add_argument("--log-file", default="signal_log.csv",
                         help="Log each run to this CSV (default signal_log.csv, "
                              "same file live_tools.py graph reads)")
    parser.add_argument("--no-log", action="store_true",
                         help="Skip writing to the log file")
    parser.add_argument("--interval-seconds", type=int, default=900,
                         help="Seconds between runs when --loop is set (default 15 min)")
    args = parser.parse_args()

    def run_once():
        try:
            result = run_full_pipeline(
                args.ticker, interval=args.interval, klines_limit=args.klines_limit,
                daily_period=args.daily_period, weight_pattern=args.weight_pattern,
                weight_indicators=args.weight_indicators,
                extreme_fear_mode=args.extreme_fear_mode,
                stop_mult=args.stop_mult, target_mult=args.target_mult,
                use_ml=args.ml or args.ml_weight > 0,
                ml_weight=args.ml_weight, ml_veto=args.ml_veto,
                ml_confirm=args.ml_confirm,
                buy_bar=args.buy_bar, sell_bar=args.sell_bar,
                short_trend_filter=not args.no_short_trend_filter,
                trend_sma_period=args.trend_sma_period,
            )
            if not args.no_log:
                try:
                    # Import here to avoid circular dep at module level
                    from live_tools import append_ping_to_log
                    row = append_ping_to_log(result, args.log_file)
                    exits = result["combined"].get("exit_levels", {}) or {}
                    if exits.get("applicable"):
                        print(f"  Logged to {args.log_file} "
                              f"(target={exits['target']}, stop={exits['stop']})")
                    else:
                        print(f"  Logged to {args.log_file}")
                except Exception as log_e:
                    print(f"  [log] failed to write to {args.log_file}: {log_e}")
        except Exception as e:
            print(f"\n[ERROR] Pipeline run failed: {type(e).__name__}: {e}\n")

    if not args.loop:
        run_once()
        return

    print(f"Running continuously every {args.interval_seconds}s. Ctrl+C to stop.\n")
    try:
        while True:
            run_once()
            time.sleep(args.interval_seconds)
    except KeyboardInterrupt:
        print("\nStopped.")


# ======================================================================
# SECTION 2 — run_multi_ticker.py (batch runner across a ticker list)
# ======================================================================

DEFAULT_TICKERS = ["BTC", "ETH", "SOL"]


def run_batch(tickers: list) -> list:
    results = []

    for ticker in tickers:
        print(f"\nRunning {ticker}...")
        try:
            result = run_full_pipeline(ticker, verbose=False)
            results.append({
                "ticker": ticker,
                "ok": True,
                "initial_score": result["step1_initial_scoring"]["initial_score"],
                "gate_decision": result["step2_reddit_data"]["gate_decision"],
                "gated_score": result["step2_reddit_data"]["gated_score"],
                "technical_score": result["step3_indicators"]["technical_score"],
                "indicator_final_score": result["step3_indicators"]["indicator_final_score"],
                "final_score": result["combined"]["final_score"],
                "decision": result["combined"]["decision"],
                "direction": result["combined"]["direction"],
                "exit_levels": result["combined"].get("exit_levels", {}),
                "error": None,
            })
            print(f"  {ticker}: {result['combined']['decision']} "
                  f"(final_score={result['combined']['final_score']})")
        except Exception as e:  # noqa: BLE001 - one bad ticker shouldn't kill the batch
            results.append({
                "ticker": ticker, "ok": False, "error": f"{type(e).__name__}: {e}",
            })
            print(f"  {ticker}: FAILED — {type(e).__name__}: {e}")

    return results


def print_summary_table(results: list):
    print(f"\n{'=' * 88}")
    print(f"  SUMMARY — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'=' * 88}")
    header = (f"{'Ticker':<7}{'Initial':>8}{'Gated':>8}{'IndFinal':>9}{'Final':>8}"
              f"{'Direction':>13}{'Target':>12}{'Stop':>12}{'R:R':>6}")
    print(header)
    print("-" * 88)

    for r in results:
        if not r["ok"]:
            print(f"{r['ticker']:<7}  ERROR: {r['error']}")
            continue
        ex = r.get("exit_levels") or {}
        if ex.get("applicable"):
            tgt = f"{ex['target']:,.2f}"
            stp = f"{ex['stop']:,.2f}"
            rr = f"{ex['risk_reward']:.1f}"
        else:
            tgt = stp = rr = "—"
        print(f"{r['ticker']:<7}"
              f"{r['initial_score']:>8.2f}"
              f"{r['gated_score']:>8.2f}"
              f"{r['indicator_final_score']:>9.1f}"
              f"{r['final_score']:>8.2f}"
              f"{r['direction']:>13}"
              f"{tgt:>12}"
              f"{stp:>12}"
              f"{rr:>6}")

    print("-" * 88)
    print("  Target/Stop = ATR-based volatility bands (default 2:1 R:R), NOT price")
    print("  predictions. '—' = WATCH/AVOID (no actionable direction).")
    print(f"{'=' * 88}\n")


def main_multi():
    tickers = sys.argv[1:] if len(sys.argv) > 1 else DEFAULT_TICKERS
    results = run_batch(tickers)
    print_summary_table(results)


# ======================================================================
# SECTION 3 — backtest_direction.py (historical backtest of the direction signal)
# ======================================================================

def backtest_squeeze_history(ticker: str, target_4h_bars: int = 4000) -> pd.Series:
    """
    Pulls historical 4h squeeze scores and resamples to one reading per
    calendar day (last 4h bar of the day), matching entry_point_model2's
    daily granularity for Step 3. Returns a Series indexed by date.
    """
    symbol = cf.to_binance_symbol(ticker)
    klines = cf.fetch_klines_paginated(symbol, interval="4h", target_bars=target_4h_bars)
    squeezed = cf.add_squeeze_features(klines)
    squeezed = squeezed.dropna(subset=["BB_WIDTH_PCTL"])

    coil = (1 - squeezed["BB_WIDTH_PCTL"]) * 70
    duration = (squeezed["SQUEEZE_DURATION"] / 40).clip(upper=1.0) * 30
    squeezed["initial_score"] = (coil + duration).clip(0, 100)

    daily = squeezed["initial_score"].resample("D").last().dropna()
    daily.index = daily.index.normalize()
    return daily


def _period_to_years(period: str) -> float:
    """Rough length of a yfinance period string in years, for sizing the
    matching 4h squeeze history. 'max' is treated as 8y (plenty for crypto)."""
    p = str(period).strip().lower()
    if p == "max":
        return 8.0
    if p == "ytd":
        return 1.0
    try:
        if p.endswith("mo"):
            return float(p[:-2]) / 12.0
        if p.endswith("y"):
            return float(p[:-1])
        if p.endswith("d"):
            return float(p[:-1]) / 365.0
    except ValueError:
        pass
    return 2.0


def run_backtest(ticker: str, period: str = "2y", forward_days: int = 5,
                  weight_pattern: float = 0.6, weight_indicators: float = 0.4,
                  extreme_fear_mode: str = "symmetric",
                  buy_bar: float = 60, sell_bar: float = 40,
                  squeeze_bars: int = None) -> pd.DataFrame:
    print(f"Pulling daily technical/macro history for {ticker}...")
    yahoo_ticker = to_yahoo_crypto_symbol(ticker)
    tech_df = epm.analyze(yahoo_ticker, period=period)
    tech_df = tech_df.dropna(subset=["final_score"])
    tech_df.index = pd.to_datetime(tech_df.index).normalize()

    # BUG FIX: backtest_squeeze_history's default of 4000 4h bars is only
    # ~1.8 years. Because the squeeze/technical join below is an INNER join,
    # that silently capped EVERY backtest at ~1.8y no matter what --period
    # asked for. Scale the 4h depth to the requested period instead
    # (6 bars/day, +15% slack for exchange gaps), capped at the paginator's
    # hard maximum (20 requests x 1500 bars).
    if squeeze_bars is None:
        squeeze_bars = min(int(_period_to_years(period) * 365 * 6 * 1.15), 30000)

    print(f"Pulling 4h squeeze history for {ticker} (resampled to daily)...")
    squeeze_daily = backtest_squeeze_history(ticker, target_4h_bars=squeeze_bars)

    merged = tech_df.join(squeeze_daily.rename("initial_score"), how="inner")
    merged = merged.dropna(subset=["initial_score", "final_score", "Close"])

    if merged.empty:
        raise ValueError(f"No overlapping dates between squeeze history and technical "
                          f"history for {ticker} — can't backtest.")

    # NEUTRAL sentiment assumption (see module docstring) — gated_score == initial_score
    merged["gated_score"] = merged["initial_score"]
    merged["combined_final_score"] = (
        weight_pattern * merged["gated_score"] + weight_indicators * merged["final_score"]
    ).clip(0, 100)

    # extreme_fear_mode ONLY affects days where vix_level >= 35 (extreme fear).
    # "symmetric" (default) mirrors the raised buy bars exactly; "risk_off"
    # keeps buying harder but makes selling easier in a panic. See
    # unified_model.classify_direction's docstring for the full rationale.
    merged["direction"] = merged.apply(
        lambda row: classify_direction(row["combined_final_score"], row["vix_level"],
                                        buy_bar=buy_bar, sell_bar=sell_bar,
                                        extreme_fear_mode=extreme_fear_mode), axis=1
    )

    merged["forward_return"] = merged["Close"].shift(-forward_days) / merged["Close"] - 1
    merged = merged.dropna(subset=["forward_return"])

    return merged


def backtest_exits(merged, stop_mult: float = 1.5,
                   target_mult: float = 3.0, max_hold_days: int = 15,
                   side: str = "both", short_sma_filter: int = 0,
                   confirm_days: int = 1,
                    fee_bps: float = 10.0, slippage_bps: float = 5.0) -> dict:
    """
    Simulates the ATR exit levels on every historical actionable signal:
    entry at that day's close, then walk forward daily bars until the
    TARGET is touched (High>=target for longs / Low<=target for shorts),
    the STOP is touched, or max_hold_days passes (timeout).

    Also records MFE - max favorable excursion - how far price moved
    toward the target (as a % of the target distance) before the trade
    resolved. High MFE on stop-outs/timeouts = "almost reached, then
    reversed", the failure mode a trailing stop or nearer target fixes.

    HONESTY CAVEATS baked into the numbers:
    - Daily bars can't tell which of target/stop was touched FIRST when
      both fall inside one bar's range; those ambiguous bars are counted
      as STOPS (pessimistic) and tallied separately.
    - Live exits use 4h ATR; this uses daily ATR (bigger), so absolute
      levels differ - the structural question (do 3x targets get reached
      before 1.5x stops) is what's being measured.
    - Consecutive-day signals are simulated as independent trades.
    """
    df = merged.dropna(subset=["High", "Low", "Close"]).copy()
    df["atr"] = cf.compute_atr(df, period=14)
    # Trend filter for shorts: only short when price is ALREADY below its
    # N-day SMA (i.e. with the downtrend). Fixes the structural flaw where
    # a low composite score means "no bullish setup", not "bearish setup" -
    # without this, the mirror shorts into uptrends and bleeds to drift.
    if short_sma_filter and short_sma_filter > 0:
        df["_trend_sma"] = df["Close"].rolling(short_sma_filter).mean()

    # PERSISTENCE FILTER: require the SAME direction on confirm_days
    # consecutive days before entering. confirm_days=1 is the current
    # behavior (enter the moment the signal appears).
    #
    # Why days and not minutes: Step 1 uses 4h bars and Step 3 uses DAILY
    # data, so two checks 20 minutes apart are the same observation sampled
    # twice, not two pieces of evidence. Daily spacing is the shortest
    # interval where the inputs have actually refreshed.
    #
    # The cost is entry delay. Trades here resolve in ~9 days on average,
    # so waiting 2-3 days can eat a meaningful part of the move - which is
    # exactly what this measures rather than assumes.
    dirs = df["direction"].tolist()

    def _confirmed(i):
        if confirm_days <= 1:
            return True
        if i < confirm_days - 1:
            return False
        window = dirs[i - confirm_days + 1: i + 1]
        return all(d == window[-1] for d in window)

    trades = []
    idx = df.index.to_list()
    for i, (day, row) in enumerate(df.iterrows()):
        if not _confirmed(i):
            continue
        d = row["direction"]
        if d not in ("BUY", "STRONG_BUY", "SELL", "STRONG_SELL"):
            continue
        if side == "long" and d not in ("BUY", "STRONG_BUY"):
            continue
        if side == "short" and d not in ("SELL", "STRONG_SELL"):
            continue
        if (short_sma_filter and d in ("SELL", "STRONG_SELL")
                and not (row.get("_trend_sma") == row.get("_trend_sma")  # NaN warmup
                         and row["Close"] < row["_trend_sma"])):
            continue  # short suppressed: price not below its trend SMA
        if not (row["atr"] == row["atr"]):  # NaN ATR (warmup rows)
            continue
        lvl = cf.compute_exit_levels(row["Close"], d, row["atr"],
                                     stop_mult=stop_mult, target_mult=target_mult)
        if not lvl.get("applicable"):
            continue
        entry, target, stop = lvl["entry"], lvl["target"], lvl["stop"]
        is_long = lvl["side"] == "long"
        tgt_dist = abs(target - entry)

        outcome, exit_day, mfe = "timeout", None, 0.0
        fwd = df.iloc[i + 1: i + 1 + max_hold_days]
        if fwd.empty:
            continue
        for fday, frow in fwd.iterrows():
            hi, lo = frow["High"], frow["Low"]
            fav = (hi - entry) if is_long else (entry - lo)
            if tgt_dist:
                mfe = max(mfe, fav / tgt_dist)
            hit_t = hi >= target if is_long else lo <= target
            hit_s = lo <= stop if is_long else hi >= stop
            if hit_t and hit_s:
                outcome, exit_day = "ambiguous_stop", fday  # pessimistic
                break
            if hit_t:
                outcome, exit_day = "target", fday
                break
            if hit_s:
                outcome, exit_day = "stop", fday
                break
        if outcome == "timeout":
            last_close = fwd.iloc[-1]["Close"]
            denom = stop_mult * row["atr"]
            pnl_r = ((last_close - entry) if is_long else (entry - last_close)) / denom
        elif outcome == "target":
            pnl_r = lvl["risk_reward"]
        else:
            pnl_r = -1.0
        # COST MODELING. The gross numbers above assume perfect fills at
        # the level and zero fees — optimistic in a way that scales with
        # how tight the stop is: 1R here is stop_mult*ATR of price move,
        # and a fixed round-trip cost is a LARGER fraction of a smaller R.
        # cost_r = round-trip (fee+slippage) / stop distance as % of entry.
        # Defaults (10bps fee + 5bps slippage per side = 30bps round trip)
        # are deliberately conservative for Binance.US spot; override per
        # your actual tier. Gross keys are unchanged so every previously
        # reported number stays comparable; _net keys are the honest ones.
        stop_frac = (stop_mult * row["atr"]) / entry if entry else float("nan")
        cost_r = ((2.0 * (fee_bps + slippage_bps) / 1e4) / stop_frac
                  if stop_frac and stop_frac == stop_frac else 0.0)
        trades.append({"date": day, "direction": d, "outcome": outcome,
                       "score": float(row.get("combined_final_score", float("nan"))),
                       "mfe_pct_of_target": round(mfe * 100, 1),
                       "pnl_r": round(pnl_r, 3),
                       "cost_r": round(cost_r, 4),
                       "pnl_r_net": round(pnl_r - cost_r, 3),
                       "days_held": (idx.index(exit_day) - i) if exit_day is not None else max_hold_days})

    if not trades:
        return {"n": 0, "trades": trades, "confirm_days": confirm_days}
    tdf = pd.DataFrame(trades)
    nonwin = tdf.loc[tdf["outcome"] != "target", "mfe_pct_of_target"]
    return {
        "n": len(tdf),
        "confirm_days": confirm_days,
        "target_rate": (tdf["outcome"] == "target").mean(),
        "stop_rate": tdf["outcome"].isin(["stop", "ambiguous_stop"]).mean(),
        "ambiguous_n": int((tdf["outcome"] == "ambiguous_stop").sum()),
        "timeout_rate": (tdf["outcome"] == "timeout").mean(),
        "expectancy_r": tdf["pnl_r"].mean(),
        "expectancy_r_net": tdf["pnl_r_net"].mean(),
        "avg_cost_r": tdf["cost_r"].mean(),
        "avg_days_held": tdf["days_held"].mean(),
        "avg_mfe_on_losses": nonwin.mean() if len(nonwin) else float("nan"),
        "near_miss_rate": (nonwin >= 70).mean() if len(nonwin) else float("nan"),
        "trades": trades,
    }


def compute_position_sizing(res: dict, bucket: float = 10.0,
                            kelly_fraction: float = 0.25, max_size: float = 2.0,
                            min_n: int = 15) -> dict:
    """
    Size positions by MEASURED edge instead of trading every signal the same.

    You already paid to learn that score 60-70 was +0.10R and 70-80 was
    +0.32R. Sizing them identically throws that away. This converts each
    score band's empirical outcome distribution into a size multiplier.

    METHOD: Kelly's continuous approximation, f* = mean / variance, applied
    to the actual per-trade R outcomes in each band. Then multiplied by
    kelly_fraction (default 0.25 = quarter-Kelly).

    WHY FRACTIONAL KELLY, NOT FULL: Kelly assumes you KNOW the true win
    probability. You don't — you have an estimate from a few dozen
    overlapping-window trades. Full Kelly on an overestimated edge is a
    fast route to ruin, and Kelly's own variance is brutal even when the
    edge is real. Quarter-Kelly gives up a little growth for a large
    reduction in drawdown, which is the right trade when the inputs are
    uncertain. Raise it only if the bands hold up over many more trades.

    GUARDRAILS:
      - bands with fewer than min_n trades get size 0 (not enough evidence)
      - bands with expectancy <= 0 get size 0 (don't fund a losing bucket)
      - sizes are capped at max_size
      - output is normalized so the trade-weighted average size is 1.0,
        i.e. "relative to your normal position", NOT a % of capital
    """
    trades = res.get("trades", [])
    if not trades:
        return {}
    tdf = pd.DataFrame(trades).dropna(subset=["score", "pnl_r"])
    if tdf.empty:
        return {}

    lo = int(tdf["score"].min() // bucket * bucket)
    hi = int(tdf["score"].max() // bucket * bucket + bucket)
    edges = [lo + i * bucket for i in range(int((hi - lo) / bucket) + 1)]
    tdf["band"] = pd.cut(tdf["score"], bins=edges, right=False)

    raw = {}
    for band, g in tdf.groupby("band", observed=True):
        n = len(g)
        mean_r = g["pnl_r"].mean()
        std_r = g["pnl_r"].std()
        var_r = std_r ** 2 if std_r == std_r and std_r > 0 else float("nan")
        if n < min_n:
            raw[band] = {"n": n, "mean_r": mean_r, "std_r": std_r,
                         "kelly": 0.0, "reason": f"only {n} trades (<{min_n})"}
        elif mean_r <= 0:
            raw[band] = {"n": n, "mean_r": mean_r, "std_r": std_r,
                         "kelly": 0.0, "reason": "expectancy <= 0"}
        elif var_r != var_r or var_r <= 0:
            raw[band] = {"n": n, "mean_r": mean_r, "std_r": std_r,
                         "kelly": 0.0, "reason": "no variance estimate"}
        else:
            raw[band] = {"n": n, "mean_r": mean_r, "std_r": std_r,
                         "kelly": (mean_r / var_r) * kelly_fraction, "reason": ""}

    # Normalize to a multiplier around 1.0, weighted by how often each
    # band actually occurs — so "1.0x" means your usual size.
    tradeable = {b: v for b, v in raw.items() if v["kelly"] > 0}
    if tradeable:
        tot_n = sum(v["n"] for v in tradeable.values())
        wavg = sum(v["kelly"] * v["n"] for v in tradeable.values()) / tot_n
        for v in raw.values():
            v["size"] = min(max_size, v["kelly"] / wavg) if (wavg > 0 and v["kelly"] > 0) else 0.0
    else:
        for v in raw.values():
            v["size"] = 0.0
    return {str(b): v for b, v in raw.items()}


def print_position_sizing(sizing: dict, kelly_fraction: float):
    print(f"\n{'=' * 84}")
    print(f"  POSITION SIZING BY SCORE  ({kelly_fraction:g}-Kelly on measured outcomes)")
    print(f"{'=' * 84}")
    if not sizing:
        print("  No trades to size against.\n")
        return
    print(f"{'Score band':<15}{'N':>6}{'Mean R':>10}{'Std R':>9}{'Kelly f*':>11}"
          f"{'SIZE':>8}   {'note'}")
    print("-" * 84)
    for band, v in sizing.items():
        size_s = f"{v['size']:.2f}x" if v["size"] > 0 else "SKIP"
        std_s = f"{v['std_r']:.2f}" if v["std_r"] == v["std_r"] else "n/a"
        print(f"{band:<15}{v['n']:>6}{v['mean_r']:>+10.2f}{std_s:>9}"
              f"{v['kelly']:>11.3f}{size_s:>8}   {v['reason']}")
    print("-" * 84)
    print("  SIZE is RELATIVE to your normal position, not a % of capital.")
    print("  1.00x = usual size, 0.50x = half, SKIP = don't take the trade.")
    print("  Quarter-Kelly by default because these probabilities are ESTIMATES")
    print("  from small, overlapping samples — full Kelly on an overestimated")
    print("  edge compounds losses fast. Widen only after many more trades.")
    print(f"{'=' * 84}\n")


def print_probability_table(res: dict, bucket: float = 10.0, min_n: int = 10):
    """
    EMPIRICAL outcome frequencies by score bucket — the calibration layer.

    This is NOT a prediction. It reports what actually happened historically
    to trades that fired at each score level: how often the ATR target was
    reached before the stop, how often the stop came first, and the average
    R outcome. That makes it a genuinely calibrated probability conditioned
    on your own signal, rather than a model's guess about price direction.

    Why this beats the ML attempt: the ML was asked "will price rise 1.5% in
    5 days?" (a proxy) and topped out near coin-flip out of sample. This
    asks "when my signal scored 70-80, how often did the trade work?" —
    the actual question, answered by counting rather than forecasting.

    min_n guards against reading meaning into thin buckets; anything with
    fewer than min_n trades is shown but flagged as unreliable.
    """
    trades = res.get("trades", [])
    if not trades:
        print("\n  No trades to calibrate against.\n")
        return {}
    tdf = pd.DataFrame(trades).dropna(subset=["score"])
    if tdf.empty:
        print("\n  No scored trades to calibrate against.\n")
        return {}

    lo = int(tdf["score"].min() // bucket * bucket)
    hi = int(tdf["score"].max() // bucket * bucket + bucket)
    edges = [lo + i * bucket for i in range(int((hi - lo) / bucket) + 1)]
    tdf["band"] = pd.cut(tdf["score"], bins=edges, right=False)

    print(f"\n{'=' * 82}")
    print(f"  CALIBRATED OUTCOME PROBABILITIES BY SCORE  (bucket={bucket:g})")
    print(f"  Empirical frequencies from {len(tdf)} simulated trades - not a forecast")
    print(f"{'=' * 82}")
    print(f"{'Score band':<15}{'N':>6}{'P(target)':>11}{'P(stop)':>10}"
          f"{'P(timeout)':>12}{'Expectancy':>12}{'':>6}")
    print("-" * 82)

    table = {}
    for band, g in tdf.groupby("band", observed=True):
        n = len(g)
        if n == 0:
            continue
        p_t = (g["outcome"] == "target").mean()
        p_s = g["outcome"].isin(["stop", "ambiguous_stop"]).mean()
        p_o = (g["outcome"] == "timeout").mean()
        exp = g["pnl_r"].mean()
        flag = "" if n >= min_n else "  thin"
        print(f"{str(band):<15}{n:>6}{p_t*100:>10.1f}%{p_s*100:>9.1f}%"
              f"{p_o*100:>11.1f}%{exp:>+11.2f}R{flag:>6}")
        table[str(band)] = {"n": n, "p_target": round(p_t, 3), "p_stop": round(p_s, 3),
                            "p_timeout": round(p_o, 3), "expectancy_r": round(exp, 3)}
    print("-" * 82)
    print("  HOW TO USE THIS: when a live signal scores 72, look up the 70-80 row.")
    print("  That P(target) is your calibrated win probability for this trade -")
    print("  derived from your own history, no model required. If P(target) does")
    print("  not RISE with score, the score is not measuring conviction and the")
    print("  thresholds are decorative.")
    print("  Buckets marked 'thin' have too few trades to trust.")
    print(f"{'=' * 82}\n")
    return table


def print_exit_report(res: dict, stop_mult: float, target_mult: float, max_hold_days: int):
    print(f"\n{'=' * 74}")
    print(f"  EXIT BACKTEST - target {target_mult}xATR / stop {stop_mult}xATR, "
          f"max hold {max_hold_days} days")
    if res.get("confirm_days", 1) > 1:
        print(f"  Persistence filter: same direction {res['confirm_days']} days running")
    print(f"{'=' * 74}")
    if res["n"] == 0:
        print("  No actionable signals with enough forward data to simulate.")
        return
    be = 1.0 / (1.0 + target_mult / stop_mult)
    print(f"  Trades simulated: {res['n']}")
    print(f"  Target hit:  {res['target_rate']*100:5.1f}%   (breakeven at this R:R ~ {be*100:.0f}%)")
    print(f"  Stop hit:    {res['stop_rate']*100:5.1f}%   (incl. {res['ambiguous_n']} ambiguous "
          f"same-bar cases counted pessimistically as stops)")
    print(f"  Timeout:     {res['timeout_rate']*100:5.1f}%   (neither level in {max_hold_days} days)")
    print(f"  Expectancy:  {res['expectancy_r']:+.2f}R per trade   |   avg hold {res['avg_days_held']:.1f} days")
    print(f"  --- 'almost reached, then reversed' diagnostics ---")
    print(f"  Avg MFE on non-winners: {res['avg_mfe_on_losses']:.0f}% of the way to target")
    print(f"  Near-miss rate (got >=70% to target, still didn't win): "
          f"{res['near_miss_rate']*100:.0f}% of non-winners")
    print(f"  -> If near-miss rate is high, a TRAILING stop or partial take-profit")
    print(f"     at ~70-80% of target would capture what fixed targets give back.")
    # --- per-side breakdown: is one side carrying (or killing) the edge? ---
    tdf = pd.DataFrame(res["trades"])
    tdf["side"] = tdf["direction"].apply(
        lambda d: "LONG" if d in ("BUY", "STRONG_BUY") else "SHORT")
    print(f"  --- per-side breakdown ---")
    for side, g in tdf.groupby("side"):
        tr = (g["outcome"] == "target").mean() * 100
        print(f"  {side:5s}: {len(g):4d} trades | target {tr:4.1f}% | "
              f"expectancy {g['pnl_r'].mean():+.2f}R")
    print(f"{'=' * 74}\n")


def print_score_buckets(merged, forward_days: int, bucket: float = 2.5):
    """
    Forward returns by NARROW score band — answers "where should the BUY bar
    actually be?" The coarse direction table lumps 40-60 into one WATCH
    bucket; this splits it so you can see whether a 58 behaves like a 62
    (bar is too strict) or like a 45 (bar is right where it belongs).
    """
    df = merged.dropna(subset=["combined_final_score", "forward_return"]).copy()
    lo = int(df["combined_final_score"].min() // bucket * bucket)
    hi = int(df["combined_final_score"].max() // bucket * bucket + bucket)
    edges = [lo + i * bucket for i in range(int((hi - lo) / bucket) + 1)]
    df["band"] = pd.cut(df["combined_final_score"], bins=edges, right=False)

    print(f"\n{'=' * 74}")
    print(f"  SCORE BANDS vs {forward_days}-day forward return  (bucket={bucket})")
    print(f"  Current BUY bar = 60, SELL bar = 40")
    print(f"{'=' * 74}")
    print(f"{'Score band':<16}{'Days':>7}{'Avg fwd ret':>14}{'% positive':>13}")
    print("-" * 74)
    for band, g in df.groupby("band", observed=True):
        if len(g) == 0:
            continue
        avg = g["forward_return"].mean() * 100
        pos = (g["forward_return"] > 0).mean() * 100
        marker = ""
        left = band.left
        if left == 60: marker = "  <- BUY bar"
        elif left == 40: marker = "  <- SELL bar"
        print(f"{str(band):<16}{len(g):>7}{avg:>13.2f}%{pos:>12.1f}%{marker}")
    print("-" * 74)
    print("  Read it this way: if the bands just BELOW 60 look like the bands")
    print("  just ABOVE it, the bar is too strict and can move down. If they")
    print("  look like the 40s, the bar is correctly placed and lowering it")
    print("  would import noise. Overlapping windows - not independent samples.")
    print(f"{'=' * 74}\n")


def summarize(merged: pd.DataFrame, forward_days: int, extreme_fear_mode: str = "symmetric"):
    n_extreme = int((merged["vix_level"] >= 35).sum())
    print(f"\n{'=' * 78}")
    print(f"  DIRECTION BACKTEST — {forward_days}-trading-day forward returns")
    print(f"  {merged.index.min().date()} to {merged.index.max().date()}  "
          f"({len(merged)} trading days)")
    print(f"  extreme_fear_mode = {extreme_fear_mode!r}  "
          f"({n_extreme} of {len(merged)} days were extreme-fear, VIX>=35 — "
          f"mode only affects those days)")
    print(f"{'=' * 78}")

    order = ["STRONG_BUY", "BUY", "WATCH", "SELL", "STRONG_SELL"]
    header = f"{'Direction':<14}{'Days':>7}{'% of total':>12}{'Avg fwd ret':>14}{'Win rate':>12}"
    print(header)
    print("-" * 78)

    for label in order:
        bucket = merged[merged["direction"] == label]
        n = len(bucket)
        if n == 0:
            print(f"{label:<14}{0:>7}{'0.0%':>12}{'—':>14}{'—':>12}")
            continue

        pct_of_total = n / len(merged) * 100
        avg_return = bucket["forward_return"].mean() * 100

        if label in ("STRONG_BUY", "BUY"):
            win_rate = (bucket["forward_return"] > 0).mean() * 100
        elif label in ("SELL", "STRONG_SELL"):
            win_rate = (bucket["forward_return"] < 0).mean() * 100
        else:
            win_rate = float("nan")

        win_str = f"{win_rate:.1f}%" if pd.notna(win_rate) else "—"
        print(f"{label:<14}{n:>7}{pct_of_total:>11.1f}%{avg_return:>13.2f}%{win_str:>12}")

    print("-" * 78)
    print(f"  'Win rate' = % of BUY/STRONG_BUY days with a positive forward return,\n"
          f"  or % of SELL/STRONG_SELL days with a negative forward return.\n"
          f"  Overlapping windows — not independent samples. See module docstring\n"
          f"  for what this backtest does and doesn't cover (no historical sentiment).")
    print(f"{'=' * 78}\n")


def compare_extreme_fear_modes(ticker: str, period: str = "2y", forward_days: int = 5,
                                weight_pattern: float = 0.6, weight_indicators: float = 0.4):
    """
    Runs the backtest twice — once per extreme_fear_mode — over the SAME
    underlying data (only extreme-fear days can differ between the two
    runs), and prints both summaries plus a focused diff on just the
    extreme-fear days so you can see whether 'risk_off' actually helped
    or hurt before choosing it as your live default.
    """
    results = {}
    for mode in ("symmetric", "risk_off"):
        print(f"\n### Running with extreme_fear_mode='{mode}' ###")
        results[mode] = run_backtest(ticker, period=period, forward_days=forward_days,
                                     weight_pattern=weight_pattern,
                                     weight_indicators=weight_indicators,
                                     extreme_fear_mode=mode)
        summarize(results[mode], forward_days, extreme_fear_mode=mode)

    sym, risk = results["symmetric"], results["risk_off"]
    extreme_mask = sym["vix_level"] >= 35
    n_extreme = int(extreme_mask.sum())

    print(f"\n{'=' * 78}")
    print(f"  EXTREME-FEAR DAYS ONLY — where the two modes can actually differ")
    print(f"  ({n_extreme} of {len(sym)} days had VIX >= 35)")
    print(f"{'=' * 78}")
    if n_extreme == 0:
        print("  No extreme-fear days in this window — the two modes produced "
              "identical results here. Try a longer --period or a more volatile "
              "ticker to get a real comparison.")
    else:
        for mode, df in (("symmetric", sym), ("risk_off", risk)):
            bucket = df.loc[extreme_mask]
            sell_bucket = bucket[bucket["direction"].isin(["SELL", "STRONG_SELL"])]
            n_sell = len(sell_bucket)
            avg_ret = sell_bucket["forward_return"].mean() * 100 if n_sell else float("nan")
            win = ((sell_bucket["forward_return"] < 0).mean() * 100) if n_sell else float("nan")
            print(f"  [{mode:9s}] SELL/STRONG_SELL fired on {n_sell}/{n_extreme} extreme-fear "
                  f"days  |  avg fwd return {avg_ret:+.2f}%" if n_sell else
                  f"  [{mode:9s}] SELL/STRONG_SELL fired on 0/{n_extreme} extreme-fear days")
            if n_sell:
                print(f"                win rate (return went negative) {win:.1f}%")
    print(f"{'=' * 78}\n")

    return results


def main_backtest():
    parser = argparse.ArgumentParser(description="Backtest the bidirectional direction signal")
    parser.add_argument("ticker")
    parser.add_argument("--period", default="2y")
    parser.add_argument("--forward-days", type=int, default=5)
    parser.add_argument("--weight-pattern", type=float, default=0.6)
    parser.add_argument("--weight-indicators", type=float, default=0.4)
    parser.add_argument("--extreme-fear-mode", choices=("symmetric", "risk_off"),
                         default="symmetric",
                         help="Sell-side stance during VIX>=35 panics — see "
                              "unified_model.classify_direction's docstring. Ignored "
                              "if --compare-modes is set.")
    parser.add_argument("--compare-modes", action="store_true",
                         help="Run BOTH extreme_fear_mode settings back to back and "
                              "print a focused diff on extreme-fear days, instead of "
                              "a single run.")
    parser.add_argument("--buy-bar", type=float, default=60,
                         help="BUY threshold to test (default 60). Pair with --exits "
                              "to see whether moving it improves expectancy.")
    parser.add_argument("--sell-bar", type=float, default=40,
                         help="SELL threshold to test (default 40)")
    parser.add_argument("--score-bands", action="store_true",
                         help="Show forward returns by narrow score band, to test "
                              "whether the BUY/SELL bars are placed correctly")
    parser.add_argument("--band-size", type=float, default=2.5)
    parser.add_argument("--sizing", action="store_true",
                         help="Print position size multipliers per score band, "
                              "from measured expectancy (fractional Kelly). Implies --exits.")
    parser.add_argument("--kelly-fraction", type=float, default=0.25,
                         help="Fraction of full Kelly to use (default 0.25)")
    parser.add_argument("--prob-table", action="store_true",
                         help="Print empirical outcome probabilities by score bucket "
                              "(the calibration layer). Implies --exits.")
    parser.add_argument("--prob-bucket", type=float, default=10.0)
    parser.add_argument("--exits", action="store_true",
                         help="Also simulate the ATR target/stop exits on every "
                              "historical signal: hit rates, expectancy, and the "
                              "'almost reached then reversed' (MFE) diagnostics.")
    parser.add_argument("--stop-mult", type=float, default=1.5)
    parser.add_argument("--target-mult", type=float, default=3.0)
    parser.add_argument("--max-hold-days", type=int, default=15,
                         help="Timeout for the exit simulation (default 15 trading days)")
    parser.add_argument("--side", choices=("both", "long", "short"), default="both",
                         help="Restrict the exit simulation to one side (default both)")
    parser.add_argument("--confirm-days", type=int, default=1,
                         help="Require the same direction N days running before "
                              "entering (1 = enter immediately, current behavior). "
                              "Tests whether persistence filtering beats speed.")
    parser.add_argument("--short-sma-filter", type=int, default=0,
                         help="Only take SHORT trades when Close is below this N-day "
                              "SMA (0 = off). Tests the 'only short downtrends' fix.")
    args = parser.parse_args()

    if args.compare_modes:
        compare_extreme_fear_modes(args.ticker, period=args.period,
                                    forward_days=args.forward_days,
                                    weight_pattern=args.weight_pattern,
                                    weight_indicators=args.weight_indicators)
        return

    if args.buy_bar != 60 or args.sell_bar != 40:
        print(f"\n[testing modified thresholds: BUY>={args.buy_bar}, SELL<={args.sell_bar}]")
    merged = run_backtest(args.ticker, period=args.period, forward_days=args.forward_days,
                           buy_bar=args.buy_bar, sell_bar=args.sell_bar,
                           weight_pattern=args.weight_pattern,
                           weight_indicators=args.weight_indicators,
                           extreme_fear_mode=args.extreme_fear_mode)
    summarize(merged, args.forward_days, extreme_fear_mode=args.extreme_fear_mode)

    if args.score_bands:
        print_score_buckets(merged, args.forward_days, bucket=args.band_size)

    if args.exits or args.prob_table or args.sizing:
        res = backtest_exits(merged, stop_mult=args.stop_mult,
                             target_mult=args.target_mult,
                             max_hold_days=args.max_hold_days, side=args.side,
                             short_sma_filter=args.short_sma_filter,
                             confirm_days=args.confirm_days)
        if args.exits:
            print_exit_report(res, args.stop_mult, args.target_mult, args.max_hold_days)
        if args.prob_table:
            print_probability_table(res, bucket=args.prob_bucket)
        if args.sizing:
            sz = compute_position_sizing(res, bucket=args.prob_bucket,
                                         kelly_fraction=args.kelly_fraction)
            print_position_sizing(sz, args.kelly_fraction)


# ======================================================================
# EXIT GEOMETRY COMPARISON
# ======================================================================
# THE PROBLEM THIS ANSWERS. Live exit levels are built from 4h ATR
# (stop ~1.1% of price on BTC). The backtest that validated the 3.0x /
# 1.5x geometry uses DAILY ATR (stop ~2.7%). Both then allow the same
# 15-day hold. So live has been running the backtest's patience with a
# ~2.5x tighter stop — a different trade than the one that was
# validated, under the same name. The first live outcomes (4 stop-outs)
# are consistent with that, though 4 is far too few to prove anything;
# what is solid is the arithmetic, and this measures its consequences on
# history.
#
# WHAT IS COMPARED — the three options actually on the table:
#   live_current  4h ATR,   15-day hold   (what the bot does today)
#   match_backtest daily ATR, 15-day hold  (option 1: live adopts the
#                                           geometry that was validated)
#   match_horizon  4h ATR,   2-day hold    (option 2: keep the tight
#                                           stop, shorten the patience
#                                           to fit it)
#
# METHOD. Every configuration is resolved against the SAME 4h bars, so
# the comparison is apples-to-apples and the only thing varying is the
# geometry. 4h is the finest data available; resolving at that
# granularity also cuts (does not eliminate) the ambiguous-bar problem,
# since fewer target+stop pairs fall inside one bar.
#
# NO LOOKAHEAD: the ATR used for a signal is the one available at the
# signal bar, never later. Entry is the first 4h bar strictly after the
# daily signal close.
#
# THIS CHANGES NO DEFAULTS. It produces the evidence for a decision that
# stays yours.


def build_4h_atr(bars_4h: pd.DataFrame, period: int = 14) -> pd.Series:
    """4h ATR series aligned to the 4h bar index."""
    return cf.compute_atr(bars_4h, period=period)


def resolve_on_4h(bars_4h: pd.DataFrame, entry_ts, entry: float,
                   target: float, stop: float, is_long: bool,
                   max_bars: int) -> dict:
    """Walk 4h bars strictly after entry_ts. Same pessimistic rules as
    everywhere else: both touched in one bar counts as a stop."""
    fwd = bars_4h[bars_4h.index > entry_ts].iloc[:max_bars]
    if fwd.empty:
        return {"outcome": None, "bars": 0, "pnl_r": None, "mfe": 0.0}
    tgt_dist, stop_dist = abs(target - entry), abs(entry - stop)
    mfe = 0.0
    for n, (_, row) in enumerate(fwd.iterrows(), 1):
        hi, lo = row["High"], row["Low"]
        fav = (hi - entry) if is_long else (entry - lo)
        if tgt_dist:
            mfe = max(mfe, fav / tgt_dist)
        hit_t = hi >= target if is_long else lo <= target
        hit_s = lo <= stop if is_long else hi >= stop
        if hit_t and hit_s:
            return {"outcome": "ambiguous_stop", "bars": n, "pnl_r": -1.0, "mfe": mfe}
        if hit_t:
            return {"outcome": "target", "bars": n,
                    "pnl_r": (tgt_dist / stop_dist) if stop_dist else float("nan"),
                    "mfe": mfe}
        if hit_s:
            return {"outcome": "stop", "bars": n, "pnl_r": -1.0, "mfe": mfe}
    if len(fwd) < max_bars:
        return {"outcome": None, "bars": len(fwd), "pnl_r": None, "mfe": mfe}
    last = fwd.iloc[-1]["Close"]
    pnl = ((last - entry) if is_long else (entry - last))
    return {"outcome": "timeout", "bars": len(fwd),
            "pnl_r": (pnl / stop_dist) if stop_dist else float("nan"), "mfe": mfe}


def backtest_exit_geometry(merged: pd.DataFrame, bars_4h: pd.DataFrame,
                            atr_source: str = "daily",
                            stop_mult: float = 1.5, target_mult: float = 3.0,
                            max_hold_days: float = 15,
                            short_sma_filter: int = 50, confirm_days: int = 2,
                            fee_bps: float = 10.0, slippage_bps: float = 5.0,
                            bars_per_day: int = 6) -> dict:
    """Same signals, one geometry knob changed, resolved on 4h bars."""
    if atr_source not in ("daily", "4h"):
        raise ValueError("atr_source must be 'daily' or '4h'")
    df = merged.dropna(subset=["High", "Low", "Close"]).copy()
    df["_atr_daily"] = cf.compute_atr(df, period=14)
    if short_sma_filter and short_sma_filter > 0:
        df["_trend_sma"] = df["Close"].rolling(short_sma_filter).mean()
    atr4 = build_4h_atr(bars_4h)
    max_bars = max(1, int(max_hold_days * bars_per_day))
    dirs = df["direction"].tolist()

    def confirmed(i):
        if confirm_days <= 1:
            return True
        if i < confirm_days - 1:
            return False
        w = dirs[i - confirm_days + 1: i + 1]
        return all(d == w[-1] for d in w)

    trades = []
    for i, (day, row) in enumerate(df.iterrows()):
        if not confirmed(i):
            continue
        d = row["direction"]
        if d not in ("BUY", "STRONG_BUY", "SELL", "STRONG_SELL"):
            continue
        if (short_sma_filter and d in ("SELL", "STRONG_SELL")
                and not (row.get("_trend_sma") == row.get("_trend_sma")
                         and row["Close"] < row["_trend_sma"])):
            continue
        # Entry: first 4h bar strictly after the daily close that produced
        # the signal. Anything earlier would be lookahead.
        entry_ts = pd.Timestamp(day).normalize() + pd.Timedelta(hours=24)
        if atr_source == "daily":
            atr = row["_atr_daily"]
        else:
            prior = atr4[atr4.index <= entry_ts]
            atr = prior.iloc[-1] if len(prior) else float("nan")
        if not (atr == atr) or atr <= 0:
            continue
        lvl = cf.compute_exit_levels(row["Close"], d, atr,
                                     stop_mult=stop_mult, target_mult=target_mult)
        if not lvl.get("applicable"):
            continue
        entry, target, stop = lvl["entry"], lvl["target"], lvl["stop"]
        is_long = lvl["side"] == "long"
        r = resolve_on_4h(bars_4h, entry_ts, entry, target, stop, is_long, max_bars)
        if r["outcome"] is None:
            continue  # still open at the end of history — not a result
        stop_frac = abs(entry - stop) / entry if entry else float("nan")
        cost_r = ((2.0 * (fee_bps + slippage_bps) / 1e4) / stop_frac
                  if stop_frac and stop_frac == stop_frac else 0.0)
        trades.append({"date": day, "direction": d, "outcome": r["outcome"],
                       "score": float(row.get("combined_final_score", float("nan"))),
                       "pnl_r": round(r["pnl_r"], 3),
                       "cost_r": round(cost_r, 4),
                       "pnl_r_net": round(r["pnl_r"] - cost_r, 3),
                       "bars_held": r["bars"],
                       "days_held": round(r["bars"] / bars_per_day, 2),
                       "stop_pct": round(stop_frac * 100, 3),
                       "mfe_pct_of_target": round(r["mfe"] * 100, 1)})
    if not trades:
        return {"n": 0, "trades": []}
    return stats_from_trades(trades)


def stats_from_trades(trades: list) -> dict:
    """Same summary dict backtest_exit_geometry returns, computed from any
    trade list — including a BUY-only or SELL-only subset of one it
    already produced. Keeps 'BUY-side only' analysis using the exact same
    arithmetic as everything else, instead of a parallel implementation
    that could silently drift."""
    if not trades:
        return {"n": 0, "trades": []}
    t = pd.DataFrame(trades)
    return {"n": len(t),
            "target_rate": (t["outcome"] == "target").mean(),
            "stop_rate": t["outcome"].isin(["stop", "ambiguous_stop"]).mean(),
            "ambiguous_n": int((t["outcome"] == "ambiguous_stop").sum()),
            "timeout_rate": (t["outcome"] == "timeout").mean(),
            "expectancy_r": t["pnl_r"].mean(),
            "expectancy_r_net": t["pnl_r_net"].mean(),
            "avg_cost_r": t["cost_r"].mean(),
            "avg_stop_pct": t["stop_pct"].mean(),
            "avg_days_held": t["days_held"].mean(),
            "trades": trades}


GEOMETRY_CONFIGS = {
    "live_current":   {"atr_source": "4h",    "max_hold_days": 15,
                       "label": "4h ATR, 15d hold (what the bot does now)"},
    "match_backtest": {"atr_source": "daily", "max_hold_days": 15,
                       "label": "OPTION 1: daily ATR, 15d hold"},
    "match_horizon":  {"atr_source": "4h",    "max_hold_days": 2,
                       "label": "OPTION 2: 4h ATR, 2d hold"},
}


def compare_exit_geometries(results: dict, min_n: int = 15) -> str:
    """Render the comparison. Refuses to name a winner on thin data, and
    judges on NET expectancy."""
    lines = ["", "EXIT GEOMETRY COMPARISON", "=" * 78,
             f"{'config':<16}{'n':>5}{'stop%':>8}{'target':>8}{'timeout':>9}"
             f"{'gross':>9}{'NET':>9}{'avg hold':>10}"]
    lines.append("-" * 78)
    for key, r in results.items():
        if not r.get("n"):
            lines.append(f"{key:<16}{'0':>5}   (no trades)")
            continue
        lines.append(
            f"{key:<16}{r['n']:>5}{r['avg_stop_pct']:>7.2f}%"
            f"{r['target_rate']*100:>7.0f}%{r['timeout_rate']*100:>8.0f}%"
            f"{r['expectancy_r']:>+9.3f}{r['expectancy_r_net']:>+9.3f}"
            f"{r['avg_days_held']:>9.1f}d")
    lines.append("")
    usable = {k: r for k, r in results.items() if r.get("n", 0) >= min_n}
    if len(usable) < 2:
        lines.append(f"INSUFFICIENT: fewer than 2 configs reached {min_n} trades. "
                     f"No comparison is honest yet.")
        return "\n".join(lines)
    best = max(usable, key=lambda k: usable[k]["expectancy_r_net"])
    cur = results.get("live_current", {})
    lines.append(f"Best NET expectancy: {best} "
                 f"({usable[best]['expectancy_r_net']:+.3f}R over {usable[best]['n']} trades)")
    if cur.get("n", 0) >= min_n and best != "live_current":
        gap = usable[best]["expectancy_r_net"] - cur["expectancy_r_net"]
        lines.append(f"  vs live_current: {gap:+.3f}R per trade difference")
    lines += ["",
              "READ THIS BEFORE ACTING:",
              "- These configs were compared on the SAME history the buy bar,",
              "  the persistence filter and the SMA filter were tuned on. A",
              "  winner here is a candidate, not a validated choice.",
              "- Confirm any winner with:  pipeline.py walkforward  (folds) and",
              "  robustness (split-sample) before changing live behaviour.",
              "- NET is the column that matters; a tighter stop pays more cost",
              "  per R, which is exactly what separates option 2 from option 1.",
              "- Nothing was changed by this run."]
    return "\n".join(lines)


def main_exitgeometry():
    parser = argparse.ArgumentParser(
        description="Compare live vs backtest exit geometries on history")
    parser.add_argument("ticker")
    parser.add_argument("--years", type=float, default=2.0)
    parser.add_argument("--confirm-days", type=int, default=2)
    parser.add_argument("--short-sma-filter", type=int, default=50)
    parser.add_argument("--stop-mult", type=float, default=1.5)
    parser.add_argument("--target-mult", type=float, default=3.0)
    parser.add_argument("--fee-bps", type=float, default=2.0,
                        help="Per side. Binance.US spot taker ~2bps, maker 0.")
    parser.add_argument("--slippage-bps", type=float, default=2.0, help="Per side.")
    parser.add_argument("--hold-sweep", default="",
                        help="Extra 4h-ATR hold budgets in days, e.g. 1,2,3,5")
    parser.add_argument("--unlock-lockbox", action="store_true")
    args = parser.parse_args()

    yf_period = next((p for y, p in ((1, "1y"), (2, "2y"), (5, "5y"), (10, "10y"))
                      if args.years <= y), "max")
    n_4h = min(int(args.years * 365 * 6 * 1.15), 30000)
    merged = run_backtest(args.ticker, period=yf_period, squeeze_bars=n_4h)
    merged = apply_lockbox(merged, unlock=args.unlock_lockbox)
    print(f"Pulling {n_4h} 4h bars for exit resolution...")
    bars_4h = cf.fetch_klines_paginated(cf.to_binance_symbol(args.ticker),
                                        interval="4h", target_bars=n_4h)

    configs = dict(GEOMETRY_CONFIGS)
    for d in [x for x in args.hold_sweep.split(",") if x.strip()]:
        configs[f"4h_atr_{d}d"] = {"atr_source": "4h", "max_hold_days": float(d),
                                   "label": f"4h ATR, {d}d hold"}
    results = {}
    for key, cfg in configs.items():
        print(f"  {key}: {cfg['label']}")
        results[key] = backtest_exit_geometry(
            merged, bars_4h, atr_source=cfg["atr_source"],
            stop_mult=args.stop_mult, target_mult=args.target_mult,
            max_hold_days=cfg["max_hold_days"],
            short_sma_filter=args.short_sma_filter,
            confirm_days=args.confirm_days,
            fee_bps=args.fee_bps, slippage_bps=args.slippage_bps)
    print(compare_exit_geometries(results))
    print(cost_sensitivity(results))


# ======================================================================
# EARNINGS OPTIMIZATION — where the money actually leaks
# ======================================================================
# CONTEXT. The 4-year geometry comparison put the live config's NET edge
# at +0.089R over 326 trades — about one standard error from zero. No
# parameter sweep manufactures alpha out of that. What is mathematically
# certain is where the existing edge LEAKS:
#
#   1. FRICTION. Live geometry pays ~0.154R/trade at 30bps round trip —
#      63% of gross. The breakeven between geometries sits near 33bps,
#      so the user's actual fee tier decides more than any knob here.
#      -> cost_sensitivity(): NET at every plausible fee level, so the
#         decision is read off a table instead of argued about.
#   2. DEAD BANDS. If the edge is concentrated in some score bands, the
#      signals published from the other bands are noise with fees.
#      -> band_edge_analysis(): which bands carry net-positive
#         expectancy, with min_n honesty.
#   3. UNVALIDATED KNOB-TURNING. Any config found by searching the same
#      history is a candidate, not an answer.
#      -> main_optimize(): grid-search on SEALED data only, then the top
#         candidates must survive walk-forward folds INCLUDING beating
#         the current live config fold-by-fold before the word
#         "recommend" appears. Anything less prints as "candidate".
#
# Nothing here changes live behavior. This is a signal service: its
# earnings potential IS the net expectancy of what it publishes, and the
# fastest way to raise that is to stop publishing negative-EV trades and
# stop pretending fees are zero — not to find a magic parameter.

COST_LEVELS_BPS = (0, 10, 20, 30, 40, 60, 80)   # round trip


def cost_sensitivity(results: dict, levels=COST_LEVELS_BPS) -> str:
    """NET expectancy of each geometry config at each round-trip cost.
    Pure arithmetic on the recorded trades — cost_r scales linearly with
    bps, so net(c) = gross - (c/1e4)/stop_frac per trade."""
    lines = ["", "COST SENSITIVITY (net R/trade by round-trip cost)",
             "=" * 72,
             f"{'config':<16}" + "".join(f"{c:>7}bp" for c in levels)]
    lines.append("-" * 72)
    breakevens = {}
    for key, r in results.items():
        trades = r.get("trades", [])
        if not trades:
            continue
        row = f"{key:<16}"
        nets = []
        for c in levels:
            net = sum(t["pnl_r"] - (c / 1e4) / (t["stop_pct"] / 100)
                      for t in trades) / len(trades)
            nets.append(net)
            row += f"{net:>+9.3f}"
        lines.append(row)
        # linear in c -> exact breakeven where net crosses 0
        g = sum(t["pnl_r"] for t in trades) / len(trades)
        k = sum(1.0 / (t["stop_pct"] / 100) for t in trades) / len(trades) / 1e4
        breakevens[key] = g / k if k else float("inf")
    lines.append("")
    for key, be in sorted(breakevens.items(), key=lambda x: -x[1]):
        if be <= 0:
            lines.append(f"  {key}: gross is negative — no fee level saves it")
        else:
            lines.append(f"  {key}: edge survives up to ~{be:.0f}bps round trip")
    lines += ["", "  Find your ACTUAL Binance.US taker fee and read your row.",
              "  If you can enter with maker/limit orders instead of market",
              "  orders, the round trip can drop dramatically - that single",
              "  change likely beats every parameter in this file."]
    return "\n".join(lines)


def band_edge_analysis(trades: list, min_n: int = 20,
                        bucket: float = 10.0) -> dict:
    """Which score bands carry net-positive expectancy. Bands below min_n
    are 'insufficient', never included in the keep-list."""
    bands = {}
    for t in trades:
        s = t.get("score")
        if s != s:
            continue
        b = int(s // bucket * bucket)
        bands.setdefault(b, []).append(t)
    out = {}
    for b, ts in sorted(bands.items()):
        net = sum(t.get("pnl_r_net", t["pnl_r"]) for t in ts) / len(ts)
        out[b] = {"n": len(ts), "net_r": round(net, 3),
                  "status": ("insufficient" if len(ts) < min_n else
                             "keep" if net > 0 else "drop")}
    return out


def render_band_analysis(bands: dict, bucket: float = 10.0) -> str:
    lines = ["", "EDGE CONCENTRATION BY SCORE BAND", "=" * 50,
             f"{'band':<12}{'n':>6}{'net R':>10}   status"]
    lines.append("-" * 50)
    kept, dropped = 0, 0
    for b, v in bands.items():
        lines.append(f"{b:>3}-{int(b+bucket):<7}{v['n']:>6}{v['net_r']:>+10.3f}   {v['status']}")
        if v["status"] == "keep":
            kept += v["n"]
        elif v["status"] == "drop":
            dropped += v["n"]
    if dropped:
        lines += ["", f"  {dropped} of {kept+dropped} decided trades sit in "
                      f"negative-net bands. Publishing those signals costs",
                  "  followers money in expectation. The empirical calibration",
                  "  table already exists for exactly this - the cheapest",
                  "  earnings improvement is not publishing the drop-bands."]
    return "\n".join(lines)


def _geometry_grid():
    grid = []
    for atr_source in ("4h", "daily"):
        for hold in (2, 5, 10, 15):
            for confirm in (1, 2, 3):
                grid.append({"atr_source": atr_source, "max_hold_days": hold,
                             "confirm_days": confirm,
                             "key": f"{atr_source}atr_h{hold}_c{confirm}"})
    return grid


def main_optimize():
    parser = argparse.ArgumentParser(
        description="Search exit configs on SEALED data, then walk-forward "
                    "validate the leaders. Prints candidates; changes nothing.")
    parser.add_argument("ticker")
    parser.add_argument("--years", type=float, default=4.0)
    parser.add_argument("--fee-bps", type=float, default=2.0,
                        help="Per side. Binance.US spot taker ~2bps, maker 0.")
    parser.add_argument("--slippage-bps", type=float, default=2.0, help="Per side.")
    parser.add_argument("--min-n", type=int, default=40)
    parser.add_argument("--folds", type=int, default=4)
    parser.add_argument("--top", type=int, default=3)
    parser.add_argument("--direction", choices=("buy", "sell"), default=None,
                        help="Restrict every stage (grid, folds, bands, cost "
                             "table) to BUY/STRONG_BUY or SELL/STRONG_SELL. "
                             "Default: both combined.")
    args = parser.parse_args()

    yf_period = next((p for y, p in ((1, "1y"), (2, "2y"), (5, "5y"), (10, "10y"))
                      if args.years <= y), "max")
    n_4h = min(int(args.years * 365 * 6 * 1.15), 30000)
    merged = run_backtest(args.ticker, period=yf_period, squeeze_bars=n_4h)
    cutoff = pd.Timestamp.now().normalize() - pd.Timedelta(days=int(args.years * 365))
    merged = merged[merged.index >= cutoff]
    merged = apply_lockbox(merged)          # NEVER unlocked here: this is a search
    bars_4h = cf.fetch_klines_paginated(cf.to_binance_symbol(args.ticker),
                                        interval="4h", target_bars=n_4h)

    # Single chokepoint: every stage (grid search, fold validation, band
    # analysis, cost table) reads results through run_cfg, so filtering
    # here keeps them all consistent. min_n still applies AFTER the
    # filter, which is the honest order — a config that only clears the
    # threshold by counting trades you are excluding has not cleared it.
    _wanted = ({"BUY", "STRONG_BUY"} if args.direction == "buy" else
               {"SELL", "STRONG_SELL"} if args.direction == "sell" else None)

    def run_cfg(frame, cfg):
        r = backtest_exit_geometry(
            frame, bars_4h, atr_source=cfg["atr_source"],
            max_hold_days=cfg["max_hold_days"], confirm_days=cfg["confirm_days"],
            fee_bps=args.fee_bps, slippage_bps=args.slippage_bps)
        if _wanted is None:
            return r
        return stats_from_trades([t for t in r.get("trades", [])
                                  if t["direction"] in _wanted])

    if args.direction:
        print(f"\n[{args.direction.upper()} ONLY] every stage below is "
              f"restricted to {args.direction} trades")

    print(f"\nSTAGE 1 — grid search on sealed history "
          f"({len(_geometry_grid())} configs, min n={args.min_n})")
    baseline_cfg = {"atr_source": "4h", "max_hold_days": 15, "confirm_days": 2,
                    "key": "live_current"}
    scored = []
    for cfg in _geometry_grid():
        r = run_cfg(merged, cfg)
        if r.get("n", 0) >= args.min_n:
            scored.append((cfg, r))
            print(f"  {cfg['key']:<18} n={r['n']:<5} net {r['expectancy_r_net']:+.3f}R")
        else:
            print(f"  {cfg['key']:<18} n={r.get('n',0):<5} (below min_n, excluded)")
    base = run_cfg(merged, baseline_cfg)
    print(f"  {'live_current':<18} n={base.get('n',0):<5} "
          f"net {base.get('expectancy_r_net', float('nan')):+.3f}R   <- baseline")
    if not scored:
        print("\nNo config reached min_n. Nothing to validate.")
        return
    scored.sort(key=lambda x: -x[1]["expectancy_r_net"])
    leaders = scored[:args.top]

    print(f"\nSTAGE 2 — walk-forward validation of top {len(leaders)} "
          f"({args.folds} folds; must beat live_current fold-by-fold)")
    folds = walkforward_folds(merged, args.folds)
    base_folds = [run_cfg(f, baseline_cfg) for f in folds]
    recommended = None
    for cfg, insample in leaders:
        fold_res = [run_cfg(f, cfg) for f in folds]
        v = walkforward_verdict(fold_res)
        beats = sum(1 for fr, br in zip(fold_res, base_folds)
                    if fr.get("n", 0) >= 10 and br.get("n", 0) >= 10
                    and fr["expectancy_r_net"] > br["expectancy_r_net"])
        counted = sum(1 for fr, br in zip(fold_res, base_folds)
                      if fr.get("n", 0) >= 10 and br.get("n", 0) >= 10)
        per_fold = " ".join(f"{fr.get('expectancy_r_net', float('nan')):+.2f}"
                            if fr.get("n", 0) >= 10 else "thin"
                            for fr in fold_res)
        print(f"  {cfg['key']:<18} in-sample {insample['expectancy_r_net']:+.3f}R | "
              f"folds [{per_fold}] | {v['verdict']} | beats baseline {beats}/{counted}")
        # PRE-REGISTERED BAR: generalizes on its own AND beats the current
        # config in every counted fold. Anything less is a candidate only.
        if (recommended is None and v["verdict"] == "GENERALIZES"
                and counted >= 2 and beats == counted):
            recommended = cfg

    print()
    if recommended:
        print(f"RECOMMENDED CANDIDATE: {recommended['key']}")
        print("  It generalized across folds and beat live_current in every")
        print("  counted fold — on SEALED data. Before changing the bot:")
        print(f"  1. replicate on another ticker (optimize ETH)")
        print(f"  2. only then consider changing live defaults")
    else:
        print("NO CONFIG EARNED A RECOMMENDATION. The honest summary: nothing")
        print("in this grid reliably beats what the bot already does. That is")
        print("a real answer — the money is in costs and band selection, not")
        print("in these knobs.")

    print(render_band_analysis(band_edge_analysis(base.get("trades", []))))
    both = {"live_current": base}
    both.update({cfg["key"]: r for cfg, r in leaders})
    print(cost_sensitivity(both))


# ======================================================================
# LOCKBOX + WALK-FORWARD (weaknesses #1 and #2)
# ======================================================================
# Every threshold in this model was tuned against data that overlaps
# every other threshold's validation. Two standard defenses from real
# quant practice, adapted:
#
# LOCKBOX: the most recent LOCKBOX_MONTHS of data are sealed. Tuning
# searches (mlsweep) exclude them BY DEFAULT, so there is always a
# stretch of data no search has ever touched. Opening it (--unlock-
# lockbox) is a one-way door per question asked of it — once a config
# has been chosen by looking at lockbox data, that data can never again
# serve as out-of-sample for that choice. The code cannot enforce the
# one-way part; it can enforce the default and make opening it loud.
#
# WALK-FORWARD: evaluate the FIXED production config on K sequential,
# non-overlapping folds. No tuning inside — this answers exactly one
# question: does the config that was chosen once keep working across
# regimes it was not chosen on? An edge present in 4/4 folds is a very
# different object from the same average edge concentrated in 1.

LOCKBOX_MONTHS = 6


def apply_lockbox(df: pd.DataFrame, months: int = LOCKBOX_MONTHS,
                   unlock: bool = False, now=None) -> pd.DataFrame:
    """Trim the sealed window off the end of a time-indexed frame."""
    if unlock or df is None or len(df) == 0 or months <= 0:
        if unlock:
            print("  [LOCKBOX] *** UNLOCKED — this run consumes holdout data. "
                  "Whatever is decided from it cannot be re-validated on it. ***")
        return df
    cutoff = pd.Timestamp.now().normalize() - pd.DateOffset(months=months)
    kept = df[df.index < cutoff]
    print(f"  [LOCKBOX] sealed: excluding data on/after {cutoff.date()} "
          f"({len(df) - len(kept)} rows held out; --unlock-lockbox to open)")
    return kept


def walkforward_folds(merged: pd.DataFrame, n_folds: int = 4) -> list:
    """Split a time-indexed frame into sequential, equal-duration folds."""
    if merged is None or len(merged) == 0 or n_folds < 2:
        return [merged] if merged is not None and len(merged) else []
    start, end = merged.index.min(), merged.index.max()
    edges = pd.date_range(start, end, periods=n_folds + 1)
    return [merged[(merged.index >= edges[i]) & (merged.index < edges[i + 1])]
            if i < n_folds - 1 else merged[merged.index >= edges[i]]
            for i in range(n_folds)]


def walkforward_verdict(fold_results: list, min_n: int = 10) -> dict:
    """Folds with n>=min_n count; the edge 'generalizes' only if NET
    expectancy is positive in EVERY counted fold, and it is INSUFFICIENT
    if fewer than 2 folds have enough trades."""
    counted = [f for f in fold_results if f.get("n", 0) >= min_n]
    if len(counted) < 2:
        return {"verdict": "INSUFFICIENT_DATA", "folds_counted": len(counted),
                "folds_total": len(fold_results)}
    pos = sum(1 for f in counted
              if f.get("expectancy_r_net", f.get("expectancy_r", 0)) > 0)
    verdict = ("GENERALIZES" if pos == len(counted) else
               "REGIME_DEPENDENT" if pos > 0 else "NO_EDGE")
    return {"verdict": verdict, "folds_positive": pos,
            "folds_counted": len(counted), "folds_total": len(fold_results)}


LIVE_GEOMETRY = {"atr_source": "4h", "max_hold_days": 15, "stop_mult": 1.5,
                 "target_mult": 3.0, "confirm_days": 2, "short_sma_filter": 50}
# ^ SINGLE SOURCE OF TRUTH for what the live bot actually does. Validation
# commands read from this instead of hardcoding their own assumptions.
#
# THE BUG THIS FIXES: walkforward called backtest_exits, which computes
# DAILY ATR. So it was validating the match_backtest geometry (6.03%
# stops, 9.2d holds) while the bot runs the 4h geometry (2.43% stops,
# 2.3d holds). The REGIME_DEPENDENT verdict was real, but it was a
# verdict about a trade the bot never places. Same signals, different
# strategy. Now the default is the live geometry; --atr-source daily
# reproduces the old numbers.


def evaluate_geometry_folds(merged, bars_4h, folds, atr_source, max_hold_days,
                             stop_mult, target_mult, confirm_days,
                             short_sma_filter, fee_bps, slippage_bps,
                             verbose=True, direction=None):
    """Run ONE fixed geometry across sequential folds. No tuning inside.

    direction: None (all trades), 'buy' (BUY/STRONG_BUY only), or 'sell'
    (SELL/STRONG_SELL only). Filtering happens AFTER backtest_exit_geometry
    runs, on its trade list, via stats_from_trades — so a BUY-only report
    uses the identical arithmetic as everything else, just a subset of
    trades. It does not change signal generation or which bars are
    scanned; a SELL-heavy fold with 0 BUY trades will show n=0."""
    if direction not in (None, "buy", "sell"):
        raise ValueError("direction must be None, 'buy', or 'sell'")
    wanted = ({"BUY", "STRONG_BUY"} if direction == "buy" else
              {"SELL", "STRONG_SELL"} if direction == "sell" else None)
    results = []
    for k, fold in enumerate(walkforward_folds(merged, folds), 1):
        if len(fold) == 0:
            results.append({"n": 0})
            if verbose:
                print(f"  fold {k}: empty")
            continue
        r = backtest_exit_geometry(
            fold, bars_4h, atr_source=atr_source, stop_mult=stop_mult,
            target_mult=target_mult, max_hold_days=max_hold_days,
            short_sma_filter=short_sma_filter, confirm_days=confirm_days,
            fee_bps=fee_bps, slippage_bps=slippage_bps)
        if wanted is not None:
            sub = [t for t in r.get("trades", []) if t["direction"] in wanted]
            r = stats_from_trades(sub)
        results.append(r)
        if verbose:
            if r.get("n", 0):
                print(f"  fold {k} ({fold.index.min().date()} → "
                      f"{fold.index.max().date()}): n={r['n']}, "
                      f"stop {r['avg_stop_pct']:.2f}%, "
                      f"gross {r['expectancy_r']:+.3f}R, "
                      f"NET {r['expectancy_r_net']:+.3f}R, "
                      f"hold {r['avg_days_held']:.1f}d")
            else:
                print(f"  fold {k}: no trades")
    return results


def concentration_report(results, min_n=10):
    """How much of the edge lives in ONE fold. A strategy whose profit
    vanishes when its best fold is removed has not shown an edge — it has
    shown one good stretch. This is the number the BTC run made
    unavoidable (+0.631R in fold 4 vs -0.12R across the other three)."""
    counted = [r for r in results if r.get("n", 0) >= min_n]
    if len(counted) < 3:
        return "  concentration: needs 3+ counted folds to assess"
    tot_r = sum(r["expectancy_r_net"] * r["n"] for r in counted)
    tot_n = sum(r["n"] for r in counted)
    best = max(counted, key=lambda r: r["expectancy_r_net"] * r["n"])
    rest_n = tot_n - best["n"]
    overall = tot_r / tot_n if tot_n else float("nan")
    ex_best = ((tot_r - best["expectancy_r_net"] * best["n"]) / rest_n
               if rest_n else float("nan"))
    verdict = ("CONCENTRATED — the edge is essentially one fold"
               if overall > 0 and ex_best <= 0 else
               "spread across folds" if overall > 0 else "negative overall")
    return (f"  all counted folds:  {overall:+.3f}R over {tot_n} trades\n"
            f"  excluding best fold: {ex_best:+.3f}R over {rest_n} trades\n"
            f"  concentration: {verdict}")


def main_walkforward():
    parser = argparse.ArgumentParser(
        description="Evaluate the FIXED production config on sequential "
                    "non-overlapping folds (no tuning inside)")
    parser.add_argument("tickers", nargs="+")
    parser.add_argument("--years", type=float, default=4.0)
    parser.add_argument("--folds", type=int, default=4)
    parser.add_argument("--unlock-lockbox", action="store_true")
    parser.add_argument("--atr-source", choices=("4h", "daily"),
                        default=LIVE_GEOMETRY["atr_source"],
                        help="Which ATR builds the exit levels. DEFAULT 4h = "
                             "what the live bot does. 'daily' reproduces the "
                             "old (mismatched) numbers.")
    parser.add_argument("--max-hold-days", type=float,
                        default=LIVE_GEOMETRY["max_hold_days"])
    parser.add_argument("--stop-mult", type=float, default=LIVE_GEOMETRY["stop_mult"])
    parser.add_argument("--target-mult", type=float, default=LIVE_GEOMETRY["target_mult"])
    parser.add_argument("--confirm-days", type=int, default=LIVE_GEOMETRY["confirm_days"])
    parser.add_argument("--short-sma-filter", type=int,
                        default=LIVE_GEOMETRY["short_sma_filter"])
    parser.add_argument("--fee-bps", type=float, default=2.0,
                        help="Per side. Binance.US spot taker ~2bps, maker 0.")
    parser.add_argument("--slippage-bps", type=float, default=2.0, help="Per side.")
    parser.add_argument("--compare-geometries", action="store_true",
                        help="Also run the other ATR source for contrast")
    parser.add_argument("--direction", choices=("buy", "sell"), default=None,
                        help="Report only BUY/STRONG_BUY or only "
                             "SELL/STRONG_SELL trades. Default: both combined "
                             "(what live_current has always reported).")
    args = parser.parse_args()

    yf_period = next((p for y, p in ((1, "1y"), (2, "2y"), (5, "5y"), (10, "10y"))
                      if args.years <= y), "max")
    n_4h = min(int(args.years * 365 * 6 * 1.15), 30000)
    cutoff = pd.Timestamp.now().normalize() - pd.Timedelta(days=int(args.years * 365))
    live = (args.atr_source == LIVE_GEOMETRY["atr_source"]
            and args.max_hold_days == LIVE_GEOMETRY["max_hold_days"]
            and args.stop_mult == LIVE_GEOMETRY["stop_mult"]
            and args.target_mult == LIVE_GEOMETRY["target_mult"]
            and args.confirm_days == LIVE_GEOMETRY["confirm_days"]
            and args.short_sma_filter == LIVE_GEOMETRY["short_sma_filter"])

    for ticker in args.tickers:
        rt = 2 * (args.fee_bps + args.slippage_bps)
        print(f"\n=== {ticker} walk-forward ({args.folds} folds, "
              f"{args.atr_source} ATR, {args.max_hold_days:g}d hold, "
              f"net of {rt:g}bps round trip) ===")
        print("  geometry " + ("MATCHES the live bot" if live else
              "DIFFERS FROM the live bot — this verdict is about a trade "
              "the bot does not place"))
        merged = run_backtest(ticker, period=yf_period, squeeze_bars=n_4h)
        merged = merged[merged.index >= cutoff]
        merged = apply_lockbox(merged, unlock=args.unlock_lockbox)
        print(f"Pulling {n_4h} 4h bars for exit resolution...")
        bars_4h = cf.fetch_klines_paginated(cf.to_binance_symbol(ticker),
                                            interval="4h", target_bars=n_4h)

        results = evaluate_geometry_folds(
            merged, bars_4h, args.folds, args.atr_source, args.max_hold_days,
            args.stop_mult, args.target_mult, args.confirm_days,
            args.short_sma_filter, args.fee_bps, args.slippage_bps,
            direction=args.direction)
        v = walkforward_verdict(results)
        dlabel = f" [{args.direction.upper()} ONLY]" if args.direction else ""
        print(f"  VERDICT{dlabel}: {v['verdict']} "
              f"({v.get('folds_positive','—')}/{v['folds_counted']} "
              f"counted folds net-positive)")
        print(concentration_report(results))

        if args.compare_geometries:
            other = "daily" if args.atr_source == "4h" else "4h"
            print(f"\n  --- same folds, {other} ATR for contrast ---")
            r2 = evaluate_geometry_folds(
                merged, bars_4h, args.folds, other, args.max_hold_days,
                args.stop_mult, args.target_mult, args.confirm_days,
                args.short_sma_filter, args.fee_bps, args.slippage_bps,
                direction=args.direction)
            v2 = walkforward_verdict(r2)
            print(f"  VERDICT ({other} ATR){dlabel}: {v2['verdict']} "
                  f"({v2.get('folds_positive','—')}/{v2['folds_counted']})")
            print(concentration_report(r2))


# ======================================================================
# ROBUSTNESS VALIDATION — the honest answer to the 4-year failure
# ======================================================================
# Context: extending the backtest window to ~4 years showed BUY win rate
# falling to ~50% and SELL expectancy flipping sign over 2022-2026,
# meaning the original 2024-2026 validation window may simply have been
# FAVORABLE to the signal. One rescue candidate was identified but not
# acted on: trades entered while VIX was stressed showed strongly
# positive expectancy while normal-VIX trades were negative. A two-ticker
# check is NOT replication for a market-wide variable like VIX (both
# tickers see the same VIX days), so the bar here is deliberately higher:
#
#   The VIX regime edge counts as REPLICATED only if, with n>=MIN_N
#   trades per cell, stressed expectancy beats normal expectancy AND is
#   positive in BOTH time halves of the window on EVERY ticker tested
#   (>=3 tickers recommended: e.g. BTC ETH SOL).
#
# The short side gets its own verdict: shorts (with the production
# 50-SMA trend filter) must show positive expectancy in both halves on a
# majority of tickers, otherwise the honest recommendation is long-only.
#
# Nothing here changes any default. It produces the evidence; the
# decision stays with you.

ROBUSTNESS_MIN_N = 10  # below this a cell is "insufficient data", not a pass/fail


def attach_vix_to_trades(trades: list, merged: pd.DataFrame) -> list:
    """Annotate each exit-backtest trade with the VIX level on its entry
    date (from the merged backtest frame). Trades whose date is missing
    from the frame get vix_level=NaN and are excluded from VIX splits."""
    vix_by_date = merged["vix_level"].to_dict() if "vix_level" in merged else {}
    out = []
    for t in trades:
        t = dict(t)
        t["vix_level"] = float(vix_by_date.get(t["date"], float("nan")))
        out.append(t)
    return out


def subset_stats(trades: list) -> dict:
    """Summary stats for a list of trade dicts. Pure and offline.

    Judges on NET pnl (pnl_r_net) when the trades carry it — the same
    standard as walkforward/optimize/overlays. Falls back to gross for
    old-style trades that predate cost modelling, so historical tests
    still pass, but any modern (geometry) trade stream is judged after
    costs like everything else."""
    n = len(trades)
    if n == 0:
        return {"n": 0}
    wins = sum(1 for t in trades if t["outcome"] == "target")
    stops = sum(1 for t in trades if t["outcome"] in ("stop", "ambiguous_stop"))
    timeouts = sum(1 for t in trades if t["outcome"] == "timeout")
    exp = sum(t.get("pnl_r_net", t["pnl_r"]) for t in trades) / n
    return {"n": n, "target_rate": wins / n, "stop_rate": stops / n,
            "timeout_rate": timeouts / n, "expectancy_r": exp}


def split_trades(trades: list, vix_threshold: float) -> dict:
    """Split annotated trades into the cells the verdicts need. Time halves
    are split at the midpoint of the DATE RANGE (not trade count), so a
    quiet half stays a small-n half instead of being padded."""
    cells = {"all": trades,
             "long": [t for t in trades if t["direction"] in ("BUY", "STRONG_BUY")],
             "short": [t for t in trades if t["direction"] in ("SELL", "STRONG_SELL")]}
    if trades:
        dates = sorted(t["date"] for t in trades)
        mid = dates[0] + (dates[-1] - dates[0]) / 2
        for half, keep in (("h1", lambda t: t["date"] <= mid),
                            ("h2", lambda t: t["date"] > mid)):
            sub = [t for t in trades if keep(t)]
            cells[half] = sub
            cells[f"{half}_long"] = [t for t in sub if t["direction"] in ("BUY", "STRONG_BUY")]
            cells[f"{half}_short"] = [t for t in sub if t["direction"] in ("SELL", "STRONG_SELL")]
            cells[f"{half}_vix_stressed"] = [t for t in sub
                                             if t["vix_level"] == t["vix_level"]
                                             and t["vix_level"] >= vix_threshold]
            cells[f"{half}_vix_normal"] = [t for t in sub
                                           if t["vix_level"] == t["vix_level"]
                                           and t["vix_level"] < vix_threshold]
        cells["vix_stressed"] = [t for t in trades if t["vix_level"] == t["vix_level"]
                                 and t["vix_level"] >= vix_threshold]
        cells["vix_normal"] = [t for t in trades if t["vix_level"] == t["vix_level"]
                               and t["vix_level"] < vix_threshold]
    return cells


def vix_replication_verdict(per_ticker_cells: dict, min_n: int = ROBUSTNESS_MIN_N) -> dict:
    """The pre-registered test. For every ticker and both halves:
    stressed expectancy must beat normal expectancy AND be positive,
    with n>=min_n in both cells. Any insufficient cell -> the whole
    verdict is INSUFFICIENT (never a pass by default)."""
    checks, insufficient = [], False
    for ticker, cells in per_ticker_cells.items():
        for half in ("h1", "h2"):
            s = subset_stats(cells.get(f"{half}_vix_stressed", []))
            m = subset_stats(cells.get(f"{half}_vix_normal", []))
            if s["n"] < min_n or m["n"] < min_n:
                checks.append({"ticker": ticker, "half": half, "status": "insufficient",
                               "n_stressed": s["n"], "n_normal": m["n"]})
                insufficient = True
                continue
            ok = (s["expectancy_r"] > m["expectancy_r"]) and (s["expectancy_r"] > 0)
            checks.append({"ticker": ticker, "half": half,
                           "status": "pass" if ok else "fail",
                           "stressed_exp": round(s["expectancy_r"], 3),
                           "normal_exp": round(m["expectancy_r"], 3),
                           "n_stressed": s["n"], "n_normal": m["n"]})
    if insufficient:
        verdict = "INSUFFICIENT_DATA"
    elif all(c["status"] == "pass" for c in checks):
        verdict = "REPLICATED"
    else:
        verdict = "NOT_REPLICATED"
    return {"verdict": verdict, "checks": checks}


def short_side_verdict(per_ticker_cells: dict, min_n: int = ROBUSTNESS_MIN_N) -> dict:
    """Shorts must be positive-expectancy in BOTH halves on a MAJORITY of
    tickers (with the production trend filter already applied upstream).
    Otherwise the recommendation is long-only."""
    ticker_ok, checks, insufficient = 0, [], False
    for ticker, cells in per_ticker_cells.items():
        halves = []
        for half in ("h1", "h2"):
            st = subset_stats(cells.get(f"{half}_short", []))
            if st["n"] < min_n:
                checks.append({"ticker": ticker, "half": half, "status": "insufficient",
                               "n": st["n"]})
                insufficient = True
                halves.append(None)
            else:
                ok = st["expectancy_r"] > 0
                halves.append(ok)
                checks.append({"ticker": ticker, "half": half,
                               "status": "pass" if ok else "fail",
                               "expectancy_r": round(st["expectancy_r"], 3), "n": st["n"]})
        if all(h is True for h in halves):
            ticker_ok += 1
    n_tickers = len(per_ticker_cells)
    if insufficient and ticker_ok <= n_tickers / 2:
        verdict = "INSUFFICIENT_DATA"
    elif ticker_ok > n_tickers / 2:
        verdict = "SHORTS_HOLD_UP"
    else:
        verdict = "RECOMMEND_LONG_ONLY"
    return {"verdict": verdict, "tickers_passing": ticker_ok,
            "tickers_total": n_tickers, "checks": checks}


def _fmt_cell(name: str, st: dict) -> str:
    if st["n"] == 0:
        return f"| {name} | 0 | — | — | — | — |"
    return (f"| {name} | {st['n']} | {st['target_rate']*100:.1f}% "
            f"| {st['stop_rate']*100:.1f}% | {st['timeout_rate']*100:.1f}% "
            f"| {st['expectancy_r']:+.3f}R |")


def build_robustness_report(per_ticker_cells: dict, years: float,
                             vix_threshold: float, config_desc: str) -> str:
    """Render the full markdown report. Pure — takes cells, returns text."""
    lines = ["# Robustness Report", "",
             f"Window: last ~{years:g} years · {config_desc}",
             f"VIX stressed threshold: >= {vix_threshold:g} · "
             f"min trades per verdict cell: {ROBUSTNESS_MIN_N}",
             "",
             "Pre-registered criteria (decided BEFORE looking at results):",
             "- VIX edge replicates only if stressed beats normal AND is positive",
             "  in both time halves on every ticker.",
             "- Shorts hold up only if positive in both halves on a majority of tickers.",
             "",
             "No defaults were changed by this run. Evidence only.", ""]
    for ticker, cells in per_ticker_cells.items():
        lines += [f"## {ticker}", "",
                  "| Subset | n | Target | Stop | Timeout | Expectancy |",
                  "|---|---|---|---|---|---|"]
        order = ["all", "long", "short", "h1", "h2", "h1_long", "h2_long",
                 "h1_short", "h2_short", "vix_stressed", "vix_normal",
                 "h1_vix_stressed", "h1_vix_normal", "h2_vix_stressed",
                 "h2_vix_normal"]
        labels = {"all": "All trades", "long": "Long only", "short": "Short only",
                  "h1": "First half", "h2": "Second half",
                  "h1_long": "H1 long", "h2_long": "H2 long",
                  "h1_short": "H1 short", "h2_short": "H2 short",
                  "vix_stressed": f"VIX >= {vix_threshold:g}",
                  "vix_normal": f"VIX < {vix_threshold:g}",
                  "h1_vix_stressed": "H1 VIX stressed", "h1_vix_normal": "H1 VIX normal",
                  "h2_vix_stressed": "H2 VIX stressed", "h2_vix_normal": "H2 VIX normal"}
        for key in order:
            lines.append(_fmt_cell(labels[key], subset_stats(cells.get(key, []))))
        lines.append("")
    vv = vix_replication_verdict(per_ticker_cells)
    sv = short_side_verdict(per_ticker_cells)
    lines += ["## Verdicts", "", f"**VIX regime edge: {vv['verdict']}**", ""]
    for c in vv["checks"]:
        if c["status"] == "insufficient":
            lines.append(f"- {c['ticker']} {c['half']}: insufficient data "
                         f"(stressed n={c['n_stressed']}, normal n={c['n_normal']})")
        else:
            lines.append(f"- {c['ticker']} {c['half']}: {c['status']} "
                         f"(stressed {c['stressed_exp']:+.3f}R n={c['n_stressed']} vs "
                         f"normal {c['normal_exp']:+.3f}R n={c['n_normal']})")
    lines += ["", f"**Short side: {sv['verdict']}** "
                  f"({sv['tickers_passing']}/{sv['tickers_total']} tickers positive "
                  f"in both halves)", ""]
    for c in sv["checks"]:
        if c["status"] == "insufficient":
            lines.append(f"- {c['ticker']} {c['half']}: insufficient data (n={c['n']})")
        else:
            lines.append(f"- {c['ticker']} {c['half']}: {c['status']} "
                         f"({c['expectancy_r']:+.3f}R, n={c['n']})")
    lines += ["", "### How to read this",
              "- REPLICATED means the VIX gate earned the right to become an",
              "  optional entry filter (still your call to enable it).",
              "- NOT_REPLICATED means the +R on stressed days was likely the",
              "  2022 bear market wearing a costume — document it and move on.",
              "- INSUFFICIENT_DATA means no conclusion is honest yet; more",
              "  tickers or a longer window are needed before deciding.", ""]
    return "\n".join(lines)


def main_robustness():
    parser = argparse.ArgumentParser(
        description="Multi-ticker, split-sample robustness validation of the "
                    "exit backtest, incl. the VIX regime rescue candidate")
    parser.add_argument("tickers", nargs="+", help="e.g. BTC ETH SOL")
    parser.add_argument("--years", type=float, default=4.0,
                         help="Window length in years (default 4). Yahoo is "
                              "fetched at the next-larger valid period and "
                              "trimmed, so any value works.")
    parser.add_argument("--vix-threshold", type=float, default=25.0,
                         help="VIX level at/above which a trade counts as "
                              "'stressed' (default 25)")
    parser.add_argument("--confirm-days", type=int, default=2,
                         help="Persistence filter, production default 2")
    parser.add_argument("--short-sma-filter", type=int, default=50,
                         help="Short trend filter SMA, production default 50")
    parser.add_argument("--stop-mult", type=float, default=1.5)
    parser.add_argument("--target-mult", type=float, default=3.0)
    parser.add_argument("--max-hold-days", type=float, default=15)
    parser.add_argument("--atr-source", choices=("4h", "daily"),
                         default=LIVE_GEOMETRY["atr_source"],
                         help="Which ATR builds the exit levels. DEFAULT 4h "
                              "= what the live bot does. This command used "
                              "to hardcode daily ATR — the same "
                              "validation-of-a-trade-the-bot-never-places "
                              "defect walkforward had. 'daily' reproduces "
                              "the old numbers.")
    parser.add_argument("--direction", choices=("buy", "sell"), default=None,
                         help="Restrict all cells to one side. Default: both.")
    parser.add_argument("--fee-bps", type=float, default=2.0,
                         help="Per side. Binance.US spot taker ~2bps, maker 0.")
    parser.add_argument("--slippage-bps", type=float, default=2.0,
                         help="Per side.")
    parser.add_argument("--out", default="docs/robustness.md",
                         help="Markdown report path (default docs/robustness.md)")
    args = parser.parse_args()

    # Smallest valid yfinance period covering the window
    yf_period = next((p for y, p in ((1, "1y"), (2, "2y"), (5, "5y"), (10, "10y"))
                      if args.years <= y), "max")
    squeeze_bars = min(int(args.years * 365 * 6 * 1.15), 30000)
    cutoff = pd.Timestamp.now().normalize() - pd.Timedelta(days=int(args.years * 365))
    wanted = ({"BUY", "STRONG_BUY"} if args.direction == "buy" else
              {"SELL", "STRONG_SELL"} if args.direction == "sell" else None)
    matches_live = (args.atr_source == LIVE_GEOMETRY["atr_source"]
                    and args.max_hold_days == LIVE_GEOMETRY["max_hold_days"]
                    and args.stop_mult == LIVE_GEOMETRY["stop_mult"]
                    and args.target_mult == LIVE_GEOMETRY["target_mult"]
                    and args.confirm_days == LIVE_GEOMETRY["confirm_days"]
                    and args.short_sma_filter == LIVE_GEOMETRY["short_sma_filter"])

    per_ticker_cells = {}
    for ticker in args.tickers:
        print(f"\n=== {ticker}: pulling {args.years:g}y of history ===")
        print("  geometry " + ("MATCHES the live bot" if matches_live else
              "DIFFERS FROM the live bot — verdicts below are about a "
              "trade the bot does not place"))
        merged = run_backtest(ticker, period=yf_period, squeeze_bars=squeeze_bars)
        merged = merged[merged.index >= cutoff]
        print(f"{ticker}: {len(merged)} joined daily rows from "
              f"{merged.index.min().date()} to {merged.index.max().date()}")
        bars_4h = cf.fetch_klines_paginated(cf.to_binance_symbol(ticker),
                                            interval="4h",
                                            target_bars=squeeze_bars)
        res = backtest_exit_geometry(
            merged, bars_4h, atr_source=args.atr_source,
            stop_mult=args.stop_mult, target_mult=args.target_mult,
            max_hold_days=args.max_hold_days,
            short_sma_filter=args.short_sma_filter,
            confirm_days=args.confirm_days,
            fee_bps=args.fee_bps, slippage_bps=args.slippage_bps)
        trades = res.get("trades", [])
        if wanted is not None:
            trades = [t for t in trades if t["direction"] in wanted]
        trades = attach_vix_to_trades(trades, merged)
        per_ticker_cells[ticker] = split_trades(trades, args.vix_threshold)

    config_desc = (f"{args.atr_source} ATR "
                   f"({'LIVE geometry' if matches_live else 'NON-live'}), "
                   f"confirm_days={args.confirm_days}, "
                   f"short_sma_filter={args.short_sma_filter}, "
                   f"exits {args.target_mult:g}x/{args.stop_mult:g}x, "
                   f"max_hold={args.max_hold_days:g}d, "
                   f"net of {2 * (args.fee_bps + args.slippage_bps):g}bps RT"
                   + (f", {args.direction.upper()} only" if args.direction else ""))
    report = build_robustness_report(per_ticker_cells, args.years,
                                      args.vix_threshold, config_desc)
    print("\n" + report)
    if args.out:
        import os
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w") as f:
            f.write(report)
        print(f"\nReport written to {args.out}")


# ======================================================================
# CLI DISPATCHER — subcommands: run / multi / backtest
# ======================================================================

def build_ml_frame(ticker: str, period: str = "3y", with_squeeze: bool = False,
                   interval: str = "4h"):
    """
    Builds the daily indicator frame the ML trains on. With with_squeeze=True,
    joins in Step 1's Bollinger squeeze features (BB_WIDTH_PCTL,
    SQUEEZE_DURATION) resampled from Binance 4h bars — a genuinely different
    SOURCE and TIMEFRAME than the Yahoo daily indicators, so it's new
    information rather than another transform of the same price series.
    """
    yahoo_ticker = to_yahoo_crypto_symbol(ticker)
    df = epm.analyze(yahoo_ticker, period=period)
    if not with_squeeze:
        return df
    symbol = cf.to_binance_symbol(ticker)
    klines = cf.fetch_klines_paginated(symbol, interval=interval, target_bars=4000)
    sq = cf.add_squeeze_features(klines).dropna(subset=["BB_WIDTH_PCTL"])
    daily = sq[["BB_WIDTH_PCTL", "SQUEEZE_DURATION"]].resample("D").last()
    daily.index = daily.index.normalize()
    df.index = pd.to_datetime(df.index).normalize()
    out = df.join(daily, how="left")
    # These names don't match the RSI_/SMA_/_score patterns, so rename them
    # into the _score convention to get picked up by build_feature_target.
    out["squeeze_width_score"] = out["BB_WIDTH_PCTL"]
    out["squeeze_duration_score"] = out["SQUEEZE_DURATION"]
    return out


# Named feature sets, smallest first. The theory being tested: with only
# ~175 EFFECTIVE independent samples (5-day windows overlap 4-in-5), a
# depth-5 XGBoost can memorize noise from 10 correlated features. Fewer,
# conceptually distinct features should generalize better.
FEATURE_SETS = {
    # Real column names (RSI_PERIODS=[5,10,15], SMA_PERIODS=[5,10,20],
    # CMF_20, MFI_14, plus dxy_score/vix_score from the macro side).
    # Each set picks CONCEPTUALLY DISTINCT signals rather than several
    # views of the same thing - the point is to cut correlated inputs,
    # since ~175 effective independent samples can't support 11 features.
    "minimal": ["RSI_15", "MFI_14"],                            # momentum + volume
    "core3":   ["RSI_15", "SMA_20", "MFI_14"],                  # + trend
    "core4":   ["RSI_15", "SMA_20", "MFI_14", "vix_score"],     # + macro
    "core5":   ["RSI_15", "SMA_20", "MFI_14", "vix_score", "CMF_20"],
    "all":     None,   # None = everything build_feature_target finds
}


def _resolve_features(name, frame):
    """Resolve a named feature set against columns actually present."""
    want = FEATURE_SETS.get(name)
    if want is None:
        return None, []
    have = [c for c in want if c in frame.columns]
    missing = [c for c in want if c not in frame.columns]
    if not have:
        # Returning None would silently fall back to ALL features and make
        # the comparison meaningless - flag it loudly instead.
        print(f"  [ERROR] feature set resolved to NOTHING (wanted {want}). "
              f"Available: {sorted(frame.columns)[:15]}...")
    return (have if have else None), missing


def ml_sweep(ticker: str, period: str = "3y", horizons=(5, 7, 10),
             thresholds=(0.010, 0.015, 0.020), squeeze_variants=(False, True),
             feature_sets=("all",), periods=None, unlock_lockbox: bool = False):
    """
    Sweeps ML target definitions and feature sets, reporting HONEST
    out-of-sample holdout AUC for each. AUC is the metric that matters:
    accuracy is inflated by class imbalance (a model can score 90%
    'accuracy' by always predicting the majority class while learning
    nothing). 0.50 = coin flip.
    """
    periods = periods or (period,)
    results = []

    print(f"\n{'=' * 88}")
    print(f"  ML SWEEP — {ticker}   (holdout ROC-AUC; 0.50 = coin flip)")
    print(f"  Testing: fewer features + longer history")
    print(f"{'=' * 88}")
    print(f"{'Period':<8}{'Features':<10}{'NFeat':>6}{'Horizon':>9}{'Thresh':>8}"
          f"{'PosRate':>9}{'AUC':>8}{'TrainN':>8}{'TestN':>7}")
    print("-" * 88)

    for per in periods:
        for sq in squeeze_variants:
            try:
                frame = build_ml_frame(ticker, period=per, with_squeeze=sq)
                frame = apply_lockbox(frame, unlock=unlock_lockbox)
            except Exception as e:
                print(f"{per:<8}frame build FAILED: {type(e).__name__}: {e}")
                continue
            tag_sq = "+sqz" if sq else ""
            for fs_name in feature_sets:
                cols, missing = _resolve_features(fs_name, frame)
                if missing:
                    print(f"  [note] {fs_name}: missing {missing} — using what's available")
                for h in horizons:
                    for t in thresholds:
                        try:
                            r = cf.train_ml_model_with_holdout(
                                frame, lookahead_days=h, threshold_pct=t,
                                feature_cols=cols)
                            auc = r.get("roc_auc")
                            y = r.get("y_test")
                            pos = float(sum(y)) / len(y) if y is not None and len(y) else float("nan")
                            nfeat = len(r.get("feature_cols", []))
                            trn = len(r.get("y_train", []))
                            auc_s = f"{auc:.3f}" if auc is not None and auc == auc else "n/a"
                            star = "  *" if (auc is not None and auc == auc and auc >= 0.58) else ""
                            print(f"{per:<8}{fs_name + tag_sq:<10}{nfeat:>6}{h:>9}{t*100:>7.1f}%"
                                  f"{pos*100:>8.1f}%{auc_s:>8}{trn:>8}{len(y):>7}{star}")
                            results.append({"period": per, "features": fs_name + tag_sq,
                                            "nfeat": nfeat, "horizon": h, "threshold": t,
                                            "auc": auc, "test_n": len(y)})
                        except Exception as e:
                            print(f"{per:<8}{fs_name + tag_sq:<10}{'':>6}{h:>9}{t*100:>7.1f}%"
                                  f"   FAILED: {type(e).__name__}")

    print("-" * 88)
    ok = [r for r in results if r["auc"] is not None and r["auc"] == r["auc"]]
    if ok:
        top = sorted(ok, key=lambda r: -r["auc"])[:5]
        print("  Top 5 by AUC:")
        for r in top:
            print(f"    {r['auc']:.3f}  {r['period']:<5} {r['features']:<10} "
                  f"{r['nfeat']} feat, {r['horizon']}d, {r['threshold']*100:.1f}%")
        print()
        print(f"  PRE-REGISTERED BAR: >= 0.58 on BOTH tickers, SAME config.")
        print(f"  A config winning here but not on the other ticker is a")
        print(f"  multiple-comparisons artifact, not an edge. You are testing")
        print(f"  {len(ok)} combinations - expect a few to look good by chance.")
    print(f"{'=' * 88}\n")
    return results


def main_mlsweep():
    parser = argparse.ArgumentParser(description="Sweep ML target/feature definitions")
    parser.add_argument("ticker")
    parser.add_argument("--period", default="3y")
    parser.add_argument("--horizons", default="5,7,10")
    parser.add_argument("--thresholds", default="0.010,0.015,0.020")
    parser.add_argument("--no-squeeze", action="store_true",
                         help="Skip the squeeze-feature variant (Yahoo-only)")
    parser.add_argument("--periods", default="3y,5y,max",
                         help="History lengths to test (default 3y,5y,max)")
    parser.add_argument("--feature-sets", default="minimal,core3,core4,core5,all",
                         help="Named feature sets: minimal,core3,core4,core5,all")
    parser.add_argument("--unlock-lockbox", action="store_true",
                         help="Sweep INTO the sealed holdout window (loud, one-way)")
    args = parser.parse_args()
    ml_sweep(args.ticker,
             horizons=tuple(int(x) for x in args.horizons.split(",")),
             thresholds=tuple(float(x) for x in args.thresholds.split(",")),
             squeeze_variants=((False,) if args.no_squeeze else (False, True)),
             feature_sets=tuple(args.feature_sets.split(",")),
             periods=tuple(args.periods.split(",")),
             unlock_lockbox=args.unlock_lockbox)



# ======================================================================
# LITERATURE OVERLAYS — established quant filters, parameters fixed by
# the literature, evaluated by the same fold machinery as everything else
# ======================================================================
# WHY THIS EXISTS. The three-ticker walkforward said: ex-best-fold edge
# ~ zero (+0.014 / +0.026 / -0.032), best fold always the most recent.
# The WRONG response is to invent new knobs and tune them on those same
# folds. The defensible middle ground is to test overlays whose form AND
# parameters were fixed by decades of published research on OTHER data,
# so this repo's history had no vote in choosing them:
#
#   trend_200   Long only above the 200d SMA, short only below it.
#               Classic trend filter (Faber 2007); crypto replications
#               find 20-200d trend rules beat buy-and-hold (Le & Ruthbah,
#               Monash 2023). Parameter 200 is the literature's, not ours.
#   tsmom_365   Trade only WITH the sign of the trailing 12-month return
#               (Moskowitz, Ooi & Pedersen 2012 — positive predictor
#               across 58 futures markets). 365 fixed by that paper.
#   tsmom_28    Crypto-specific: 28-day lookback found best in a
#               2013-2023 crypto TSMOM study (AUT 2024), benefit mainly
#               from reduced downside. 28 fixed by that paper.
#   vol_scale   Scale position size by target_vol/realized_vol (Moreira
#               & Muir 2017: "take less risk when volatility is high").
#               HONESTY NOTE: Cederburg et al. 2020 find NO systematic
#               out-of-sample Sharpe improvement across 103 strategies —
#               the robust benefit is drawdown reduction, not alpha. It
#               is included with that caveat, judged like everything else.
#
# WHAT AN OVERLAY MAY DO: drop a trade (gate) or reweight it (sizing).
# It may NOT move entries, exits, or levels — the underlying trade
# stream is exactly what the live bot produces.
#
# PRE-REGISTERED ACCEPTANCE BAR (fixed before looking at results):
#   adopt-candidate only if the overlay improves the EX-BEST-FOLD net
#   expectancy on at least 2 of 3 tickers and degrades no ticker's
#   ex-best by more than 0.02R. Anything else prints as "no".
#   Even then: nothing changes automatically. Ever.

OVERLAY_PARAMS = {"trend_sma": 200, "tsmom_long": 365, "tsmom_short": 28,
                  "vol_window": 20, "vol_target_ann": 0.60, "vol_cap": 1.5,
                  "rvol_window": 20, "rvol_threshold": 1.5,
                  # --- Gate batch 2, REGISTERED 2026-08-06 (hyp. #10-13) ---
                  "atr_expand_period": 14, "atr_expand_lookback": 5,
                  "vix_calm_threshold": 25.0, "near_high_window": 252,
                  "near_high_frac": 0.85, "btc_regime_sma": 50,
                  # --- Gate batch 3, REGISTERED 2026-08-06 (hyp. #14-16) ---
                  "score_rising_days": 3, "strong_close_frac": 0.70,
                  "fresh_signal_cooldown_days": 5,
                  # --- Gate batch 4, REGISTERED 2026-08-06 (hyp. #18-20) ---
                  # DATA-DERIVED, WEAKEST CLASS: these are the INVERSES of
                  # gates that failed unanimously. Inverting a failed
                  # prediction is one step from peeking at the answer, so a
                  # screen pass here means LESS than a screen pass from a
                  # literature-derived gate. Reused thresholds only — no new
                  # numbers were chosen, which is the one thing keeping this
                  # honest.
                  "quiet_rvol_max": 0.70}
# BATCH 3 REGISTERED DIRECTIONS (fixed before results):
#   score_rising : final_score today > final_score 3 sessions ago —
#                  momentum of the SIGNAL itself, not of price (price
#                  self-trend is a dead family) -> rising is BETTER.
#   strong_close : entry-day close in the top 30%% of its own daily
#                  range ((C-L)/(H-L) >= 0.70) — the practitioner
#                  standard for a strong close -> strong is BETTER.
#   fresh_signal : no same-ticker STOP-OUT whose exit fell within the 5
#                  days before this entry — a just-failed breakout
#                  poisons the setup -> fresh is BETTER. Uses only
#                  trades that EXITED before this entry (no lookahead).
# Ledger count after this batch: 16. The screen's false-positive rate
# times sixteen attempts means a pass here is WEAK by construction; the
# gauntlet (4y/5f + 5y) and live outcomes remain the only real bars.
# REGISTERED DIRECTIONS for batch 2, written before any result was seen:
#   atr_expand : breakouts into RISING volatility travel further ->
#                expanding is BETTER. (14d ATR vs 5 sessions ago; both
#                numbers are the standard defaults, not tuned here.)
#   vix_calm   : risk-on conditions favour crypto longs -> VIX < 25 is
#                BETTER. 25 is this repo's own pre-existing "stressed"
#                line (robustness command), chosen long before this gate.
#   near_high  : proximity to the 52-week high predicts continuation
#                (George & Hwang 2004) -> within 15% of the 252d max is
#                BETTER. 0.85 mirrors their nearness construction.
#   btc_regime : alt longs (ETH/SOL) work when the market leader is in
#                an uptrend -> BTC above its own 50d SMA is BETTER.
#                Identity on BTC itself (it cannot gate itself; a
#                self-trend gate already failed as trend_200).
# LADDER: stage 1 = 4y/4f SCREEN (contaminated; passes are weak).
# Stage 2 = 4y/5f AND 5y/4f (the gauntlet that killed compression_deep).
# Stage 3 = watch survivors against live outcomes. Nothing changes the
# bot before stage 3. Every gate here goes on the findings ledger.
# rvol_window/rvol_threshold: PRE-REGISTERED before any result was seen.
# 20-day baseline and 1.5x are the practitioner convention for breakout
# volume confirmation (IBD CAN SLIM requires 40-50% above average; most
# sources quote 1.5x-2x as the institutional-participation threshold).
#
# EVIDENTIARY NOTE, stated plainly: unlike trend_200 / tsmom_365, whose
# parameters come from peer-reviewed work (Faber; Moskowitz-Ooi-Pedersen
# 2012), the 1.5x volume rule comes from trading practitioner literature.
# That is a weaker source. It is still a genuine pre-registration — the
# number was fixed from outside this repo's data — but it deserves less
# prior confidence than the momentum overlays, and if it "passes" on one
# ticker that should be read accordingly.
#
# The threshold is NOT swept. A sweep would pick the best-performing
# cutoff on these exact folds, which is the fitting this whole harness
# exists to prevent. rvol_curve() below prints a sensitivity table as a
# DIAGNOSTIC only; choosing a threshold from it would void the test.


def build_daily_volume(bars_4h: pd.DataFrame) -> pd.Series:
    """Daily volume summed from 4h bars. The daily Yahoo frame drops
    Volume, but the Binance klines already carry it — so this needs no
    new data source, just a column that was being thrown away."""
    if bars_4h is None or "Volume" not in getattr(bars_4h, "columns", []):
        return pd.Series(dtype=float)
    v = bars_4h["Volume"].astype(float)
    idx = pd.to_datetime(v.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    return v.groupby(idx.normalize()).sum()


def build_overlay_series(merged: pd.DataFrame, bars_4h=None,
                          btc_close: pd.Series = None) -> dict:
    """Daily series used by the overlays. Everything is a trailing
    calculation: the value AT date d uses closes up to and including d,
    never beyond — the same information the live bot would have."""
    c = merged["Close"].astype(float)
    ret = c.pct_change()
    out = {
        "sma200": c.rolling(OVERLAY_PARAMS["trend_sma"]).mean(),
        "mom365": c.pct_change(OVERLAY_PARAMS["tsmom_long"]),
        "mom28": c.pct_change(OVERLAY_PARAMS["tsmom_short"]),
        "vol_ann": ret.rolling(OVERLAY_PARAMS["vol_window"]).std()
                     * math.sqrt(365),
        "close": c,
    }
    p = OVERLAY_PARAMS
    if {"High", "Low"}.issubset(merged.columns):
        atr14 = cf.compute_atr(merged, period=p["atr_expand_period"])
        out["atr_expanding"] = atr14 > atr14.shift(p["atr_expand_lookback"])
    else:
        out["atr_expanding"] = pd.Series(dtype=bool)
    out["vix"] = (merged["vix_level"].astype(float)
                  if "vix_level" in merged.columns else pd.Series(dtype=float))
    out["high_frac"] = c / c.rolling(p["near_high_window"]).max()
    if "final_score" in merged.columns:
        fs = merged["final_score"].astype(float)
        out["score_rising"] = fs > fs.shift(p["score_rising_days"])
    else:
        out["score_rising"] = pd.Series(dtype=bool)
    if {"High", "Low"}.issubset(merged.columns):
        rng_ = (merged["High"] - merged["Low"]).astype(float)
        out["close_frac"] = ((c - merged["Low"]) / rng_.where(rng_ > 0))
    else:
        out["close_frac"] = pd.Series(dtype=float)
    if btc_close is not None and len(btc_close):
        b = btc_close.astype(float)
        out["btc_above_sma"] = b > b.rolling(p["btc_regime_sma"]).mean()
    else:
        out["btc_above_sma"] = pd.Series(dtype=bool)
    dv = build_daily_volume(bars_4h)
    if len(dv):
        # Baseline EXCLUDES the current day (.shift(1)) so a signal day's
        # own volume cannot inflate the average it is measured against.
        # The signal fires at the daily close, so that day's volume IS
        # known — using it as the numerator is not lookahead.
        base = dv.rolling(OVERLAY_PARAMS["rvol_window"]).mean().shift(1)
        out["rvol"] = dv / base
    else:
        out["rvol"] = pd.Series(dtype=float)
    return out


def _is_long(direction: str) -> bool:
    return direction in ("BUY", "STRONG_BUY")


def _norm_date(d):
    """Normalize any timestamp to a tz-naive midnight Timestamp.

    THE BUG THIS FIXES: build_daily_volume keys on tz-naive midnight
    (from the Binance klines), but the daily frame's index can be
    tz-aware or carry a time component depending on the yfinance path.
    A mismatch makes every rvol lookup return NaN, the gate fails closed,
    and the overlay silently reports 'no trades passed' — which reads
    exactly like a real finding. Measured: with clean alignment ~41%% of
    days clear RVOL 1.0; with a tz-aware index, 0%%."""
    ts = pd.Timestamp(d)
    if ts.tzinfo is not None:
        ts = ts.tz_localize(None)
    return ts.normalize()


def _sv(series_obj, d) -> float:
    """Safe series lookup: missing date -> NaN (Series.get returns None,
    which passes a NaN check and then blows up in comparisons)."""
    v = series_obj.get(d)
    return float("nan") if v is None else v


def _sv_daily(series_obj, d) -> float:
    """Safe lookup for series keyed on normalized daily dates."""
    if not len(series_obj):
        return float("nan")
    return _sv(series_obj, _norm_date(d))


def apply_overlay(trades: list, series: dict, overlay: str) -> list:
    """Gate or reweight a trade list. Pure; returns new list with a
    'weight' key (1.0 unless vol_scale). Unknown dates fail closed for
    gates (trade dropped) and fail neutral for sizing (weight 1)."""
    out = []
    for t in trades:
        d = t["date"]
        is_long = _is_long(t["direction"])
        keep, w = True, 1.0
        if overlay == "baseline":
            pass
        elif overlay == "trend_200":
            sma, px = _sv(series["sma200"], d), _sv(series["close"], d)
            keep = (sma == sma and px == px
                    and ((px > sma) if is_long else (px < sma)))
        elif overlay == "tsmom_365":
            m = _sv(series["mom365"], d)
            keep = (m == m) and ((m > 0) if is_long else (m < 0))
        elif overlay == "tsmom_28":
            m = _sv(series["mom28"], d)
            keep = (m == m) and ((m > 0) if is_long else (m < 0))
        elif overlay == "rvol_150":
            r = _sv_daily(series.get("rvol", pd.Series(dtype=float)), d)
            keep = (r == r) and r >= OVERLAY_PARAMS["rvol_threshold"]
        elif overlay == "compression_deep":
            # Registered as a median SPLIT, not a tuned threshold: the
            # cutoff is the median entry-RVOL of the trades being
            # evaluated, stashed in series["_rvol_median"] by the caller.
            # Both halves get reported, so there is nothing to select.
            r = _sv_daily(series.get("rvol", pd.Series(dtype=float)), d)
            med = series.get("_rvol_median", float("nan"))
            keep = (r == r) and (med == med) and r <= med
        elif overlay == "compression_shallow":
            r = _sv_daily(series.get("rvol", pd.Series(dtype=float)), d)
            med = series.get("_rvol_median", float("nan"))
            keep = (r == r) and (med == med) and r > med
        elif overlay == "atr_expand":
            e = _sv_daily(series.get("atr_expanding", pd.Series(dtype=bool)), d)
            keep = (e == e) and bool(e)
        elif overlay == "vix_calm":
            v = _sv_daily(series.get("vix", pd.Series(dtype=float)), d)
            keep = (v == v) and v < OVERLAY_PARAMS["vix_calm_threshold"]
        elif overlay == "near_high":
            h = _sv_daily(series.get("high_frac", pd.Series(dtype=float)), d)
            keep = (h == h) and h >= OVERLAY_PARAMS["near_high_frac"]
        elif overlay == "btc_regime":
            if series.get("_ticker", "").upper().startswith("BTC"):
                keep = True          # identity: BTC cannot gate itself
            else:
                b = _sv_daily(series.get("btc_above_sma",
                                          pd.Series(dtype=bool)), d)
                keep = (b == b) and bool(b)
        elif overlay == "score_rising":
            r = _sv_daily(series.get("score_rising", pd.Series(dtype=bool)), d)
            keep = (r == r) and bool(r)
        elif overlay == "strong_close":
            fr = _sv_daily(series.get("close_frac", pd.Series(dtype=float)), d)
            keep = (fr == fr) and fr >= OVERLAY_PARAMS["strong_close_frac"]
        elif overlay == "fresh_signal":
            # Needs cross-trade state: the caller precomputes stop-exit
            # dates for this trade list into series["_stop_exits"]. Only
            # exits strictly BEFORE this entry can block it (no
            # lookahead); block if any fell within the cooldown window.
            cd = OVERLAY_PARAMS["fresh_signal_cooldown_days"]
            entry = _norm_date(d)
            keep = not any(0 < (entry - x).days <= cd
                           for x in series.get("_stop_exits", ()))
        elif overlay == "score_fading":
            # INVERSE of score_rising (#14, failed -0.570/-0.076/-0.265)
            r = _sv_daily(series.get("score_rising", pd.Series(dtype=bool)), d)
            keep = (r == r) and not bool(r)
        elif overlay == "recent_stop":
            # INVERSE of fresh_signal (#16, failed -0.175/-0.105/-0.091):
            # REQUIRE a same-ticker stop-exit in the prior cooldown window.
            cd = OVERLAY_PARAMS["fresh_signal_cooldown_days"]
            entry = _norm_date(d)
            keep = any(0 < (entry - x).days <= cd
                       for x in series.get("_stop_exits", ()))
        elif overlay == "quiet_entry":
            # Composite of the two measured quiet properties: low volume
            # AND no score momentum. Thresholds REUSED (0.70 sits at the
            # observed signal-day RVOL median across tickers, 0.60-0.66,
            # rounded up; score window is #14's 3 days). Nothing tuned.
            r = _sv_daily(series.get("rvol", pd.Series(dtype=float)), d)
            up = _sv_daily(series.get("score_rising", pd.Series(dtype=bool)), d)
            keep = ((r == r) and r <= OVERLAY_PARAMS["quiet_rvol_max"]
                    and (up == up) and not bool(up))
        elif overlay == "vol_scale":
            v = _sv(series["vol_ann"], d)
            if v == v and v > 0:
                w = min(OVERLAY_PARAMS["vol_target_ann"] / v,
                        OVERLAY_PARAMS["vol_cap"])
        else:
            raise ValueError(f"unknown overlay {overlay}")
        if keep:
            nt = dict(t)
            nt["weight"] = round(w, 4)
            out.append(nt)
    return out


def weighted_net(trades: list) -> float:
    """Weight-aware net expectancy. With all weights 1 this is the plain
    mean, so baseline numbers are unchanged."""
    if not trades:
        return float("nan")
    wsum = sum(t.get("weight", 1.0) for t in trades)
    if wsum <= 0:
        return float("nan")
    return sum(t.get("weight", 1.0) * t["pnl_r_net"] for t in trades) / wsum


def overlay_fold_table(fold_trades: list, series: dict,
                        overlays=("baseline", "quiet_entry", "score_fading",
                                  "recent_stop", "score_rising", "strong_close",
                                  "fresh_signal", "atr_expand", "vix_calm",
                                  "near_high", "btc_regime", "trend_200",
                                  "tsmom_365", "tsmom_28", "rvol_150",
                                  "compression_deep", "compression_shallow",
                                  "vol_scale")) -> dict:
    """{overlay: {'per_fold': [(n, net)...], 'all': x, 'ex_best': y}}.
    ex_best uses the same rule as concentration_report: drop the fold
    with the largest total contribution, min 10 trades to count."""
    res = {}
    for ov in overlays:
        per = []
        for trades in fold_trades:
            sel = apply_overlay(trades, series, ov)
            per.append((len(sel), weighted_net(sel),
                        sum(t.get("weight", 1.0) for t in sel)))
        counted = [(n, net, w) for n, net, w in per if n >= 10 and net == net]
        if len(counted) >= 3:
            tot_w = sum(w for _, _, w in counted)
            tot_r = sum(net * w for _, net, w in counted)
            best = max(counted, key=lambda x: x[1] * x[2])
            rest_w = tot_w - best[2]
            allv = tot_r / tot_w if tot_w else float("nan")
            exb = ((tot_r - best[1] * best[2]) / rest_w
                   if rest_w > 0 else float("nan"))
        else:
            allv, exb = float("nan"), float("nan")
        res[ov] = {"per_fold": per, "all": allv, "ex_best": exb}
    return res


def render_overlay_table(ticker: str, res: dict) -> str:
    folds = len(next(iter(res.values()))["per_fold"])
    head = f"{'overlay':<12}" + "".join(f"{'f'+str(i+1):>14}" for i in range(folds))
    head += f"{'ALL':>10}{'EX-BEST':>10}"
    lines = [f"\n{ticker} — literature overlays on the live geometry",
             "=" * len(head), head, "-" * len(head)]
    for ov, r in res.items():
        row = f"{ov:<12}"
        for n, net, _ in r["per_fold"]:
            row += (f"{net:>+8.3f}({n:>3})" if n else f"{'—':>14}")
        row += (f"{r['all']:>+10.3f}" if r['all'] == r['all'] else f"{'n/a':>10}")
        row += (f"{r['ex_best']:>+10.3f}" if r['ex_best'] == r['ex_best']
                else f"{'n/a':>10}")
        lines.append(row)
    return "\n".join(lines)


def rvol_coverage(fold_trades: list, series: dict) -> str:
    """DIAGNOSTIC: is RVOL *missing* on signal days, or *present but low*?

    These look identical in the overlay table (both drop the trade) but
    mean opposite things:
      - mostly MISSING  -> index misalignment between the daily trade
                           dates and the volume series. A bug. Fix it.
      - mostly PRESENT but below 1.5 -> a real property: this signal
                           fires on quiet days. Since the underlying
                           model is a SQUEEZE detector, and a squeeze is
                           volatility/volume COMPRESSION, that would be
                           structurally expected — and would mean volume
                           confirmation contradicts the signal's own
                           definition rather than refining it.
    Roughly 35-45%% of days should clear RVOL 1.0 on any normal series;
    far below that with good coverage is the interesting case."""
    rv = series.get("rvol", pd.Series(dtype=float))
    dates = [t["date"] for fold in fold_trades for t in fold]
    if not dates:
        return "  rvol coverage: no trades"
    if not len(rv):
        return "  rvol coverage: no volume series at all"
    vals, missing = [], 0
    for d in dates:
        v = _sv_daily(rv, d)
        if v == v:
            vals.append(v)
        else:
            missing += 1
    n = len(dates)
    lines = [f"  rvol coverage on signal days (n={n})",
             f"    missing (no volume match): {missing} "
             f"({missing / n * 100:.0f}%)"]
    if vals:
        s = pd.Series(vals)
        above1 = (s >= 1.0).mean() * 100
        lines += [f"    present: {len(vals)} — median {s.median():.2f}, "
                  f"mean {s.mean():.2f}",
                  f"    share >= 1.0: {above1:.0f}%"]
        # Compare against ALL days, which is the control: if signal days
        # look like every other day, the gate is just thinning the sample.
        allv = rv.dropna()
        if len(allv):
            lines.append(f"    (all days: median {allv.median():.2f}, "
                         f"share >= 1.0 {(allv >= 1.0).mean() * 100:.0f}%)")
    if missing / n > 0.5:
        lines.append("    ^ VERDICT: mostly MISSING — this is an index/data "
                     "alignment bug, not a finding. The overlay result is void.")
    elif vals and (pd.Series(vals) >= 1.0).mean() < 0.25:
        lines.append("    ^ VERDICT: coverage is fine but signal days are "
                     "genuinely QUIET. Consistent with a squeeze detector "
                     "firing on compression. Volume confirmation may be the "
                     "wrong tool for this signal by construction.")
    return "\n".join(lines)


def rvol_curve(fold_trades: list, series: dict,
                thresholds=(1.0, 1.25, 1.5, 2.0)) -> str:
    """DIAGNOSTIC ONLY — NOT part of the pre-registered test.

    Shows how trade count and ex-best net move as the volume threshold
    changes. Useful for understanding WHY rvol_150 passed or failed (e.g.
    'it just removed half the sample'). Picking a threshold from this
    table would be exactly the curve-fitting the harness prevents: the
    registered spec is 1.5x and stays 1.5x regardless of what this shows.
    """
    saved = OVERLAY_PARAMS["rvol_threshold"]
    lines = ["  rvol sensitivity (DIAGNOSTIC — does not change the verdict)",
             f"    {'thresh':<9}{'trades kept':>13}{'ex-best':>10}"]
    try:
        for th in thresholds:
            OVERLAY_PARAMS["rvol_threshold"] = th
            res = overlay_fold_table(fold_trades, series,
                                     overlays=("baseline", "rvol_150"))
            kept = sum(n for n, _, _ in res["rvol_150"]["per_fold"])
            total = sum(n for n, _, _ in res["baseline"]["per_fold"])
            eb = res["rvol_150"]["ex_best"]
            eb_s = f"{eb:+.3f}" if eb == eb else "n/a"
            mark = "  <- registered" if abs(th - saved) < 1e-9 else ""
            lines.append(f"    {th:<9.2f}{kept:>5}/{total:<7}{eb_s:>10}{mark}")
    finally:
        OVERLAY_PARAMS["rvol_threshold"] = saved
    return "\n".join(lines)


# ----------------------------------------------------------------------
# VOLUME, USED IN THE DIRECTION THE DATA POINTS
# ----------------------------------------------------------------------
# MEASURED FIRST (3 tickers, ~350 BUY trades): signal days run at
# RVOL median 0.60-0.66 vs 0.91-0.95 for all days; only 5-10% of signal
# days clear RVOL 1.0 vs 41-44% of all days. The signal fires on
# COMPRESSION. So a breakout-style "confirm with high volume" gate asks
# it to stop being a squeeze detector, which is why rvol_150 kept 0-2
# trades. Two follow-ups that respect that instead of fighting it:
#
#   compression_depth  Does DEEPER compression predict better outcomes?
#                      ("the tighter the coil, the bigger the spring" —
#                      the standard squeeze-trading claim.) Reported as
#                      quartiles, so no threshold is chosen at all, plus
#                      a median-SPLIT gate as the registered test. A
#                      median split is not an optimized cutoff: it is
#                      fixed by the data's own centre, and BOTH halves
#                      are always printed so there is nothing to
#                      cherry-pick.
#
#   post_entry_expansion  Did volume EXPAND after entry? This cannot gate
#                      an entry (it is unknowable then), so it is
#                      reported as a management/exit question: measured
#                      strictly in the first 24h AFTER entry, then
#                      outcomes are split on it. If expansion separates
#                      winners from losers, an early-exit rule becomes
#                      worth designing. If not, drop the idea.
#
# HYPOTHESIS DIRECTION IS REGISTERED HERE, BEFORE RESULTS: deeper
# compression is expected to be BETTER, and post-entry expansion is
# expected to be BETTER. If the data says the opposite, that is a real
# result and gets reported as such, not quietly reinterpreted.


def rvol_quartile_report(trades: list, series: dict) -> str:
    """Net expectancy by entry-RVOL quartile. Purely descriptive — no
    threshold is chosen, so nothing here can be curve-fitted. The shape
    of the relationship is the finding (monotone or not)."""
    rows = []
    for t in trades:
        r = _sv_daily(series.get("rvol", pd.Series(dtype=float)), t["date"])
        if r == r:
            rows.append((r, t.get("pnl_r_net", t["pnl_r"])))
    if len(rows) < 20:
        return f"  compression quartiles: only {len(rows)} trades — too few"
    df = pd.DataFrame(rows, columns=["rvol", "net"]).sort_values("rvol")
    df["q"] = pd.qcut(df["rvol"], 4, labels=["Q1 deepest", "Q2", "Q3",
                                              "Q4 least"], duplicates="drop")
    lines = ["  net expectancy by entry-volume quartile (Q1 = most compressed)",
             f"    {'quartile':<12}{'n':>5}{'rvol range':>16}{'net R':>10}"]
    for q, g in df.groupby("q", observed=True):
        lines.append(f"    {str(q):<12}{len(g):>5}"
                     f"{g['rvol'].min():>8.2f}-{g['rvol'].max():<7.2f}"
                     f"{g['net'].mean():>+10.3f}")
    q1 = df[df["q"] == "Q1 deepest"]["net"].mean()
    q4 = df[df["q"] == "Q4 least"]["net"].mean()
    if q1 == q1 and q4 == q4:
        lines.append(f"    deepest minus least: {q1 - q4:+.3f}R "
                     f"({'supports' if q1 > q4 else 'CONTRADICTS'} "
                     f"the registered hypothesis that tighter coils pay more)")
    return "\n".join(lines)


def post_entry_expansion(trades: list, bars_4h: pd.DataFrame,
                          window_bars: int = 6) -> str:
    """Did volume expand in the first 24h AFTER entry, and did that
    separate outcomes? NOT an entry filter — this information does not
    exist at entry. It is a management question: if expansion predicts
    the good trades, an early-exit-on-no-expansion rule is worth
    designing next. Strictly forward-looking from entry, never using
    bars beyond the measurement window."""
    if bars_4h is None or "Volume" not in getattr(bars_4h, "columns", []):
        return "  post-entry expansion: no volume data"
    v = bars_4h["Volume"].astype(float)
    idx = pd.to_datetime(v.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    v = pd.Series(v.values, index=idx).sort_index()
    prior = v.rolling(30).mean()          # ~5 days of 4h bars, trailing
    exp_rows = []
    for t in trades:
        entry_ts = _norm_date(t["date"]) + pd.Timedelta(hours=24)
        base = prior[prior.index <= entry_ts]
        if not len(base) or not (base.iloc[-1] > 0):
            continue
        fwd = v[(v.index > entry_ts)].iloc[:window_bars]
        if len(fwd) < window_bars:
            continue
        ratio = fwd.mean() / base.iloc[-1]
        exp_rows.append((ratio, t.get("pnl_r_net", t["pnl_r"])))
    if len(exp_rows) < 20:
        return f"  post-entry expansion: only {len(exp_rows)} usable trades"
    df = pd.DataFrame(exp_rows, columns=["ratio", "net"])
    hi = df[df["ratio"] >= 1.0]
    lo = df[df["ratio"] < 1.0]
    lines = ["  outcomes split by volume expansion in the first 24h AFTER entry",
             f"    expanded (>=1.0x):  n={len(hi):<4} net {hi['net'].mean():+.3f}R"
             if len(hi) else "    expanded: none",
             f"    did not expand:     n={len(lo):<4} net {lo['net'].mean():+.3f}R"
             if len(lo) else "    did not expand: none"]
    if len(hi) >= 10 and len(lo) >= 10:
        gap = hi["net"].mean() - lo["net"].mean()
        lines.append(f"    gap: {gap:+.3f}R "
                     f"({'supports' if gap > 0 else 'CONTRADICTS'} the "
                     f"registered hypothesis that expansion marks the "
                     f"good trades)")
        if abs(gap) < 0.10:
            lines.append("    (gap under 0.10R — treat as no separation)")
    else:
        lines.append("    one side too thin to compare")
    return "\n".join(lines)


def overlay_verdict(per_ticker: dict, tol: float = 0.02) -> str:
    """Apply the pre-registered bar across tickers. per_ticker maps
    ticker -> overlay_fold_table result."""
    lines = ["", "PRE-REGISTERED ACCEPTANCE (fixed before results were seen):",
             "  candidate = improves EX-BEST net on >=2 of 3 tickers AND",
             f"  degrades no ticker's ex-best by more than {tol:.2f}R", ""]
    overlays = [o for o in next(iter(per_ticker.values())) if o != "baseline"]
    any_candidate = False
    for ov in overlays:
        better, worse_big, detail = 0, 0, []
        for tkr, res in per_ticker.items():
            b, o = res["baseline"]["ex_best"], res[ov]["ex_best"]
            if b != b or o != o:
                detail.append(f"{tkr}:n/a")
                continue
            diff = o - b
            detail.append(f"{tkr}:{diff:+.3f}")
            if diff > 0:
                better += 1
            if diff < -tol:
                worse_big += 1
        ok = better >= 2 and worse_big == 0
        any_candidate |= ok
        n_na = sum(1 for x in detail if x.endswith("n/a"))
        tag = "CANDIDATE" if ok else "no"
        if ok and n_na:
            # An unmeasurable ticker satisfied "no degradation" by
            # absence, not evidence. Still a screen-stage pass, but a
            # weaker one — say so where it will be read.
            tag += f" (weak: {n_na} ticker(s) n/a — gate thinned them below min_n)"
        lines.append(f"  {ov:<12} ex-best vs baseline [{', '.join(detail)}]"
                     f"  ->  {tag}")
    lines.append("")
    if any_candidate:
        lines += ["  A candidate is NOT an adoption. Next steps if you want it:",
                  "  1. rerun with --folds 5 and on a different --years window",
                  "  2. paper-trade it alongside the live outcomes tracker",
                  "  3. only then consider changing live behaviour"]
    else:
        lines += ["  No overlay met the bar. That is the answer, not a failure:",
                  "  these were the field's best pre-registered ideas, and on",
                  "  this signal they don't add out-of-fold edge. The honest",
                  "  levers remain costs, band selection, and live evidence."]
    lines.append("  Nothing was changed by this run.")
    return "\n".join(lines)


_btc_close_cache = {"s": None}


def um_fetch_btc_close(years: float) -> pd.Series:
    """BTC daily closes for the btc_regime gate. Trailing data only."""
    yf_period = next((p for y, p in ((1, "1y"), (2, "2y"), (5, "5y"),
                                      (10, "10y")) if years <= y), "max")
    df = epm.analyze(to_yahoo_crypto_symbol("BTC"), period=yf_period)
    return df["Close"].astype(float)


def main_overlays():
    parser = argparse.ArgumentParser(
        description="Test literature-fixed overlays (trend, TSMOM, vol "
                    "scaling) on the live geometry, per fold, lockboxed.")
    parser.add_argument("tickers", nargs="+")
    parser.add_argument("--years", type=float, default=4.0)
    parser.add_argument("--folds", type=int, default=4)
    parser.add_argument("--fee-bps", type=float, default=2.0)
    parser.add_argument("--slippage-bps", type=float, default=2.0)
    parser.add_argument("--direction", choices=("buy", "sell"), default=None,
                        help="Restrict to BUY/STRONG_BUY or SELL/STRONG_SELL "
                             "trades before applying overlays. Default: both.")
    parser.add_argument("--rvol-curve", action="store_true",
                        help="Print volume-threshold sensitivity. DIAGNOSTIC "
                             "ONLY — the registered threshold stays 1.5x.")
    args = parser.parse_args()

    yf_period = next((p for y, p in ((1, "1y"), (2, "2y"), (5, "5y"), (10, "10y"))
                      if args.years <= y), "max")
    n_4h = min(int(args.years * 365 * 6 * 1.15), 30000)
    cutoff = pd.Timestamp.now().normalize() - pd.Timedelta(days=int(args.years * 365))
    g = LIVE_GEOMETRY
    per_ticker = {}
    for ticker in args.tickers:
        print(f"\n=== {ticker}: baseline trades from the LIVE geometry ===")
        merged = run_backtest(ticker, period=yf_period, squeeze_bars=n_4h)
        merged = merged[merged.index >= cutoff]
        merged = apply_lockbox(merged)          # never unlocked here
        bars_4h = cf.fetch_klines_paginated(cf.to_binance_symbol(ticker),
                                            interval="4h", target_bars=n_4h)
        # built AFTER the fetch: rvol needs the klines' Volume column.
        # btc_regime needs BTC daily closes when gating an alt; fetched
        # once per command and reused.
        if ticker.upper().startswith("BTC"):
            btc_c = merged["Close"]
        else:
            if _btc_close_cache["s"] is None:
                print("  fetching BTC daily closes for the btc_regime gate...")
                _btc_close_cache["s"] = um_fetch_btc_close(args.years)
            btc_c = _btc_close_cache["s"]
        series = build_overlay_series(merged, bars_4h, btc_close=btc_c)
        series["_ticker"] = ticker
        # fresh_signal support: exit dates of stopped trades (entry +
        # days_held), computed once from every fold's trades below
        if not len(series.get("rvol", [])):
            print("  NOTE: no volume data — rvol_150 will show as n/a")
        fold_trades = []
        for fold in walkforward_folds(merged, args.folds):
            if len(fold) == 0:
                fold_trades.append([])
                continue
            r = backtest_exit_geometry(
                fold, bars_4h, atr_source=g["atr_source"],
                stop_mult=g["stop_mult"], target_mult=g["target_mult"],
                max_hold_days=g["max_hold_days"],
                short_sma_filter=g["short_sma_filter"],
                confirm_days=g["confirm_days"],
                fee_bps=args.fee_bps, slippage_bps=args.slippage_bps)
            trades = r.get("trades", [])
            if args.direction:
                wanted = ({"BUY", "STRONG_BUY"} if args.direction == "buy"
                         else {"SELL", "STRONG_SELL"})
                trades = [t for t in trades if t["direction"] in wanted]
            fold_trades.append(trades)
        # Median entry-RVOL across ALL folds' trades — computed once, so
        # every fold is split on the same line and no fold can pick its
        # own favourable cutoff.
        series["_stop_exits"] = tuple(
            _norm_date(t["date"]) + pd.Timedelta(days=float(t.get("days_held", 0)))
            for fold in fold_trades for t in fold
            if t.get("outcome") in ("stop", "ambiguous_stop"))
        _rv = [_sv_daily(series.get("rvol", pd.Series(dtype=float)), t["date"])
               for fold in fold_trades for t in fold]
        _rv = [x for x in _rv if x == x]
        series["_rvol_median"] = (float(pd.Series(_rv).median()) if _rv
                                  else float("nan"))
        res = overlay_fold_table(fold_trades, series)
        per_ticker[ticker] = res
        print(render_overlay_table(ticker, res))
        if _rv:
            print(f"  compression split at RVOL median "
                  f"{series['_rvol_median']:.2f} "
                  f"(deep = at or below, shallow = above)")
            print(rvol_quartile_report([t for f in fold_trades for t in f],
                                       series))
            print(post_entry_expansion([t for f in fold_trades for t in f],
                                        bars_4h))
        if args.rvol_curve and len(series.get("rvol", [])):
            print(rvol_coverage(fold_trades, series))
            print(rvol_curve(fold_trades, series))
    print(overlay_verdict(per_ticker))


# ======================================================================
# DIAGNOSE — characterization, not hypothesis testing
# ======================================================================
# CONTEXT. Seven overlay/filter hypotheses were tested against the same
# four years tonight; all failed the independent-window check. Testing
# an eighth filter on that history is close to worthless — with enough
# attempts something passes any bar by chance (compression_deep did,
# then died on the 5y window). This command is a different kind of work:
# DESCRIPTIVE. It answers "what is the signal actually doing" from data
# already recorded per trade, which does not burn statistical validity.
#
# RULE: anything promising found here is NOT a result. It becomes a
# registered hypothesis (written down, direction stated) and gets tested
# ONCE on data that had no vote in generating it — realistically the
# live outcomes file, since the 4y history is exhausted. That rule is
# printed in the output so it survives the chat that created it.


def mfe_report(trades: list) -> str:
    """How far trades ran in the favorable direction before resolving,
    as % of target distance. mfe_pct_of_target has been recorded per
    trade all along. The interesting number: how often LOSERS first got
    most of the way to the target — 'near-miss rate'. High near-miss
    means the target may sit past where moves exhaust; low means losers
    were simply wrong, and exit tinkering has nothing to grab."""
    stopped = [t["mfe_pct_of_target"] for t in trades
               if t["outcome"] in ("stop", "ambiguous_stop")
               and t.get("mfe_pct_of_target") == t.get("mfe_pct_of_target")]
    hit = [t for t in trades if t["outcome"] == "target"]
    timed = [t for t in trades if t["outcome"] == "timeout"]
    if len(stopped) < 10:
        return "  MFE: too few resolved losers to characterize"
    s = pd.Series(stopped)
    lines = ["  How far LOSERS ran toward target before stopping "
             f"(n={len(s)} stopped, {len(hit)} hit target, {len(timed)} timed out)",
             f"    median MFE: {s.median():.0f}% of target distance",
             f"    reached >=50% of target first: {(s >= 50).mean() * 100:.0f}%",
             f"    reached >=75% of target first: {(s >= 75).mean() * 100:.0f}%",
             f"    never reached 25%:            {(s < 25).mean() * 100:.0f}%"]
    near = (s >= 75).mean()
    if near >= 0.25:
        lines.append("    ^ notable: a quarter or more of losers were near-"
                     "misses. A partial-take or trailing rule is a PLAUSIBLE")
        lines.append("      hypothesis — register it, then test it on LIVE "
                     "outcomes, not on this history again.")
    else:
        lines.append("    ^ losers mostly never got close: they were wrong "
                     "entries, not mismanaged exits. Exit tinkering has")
        lines.append("      little to work with here.")
    return "\n".join(lines)


def hold_time_report(trades: list) -> str:
    """Resolution-speed fingerprint: do winners and losers take similar
    time? A big asymmetry changes what a timeout means."""
    w = [t["days_held"] for t in trades if t["outcome"] == "target"]
    l = [t["days_held"] for t in trades
         if t["outcome"] in ("stop", "ambiguous_stop")]
    if len(w) < 8 or len(l) < 8:
        return "  hold times: too few on one side"
    return ("  Resolution speed\n"
            f"    winners: median {pd.Series(w).median():.1f}d "
            f"(p90 {pd.Series(w).quantile(.9):.1f}d)\n"
            f"    losers:  median {pd.Series(l).median():.1f}d "
            f"(p90 {pd.Series(l).quantile(.9):.1f}d)")


def strength_report(trades: list) -> str:
    """Does the STRONG_ label earn its keep? This evaluates an EXISTING
    live mechanism (conviction tiers already published every hour), not
    a new filter — but any action taken from it still goes on the
    hypothesis ledger like everything else."""
    strong = [t for t in trades if t["direction"].startswith("STRONG")]
    plain = [t for t in trades if not t["direction"].startswith("STRONG")]
    if len(strong) < 10 or len(plain) < 10:
        return (f"  STRONG vs plain: too thin (strong n={len(strong)}, "
                f"plain n={len(plain)})")
    sr, pr = stats_from_trades(strong), stats_from_trades(plain)
    gap = sr["expectancy_r_net"] - pr["expectancy_r_net"]
    lines = ["  Conviction tiers (does STRONG_ earn its label?)",
             f"    STRONG: n={sr['n']:<4} net {sr['expectancy_r_net']:+.3f}R  "
             f"target {sr['target_rate'] * 100:.0f}%",
             f"    plain:  n={pr['n']:<4} net {pr['expectancy_r_net']:+.3f}R  "
             f"target {pr['target_rate'] * 100:.0f}%",
             f"    gap: {gap:+.3f}R "
             + ("(STRONG is adding information)" if gap > 0.10 else
                "(STRONG is NOT separating — the label may be decoration)"
                if gap < -0.10 else "(inside noise)")]
    return "\n".join(lines)


def follower_experience_report(trades: list) -> str:
    """What a person following every signal actually lives through:
    equity path in R, max drawdown, losing streaks. A signal service
    with +0.2R expectancy and a 12-loss streak loses its audience
    before the expectancy shows up."""
    if len(trades) < 20:
        return "  follower experience: too few trades"
    ordered = sorted(trades, key=lambda t: t["date"])
    eq, peak, mdd, streak, worst_streak = 0.0, 0.0, 0.0, 0, 0
    for t in ordered:
        eq += t["pnl_r_net"]
        peak = max(peak, eq)
        mdd = max(mdd, peak - eq)
        if t["pnl_r_net"] < 0:
            streak += 1
            worst_streak = max(worst_streak, streak)
        else:
            streak = 0
    total = eq
    yrs = max((ordered[-1]["date"] - ordered[0]["date"]).days / 365.25, 0.1)
    lines = ["  Follower experience (taking every signal, 1R risk each)",
             f"    total: {total:+.1f}R over {len(ordered)} trades "
             f"(~{len(ordered) / yrs:.0f} signals/yr)",
             f"    max drawdown: {mdd:.1f}R from peak",
             f"    longest losing streak: {worst_streak}",
             f"    ratio check: drawdown is {mdd / max(total, 0.1):.1f}x "
             f"the total gain" if total > 0 else
             "    total is not positive — expectancy first, experience later"]
    return "\n".join(lines)


def main_diagnose():
    parser = argparse.ArgumentParser(
        description="Characterize the live-geometry trades: MFE, hold "
                    "times, conviction tiers, follower experience. "
                    "Descriptive only — no accept/reject verdicts.")
    parser.add_argument("tickers", nargs="+")
    parser.add_argument("--years", type=float, default=4.0)
    parser.add_argument("--direction", choices=("buy", "sell"), default="buy",
                        help="Default buy: the going-forward side.")
    parser.add_argument("--fee-bps", type=float, default=2.0)
    parser.add_argument("--slippage-bps", type=float, default=2.0)
    args = parser.parse_args()

    yf_period = next((p for y, p in ((1, "1y"), (2, "2y"), (5, "5y"), (10, "10y"))
                      if args.years <= y), "max")
    n_4h = min(int(args.years * 365 * 6 * 1.15), 30000)
    cutoff = pd.Timestamp.now().normalize() - pd.Timedelta(days=int(args.years * 365))
    g = LIVE_GEOMETRY
    wanted = ({"BUY", "STRONG_BUY"} if args.direction == "buy"
              else {"SELL", "STRONG_SELL"})
    for ticker in args.tickers:
        print(f"\n=== {ticker} diagnosis "
              f"({args.direction.upper()}, live geometry, {args.years:g}y) ===")
        merged = run_backtest(ticker, period=yf_period, squeeze_bars=n_4h)
        merged = merged[merged.index >= cutoff]
        merged = apply_lockbox(merged)
        bars_4h = cf.fetch_klines_paginated(cf.to_binance_symbol(ticker),
                                            interval="4h", target_bars=n_4h)
        r = backtest_exit_geometry(
            merged, bars_4h, atr_source=g["atr_source"],
            stop_mult=g["stop_mult"], target_mult=g["target_mult"],
            max_hold_days=g["max_hold_days"],
            short_sma_filter=g["short_sma_filter"],
            confirm_days=g["confirm_days"],
            fee_bps=args.fee_bps, slippage_bps=args.slippage_bps)
        trades = [t for t in r.get("trades", []) if t["direction"] in wanted]
        if len(trades) < 20:
            print(f"  only {len(trades)} trades — skipping")
            continue
        print(mfe_report(trades))
        print(hold_time_report(trades))
        print(strength_report(trades))
        print(follower_experience_report(trades))
    print("\nRULE (survives this chat): anything promising above is a")
    print("hypothesis, not a result. Write it down with a direction, then")
    print("test it ONCE on data that had no vote in generating it — in")
    print("practice the live outcomes file, since the 4y history has now")
    print("had 7+ hypotheses run against it and is close to exhausted.")


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("run", "multi", "backtest", "mlsweep", "robustness", "walkforward", "exitgeometry", "optimize", "overlays", "diagnose"):
        print("Usage: python pipeline.py <run|multi|backtest|robustness> [args...]\n"
              "  run BTC ...          - single-ticker pipeline (was unified_model.py)\n"
              "  multi BTC ETH ...    - batch across tickers   (was run_multi_ticker.py)\n"
              "  backtest BTC ...     - historical backtest    (was backtest_direction.py)\n"
              "  mlsweep BTC          - sweep ML target/feature definitions by holdout AUC\n"
              "  optimize BTC         - grid-search exit configs on sealed data, walk-forward\n"
              "                         validate leaders, show cost + band leakage\n"
              "  exitgeometry BTC     - compare live (4h ATR) vs backtest (daily ATR) exit\n"
              "                         geometries on history — options 1 and 2\n"
              "  walkforward BTC ETH SOL - fixed-config evaluation on sequential folds (lockboxed)\n"
              "  diagnose BTC ETH SOL - characterize live-geometry trades: MFE, hold times,\n"
              "                         conviction tiers, follower experience (descriptive)\n"
              "  overlays BTC ETH SOL - test literature-fixed filters (200d trend, TSMOM,\n"
              "                         vol scaling) on the live geometry, per fold\n"
              "  robustness BTC ETH SOL - split-sample validation of the 4y failure +\n"
              "                         VIX regime rescue candidate (writes docs/robustness.md)\n"
              "Run 'python pipeline.py <command> --help' for that command's options.")
        sys.exit(1)

    command = sys.argv.pop(1)  # remove the subcommand so each parser sees its own args
    if command == "run":
        main_run()
    elif command == "multi":
        main_multi()
    elif command == "backtest":
        main_backtest()
    elif command == "mlsweep":
        main_mlsweep()
    elif command == "robustness":
        main_robustness()
    elif command == "walkforward":
        main_walkforward()
    elif command == "exitgeometry":
        main_exitgeometry()
    elif command == "optimize":
        main_optimize()
    elif command == "overlays":
        main_overlays()
    elif command == "diagnose":
        main_diagnose()


if __name__ == "__main__":
    main()
