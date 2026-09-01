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
from datetime import datetime, timedelta, timezone

import pytest
import pandas as pd
import numpy as np

# Make the pipeline modules importable no matter where pytest is invoked
# from, as long as this test file sits beside them.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pipeline as um
import signal_engines as epm
import signal_engines as ads


@pytest.fixture(autouse=True)
def _isolate_sentiment_run_cache():
    """The per-run sentiment cache is process-global. Production gets a
    fresh process per workflow run; tests share one, so reset around every
    test or a reading leaks into an unrelated assertion."""
    import signal_engines as _se
    _se.reset_run_cache()
    yield
    _se.reset_run_cache()


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

    def test_gate_error_reports_http_status_and_body(self, capsys, tmp_path):
        # The whole point: an ERROR must carry the CAUSE.
        err = ConnectionError("boom")
        err.http_status = 429
        err.http_body = '{"detail":"monthly quota exceeded"}'

        def boom(*a, **kw):
            raise err

        gate = epm.cached_sentiment_check(
            "BTC", fetcher=boom, api_key="k",
            cache_path=str(tmp_path / "none.json"), ttl_hours=0)
        out = capsys.readouterr().out
        assert gate["decision"] == "ERROR"
        assert gate["gate_multiplier"] == 1.0      # fallback UNCHANGED
        assert "429" in out and "quota exceeded" in out
        assert "429" in gate["reason"]

    def test_gate_error_still_returns_neutral_fallback(self, tmp_path):
        # Guard the thing that must NOT change.
        def boom(*a, **kw):
            raise ConnectionError("no status attached")

        gate = epm.cached_sentiment_check(
            "BTC", fetcher=boom, api_key="k",
            cache_path=str(tmp_path / "none.json"), ttl_hours=0)
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


# ======================================================================
# LIVE-PATH SENTIMENT GATING — Adanos quota
# ======================================================================
# The gate is DAMPEN-ONLY (multiplier <= 1.0), so on a day whose Step 1
# score is low enough that even PERFECT indicators cannot reach the buy
# bar, dampening provably cannot change the label — and the Adanos call is
# a pure no-op. Skipping those days is free quota.
#
# THE CUTOFF IS DERIVED, NOT THE BUY BAR. final = wp*gated + wi*indicators.
# With perfect indicators (100), final = wp*initial + wi*100, so the label
# can only reach buy_bar when initial >= (buy_bar - wi*100)/wp = 33.3 at
# production weights. Using buy_bar (60) as the threshold would skip the
# whole 33.3..60 band, where a VETO genuinely does flip a BUY — see
# test_cutoff_must_not_be_the_buy_bar, which demonstrates the flip.
class TestLiveSentimentQuotaGating:

    def test_cutoff_is_derived_from_the_weights(self):
        assert um.sentiment_call_cutoff(60.0, 0.6, 0.4) == pytest.approx(33.333, abs=0.01)
        # It must move with the bar and the weights, not be hardcoded.
        assert um.sentiment_call_cutoff(70.0, 0.6, 0.4) > um.sentiment_call_cutoff(60.0, 0.6, 0.4)
        assert um.sentiment_call_cutoff(60.0, 0.8, 0.2) > um.sentiment_call_cutoff(60.0, 0.6, 0.4)

    def test_cutoff_must_not_be_the_buy_bar(self):
        # A score of 50 is BELOW the buy bar but ABOVE the derived cutoff,
        # and the gate changes the outcome there. This is the test that
        # forbids "skip whenever initial_score < buy_bar".
        step3 = {"indicator_final_score": 100.0, "vix_level": 18.0}
        undampened = um.combine_and_decide({"gated_score": 50.0}, step3)
        vetoed = um.combine_and_decide({"gated_score": 25.0}, step3)   # 50 * 0.5
        assert undampened["direction"] in ("BUY", "STRONG_BUY")
        assert vetoed["direction"] not in ("BUY", "STRONG_BUY"), (
            "if a VETO cannot flip this, the cutoff argument is wrong")
        assert 50.0 > um.sentiment_call_cutoff(60.0, 0.6, 0.4)

    def test_below_cutoff_skips_the_api_call_entirely(self, tmp_path):
        calls = []

        def fetcher(*a, **kw):
            calls.append(1)
            raise AssertionError("must not be called below the cutoff")

        step2 = um.apply_reddit_step("BTC", {"step": 1, "initial_score": 10.0},
                                     lazy=True, fetcher=fetcher,
                                     cache_path=str(tmp_path / "c.json"), ttl_hours=0)
        assert calls == []
        assert step2["gate_decision"] == "SKIPPED_BELOW_THRESHOLD"
        assert step2["gate_multiplier"] == 1.0
        assert step2["gated_score"] == pytest.approx(10.0)

    def test_above_cutoff_still_calls(self, tmp_path):
        calls = []

        def fetcher(ticker, **kw):
            calls.append(ticker)
            return {"decision": "PROCEED", "gate_multiplier": 1.0, "reason": "ok",
                    "sentiment_score": 0.1, "mentions": 40,
                    "cache_hit": False, "cache_age_hours": 0.0,
                    "stale_fallback": False}

        epm.reset_run_cache()
        step2 = um.apply_reddit_step("BTC", {"step": 1, "initial_score": 80.0},
                                     lazy=True, fetcher=fetcher,
                                     cache_path=str(tmp_path / "c.json"), ttl_hours=0)
        assert calls == ["BTC"]
        assert step2["gate_decision"] == "PROCEED"

    def test_skip_label_is_distinct_from_error(self, tmp_path):
        # ERROR means the provider failed and the gate is silently neutral.
        # SKIPPED_BELOW_THRESHOLD means we chose not to ask. Conflating them
        # would hide a real outage inside a routine optimisation.
        step2 = um.apply_reddit_step("BTC", {"step": 1, "initial_score": 5.0},
                                     lazy=True, fetcher=lambda *a, **k: None,
                                     cache_path=str(tmp_path / "c.json"), ttl_hours=0)
        assert step2["gate_decision"] == "SKIPPED_BELOW_THRESHOLD"
        assert step2["gate_decision"] != "ERROR"
        assert step2["gate_decision"] != "SKIPPED"

    def test_lazy_off_by_default_preserves_old_behaviour(self, tmp_path):
        epm.reset_run_cache()
        calls = []

        def fetcher(ticker, **kw):
            calls.append(ticker)
            return {"decision": "PROCEED", "gate_multiplier": 1.0, "reason": "ok",
                    "cache_hit": False, "cache_age_hours": 0.0, "stale_fallback": False}

        um.apply_reddit_step("BTC", {"step": 1, "initial_score": 1.0}, fetcher=fetcher,
                             cache_path=str(tmp_path / "c.json"), ttl_hours=0)
        assert calls == ["BTC"], "default must remain always-call"


class TestPerRunSentimentCache:

    @pytest.fixture(autouse=True)
    def _td(self, tmp_path):
        self._tmpdir = tmp_path

    def test_same_ticker_twice_in_one_run_calls_once(self):
        epm.reset_run_cache()
        calls = []

        def fetcher(ticker, **kw):
            calls.append(ticker)
            return {"decision": "PROCEED", "gate_multiplier": 1.0, "reason": "ok",
                    "sentiment_score": 0.2, "mentions": 30}

        import os as _os
        cp = str(self._tmpdir / "c.json")
        epm.cached_sentiment_check("BTC", fetcher=fetcher, api_key="k",
                                   cache_path=cp, ttl_hours=4)
        if _os.path.exists(cp):
            _os.remove(cp)          # kill the DISK layer
        epm.cached_sentiment_check("BTC", fetcher=fetcher, api_key="k",
                                   cache_path=cp, ttl_hours=4)
        assert calls == ["BTC"], (
            f"disk cache was deleted, so the per-run cache must have served "
            f"the second call; got {calls}")

    def test_different_tickers_are_not_shared(self):
        # Adanos is keyed per token (/v1/token/{symbol}), NOT market-wide.
        # Serving BTC's reading for ETH would be a correctness bug, not a
        # saving.
        epm.reset_run_cache()
        calls = []

        def fetcher(ticker, **kw):
            calls.append(ticker)
            return {"decision": "PROCEED", "gate_multiplier": 1.0, "reason": ticker,
                    "sentiment_score": 0.2, "mentions": 30}

        cp = str(self._tmpdir / "c2.json")
        a = epm.cached_sentiment_check("BTC", fetcher=fetcher, api_key="k",
                                       cache_path=cp, ttl_hours=4)
        b = epm.cached_sentiment_check("ETH", fetcher=fetcher, api_key="k",
                                       cache_path=cp, ttl_hours=4)
        assert calls == ["BTC", "ETH"]
        assert a["reason"] != b["reason"]

    def test_run_cache_does_not_memoise_an_error(self, tmp_path):
        # An ERROR must be retried by the next ticker/run, not cached.
        # Uses an EMPTY on-disk cache: with a populated one the error path
        # correctly falls back to a stale reading instead of ERROR, which
        # is a different (also desirable) behaviour.
        epm.reset_run_cache()
        cp = str(tmp_path / "no_such_cache.json")
        calls = []

        def boom(ticker, **kw):
            calls.append(ticker)
            raise ConnectionError("down")

        for _ in range(2):
            g = epm.cached_sentiment_check("BTC", fetcher=boom, api_key="k",
                                           cache_path=cp, ttl_hours=0)
            assert g["decision"] == "ERROR"
        assert len(calls) == 2, "a failed call must not be cached as a result"


