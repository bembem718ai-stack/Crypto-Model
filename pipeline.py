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

def apply_reddit_step(ticker: str, step1_result: dict, subreddits: list = None,
                       limit_per_sub: int = 100, min_mentions: int = 15) -> dict:
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

    gate = ads.first_pass_sentiment_check_adanos(ticker, min_mentions_for_confidence=min_mentions)

    gated_score = ads.apply_gate_to_score(gate, step1_result["initial_score"])

    return {
        "step": 2,
        "step_name": "reddit_data",
        "timestamp": datetime.now(timezone.utc),
        "ticker": ticker,
        "gate_decision": gate["decision"],
        "gate_multiplier": gate["gate_multiplier"],
        "gate_reason": gate["reason"],
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


def run_backtest(ticker: str, period: str = "2y", forward_days: int = 5,
                  weight_pattern: float = 0.6, weight_indicators: float = 0.4,
                  extreme_fear_mode: str = "symmetric",
                  buy_bar: float = 60, sell_bar: float = 40) -> pd.DataFrame:
    print(f"Pulling daily technical/macro history for {ticker}...")
    yahoo_ticker = to_yahoo_crypto_symbol(ticker)
    tech_df = epm.analyze(yahoo_ticker, period=period)
    tech_df = tech_df.dropna(subset=["final_score"])
    tech_df.index = pd.to_datetime(tech_df.index).normalize()

    print(f"Pulling 4h squeeze history for {ticker} (resampled to daily)...")
    squeeze_daily = backtest_squeeze_history(ticker)

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
                   side: str = "both", short_sma_filter: int = 0) -> dict:
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

    trades = []
    idx = df.index.to_list()
    for i, (day, row) in enumerate(df.iterrows()):
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
        trades.append({"date": day, "direction": d, "outcome": outcome,
                       "score": float(row.get("combined_final_score", float("nan"))),
                       "mfe_pct_of_target": round(mfe * 100, 1),
                       "pnl_r": round(pnl_r, 3),
                       "days_held": (idx.index(exit_day) - i) if exit_day is not None else max_hold_days})

    if not trades:
        return {"n": 0, "trades": trades}
    tdf = pd.DataFrame(trades)
    nonwin = tdf.loc[tdf["outcome"] != "target", "mfe_pct_of_target"]
    return {
        "n": len(tdf),
        "target_rate": (tdf["outcome"] == "target").mean(),
        "stop_rate": tdf["outcome"].isin(["stop", "ambiguous_stop"]).mean(),
        "ambiguous_n": int((tdf["outcome"] == "ambiguous_stop").sum()),
        "timeout_rate": (tdf["outcome"] == "timeout").mean(),
        "expectancy_r": tdf["pnl_r"].mean(),
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
    parser.add_argument("--buy-bar", type=float, default=70,
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
                             short_sma_filter=args.short_sma_filter)
        if args.exits:
            print_exit_report(res, args.stop_mult, args.target_mult, args.max_hold_days)
        if args.prob_table:
            print_probability_table(res, bucket=args.prob_bucket)
        if args.sizing:
            sz = compute_position_sizing(res, bucket=args.prob_bucket,
                                         kelly_fraction=args.kelly_fraction)
            print_position_sizing(sz, args.kelly_fraction)


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
             feature_sets=("all",), periods=None):
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
    args = parser.parse_args()
    ml_sweep(args.ticker,
             horizons=tuple(int(x) for x in args.horizons.split(",")),
             thresholds=tuple(float(x) for x in args.thresholds.split(",")),
             squeeze_variants=((False,) if args.no_squeeze else (False, True)),
             feature_sets=tuple(args.feature_sets.split(",")),
             periods=tuple(args.periods.split(",")))


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("run", "multi", "backtest", "mlsweep"):
        print("Usage: python pipeline.py <run|multi|backtest> [args...]\n"
              "  run BTC ...        - single-ticker pipeline (was unified_model.py)\n"
              "  multi BTC ETH ...  - batch across tickers   (was run_multi_ticker.py)\n"
              "  backtest BTC ...   - historical backtest    (was backtest_direction.py)\n"
              "  mlsweep BTC        - sweep ML target/feature definitions by holdout AUC\n"
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


if __name__ == "__main__":
    main()
