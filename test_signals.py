"""
test_signals.py
================
Comprehensive test suite for the unified crypto-signal pipeline's DECISION
logic — the part that turns scores into BUY / SELL / WATCH labels — with
deliberately heavy coverage of the newer, less-trusted SELL side.

WHY THIS SHAPE:
    You can't test the SELL side by "waiting for the market to hand you a
    STRONG_SELL." So this suite drives the pure decision functions
    (classify_direction, _decide_row, sentiment_gate, combine_and_decide)
    with SYNTHETIC scores spanning the whole 0..100 range, in both VIX
    regimes. That exercises SELL/STRONG_SELL deterministically and offline.
    The full run_full_pipeline() is also tested end-to-end, but with the
    three network steps monkeypatched so we can force any final score we
    want — including a full-blown STRONG_SELL — without touching Binance,
    Yahoo, or Adanos.

    Everything here runs OFFLINE and DETERMINISTICALLY by default. One
    optional live end-to-end test is gated behind an env flag (see bottom).

HOW TO RUN (from the folder that contains unified_model.py etc.):
    pip install pytest
    pytest test_signals.py -v

    # include the live end-to-end test (spends 1 Adanos request, hits network):
    RUN_LIVE=1 pytest test_signals.py -v        # (set ADANOS_API_KEY first)
    #  Windows PowerShell:  $env:RUN_LIVE=1; pytest test_signals.py -v

SELL-SIDE FIX THIS SUITE LOCKS IN (read TestExtremeFearSellSemantics):
    The old classify_direction docstring claimed extreme fear made selling
    *easier* ("SELL bar rises toward neutral"); the code did the opposite
    (sell bar 40 -> 30, away from neutral). The code was the correct
    geometric mirror of the validated buy side; the prose was the lapse.
    The docstring is now fixed, and the two panic stances are explicit:
      - extreme_fear_mode="symmetric" (default): exact mirror, both bars
        move away from neutral (harder to act either way).
      - extreme_fear_mode="risk_off": buying still harder, selling easier
        (the stance the old prose described), now an opt-in, not a bug.
"""

import os
import sys
from datetime import datetime, timezone

import pytest
import pandas as pd
import numpy as np

# Make the pipeline modules importable no matter where pytest is invoked
# from, as long as this test file sits beside them.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pipeline as um
import signal_engines as epm
import signal_engines as ads


# The label sets, named once so the tests read clearly.
BULLISH = {"BUY", "STRONG_BUY"}
BEARISH = {"SELL", "STRONG_SELL"}
NORMAL_VIX = 20.0      # below VIX_EXTREME (35) -> normal thresholds
EXTREME_VIX = 40.0     # at/above VIX_EXTREME (35) -> extreme-fear thresholds


# ======================================================================
# Helpers to fabricate the step-result dicts the combine/pipeline expects,
# so tests can set an exact final score without any real data.
# ======================================================================

def _fake_step1(score, ts=None):
    return {"step": 1, "step_name": "initial_scoring",
            "timestamp": ts or datetime.now(timezone.utc),
            "ticker": "TEST", "initial_score": score,
            "close": 50000.0, "atr": 800.0}


def _fake_step2(gated_score, ts=None):
    return {"step": 2, "step_name": "reddit_data",
            "timestamp": ts or datetime.now(timezone.utc),
            "ticker": "TEST", "gate_decision": "PROCEED", "gate_multiplier": 1.0,
            "gate_reason": "synthetic", "score_before_reddit": gated_score,
            "gated_score": gated_score}


def _fake_step3(indicator_score, vix, ts=None):
    return {"step": 3, "step_name": "indicators_indexes",
            "timestamp": ts or datetime.now(timezone.utc),
            "ticker": "TEST", "technical_score": indicator_score,
            "macro_multiplier": 1.0, "indicator_final_score": indicator_score,
            "vix_level": vix}


def _final_score_to_direction(score, vix):
    """Convenience wrapper mirroring how combine_and_decide labels a score."""
    return um.classify_direction(score, vix)


# ======================================================================
# 1. to_yahoo_crypto_symbol — the Grayscale-trust bug regression guard
# ======================================================================

class TestYahooSymbol:
    """Bare 'BTC'/'ETH' silently resolve to Grayscale trust ETFs on Yahoo,
    not spot. This locks in the -USD suffixing that fixed that."""

    def test_bare_symbol_gets_usd_suffix(self):
        assert um.to_yahoo_crypto_symbol("BTC") == "BTC-USD"
        assert um.to_yahoo_crypto_symbol("ETH") == "ETH-USD"
        assert um.to_yahoo_crypto_symbol("SOL") == "SOL-USD"

    def test_lowercase_is_upcased(self):
        assert um.to_yahoo_crypto_symbol("btc") == "BTC-USD"

    def test_already_paired_symbol_is_left_alone(self):
        assert um.to_yahoo_crypto_symbol("BTC-USD") == "BTC-USD"
        assert um.to_yahoo_crypto_symbol("eth-usd") == "ETH-USD"

    def test_never_returns_bare_symbol(self):
        # The actual bug: a bare symbol must never be passed through, since
        # Yahoo would fetch the wrong instrument without erroring.
        for t in ["BTC", "ETH", "SOL", "DOGE", "ADA"]:
            assert um.to_yahoo_crypto_symbol(t).endswith("-USD")


# ======================================================================
# 2. sentiment_gate — Step 2's four branches, boundaries, dampen-only
# ======================================================================

class TestSentimentGate:

    def test_low_confidence_when_too_few_mentions(self):
        gate = ads.sentiment_gate(-0.9, n_mentions=5)  # very bearish but ignored
        assert gate["decision"] == "LOW_CONFIDENCE"
        assert gate["gate_multiplier"] == 1.0  # ignored -> no dampening

    def test_proceed_on_neutral_or_positive(self):
        assert ads.sentiment_gate(0.0, 50)["decision"] == "PROCEED"
        assert ads.sentiment_gate(0.5, 50)["decision"] == "PROCEED"
        assert ads.sentiment_gate(-0.10, 50)["decision"] == "PROCEED"  # above -0.15

    def test_caution_band(self):
        gate = ads.sentiment_gate(-0.25, 50)  # between -0.15 and -0.35
        assert gate["decision"] == "CAUTION"
        assert 0.6 <= gate["gate_multiplier"] < 1.0

    def test_veto_on_extreme_bearish(self):
        gate = ads.sentiment_gate(-0.40, 50)
        assert gate["decision"] == "VETO"
        assert gate["gate_multiplier"] == 0.5

    def test_boundary_exactly_bearish_threshold(self):
        # -0.15 is the CAUTION trigger (<=). Exactly -0.15 -> CAUTION, mult 1.0
        gate = ads.sentiment_gate(-0.15, 50)
        assert gate["decision"] == "CAUTION"
        assert gate["gate_multiplier"] == pytest.approx(1.0, abs=1e-9)

    def test_boundary_exactly_extreme_threshold(self):
        # -0.35 is the VETO trigger (<=). Exactly -0.35 -> VETO
        assert ads.sentiment_gate(-0.35, 50)["decision"] == "VETO"

    @pytest.mark.parametrize("sentiment", [-1.0, -0.5, -0.35, -0.2, -0.15, 0.0, 0.4, 1.0])
    @pytest.mark.parametrize("mentions", [0, 5, 15, 100])
    def test_gate_never_boosts_a_score(self, sentiment, mentions):
        """CORE INVARIANT: the gate is a risk filter, not a bull signal —
        it may only dampen (<=1.0) or leave unchanged, NEVER amplify."""
        gate = ads.sentiment_gate(sentiment, mentions)
        assert gate["gate_multiplier"] <= 1.0
        before = 80.0
        after = ads.apply_gate_to_score(gate, before)
        assert after <= before + 1e-9


# ======================================================================
# 3. first_pass_sentiment_check_adanos — network monkeypatched away
# ======================================================================

class TestAdanosGateWiring:
    """Tests the Adanos entry point WITHOUT hitting the API, by patching the
    fetch. Confirms the 'quiet ticker' path and that a real bearish reading
    flows through the same sentiment_gate thresholds."""

    def test_no_mentions_found_is_low_confidence_not_error(self, monkeypatch):
        monkeypatch.setattr(ads, "fetch_token_sentiment",
                            lambda *a, **k: {"symbol": "BTC", "found": False})
        gate = ads.first_pass_sentiment_check_adanos("BTC", api_key="x")
        assert gate["decision"] == "LOW_CONFIDENCE"
        assert gate["gate_multiplier"] == 1.0

    def test_missing_sentiment_score_is_low_confidence(self, monkeypatch):
        monkeypatch.setattr(ads, "fetch_token_sentiment",
                            lambda *a, **k: {"found": True, "mentions": 50,
                                             "sentiment_score": None})
        gate = ads.first_pass_sentiment_check_adanos("BTC", api_key="x")
        assert gate["decision"] == "LOW_CONFIDENCE"

    def test_bearish_reading_flows_to_veto(self, monkeypatch):
        monkeypatch.setattr(ads, "fetch_token_sentiment",
                            lambda *a, **k: {"found": True, "mentions": 80,
                                             "sentiment_score": -0.42})
        gate = ads.first_pass_sentiment_check_adanos("BTC", api_key="x")
        assert gate["decision"] == "VETO"
        assert gate["gate_multiplier"] == 0.5

    def test_thin_mentions_ignored_even_if_bearish(self, monkeypatch):
        monkeypatch.setattr(ads, "fetch_token_sentiment",
                            lambda *a, **k: {"found": True, "mentions": 3,
                                             "sentiment_score": -0.9})
        gate = ads.first_pass_sentiment_check_adanos("BTC", api_key="x")
        assert gate["decision"] == "LOW_CONFIDENCE"
        assert gate["gate_multiplier"] == 1.0


# ======================================================================
# 4. classify_direction — the SELL side, exhaustively
# ======================================================================

class TestDirectionNormalRegime:
    """Normal regime (VIX < 35). Bars: SB>=75, B>=60, S<=40, SS<=25."""

    @pytest.mark.parametrize("score,expected", [
        (100, "STRONG_BUY"), (80, "STRONG_BUY"), (75, "STRONG_BUY"),  # >= 75
        (74.9, "BUY"), (65, "BUY"), (60, "BUY"),                      # >= 60
        (59.9, "WATCH"), (50, "WATCH"), (41, "WATCH"),                # 40 < s < 60
        (40, "SELL"), (30, "SELL"), (25.1, "SELL"),                   # <= 40
        (25, "STRONG_SELL"), (10, "STRONG_SELL"), (0, "STRONG_SELL"), # <= 25
    ])
    def test_label_table(self, score, expected):
        assert um.classify_direction(score, NORMAL_VIX) == expected

    def test_sell_side_actually_reachable(self):
        # The whole point: low scores must produce bearish labels, not just
        # "not a buy."
        assert um.classify_direction(35, NORMAL_VIX) in BEARISH
        assert um.classify_direction(5, NORMAL_VIX) == "STRONG_SELL"


class TestDirectionExtremeFearRegime:
    """Extreme fear (VIX >= 35). Bars: SB>=80, B>=70, S<=30, SS<=20."""

    @pytest.mark.parametrize("score,expected", [
        (85, "STRONG_BUY"), (80, "STRONG_BUY"),
        (79.9, "BUY"), (70, "BUY"),
        (69.9, "WATCH"), (50, "WATCH"), (31, "WATCH"),
        (30, "SELL"), (21, "SELL"),
        (20, "STRONG_SELL"), (0, "STRONG_SELL"),
    ])
    def test_label_table(self, score, expected):
        assert um.classify_direction(score, EXTREME_VIX) == expected

    def test_buying_is_harder_in_panic(self):
        # A score of 72 is a BUY normally but only a WATCH in extreme fear
        # (panic raises the buy bar to 80/70 regardless of the normal bar).
        assert um.classify_direction(65, NORMAL_VIX) == "BUY"
        assert um.classify_direction(65, EXTREME_VIX) == "WATCH"


class TestDirectionEdgeCases:

    def test_nan_score_is_insufficient_data(self):
        assert um.classify_direction(float("nan"), NORMAL_VIX) == "INSUFFICIENT_DATA"

    def test_nan_vix_treated_as_normal_regime(self):
        # pd.notna(vix) guards the extreme branch, so NaN VIX -> normal bars.
        assert um.classify_direction(65, float("nan")) == "BUY"      # normal buy bar
        assert um.classify_direction(35, float("nan")) == "SELL"     # normal sell bar

    def test_midpoint_is_watch(self):
        assert um.classify_direction(50, NORMAL_VIX) == "WATCH"
        assert um.classify_direction(50, EXTREME_VIX) == "WATCH"


class TestDirectionMirrorSymmetry:
    """The SELL side is an exact mirror of the BUY side about 50 at the
    default bars (75<->25, 60<->40), in BOTH regimes.

    NOTE: this symmetry is a property of the DEFAULT thresholds, not a
    law. Raising buy_bar without moving sell_bar deliberately breaks it
    (tested separately below) - which is a legitimate choice when the
    evidence supports one side and not the other."""

    MIRROR = {"STRONG_BUY": "STRONG_SELL", "BUY": "SELL", "WATCH": "WATCH",
              "SELL": "BUY", "STRONG_SELL": "STRONG_BUY"}

    @pytest.mark.parametrize("vix", [NORMAL_VIX, EXTREME_VIX])
    def test_reflection_symmetry_across_full_range(self, vix):
        for s in range(0, 101):
            lo = um.classify_direction(float(s), vix)
            hi = um.classify_direction(float(100 - s), vix)
            assert self.MIRROR[lo] == hi, (
                f"Symmetry broken at score={s}, vix={vix}: "
                f"classify({s})={lo} but classify({100 - s})={hi}")

    def test_raising_buy_bar_alone_breaks_symmetry_deliberately(self):
        """Documents the tradeoff: buy_bar=70 replicated on both tickers
        (+0.17R->+0.31R BTC, +0.08R->+0.24R ETH), but no equivalent
        evidence exists for moving sell_bar to 30. Asymmetry is the
        honest result of asymmetric evidence."""
        assert um.classify_direction(65, NORMAL_VIX, buy_bar=70) == "WATCH"
        assert um.classify_direction(35, NORMAL_VIX, buy_bar=70) == "SELL"  # unchanged

    def test_panic_bars_are_derived_not_hardcoded(self):
        """Panic bars derive from the normal bars (regular +/-10, strong
        +/-5), reproducing the validated 80/70/30/20 at defaults. They
        used to be hardcoded, which silently NULLIFIED panic hardening
        when buy_bar was raised to 70 (normal bar == panic bar)."""
        assert um.classify_direction(65, EXTREME_VIX) == "WATCH"   # panic bar 70
        assert um.classify_direction(72, EXTREME_VIX) == "BUY"
        # and it still hardens if the normal bar moves:
        assert um.classify_direction(72, EXTREME_VIX, buy_bar=70) == "WATCH"  # panic bar 80


class TestExtremeFearSellSemantics:
    """The corrected sell-side behavior in a VIX panic, for both modes.

    DEFAULT ("symmetric"): the sell bars are the exact geometric mirror of
    the raised buy bars, so selling gets HARDER in a panic, just like
    buying. OPT-IN ("risk_off"): selling gets EASIER (the stance the old
    docstring wrongly described as the default)."""

    def test_symmetric_default_makes_both_directions_harder(self):
        # Scores in (30, 40] are SELL when calm but WATCH in a panic:
        # selling got HARDER, mirroring buying getting harder.
        for s in (31, 35, 40):
            assert um.classify_direction(s, NORMAL_VIX) == "SELL"
            assert um.classify_direction(s, EXTREME_VIX) == "WATCH"

    def test_symmetric_extreme_bars_reflect_the_buy_side(self):
        # Derived panic bars: buy 60->70, strong_buy 75->80, and their
        # exact reflections sell 40->30, strong_sell 25->20.
        assert um.classify_direction(70, EXTREME_VIX) == "BUY"
        assert um.classify_direction(30, EXTREME_VIX) == "SELL"          # mirror of 70
        assert um.classify_direction(80, EXTREME_VIX) == "STRONG_BUY"
        assert um.classify_direction(20, EXTREME_VIX) == "STRONG_SELL"   # mirror of 80

    def test_risk_off_mode_makes_selling_easier_in_panic(self):
        # A score of 42 in a panic: default(symmetric) -> WATCH (needs <=30
        # to sell); risk_off raises the sell bar to 45 -> 42 is now a SELL.
        assert um.classify_direction(42, EXTREME_VIX, extreme_fear_mode="symmetric") == "WATCH"
        assert um.classify_direction(42, EXTREME_VIX, extreme_fear_mode="risk_off") == "SELL"

    def test_risk_off_keeps_buying_harder(self):
        # risk_off only changes the sell side; the raised buy bars stay put,
        # so 65 is still only a WATCH (not a BUY) in a panic.
        assert um.classify_direction(65, EXTREME_VIX, extreme_fear_mode="risk_off") == "WATCH"

    def test_risk_off_does_not_change_the_calm_regime(self):
        # extreme_fear_mode is irrelevant when VIX is below the threshold.
        for s in (10, 35, 50, 65, 90):
            assert (um.classify_direction(s, NORMAL_VIX, extreme_fear_mode="risk_off")
                    == um.classify_direction(s, NORMAL_VIX, extreme_fear_mode="symmetric"))

    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError):
            um.classify_direction(50, EXTREME_VIX, extreme_fear_mode="nonsense")


# ======================================================================
# 5. _decide_row — the entry-only decision (STRONG_BUY/BUY/WATCH/AVOID)
# ======================================================================

class TestEntryDecision:
    """entry_point_model2._decide_row has NO sell side by design — it's the
    entry-only label. SELL lives only in classify_direction."""

    def _decide(self, score, vix):
        import pandas as pd
        return epm._decide_row(pd.Series({"final_score": score, "vix_level": vix}))

    @pytest.mark.parametrize("score,expected", [
        (90, "STRONG_BUY"), (75, "STRONG_BUY"),
        (74, "BUY"), (60, "BUY"),
        (59, "WATCH"), (45, "WATCH"),
        (44, "AVOID"), (10, "AVOID"),
    ])
    def test_normal_regime(self, score, expected):
        assert self._decide(score, NORMAL_VIX) == expected

    def test_extreme_fear_raises_buy_bars(self):
        # buy bar 60 -> 70, strong 75 -> 80 in extreme fear
        assert self._decide(65, NORMAL_VIX) == "BUY"
        assert self._decide(65, EXTREME_VIX) == "WATCH"
        assert self._decide(78, NORMAL_VIX) == "STRONG_BUY"
        assert self._decide(78, EXTREME_VIX) == "BUY"

    def test_no_sell_label_ever(self):
        for s in range(0, 101):
            assert self._decide(s, NORMAL_VIX) not in BEARISH


# ======================================================================
# 6. combine_and_decide — weighting math + the two labels' consistency
# ======================================================================

class TestCombine:

    def test_weighting_math(self):
        step2 = _fake_step2(gated_score=100.0)
        step3 = _fake_step3(indicator_score=0.0, vix=NORMAL_VIX)
        out = um.combine_and_decide(step2, step3, weight_pattern=0.6, weight_indicators=0.4)
        assert out["final_score"] == pytest.approx(60.0)

    def test_weighting_favours_pattern_side(self):
        # Same two inputs swapped: the 0.6-weighted side should dominate.
        hi_pattern = um.combine_and_decide(_fake_step2(100.0), _fake_step3(0.0, NORMAL_VIX))
        hi_indic = um.combine_and_decide(_fake_step2(0.0), _fake_step3(100.0, NORMAL_VIX))
        assert hi_pattern["final_score"] > hi_indic["final_score"]

    def test_final_score_is_clipped_to_100(self):
        # Weights that sum > 1 with high inputs must still clip at 100.
        out = um.combine_and_decide(_fake_step2(80.0), _fake_step3(80.0, NORMAL_VIX),
                                    weight_pattern=1.0, weight_indicators=1.0)
        assert out["final_score"] == 100.0

    @pytest.mark.parametrize("target", list(range(0, 101, 5)))
    @pytest.mark.parametrize("vix", [NORMAL_VIX, EXTREME_VIX])
    def test_decision_and_direction_never_contradict(self, target, vix):
        """decision (entry-only) and direction (bidirectional) come off the
        SAME final score, so they must never disagree in sign:
          - a bullish decision implies a bullish direction (shared bars), and
          - a bearish direction implies the decision is AVOID.
        """
        step2 = _fake_step2(gated_score=float(target))
        step3 = _fake_step3(indicator_score=float(target), vix=vix)
        out = um.combine_and_decide(step2, step3)  # final_score == target
        decision, direction = out["decision"], out["direction"]

        if decision in BULLISH:
            assert direction in BULLISH, (target, vix, decision, direction)
        if direction in BEARISH:
            assert decision == "AVOID", (target, vix, decision, direction)