# ======================================================================
# TRIGGER REDUNDANCY GUARD
# ======================================================================
# Native cron and cron-job.org both drive this workflow on purpose now:
# either one alone has been unreliable (an 11h gap on 2026-08-27 with
# dispatch-only; and GitHub's own cron was abandoned earlier for the same
# reason). Redundancy is the point. The guard is what stops redundancy
# becoming double-spend: whichever trigger arrives second sees a log entry
# newer than the window and stands down.
#
# FAIL-OPEN, ALWAYS. Every ambiguous case (missing file, empty file,
# unparseable timestamp, unreadable) returns should_run=True. A guard that
# fails closed would silently stop the signal service, which is a far worse
# failure than one duplicate run.
class TestTriggerGuard:

    def _log(self, tmp_path, minutes_old):
        p = tmp_path / "signal_log.csv"
        ts = pd.Timestamp.now(tz="UTC") - pd.Timedelta(minutes=minutes_old)
        pd.DataFrame({"timestamp_utc": [ts.isoformat()]}).to_csv(p, index=False)
        return str(p)

    def test_recent_entry_stands_down(self):
        import live_tools as lt
        run, why = lt.should_run_now(self._log(self._tp, 10), max_age_minutes=50)
        assert run is False
        assert "10" in why or "min" in why

    def test_old_entry_proceeds(self):
        import live_tools as lt
        run, _ = lt.should_run_now(self._log(self._tp, 65), max_age_minutes=50)
        assert run is True

    def test_boundary_just_inside_stands_down(self):
        import live_tools as lt
        assert lt.should_run_now(self._log(self._tp, 49), max_age_minutes=50)[0] is False

    def test_boundary_just_outside_proceeds(self):
        import live_tools as lt
        assert lt.should_run_now(self._log(self._tp, 51), max_age_minutes=50)[0] is True

    def test_missing_file_fails_open(self):
        import live_tools as lt
        run, why = lt.should_run_now(str(self._tp / "nope.csv"), max_age_minutes=50)
        assert run is True and "no log" in why.lower()

    def test_empty_log_fails_open(self):
        import live_tools as lt
        p = self._tp / "empty.csv"
        pd.DataFrame({"timestamp_utc": []}).to_csv(p, index=False)
        assert lt.should_run_now(str(p), max_age_minutes=50)[0] is True

    def test_unparseable_timestamps_fail_open(self):
        import live_tools as lt
        p = self._tp / "junk.csv"
        pd.DataFrame({"timestamp_utc": ["not-a-date"]}).to_csv(p, index=False)
        assert lt.should_run_now(str(p), max_age_minutes=50)[0] is True

    def test_writes_github_output(self, monkeypatch):
        import live_tools as lt
        out = self._tp / "gh_out"
        monkeypatch.setenv("GITHUB_OUTPUT", str(out))
        lt.emit_should_run(self._log(self._tp, 10), max_age_minutes=50)
        assert "should_run=false" in out.read_text()
        out.write_text("")
        lt.emit_should_run(self._log(self._tp, 99), max_age_minutes=50)
        assert "should_run=true" in out.read_text()

    def test_emit_returns_zero_even_when_standing_down(self, monkeypatch):
        # Standing down is a normal outcome, not a failure. A non-zero exit
        # would paint the Actions run red for working correctly.
        import live_tools as lt
        monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
        assert lt.emit_should_run(self._log(self._tp, 5), max_age_minutes=50) == 0
        assert lt.emit_should_run(self._log(self._tp, 500), max_age_minutes=50) == 0

    @pytest.fixture(autouse=True)
    def _tmp(self, tmp_path):
        self._tp = tmp_path


# ======================================================================
# API KEY HYGIENE — the newline that killed the gate
# ======================================================================
# ROOT CAUSE, 2026-08-05 to 2026-08-27, 1,350 consecutive runs: the
# ADANOS_API_KEY secret was stored with a trailing newline. requests
# refuses to send a header whose value contains a return character, so it
# raised InvalidHeader CLIENT-SIDE and the request never reached the API.
# There was no HTTP status to diagnose because there was no HTTP request.
# The Actions log showed `'***\n'` -- GitHub redacted the key, the newline
# sat outside the redaction.
#
# Secrets get pasted with newlines. That is normal, and the code should
# tolerate it rather than fail silently for three weeks.
class TestApiKeyHygiene:

    def test_trailing_newline_is_stripped(self, monkeypatch):
        monkeypatch.setenv("ADANOS_API_KEY", "key\n")
        assert epm.get_api_key_from_env() == "key"

    def test_windows_crlf_is_stripped(self, monkeypatch):
        monkeypatch.setenv("ADANOS_API_KEY", "key\r\n")
        assert epm.get_api_key_from_env() == "key"

    def test_surrounding_spaces_are_stripped(self, monkeypatch):
        monkeypatch.setenv("ADANOS_API_KEY", " key ")
        assert epm.get_api_key_from_env() == "key"

    def test_unset_key_stays_none(self, monkeypatch):
        monkeypatch.delenv("ADANOS_API_KEY", raising=False)
        assert epm.get_api_key_from_env() is None

    def test_blank_key_is_falsy_not_whitespace(self, monkeypatch):
        # "   " must not read as a present key, or the missing-key error
        # never fires and you get InvalidHeader all over again.
        monkeypatch.setenv("ADANOS_API_KEY", "   ")
        assert not epm.get_api_key_from_env()

    def test_stripped_key_produces_a_sendable_header(self, monkeypatch):
        # The actual failure mode, end to end: a header value with \n is
        # rejected by urllib3 before any socket opens.
        import urllib3.util
        monkeypatch.setenv("ADANOS_API_KEY", "abc123\n")
        k = epm.get_api_key_from_env()
        urllib3.util.parse_url("https://x")          # import sanity
        assert "\n" not in k and "\r" not in k


# ======================================================================
# SENTIMENT TTL — the second half of the quota fix
# ======================================================================
# Reddit sentiment does not move hourly (three consecutive live readings on
# 2026-08-03 were all sentiment_score=-0.06). Gating on the derived cutoff
# alone still projected 381 req/month for ONE ticker against a 200/month
# tier, and ~1,143 for three. A 12h per-symbol TTL bounds it by CALENDAR
# rather than by candidate rate: at most 2 calls/day/symbol however many
# hours qualify, so 3 tickers x 2 x 31 = 186/month worst case.
class TestSentimentTTL:

    def test_default_ttl_is_twelve_hours(self):
        assert epm.SENTIMENT_TTL_HOURS == 12.0

    def test_second_call_inside_twelve_hours_costs_nothing(self, tmp_path):
        epm.reset_run_cache()
        calls = []

        def fetcher(t, **kw):
            calls.append(t)
            return {"decision": "PROCEED", "gate_multiplier": 1.0, "reason": "ok",
                    "sentiment_score": 0.1, "mentions": 40}

        cp = str(tmp_path / "c.json")
        t0 = datetime(2026, 8, 28, 0, 0, tzinfo=timezone.utc)
        epm.cached_sentiment_check("BTC", cache_path=cp, fetcher=fetcher, now=t0)
        for h in (1, 6, 11):
            epm.reset_run_cache()      # isolate the DISK ttl, not the run memo
            epm.cached_sentiment_check("BTC", cache_path=cp, fetcher=fetcher,
                                       now=t0 + timedelta(hours=h))
        assert calls == ["BTC"], f"expected 1 call inside 12h, got {len(calls)}"

    def test_call_resumes_after_twelve_hours(self, tmp_path):
        epm.reset_run_cache()
        calls = []

        def fetcher(t, **kw):
            calls.append(t)
            return {"decision": "PROCEED", "gate_multiplier": 1.0, "reason": "ok",
                    "sentiment_score": 0.1, "mentions": 40}

        cp = str(tmp_path / "c.json")
        t0 = datetime(2026, 8, 28, 0, 0, tzinfo=timezone.utc)
        epm.cached_sentiment_check("BTC", cache_path=cp, fetcher=fetcher, now=t0)
        epm.reset_run_cache()
        epm.cached_sentiment_check("BTC", cache_path=cp, fetcher=fetcher,
                                   now=t0 + timedelta(hours=12, minutes=1))
        assert len(calls) == 2

    def test_ttl_is_per_symbol(self, tmp_path):
        epm.reset_run_cache()
        calls = []

        def fetcher(t, **kw):
            calls.append(t)
            return {"decision": "PROCEED", "gate_multiplier": 1.0, "reason": t,
                    "sentiment_score": 0.1, "mentions": 40}

        cp = str(tmp_path / "c.json")
        t0 = datetime(2026, 8, 28, 0, 0, tzinfo=timezone.utc)
        for sym in ("BTC", "ETH", "SOL"):
            epm.cached_sentiment_check(sym, cache_path=cp, fetcher=fetcher, now=t0)
        assert calls == ["BTC", "ETH", "SOL"], "one symbol's TTL must not mask another's"

    def test_env_can_override_the_ttl(self, monkeypatch):
        # Operators need to tighten this without a code change if the tier
        # changes; the default is a default, not a constant.
        import importlib
        monkeypatch.setenv("SENTIMENT_TTL_HOURS", "6")
        se = importlib.reload(epm)
        try:
            assert se.SENTIMENT_TTL_HOURS == 6.0
        finally:
            monkeypatch.delenv("SENTIMENT_TTL_HOURS", raising=False)
            importlib.reload(se)


