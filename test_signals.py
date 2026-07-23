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
        # A score of 65 is a BUY normally but only a WATCH in extreme fear.
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
    """The SELL side was built by mirroring the validated BUY side around 50.
    This proves that claim exactly: for every score s, the label of (100 - s)
    is the mirror label of s — in BOTH regimes."""

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
        # Raised buy bars: STRONG_BUY 80, BUY 70. Their exact reflections
        # about 50 are STRONG_SELL 20, SELL 30 — which is what the code uses.
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