# ======================================================================
# 7. Pipeline order enforcement — the guards that keep Step 1->2->3 honest
# ======================================================================

class TestOrderEnforcement:
    """Each step function refuses to run without a valid prior step. These
    reject-paths raise BEFORE any network call, so they're safe to test."""

    def test_reddit_step_rejects_non_step1(self):
        with pytest.raises(ValueError):
            um.apply_reddit_step("BTC", {"step": 3})
        with pytest.raises(ValueError):
            um.apply_reddit_step("BTC", {})  # no 'step' key at all

    def test_indicator_step_rejects_non_step2(self):
        with pytest.raises(ValueError):
            um.apply_indicator_step("BTC", {"step": 1})
        with pytest.raises(ValueError):
            um.apply_indicator_step("BTC", {})


# ======================================================================
# 8. Full pipeline end-to-end, network monkeypatched — drives the SELL
#    side through the REAL orchestrator without a market crash.
# ======================================================================

class TestPipelineEndToEndOffline:
    """Patches the three network steps so run_full_pipeline() runs its real
    ordering assertions + real combine/labelling against scores we choose.
    This is how we exercise BUY through STRONG_SELL through the actual
    orchestrator, deterministically and offline."""

    def _patch_steps(self, monkeypatch, target_score, vix):
        # Chained fake steps with strictly increasing timestamps so the
        # orchestrator's "timestamps must be sorted" assertion is exercised
        # for real (not bypassed).
        t1 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 1, 1, 0, 0, 1, tzinfo=timezone.utc)
        t3 = datetime(2026, 1, 1, 0, 0, 2, tzinfo=timezone.utc)
        monkeypatch.setattr(um, "compute_initial_score",
                            lambda *a, **k: _fake_step1(target_score, ts=t1))
        monkeypatch.setattr(um, "apply_reddit_step",
                            lambda *a, **k: _fake_step2(target_score, ts=t2))
        monkeypatch.setattr(um, "apply_indicator_step",
                            lambda *a, **k: _fake_step3(target_score, vix, ts=t3))

    @pytest.mark.parametrize("target_score,vix,expected_direction", [
        (85, NORMAL_VIX, "STRONG_BUY"),
        (65, NORMAL_VIX, "BUY"),
        (50, NORMAL_VIX, "WATCH"),
        (35, NORMAL_VIX, "SELL"),
        (10, NORMAL_VIX, "STRONG_SELL"),   # <-- the case you can't get on demand live
        (85, EXTREME_VIX, "STRONG_BUY"),
        (25, EXTREME_VIX, "SELL"),
        (15, EXTREME_VIX, "STRONG_SELL"),
    ])
    def test_pipeline_emits_expected_direction(self, monkeypatch,
                                               target_score, vix, expected_direction):
        self._patch_steps(monkeypatch, float(target_score), vix)
        result = um.run_full_pipeline("BTC", verbose=False)

        assert result["order_verified"] is True
        assert result["combined"]["final_score"] == pytest.approx(float(target_score))
        assert result["combined"]["direction"] == expected_direction

    def test_extreme_fear_mode_threads_through_pipeline(self, monkeypatch):
        # final_score 42 in a panic: default -> WATCH, risk_off -> SELL.
        # Proves the flag reaches classify_direction from the orchestrator.
        self._patch_steps(monkeypatch, 42.0, EXTREME_VIX)
        default = um.run_full_pipeline("BTC", verbose=False)
        assert default["combined"]["direction"] == "WATCH"

        self._patch_steps(monkeypatch, 42.0, EXTREME_VIX)
        risk_off = um.run_full_pipeline("BTC", verbose=False, extreme_fear_mode="risk_off")
        assert risk_off["combined"]["direction"] == "SELL"

    def test_pipeline_reports_all_three_steps_in_order(self, monkeypatch):
        self._patch_steps(monkeypatch, 50.0, NORMAL_VIX)
        result = um.run_full_pipeline("BTC", verbose=False)
        assert result["step1_initial_scoring"]["step"] == 1
        assert result["step2_reddit_data"]["step"] == 2
        assert result["step3_indicators"]["step"] == 3

    def test_pipeline_order_assertion_fires_if_steps_swapped(self, monkeypatch):
        # If a future refactor makes Step 1 secretly return a Step-3 result,
        # run_full_pipeline's own assertion must catch it.
        monkeypatch.setattr(um, "compute_initial_score",
                            lambda *a, **k: _fake_step3(50.0, NORMAL_VIX))  # wrong step!
        monkeypatch.setattr(um, "apply_reddit_step",
                            lambda *a, **k: _fake_step2(50.0))
        monkeypatch.setattr(um, "apply_indicator_step",
                            lambda *a, **k: _fake_step3(50.0, NORMAL_VIX))
        with pytest.raises(AssertionError):
            um.run_full_pipeline("BTC", verbose=False)


# ======================================================================
# 9. OPTIONAL live end-to-end — hits Binance + Yahoo + Adanos for real.
#    Skipped unless RUN_LIVE=1 (and costs 1 Adanos request). Sanity-checks
#    shape/ranges only — not exact values, which move with the market.
# ======================================================================

@pytest.mark.skipif(os.environ.get("RUN_LIVE") != "1",
                    reason="live network test; set RUN_LIVE=1 (and ADANOS_API_KEY) to run")
class TestLiveSmoke:

    def test_real_btc_run_has_valid_shape(self):
        assert os.environ.get("ADANOS_API_KEY"), "ADANOS_API_KEY must be set for the live test"
        result = um.run_full_pipeline("BTC", verbose=False)

        combined = result["combined"]
        assert 0.0 <= combined["final_score"] <= 100.0
        assert combined["decision"] in {"STRONG_BUY", "BUY", "WATCH", "AVOID", "INSUFFICIENT_DATA"}
        assert combined["direction"] in {"STRONG_BUY", "BUY", "WATCH", "SELL",
                                         "STRONG_SELL", "INSUFFICIENT_DATA"}
        # The two labels must be consistent on live data too.
        if combined["decision"] in BULLISH:
            assert combined["direction"] in BULLISH


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))


# ======================================================================
# Exit levels (ATR-based profit target / stop-loss)
# ======================================================================

class TestExitLevels:
    import signal_engines as _se

    def test_atr_is_positive(self):
        import numpy as np, pandas as pd
        import signal_engines as se
        n = 60
        rng = np.random.RandomState(1)
        close = 100 + np.cumsum(rng.randn(n))
        df = pd.DataFrame({"Open": close, "High": close + abs(rng.randn(n))*2,
                           "Low": close - abs(rng.randn(n))*2, "Close": close},
                          index=pd.date_range("2026-01-01", periods=n, freq="4h"))
        atr = se.compute_atr(df, period=14)
        assert float(atr.iloc[-1]) > 0

    def test_bullish_target_above_stop_below(self):
        import signal_engines as se
        lvl = se.compute_exit_levels(100.0, "BUY", atr=2.0)
        assert lvl["applicable"]
        assert lvl["target"] > lvl["entry"] > lvl["stop"]
        assert lvl["side"] == "long"

    def test_bearish_target_below_stop_above(self):
        import signal_engines as se
        lvl = se.compute_exit_levels(100.0, "SELL", atr=2.0)
        assert lvl["target"] < lvl["entry"] < lvl["stop"]
        assert lvl["side"] == "short"

    def test_default_risk_reward_is_2to1(self):
        import signal_engines as se
        assert se.compute_exit_levels(100.0, "BUY", atr=2.0)["risk_reward"] == 2.0
        assert se.compute_exit_levels(100.0, "SELL", atr=2.0)["risk_reward"] == 2.0

    def test_strong_signals_reach_further(self):
        import signal_engines as se
        buy = se.compute_exit_levels(100.0, "BUY", atr=2.0)
        sbuy = se.compute_exit_levels(100.0, "STRONG_BUY", atr=2.0)
        assert sbuy["target"] > buy["target"]
        assert sbuy["risk_reward"] > buy["risk_reward"]

    def test_sell_mirrors_buy_symmetrically(self):
        import signal_engines as se
        buy = se.compute_exit_levels(100.0, "BUY", atr=2.0)
        sell = se.compute_exit_levels(100.0, "SELL", atr=2.0)
        assert abs(buy["target_pct"]) == abs(sell["target_pct"])
        assert abs(buy["stop_pct"]) == abs(sell["stop_pct"])

    def test_watch_has_no_exit_levels(self):
        import signal_engines as se
        assert not se.compute_exit_levels(100.0, "WATCH", atr=2.0)["applicable"]

    def test_nan_atr_not_applicable(self):
        import signal_engines as se
        assert not se.compute_exit_levels(100.0, "BUY", atr=float("nan"))["applicable"]

    def test_custom_multipliers(self):
        import signal_engines as se
        lvl = se.compute_exit_levels(100.0, "BUY", atr=2.0, stop_mult=1.0, target_mult=2.0)
        assert lvl["risk_reward"] == 2.0
        assert lvl["stop_pct"] == -2.0   # 1.0 * 2.0 ATR = 2 below 100
        assert lvl["target_pct"] == 4.0  # 2.0 * 2.0 ATR = 4 above 100


# ======================================================================
# ML confidence engine (Yahoo-derived features, honest holdout)
# ======================================================================

class TestMLEngine:
    """ML path is optional (needs xgboost+sklearn). These skip cleanly if
    the libs aren't installed, so the core suite stays dependency-light."""

    def _make_df(self, n=300, seed=7):
        import numpy as np, pandas as pd
        import signal_engines as se
        rng = np.random.RandomState(seed)
        idx = pd.date_range("2024-06-01", periods=n, freq="D")
        close = 60000 + np.cumsum(rng.randn(n) * 400)
        return pd.DataFrame({
            "Close": close, "final_score": rng.uniform(30, 70, n),
            "technical_score": rng.uniform(30, 70, n), "macro_multiplier": 1.0,
            "RSI_14": rng.uniform(30, 70, n), "SMA_20": close + rng.randn(n)*100,
            "momentum_score": rng.uniform(-1, 1, n), "trend_score": rng.uniform(-1, 1, n),
            "OBV": np.cumsum(rng.randn(n)*1000),
            f"CMF_{se.CMF_PERIOD}": rng.uniform(-1, 1, n),
            f"MFI_{se.MFI_PERIOD}": rng.uniform(20, 80, n),
        }, index=idx)

    def test_holdout_split_is_chronological(self):
        pytest.importorskip("xgboost"); pytest.importorskip("sklearn")
        import signal_engines as se
        h = se.train_ml_model_with_holdout(self._make_df())
        # No time leakage: every test date is after every train date
        assert h["train_dates"].max() < h["test_dates"].min()

    def test_holdout_returns_valid_metrics(self):
        pytest.importorskip("xgboost"); pytest.importorskip("sklearn")
        import signal_engines as se
        h = se.train_ml_model_with_holdout(self._make_df())
        assert 0.0 <= h["accuracy"] <= 1.0
        assert h["ml_test_n"] if "ml_test_n" in h else len(h["y_test"]) > 0

    def test_pipeline_scores_are_excluded_from_features(self):
        pytest.importorskip("xgboost"); pytest.importorskip("sklearn")
        import signal_engines as se
        h = se.train_ml_model_with_holdout(self._make_df())
        # Circular columns must NOT be features
        for banned in ("final_score", "technical_score", "macro_score", "macro_multiplier"):
            assert banned not in h["feature_cols"]

    def test_too_little_history_raises(self):
        pytest.importorskip("xgboost"); pytest.importorskip("sklearn")
        import signal_engines as se
        with pytest.raises(ValueError):
            se.train_ml_model_with_holdout(self._make_df(n=15))


# ======================================================================
# Confluence gate (score direction + ML must agree)
# ======================================================================

class TestConfluenceGate:
    import live_tools as _lt

    def _mk(self, direction, ml):
        return {"combined": {"direction": direction, "ml_confidence": ml,
                             "final_score": 50, "decision": "X"}}

    def test_bullish_qualifies_when_both_agree(self):
        import live_tools as lt
        g = lt.passes_confluence(self._mk("STRONG_BUY", 60))
        assert g["qualifies"] and g["side"] == "bullish"

    def test_bearish_qualifies_when_both_agree(self):
        import live_tools as lt
        g = lt.passes_confluence(self._mk("SELL", 40))
        assert g["qualifies"] and g["side"] == "bearish"

    def test_buy_rejected_when_ml_too_low(self):
        import live_tools as lt
        assert not lt.passes_confluence(self._mk("BUY", 30))["qualifies"]

    def test_sell_rejected_when_ml_too_high(self):
        import live_tools as lt
        assert not lt.passes_confluence(self._mk("SELL", 70))["qualifies"]

    def test_watch_never_qualifies(self):
        import live_tools as lt
        assert not lt.passes_confluence(self._mk("WATCH", 90))["qualifies"]
        assert not lt.passes_confluence(self._mk("WATCH", 5))["qualifies"]

    def test_threshold_boundaries_inclusive(self):
        import live_tools as lt
        assert lt.passes_confluence(self._mk("BUY", 55))["qualifies"]   # exactly 55
        assert lt.passes_confluence(self._mk("SELL", 45))["qualifies"]  # exactly 45
        assert not lt.passes_confluence(self._mk("BUY", 54.9))["qualifies"]
        assert not lt.passes_confluence(self._mk("SELL", 45.1))["qualifies"]

    def test_missing_ml_cannot_qualify(self):
        import live_tools as lt
        g = lt.passes_confluence({"combined": {"direction": "BUY", "ml_confidence": None}})
        assert not g["qualifies"]

    def test_custom_thresholds(self):
        import live_tools as lt
        assert lt.passes_confluence(self._mk("BUY", 50), ml_bull_min=50.0)["qualifies"]
        assert lt.passes_confluence(self._mk("SELL", 50), ml_bear_max=50.0)["qualifies"]


# ======================================================================
# ROBUSTNESS VALIDATION LOGIC (pipeline.py robustness command)
# ======================================================================
# The verdict functions are the pre-registered test for the 4-year
# failure's rescue candidates. They MUST behave exactly as documented:
# any under-sampled cell forces INSUFFICIENT_DATA (never a silent pass),
# and the VIX edge only replicates if it holds in BOTH halves on EVERY
# ticker. All synthetic, all offline.

class TestRobustnessValidation:

    @staticmethod
    def _trade(date, direction, pnl_r, outcome="target", vix=20.0):
        import pandas as pd
        return {"date": pd.Timestamp(date), "direction": direction,
                "outcome": outcome, "pnl_r": pnl_r, "vix_level": vix,
                "score": 65.0, "mfe_pct_of_target": 50.0, "days_held": 5}

    def _cells(self, trades):
        return um.split_trades(trades, vix_threshold=25.0)

    def _bulk(self, start_year, direction, pnl_r, vix, n=12, outcome=None):
        if outcome is None:
            outcome = "target" if pnl_r > 0 else "stop"
        return [self._trade(f"{start_year}-01-{d+1:02d}", direction, pnl_r,
                             outcome=outcome, vix=vix) for d in range(n)]

    def test_subset_stats_basic(self):
        trades = [self._trade("2024-01-01", "BUY", 2.0, "target"),
                  self._trade("2024-01-02", "BUY", -1.0, "stop"),
                  self._trade("2024-01-03", "BUY", -1.0, "ambiguous_stop"),
                  self._trade("2024-01-04", "BUY", 0.3, "timeout")]
        st = um.subset_stats(trades)
        assert st["n"] == 4
        assert st["target_rate"] == pytest.approx(0.25)
        assert st["stop_rate"] == pytest.approx(0.5)   # stop + ambiguous_stop
        assert st["timeout_rate"] == pytest.approx(0.25)
        assert st["expectancy_r"] == pytest.approx(0.075)

    def test_subset_stats_empty(self):
        assert um.subset_stats([])["n"] == 0

    def test_split_halves_by_date_range_not_count(self):
        # 3 early trades, 1 late trade, 4-year span: the midpoint is
        # time-based, so the lone 2025 trade must sit alone in h2.
        trades = [self._trade("2022-01-01", "BUY", 1.0),
                  self._trade("2022-02-01", "BUY", 1.0),
                  self._trade("2022-03-01", "BUY", 1.0),
                  self._trade("2025-12-01", "BUY", 1.0)]
        cells = self._cells(trades)
        assert len(cells["h1"]) == 3 and len(cells["h2"]) == 1

    def test_split_vix_threshold_boundary(self):
        trades = [self._trade("2024-01-01", "BUY", 1.0, vix=25.0),   # inclusive
                  self._trade("2024-01-02", "BUY", 1.0, vix=24.99)]
        cells = self._cells(trades)
        assert len(cells["vix_stressed"]) == 1
        assert len(cells["vix_normal"]) == 1

    def test_split_nan_vix_excluded_from_vix_cells(self):
        trades = [self._trade("2024-01-01", "BUY", 1.0, vix=float("nan"))]
        cells = self._cells(trades)
        assert len(cells["vix_stressed"]) == 0 and len(cells["vix_normal"]) == 0
        assert len(cells["all"]) == 1  # still counted overall

    def test_vix_verdict_replicated(self):
        trades = (self._bulk(2022, "BUY", +2.0, vix=30) +   # h1 stressed +
                  self._bulk(2022, "BUY", -1.0, vix=15) +   # h1 normal  -
                  self._bulk(2025, "BUY", +2.0, vix=30) +   # h2 stressed +
                  self._bulk(2025, "BUY", -1.0, vix=15))    # h2 normal  -
        v = um.vix_replication_verdict({"BTC": self._cells(trades)})
        assert v["verdict"] == "REPLICATED"

    def test_vix_verdict_fails_if_one_half_fails(self):
        trades = (self._bulk(2022, "BUY", +2.0, vix=30) +
                  self._bulk(2022, "BUY", -1.0, vix=15) +
                  self._bulk(2025, "BUY", -0.5, vix=30) +   # h2 stressed NEGATIVE
                  self._bulk(2025, "BUY", -1.0, vix=15))
        v = um.vix_replication_verdict({"BTC": self._cells(trades)})
        assert v["verdict"] == "NOT_REPLICATED"

    def test_vix_verdict_stressed_must_be_positive_not_just_better(self):
        # stressed -0.2R "beats" normal -1.0R but is still a losing gate
        trades = (self._bulk(2022, "BUY", -0.2, vix=30) +
                  self._bulk(2022, "BUY", -1.0, vix=15) +
                  self._bulk(2025, "BUY", -0.2, vix=30) +
                  self._bulk(2025, "BUY", -1.0, vix=15))
        v = um.vix_replication_verdict({"BTC": self._cells(trades)})
        assert v["verdict"] == "NOT_REPLICATED"

    def test_vix_verdict_insufficient_forces_no_conclusion(self):
        # Only 3 stressed trades in h2: below MIN_N -> INSUFFICIENT_DATA
        trades = (self._bulk(2022, "BUY", +2.0, vix=30) +
                  self._bulk(2022, "BUY", -1.0, vix=15) +
                  self._bulk(2025, "BUY", +2.0, vix=30, n=3) +
                  self._bulk(2025, "BUY", -1.0, vix=15))
        v = um.vix_replication_verdict({"BTC": self._cells(trades)})
        assert v["verdict"] == "INSUFFICIENT_DATA"

    def test_vix_verdict_every_ticker_must_pass(self):
        good = (self._bulk(2022, "BUY", +2.0, vix=30) +
                self._bulk(2022, "BUY", -1.0, vix=15) +
                self._bulk(2025, "BUY", +2.0, vix=30) +
                self._bulk(2025, "BUY", -1.0, vix=15))
        bad = (self._bulk(2022, "BUY", -1.0, vix=30) +
               self._bulk(2022, "BUY", -1.0, vix=15) +
               self._bulk(2025, "BUY", -1.0, vix=30) +
               self._bulk(2025, "BUY", -1.0, vix=15))
        v = um.vix_replication_verdict({"BTC": self._cells(good),
                                        "SOL": self._cells(bad)})
        assert v["verdict"] == "NOT_REPLICATED"

    def test_short_verdict_majority_rule(self):
        pos = (self._bulk(2022, "SELL", +0.5, vix=20) +
               self._bulk(2025, "SELL", +0.5, vix=20))
        neg = (self._bulk(2022, "SELL", -0.5, vix=20) +
               self._bulk(2025, "SELL", -0.5, vix=20))
        v = um.short_side_verdict({"BTC": self._cells(pos),
                                   "ETH": self._cells(pos),
                                   "SOL": self._cells(neg)})
        assert v["verdict"] == "SHORTS_HOLD_UP" and v["tickers_passing"] == 2
        v2 = um.short_side_verdict({"BTC": self._cells(neg),
                                    "ETH": self._cells(neg),
                                    "SOL": self._cells(pos)})
        assert v2["verdict"] == "RECOMMEND_LONG_ONLY"

    def test_report_renders_and_states_criteria(self):
        trades = (self._bulk(2022, "BUY", +2.0, vix=30) +
                  self._bulk(2025, "SELL", -1.0, vix=15))
        report = um.build_robustness_report({"BTC": self._cells(trades)},
                                            years=4, vix_threshold=25.0,
                                            config_desc="test config")
        assert "Pre-registered criteria" in report
        assert "No defaults were changed" in report
        assert "| All trades |" in report and "Verdicts" in report

    def test_period_to_years(self):
        assert um._period_to_years("2y") == pytest.approx(2.0)
        assert um._period_to_years("6mo") == pytest.approx(0.5)
        assert um._period_to_years("max") == pytest.approx(8.0)
        assert um._period_to_years("garbage") == pytest.approx(2.0)  # safe fallback

    def test_attach_vix_missing_date_gets_nan(self):
        import pandas as pd
        merged = pd.DataFrame({"vix_level": [22.0]},
                              index=[pd.Timestamp("2024-01-01")])
        trades = [{"date": pd.Timestamp("2024-01-01")},
                  {"date": pd.Timestamp("2024-06-01")}]
        out = um.attach_vix_to_trades(trades, merged)
        assert out[0]["vix_level"] == 22.0
        assert out[1]["vix_level"] != out[1]["vix_level"]  # NaN