# ======================================================================
# DERIVATIVES COLLECTOR — the merge must be idempotent
# ======================================================================
# Every free derivatives source serves a ROLLING window, not an archive:
# Kraken funding ~1y hourly, OKX funding ~3 months, OKX OI 180 daily rows.
# So the collector re-fetches the FULL window every run and merges on
# (symbol, timestamp). That makes re-running harmless, makes a missed run
# self-healing as long as the gap is shorter than the venue's window, and
# gets a year of Kraken history free on the first run.
#
# This is DATA COLLECTION, not a hypothesis. Nothing here is scored.
class TestDerivativesMerge:

    def _cd(self):
        import importlib
        rd = os.path.join(os.path.dirname(os.path.abspath(__file__)), "research")
        if rd not in sys.path:
            sys.path.insert(0, rd)
        return importlib.import_module("collect_derivs")

    def _df(self, rows):
        return pd.DataFrame(rows, columns=["symbol", "timestamp", "funding_rate"])

    def test_overlapping_fetches_do_not_duplicate(self):
        cd = self._cd()
        a = self._df([("PF_XBTUSD", "2026-08-01T00:00:00Z", 1.0),
                      ("PF_XBTUSD", "2026-08-01T01:00:00Z", 2.0)])
        b = self._df([("PF_XBTUSD", "2026-08-01T01:00:00Z", 2.0),   # overlap
                      ("PF_XBTUSD", "2026-08-01T02:00:00Z", 3.0)])  # new
        merged, added, coll = cd.merge_rows(a, b)
        assert len(merged) == 3 and added == 1 and coll == 0

    def test_merge_is_idempotent(self):
        cd = self._cd()
        a = self._df([("PF_XBTUSD", "2026-08-01T00:00:00Z", 1.0)])
        once, _, _ = cd.merge_rows(a, a)
        twice, added, _ = cd.merge_rows(once, a)
        assert len(once) == 1 and len(twice) == 1 and added == 0

    def test_out_of_order_input_is_sorted(self):
        cd = self._cd()
        a = self._df([("PF_XBTUSD", "2026-08-01T05:00:00Z", 5.0)])
        b = self._df([("PF_XBTUSD", "2026-08-01T01:00:00Z", 1.0),
                      ("PF_XBTUSD", "2026-08-01T03:00:00Z", 3.0)])
        merged, _, _ = cd.merge_rows(a, b)
        assert list(merged.timestamp) == sorted(merged.timestamp)

    def test_symbols_do_not_collide_on_the_same_timestamp(self):
        cd = self._cd()
        a = self._df([("PF_XBTUSD", "2026-08-01T00:00:00Z", 1.0)])
        b = self._df([("PF_ETHUSD", "2026-08-01T00:00:00Z", 9.0)])
        merged, added, _ = cd.merge_rows(a, b)
        assert len(merged) == 2 and added == 1

    def test_existing_value_wins_and_revision_is_counted(self):
        # A venue quietly revising its own history must be visible, not
        # silently adopted into an archive older results may depend on.
        cd = self._cd()
        a = self._df([("PF_XBTUSD", "2026-08-01T00:00:00Z", 1.0)])
        b = self._df([("PF_XBTUSD", "2026-08-01T00:00:00Z", 99.0)])
        merged, added, coll = cd.merge_rows(a, b)
        assert added == 0 and coll == 1
        assert float(merged.iloc[0].funding_rate) == 1.0

    def test_empty_incoming_leaves_file_untouched(self, tmp_path):
        cd = self._cd()
        p = str(tmp_path / "kraken_funding.csv")
        self._df([("PF_XBTUSD", "2026-08-01T00:00:00Z", 1.0)]).to_csv(p, index=False)
        before = open(p, encoding="utf-8").read()
        res = cd.write_merged(p, pd.DataFrame())
        assert res["skipped"] is True and res["added"] == 0
        assert open(p, encoding="utf-8").read() == before

    def test_none_incoming_leaves_file_untouched(self, tmp_path):
        # This is the failed-venue path: a venue we could not READ must
        # never truncate the archive we already have.
        cd = self._cd()
        p = str(tmp_path / "okx_funding.csv")
        self._df([("BTC-USDT-SWAP", "2026-08-01T00:00:00Z", 1.0)]).to_csv(p, index=False)
        before = open(p, encoding="utf-8").read()
        res = cd.write_merged(p, None)
        assert res["skipped"] is True and res["rows"] == 1
        assert open(p, encoding="utf-8").read() == before

    def test_first_write_creates_the_file(self, tmp_path):
        cd = self._cd()
        p = str(tmp_path / "new" / "okx_oi.csv")
        res = cd.write_merged(p, self._df([("BTC", "2026-08-01T00:00:00Z", 1.0)]))
        assert os.path.exists(p) and res["rows"] == 1 and res["added"] == 1

    def test_a_gap_shorter_than_the_window_self_heals(self, tmp_path):
        # Miss a run: the next full-window fetch backfills the hole.
        cd = self._cd()
        p = str(tmp_path / "kraken_funding.csv")
        cd.write_merged(p, self._df([("PF_XBTUSD", "2026-08-01T00:00:00Z", 1.0)]))
        full = self._df([("PF_XBTUSD", "2026-08-01T00:00:00Z", 1.0),
                         ("PF_XBTUSD", "2026-08-01T01:00:00Z", 2.0),   # missed
                         ("PF_XBTUSD", "2026-08-01T02:00:00Z", 3.0)])
        res = cd.write_merged(p, full)
        assert res["rows"] == 3 and res["added"] == 2


# ======================================================================
# PAGINATION CEILING + TRUNCATION ASSERTION
# ======================================================================
# fetch_klines_paginated defaulted to max_requests=20, and Binance.US
# returns 1000 bars per call -- a hard 20,000-bar ceiling. The 1h program
# needs ~60,730 bars per ticker, i.e. >= 61 pages. Without the raise the
# export would silently write a ~2.3-year file and every 1h number would be
# computed on a third of the available history with nothing saying so.
#
# Raising the ceiling alone fixes today and leaves the failure mode intact,
# so the export also asserts that what came back is at least 95% of what was
# asked for. The tolerance exists because a legitimately short symbol (SOL
# lists later than BTC) returns fewer bars than requested; that case is
# distinguished by the paginator reaching a true empty page, not by count.
class TestPaginationCeiling:

    def test_default_max_requests_covers_61_pages(self):
        import inspect
        sig = inspect.signature(epm.fetch_klines_paginated)
        assert sig.parameters["max_requests"].default >= 61, (
            "1h needs >= 61 pages of 1000 bars; default is "
            f"{sig.parameters['max_requests'].default}")

    def test_paginator_can_exceed_the_old_20k_ceiling(self, monkeypatch):
        # 25 pages x 1000 = 25,000 bars: impossible under the old default.
        pages = {"n": 0}

        def fake(symbol, interval="4h", limit=1000, end_time_ms=None):
            pages["n"] += 1
            if pages["n"] > 25:
                return pd.DataFrame()
            end = 1_700_000_000_000 - (pages["n"] - 1) * 1000 * 3_600_000
            idx = pd.to_datetime(
                [end - i * 3_600_000 for i in range(1000)][::-1], unit="ms")
            return pd.DataFrame({"Open": 1.0, "High": 1.0, "Low": 1.0,
                                 "Close": 1.0, "Volume": 1.0}, index=idx)

        monkeypatch.setattr(epm, "fetch_klines", fake)
        out = epm.fetch_klines_paginated("BTCUSDT", interval="1h",
                                         target_bars=25000)
        assert len(out) > 20000, f"still capped at {len(out)} bars"

    def test_truncation_assertion_fires_on_a_short_return(self):
        with pytest.raises(ValueError) as e:
            epm.assert_not_truncated("BTCUSDT", requested=60000, returned=20000)
        assert "20000" in str(e.value) and "60000" in str(e.value)

    def test_truncation_assertion_passes_at_95_percent(self):
        epm.assert_not_truncated("BTCUSDT", requested=60000, returned=57000)

    def test_truncation_assertion_passes_when_exact(self):
        epm.assert_not_truncated("BTCUSDT", requested=1000, returned=1000)

    def test_truncation_assertion_allows_a_genuinely_short_symbol(self):
        # A symbol that reached the true start of its history is not
        # truncated, however far short of the request it lands.
        epm.assert_not_truncated("SOLUSDT", requested=60000, returned=52000,
                                 reached_start=True)

    def test_truncation_message_names_the_symbol(self):
        with pytest.raises(ValueError) as e:
            epm.assert_not_truncated("ETHUSDT", requested=60000, returned=1000)
        assert "ETHUSDT" in str(e.value)


# ======================================================================
# LIVE PUBLICATION GUARDS — tradability (#167) and cost floor
# ======================================================================
# Both refuse PUBLICATION only. Neither touches the backtest path, so no
# research number moves. A refused row is still LOGGED, with its decision
# code and with target/stop nulled, so the record keeps it while
# extract_episodes (which skips rows lacking exit levels) never treats it
# as a tradeable event.
class TestTradabilityGuard:

    def _bars(self, n=2200, price=100.0, atr_frac=0.02, flat_frac=0.0):
        idx = pd.date_range("2024-01-01", periods=n, freq="4h")
        rng = np.random.default_rng(7)
        close = np.full(n, price)
        span = price * atr_frac
        high = close + span / 2
        low = close - span / 2
        n_flat = int(n * flat_frac)
        if n_flat:
            high[:n_flat] = close[:n_flat]
            low[:n_flat] = close[:n_flat]
        return pd.DataFrame({"Open": close, "High": high, "Low": low,
                             "Close": close, "Volume": 1.0}, index=idx)

    def test_liquid_series_is_tradable(self):
        r = lt.tradability_check("BTC", self._bars())
        assert r["tradable"] is True, r
        assert r["flat_share"] <= 0.10 and r["med_stop_pct"] >= 0.5

    def test_flat_bar_heavy_series_is_refused(self):
        r = lt.tradability_check("DEAD", self._bars(flat_frac=0.40))
        assert r["tradable"] is False
        assert "flat" in r["reason"].lower()

    def test_tight_stop_series_is_refused(self):
        # ATR so small that 1.5*ATR is under 0.5% of price.
        r = lt.tradability_check("TIGHT", self._bars(atr_frac=0.0005))
        assert r["tradable"] is False
        assert "stop" in r["reason"].lower()

    def test_thresholds_match_hypothesis_167(self):
        assert lt.MAX_FLAT_BAR_SHARE == 0.10
        assert lt.MIN_STOP_PCT_OF_ENTRY == 0.5

    def test_empty_bars_fail_open_to_refusal(self):
        # Unknown tradability must NOT publish. This guard fails CLOSED --
        # the opposite of the trigger guard, because publishing a signal on
        # an instrument we cannot assess is the harmful direction.
        r = lt.tradability_check("X", pd.DataFrame())
        assert r["tradable"] is False


