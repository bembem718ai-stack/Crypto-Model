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
                          use_ml: bool = False) -> dict:
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
        **ml_info,
    }


# ======================================================================
# COMBINE — blend Step 1+2's pattern-based score with Step 3's
# indicator-based score into one final decision
# ======================================================================

EXTREME_FEAR_MODES = ("symmetric", "risk_off")


def classify_direction(final_score: float, vix_level: float,
                        strong_buy_bar: float = 75, buy_bar: float = 60,
                        sell_bar: float = 40, strong_sell_bar: float = 25,
                        extreme_fear_mode: str = "symmetric",
                        vix_extreme: float = 35) -> str:
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
        # Validated buy-side panic bars (identical to entry_point_model2.py:
        # STRONG_BUY 80, BUY 70). Sell bars depend on the chosen mode.
        sb_bar, b_bar = 80, 70
        if extreme_fear_mode == "risk_off":
            ss_bar, s_bar = 30, 45     # sell EASIER in a panic (toward neutral)
        else:                          # "symmetric": exact mirror of 80/70
            ss_bar, s_bar = 20, 30
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
                        extreme_fear_mode: str = "symmetric") -> dict:
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

    final_score = weight_pattern * gated_score + weight_indicators * indicator_score
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
                                    extreme_fear_mode=extreme_fear_mode)

    return {
        "final_score": round(final_score, 2),
        "decision": decision,
        "direction": direction,
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
                       use_ml: bool = False,
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
    step3 = apply_indicator_step(ticker, step2, period=daily_period, use_ml=use_ml)
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
                      f"ROC-AUC={auc_str}, tested on {step3.get('ml_test_n')} days "
                      f"[DISPLAY ONLY — not in the score]")
            else:
                print(f"  ML confidence: unavailable ({step3.get('ml_error', 'training failed')})")

    # --- Enforce the order actually happened correctly ---
    assert [s["step"] for s in step_log] == [1, 2, 3], \
        f"Step order violated! Got {[s['step'] for s in step_log]}, expected [1, 2, 3]"
    timestamps = [s["timestamp"] for s in step_log]
    assert timestamps == sorted(timestamps), \
        "Step timestamps are not strictly increasing — steps ran out of order!"

    combined = combine_and_decide(step2, step3, weight_pattern=weight_pattern,
                                   weight_indicators=weight_indicators,
                                   extreme_fear_mode=extreme_fear_mode)

    # --- Exit levels: ATR-based profit target + stop-loss for the ---
    # --- direction we just produced. Volatility bands, not predictions. ---
    exit_levels = cf.compute_exit_levels(
        entry_price=step1["close"], direction=combined["direction"],
        atr=step1.get("atr"), stop_mult=stop_mult, target_mult=target_mult,
    )
    combined["exit_levels"] = exit_levels
    # ML confidence rides along in the output (display-only; not in final_score)
    combined["ml_confidence"] = step3.get("ai_confidence_score") if step3.get("ml_ok") else None
    combined["ml_accuracy"] = step3.get("ml_accuracy") if step3.get("ml_ok") else None

    if verbose:
        print(f"\n{'-' * 70}")
        print(f"  COMBINED: {combined['gated_score_contribution']} (pattern+reddit, "
              f"weight={weight_pattern}) + {combined['indicator_score_contribution']} "
              f"(indicators, weight={weight_indicators})")
        print(f"  FINAL SCORE: {combined['final_score']}  ->  ENTRY DECISION: {combined['decision']}  "
              f"|  DIRECTION: {combined['direction']}")
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
                use_ml=args.ml,
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
                  extreme_fear_mode: str = "symmetric") -> pd.DataFrame:
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
                                        extreme_fear_mode=extreme_fear_mode), axis=1
    )

    merged["forward_return"] = merged["Close"].shift(-forward_days) / merged["Close"] - 1
    merged = merged.dropna(subset=["forward_return"])

    return merged


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
    args = parser.parse_args()

    if args.compare_modes:
        compare_extreme_fear_modes(args.ticker, period=args.period,
                                    forward_days=args.forward_days,
                                    weight_pattern=args.weight_pattern,
                                    weight_indicators=args.weight_indicators)
        return

    merged = run_backtest(args.ticker, period=args.period, forward_days=args.forward_days,
                           weight_pattern=args.weight_pattern,
                           weight_indicators=args.weight_indicators,
                           extreme_fear_mode=args.extreme_fear_mode)
    summarize(merged, args.forward_days, extreme_fear_mode=args.extreme_fear_mode)


# ======================================================================
# CLI DISPATCHER — subcommands: run / multi / backtest
# ======================================================================

def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("run", "multi", "backtest"):
        print("Usage: python pipeline.py <run|multi|backtest> [args...]\n"
              "  run BTC ...        - single-ticker pipeline (was unified_model.py)\n"
              "  multi BTC ETH ...  - batch across tickers   (was run_multi_ticker.py)\n"
              "  backtest BTC ...   - historical backtest    (was backtest_direction.py)\n"
              "Run 'python pipeline.py <command> --help' for that command's options.")
        sys.exit(1)

    command = sys.argv.pop(1)  # remove the subcommand so each parser sees its own args
    if command == "run":
        main_run()
    elif command == "multi":
        main_multi()
    elif command == "backtest":
        main_backtest()


if __name__ == "__main__":
    main()