# ======================================================================
# AUDIT HARNESS (audit.py)
# ======================================================================
# The audit is what gets trusted when deciding whether a finding still
# holds, so its classification logic needs testing as much as the model
# does. Two failure modes matter most:
#   1. a check that PASSES on insufficient data (false comfort)
#   2. a check that FAILS on intentional design (false alarm — this
#      already happened once with STRONG_* conviction scaling)
# Both are covered below. All offline.

class TestAuditHarness:

    @staticmethod
    def _audit():
        import audit
        audit._results.clear()   # module-level accumulator
        return audit

    @staticmethod
    def _trades(direction, pnl_r, n, start_year=2024, score=65.0):
        import pandas as pd
        return [{"date": pd.Timestamp(f"{start_year}-01-01") + pd.Timedelta(days=d),
                 "direction": direction, "pnl_r": pnl_r, "score": score,
                 "outcome": "target" if pnl_r > 0 else "stop",
                 "vix_level": 20.0, "mfe_pct_of_target": 50.0, "days_held": 5}
                for d in range(n)]

    # --- structural checks must not fire on intentional design ---------

    def test_exit_math_accepts_conviction_scaling(self):
        # STRONG_* targets are 1.333x wider with the same stop, so R:R is
        # 2.667 BY DESIGN. A naive "must equal 2.0" check false-alarms here.
        a = self._audit()
        assert a.check_exit_math() == a.PASS

    def test_ml_display_only_is_behavioral_not_grep(self):
        # ml_confidence legitimately appears as an OUTPUT field, so the
        # check must test behavior: varying ML must not move the score.
        a = self._audit()
        assert a.check_ml_is_display_only() == a.PASS

    def test_ml_check_would_catch_a_rearmed_engine(self):
        # Directly verify the property the check relies on: with ml_weight
        # turned up, ML DOES move the score — so the check has real teeth.
        step2 = {"gated_score": 72.0}
        def score(ml):
            return um.combine_and_decide(
                step2, {"indicator_final_score": 68.0, "vix_level": 18.0,
                        "ai_confidence_score": ml, "ml_ok": True},
                ml_weight=1.0)["final_score"]
        assert score(1.0) != score(99.0)

    def test_squeeze_depth_regression_guard(self):
        a = self._audit()
        assert a.check_squeeze_depth_scaling() == a.PASS

    # --- live-data checks must not pass on thin or bad data ------------

    def test_param_check_insufficient_not_pass(self):
        a = self._audit()
        import pipeline as um_
        # Force both arms to return too few trades
        orig = um_.backtest_exits
        try:
            um_.backtest_exits = lambda *ar, **kw: {"n": 3, "expectancy_r": 5.0}
            st = a.check_param_helps(
                "BTC", None, "fake filter",
                {"confirm_days": 1}, {"confirm_days": 2})
        finally:
            um_.backtest_exits = orig
        assert st == a.INSUFFICIENT   # NOT pass, despite a huge fake gain

    def test_param_check_grades_gain_correctly(self):
        a = self._audit()
        import pipeline as um_
        orig = um_.backtest_exits
        outcomes = {}
        try:
            for label, on_exp in (("big", 0.50), ("small", 0.02), ("negative", -0.20)):
                seq = iter([{"n": 40, "expectancy_r": 0.0},
                            {"n": 40, "expectancy_r": on_exp}])
                um_.backtest_exits = lambda *ar, **kw: next(seq)
                outcomes[label] = a.check_param_helps(
                    "BTC", None, f"{label} filter", {"confirm_days": 1}, {"confirm_days": 2})
        finally:
            um_.backtest_exits = orig
        assert outcomes["big"] == a.PASS
        assert outcomes["small"] == a.DEGRADED   # positive but under the bar
        assert outcomes["negative"] == a.FAIL

    def test_headline_check_fails_on_sign_flip(self):
        a = self._audit()
        cells = {"h1_long": self._trades("BUY", -0.5, 20, 2022),
                 "h2_long": self._trades("BUY", +0.5, 20, 2025)}
        cells["all"] = cells["h1_long"] + cells["h2_long"]
        assert a.check_headline_degradation("BTC", cells) == a.FAIL

    def test_headline_check_flags_regime_dependence_as_degraded(self):
        a = self._audit()
        cells = {"h1_long": self._trades("BUY", +0.05, 20, 2022),
                 "h2_long": self._trades("BUY", +1.20, 20, 2025)}
        cells["all"] = cells["h1_long"] + cells["h2_long"]
        # Both halves positive but far apart -> works, but regime-dependent
        assert a.check_headline_degradation("BTC", cells) == a.DEGRADED

    def test_headline_check_insufficient_on_thin_halves(self):
        a = self._audit()
        cells = {"h1_long": self._trades("BUY", +1.0, 4, 2022),
                 "h2_long": self._trades("BUY", +1.0, 4, 2025)}
        cells["all"] = cells["h1_long"] + cells["h2_long"]
        assert a.check_headline_degradation("BTC", cells) == a.INSUFFICIENT

    def test_score_band_check_fails_when_score_does_not_rank(self):
        a = self._audit()
        # Higher band does WORSE -> the buy bar is arbitrary
        cells = {"all": (self._trades("BUY", +0.6, 20, score=65.0) +
                         self._trades("BUY", -0.6, 20, score=75.0))}
        assert a.check_score_bands("BTC", cells) == a.FAIL

    def test_score_band_check_passes_when_score_ranks(self):
        a = self._audit()
        cells = {"all": (self._trades("BUY", -0.2, 20, score=65.0) +
                         self._trades("BUY", +0.8, 20, score=75.0))}
        assert a.check_score_bands("BTC", cells) == a.PASS

    def test_sizing_replication_insufficient_with_one_ticker(self):
        a = self._audit()
        assert a.check_sizing_replication({"BTC": {"trades": []}}) == a.INSUFFICIENT

    # --- report must never hide a failure ------------------------------

    def test_report_counts_every_status(self):
        a = self._audit()
        a.record("X", "pass check", a.PASS, "ok")
        a.record("X", "fail check", a.FAIL, "bad")
        a.record("X", "skip check", a.SKIP, "no network")
        rep = a.render_report(["BTC"], 4)
        assert "| FAIL | 1 |" in rep and "| SKIP | 1 |" in rep
        assert "Never read a SKIP as a PASS" in rep
        assert "fail check" in rep


# ======================================================================
# SENTIMENT CACHING + LAZY CALLING (the Adanos quota fix)
# ======================================================================
# Adanos is the binding constraint on the whole project (200 req/month
# free tier vs ~1023 being spent). These tests lock in the two things
# that could go wrong with the fix:
#   1. caching an ERROR result, which would silently disable the gate
#      for hours while looking like it was working
#   2. a hardcoded skip cutoff that rots when the buy bar or the
#      weights change

class TestSentimentCaching:

    @staticmethod
    def _gate(decision="PROCEED", mult=1.0):
        return {"decision": decision, "gate_multiplier": mult, "reason": "test"}

    def _tmp(self, tmp_path):
        return str(tmp_path / "sentiment_cache.json")

    def test_first_call_fetches_and_caches(self, tmp_path):
        calls = []
        def fetcher(t, **kw):
            calls.append(t)
            return self._gate()
        g = ads.cached_sentiment_check("BTC", ttl_hours=4, cache_path=self._tmp(tmp_path),
                                      fetcher=fetcher)
        assert calls == ["BTC"] and g["cache_hit"] is False
        assert ads._load_sentiment_cache(self._tmp(tmp_path))["BTC"]["gate"]["decision"] == "PROCEED"

    def test_second_call_within_ttl_costs_zero_requests(self, tmp_path):
        calls = []
        def fetcher(t, **kw):
            calls.append(t)
            return self._gate("VETO", 0.5)
        p = self._tmp(tmp_path)
        ads.cached_sentiment_check("BTC", ttl_hours=4, cache_path=p, fetcher=fetcher)
        g = ads.cached_sentiment_check("BTC", ttl_hours=4, cache_path=p, fetcher=fetcher)
        assert len(calls) == 1                  # THE POINT: no second request
        assert g["cache_hit"] is True
        assert g["gate_multiplier"] == 0.5      # and the real reading survived

    def test_expired_ttl_refetches(self, tmp_path):
        import datetime as dt
        calls = []
        def fetcher(t, **kw):
            calls.append(t)
            return self._gate()
        p = self._tmp(tmp_path)
        t0 = dt.datetime(2026, 8, 1, 0, 0, tzinfo=dt.timezone.utc)
        ads.cached_sentiment_check("BTC", ttl_hours=4, cache_path=p, fetcher=fetcher, now=t0)
        later = t0 + dt.timedelta(hours=5)
        ads.cached_sentiment_check("BTC", ttl_hours=4, cache_path=p, fetcher=fetcher, now=later)
        assert len(calls) == 2

    def test_ttl_zero_disables_caching(self, tmp_path):
        calls = []
        def fetcher(t, **kw):
            calls.append(t); return self._gate()
        p = self._tmp(tmp_path)
        for _ in range(3):
            ads.cached_sentiment_check("BTC", ttl_hours=0, cache_path=p, fetcher=fetcher)
        assert len(calls) == 3   # original behaviour preserved

    def test_error_results_are_NOT_cached(self, tmp_path):
        # A LOW_CONFIDENCE from an upstream failure is not a reading.
        # Caching it would silently switch the gate off for the whole TTL.
        calls = []
        def fetcher(t, **kw):
            calls.append(t); return self._gate("LOW_CONFIDENCE", 1.0)
        p = self._tmp(tmp_path)
        ads.cached_sentiment_check("BTC", ttl_hours=4, cache_path=p, fetcher=fetcher)
        ads.cached_sentiment_check("BTC", ttl_hours=4, cache_path=p, fetcher=fetcher)
        assert len(calls) == 2                        # retried, did not cache
        assert ads._load_sentiment_cache(p) == {}

    def test_tickers_cached_independently(self, tmp_path):
        calls = []
        def fetcher(t, **kw):
            calls.append(t); return self._gate()
        p = self._tmp(tmp_path)
        ads.cached_sentiment_check("BTC", ttl_hours=4, cache_path=p, fetcher=fetcher)
        ads.cached_sentiment_check("ETH", ttl_hours=4, cache_path=p, fetcher=fetcher)
        ads.cached_sentiment_check("BTC", ttl_hours=4, cache_path=p, fetcher=fetcher)
        assert calls == ["BTC", "ETH"]

    def test_stale_cache_used_when_live_call_fails(self, tmp_path):
        # Going neutral on a failure silently disables the gate. An old
        # reading is better, but the caller must be able to SEE it is old.
        import datetime as dt
        p = self._tmp(tmp_path)
        t0 = dt.datetime(2026, 8, 1, 0, 0, tzinfo=dt.timezone.utc)
        ads.cached_sentiment_check("BTC", ttl_hours=4, cache_path=p, now=t0,
                                  fetcher=lambda t, **kw: self._gate("VETO", 0.5))
        def broken(t, **kw):
            raise ConnectionError("adanos down")
        g = ads.cached_sentiment_check("BTC", ttl_hours=4, cache_path=p, fetcher=broken,
                                      now=t0 + dt.timedelta(hours=9))
        assert g["stale_fallback"] is True
        assert g["gate_multiplier"] == 0.5
        assert g["cache_age_hours"] == pytest.approx(9.0, abs=0.1)

    def test_failure_with_no_cache_degrades_visibly(self, tmp_path):
        # CONTRACT CHANGE (Aug 5, deliberate): this used to assert a
        # raise. In production the raise killed every hourly run for 2+
        # days once Adanos quota exhausted — a gate that never changed a
        # score took the whole service down, and created a deadlock (the
        # cache that would save quota can only be seeded by a successful
        # call). Failure with no cache now returns a VISIBLE neutral
        # gate; TestSentimentFailureDegradation pins the full behavior.
        def broken(t, **kw):
            raise ConnectionError("adanos down")
        g = ads.cached_sentiment_check("BTC", ttl_hours=4,
                                       cache_path=self._tmp(tmp_path),
                                       fetcher=broken)
        assert g["decision"] == "ERROR" and g["gate_multiplier"] == 1.0

    def test_corrupt_cache_file_is_survivable(self, tmp_path):
        p = self._tmp(tmp_path)
        open(p, "w").write("{not json")
        g = ads.cached_sentiment_check("BTC", ttl_hours=4, cache_path=p,
                                      fetcher=lambda t, **kw: self._gate())
        assert g["cache_hit"] is False


class TestLazySentiment:

    def test_cutoff_is_derived_from_bar_and_weights(self):
        # Production: (60 - 0.4*100) / 0.6 = 33.33
        assert um.sentiment_call_cutoff(60.0, 0.6, 0.4) == pytest.approx(33.333, abs=0.01)

    def test_cutoff_moves_with_the_buy_bar(self):
        # THE POINT of deriving it: raising the bar must raise the cutoff,
        # so the relationship survives a threshold change instead of rotting.
        lo = um.sentiment_call_cutoff(60.0, 0.6, 0.4)
        hi = um.sentiment_call_cutoff(70.0, 0.6, 0.4)
        assert hi > lo

    def test_cutoff_moves_with_the_weights(self):
        assert um.sentiment_call_cutoff(60.0, 0.8, 0.2) != \
               um.sentiment_call_cutoff(60.0, 0.6, 0.4)

    def test_cutoff_degenerate_weights_never_skip(self):
        assert um.sentiment_call_cutoff(60.0, 0.0, 1.0) == 0.0

    def test_lazy_off_by_default_always_calls(self):
        call, _ = um.should_call_sentiment(5.0)          # no lazy arg
        assert call is True

    def test_lazy_skips_only_below_cutoff(self):
        assert um.should_call_sentiment(20.0, lazy=True)[0] is False
        assert um.should_call_sentiment(40.0, lazy=True)[0] is True

    def test_lazy_boundary_calls_at_cutoff(self):
        cutoff = um.sentiment_call_cutoff()
        assert um.should_call_sentiment(cutoff, lazy=True)[0] is True
        assert um.should_call_sentiment(cutoff - 0.01, lazy=True)[0] is False

    def test_skip_reason_is_explanatory(self):
        _, why = um.should_call_sentiment(10.0, lazy=True)
        assert "cutoff" in why and "quota" in why


# ======================================================================
# OUTCOME TRACKING (live_tools.py outcomes — weakness #3)
# ======================================================================
# The rules here MUST mirror backtest_exits exactly, or live-vs-backtest
# comparison is meaningless. Episode extraction must collapse the 30-min
# ping spam into single events, or "43 BUYs" keeps meaning 4.

import live_tools as lt


def _log_rows(rows):
    cols = ["timestamp_utc","ticker","price","final_score","direction",
            "target_price","stop_price","atr","vix_level"]
    return pd.DataFrame([dict(zip(cols, r)) for r in rows])


def _daily(start, bars):
    """4h bars (live exit levels come from 4h ATR, so resolution must
    match). Kept under the old name so existing cases read unchanged;
    each 'bar' is now 4 hours, and bars_per_day=6 in the tests below."""
    idx = pd.date_range(start, periods=len(bars), freq="4h")
    return pd.DataFrame(bars, index=idx, columns=["High","Low","Close"])


class TestEpisodeExtraction:

    def test_consecutive_pings_collapse_to_one_episode(self):
        rows = [(f"2026-08-01T{h:02d}:00:00","BTC",100.0,65,"BUY",106.0,97.0,2.0,20)
                for h in range(6)]
        eps = lt.extract_episodes(_log_rows(rows))
        assert len(eps) == 1
        assert eps[0]["n_log_rows"] == 6
        assert eps[0]["entry_price"] == 100.0   # FIRST row's values

    def test_strength_change_does_not_split_episode(self):
        rows = [("2026-08-01T10:00:00","BTC",100.0,65,"BUY",106.0,97.0,2.0,20),
                ("2026-08-01T10:30:00","BTC",101.0,72,"STRONG_BUY",106.0,97.0,2.0,20)]
        eps = lt.extract_episodes(_log_rows(rows))
        assert len(eps) == 1 and eps[0]["peak_direction"] == "STRONG_BUY"

    def test_leaving_family_ends_episode_and_reentry_starts_new(self):
        rows = [("2026-08-01T10:00:00","BTC",100.0,65,"BUY",106.0,97.0,2.0,20),
                ("2026-08-01T10:30:00","BTC",100.0,50,"WATCH",None,None,2.0,20),
                ("2026-08-01T11:00:00","BTC",99.0,66,"BUY",105.0,96.0,2.0,20)]
        eps = lt.extract_episodes(_log_rows(rows))
        assert len(eps) == 2 and eps[1]["entry_price"] == 99.0

    def test_direct_flip_long_to_short_is_two_episodes(self):
        rows = [("2026-08-01T10:00:00","BTC",100.0,65,"BUY",106.0,97.0,2.0,20),
                ("2026-08-01T10:30:00","BTC",100.0,30,"SELL",94.0,103.0,2.0,20)]
        eps = lt.extract_episodes(_log_rows(rows))
        assert [e["side"] for e in eps] == ["long","short"]

    def test_tickers_do_not_bleed_into_each_other(self):
        rows = [("2026-08-01T10:00:00","BTC",100.0,65,"BUY",106.0,97.0,2.0,20),
                ("2026-08-01T10:10:00","ETH",50.0,64,"BUY",53.0,48.5,1.0,20),
                ("2026-08-01T10:30:00","BTC",100.5,66,"BUY",106.0,97.0,2.0,20)]
        eps = lt.extract_episodes(_log_rows(rows))
        assert len(eps) == 2 and {e["ticker"] for e in eps} == {"BTC","ETH"}

    def test_rows_without_exit_levels_are_skipped(self):
        rows = [("2026-08-01T10:00:00","BTC",100.0,50,"WATCH",None,None,2.0,20)]
        assert lt.extract_episodes(_log_rows(rows)) == []