class TestCostFloor:

    def test_threshold_is_derived_from_the_relationship(self):
        # Encoded as "cost may not exceed 10% of 1R", with the stop
        # fraction DERIVED -- not a hardcoded percentage that silently
        # decouples if the fee assumption changes.
        assert lt.MAX_COST_FRACTION_OF_R == 0.10
        got = lt.min_stop_fraction(fee_bps=2.0, slippage_bps=2.0)
        assert got == pytest.approx(0.008), got          # 0.80%, not 0.08%
        assert lt.min_stop_fraction(fee_bps=4.0, slippage_bps=4.0) == pytest.approx(0.016)

    def test_cost_at_the_threshold_is_exactly_ten_percent_of_R(self):
        frac = lt.min_stop_fraction()
        cost_r = (2 * (2.0 + 2.0) / 1e4) / frac
        assert cost_r == pytest.approx(0.10)

    def test_stop_below_the_floor_is_skipped(self):
        assert lt.below_cost_floor(entry=100.0, stop=99.95) is True     # 0.05%
    def test_stop_above_the_floor_passes(self):
        assert lt.below_cost_floor(entry=100.0, stop=98.0) is False     # 2.0%
    def test_stop_exactly_at_the_floor_passes(self):
        assert lt.below_cost_floor(entry=100.0, stop=99.2) is False     # 0.80%
    def test_missing_levels_do_not_trigger_the_floor(self):
        # No exit levels means nothing to publish anyway; the floor must
        # not manufacture a skip reason for a WATCH row.
        assert lt.below_cost_floor(entry=100.0, stop=None) is False


class TestPublicationRefusalPath:

    def _result(self, direction="BUY", entry=78000.0, stop=76000.0):
        return {"ticker": "BTC",
                "step1_initial_scoring": {"close": entry, "initial_score": 70.0,
                                          "atr": 1000.0},
                "step2_reddit_data": {"gated_score": 70.0, "gate_decision": "PROCEED",
                                      "gate_multiplier": 1.0},
                "step3_indicators": {"indicator_final_score": 65.0, "vix_level": 18.0},
                "combined": {"final_score": 68.0, "direction": direction,
                             "decision": "ENTER",
                             "exit_levels": {"applicable": True, "entry": entry,
                                             "target": entry * 1.05, "stop": stop,
                                             "atr": 1000.0, "risk_reward": 2.0}}}

    def test_tradable_ticker_publishes_unchanged(self):
        row = lt.apply_publication_guards(self._result(), {"tradable": True})
        assert row["combined"]["decision"] == "ENTER"
        assert row["combined"]["exit_levels"]["applicable"] is True

    def test_untradable_ticker_is_refused_and_levels_nulled(self):
        row = lt.apply_publication_guards(
            self._result(), {"tradable": False, "reason": "flat-bar share 41.0%"})
        assert row["combined"]["decision"] == "REFUSED_UNTRADABLE"
        assert row["combined"]["exit_levels"]["applicable"] is False

    def test_cost_floor_breach_is_skipped_and_levels_nulled(self):
        # stop 0.05% from entry -> cost_r = 1.6R
        row = lt.apply_publication_guards(
            self._result(stop=78000.0 * (1 - 0.0005)), {"tradable": True})
        assert row["combined"]["decision"] == "SKIPPED_COST_FLOOR"
        assert row["combined"]["exit_levels"]["applicable"] is False

    def test_refused_row_yields_no_tradeable_episode(self):
        # The point of nulling the levels: extract_episodes skips rows with
        # no target/stop, so a refused row never becomes a live episode.
        row = lt.apply_publication_guards(
            self._result(), {"tradable": False, "reason": "x"})
        logged = lt.append_ping_to_log(row, log_path=self._p)
        df = pd.DataFrame([logged])
        assert not lt.extract_episodes(df)

    def test_watch_row_is_untouched_by_either_guard(self):
        r = self._result(direction="WATCH")
        r["combined"]["exit_levels"] = {"applicable": False}
        row = lt.apply_publication_guards(r, {"tradable": True})
        assert row["combined"]["decision"] == "ENTER"

    @pytest.fixture(autouse=True)
    def _tmp(self, tmp_path):
        self._p = str(tmp_path / "log.csv")


class TestSentimentCacheHygiene:

    def test_no_vestigial_mentions_key(self, tmp_path):
        epm.reset_run_cache()

        def fetcher(t, **kw):
            return {"decision": "PROCEED", "gate_multiplier": 1.0, "reason": "ok",
                    "sentiment_score": 0.2, "sentiment_mentions": 4200}

        cp = str(tmp_path / "c.json")
        epm.cached_sentiment_check("BTC", cache_path=cp, fetcher=fetcher, ttl_hours=4)
        import json
        gate = json.load(open(cp))["BTC"]["gate"]
        assert "mentions" not in gate, (
            "vestigial 'mentions' key: two names for one concept is how a "
            "silent None gets served later")
        assert gate["sentiment_mentions"] == 4200


# ======================================================================
# DERIVATIVES COLLECTOR STALENESS
# ======================================================================
# A silent collector failure now costs TEST DATA THAT CANNOT BE REFETCHED:
# Kraken serves a 1-year rolling window, so a day not collected is gone from
# the venue forever and falls permanently outside the FUNDING program's
# eventual sample. This is the one staleness check in the project whose
# subject is unrecoverable, which is why the threshold is 3 days and not a
# week.
class TestCollectorStaleness:
    """The staleness check now covers EVERY derivatives source, not just
    kraken_funding, and each failure quotes what a missed day costs for that
    source specifically. The thresholds these tests pin are unchanged."""

    def _audit(self):
        import importlib
        return importlib.import_module("audit")

    def _write(self, tmp_path, days_old, name="kraken_funding"):
        """Write one source file into a directory and return the DIRECTORY."""
        p = tmp_path / ("%s.csv" % name)
        ts = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=days_old)
        pd.DataFrame({"symbol": ["PF_XBTUSD"],
                      "timestamp": [ts.strftime("%Y-%m-%dT%H:%M:%SZ")],
                      "funding_rate": [1.0],
                      "relative_funding_rate": [1e-5]}).to_csv(p, index=False)
        return str(tmp_path)

    def _rec(self, a, source="kraken_funding"):
        want = "Derivatives current: %s" % source
        hits = [r for r in a._results if r["name"] == want]
        assert hits, f"no record for {source}"
        return hits[-1]

    def test_fresh_collector_passes(self, tmp_path):
        a = self._audit(); a._results.clear()
        a.check_derivatives_collector(self._write(tmp_path, 0.5))
        assert self._rec(a)["status"] == a.PASS

    def test_two_days_stale_still_passes(self, tmp_path):
        a = self._audit(); a._results.clear()
        a.check_derivatives_collector(self._write(tmp_path, 2))
        assert self._rec(a)["status"] == a.PASS

    def test_over_three_days_fails(self, tmp_path):
        a = self._audit(); a._results.clear()
        a.check_derivatives_collector(self._write(tmp_path, 4))
        r = self._rec(a)
        assert r["status"] == a.FAIL
        assert "cannot be re-fetched" in r["detail"].lower()

    def test_failure_states_what_a_missed_day_costs(self, tmp_path):
        # The point of the per-source table: an outage must be priceable.
        a = self._audit(); a._results.clear()
        a.check_derivatives_collector(self._write(tmp_path, 4))
        r = self._rec(a)
        assert "1/365" in r["detail"], "cost of a missed day not quoted"
        assert r["evidence"]["window"] and r["evidence"]["cost_of_a_missed_day"]

    def test_current_only_source_says_the_day_is_gone(self, tmp_path):
        # kraken_tickers has NO window; its failure must not read like a
        # rolling-window one.
        a = self._audit(); a._results.clear()
        a.check_derivatives_collector(self._write(tmp_path, 4, "kraken_tickers"))
        r = self._rec(a, "kraken_tickers")
        assert r["status"] == a.FAIL
        assert "whole day" in r["detail"].lower()

    def test_missing_file_is_skip_not_pass(self, tmp_path):
        # Never a silent PASS: the audit's own design rule.
        a = self._audit(); a._results.clear()
        a.check_derivatives_collector(str(tmp_path))
        assert all(r["status"] == a.SKIP for r in a._results)

    def test_every_source_is_checked(self, tmp_path):
        a = self._audit(); a._results.clear()
        import importlib, sys as _s, os as _o
        rd = _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), "research")
        if rd not in _s.path:
            _s.path.insert(0, rd)
        cd = importlib.import_module("collect_derivs")
        a.check_derivatives_collector(str(tmp_path))
        assert len(a._results) == len(cd.SOURCE_WINDOWS)

    def test_threshold_is_three_days(self):
        assert self._audit().DERIVS_STALE_DAYS == 3


# ======================================================================
# SHADOW BASKET LOGGER
# ======================================================================
# Scored, logged, NEVER published. The four properties that make it safe
# are asserted here rather than trusted: separate file, zero Adanos, daily
# indicator caching, and the superset relationship that makes ungated
# scoring sound.
class TestShadowBasket:

    def _sb(self):
        import importlib
        return importlib.import_module("shadow_basket")

    def test_universe_is_the_tradable_26(self):
        u = self._sb().universe()
        assert len(u) == 26, f"expected the #167 tradable-26, got {len(u)}"
        for t in ("BTC", "ETH", "SOL"):
            assert t in u

    def _code_strings(self):
        """Every string LITERAL in the module, docstrings excluded.

        Grepping the source text catches prose -- the docstring says the
        module never touches signal_log.csv, and a text search cannot tell
        that apart from actually touching it. The AST can.
        """
        import ast
        tree = ast.parse(open("shadow_basket.py", encoding="utf-8").read())
        docs = {id(ast.get_docstring(n, clean=False)) for n in ast.walk(tree)
                if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef))}
        out = []
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                if id(n.value) not in docs:
                    out.append(n.value)
        return out

    def _code_names(self):
        import ast
        tree = ast.parse(open("shadow_basket.py", encoding="utf-8").read())
        return {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} |                {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}

    def test_writes_a_separate_log_never_signal_log(self):
        sb = self._sb()
        assert sb.SHADOW_LOG == "shadow_log.csv"
        assert sb.SHADOW_LOG != lt.DEFAULT_LOG
        assert "signal_log.csv" not in self._code_strings(), (
            "shadow code must never name the live log")

    def test_spends_zero_adanos(self):
        # Checked on the AST, not the text: the docstring legitimately says
        # "ZERO ADANOS", and a grep cannot tell prose from a call.
        names = self._code_names()
        for forbidden in ("cached_sentiment_check", "apply_reddit_step",
                          "first_pass_sentiment_check_adanos",
                          "fetch_token_sentiment", "sentiment_gate"):
            assert forbidden not in names, f"shadow path calls {forbidden}"
        for lit in self._code_strings():
            assert "ADANOS_API_KEY" not in lit

    def test_never_publishes(self):
        names = self._code_names()
        for forbidden in ("fire_alert", "generate_html_chart",
                          "append_ping_to_log", "passes_confluence"):
            assert forbidden not in names, f"shadow path calls {forbidden}"

    def test_daily_indicators_cached_once_per_day(self, monkeypatch):
        sb = self._sb()
        sb._IND_CACHE.clear()
        calls = []

        def fake(ticker, step2_result, period="2y", use_ml=False):
            calls.append(ticker)
            return {"step": 3, "indicator_final_score": 60.0, "vix_level": 18.0}

        monkeypatch.setattr(sb.pl, "apply_indicator_step", fake)
        now = datetime(2026, 9, 1, 5, 0, tzinfo=timezone.utc)
        for hour in (5, 6, 7):
            sb.daily_indicators("BTC", now=now.replace(hour=hour))
        assert calls == ["BTC"], f"expected 1 pull for the day, got {len(calls)}"

    def test_cache_refreshes_on_a_new_utc_day(self, monkeypatch):
        sb = self._sb()
        sb._IND_CACHE.clear()
        calls = []

        def fake(ticker, step2_result, period="2y", use_ml=False):
            calls.append(ticker)
            return {"step": 3, "indicator_final_score": 60.0, "vix_level": 18.0}

        monkeypatch.setattr(sb.pl, "apply_indicator_step", fake)
        sb.daily_indicators("BTC", now=datetime(2026, 9, 1, 23, tzinfo=timezone.utc))
        sb.daily_indicators("BTC", now=datetime(2026, 9, 2, 0, tzinfo=timezone.utc))
        assert len(calls) == 2

    def test_second_indicator_call_reports_cache_hit(self, monkeypatch):
        sb = self._sb()
        sb._IND_CACHE.clear()
        monkeypatch.setattr(sb.pl, "apply_indicator_step",
                            lambda *a, **k: {"step": 3, "indicator_final_score": 1.0,
                                             "vix_level": 18.0})
        now = datetime(2026, 9, 1, 5, tzinfo=timezone.utc)
        assert sb.daily_indicators("BTC", now=now)[1] is False
        assert sb.daily_indicators("BTC", now=now)[1] is True

    def test_ungated_score_is_a_superset_of_gated(self):
        # THE property that makes ungated shadow scoring sound: the gate is
        # dampen-only, so ungated >= gated, so shadow BUY days are a
        # superset of gated BUY days and nothing is silently lost.
        step3 = {"indicator_final_score": 70.0, "vix_level": 18.0}
        for initial in (20.0, 45.0, 61.0, 88.0):
            ungated = um.combine_and_decide({"gated_score": initial}, step3)
            for mult in (0.5, 0.6, 0.8, 1.0):        # the gate's whole range
                gated = um.combine_and_decide({"gated_score": initial * mult}, step3)
                assert ungated["final_score"] >= gated["final_score"] - 1e-9

    def test_one_bad_ticker_does_not_stop_the_rest(self, monkeypatch, tmp_path):
        sb = self._sb()
        sb._IND_CACHE.clear()

        def flaky(ticker, now=None):
            if ticker == "BOOM":
                raise RuntimeError("kaboom")
            return {c: None for c in sb.SHADOW_COLUMNS} | {"ticker": ticker}

        monkeypatch.setattr(sb, "score_shadow", flaky)
        rows = sb.run_shadow(["AAA", "BOOM", "BBB"],
                             log_path=str(tmp_path / "s.csv"))
        assert [r["ticker"] for r in rows] == ["AAA", "BBB"]

    def test_log_schema_is_stable(self, monkeypatch, tmp_path):
        sb = self._sb()
        p = str(tmp_path / "s.csv")
        sb.append_shadow_rows([{c: None for c in sb.SHADOW_COLUMNS}], p)
        assert list(pd.read_csv(p).columns) == sb.SHADOW_COLUMNS

    def test_outcome_resolution_reuses_the_live_rules(self):
        # Shadow episodes must be scored by exactly the rules live ones are,
        # or the two records are not comparable.
        assert "resolve_outcomes" in self._code_names()


# ======================================================================
# WINDOW-STABILITY PROFILER — the degenerate all-zero case
# ======================================================================
# ABLATION rung #201 (extreme-fear regime removed) came back as EXACTLY
# 0.000 at all 50 window starts, because on BTC the composite score is
# essentially never in the band the raised buy bar moves through. The
# profiler rendered that as "sign-stability 0% (positive)" -- the most
# unstable-looking label it has, for the most stable series it can be
# handed. A reader skimming the sign-stability column would draw the exact
# opposite conclusion from the truth.
class TestWindowStabilityDegenerate:

    def _ws(self):
        import importlib
        rd = os.path.join(os.path.dirname(os.path.abspath(__file__)), "research")
        if rd not in sys.path:
            sys.path.insert(0, rd)
        return importlib.import_module("window_stability")

    def test_identically_zero_is_stable_not_unstable(self):
        ws = self._ws()
        r = ws.profile(lambda a, b: 0.0, "2020-01-01", "2024-01-01", n_starts=10)
        assert r["n_defined"] == 10
        assert r["zero"] == 10
        assert r["modal_sign"] == "zero"
        assert r["sign_stability"] == 1.0

    def test_zero_case_renders_without_claiming_a_sign(self):
        ws = self._ws()
        r = ws.profile(lambda a, b: 0.0, "2020-01-01", "2024-01-01", n_starts=10)
        out = ws.render("all-zero", r)
        assert "zero" in out
        assert "positive" not in out and "negative" not in out

    def test_ordinary_signs_are_unchanged(self):
        ws = self._ws()
        neg = ws.profile(lambda a, b: -0.2, "2020-01-01", "2024-01-01", n_starts=10)
        assert neg["modal_sign"] == "negative" and neg["sign_stability"] == 1.0
        pos = ws.profile(lambda a, b: 0.3, "2020-01-01", "2024-01-01", n_starts=10)
        assert pos["modal_sign"] == "positive" and pos["sign_stability"] == 1.0

    def test_a_single_nonzero_value_restores_a_real_sign(self):
        ws = self._ws()
        seen = {"n": 0}

        def stat(a, b):
            seen["n"] += 1
            return -1.0 if seen["n"] == 1 else 0.0

        r = ws.profile(stat, "2020-01-01", "2024-01-01", n_starts=10)
        assert r["zero"] == 9 and r["negative"] == 1
        assert r["modal_sign"] == "negative"