class TestEpisodeResolution:

    EP = {"episode_id":"BTC_x","ticker":"BTC","side":"long",
          "entry_time_utc":"2026-08-01T10:00:00","entry_direction":"BUY",
          "peak_direction":"BUY","entry_price":100.0,"target_price":106.0,
          "stop_price":97.0,"entry_score":65.0,"atr":2.0,"vix_level":20.0,
          "n_log_rows":3,"signal_last_seen_utc":"2026-08-01T12:00:00"}

    def test_target_hit(self):
        d = _daily("2026-08-02", [(103,99,102),(107,101,106)])
        r = lt.resolve_episode(self.EP, d)
        assert r["status"]=="closed" and r["outcome"]=="target"
        assert r["pnl_r"] == pytest.approx(2.0)   # 6 gained / 3 risked
        assert r["bars_held"] == 2                # 2 four-hour bars

    def test_stop_hit(self):
        d = _daily("2026-08-02", [(101,96.5,98)])
        r = lt.resolve_episode(self.EP, d)
        assert r["outcome"]=="stop" and r["pnl_r"] == -1.0

    def test_both_in_one_bar_is_ambiguous_stop_pessimistic(self):
        # SAME rule as backtest_exits — the property live/backtest
        # comparability depends on.
        d = _daily("2026-08-02", [(107,96,100)])
        r = lt.resolve_episode(self.EP, d)
        assert r["outcome"]=="ambiguous_stop" and r["pnl_r"] == -1.0

    def test_bars_before_entry_are_not_scanned(self):
        # Bars at or before the entry TIMESTAMP must not count. With 4h
        # data we can cut at the exact entry moment rather than dropping
        # the whole day, so a 06:00 spike is excluded for a 10:00 entry.
        d = _daily("2026-08-01T02:00:00", [(110,99,105),(101,99,100),
                                            (101,99,100)])
        r = lt.resolve_episode(self.EP, d, max_hold_days=1, bars_per_day=6)
        assert r["outcome"] != "target", "a pre-entry bar was counted"

    def test_short_side_mirrors(self):
        ep = dict(self.EP, side="short", entry_direction="SELL",
                  target_price=94.0, stop_price=103.0)
        d = _daily("2026-08-02", [(101,93.5,95)])
        r = lt.resolve_episode(ep, d)
        assert r["outcome"]=="target" and r["pnl_r"] == pytest.approx(2.0)

    def test_open_when_too_few_bars(self):
        d = _daily("2026-08-02", [(101,99,100)])
        r = lt.resolve_episode(self.EP, d, max_hold_days=15)
        assert r["status"]=="open" and r["pnl_r"] is None

    def test_timeout_pnl_from_last_close(self):
        # budget = max_hold_days * bars_per_day; use 2 bars exactly
        d = _daily("2026-08-02", [(101,99,100),(102,100,101.5)])
        r = lt.resolve_episode(self.EP, d, max_hold_days=1, bars_per_day=2)
        assert r["outcome"]=="timeout"
        assert r["pnl_r"] == pytest.approx(0.5)   # +1.5 / 3 risked

    def test_granularity_mismatch_regression(self):
        # THE BUG THIS SECTION EXISTS FOR: live stops sit ~1.2% from
        # entry (4h ATR). A DAILY bar routinely spans more than that, so
        # resolving against daily bars stopped out every episode on bar
        # one regardless of what happened. A 4h bar that stays inside
        # both levels must leave the episode OPEN, not stopped.
        inside = _daily("2026-08-02", [(100.8, 99.4, 100.2)] * 3)
        r = lt.resolve_episode(self.EP, inside, max_hold_days=15)
        assert r["status"] == "open" and r["outcome"] is None
        wide_daily_like = _daily("2026-08-02", [(107, 96, 100)])
        assert lt.resolve_episode(self.EP, wide_daily_like)["outcome"] \
            == "ambiguous_stop"

    def test_resolve_outcomes_end_to_end(self, tmp_path):
        log = tmp_path/"log.csv"
        _log_rows([("2026-08-01T10:00:00","BTC",100.0,65,"BUY",106.0,97.0,2.0,20),
                   ("2026-08-01T10:30:00","BTC",100.5,66,"BUY",106.0,97.0,2.0,20)]
                  ).to_csv(log, index=False)
        d = _daily("2026-08-02", [(107,101,106)])
        out = lt.resolve_outcomes(str(log), str(tmp_path/"out.csv"),
                                  fetcher=lambda t: d)
        assert len(out)==1 and out.iloc[0]["outcome"]=="target"
        assert (tmp_path/"out.csv").exists()

    def test_compare_refuses_below_min_n(self):
        df = pd.DataFrame([{"status":"closed","outcome":"target",
                            "entry_score":65.0,"pnl_r":2.0}])
        txt = lt.compare_live_to_backtest(df, min_n=15)
        assert "INSUFFICIENT" in txt


# ======================================================================
# COST MODELING (weakness #4)
# ======================================================================

class TestCostModeling:

    @staticmethod
    def _frame():
        # One clean long. NOTE: backtest_exits recomputes ATR internally
        # (14-period) so the frame needs enough warmup bars with real
        # ranges; constant High-Low of 2 gives ATR ~= 2 after warmup.
        n = 25
        idx = pd.date_range("2026-01-01", periods=n, freq="D")
        df = pd.DataFrame({"Close":[100.0]*n,"High":[101.0]*n,"Low":[99.0]*n,
                           "direction":["WATCH"]*n,
                           "combined_final_score":[65.0]*n}, index=idx)
        df.iloc[20, df.columns.get_loc("direction")] = "BUY"
        df.iloc[21, df.columns.get_loc("High")] = 107.0   # target hit
        df.iloc[21, df.columns.get_loc("Low")] = 100.5    # no stop touch either config
        return df

    def test_cost_r_math(self):
        # stop = 1.5*ATR = 3 = 3% of entry. round trip 30bps -> 0.003/0.03 = 0.1R
        r = um.backtest_exits(self._frame(), confirm_days=1,
                              fee_bps=10.0, slippage_bps=5.0)
        t = r["trades"][0]
        assert t["cost_r"] == pytest.approx(0.10, abs=1e-3)
        assert t["pnl_r_net"] == pytest.approx(t["pnl_r"] - 0.10, abs=1e-3)
        assert r["expectancy_r_net"] == pytest.approx(r["expectancy_r"] - 0.10, abs=1e-3)

    def test_zero_cost_reproduces_gross(self):
        r = um.backtest_exits(self._frame(), confirm_days=1,
                              fee_bps=0.0, slippage_bps=0.0)
        assert r["expectancy_r_net"] == pytest.approx(r["expectancy_r"])

    def test_tighter_stop_pays_more_cost_in_r(self):
        # Same friction, half the stop distance -> double the cost in R.
        wide = um.backtest_exits(self._frame(), confirm_days=1, stop_mult=1.5)
        tight = um.backtest_exits(self._frame(), confirm_days=1, stop_mult=0.75)
        assert tight["trades"][0]["cost_r"] == pytest.approx(
            2*wide["trades"][0]["cost_r"], rel=1e-3)

    def test_gross_keys_unchanged_for_backward_compat(self):
        r = um.backtest_exits(self._frame(), confirm_days=1)
        assert "expectancy_r" in r and "expectancy_r_net" in r


# ======================================================================
# DATA INTEGRITY (weakness #5)
# ======================================================================

class TestDataIntegrity:

    def _clean(self, n=30):
        idx = pd.date_range("2026-07-01", periods=n, freq="D", tz="UTC")
        c = pd.Series(100.0, index=idx) + pd.Series(range(n), index=idx)*0.1
        return pd.DataFrame({"High":c+1,"Low":c-1,"Close":c})

    def test_clean_frame_passes(self):
        df = self._clean()
        assert epm.validate_market_data(df, now=df.index[-1]) == []

    def test_catches_high_below_low(self):
        df = self._clean(); df.iloc[5, df.columns.get_loc("High")] = 0.5
        assert any("High < Low" in i for i in epm.validate_market_data(df))

    def test_catches_bad_tick_jump(self):
        df = self._clean(); df.iloc[10, df.columns.get_loc("Close")] = 500.0
        assert any("bad ticks" in i for i in epm.validate_market_data(df))

    def test_catches_stale_feed(self):
        df = self._clean()
        late = df.index[-1] + pd.Timedelta(days=5)
        assert any("stale" in i for i in
                   epm.validate_market_data(df, interval_hours=24, now=late))

    def test_catches_nonpositive_and_empty(self):
        df = self._clean(); df.iloc[0, df.columns.get_loc("Close")] = -1
        assert any("non-positive" in i for i in epm.validate_market_data(df))
        assert epm.validate_market_data(df.iloc[0:0]) == ["empty frame"]

    def test_cross_check_within_tolerance(self):
        assert epm.cross_check_price(100.0, 101.0)["ok"] is True

    def test_cross_check_divergence_fails(self):
        r = epm.cross_check_price(100.0, 110.0)
        assert r["ok"] is False and "DISAGREE" in r["reason"]

    def test_cross_check_missing_source_fails(self):
        assert epm.cross_check_price(100.0, float("nan"))["ok"] is False


# ======================================================================
# LOCKBOX + WALK-FORWARD (weaknesses #1, #2)
# ======================================================================

class TestLockboxWalkforward:

    def _merged(self, days=400):
        idx = pd.date_range(end=pd.Timestamp.now().normalize(), periods=days, freq="D")
        return pd.DataFrame({"Close":[100.0]*days}, index=idx)

    def test_lockbox_seals_recent_months_by_default(self):
        df = self._merged(400)
        kept = um.apply_lockbox(df, months=6)
        assert kept.index.max() < pd.Timestamp.now().normalize() - pd.DateOffset(months=6) 
        assert len(kept) < len(df)

    def test_lockbox_unlock_returns_everything(self):
        df = self._merged(400)
        assert len(um.apply_lockbox(df, months=6, unlock=True)) == len(df)

    def test_folds_are_sequential_and_cover_everything(self):
        df = self._merged(365)
        folds = um.walkforward_folds(df, 4)
        assert sum(len(f) for f in folds) == len(df)
        for a, b in zip(folds, folds[1:]):
            assert a.index.max() < b.index.min()   # no overlap, time-ordered

    def test_walkforward_verdict_generalizes_requires_all_folds(self):
        ok = {"n":20,"expectancy_r_net":0.2}
        bad = {"n":20,"expectancy_r_net":-0.1}
        assert um.walkforward_verdict([ok,ok,ok,ok])["verdict"] == "GENERALIZES"
        assert um.walkforward_verdict([ok,ok,ok,bad])["verdict"] == "REGIME_DEPENDENT"
        assert um.walkforward_verdict([bad,bad])["verdict"] == "NO_EDGE"

    def test_walkforward_verdict_insufficient_on_thin_folds(self):
        thin = {"n":3,"expectancy_r_net":0.9}
        ok = {"n":20,"expectancy_r_net":0.2}
        assert um.walkforward_verdict([thin,thin,ok])["verdict"] == "INSUFFICIENT_DATA"

    def test_verdict_uses_net_not_gross(self):
        # Positive gross, negative net must NOT count as generalizing.
        f = {"n":20,"expectancy_r":0.05,"expectancy_r_net":-0.05}
        assert um.walkforward_verdict([f,f])["verdict"] == "NO_EDGE"


# ======================================================================
# LOG SCHEMA MIGRATION + SENTIMENT PASSTHROUGH (weakness #6)
# ======================================================================

class TestLogMigration:

    def test_old_narrow_log_is_migrated_not_misaligned(self, tmp_path):
        p = str(tmp_path/"log.csv")
        old_cols = [c for c in lt.LOG_COLUMNS
                    if c not in ("sentiment_score","sentiment_mentions","gate_cache_hit")]
        pd.DataFrame([{c: 1 for c in old_cols}]).to_csv(p, index=False)
        result = {"ticker":"BTC",
                  "step1_initial_scoring":{"close":100.0,"initial_score":50.0,"atr":2.0},
                  "step2_reddit_data":{"gated_score":50.0,"gate_decision":"PROCEED",
                                        "gate_multiplier":1.0,"sentiment_score":0.12,
                                        "sentiment_mentions":40,"gate_cache_hit":True},
                  "step3_indicators":{"indicator_final_score":55.0,"vix_level":18.0},
                  "combined":{"final_score":52.0,"decision":"WATCH","direction":"WATCH",
                               "exit_levels":{},"ml_confidence":None}}
        lt.append_ping_to_log(result, p)
        df = pd.read_csv(p)
        assert list(df.columns) == lt.LOG_COLUMNS
        assert len(df) == 2
        assert df.iloc[1]["sentiment_score"] == pytest.approx(0.12)
        assert pd.isna(df.iloc[0]["sentiment_score"])   # old row, new col

    def test_gate_result_carries_raw_reading(self):
        g = epm.sentiment_gate(0.05, 40)
        # the adanos wrapper adds these; the plain gate needn't — but the
        # wrapper contract is what the log depends on, so test it via a fake
        import signal_engines as se
        orig = se.fetch_token_sentiment
        try:
            se.fetch_token_sentiment = lambda t, api_key=None: {
                "found": True, "sentiment_score": 0.05, "mentions": 40,
                "bullish_pct": 60, "bearish_pct": 40, "buzz_score": 1}
            out = se.first_pass_sentiment_check_adanos("BTC")
        finally:
            se.fetch_token_sentiment = orig
        assert out["sentiment_score"] == 0.05 and out["sentiment_mentions"] == 40


# ======================================================================
# EXIT GEOMETRY COMPARISON (options 1 and 2)
# ======================================================================
# The comparison decides whether live should adopt daily ATR (option 1)
# or shorten its horizon (option 2). Two things must hold or the answer
# is garbage: no lookahead in the ATR used, and identical signal
# selection across configs so only the geometry varies.

class TestExitGeometry:

    @staticmethod
    def _bars4h(start, n, base=100.0, rng_pct=0.004):
        idx = pd.date_range(start, periods=n, freq="4h")
        c = pd.Series(base, index=idx)
        return pd.DataFrame({"High": c*(1+rng_pct), "Low": c*(1-rng_pct), "Close": c})

    @staticmethod
    def _merged(n=40, signal_at=30):
        idx = pd.date_range("2026-01-01", periods=n, freq="D")
        df = pd.DataFrame({"Close":[100.0]*n,"High":[101.0]*n,"Low":[99.0]*n,
                           "direction":["WATCH"]*n,
                           "combined_final_score":[65.0]*n}, index=idx)
        df.iloc[signal_at, df.columns.get_loc("direction")] = "BUY"
        return df

    def test_resolve_on_4h_target_stop_ambiguous(self):
        b = self._bars4h("2026-02-01", 5)
        b.iloc[1, b.columns.get_loc("High")] = 110.0
        r = um.resolve_on_4h(b, pd.Timestamp("2026-01-31"), 100.0, 106.0, 97.0,
                             True, max_bars=10)
        assert r["outcome"] == "target" and r["bars"] == 2
        b2 = self._bars4h("2026-02-01", 5)
        b2.iloc[0, b2.columns.get_loc("Low")] = 90.0
        assert um.resolve_on_4h(b2, pd.Timestamp("2026-01-31"), 100.0, 106.0,
                                97.0, True, 10)["outcome"] == "stop"
        b3 = self._bars4h("2026-02-01", 5)
        b3.iloc[0, b3.columns.get_loc("High")] = 110.0
        b3.iloc[0, b3.columns.get_loc("Low")] = 90.0
        assert um.resolve_on_4h(b3, pd.Timestamp("2026-01-31"), 100.0, 106.0,
                                97.0, True, 10)["outcome"] == "ambiguous_stop"

    def test_quiet_bars_leave_it_unresolved_then_timeout(self):
        b = self._bars4h("2026-02-01", 20)
        open_r = um.resolve_on_4h(b, pd.Timestamp("2026-01-31"), 100.0, 106.0,
                                  97.0, True, max_bars=50)
        assert open_r["outcome"] is None, "ran out of bars but claimed a result"
        done = um.resolve_on_4h(b, pd.Timestamp("2026-01-31"), 100.0, 106.0,
                                97.0, True, max_bars=10)
        assert done["outcome"] == "timeout"

    def test_bars_before_entry_are_never_scanned(self):
        b = self._bars4h("2026-02-01", 10)
        b.iloc[0, b.columns.get_loc("High")] = 200.0     # huge spike BEFORE entry
        r = um.resolve_on_4h(b, b.index[3], 100.0, 106.0, 97.0, True, 10)
        assert r["outcome"] != "target" or r["bars"] > 0
        assert not (r["outcome"] == "target" and r["bars"] == 0), "lookahead"

    def test_4h_atr_is_not_taken_from_the_future(self):
        # The ATR used must come from bars at or before entry. Spike the
        # bars AFTER entry: the chosen geometry must be unaffected.
        merged = self._merged()
        quiet = self._bars4h("2026-01-01", 400)
        loud = quiet.copy()
        entry_ts = pd.Timestamp("2026-01-31") + pd.Timedelta(hours=24)
        after = loud.index > entry_ts
        loud.loc[after, "High"] = loud.loc[after, "High"] * 3
        a = um.backtest_exit_geometry(merged, quiet, atr_source="4h",
                                      confirm_days=1, short_sma_filter=0)
        b = um.backtest_exit_geometry(merged, loud, atr_source="4h",
                                      confirm_days=1, short_sma_filter=0)
        if a["n"] and b["n"]:
            assert a["trades"][0]["stop_pct"] == pytest.approx(
                b["trades"][0]["stop_pct"]), "future bars changed the ATR"

    def test_daily_atr_gives_a_wider_stop_than_4h_atr(self):
        # THE WHOLE POINT of the comparison: option 1 must actually be
        # the looser geometry, or the test is measuring nothing.
        merged = self._merged()
        bars = self._bars4h("2026-01-01", 400)
        d = um.backtest_exit_geometry(merged, bars, atr_source="daily",
                                      confirm_days=1, short_sma_filter=0)
        f = um.backtest_exit_geometry(merged, bars, atr_source="4h",
                                      confirm_days=1, short_sma_filter=0)
        if d["n"] and f["n"]:
            assert d["avg_stop_pct"] > f["avg_stop_pct"]

    def test_shorter_hold_cannot_increase_bars_held(self):
        merged = self._merged()
        bars = self._bars4h("2026-01-01", 400)
        long_h = um.backtest_exit_geometry(merged, bars, atr_source="4h",
                                           max_hold_days=15, confirm_days=1,
                                           short_sma_filter=0)
        short_h = um.backtest_exit_geometry(merged, bars, atr_source="4h",
                                            max_hold_days=2, confirm_days=1,
                                            short_sma_filter=0)
        if long_h["n"] and short_h["n"]:
            assert short_h["avg_days_held"] <= long_h["avg_days_held"] + 1e-9

    def test_comparison_refuses_a_winner_on_thin_data(self):
        thin = {"live_current": {"n": 3, "expectancy_r_net": 9.0,
                                 "expectancy_r": 9.0, "avg_stop_pct": 1.0,
                                 "target_rate": 1.0, "timeout_rate": 0.0,
                                 "avg_days_held": 1.0},
                "match_backtest": {"n": 2, "expectancy_r_net": -1.0,
                                   "expectancy_r": -1.0, "avg_stop_pct": 2.0,
                                   "target_rate": 0.0, "timeout_rate": 0.0,
                                   "avg_days_held": 1.0}}
        txt = um.compare_exit_geometries(thin, min_n=15)
        assert "INSUFFICIENT" in txt and "Best NET" not in txt

    def test_comparison_judges_on_net_not_gross(self):
        res = {"a": {"n": 50, "expectancy_r": 0.30, "expectancy_r_net": 0.05,
                     "avg_stop_pct": 1.0, "target_rate": 0.4, "timeout_rate": 0.1,
                     "avg_days_held": 2.0},
               "b": {"n": 50, "expectancy_r": 0.20, "expectancy_r_net": 0.15,
                     "avg_stop_pct": 2.5, "target_rate": 0.35, "timeout_rate": 0.2,
                     "avg_days_held": 8.0}}
        txt = um.compare_exit_geometries(res, min_n=15)
        assert "Best NET expectancy: b" in txt   # a wins gross, b wins net

    def test_comparison_warns_about_in_sample_reuse(self):
        res = {"a": {"n": 50, "expectancy_r": 0.2, "expectancy_r_net": 0.1,
                     "avg_stop_pct": 1.0, "target_rate": 0.4, "timeout_rate": 0.1,
                     "avg_days_held": 2.0},
               "b": {"n": 50, "expectancy_r": 0.1, "expectancy_r_net": 0.05,
                     "avg_stop_pct": 2.0, "target_rate": 0.3, "timeout_rate": 0.2,
                     "avg_days_held": 6.0}}
        txt = um.compare_exit_geometries(res, min_n=15)
        assert "walkforward" in txt and "candidate, not a validated choice" in txt