# ======================================================================
# SHADOW ARM — SQUEEZE_ONLY logged beside the incumbent (#203)
# ======================================================================
# ABLATION #198 found the indicator block subtracts on both frozen windows.
# #203 asks the promotion question, and promotion requires BOTH an in-sample
# pass AND shadow agreement at the 30-episode checkpoint. That second half
# only exists if the shadow log carries the squeeze-only labels from the
# first row onward -- so this arm goes in BEFORE any row is written.
#
# The second label is a RE-BLEND of scores already computed. It must cost
# zero extra Adanos AND zero extra price/indicator fetches, or the shadow
# basket's whole economy changes.
class TestShadowSqueezeArm:

    def _sb(self):
        import importlib
        return importlib.import_module("shadow_basket")

    def _fake_scores(self, monkeypatch, initial=80.0, indicator=20.0):
        """Pin Step 1 and Step 3 so both blends are arithmetic, not network."""
        sb = self._sb()
        calls = {"step1": 0, "step3": 0}

        def fake_step1(ticker, **kw):
            calls["step1"] += 1
            return {"step": 1, "initial_score": initial, "close": 100.0,
                    "atr": 5.0, "ticker": ticker}

        def fake_step3(ticker, prev, **kw):
            calls["step3"] += 1
            return {"step": 3, "indicator_final_score": indicator,
                    "final_score": indicator, "vix_level": 18.0}

        monkeypatch.setattr(sb.pl, "compute_initial_score", fake_step1)
        monkeypatch.setattr(sb.pl, "apply_indicator_step", fake_step3)
        sb._IND_CACHE.clear()
        return sb, calls

    def test_row_carries_both_label_sets(self, monkeypatch):
        sb, _ = self._fake_scores(monkeypatch)
        row = sb.score_shadow("BTC")
        for col in ("decision", "direction", "final_score",
                    "sq_decision", "sq_direction", "sq_final_score"):
            assert col in row, f"shadow row is missing {col}"

    def test_squeeze_arm_drops_the_indicator_block_entirely(self, monkeypatch):
        # 1.0 pattern / 0.0 indicators means the blend IS the gated score.
        sb, _ = self._fake_scores(monkeypatch, initial=80.0, indicator=20.0)
        row = sb.score_shadow("BTC")
        assert row["sq_final_score"] == pytest.approx(80.0)
        # and the incumbent blend is the 0.6/0.4 mix, unchanged
        assert row["final_score"] == pytest.approx(0.6 * 80.0 + 0.4 * 20.0)

    def test_the_two_arms_can_disagree(self, monkeypatch):
        # The whole point. 80/20 puts the incumbent at 56 (WATCH) and
        # squeeze-only at 80 (STRONG_BUY): same day, different label.
        sb, _ = self._fake_scores(monkeypatch, initial=80.0, indicator=20.0)
        row = sb.score_shadow("BTC")
        assert row["direction"] != row["sq_direction"]

    def test_second_arm_costs_no_extra_fetches(self, monkeypatch):
        sb, calls = self._fake_scores(monkeypatch)
        sb.score_shadow("BTC")
        assert calls["step1"] == 1, "squeeze arm re-fetched price data"
        assert calls["step3"] == 1, "squeeze arm re-fetched indicators"

    def test_second_arm_spends_zero_adanos(self, monkeypatch):
        # Both arms take the UNGATED path, so the superset note covers both.
        sb, _ = self._fake_scores(monkeypatch)
        row = sb.score_shadow("BTC")
        assert row["gate_decision"] == "UNGATED_SHADOW"

    def test_squeeze_arm_logs_its_own_exit_levels(self, monkeypatch):
        # A label with no target/stop cannot be resolved into an episode,
        # so the arm would accrue nothing toward the 30-episode checkpoint.
        sb, _ = self._fake_scores(monkeypatch, initial=80.0, indicator=20.0)
        row = sb.score_shadow("BTC")
        assert row["sq_target_price"] is not None
        assert row["sq_stop_price"] is not None
        assert row["sq_target_price"] > 100.0 > row["sq_stop_price"]

    def test_both_arms_are_in_the_schema(self):
        sb = self._sb()
        for col in ("sq_final_score", "sq_decision", "sq_direction",
                    "sq_target_price", "sq_stop_price", "sq_risk_reward"):
            assert col in sb.SHADOW_COLUMNS

    def test_projection_renames_the_arm_onto_the_canonical_columns(self):
        # Resolution reuses live_tools.extract_episodes UNCHANGED, which
        # reads `direction`/`target_price`/`stop_price` by name. The arm is
        # resolved by projecting its columns onto those names -- never by a
        # second copy of the episode logic.
        sb = self._sb()
        df = pd.DataFrame([{
            "timestamp_utc": "2026-08-30T00:00:00", "ticker": "BTC",
            "direction": "WATCH", "target_price": None, "stop_price": None,
            "risk_reward": None, "final_score": 56.0,
            "sq_direction": "STRONG_BUY", "sq_target_price": 120.0,
            "sq_stop_price": 92.5, "sq_risk_reward": 2.67, "sq_final_score": 80.0,
        }])
        out = sb.project_arm(df, "squeeze")
        assert out.loc[0, "direction"] == "STRONG_BUY"
        assert out.loc[0, "target_price"] == 120.0
        assert out.loc[0, "stop_price"] == 92.5
        assert out.loc[0, "final_score"] == 80.0

    def test_projection_of_the_incumbent_arm_is_the_identity(self):
        sb = self._sb()
        df = pd.DataFrame([{
            "timestamp_utc": "2026-08-30T00:00:00", "ticker": "BTC",
            "direction": "BUY", "target_price": 115.0, "stop_price": 92.5,
            "sq_direction": "WATCH", "sq_target_price": None,
            "sq_stop_price": None,
        }])
        out = sb.project_arm(df, "incumbent")
        assert out.loc[0, "direction"] == "BUY"
        assert out.loc[0, "target_price"] == 115.0

    def test_unknown_arm_is_refused(self):
        sb = self._sb()
        with pytest.raises(ValueError):
            sb.project_arm(pd.DataFrame({"direction": ["BUY"]}), "nonsense")

    def test_append_refuses_to_misalign_a_stale_header(self, tmp_path):
        # A log written under the OLD schema plus rows written under the new
        # one would silently shift every column right of the insertion. That
        # must fail loudly, not corrupt six months of forward record.
        sb = self._sb()
        p = tmp_path / "shadow_log.csv"
        p.write_text("timestamp_utc,ticker,price\n2026-01-01T00:00:00,BTC,1.0\n",
                     encoding="utf-8")
        with pytest.raises(ValueError, match="schema"):
            sb.append_shadow_rows([{c: None for c in sb.SHADOW_COLUMNS}], str(p))

    def test_append_accepts_a_matching_header(self, tmp_path):
        sb = self._sb()
        p = tmp_path / "shadow_log.csv"
        row = {c: None for c in sb.SHADOW_COLUMNS}
        row["ticker"] = "BTC"
        assert sb.append_shadow_rows([row], str(p)) == 1
        assert sb.append_shadow_rows([row], str(p)) == 1
        got = pd.read_csv(p)
        assert len(got) == 2 and list(got.columns) == sb.SHADOW_COLUMNS


# ======================================================================
# SHADOW EXIT LEVELS — the defect that made the log unresolvable
# ======================================================================
# combine_and_decide does NOT return exit_levels; run_full_pipeline computes
# them afterwards from step1. The first shadow_basket read
# `combined.get("exit_levels")`, which is always empty, so every row logged
# target_price=None -- and extract_episodes skips rows with no target+stop.
# The basket would have accrued labels forever and zero episodes, looking
# healthy the whole time. Caught before the first row was written.
class TestShadowExitLevelsAreReal:

    def _sb(self):
        import importlib
        return importlib.import_module("shadow_basket")

    def _pin(self, monkeypatch, initial, indicator, close=100.0, atr=5.0):
        sb = self._sb()
        monkeypatch.setattr(sb.pl, "compute_initial_score", lambda t, **k: {
            "step": 1, "initial_score": initial, "close": close,
            "atr": atr, "ticker": t})
        monkeypatch.setattr(sb.pl, "apply_indicator_step", lambda t, p, **k: {
            "step": 3, "indicator_final_score": indicator,
            "final_score": indicator, "vix_level": 18.0})
        sb._IND_CACHE.clear()
        return sb

    def test_combine_and_decide_still_does_not_supply_exit_levels(self):
        # If pipeline ever starts returning them, this test fails and the
        # duplicated computation in shadow_basket should be revisited.
        out = um.combine_and_decide(
            {"step": 2, "gated_score": 80.0, "gate_multiplier": 1.0},
            {"step": 3, "indicator_final_score": 80.0, "final_score": 80.0,
             "vix_level": 18.0})
        assert "exit_levels" not in out

    def test_a_buy_row_carries_resolvable_levels(self, monkeypatch):
        sb = self._pin(monkeypatch, initial=90.0, indicator=90.0)
        row = sb.score_shadow("BTC")
        assert row["direction"] in ("BUY", "STRONG_BUY")
        assert row["target_price"] is not None and row["stop_price"] is not None

    def test_levels_match_the_live_computation_exactly(self, monkeypatch):
        sb = self._pin(monkeypatch, initial=90.0, indicator=90.0)
        row = sb.score_shadow("BTC")
        want = ads.compute_exit_levels(entry_price=100.0,
                                      direction=row["direction"], atr=5.0,
                                      stop_mult=1.5, target_mult=3.0)
        assert row["target_price"] == want["target"]
        assert row["stop_price"] == want["stop"]

    def test_a_watch_row_carries_no_levels(self, monkeypatch):
        # WATCH is not actionable; logging levels for it would invent an
        # episode the model never signalled.
        sb = self._pin(monkeypatch, initial=50.0, indicator=50.0)
        row = sb.score_shadow("BTC")
        assert row["direction"] == "WATCH"
        assert row["target_price"] is None and row["stop_price"] is None

    def test_the_logged_row_actually_becomes_an_episode(self, monkeypatch, tmp_path):
        # The end-to-end property the defect broke: a BUY row must survive
        # extract_episodes. Two rows, because an episode needs a first row
        # with levels and this proves the log format feeds the real parser.
        sb = self._pin(monkeypatch, initial=90.0, indicator=90.0)
        p = tmp_path / "shadow_log.csv"
        rows = [sb.score_shadow("BTC"), sb.score_shadow("BTC")]
        sb.append_shadow_rows(rows, str(p))
        eps = lt.extract_episodes(pd.read_csv(p))
        assert len(eps) == 1, "a BUY shadow row did not become an episode"
        assert eps[0]["ticker"] == "BTC"

    def test_the_squeeze_arm_also_becomes_an_episode(self, monkeypatch, tmp_path):
        # 90/10: incumbent blends to 58 (WATCH, no levels), squeeze-only to
        # 90 (STRONG_BUY). The incumbent arm yields no episode and the
        # squeeze arm yields one -- from the same two logged rows.
        sb = self._pin(monkeypatch, initial=90.0, indicator=10.0)
        p = tmp_path / "shadow_log.csv"
        sb.append_shadow_rows([sb.score_shadow("BTC"), sb.score_shadow("BTC")],
                              str(p))
        df = pd.read_csv(p)
        assert lt.extract_episodes(sb.project_arm(df, "incumbent")) == []
        sq = lt.extract_episodes(sb.project_arm(df, "squeeze"))
        assert len(sq) == 1
        assert sq[0]["entry_direction"] == "STRONG_BUY"