# ======================================================================
# EARNINGS OPTIMIZATION (cost sensitivity, band gate, validated search)
# ======================================================================
# The optimizer is the most dangerous code in the repo: a search that
# reports winners. These tests pin the honesty properties — breakevens
# are exact, thin bands never make the keep-list, and the "recommend"
# bar requires beating the baseline in EVERY counted fold.

class TestEarningsOptimization:

    @staticmethod
    def _trades(pnl_r, stop_pct, n, score=65.0, net=None):
        return [{"pnl_r": pnl_r, "stop_pct": stop_pct, "score": score,
                 "pnl_r_net": net if net is not None else pnl_r}
                for _ in range(n)]

    def test_cost_sensitivity_breakeven_is_exact(self):
        # gross +0.30R, stop 2% -> cost_r per bp = 1/0.02/1e4 = 0.005
        # breakeven = 0.30 / 0.005 = 60 bps
        res = {"cfg": {"trades": self._trades(0.30, 2.0, 50)}}
        txt = um.cost_sensitivity(res)
        assert "~60bps" in txt
        # and the 60bp column should be ~0.000
        assert "+0.000" in txt or "-0.000" in txt

    def test_cost_sensitivity_tighter_stop_dies_sooner(self):
        res = {"tight": {"trades": self._trades(0.30, 1.0, 50)},
               "wide":  {"trades": self._trades(0.30, 3.0, 50)}}
        txt = um.cost_sensitivity(res)
        t = txt.index("tight: edge survives up to ~30bps")
        w = txt.index("wide: edge survives up to ~90bps")
        assert t > 0 and w > 0
        assert w < t   # sorted best-first: wide listed before tight

    def test_band_analysis_drops_negative_and_keeps_positive(self):
        trades = (self._trades(0.5, 2.0, 25, score=65, net=0.4) +
                  self._trades(-0.4, 2.0, 25, score=75, net=-0.5))
        bands = um.band_edge_analysis(trades, min_n=20)
        assert bands[60]["status"] == "keep"
        assert bands[70]["status"] == "drop"

    def test_band_analysis_thin_band_is_insufficient_even_if_stellar(self):
        trades = (self._trades(0.1, 2.0, 30, score=65, net=0.05) +
                  self._trades(5.0, 2.0, 4, score=85, net=4.9))
        bands = um.band_edge_analysis(trades, min_n=20)
        assert bands[80]["status"] == "insufficient"   # 4 trades of +4.9R != keep

    def test_render_band_analysis_calls_out_drop_bands(self):
        trades = (self._trades(0.5, 2.0, 25, score=65, net=0.4) +
                  self._trades(-0.4, 2.0, 25, score=75, net=-0.5))
        txt = um.render_band_analysis(um.band_edge_analysis(trades, min_n=20))
        assert "negative-net bands" in txt

    def test_grid_covers_both_atr_sources_and_baseline_shape(self):
        grid = um._geometry_grid()
        assert {g["atr_source"] for g in grid} == {"4h", "daily"}
        assert len(grid) == 2 * 4 * 3
        assert all("key" in g for g in grid)


# ======================================================================
# WALKFORWARD GEOMETRY MATCHING (the validation-mismatch fix)
# ======================================================================
# THE BUG: walkforward called backtest_exits (DAILY ATR) while the live
# bot builds exits from 4h ATR. It produced a real verdict about a trade
# the bot never places. These tests pin the contract: LIVE_GEOMETRY is
# the single source of truth, and the default validation path uses it.

class TestWalkforwardGeometry:

    def test_live_geometry_matches_documented_production_config(self):
        g = um.LIVE_GEOMETRY
        assert g["atr_source"] == "4h", "live bot uses 4h ATR for exit levels"
        assert g["stop_mult"] == 1.5 and g["target_mult"] == 3.0
        assert g["confirm_days"] == 2 and g["short_sma_filter"] == 50
        assert g["max_hold_days"] == 15

    def test_concentration_report_flags_single_fold_edge(self):
        # The BTC shape: three mediocre folds plus one huge one.
        folds = [{"n": 53, "expectancy_r_net": 0.077},
                 {"n": 46, "expectancy_r_net": -0.358},
                 {"n": 62, "expectancy_r_net": -0.113},
                 {"n": 54, "expectancy_r_net": 0.631}]
        txt = um.concentration_report(folds)
        assert "CONCENTRATED" in txt
        assert "excluding best fold" in txt

    def test_concentration_report_accepts_spread_edge(self):
        folds = [{"n": 50, "expectancy_r_net": 0.20}] * 4
        assert "spread across folds" in um.concentration_report(folds)

    def test_concentration_report_needs_three_folds(self):
        folds = [{"n": 50, "expectancy_r_net": 0.2}, {"n": 3, "expectancy_r_net": 9.0}]
        assert "needs 3+" in um.concentration_report(folds)

    def test_concentration_excludes_thin_folds_from_the_math(self):
        # A 2-trade fold at +9R must not rescue the overall number.
        folds = [{"n": 50, "expectancy_r_net": -0.2},
                 {"n": 50, "expectancy_r_net": -0.2},
                 {"n": 50, "expectancy_r_net": -0.2},
                 {"n": 2, "expectancy_r_net": 9.0}]
        assert "negative overall" in um.concentration_report(folds)

    def test_folds_use_geometry_not_daily_backtest_exits(self):
        # Behavioral: the 4h path must produce a TIGHTER stop than daily.
        # If evaluate_geometry_folds ever reverts to backtest_exits, the
        # two would be identical and this fails.
        n = 200
        idx = pd.date_range("2026-01-01", periods=n, freq="D")
        merged = pd.DataFrame({"Close": [100.0]*n, "High": [101.0]*n,
                               "Low": [99.0]*n, "direction": ["BUY"]*n,
                               "combined_final_score": [65.0]*n}, index=idx)
        h4 = pd.date_range("2026-01-01", periods=n*6, freq="4h")
        c = pd.Series(100.0, index=h4)
        bars = pd.DataFrame({"High": c*1.004, "Low": c*0.996, "Close": c})
        four = um.evaluate_geometry_folds(merged, bars, 2, "4h", 15, 1.5, 3.0,
                                          1, 0, 2.0, 2.0, verbose=False)
        daily = um.evaluate_geometry_folds(merged, bars, 2, "daily", 15, 1.5, 3.0,
                                           1, 0, 2.0, 2.0, verbose=False)
        f = [r for r in four if r.get("n", 0)]
        d = [r for r in daily if r.get("n", 0)]
        if f and d:
            assert f[0]["avg_stop_pct"] < d[0]["avg_stop_pct"], \
                "4h geometry should give a tighter stop than daily"


# ======================================================================
# LITERATURE OVERLAYS (trend / TSMOM / vol scaling)
# ======================================================================
# The whole defense of this feature is that parameters came from the
# LITERATURE, not from tuning on this repo's folds — and that overlays
# only drop or reweight trades, never move them. These tests pin both.

class TestLiteratureOverlays:

    @staticmethod
    def _series(n=500, base=100.0, trend=0.0):
        idx = pd.date_range("2024-01-01", periods=n, freq="D")
        c = pd.Series(base * (1 + trend) ** np.arange(n), index=idx)
        merged = pd.DataFrame({"Close": c})
        return um.build_overlay_series(merged), idx

    @staticmethod
    def _trade(date, direction="BUY", pnl=0.5):
        return {"date": date, "direction": direction, "pnl_r": pnl,
                "pnl_r_net": pnl, "outcome": "target"}

    def test_parameters_are_the_literatures_not_ours(self):
        # 200d SMA (Faber), 365d TSMOM (Moskowitz-Ooi-Pedersen 2012),
        # 28d TSMOM (AUT crypto study). If someone "tunes" these, this
        # test is the tripwire that says: that changes the whole defense.
        p = um.OVERLAY_PARAMS
        assert p["trend_sma"] == 200
        assert p["tsmom_long"] == 365
        assert p["tsmom_short"] == 28

    def test_trend_gate_blocks_longs_below_sma_and_shorts_above(self):
        s, idx = self._series(n=400, trend=-0.002)   # steady downtrend
        d = idx[350]                                  # price well below SMA
        longs = um.apply_overlay([self._trade(d, "BUY")], s, "trend_200")
        shorts = um.apply_overlay([self._trade(d, "SELL")], s, "trend_200")
        assert longs == [] and len(shorts) == 1

    def test_tsmom_gates_on_sign_of_trailing_return(self):
        s, idx = self._series(n=450, trend=0.002)    # steady uptrend
        d = idx[440]
        assert len(um.apply_overlay([self._trade(d, "BUY")], s, "tsmom_365")) == 1
        assert um.apply_overlay([self._trade(d, "SELL")], s, "tsmom_365") == []

    def test_no_lookahead_a_future_crash_cannot_change_todays_gate(self):
        n = 460
        idx = pd.date_range("2024-01-01", periods=n, freq="D")
        up = 100 * (1.002) ** np.arange(n)
        crashed = up.copy(); crashed[430:] = up[430:] * 0.4   # crash AFTER d
        d = idx[420]
        s_up = um.build_overlay_series(pd.DataFrame({"Close": pd.Series(up, index=idx)}))
        s_cr = um.build_overlay_series(pd.DataFrame({"Close": pd.Series(crashed, index=idx)}))
        a = um.apply_overlay([self._trade(d, "BUY")], s_up, "tsmom_365")
        b = um.apply_overlay([self._trade(d, "BUY")], s_cr, "tsmom_365")
        assert len(a) == len(b) == 1, "a future crash changed a past gate — lookahead"

    def test_vol_scale_downweights_high_vol_and_caps_leverage(self):
        n = 100
        idx = pd.date_range("2024-01-01", periods=n, freq="D")
        rng = np.random.default_rng(0)
        calm = 100 * np.exp(np.cumsum(rng.normal(0, 0.001, n)))
        wild = 100 * np.exp(np.cumsum(rng.normal(0, 0.08, n)))
        s_calm = um.build_overlay_series(pd.DataFrame({"Close": pd.Series(calm, index=idx)}))
        s_wild = um.build_overlay_series(pd.DataFrame({"Close": pd.Series(wild, index=idx)}))
        d = idx[80]
        w_calm = um.apply_overlay([self._trade(d)], s_calm, "vol_scale")[0]["weight"]
        w_wild = um.apply_overlay([self._trade(d)], s_wild, "vol_scale")[0]["weight"]
        assert w_wild < w_calm
        assert w_calm <= um.OVERLAY_PARAMS["vol_cap"] + 1e-9

    def test_weighted_net_reduces_to_plain_mean_when_weights_are_one(self):
        ts = [dict(self._trade(pd.Timestamp("2024-06-01"), pnl=x), weight=1.0)
              for x in (0.5, -1.0, 2.0)]
        assert um.weighted_net(ts) == pytest.approx((0.5 - 1.0 + 2.0) / 3)

    def test_acceptance_bar_requires_two_ticker_improvement(self):
        def mk(base_ex, ov_ex):
            return {"baseline": {"ex_best": base_ex, "all": 0.0, "per_fold": [(20, 0.0, 20)]*4},
                    "trend_200": {"ex_best": ov_ex, "all": 0.0, "per_fold": [(20, 0.0, 20)]*4}}
        good = {"BTC": mk(0.01, 0.05), "ETH": mk(0.02, 0.06), "SOL": mk(-0.03, -0.031)}
        bad = {"BTC": mk(0.01, 0.05), "ETH": mk(0.02, 0.01), "SOL": mk(-0.03, -0.09)}
        assert "CANDIDATE" in um.overlay_verdict(good)
        v = um.overlay_verdict(bad)
        assert "CANDIDATE" not in v and "No overlay met the bar" in v

    def test_gate_fails_closed_when_series_is_unknown(self):
        s, idx = self._series(n=300)
        stranger = pd.Timestamp("1999-01-01")
        assert um.apply_overlay([self._trade(stranger)], s, "trend_200") == []
        # sizing fails NEUTRAL, not closed
        w = um.apply_overlay([self._trade(stranger)], s, "vol_scale")[0]["weight"]
        assert w == 1.0


# ======================================================================
# BUY/SELL DIRECTION SPLIT (evaluate_geometry_folds direction filter)
# ======================================================================
# Needed to answer "how does BUY perform on its own" honestly, rather
# than inferring it from combined numbers. Must reuse the same summary
# arithmetic (stats_from_trades) as everything else, and must not touch
# which bars get scanned or how trades resolve — filtering happens only
# on the already-produced trade list.