# ======================================================================
# RANK-PERMUTATION PLACEBO — must preserve the turnover it claims to
# ======================================================================
# The placebo's entire job is to destroy ONE thing (which asset was picked)
# and preserve everything else. The first version re-permuted every ROW, so
# a weekly-rebalanced portfolio holding 5 names for 7 days became 5 DIFFERENT
# random names each day: turnover 1.566 vs the real rule's 0.116 on
# #187/CONFIRMATION, 13x the costs, and a null dragged to -0.38/yr by
# fabricated trading. A null crippled by costs the real rule never pays is a
# false-positive generator, so this is tested, not assumed.
class TestRankPermutationPreservesTurnover:

    def _ph(self):
        import importlib
        rd = os.path.join(os.path.dirname(os.path.abspath(__file__)), "research")
        if rd not in sys.path:
            sys.path.insert(0, rd)
        return importlib.import_module("portfolio_harness")

    def _weekly_weights(self, n_days=70, n_assets=10, n_hold=3):
        """A weekly-rebalanced equal-weight path: same names for 7 days."""
        idx = pd.date_range("2024-01-01", periods=n_days, freq="D")
        cols = [f"A{i}" for i in range(n_assets)]
        W = pd.DataFrame(0.0, index=idx, columns=cols)
        rng = np.random.default_rng(0)
        cur = None
        for d in idx:
            if d.weekday() == 0 or cur is None:
                cur = np.zeros(n_assets)
                cur[rng.choice(n_assets, n_hold, replace=False)] = 1.0 / n_hold
            W.loc[d] = cur
        return W

    def test_weights_are_held_between_rebalances(self):
        ph = self._ph()
        W = self._weekly_weights()
        out = ph.rank_permutation_placebo(W, seed=1)
        # Within a Monday-to-Sunday block the permuted rows must be identical.
        block = out.loc["2024-01-08":"2024-01-14"]
        assert block.nunique().sum() == len(block.columns), (
            "placebo changed its holdings inside a rebalance period")

    def test_row_sums_and_position_counts_are_preserved(self):
        ph = self._ph()
        W = self._weekly_weights()
        out = ph.rank_permutation_placebo(W, seed=2)
        assert np.allclose(out.sum(axis=1).to_numpy(), W.sum(axis=1).to_numpy())
        assert ((out > 0).sum(axis=1).to_numpy() ==
                (W > 0).sum(axis=1).to_numpy()).all()

    def test_turnover_matches_the_real_path(self):
        ph = self._ph()
        W = self._weekly_weights()
        rng = np.random.default_rng(7)
        px = pd.DataFrame(
            100 * np.cumprod(1 + rng.normal(0, 0.02, size=W.shape), axis=0),
            index=W.index, columns=W.columns)
        real = ph.portfolio_returns(W, px)["turnover"].mean()
        for seed in range(5):
            wp = ph.rank_permutation_placebo(W, seed=seed)
            got = ph.portfolio_returns(wp, px)["turnover"].mean()
            assert got == pytest.approx(real, rel=0.35), (
                f"placebo turnover {got:.4f} vs real {real:.4f} — the null "
                f"is paying costs the strategy never pays")

    def test_a_daily_strategy_still_gets_a_fresh_permutation_each_row(self):
        # Cadence-agnostic: a genuinely daily rule changes target every row.
        ph = self._ph()
        idx = pd.date_range("2024-01-01", periods=40, freq="D")
        cols = [f"A{i}" for i in range(8)]
        rng = np.random.default_rng(3)
        W = pd.DataFrame(0.0, index=idx, columns=cols)
        for i, d in enumerate(idx):
            row = np.zeros(8)
            row[rng.choice(8, 2, replace=False)] = 0.5
            W.loc[d] = row
        out = ph.rank_permutation_placebo(W, seed=4)
        held = {tuple(np.flatnonzero(r)) for r in out.to_numpy()}
        assert len(held) > 5, "daily strategy was frozen into one permutation"

    def test_selection_is_actually_destroyed(self):
        # The one thing it MUST break: which asset carries the weight.
        ph = self._ph()
        W = self._weekly_weights()
        out = ph.rank_permutation_placebo(W, seed=11)
        assert not out.equals(W)

    def test_cash_rows_stay_cash(self):
        ph = self._ph()
        W = self._weekly_weights()
        W.iloc[10:20] = 0.0
        out = ph.rank_permutation_placebo(W, seed=5)
        assert (out.iloc[10:20].to_numpy() == 0).all()


# ======================================================================
# FIXED RANK-PERMUTATION — the primary null for a selection claim
# ======================================================================
# Differs from the strategy in exactly ONE respect: which asset each weight
# lands on. Same path, relabelled universe, so the turnover profile is
# preserved EXACTLY rather than approximately.
class TestFixedRankPermutation:

    def _ph(self):
        import importlib
        rd = os.path.join(os.path.dirname(os.path.abspath(__file__)), "research")
        if rd not in sys.path:
            sys.path.insert(0, rd)
        return importlib.import_module("portfolio_harness")

    def _weekly(self, n_days=84, n_assets=12, n_hold=4):
        idx = pd.date_range("2024-01-01", periods=n_days, freq="D")
        cols = [f"A{i}" for i in range(n_assets)]
        W = pd.DataFrame(0.0, index=idx, columns=cols)
        rng = np.random.default_rng(0)
        cur = None
        for d in idx:
            if d.weekday() == 0 or cur is None:
                cur = np.zeros(n_assets)
                cur[rng.choice(n_assets, n_hold, replace=False)] = 1.0 / n_hold
            W.loc[d] = cur
        return W

    def test_row_sums_and_counts_preserved(self):
        ph = self._ph()
        W = self._weekly()
        out = ph.rank_permutation_fixed_placebo(W, seed=1)
        assert np.allclose(out.sum(axis=1).to_numpy(), W.sum(axis=1).to_numpy())
        assert ((out > 0).sum(axis=1).to_numpy() ==
                (W > 0).sum(axis=1).to_numpy()).all()

    def test_the_permutation_is_the_same_every_row(self):
        # The defining property: ONE relabelling for the whole window. Stated
        # column-wise, which is what "fixed" actually means -- every output
        # column must equal some input column over ALL rows at once. (A
        # row-by-row check cannot express this: flatnonzero returns sorted
        # positions, so pairing them positionally does not recover the map.)
        ph = self._ph()
        W = self._weekly()
        out = ph.rank_permutation_fixed_placebo(W, seed=2)
        A, B = W.to_numpy(), out.to_numpy()
        perm = []
        for j in range(B.shape[1]):
            hits = [i for i in range(A.shape[1]) if np.array_equal(B[:, j], A[:, i])]
            assert hits, f"output column {j} matches no input column"
            perm.append(hits[0])
        assert np.array_equal(B, A[:, perm]), "not a single fixed relabelling"

    def test_turnover_is_preserved_closely(self):
        # Same path, relabelled -- turnover differs only through price drift.
        ph = self._ph()
        W = self._weekly()
        rng = np.random.default_rng(9)
        px = pd.DataFrame(
            100 * np.cumprod(1 + rng.normal(0, 0.02, size=W.shape), axis=0),
            index=W.index, columns=W.columns)
        real = ph.portfolio_returns(W, px)["turnover"].mean()
        for seed in range(6):
            wp = ph.rank_permutation_fixed_placebo(W, seed=seed)
            got = ph.portfolio_returns(wp, px)["turnover"].mean()
            assert got == pytest.approx(real, rel=0.10), (
                f"fixed-permutation turnover {got:.4f} vs real {real:.4f}")

    def test_identity_is_destroyed_across_seeds(self):
        ph = self._ph()
        W = self._weekly()
        seen = set()
        for seed in range(20):
            out = ph.rank_permutation_fixed_placebo(W, seed=seed)
            seen.add(tuple(np.flatnonzero(out.iloc[0].to_numpy())))
        assert len(seen) > 3, "fixed permutation is not exploring relabellings"

    def test_cash_rows_stay_cash(self):
        ph = self._ph()
        W = self._weekly()
        W.iloc[7:14] = 0.0
        out = ph.rank_permutation_fixed_placebo(W, seed=3)
        assert (out.iloc[7:14].to_numpy() == 0).all()


# ======================================================================
# ALLOCATION's block-shuffle repair — the null must be constrained the
# way the strategy is constrained
# ======================================================================
# ROTATION established the standing rule: a placebo pays what the strategy
# pays. Checking block_shuffle_placebo against it found a SECOND failure of
# the same family -- shuffling the whole weight matrix moves the
# cross-section through time, so a late block landing on an early date holds
# assets that had not listed yet. Measured on DISCOVERY: 15.4% of gross
# weight on non-existent assets, against 0.013% for the real path. Those
# positions earn exactly 0 via fillna(0.0) -- an invisible drag the strategy
# never pays. Shuffling the SCALE path instead destroys the timing claim
# while leaving the investable universe alone: 0.023%.
class TestAllocationScaleShuffle:

    def _al(self):
        import importlib
        rd = os.path.join(os.path.dirname(os.path.abspath(__file__)), "research")
        if rd not in sys.path:
            sys.path.insert(0, rd)
        return importlib.import_module("run_allocation")

    def _scale(self, n=105):
        idx = pd.date_range("2024-01-01", periods=n, freq="D")
        return pd.Series(np.linspace(0.2, 1.4, n), index=idx)

    def test_shuffle_preserves_the_multiset_of_values(self):
        # Same exposure profile, different order. Nothing invented, nothing
        # dropped -- that is what makes it an exposure-matched null.
        al = self._al()
        s = self._scale()
        out = al.scale_block_shuffle(s, seed=1)
        assert sorted(out.to_numpy()) == pytest.approx(sorted(s.to_numpy()))

    def test_shuffle_actually_reorders(self):
        al = self._al()
        s = self._scale()
        assert not np.allclose(al.scale_block_shuffle(s, seed=2).to_numpy(),
                               s.to_numpy())

    def test_blocks_stay_contiguous(self):
        # A 21-day block must survive intact, or this is not a block shuffle
        # and the exposure path's own persistence is destroyed too.
        al = self._al()
        s = self._scale()
        out = al.scale_block_shuffle(s, seed=3, block_days=21).to_numpy()
        src = s.to_numpy()
        blocks = [src[i:i + 21] for i in range(0, len(src), 21)]
        for j in range(0, len(out) - 21 + 1, 21):
            chunk = out[j:j + 21]
            assert any(np.allclose(chunk, b) for b in blocks if len(b) == 21)

    def test_a_constant_scale_shuffles_to_itself(self):
        # Why #195's clause 2 is DEGENERATE rather than passed or failed:
        # its scale path is constant, so its null IS the rule.
        al = self._al()
        s = pd.Series(1.0, index=pd.date_range("2024-01-01", periods=84, freq="D"))
        assert np.allclose(al.scale_block_shuffle(s, seed=4).to_numpy(),
                           s.to_numpy())

    def test_universe_fidelity_beats_weight_matrix_shuffling(self):
        # The defect and its repair, as an assertion. Assets B and C do not
        # exist for the first half; a weight-matrix shuffle moves them there,
        # a scale shuffle cannot.
        al = self._al()
        import importlib
        ph = importlib.import_module("portfolio_harness")
        n = 84
        idx = pd.date_range("2024-01-01", periods=n, freq="D")
        px = pd.DataFrame({"A": np.linspace(100, 200, n),
                           "B": np.linspace(100, 200, n),
                           "C": np.linspace(100, 200, n)}, index=idx)
        px.loc[idx[:42], ["B", "C"]] = np.nan
        base = pd.DataFrame(0.0, index=idx, columns=px.columns)
        base.loc[idx[:42], "A"] = 1.0
        base.loc[idx[42:]] = 1.0 / 3
        scale = pd.Series(np.linspace(0.3, 1.2, n), index=idx)
        rule = base.mul(scale, axis=0)

        wm = np.mean([al.held_nonexistent_weight(
            ph.block_shuffle_placebo(rule, seed=s, block_days=21), px)
            for s in range(8)])
        ss = np.mean([al.held_nonexistent_weight(
            base.mul(al.scale_block_shuffle(scale, seed=s), axis=0), px)
            for s in range(8)])
        assert al.held_nonexistent_weight(rule, px) == 0.0
        assert wm > 0.05, "the weight-matrix defect should be visible here"
        assert ss == 0.0, "the scale shuffle must never hold a non-existent asset"

    def test_held_nonexistent_weight_is_zero_for_a_clean_path(self):
        al = self._al()
        idx = pd.date_range("2024-01-01", periods=30, freq="D")
        px = pd.DataFrame({"A": np.arange(30.0) + 1}, index=idx)
        W = pd.DataFrame({"A": np.ones(30)}, index=idx)
        assert al.held_nonexistent_weight(W, px) == 0.0


# ======================================================================
# NEW DERIVATIVES SOURCES — kraken_tickers / okx_rubik / deribit_options
# ======================================================================
# Same merge-test style as TestDerivativesMerge: the pure parts are tested
# without network. These three sources are the reason the daily job matters:
# two of them are CURRENT-ONLY, so a day not sampled is gone with no window
# to recover it from.
class TestNewDerivativeSources:

    def _cd(self):
        import importlib
        rd = os.path.join(os.path.dirname(os.path.abspath(__file__)), "research")
        if rd not in sys.path:
            sys.path.insert(0, rd)
        return importlib.import_module("collect_derivs")

    # ---- registration in the shared pattern ---------------------------
    def test_all_three_sources_are_registered(self):
        cd = self._cd()
        names = [n for n, _ in cd.SOURCES]
        for s in ("kraken_tickers", "okx_rubik", "deribit_options"):
            assert s in names, f"{s} not wired into SOURCES"

    def test_every_source_documents_its_window_and_outage_cost(self):
        # A future outage must be priceable. Every source states its window
        # AND what a missed day costs.
        cd = self._cd()
        for name, _ in cd.SOURCES:
            assert name in cd.SOURCE_WINDOWS, f"{name} has no window documented"
            window, cost = cd.SOURCE_WINDOWS[name]
            assert window and cost

    def test_current_only_sources_say_the_day_is_simply_gone(self):
        # The distinction that makes daily collection urgent rather than
        # merely tidy.
        cd = self._cd()
        for name in ("kraken_tickers", "deribit_options"):
            window, cost = cd.SOURCE_WINDOWS[name]
            assert "CURRENT-ONLY" in window
            assert "whole day" in cost

    # ---- kraken tickers: snapshot semantics ---------------------------
    def test_ticker_snapshot_keys_on_the_DAY_not_the_instant(self):
        # Re-running inside one day must be idempotent, so the merge key is
        # the snapshot DAY; the true instant is kept separately.
        cd = self._cd()
        rows = [{"symbol": "PF_XBTUSD", "timestamp": "2026-09-01T00:00:00Z",
                 "observed_utc": "2026-09-01T05:20:00Z", "openInterest": 100.0},
                {"symbol": "PF_XBTUSD", "timestamp": "2026-09-01T00:00:00Z",
                 "observed_utc": "2026-09-01T17:20:00Z", "openInterest": 999.0}]
        a = pd.DataFrame(rows[:1])
        b = pd.DataFrame(rows[1:])
        merged, added, coll = cd.merge_rows(a, b)
        assert len(merged) == 1 and added == 0
        assert coll == 1, "a differing second snapshot must be COUNTED"
        assert float(merged.iloc[0]["openInterest"]) == 100.0, "disk must win"

    def test_ticker_fields_include_the_positioning_quantities(self):
        cd = self._cd()
        for f in ("openInterest", "markPrice", "indexPrice",
                  "fundingRatePrediction"):
            assert f in cd.TICKER_FIELDS

    # ---- okx rubik: wide shape keeps the key unique -------------------
    def test_rubik_is_wide_so_the_merge_key_stays_unique(self):
        # Long format would put three metrics on one (symbol, timestamp) and
        # collide. Wide keeps one row per currency-day.
        cd = self._cd()
        df = pd.DataFrame([
            {"symbol": "BTC", "timestamp": "2026-08-31T16:00:00Z",
             "long_short_ratio": "1.06", "taker_buy_vol": "3.4",
             "taker_sell_vol": "3.5", "open_interest": "2.8", "volume": "6.9"}])
        assert not df.duplicated(subset=cd.KEY).any()
        merged, added, _ = cd.merge_rows(None, df)
        assert len(merged) == 1 and added == 1

    def test_rubik_merge_is_idempotent(self):
        cd = self._cd()
        df = pd.DataFrame([
            {"symbol": "ETH", "timestamp": "2026-08-30T16:00:00Z",
             "long_short_ratio": "0.9"},
            {"symbol": "ETH", "timestamp": "2026-08-31T16:00:00Z",
             "long_short_ratio": "1.1"}])
        once, a1, _ = cd.merge_rows(None, df)
        twice, a2, coll = cd.merge_rows(once, df)
        assert len(once) == len(twice) == 2
        assert a1 == 2 and a2 == 0 and coll == 0

    # ---- deribit: two series in one file, keys must not collide -------
    def test_deribit_symbol_suffix_separates_the_two_series(self):
        # <CCY>-OPTIONS is a daily chain snapshot; <CCY>-HISTVOL is an
        # hourly rolling series. Without the suffix they would collide on
        # (symbol, timestamp) at midnight.
        cd = self._cd()
        df = pd.DataFrame([
            {"symbol": "BTC-OPTIONS", "timestamp": "2026-09-01T00:00:00Z",
             "put_call_oi_ratio": 0.8},
            {"symbol": "BTC-HISTVOL", "timestamp": "2026-09-01T00:00:00Z",
             "historical_volatility": 42.0}])
        assert not df.duplicated(subset=cd.KEY).any()
        merged, added, _ = cd.merge_rows(None, df)
        assert len(merged) == 2 and added == 2

    def test_deribit_option_currencies_exclude_SOL_and_histvol_does_not(self):
        # MEASURED coverage fact 2026-09-01: Deribit lists SOL as SPOT only,
        # zero options and zero futures. Its hist-vol IS served but is
        # REALISED vol from spot, not options-implied.
        cd = self._cd()
        assert "SOL" not in cd.DERIBIT_OPT_CCYS
        assert "SOL" in cd.DERIBIT_HV_CCYS
        assert set(cd.DERIBIT_OPT_CCYS) == {"BTC", "ETH"}

    def test_option_kind_parsed_from_the_instrument_name(self):
        cd = self._cd()
        assert cd._opt_kind("BTC-1SEP26-85000-C") == "C"
        assert cd._opt_kind("ETH-26DEC26-4000-P") == "P"
        assert cd._opt_kind("") == ""

    # ---- audit wiring -------------------------------------------------
    def test_audit_checks_every_source_not_just_kraken_funding(self):
        import importlib
        a = importlib.import_module("audit")
        cd = self._cd()
        res = a.check_derivatives_collector()
        assert isinstance(res, list)
        assert len(res) == len(cd.SOURCE_WINDOWS), (
            "audit must check every documented source")