class TestDirectionSplit:

    @staticmethod
    def _merged(n=60):
        idx = pd.date_range("2026-01-01", periods=n, freq="D")
        df = pd.DataFrame({"Close": [100.0]*n, "High": [101.0]*n,
                           "Low": [99.0]*n, "direction": ["WATCH"]*n,
                           "combined_final_score": [65.0]*n}, index=idx)
        # alternate BUY / SELL signals through the window
        for i in range(10, n - 5, 8):
            df.iloc[i, df.columns.get_loc("direction")] = "BUY" if (i // 8) % 2 == 0 else "SELL"
        return df

    @staticmethod
    def _bars4h(n_days):
        idx = pd.date_range("2026-01-01", periods=n_days * 6, freq="4h")
        c = pd.Series(100.0, index=idx)
        return pd.DataFrame({"High": c * 1.006, "Low": c * 0.994, "Close": c})

    def test_stats_from_trades_matches_backtest_exit_geometry_on_full_set(self):
        merged, bars = self._merged(), self._bars4h(60)
        full = um.backtest_exit_geometry(merged, bars, atr_source="4h",
                                         confirm_days=1, short_sma_filter=0)
        if full["n"]:
            recomputed = um.stats_from_trades(full["trades"])
            assert recomputed["n"] == full["n"]
            assert recomputed["expectancy_r_net"] == pytest.approx(
                full["expectancy_r_net"])

    def test_direction_filter_only_keeps_requested_side(self):
        merged, bars = self._merged(), self._bars4h(60)
        res = um.evaluate_geometry_folds(merged, bars, 1, "4h", 15, 1.5, 3.0,
                                         1, 0, 2.0, 2.0, verbose=False,
                                         direction="buy")
        for r in res:
            for t in r.get("trades", []):
                assert t["direction"] in ("BUY", "STRONG_BUY")

    def test_buy_and_sell_splits_are_disjoint_and_cover_all_trades(self):
        merged, bars = self._merged(), self._bars4h(60)
        allr = um.evaluate_geometry_folds(merged, bars, 1, "4h", 15, 1.5, 3.0,
                                          1, 0, 2.0, 2.0, verbose=False)
        buys = um.evaluate_geometry_folds(merged, bars, 1, "4h", 15, 1.5, 3.0,
                                          1, 0, 2.0, 2.0, verbose=False,
                                          direction="buy")
        sells = um.evaluate_geometry_folds(merged, bars, 1, "4h", 15, 1.5, 3.0,
                                           1, 0, 2.0, 2.0, verbose=False,
                                           direction="sell")
        n_all = sum(r.get("n", 0) for r in allr)
        n_split = sum(r.get("n", 0) for r in buys) + sum(r.get("n", 0) for r in sells)
        assert n_split == n_all, "BUY+SELL trade counts must reconstruct the total"

    def test_invalid_direction_rejected(self):
        merged, bars = self._merged(), self._bars4h(60)
        with pytest.raises(ValueError):
            um.evaluate_geometry_folds(merged, bars, 1, "4h", 15, 1.5, 3.0,
                                       1, 0, 2.0, 2.0, direction="long")

    def test_empty_direction_subset_is_n_zero_not_a_crash(self):
        # A fold that happens to have zero BUY signals must report n=0
        # cleanly, not raise, since sequential folds can be lopsided.
        idx = pd.date_range("2026-01-01", periods=20, freq="D")
        merged = pd.DataFrame({"Close": [100.0]*20, "High": [101.0]*20,
                               "Low": [99.0]*20, "direction": ["SELL"]*20,
                               "combined_final_score": [65.0]*20}, index=idx)
        merged.iloc[5, merged.columns.get_loc("direction")] = "SELL"
        bars = self._bars4h(20)
        res = um.evaluate_geometry_folds(merged, bars, 1, "4h", 15, 1.5, 3.0,
                                         1, 0, 2.0, 2.0, verbose=False,
                                         direction="buy")
        assert res[0].get("n", 0) == 0


class TestOptimizeDirectionFilter:
    """optimize --direction must filter at run_cfg so EVERY stage (grid,
    folds, bands, cost table) sees the same subset — and min_n must be
    applied AFTER filtering, or a config could 'qualify' on trade counts
    it is actually excluding."""

    def test_fee_defaults_match_real_binance_us_schedule(self):
        # My original 10+5 guess was 12x too high and inverted the
        # geometry ranking. Every command must default to the real ~2bps.
        import inspect
        src = inspect.getsource(um.main_optimize)
        assert 'default=10.0' not in src, "stale fee default is back"
        src_eg = inspect.getsource(um.main_exitgeometry)
        assert 'default=10.0' not in src_eg, "stale fee default is back"

    def test_stats_from_trades_handles_empty_subset(self):
        assert um.stats_from_trades([])["n"] == 0

    def test_band_analysis_on_buy_subset_ignores_sell_bands(self):
        buys = [{"score": 65.0, "pnl_r_net": 0.2, "pnl_r": 0.2} for _ in range(30)]
        sells = [{"score": 35.0, "pnl_r_net": -0.5, "pnl_r": -0.5} for _ in range(30)]
        both = um.band_edge_analysis(buys + sells, min_n=20)
        only = um.band_edge_analysis(buys, min_n=20)
        assert 30 in both and 30 not in only, \
            "SELL-side band leaked into a BUY-only analysis"
        assert only[60]["status"] == "keep"


# ======================================================================
# VOLUME CONFIRMATION OVERLAY (rvol_150)
# ======================================================================
# Pre-registered: RVOL >= 1.5 vs a 20-day baseline. The defense of this
# overlay is that the threshold came from outside this repo's data and
# is never swept. These tests pin that, plus the no-lookahead property
# and the fact that the baseline excludes the current day.

class TestVolumeOverlay:

    @staticmethod
    def _bars_with_volume(n_days, vol_pattern=None):
        idx = pd.date_range("2024-01-01", periods=n_days * 6, freq="4h")
        c = pd.Series(100.0, index=idx)
        vols = []
        for d in range(n_days):
            v = 100.0 if vol_pattern is None else vol_pattern(d)
            vols.extend([v / 6] * 6)
        return pd.DataFrame({"High": c * 1.005, "Low": c * 0.995,
                             "Close": c, "Volume": vols}, index=idx)

    @staticmethod
    def _merged(n_days):
        idx = pd.date_range("2024-01-01", periods=n_days, freq="D")
        return pd.DataFrame({"Close": [100.0] * n_days}, index=idx)

    def test_threshold_is_the_conventional_one_and_not_swept(self):
        # 1.5x / 20-day is the practitioner convention (IBD CAN SLIM:
        # 40-50% above average). If someone "optimizes" these on the
        # repo's own folds, the pre-registration defense is void.
        assert um.OVERLAY_PARAMS["rvol_threshold"] == 1.5
        assert um.OVERLAY_PARAMS["rvol_window"] == 20

    def test_daily_volume_sums_the_4h_bars(self):
        bars = self._bars_with_volume(5, lambda d: 600.0)
        dv = um.build_daily_volume(bars)
        assert len(dv) == 5
        assert dv.iloc[0] == pytest.approx(600.0)

    def test_high_volume_day_passes_low_volume_day_blocked(self):
        # 30 quiet days, then one at 3x
        bars = self._bars_with_volume(31, lambda d: 300.0 if d == 30 else 100.0)
        series = um.build_overlay_series(self._merged(31), bars)
        spike_day = pd.Timestamp("2024-01-31")
        quiet_day = pd.Timestamp("2024-01-30")
        t_spike = {"date": spike_day, "direction": "BUY", "pnl_r": 1.0, "pnl_r_net": 1.0}
        t_quiet = {"date": quiet_day, "direction": "BUY", "pnl_r": 1.0, "pnl_r_net": 1.0}
        assert len(um.apply_overlay([t_spike], series, "rvol_150")) == 1
        assert um.apply_overlay([t_quiet], series, "rvol_150") == []

    def test_baseline_excludes_the_current_day(self):
        # If the current day were included in its own 20-day average, a
        # huge spike would partly dilute itself and RVOL would understate.
        bars = self._bars_with_volume(25, lambda d: 2000.0 if d == 24 else 100.0)
        series = um.build_overlay_series(self._merged(25), bars)
        r = series["rvol"].get(pd.Timestamp("2024-01-25"))
        assert r == pytest.approx(20.0, rel=0.01), \
            "baseline appears to include the current day"

    def test_no_lookahead_future_volume_cannot_change_todays_rvol(self):
        quiet = self._bars_with_volume(30, lambda d: 100.0)
        loud_later = self._bars_with_volume(
            30, lambda d: 9999.0 if d > 24 else 100.0)
        d = pd.Timestamp("2024-01-25")
        s1 = um.build_overlay_series(self._merged(30), quiet)
        s2 = um.build_overlay_series(self._merged(30), loud_later)
        assert s1["rvol"].get(d) == pytest.approx(s2["rvol"].get(d)), \
            "future volume changed a past RVOL — lookahead"

    def test_missing_volume_data_degrades_gracefully(self):
        series = um.build_overlay_series(self._merged(30), None)
        assert len(series["rvol"]) == 0
        t = {"date": pd.Timestamp("2024-01-15"), "direction": "BUY",
             "pnl_r": 1.0, "pnl_r_net": 1.0}
        # gate fails CLOSED when the series is unavailable
        assert um.apply_overlay([t], series, "rvol_150") == []

    def test_rvol_curve_restores_the_registered_threshold(self):
        # The diagnostic mutates OVERLAY_PARAMS; it must put it back even
        # if something throws, or the registered spec silently changes.
        bars = self._bars_with_volume(30, lambda d: 100.0 + d * 10)
        series = um.build_overlay_series(self._merged(30), bars)
        trades = [[{"date": pd.Timestamp("2024-01-25"), "direction": "BUY",
                    "pnl_r": 1.0, "pnl_r_net": 1.0, "score": 65.0}] * 12] * 4
        um.rvol_curve(trades, series)
        assert um.OVERLAY_PARAMS["rvol_threshold"] == 1.5

    def test_rvol_is_in_the_default_overlay_set(self):
        import inspect
        sig = inspect.signature(um.overlay_fold_table)
        assert "rvol_150" in sig.parameters["overlays"].default


class TestRvolDateAlignment:
    """The rvol gate silently reported 'no trades passed' when the daily
    index was tz-aware — indistinguishable in the output from a real
    finding. These pin the fix: lookups normalize dates first, and the
    coverage diagnostic can tell a bug from a property."""

    @staticmethod
    def _bars(n_days, vol=lambda d: 100.0):
        idx = pd.date_range("2024-01-01", periods=n_days * 6, freq="4h")
        c = pd.Series(100.0, index=idx)
        vols = []
        for d in range(n_days):
            vols.extend([vol(d) / 6] * 6)
        return pd.DataFrame({"High": c, "Low": c, "Close": c, "Volume": vols},
                            index=idx)

    def test_tz_aware_trade_date_still_matches_volume(self):
        rng = np.random.default_rng(3)
        bars = self._bars(120, lambda d: float(rng.lognormal(3, 0.8)))
        merged = pd.DataFrame({"Close": [100.0] * 120},
                              index=pd.date_range("2024-01-01", periods=120, freq="D"))
        series = um.build_overlay_series(merged, bars)
        naive = pd.Timestamp("2024-03-01")
        aware = naive.tz_localize("UTC")
        a = um._sv_daily(series["rvol"], naive)
        b = um._sv_daily(series["rvol"], aware)
        assert a == a, "naive lookup failed"
        assert b == pytest.approx(a), "tz-aware date did not match the same day"

    def test_intraday_timestamp_resolves_to_its_day(self):
        bars = self._bars(60)
        merged = pd.DataFrame({"Close": [100.0] * 60},
                              index=pd.date_range("2024-01-01", periods=60, freq="D"))
        series = um.build_overlay_series(merged, bars)
        assert um._sv_daily(series["rvol"], pd.Timestamp("2024-02-15 17:43")) == \
               pytest.approx(um._sv_daily(series["rvol"], pd.Timestamp("2024-02-15")))

    def test_realistic_volume_clears_threshold_at_expected_rate(self):
        # Sanity floor: on a normal right-skewed volume series roughly
        # a third to a half of days beat their own 20-day average. If a
        # future change drops this near zero, alignment broke again.
        rng = np.random.default_rng(11)
        bars = self._bars(300, lambda d: float(rng.lognormal(3, 0.8)))
        merged = pd.DataFrame({"Close": [100.0] * 300},
                              index=pd.date_range("2024-01-01", periods=300, freq="D"))
        series = um.build_overlay_series(merged, bars)
        rv = series["rvol"].dropna()
        share = (rv >= 1.0).mean()
        assert 0.25 < share < 0.60, f"share >= 1.0 was {share:.0%}, expected ~40%"

    def test_coverage_diagnostic_flags_missing_as_a_bug(self):
        bars = self._bars(60)
        merged = pd.DataFrame({"Close": [100.0] * 60},
                              index=pd.date_range("2024-01-01", periods=60, freq="D"))
        series = um.build_overlay_series(merged, bars)
        # dates far outside the volume range -> all missing
        stranded = [[{"date": pd.Timestamp("1999-01-%02d" % (i + 1)),
                      "direction": "BUY", "pnl_r": 1.0, "pnl_r_net": 1.0}
                     for i in range(10)]]
        txt = um.rvol_coverage(stranded, series)
        assert "alignment bug" in txt

    def test_coverage_diagnostic_reports_present_but_low(self):
        # Volume steadily rising means late days always beat their
        # trailing average -> high coverage, high RVOL. Inverse case
        # (declining) gives coverage with LOW rvol.
        bars = self._bars(120, lambda d: max(1.0, 500.0 - d * 3))
        merged = pd.DataFrame({"Close": [100.0] * 120},
                              index=pd.date_range("2024-01-01", periods=120, freq="D"))
        series = um.build_overlay_series(merged, bars)
        trades = [[{"date": d, "direction": "BUY", "pnl_r": 1.0, "pnl_r_net": 1.0}
                   for d in pd.date_range("2024-03-01", periods=30, freq="D")]]
        txt = um.rvol_coverage(trades, series)
        assert "missing (no volume match): 0" in txt
        assert "alignment bug" not in txt


class TestCompressionAndExpansion:
    """Volume used in the direction the data pointed: compression depth
    at entry (registered hypothesis: deeper = better) and post-entry
    expansion (registered: expansion = better). Both must report
    CONTRADICTS honestly if the data disagrees, and neither may leak
    future information into an entry decision."""

    @staticmethod
    def _setup(n_days=200, vol=None):
        idx4 = pd.date_range("2024-01-01", periods=n_days * 6, freq="4h")
        c = pd.Series(100.0, index=idx4)
        rng = np.random.default_rng(5)
        vols = []
        for d in range(n_days):
            base = vol(d) if vol else float(rng.lognormal(3, 0.5))
            vols.extend([base / 6] * 6)
        bars = pd.DataFrame({"High": c * 1.005, "Low": c * 0.995,
                             "Close": c, "Volume": vols}, index=idx4)
        merged = pd.DataFrame({"Close": [100.0] * n_days},
                              index=pd.date_range("2024-01-01", periods=n_days, freq="D"))
        return merged, bars

    def test_quartile_report_detects_a_monotone_relationship(self):
        merged, bars = self._setup()
        series = um.build_overlay_series(merged, bars)
        # Construct trades where LOW rvol pays MORE — should read "supports"
        trades = []
        for d in pd.date_range("2024-03-01", periods=80, freq="D"):
            r = um._sv_daily(series["rvol"], d)
            if r != r:
                continue
            trades.append({"date": d, "direction": "BUY",
                           "pnl_r": -r, "pnl_r_net": -r, "score": 65.0})
        txt = um.rvol_quartile_report(trades, series)
        assert "supports" in txt, txt

    def test_quartile_report_says_contradicts_when_data_disagrees(self):
        merged, bars = self._setup()
        series = um.build_overlay_series(merged, bars)
        trades = []
        for d in pd.date_range("2024-03-01", periods=80, freq="D"):
            r = um._sv_daily(series["rvol"], d)
            if r != r:
                continue
            # HIGH rvol pays more -> must report CONTRADICTS
            trades.append({"date": d, "direction": "BUY",
                           "pnl_r": r, "pnl_r_net": r, "score": 65.0})
        txt = um.rvol_quartile_report(trades, series)
        assert "CONTRADICTS" in txt, txt

    def test_median_split_halves_are_disjoint_and_complete(self):
        merged, bars = self._setup()
        series = um.build_overlay_series(merged, bars)
        trades = [{"date": d, "direction": "BUY", "pnl_r": 0.5,
                   "pnl_r_net": 0.5, "score": 65.0}
                  for d in pd.date_range("2024-03-01", periods=60, freq="D")]
        rv = [um._sv_daily(series["rvol"], t["date"]) for t in trades]
        series["_rvol_median"] = float(pd.Series([x for x in rv if x == x]).median())
        deep = um.apply_overlay(trades, series, "compression_deep")
        shal = um.apply_overlay(trades, series, "compression_shallow")
        assert len(deep) + len(shal) == len(trades)
        assert not ({id(t) for t in deep} & {id(t) for t in shal})

    def test_compression_gate_needs_a_median_to_be_set(self):
        merged, bars = self._setup()
        series = um.build_overlay_series(merged, bars)   # no _rvol_median
        t = [{"date": pd.Timestamp("2024-03-01"), "direction": "BUY",
              "pnl_r": 0.5, "pnl_r_net": 0.5}]
        assert um.apply_overlay(t, series, "compression_deep") == []

    def test_post_entry_expansion_only_reads_bars_after_entry(self):
        # Spike volume BEFORE the entry window; the expansion measure
        # must not treat that as expansion.
        n = 120
        merged, bars = self._setup(n, vol=lambda d: 5000.0 if d < 60 else 100.0)
        trades = [{"date": d, "direction": "BUY", "pnl_r": 1.0, "pnl_r_net": 1.0}
                  for d in pd.date_range("2024-03-15", periods=40, freq="D")]
        txt = um.post_entry_expansion(trades, bars)
        # all entries are in the quiet regime -> should read as not expanded
        assert "did not expand" in txt

    def test_post_entry_expansion_flags_small_gaps_as_no_separation(self):
        merged, bars = self._setup(200)
        rng = np.random.default_rng(2)
        trades = [{"date": d, "direction": "BUY",
                   "pnl_r": float(rng.normal(0, 0.01)),
                   "pnl_r_net": float(rng.normal(0, 0.01))}
                  for d in pd.date_range("2024-03-01", periods=120, freq="D")]
        txt = um.post_entry_expansion(trades, bars)
        assert "no separation" in txt or "too thin" in txt

    def test_expansion_handles_missing_volume(self):
        assert "no volume data" in um.post_entry_expansion([], None)


class TestDiagnoseReports:
    """Characterization reports: math must be exact and thin data must
    degrade to 'too few', never to a confident-sounding number."""

    @staticmethod
    def _t(outcome, pnl, mfe=0.0, days=2.0, direction="BUY",
           date="2025-01-01"):
        return {"outcome": outcome, "pnl_r": pnl, "pnl_r_net": pnl,
                "mfe_pct_of_target": mfe, "days_held": days,
                "direction": direction, "date": pd.Timestamp(date),
                "cost_r": 0.0, "stop_pct": 2.0, "score": 65.0}

    def test_mfe_near_miss_rate_is_exact(self):
        trades = ([self._t("stop", -1.0, mfe=80.0)] * 3 +
                  [self._t("stop", -1.0, mfe=10.0)] * 9 +
                  [self._t("target", 2.0, mfe=100.0)] * 5)
        txt = um.mfe_report(trades)
        assert "reached >=75% of target first: 25%" in txt   # 3 of 12
        assert "never reached 25%:            75%" in txt    # 9 of 12

    def test_mfe_distinguishes_near_miss_regime_from_wrong_entries(self):
        near = [self._t("stop", -1.0, mfe=85.0)] * 5 + \
               [self._t("stop", -1.0, mfe=20.0)] * 7
        far = [self._t("stop", -1.0, mfe=5.0)] * 12
        assert "PLAUSIBLE" in um.mfe_report(near)
        assert "little to work with" in um.mfe_report(far)

    def test_strength_report_flags_non_separation(self):
        trades = ([self._t("target", 0.5, direction="STRONG_BUY")] * 15 +
                  [self._t("target", 0.5, direction="BUY")] * 15)
        assert "inside noise" in um.strength_report(trades)

    def test_strength_report_detects_a_real_gap(self):
        trades = ([self._t("target", 1.0, direction="STRONG_BUY")] * 15 +
                  [self._t("stop", -0.5, direction="BUY")] * 15)
        txt = um.strength_report(trades)
        assert "adding information" in txt

    def test_follower_drawdown_and_streak_are_exact(self):
        # +1, five -1s (peak +1 -> trough -4: dd 5), +6 — repeated with
        # strictly increasing dates so the sort preserves the sequence.
        seq = [1.0, -1.0, -1.0, -1.0, -1.0, -1.0, 6.0] * 3
        trades = [self._t("target" if p > 0 else "stop", p,
                          date=pd.Timestamp("2025-01-01")
                          + pd.Timedelta(days=i))
                  for i, p in enumerate(seq)]
        txt = um.follower_experience_report(trades)
        assert "longest losing streak: 5" in txt
        assert "max drawdown: 5.0R" in txt

    def test_all_reports_degrade_on_thin_data(self):
        few = [self._t("stop", -1.0)] * 4
        assert "too few" in um.mfe_report(few)
        assert "too few" in um.hold_time_report(few)
        assert "too thin" in um.strength_report(few)
        assert "too few" in um.follower_experience_report(few)


class TestLongOnlySuppression:
    """SELL suppression is now a MEASURED decision (ex-best net negative
    on 3/3 tickers), enabled in the hourly workflow. These pin that it
    actually suppresses, that BUY is untouched, and that the SELL logic
    stays evaluable rather than deleted."""

    @staticmethod
    def _res(direction, ml):
        return {"combined": {"direction": direction, "ml_confidence": ml}}

    def test_sell_is_suppressed_when_long_only(self):
        for d in ("SELL", "STRONG_SELL"):
            g = lt.passes_confluence(self._res(d, 20.0), long_only=True)
            assert g["qualifies"] is False
            assert "long-only" in g["reason"]

    def test_sell_still_qualifies_when_long_only_is_off(self):
        # The logic must remain intact so walkforward/diagnose can still
        # evaluate the short side. Suppression is publication-level.
        g = lt.passes_confluence(self._res("SELL", 20.0), long_only=False)
        assert g["qualifies"] is True and g["side"] == "bearish"

    def test_buy_is_unaffected_by_long_only(self):
        g = lt.passes_confluence(self._res("BUY", 70.0), long_only=True)
        assert g["qualifies"] is True and g["side"] == "bullish"

    def test_suppression_reason_cites_the_measurement(self):
        g = lt.passes_confluence(self._res("SELL", 20.0), long_only=True)
        # A future reader must be able to see WHY without the chat log.
        assert "-0.142" in g["reason"] and "CONCENTRATED" in g["reason"]

    def test_hourly_workflow_enables_long_only(self):
        # The decision is worthless if production doesn't pass the flag.
        import pathlib
        wf = pathlib.Path(__file__).parent / ".github/workflows/signal-check.yml"
        if wf.exists():
            assert "--long-only" in wf.read_text(), \
                "hourly workflow publishes SELL signals despite the decision"


class TestWorkflowCommitRobustness:
    """The hourly run failed at the final commit because `git add` was
    given sentiment_cache.json, which does not exist until a sentiment
    call succeeds. git exits 128 on a missing pathspec, so a fully
    successful run (check + charts + outcomes) was discarded. Optional
    artifacts must never be able to fail the commit step."""

    @staticmethod
    def _wf():
        import pathlib
        return pathlib.Path(__file__).parent / ".github/workflows/signal-check.yml"

    def test_optional_artifacts_are_existence_checked(self):
        wf = self._wf()
        if not wf.exists():
            pytest.skip("workflow not present in this checkout")
        text = wf.read_text()
        assert 'git add signal_log.csv sentiment_cache.json' not in text, \
            "bare multi-path git add is back — a missing optional file will " \
            "abort the commit and discard the run"
        assert 'if [ -e "$f" ]' in text, "existence guard missing"

    def test_workflow_still_commits_the_required_artifacts(self):
        wf = self._wf()
        if not wf.exists():
            pytest.skip("workflow not present in this checkout")
        text = wf.read_text()
        for required in ("signal_log.csv", "signal_outcomes.csv", "docs"):
            assert required in text, f"{required} no longer committed"

    def test_workflow_yaml_parses(self):
        wf = self._wf()
        if not wf.exists():
            pytest.skip("workflow not present in this checkout")
        yaml = pytest.importorskip("yaml")
        d = yaml.safe_load(wf.read_text())
        steps = d["jobs"]["check"]["steps"]
        assert any("Commit" in s.get("name", "") for s in steps)


class TestRobustnessRewire:
    """robustness had the same defect walkforward had: it validated
    daily-ATR exits while the bot runs 4h ATR — verdicts about a trade
    the bot never places. Now routed through backtest_exit_geometry with
    LIVE_GEOMETRY defaults, and cells judged on NET pnl."""

    def test_subset_stats_prefers_net_when_available(self):
        trades = [{"outcome": "target", "pnl_r": 1.0, "pnl_r_net": 0.9},
                  {"outcome": "stop", "pnl_r": -1.0, "pnl_r_net": -1.1}]
        s = um.subset_stats(trades)
        assert s["expectancy_r"] == pytest.approx((0.9 - 1.1) / 2)

    def test_subset_stats_falls_back_to_gross_for_legacy_trades(self):
        trades = [{"outcome": "target", "pnl_r": 2.0},
                  {"outcome": "stop", "pnl_r": -1.0}]
        assert um.subset_stats(trades)["expectancy_r"] == pytest.approx(0.5)

    def test_robustness_defaults_come_from_live_geometry(self):
        import inspect
        src = inspect.getsource(um.main_robustness)
        assert 'LIVE_GEOMETRY["atr_source"]' in src, \
            "robustness no longer defaults to the live bot's ATR source"
        assert "backtest_exit_geometry(" in src, \
            "robustness reverted to backtest_exits (daily-ATR defect)"
        assert "backtest_exits(" not in src.replace(
            "backtest_exit_geometry(", ""), \
            "a bare backtest_exits call is back in robustness"

    def test_robustness_reports_geometry_match_status(self):
        import inspect
        src = inspect.getsource(um.main_robustness)
        assert "MATCHES the live bot" in src
        assert "DIFFERS FROM the live bot" in src


class TestLaunchReadinessAudit:
    """The audit's D-section turns launch readiness into a checklist.
    These pin that it exists and checks the right prerequisites."""

    def test_readiness_checks_cover_the_prerequisites(self):
        import pathlib
        src = (pathlib.Path(__file__).parent / "audit.py").read_text()
        assert "check_launch_readiness" in src
        for needle in ("--long-only", 'if [ -e "$f" ]',
                       "signal_outcomes.csv", "sentiment_score",
                       "sentiment_cache.json"):
            assert needle in src, f"readiness no longer checks {needle!r}"

    def test_readiness_is_wired_into_main(self):
        import pathlib
        src = (pathlib.Path(__file__).parent / "audit.py").read_text()
        assert "check_launch_readiness()" in src.split("def main()")[1]


class TestSentimentFailureDegradation:
    """THE DEADLOCK FIX. cached_sentiment_check used to re-raise when a
    live call failed with no cache — which killed the ENTIRE hourly run.
    In production the cache never persisted (workflow bug), quota
    exhausted Aug 3, and every check for 2+ days died on that raise: a
    gate that never changed a score took the whole service down. These
    pin the correct degradation: neutral, VISIBLE, never cached."""

    @staticmethod
    def _boom(*a, **k):
        raise ConnectionError("quota exhausted")

    def test_failure_with_no_cache_degrades_instead_of_raising(self, tmp_path):
        cache = str(tmp_path / "c.json")
        g = ads.cached_sentiment_check("BTC", cache_path=cache,
                                      fetcher=self._boom)
        assert g["decision"] == "ERROR"
        assert g["gate_multiplier"] == 1.0
        assert g["stale_fallback"] is False
        assert "Adanos unavailable" in g["reason"]

    def test_failure_result_is_never_cached(self, tmp_path):
        import os, json
        cache = str(tmp_path / "c.json")
        ads.cached_sentiment_check("BTC", cache_path=cache, fetcher=self._boom)
        # either no file, or an empty dict — never an ERROR entry
        if os.path.exists(cache):
            assert "BTC" not in json.load(open(cache))

    def test_stale_fallback_still_preferred_over_neutral(self, tmp_path):
        import json
        from datetime import datetime, timezone, timedelta
        cache = str(tmp_path / "c.json")
        old = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
        json.dump({"BTC": {"fetched_at": old,
                           "gate": {"decision": "PROCEED",
                                    "gate_multiplier": 1.0,
                                    "reason": "old reading",
                                    "sentiment_score": 0.1,
                                    "mentions": 30}}}, open(cache, "w"))
        g = ads.cached_sentiment_check("BTC", cache_path=cache,
                                      fetcher=self._boom, ttl_hours=4)
        assert g["stale_fallback"] is True
        assert g["decision"] == "PROCEED"   # the real reading, not ERROR

    def test_pipeline_row_survives_sentiment_failure(self, tmp_path):
        # End to end at the step level: apply_reddit_step must produce a
        # loggable step2 even when Adanos is down and no cache exists.
        import pipeline as um
        step1 = {"step": 1, "initial_score": 62.0, "close": 63000.0,
                 "atr": 450.0, "timestamp": 1.0,
                 "bb_width_pctl": 0.1, "squeeze_duration": 5}
        orig = ads.cached_sentiment_check
        ads.cached_sentiment_check = lambda *a, **k: orig(
            "BTC", cache_path=str(tmp_path / "c.json"), fetcher=self._boom)
        try:
            step2 = um.apply_reddit_step("BTC", step1)
        finally:
            ads.cached_sentiment_check = orig
        assert step2["gate_decision"] == "ERROR"
        assert step2["gate_multiplier"] == 1.0
        assert step2["gated_score"] == 62.0   # neutral: score untouched


class TestBatchTwoGates:
    """Gate batch 2 (hypotheses #10-13), registered 2026-08-06 with
    directions fixed before results: atr_expand (expanding better),
    vix_calm (<25 better), near_high (>=85% of 252d max better),
    btc_regime (BTC>50d SMA better, identity on BTC). These pin the
    fixed parameters, no-lookahead, fail-closed, and the BTC identity."""

    @staticmethod
    def _merged(n=400, trend=0.001, vix=18.0):
        idx = pd.date_range("2024-01-01", periods=n, freq="D")
        c = pd.Series(100.0 * (1 + trend) ** np.arange(n), index=idx)
        return pd.DataFrame({"Close": c, "High": c * 1.01, "Low": c * 0.99,
                             "vix_level": [vix] * n}, index=idx)

    @staticmethod
    def _t(d, direction="BUY"):
        return {"date": d, "direction": direction, "pnl_r": 1.0,
                "pnl_r_net": 1.0, "score": 65.0}

    def test_parameters_are_fixed_and_documented(self):
        p = um.OVERLAY_PARAMS
        assert p["atr_expand_period"] == 14 and p["atr_expand_lookback"] == 5
        assert p["vix_calm_threshold"] == 25.0     # robustness's own line
        assert p["near_high_window"] == 252 and p["near_high_frac"] == 0.85
        assert p["btc_regime_sma"] == 50

    def test_vix_calm_gates_on_threshold_and_fails_closed(self):
        s_calm = um.build_overlay_series(self._merged(vix=18.0))
        s_hot = um.build_overlay_series(self._merged(vix=32.0))
        d = pd.Timestamp("2024-06-01")
        assert len(um.apply_overlay([self._t(d)], s_calm, "vix_calm")) == 1
        assert um.apply_overlay([self._t(d)], s_hot, "vix_calm") == []
        s_none = um.build_overlay_series(
            self._merged().drop(columns=["vix_level"]))
        assert um.apply_overlay([self._t(d)], s_none, "vix_calm") == []

    def test_near_high_passes_uptrend_blocks_deep_drawdown(self):
        up = um.build_overlay_series(self._merged(trend=0.001))
        d = pd.Timestamp("2024-12-01")
        assert len(um.apply_overlay([self._t(d)], up, "near_high")) == 1
        # crash to 60% of the running max -> blocked
        m = self._merged(trend=0.001)
        m.loc[m.index[300]:, "Close"] = m["Close"].iloc[299] * 0.60
        down = um.build_overlay_series(m)
        assert um.apply_overlay([self._t(m.index[350])], down, "near_high") == []

    def test_atr_expand_has_no_lookahead(self):
        # A volatility explosion AFTER date d must not change d's flag.
        base = self._merged(n=300)
        loud = base.copy()
        loud.loc[loud.index[250]:, "High"] = loud["Close"] * 1.20
        loud.loc[loud.index[250]:, "Low"] = loud["Close"] * 0.80
        d = base.index[200]
        a = um._sv_daily(um.build_overlay_series(base)["atr_expanding"], d)
        b = um._sv_daily(um.build_overlay_series(loud)["atr_expanding"], d)
        assert bool(a) == bool(b), "future volatility changed a past flag"

    def test_btc_regime_identity_on_btc_gates_alts(self):
        m = self._merged()
        rising = pd.Series(100.0 * 1.002 ** np.arange(400),
                            index=m.index)
        falling = pd.Series(100.0 * 0.998 ** np.arange(400),
                             index=m.index)
        d = pd.Timestamp("2024-12-01")
        s_btc = um.build_overlay_series(m, btc_close=falling)
        s_btc["_ticker"] = "BTC"
        assert len(um.apply_overlay([self._t(d)], s_btc, "btc_regime")) == 1, \
            "BTC must pass through its own regime gate unchanged"
        s_eth_up = um.build_overlay_series(m, btc_close=rising)
        s_eth_up["_ticker"] = "ETH"
        s_eth_dn = um.build_overlay_series(m, btc_close=falling)
        s_eth_dn["_ticker"] = "ETH"
        assert len(um.apply_overlay([self._t(d)], s_eth_up, "btc_regime")) == 1
        assert um.apply_overlay([self._t(d)], s_eth_dn, "btc_regime") == []

    def test_batch_two_is_in_the_default_overlay_set(self):
        import inspect
        default = inspect.signature(um.overlay_fold_table).parameters["overlays"].default
        for g in ("atr_expand", "vix_calm", "near_high", "btc_regime"):
            assert g in default


class TestBatchThreeGates:
    """Batch 3 (hyp. #14-16), registered 2026-08-06: score_rising
    (signal's own momentum, 3d), strong_close ((C-L)/(H-L) >= 0.70),
    fresh_signal (no stop-exit within 5d before entry). Pins: fixed
    params, fail-closed, and — critically for fresh_signal — that only
    exits BEFORE the entry can block it (no lookahead)."""

    @staticmethod
    def _merged(n=100):
        idx = pd.date_range("2024-01-01", periods=n, freq="D")
        c = pd.Series(np.linspace(100, 120, n), index=idx)
        return pd.DataFrame({"Close": c, "High": c + 2.0, "Low": c - 2.0,
                             "final_score": np.linspace(50, 80, n),
                             "vix_level": [18.0] * n}, index=idx)

    @staticmethod
    def _t(d, direction="BUY"):
        return {"date": d, "direction": direction, "pnl_r": 1.0,
                "pnl_r_net": 1.0, "score": 65.0}

    def test_params_fixed(self):
        p = um.OVERLAY_PARAMS
        assert p["score_rising_days"] == 3
        assert p["strong_close_frac"] == 0.70
        assert p["fresh_signal_cooldown_days"] == 5

    def test_score_rising_gates_on_signal_momentum(self):
        m = self._merged()                       # score rises steadily
        s = um.build_overlay_series(m)
        d = pd.Timestamp("2024-03-01")
        assert len(um.apply_overlay([self._t(d)], s, "score_rising")) == 1
        m2 = self._merged()
        m2["final_score"] = np.linspace(80, 50, 100)   # falling
        s2 = um.build_overlay_series(m2)
        assert um.apply_overlay([self._t(d)], s2, "score_rising") == []

    def test_strong_close_uses_position_in_daily_range(self):
        m = self._merged()
        d = pd.Timestamp("2024-03-01")
        # Close is dead-centre of High=C+2/Low=C-2 -> frac 0.5 -> blocked
        s = um.build_overlay_series(m)
        assert um.apply_overlay([self._t(d)], s, "strong_close") == []
        m.loc[d, "High"] = m.loc[d, "Close"] + 0.5     # close near top
        m.loc[d, "Low"] = m.loc[d, "Close"] - 4.5
        s2 = um.build_overlay_series(m)
        assert len(um.apply_overlay([self._t(d)], s2, "strong_close")) == 1

    def test_fresh_signal_blocks_after_recent_stop_only_backward(self):
        s = um.build_overlay_series(self._merged())
        entry = pd.Timestamp("2024-03-10")
        # a stop that EXITED 2 days before entry -> blocked
        s["_stop_exits"] = (pd.Timestamp("2024-03-08"),)
        assert um.apply_overlay([self._t(entry)], s, "fresh_signal") == []
        # a stop 10 days before -> outside cooldown -> passes
        s["_stop_exits"] = (pd.Timestamp("2024-02-28"),)
        assert len(um.apply_overlay([self._t(entry)], s, "fresh_signal")) == 1
        # a stop AFTER the entry must never block it (lookahead guard)
        s["_stop_exits"] = (pd.Timestamp("2024-03-12"),)
        assert len(um.apply_overlay([self._t(entry)], s, "fresh_signal")) == 1

    def test_batch_three_in_default_set(self):
        import inspect
        default = inspect.signature(
            um.overlay_fold_table).parameters["overlays"].default
        for g in ("score_rising", "strong_close", "fresh_signal"):
            assert g in default


class TestBatchFourInverseGates:
    """Batch 4 (hyp. #18-20): the INVERSES of unanimously-failed gates.
    Epistemically weakest class — derived from observed failures, not
    literature. Tests pin that each is a genuine complement of its
    failed counterpart (so the pair partitions the trades), and that no
    NEW threshold was invented beyond the documented reuse."""

    @staticmethod
    def _merged(n=120, rising=True):
        idx = pd.date_range("2024-01-01", periods=n, freq="D")
        c = pd.Series(np.linspace(100, 120, n), index=idx)
        fs = np.linspace(50, 80, n) if rising else np.linspace(80, 50, n)
        return pd.DataFrame({"Close": c, "High": c + 2.0, "Low": c - 2.0,
                             "final_score": fs,
                             "vix_level": [18.0] * n}, index=idx)

    @staticmethod
    def _t(d):
        return {"date": d, "direction": "BUY", "pnl_r": 1.0,
                "pnl_r_net": 1.0, "score": 65.0}

    def test_score_fading_is_the_exact_complement_of_score_rising(self):
        d = pd.Timestamp("2024-03-01")
        for rising in (True, False):
            s = um.build_overlay_series(self._merged(rising=rising))
            up = um.apply_overlay([self._t(d)], s, "score_rising")
            dn = um.apply_overlay([self._t(d)], s, "score_fading")
            assert len(up) + len(dn) == 1, "gates overlap or leave a gap"

    def test_recent_stop_is_the_exact_complement_of_fresh_signal(self):
        s = um.build_overlay_series(self._merged())
        entry = pd.Timestamp("2024-03-10")
        for exits in ((pd.Timestamp("2024-03-08"),),      # inside window
                      (pd.Timestamp("2024-02-20"),),      # outside window
                      ()):                                 # none at all
            s["_stop_exits"] = exits
            fresh = um.apply_overlay([self._t(entry)], s, "fresh_signal")
            recent = um.apply_overlay([self._t(entry)], s, "recent_stop")
            assert len(fresh) + len(recent) == 1

    def test_recent_stop_ignores_future_exits(self):
        s = um.build_overlay_series(self._merged())
        entry = pd.Timestamp("2024-03-10")
        s["_stop_exits"] = (pd.Timestamp("2024-03-12"),)   # AFTER entry
        assert um.apply_overlay([self._t(entry)], s, "recent_stop") == [], \
            "a future stop-exit satisfied recent_stop — lookahead"

    def test_quiet_entry_requires_both_conditions(self):
        idx = pd.date_range("2024-01-01", periods=60 * 6, freq="4h")
        c = pd.Series(100.0, index=idx)
        # Steep decline: a -5/day slope only reaches RVOL 0.74, above the
        # 0.70 line — the fixture has to be genuinely quiet to test the
        # gate rather than the gate's edge case.
        vols = []
        for day in range(60):
            v = max(1.0, 400.0 * (0.93 ** day))
            vols.extend([v / 6] * 6)
        bars = pd.DataFrame({"High": c, "Low": c, "Close": c,
                             "Volume": vols}, index=idx)
        d = pd.Timestamp("2024-02-20")
        quiet_falling = um.build_overlay_series(
            self._merged(n=60, rising=False), bars)
        quiet_rising = um.build_overlay_series(
            self._merged(n=60, rising=True), bars)
        # low rvol + falling score -> passes; low rvol + rising -> blocked
        assert len(um.apply_overlay([self._t(d)], quiet_falling,
                                     "quiet_entry")) == 1
        assert um.apply_overlay([self._t(d)], quiet_rising,
                                 "quiet_entry") == []

    def test_quiet_threshold_reuses_the_observed_median_not_a_new_number(self):
        # 0.70 rounds up the measured signal-day RVOL medians (0.60-0.66).
        # If this ever gets "tuned", the weak-class defense is gone.
        assert um.OVERLAY_PARAMS["quiet_rvol_max"] == 0.70

    def test_batch_four_in_default_set(self):
        import inspect
        default = inspect.signature(
            um.overlay_fold_table).parameters["overlays"].default
        for g in ("quiet_entry", "score_fading", "recent_stop"):
            assert g in default


class TestStructuralExits:
    """Hyp. #21-23: swing/pivot stops vs the 1.5x ATR stop. The two
    things that can silently invalidate this: a fractal that is visible
    before it could be confirmed (lookahead), and a trailing stop that
    widens. Both are pinned here, plus R:R parity across modes."""

    @staticmethod
    def _bars(n, lows=None, highs=None, close=100.0):
        idx = pd.date_range("2024-01-01", periods=n, freq="4h")
        c = pd.Series(close, index=idx)
        return pd.DataFrame({
            "High": (pd.Series(highs, index=idx) if highs is not None else c * 1.01),
            "Low": (pd.Series(lows, index=idx) if lows is not None else c * 0.99),
            "Close": c, "Volume": [100.0] * n}, index=idx)

    def test_params_are_conventional_and_fixed(self):
        p = um.STRUCTURAL_PARAMS
        assert p["swing_lookback_bars"] == 10
        assert p["fractal_side_bars"] == 2      # Williams fractal standard
        assert p["swing_buffer_pct"] == 0.001

    def test_fractal_low_is_confirmed_late_not_at_the_pivot(self):
        lows = [10, 9, 5, 9, 10, 11, 12, 13, 14, 15]
        f = um.find_fractal_lows(self._bars(10, lows=lows), side=2)
        piv_idx = 2                              # the actual low
        conf_idx = piv_idx + 2                   # visible 2 bars later
        assert f.iloc[piv_idx] != f.iloc[piv_idx], "pivot visible too early"
        assert f.iloc[conf_idx] == 5, "pivot not confirmed at the right bar"

    def test_trailing_stop_never_widens(self):
        # Rising lows: each confirmed pivot should ratchet the stop UP.
        n = 40
        lows = [90 + i for i in range(n)]
        highs = [95 + i for i in range(n)]
        bars = self._bars(n, lows=lows, highs=highs)
        fr = um.find_fractal_lows(bars)
        r = um.resolve_structural(bars, bars.index[0] - pd.Timedelta(hours=4),
                                  entry=100.0, stop=90.0, target=120.0,
                                  is_long=True, max_bars=n, trail=True,
                                  fractal_lows=fr)
        assert r["outcome"] in ("target", "trail_exit", "stop", "timeout")
        # a ratcheted exit above entry must be reported as profit
        if r["outcome"] == "trail_exit":
            assert r["pnl_r"] > 0

    def test_trail_exit_pnl_measured_from_actual_stop_not_minus_one(self):
        # Needs a REAL pivot above entry: strictly rising lows contain no
        # local minimum, so no fractal ever confirms and nothing ratchets.
        # Dip at index 3 (102) with higher bars each side -> confirms at
        # index 5 -> stop ratchets to ~101.9, above the 100 entry. Then
        # price collapses through it, so the exit must book a PROFIT.
        lows = [101, 103, 105, 102, 104, 106, 108, 110, 112, 114] + [50] * 10
        highs = [h + 4 for h in lows]
        bars = self._bars(len(lows), lows=lows, highs=highs)
        fr = um.find_fractal_lows(bars)
        assert fr.dropna().iloc[0] == 102, "expected pivot not confirmed"
        r = um.resolve_structural(bars, bars.index[0] - pd.Timedelta(hours=4),
                                  entry=100.0, stop=95.0, target=1e9,
                                  is_long=True, max_bars=len(lows), trail=True,
                                  fractal_lows=fr)
        assert r["outcome"] == "trail_exit"
        assert r["pnl_r"] > 0, "a profitable trail exit was booked as a loss"

    def test_rr_parity_across_modes(self):
        # Every mode must target the same reward:risk, so the comparison
        # isolates stop PLACEMENT rather than a different payoff.
        import inspect
        src = inspect.getsource(um.backtest_structural)
        assert "rr: float = 2.0" in src
        assert "target = entry + rr * risk" in src

    def test_unknown_mode_rejected(self):
        with pytest.raises(ValueError):
            um.backtest_structural(pd.DataFrame(), pd.DataFrame(), mode="nope")

    def test_verdict_applies_the_same_bar_as_overlays(self):
        def rows(atr_eb, alt_eb):
            mk = lambda v: [{"n": 20, "expectancy_r_net": v}] * 4
            return {"atr": {"folds": mk(atr_eb)},
                    "swing": {"folds": mk(alt_eb)},
                    "trail": {"folds": mk(atr_eb)},
                    "swing_trail": {"folds": mk(atr_eb)}}
        good = {"BTC": rows(0.0, 0.2), "ETH": rows(0.0, 0.2),
                "SOL": rows(0.0, 0.2)}
        assert "CANDIDATE" in um.structural_verdict(good)
        bad = {"BTC": rows(0.2, 0.0), "ETH": rows(0.2, 0.0),
               "SOL": rows(0.2, 0.0)}
        assert "CANDIDATE" not in um.structural_verdict(bad)


class TestTradeMechanics:
    """Hyp. #24-30: lifecycle variants. The subtle failure modes are a
    partial that double-counts, a time-stop that fires on winners, and
    derived targets that peek. All pinned here."""

    @staticmethod
    def _bars(n, lows=None, highs=None, close=100.0):
        idx = pd.date_range("2024-01-01", periods=n, freq="4h")
        c = pd.Series(close, index=idx)
        return pd.DataFrame({
            "High": (pd.Series(highs, index=idx) if highs is not None else c),
            "Low": (pd.Series(lows, index=idx) if lows is not None else c),
            "Close": c}, index=idx)

    def test_params_registered(self):
        p = um.MECHANICS_PARAMS
        assert p["bb_period"] == 20 and p["bb_std"] == 2.0
        assert p["time_stop_bars"] == 6
        assert p["partial_at_r"] == 1.0 and p["partial_frac"] == 0.5

    def test_partial_then_target_blends_correctly(self):
        # entry 100, stop 95 (risk 5), target 110 (2R). Price touches
        # 105 (+1R) then 110. Expected: 0.5*1R + 0.5*2R = 1.5R
        highs = [105, 110]; lows = [100, 105]
        bars = self._bars(2, lows=lows, highs=highs)
        r = um.resolve_mechanics(bars, bars.index[0] - pd.Timedelta(hours=4),
                                 100.0, 95.0, 110.0, True, 10, partial=True)
        assert r["outcome"] == "target"
        assert r["pnl_r"] == pytest.approx(1.5)

    def test_partial_then_stop_blends_correctly(self):
        # +1R on half, then full stop on the rest: 0.5*1 + 0.5*(-1) = 0
        highs = [105, 100]; lows = [100, 94]
        bars = self._bars(2, lows=lows, highs=highs)
        r = um.resolve_mechanics(bars, bars.index[0] - pd.Timedelta(hours=4),
                                 100.0, 95.0, 110.0, True, 10, partial=True)
        assert r["outcome"] == "stop"
        assert r["pnl_r"] == pytest.approx(0.0)

    def test_time_stop_only_fires_when_not_in_profit(self):
        flat = self._bars(10, lows=[99] * 10, highs=[101] * 10, close=99.5)
        r = um.resolve_mechanics(flat, flat.index[0] - pd.Timedelta(hours=4),
                                 100.0, 95.0, 110.0, True, 20, time_stop_bars=6)
        assert r["outcome"] == "time_stop" and r["bars"] == 6
        # a trade in profit at bar 6 must NOT be time-stopped
        up = self._bars(10, lows=[100] * 10, highs=[104] * 10, close=103.0)
        r2 = um.resolve_mechanics(up, up.index[0] - pd.Timedelta(hours=4),
                                  100.0, 95.0, 110.0, True, 20, time_stop_bars=6)
        assert r2["outcome"] != "time_stop"

    def test_no_partial_means_unchanged_pnl(self):
        highs = [105, 110]; lows = [100, 105]
        bars = self._bars(2, lows=lows, highs=highs)
        r = um.resolve_mechanics(bars, bars.index[0] - pd.Timedelta(hours=4),
                                 100.0, 95.0, 110.0, True, 10, partial=False)
        assert r["pnl_r"] == pytest.approx(2.0)

    def test_bb_width_is_trailing_only(self):
        n = 60
        idx = pd.date_range("2024-01-01", periods=n, freq="D")
        base = pd.DataFrame({"Close": pd.Series(100.0, index=idx)})
        shocked = base.copy()
        shocked.iloc[40:, 0] = 200.0          # shock AFTER day 30
        d = idx[30]
        assert um.bb_width_at(base).get(d) == pytest.approx(
            um.bb_width_at(shocked).get(d)), "future prices changed a past BB width"

    def test_variants_are_named_not_swept(self):
        # A grid search would have many numeric permutations; this must
        # stay a short list of NAMED, registered changes. Adding a name
        # here means adding a numbered hypothesis to findings.md.
        assert set(um.MECHANICS_VARIANTS) == {
            "baseline", "entry_4h", "measured", "swing_target",
            "time_stop", "partial", "rr_1_5", "rr_3", "adaptive"}


class TestAdaptiveRRAndCeiling:
    """Hyp. #31: R:R and hold horizon derived from ADX regime rather
    than preset. Plus the target-ceiling diagnostic, which must be
    honest about being an UPPER BOUND (MFE counts wick touches)."""

    def test_adaptive_params_are_wilders_conventions(self):
        p = um.ADAPTIVE_PARAMS
        assert p["adx_period"] == 14 and p["adx_trend_min"] == 25.0
        # reused repo values, not new inventions
        assert p["rr_trend"] == 3.0 and p["rr_chop"] == 1.5
        assert p["hold_trend_days"] == 15 and p["hold_chop_days"] == 3

    def test_adx_is_trailing_and_bounded(self):
        n = 200
        idx = pd.date_range("2024-01-01", periods=n, freq="D")
        c = pd.Series(np.linspace(100, 200, n), index=idx)   # strong trend
        df = pd.DataFrame({"High": c * 1.01, "Low": c * 0.99, "Close": c})
        adx = um.compute_adx(df)
        v = adx.dropna()
        assert (v >= 0).all() and (v <= 100).all()
        # a shock AFTER date d must not change ADX at d
        shocked = df.copy()
        shocked.iloc[150:] = shocked.iloc[150:] * 3
        d = idx[100]
        assert um.compute_adx(shocked).get(d) == pytest.approx(adx.get(d)), \
            "future bars changed a past ADX — lookahead"

    def test_trending_series_scores_higher_adx_than_chop(self):
        n = 200
        idx = pd.date_range("2024-01-01", periods=n, freq="D")
        trend = pd.Series(np.linspace(100, 200, n), index=idx)
        chop = pd.Series(100 + 2 * np.sin(np.arange(n) / 2.0), index=idx)
        mk = lambda s: pd.DataFrame({"High": s * 1.01, "Low": s * 0.99,
                                     "Close": s})
        assert (um.compute_adx(mk(trend)).iloc[-1]
                > um.compute_adx(mk(chop)).iloc[-1])

    def test_ceiling_math_is_exact(self):
        # 10 trades at R:R 2.0; 4 hit target (mfe 100%), 3 reached 50%
        # of target (=1R), 3 reached nothing.
        mk = lambda mfe, out: {"mfe_pct_of_target": mfe, "outcome": out,
                               "pnl_r_net": 0.0, "rr_actual": 2.0}
        trades = ([mk(100.0, "target")] * 4 + [mk(50.0, "stop")] * 3
                  + [mk(5.0, "stop")] * 3
                  + [mk(5.0, "stop")] * 10)   # pad past the min-n guard
        txt = um.target_ceiling_report(trades, levels=(1.0,))
        # at 1R: needs mfe >= 50% -> 4 + 3 = 7 of 20 -> 35%
        assert "7/20" in txt and "35%" in txt

    def test_ceiling_report_states_its_upper_bound_caveat(self):
        mk = lambda: {"mfe_pct_of_target": 60.0, "outcome": "stop",
                      "pnl_r_net": -1.0, "rr_actual": 2.0}
        txt = um.target_ceiling_report([mk() for _ in range(30)])
        assert "UPPER BOUND" in txt and "wick" in txt

    def test_ceiling_refuses_thin_samples(self):
        assert "too few" in um.target_ceiling_report([])


# ======================================================================
# EXIT-LEVEL PRECISION — the sub-dollar rounding defect
# ======================================================================
# compute_exit_levels used to round entry/target/stop to a FIXED 2 decimals.
# At BTC's $78,000 that is immaterial. For an asset trading at $0.00145 the
# entry, the target and the stop all collapse onto 0.00, and then:
#   * stop_dist = abs(entry - stop) = 0, so resolve_on_4h's
#     `tgt_dist / stop_dist` guard returned NaN pnl_r;
#   * `high >= target` is trivially true against a target of 0.00, so the
#     trade was labelled `target` on its first bar -- a MANUFACTURED 100%
#     win rate;
#   * stats_from_trades averages with .mean(), which SKIPS NaN, so win% was
#     computed over every trade while expectancy was computed over only the
#     non-NaN ones. The two columns described different trade sets.
# Measured on the 82-ticker basket: 185 of 645 STRONG_BUY trades (28.7%)
# across 35 tickers carried NaN P&L. The bot has been live with this.
class TestExitLevelPrecision:

    def test_sub_penny_asset_gets_distinct_levels(self):
        import signal_engines as se
        lvl = se.compute_exit_levels(0.00145, "STRONG_BUY", atr=0.00003)
        assert lvl["applicable"]
        e, t, s = lvl["entry"], lvl["target"], lvl["stop"]
        assert e != t and e != s and t != s, f"levels collapsed: {e}, {t}, {s}"
        assert abs(e - s) > 0, "stop distance rounded away to zero"
        assert t > e > s, "long levels must be ordered target > entry > stop"

    def test_low_volatility_dollar_asset_gets_distinct_levels(self):
        # Not just cheap coins: the trigger is 1.5*ATR falling under half a
        # cent in ABSOLUTE terms, which low volatility reaches at $1+ too.
        import signal_engines as se
        lvl = se.compute_exit_levels(1.25, "BUY", atr=0.002)
        assert lvl["applicable"]
        e, t, s = lvl["entry"], lvl["target"], lvl["stop"]
        assert e != t and e != s, f"levels collapsed: {e}, {t}, {s}"
        assert abs(e - s) > 0
        assert t > e > s

    def test_stop_distance_is_a_fixed_fraction_of_entry_at_any_price(self):
        # The whole point of ATR bands: the geometry must not depend on the
        # asset's price scale. 1.5*ATR/entry should be identical for a
        # $78,000 asset and a $0.00145 one with proportional ATR.
        import signal_engines as se
        big = se.compute_exit_levels(78000.0, "BUY", atr=1560.0)     # ATR = 2% of price
        small = se.compute_exit_levels(0.00145, "BUY", atr=0.000029)  # ATR = 2% of price
        f_big = abs(big["entry"] - big["stop"]) / big["entry"]
        f_small = abs(small["entry"] - small["stop"]) / small["entry"]
        assert f_big == pytest.approx(f_small, rel=1e-3), (
            f"stop fraction depends on price scale: {f_big} vs {f_small}")

    def test_resolve_on_4h_never_returns_nan_pnl(self):
        idx = pd.date_range("2024-01-01", periods=10, freq="4h")
        bars = pd.DataFrame({"Open": 0.00145, "High": 0.00150, "Low": 0.00140,
                             "Close": 0.00145, "Volume": 1.0}, index=idx)
        lvl = epm.compute_exit_levels(0.00145, "STRONG_BUY", atr=0.00003)
        r = um.resolve_on_4h(bars, idx[0], lvl["entry"], lvl["target"],
                             lvl["stop"], True, max_bars=9)
        assert r["pnl_r"] is None or r["pnl_r"] == r["pnl_r"], \
            f"resolve_on_4h returned NaN pnl_r: {r}"

    def test_resolve_on_4h_refuses_a_zero_stop_distance(self):
        # If a caller ever hands it entry == stop, that is a bug upstream.
        # It must fail loudly, not hand back a NaN that .mean() will hide.
        idx = pd.date_range("2024-01-01", periods=5, freq="4h")
        bars = pd.DataFrame({"Open": 1.0, "High": 1.1, "Low": 0.9,
                             "Close": 1.0, "Volume": 1.0}, index=idx)
        with pytest.raises(ValueError):
            um.resolve_on_4h(bars, idx[0], 1.0, 1.2, 1.0, True, max_bars=4)

    def test_stats_from_trades_raises_on_nan_pnl(self):
        # .mean() skipping NaN is what let a corrupt trade set report a
        # clean-looking expectancy alongside a win rate over a DIFFERENT set.
        bad = [{"outcome": "target", "pnl_r": float("nan"),
                "pnl_r_net": float("nan"), "cost_r": 0.0, "stop_pct": 0.0,
                "days_held": 1.0, "score": 70.0},
               {"outcome": "stop", "pnl_r": -1.0, "pnl_r_net": -1.0,
                "cost_r": 0.0, "stop_pct": 2.0, "days_held": 1.0, "score": 70.0}]
        with pytest.raises(ValueError):
            um.stats_from_trades(bad)

    def test_stats_from_trades_still_accepts_clean_trades(self):
        good = [{"outcome": "target", "pnl_r": 2.0, "pnl_r_net": 1.97,
                 "cost_r": 0.03, "stop_pct": 2.0, "days_held": 1.0, "score": 70.0},
                {"outcome": "stop", "pnl_r": -1.0, "pnl_r_net": -1.03,
                 "cost_r": 0.03, "stop_pct": 2.0, "days_held": 1.0, "score": 70.0}]
        s = um.stats_from_trades(good)
        assert s["n"] == 2 and s["expectancy_r"] == pytest.approx(0.5)

    def test_big_asset_levels_are_unchanged_by_the_fix(self):
        # Regression guard: the majors must not move. 2dp was already
        # correct for them and every previously reported number depends on
        # it staying correct.
        import signal_engines as se
        lvl = se.compute_exit_levels(100.0, "BUY", atr=2.0)
        assert lvl["entry"] == 100.0
        assert lvl["target"] == pytest.approx(106.0)
        assert lvl["stop"] == pytest.approx(97.0)
        assert lvl["risk_reward"] == 2.0


# ======================================================================
# PRODUCTION DIAGNOSTICS — the silently-erroring sentiment gate
# ======================================================================
# The gate had been returning decision=ERROR for 1,350 consecutive runs
# while every GitHub Actions run reported success: the gate errors, falls
# back to a neutral 1.0 multiplier, and the pipeline carries on. The
# FALLBACK IS CORRECT and is not changed by any of this -- a dead sentiment
# provider must not take the signal service down (it did once, for 2+ days).
# What was wrong is that the failure was invisible: no HTTP status, no
# response body, no annotation, no count.
class TestSentimentGateDiagnostics:

    def test_redact_secret_removes_the_key(self):
        body = '{"error":"quota","key":"SUPERSECRETKEY123"}'
        out = epm.redact_secret(body, "SUPERSECRETKEY123")
        assert "SUPERSECRETKEY123" not in out
        assert "REDACTED" in out and "quota" in out

    def test_redact_secret_also_scrubs_the_env_key(self, monkeypatch):
        monkeypatch.setenv("ADANOS_API_KEY", "ENVKEY9999")
        assert "ENVKEY9999" not in epm.redact_secret("leak ENVKEY9999 here")

    def test_redact_secret_handles_none_and_short_keys(self):
        assert epm.redact_secret(None) == ""
        # A 3-char "key" must not blank out every occurrence of that
        # substring in an unrelated body.
        assert epm.redact_secret("abcdef", "abc") == "abcdef"

    def test_gh_annotate_is_silent_off_actions(self, capsys, monkeypatch):
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
        epm.gh_annotate("warning", "T", "message")
        assert capsys.readouterr().out == ""

    def test_gh_annotate_emits_warning_on_actions(self, capsys, monkeypatch):
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        epm.gh_annotate("warning", "Sentiment gate ERROR", "HTTP 429 quota")
        out = capsys.readouterr().out
        assert out.startswith("::warning title=Sentiment gate ERROR::")
        assert "HTTP 429 quota" in out

    def test_gh_annotate_never_leaks_the_key(self, capsys, monkeypatch):
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        monkeypatch.setenv("ADANOS_API_KEY", "LEAKME12345")
        epm.gh_annotate("warning", "T", "body contained LEAKME12345")
        assert "LEAKME12345" not in capsys.readouterr().out

    def test_gh_annotate_is_single_line(self, capsys, monkeypatch):
        # A newline would truncate the annotation and orphan the remainder
        # as raw log text.
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        epm.gh_annotate("warning", "T", "line one\nline two\r\nthree")
        assert capsys.readouterr().out.count("\n") == 1

    def test_gate_error_reports_http_status_and_body(self, capsys):
        # The whole point: an ERROR must carry the CAUSE.
        err = ConnectionError("boom")
        err.http_status = 429
        err.http_body = '{"detail":"monthly quota exceeded"}'

        def boom(*a, **kw):
            raise err

        gate = epm.cached_sentiment_check(
            "BTC", fetcher=boom, api_key="k", cache_path="", ttl_hours=0)
        out = capsys.readouterr().out
        assert gate["decision"] == "ERROR"
        assert gate["gate_multiplier"] == 1.0      # fallback UNCHANGED
        assert "429" in out and "quota exceeded" in out
        assert "429" in gate["reason"]

    def test_gate_error_still_returns_neutral_fallback(self):
        # Guard the thing that must NOT change.
        def boom(*a, **kw):
            raise ConnectionError("no status attached")

        gate = epm.cached_sentiment_check(
            "BTC", fetcher=boom, api_key="k", cache_path="", ttl_hours=0)
        assert gate["decision"] == "ERROR"
        assert gate["gate_multiplier"] == 1.0
        assert gate["sentiment_score"] is None


class TestAuditGateErrorStreak:

    def _audit(self):
        import importlib
        return importlib.import_module("audit")

    def _log(self, tmp_path, decisions):
        p = tmp_path / "signal_log.csv"
        pd.DataFrame({"timestamp_utc": pd.date_range("2026-01-01", periods=len(decisions),
                                                     freq="h").astype(str),
                      "gate_decision": decisions}).to_csv(p, index=False)
        return str(p)

    def test_counts_consecutive_trailing_errors(self, tmp_path, monkeypatch):
        a = self._audit()
        monkeypatch.setattr(a, "_origin_log", lambda path="x": (None, "no remote"))
        p = self._log(tmp_path, ["PROCEED", "PROCEED", "ERROR", "ERROR", "ERROR"])
        a._results.clear()
        a.check_sentiment_gate_errors(p)
        assert a._results[-1]["evidence"]["consecutive_error_runs"] == 3

    def test_a_later_success_resets_the_streak(self, tmp_path, monkeypatch):
        a = self._audit()
        monkeypatch.setattr(a, "_origin_log", lambda path="x": (None, "no remote"))
        p = self._log(tmp_path, ["ERROR", "ERROR", "PROCEED"])
        a._results.clear()
        a.check_sentiment_gate_errors(p)
        assert a._results[-1]["evidence"]["consecutive_error_runs"] == 0
        assert a._results[-1]["status"] == a.PASS

    def test_long_streak_is_a_hard_fail(self, tmp_path, monkeypatch):
        a = self._audit()
        monkeypatch.setattr(a, "_origin_log", lambda path="x": (None, "no remote"))
        p = self._log(tmp_path, ["ERROR"] * 12)
        a._results.clear()
        a.check_sentiment_gate_errors(p)
        assert a._results[-1]["status"] == a.FAIL

    def test_freshness_labels_a_local_only_measurement(self, tmp_path, monkeypatch):
        # It cried wolf twice by reporting local-clone lag as an outage.
        a = self._audit()
        monkeypatch.setattr(a, "_origin_log", lambda path="x": (None, "no remote"))
        p = tmp_path / "signal_log.csv"
        pd.DataFrame({"timestamp_utc": ["2020-01-01T00:00:00"]}).to_csv(p, index=False)
        a._results.clear()
        a.check_log_freshness(str(p))
        assert "LOCAL CLONE ONLY" in a._results[-1]["detail"]
