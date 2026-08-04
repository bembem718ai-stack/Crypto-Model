"""
verify_fixes.py — did the six fixes actually land?
==================================================

    python verify_fixes.py

DIFFERENT FROM THE OTHER TWO CHECKS, on purpose:

    test_signals.py  asks "is each function correct?"      (unit)
    verify_fixes.py  asks "is each FIX present and wired?" (acceptance)
    audit.py         asks "what is the model's health NOW?" (diagnostic)

The gap this fills: unit tests can pass on a file that was never copied
into place, and the audit can look green while a subsystem is silently
absent. This exercises each fix end-to-end through the real call path,
using synthetic data only — no network, no Adanos requests, seconds to
run. Run it right after installing an update.

Exit code 1 if any fix is missing or broken.
"""

import sys
import tempfile
import traceback
from datetime import datetime, timedelta, timezone

import contextlib
import io

import pandas as pd

RESULTS = []


@contextlib.contextmanager
def quiet():
    """Silence the pipeline's progress prints so the report stays readable.
    Failures still surface — they travel as exceptions, not stdout."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        yield


def check(weakness, name):
    """Decorator: run a check, catch anything, record PASS/FAIL/SKIP."""
    def wrap(fn):
        try:
            with quiet():
                detail = fn()
            status = "PASS"
        except SkipCheck as e:
            detail, status = str(e), "SKIP"
        except AssertionError as e:
            detail, status = str(e) or "assertion failed", "FAIL"
        except Exception as e:
            detail, status = f"{type(e).__name__}: {e}", "FAIL"
            if "-v" in sys.argv:
                traceback.print_exc()
        RESULTS.append({"weakness": weakness, "name": name,
                        "status": status, "detail": detail})
        print(f"  [{status:<4}] #{weakness} {name}: {detail}")
        return fn
    return wrap


class SkipCheck(Exception):
    pass


def _bars4h(start, bars):
    """4h bars — live exit levels come from 4h ATR, so resolution must
    happen at that granularity, not daily."""
    idx = pd.date_range(start, periods=len(bars), freq="4h")
    return pd.DataFrame(bars, index=idx, columns=["High", "Low", "Close"])


print("Verifying fixes (synthetic data only — 0 network calls, 0 Adanos requests)\n")

# ----------------------------------------------------------------------
print("IMPORTS")
try:
    import pipeline as um
    import signal_engines as se
    import live_tools as lt
    print("  [PASS] pipeline, signal_engines, live_tools all import\n")
except Exception as e:
    print(f"  [FAIL] import failed: {type(e).__name__}: {e}")
    print("\nNothing else can be checked. Did install_update.py run?")
    sys.exit(1)

print("FIX VERIFICATION")


# ----------------------------------------------------------------------
@check(1, "Lockbox seals recent data")
def _():
    assert hasattr(um, "apply_lockbox"), "apply_lockbox missing — fix not installed"
    idx = pd.date_range(end=pd.Timestamp.now().normalize(), periods=500, freq="D")
    df = pd.DataFrame({"Close": [1.0] * 500}, index=idx)
    sealed = um.apply_lockbox(df, months=6)
    opened = um.apply_lockbox(df, months=6, unlock=True)
    assert len(sealed) < len(df), "lockbox sealed nothing"
    assert len(opened) == len(df), "unlock did not return full data"
    held = len(df) - len(sealed)
    return f"{held} of {len(df)} rows held out; unlock restores all"


@check(2, "Walk-forward judges on NET and needs every fold")
def _():
    assert hasattr(um, "walkforward_verdict"), "walkforward_verdict missing"
    good = {"n": 20, "expectancy_r_net": 0.2}
    bad = {"n": 20, "expectancy_r_net": -0.1}
    gross_only_positive = {"n": 20, "expectancy_r": 0.05, "expectancy_r_net": -0.05}
    assert um.walkforward_verdict([good] * 4)["verdict"] == "GENERALIZES"
    assert um.walkforward_verdict([good, good, bad])["verdict"] == "REGIME_DEPENDENT"
    assert um.walkforward_verdict([{"n": 2}] * 4)["verdict"] == "INSUFFICIENT_DATA"
    v = um.walkforward_verdict([gross_only_positive] * 2)["verdict"]
    assert v == "NO_EDGE", f"verdict used GROSS not NET (got {v})"
    return "GENERALIZES/REGIME_DEPENDENT/NO_EDGE/INSUFFICIENT all correct, net-based"


@check(2, "mlsweep is lockboxed by default")
def _():
    import inspect
    sig = inspect.signature(um.ml_sweep)
    assert "unlock_lockbox" in sig.parameters, "ml_sweep not lockbox-aware"
    assert sig.parameters["unlock_lockbox"].default is False, \
        "mlsweep defaults to UNLOCKED — the tuning search can see holdout data"
    src = inspect.getsource(um.ml_sweep)
    assert "apply_lockbox" in src, "ml_sweep never calls apply_lockbox"
    return "the tuning search excludes holdout unless explicitly unlocked"


# ----------------------------------------------------------------------
@check(3, "Ping spam collapses into episodes")
def _():
    assert hasattr(lt, "extract_episodes"), "extract_episodes missing"
    cols = ["timestamp_utc", "ticker", "price", "final_score", "direction",
            "target_price", "stop_price", "atr", "vix_level"]
    rows = [dict(zip(cols, (f"2026-08-01T{h:02d}:00:00", "BTC", 100.0, 65,
                            "BUY", 106.0, 97.0, 2.0, 20))) for h in range(12)]
    rows.append(dict(zip(cols, ("2026-08-01T13:00:00", "BTC", 100.0, 50,
                                "WATCH", None, None, 2.0, 20))))
    rows.append(dict(zip(cols, ("2026-08-01T14:00:00", "BTC", 99.0, 66,
                                "BUY", 105.0, 96.0, 2.0, 20))))
    eps = lt.extract_episodes(pd.DataFrame(rows))
    assert len(eps) == 2, f"expected 2 episodes from 14 rows, got {len(eps)}"
    assert eps[0]["n_log_rows"] == 12, "first episode did not absorb its pings"
    return f"14 log rows -> 2 episodes (12 pings collapsed into the first)"


@check(3, "Live resolution matches backtest rules exactly")
def _():
    ep = {"episode_id": "x", "ticker": "BTC", "side": "long",
          "entry_time_utc": "2026-08-01T10:00:00", "entry_direction": "BUY",
          "peak_direction": "BUY", "entry_price": 100.0, "target_price": 106.0,
          "stop_price": 97.0, "entry_score": 65.0, "atr": 2.0, "vix_level": 20.0,
          "n_log_rows": 1, "signal_last_seen_utc": "2026-08-01T10:00:00"}
    tgt = lt.resolve_episode(ep, _bars4h("2026-08-02", [(107, 101, 106)]))
    stp = lt.resolve_episode(ep, _bars4h("2026-08-02", [(101, 96.5, 98)]))
    amb = lt.resolve_episode(ep, _bars4h("2026-08-02", [(107, 96, 100)]))
    pre = lt.resolve_episode(ep, _bars4h("2026-08-01T02:00:00",
                                         [(110, 99, 105), (101, 99, 100)]),
                             max_hold_days=1, bars_per_day=6)
    # GRANULARITY REGRESSION: a 4h bar sitting inside both levels must
    # leave the episode OPEN. Resolving 4h-ATR levels against DAILY bars
    # stopped out everything on bar one — the bug this check exists for.
    inside = lt.resolve_episode(ep, _bars4h("2026-08-02", [(100.8, 99.4, 100.2)] * 3))
    assert tgt["outcome"] == "target" and abs(tgt["pnl_r"] - 2.0) < 1e-6
    assert stp["outcome"] == "stop" and stp["pnl_r"] == -1.0
    assert amb["outcome"] == "ambiguous_stop", \
        "both-touched bar not counted pessimistically — live and backtest disagree"
    assert pre["outcome"] != "target", "a bar before the entry timestamp was counted"
    assert inside["status"] == "open", \
        "a quiet 4h bar stopped the episode — granularity mismatch is back"
    return "target/stop/ambiguous/pre-entry/quiet-bar all behave correctly"


@check(3, "Outcomes file writes end to end")
def _():
    import os
    cols = ["timestamp_utc", "ticker", "price", "final_score", "direction",
            "target_price", "stop_price", "atr", "vix_level"]
    tmp = tempfile.mkdtemp()
    log = os.path.join(tmp, "log.csv")
    pd.DataFrame([dict(zip(cols, ("2026-08-01T10:00:00", "BTC", 100.0, 65,
                                  "BUY", 106.0, 97.0, 2.0, 20)))]).to_csv(log, index=False)
    out = os.path.join(tmp, "out.csv")
    df = lt.resolve_outcomes(log, out, fetcher=lambda t: _bars4h("2026-08-02",
                                                                [(107, 101, 106)]))
    assert os.path.isfile(out), "outcomes CSV not written"
    assert df.iloc[0]["outcome"] == "target"
    txt = lt.compare_live_to_backtest(df, min_n=15)
    assert "INSUFFICIENT" in txt, "comparison drew a conclusion from 1 episode"
    return "CSV written; comparison refuses to conclude below min_n"


# ----------------------------------------------------------------------
@check(4, "Costs are charged and scale with stop tightness")
def _():
    n = 25
    idx = pd.date_range("2026-01-01", periods=n, freq="D")
    df = pd.DataFrame({"Close": [100.0] * n, "High": [101.0] * n, "Low": [99.0] * n,
                       "direction": ["WATCH"] * n,
                       "combined_final_score": [65.0] * n}, index=idx)
    df.iloc[20, df.columns.get_loc("direction")] = "BUY"
    df.iloc[21, df.columns.get_loc("High")] = 107.0
    df.iloc[21, df.columns.get_loc("Low")] = 100.5
    r = um.backtest_exits(df, confirm_days=1, fee_bps=10.0, slippage_bps=5.0)
    assert r["n"] > 0, "fixture produced no trades"
    t = r["trades"][0]
    for k in ("cost_r", "pnl_r_net"):
        assert k in t, f"trades lack {k} — cost modeling not installed"
    assert "expectancy_r" in r and "expectancy_r_net" in r, \
        "gross key dropped — old numbers no longer comparable"
    free = um.backtest_exits(df, confirm_days=1, fee_bps=0, slippage_bps=0)
    assert abs(free["expectancy_r_net"] - free["expectancy_r"]) < 1e-9, \
        "zero-cost run still charged something"
    tight = um.backtest_exits(df, confirm_days=1, stop_mult=0.75)
    wide = um.backtest_exits(df, confirm_days=1, stop_mult=1.5)
    tc, wc = tight["trades"][0]["cost_r"], wide["trades"][0]["cost_r"]
    assert abs(tc - 2 * wc) < 1e-3, \
        f"cost does not scale with stop distance ({tc:.4f} vs {wc:.4f})"
    return f"cost {t['cost_r']:.3f}R charged; halving the stop doubles it; gross preserved"


# ----------------------------------------------------------------------
@check(5, "Bad market data is caught")
def _():
    assert hasattr(se, "validate_market_data"), "validate_market_data missing"
    idx = pd.date_range("2026-07-01", periods=30, freq="D", tz="UTC")
    c = pd.Series([100.0 + i * 0.1 for i in range(30)], index=idx)
    clean = pd.DataFrame({"High": c + 1, "Low": c - 1, "Close": c})
    assert se.validate_market_data(clean, now=idx[-1]) == [], \
        "clean data reported as bad"
    for label, mutate in (
            ("High<Low", lambda d: d.__setitem__("High", d["Low"] - 1)),
            ("bad tick", lambda d: d.loc.__setitem__((idx[10], "Close"), 5000.0)),
            ("non-positive", lambda d: d.loc.__setitem__((idx[3], "Close"), -5.0)),
            ("duplicate timestamps", lambda d: None)):
        bad = clean.copy()
        if label == "duplicate timestamps":
            bad = pd.concat([bad, bad.iloc[[0]]])
        else:
            mutate(bad)
        issues = se.validate_market_data(bad)
        assert issues, f"{label} not caught"
    stale = se.validate_market_data(clean, interval_hours=24,
                                    now=idx[-1] + pd.Timedelta(days=10))
    assert any("stale" in i for i in stale), "stale feed not caught"
    return "High<Low, bad ticks, non-positive prices, stale feeds all detected"


@check(5, "Independent sources are cross-checked")
def _():
    assert se.cross_check_price(100.0, 101.0)["ok"] is True, "2% agreement rejected"
    assert se.cross_check_price(100.0, 130.0)["ok"] is False, "30% divergence accepted"
    assert se.cross_check_price(100.0, float("nan"))["ok"] is False, \
        "missing source treated as agreement"
    return "Binance-vs-Yahoo divergence check behaves on all three cases"


# ----------------------------------------------------------------------
@check(6, "Raw sentiment reaches the log")
def _():
    orig = se.fetch_token_sentiment
    try:
        se.fetch_token_sentiment = lambda t, api_key=None: {
            "found": True, "sentiment_score": -0.22, "mentions": 55,
            "bullish_pct": 30, "bearish_pct": 70, "buzz_score": 2}
        gate = se.first_pass_sentiment_check_adanos("BTC")
    finally:
        se.fetch_token_sentiment = orig
    assert gate.get("sentiment_score") == -0.22, "raw reading not passed through"
    assert gate.get("sentiment_mentions") == 55, "mention count not passed through"
    for col in ("sentiment_score", "sentiment_mentions"):
        assert col in lt.LOG_COLUMNS, f"{col} missing from LOG_COLUMNS"
    assert gate["gate_multiplier"] < 1.0, \
        "a -0.22 reading did not dampen — gate thresholds changed unexpectedly"
    return f"reading -0.22/55 flows through; gate dampened to x{gate['gate_multiplier']}"


@check(6, "Old log migrates instead of misaligning")
def _():
    import os
    tmp = tempfile.mkdtemp()
    p = os.path.join(tmp, "log.csv")
    old_cols = [c for c in lt.LOG_COLUMNS
                if c not in ("sentiment_score", "sentiment_mentions", "gate_cache_hit")]
    pd.DataFrame([{c: 1 for c in old_cols}]).to_csv(p, index=False)
    lt.append_ping_to_log({
        "ticker": "BTC",
        "step1_initial_scoring": {"close": 100.0, "initial_score": 50.0, "atr": 2.0},
        "step2_reddit_data": {"gated_score": 50.0, "gate_decision": "PROCEED",
                              "gate_multiplier": 1.0, "sentiment_score": 0.12,
                              "sentiment_mentions": 40, "gate_cache_hit": True},
        "step3_indicators": {"indicator_final_score": 55.0, "vix_level": 18.0},
        "combined": {"final_score": 52.0, "decision": "WATCH", "direction": "WATCH",
                     "exit_levels": {}, "ml_confidence": None}}, p)
    df = pd.read_csv(p)
    assert list(df.columns) == lt.LOG_COLUMNS, "header not migrated"
    assert len(df) == 2 and abs(df.iloc[1]["sentiment_score"] - 0.12) < 1e-9, \
        "new row misaligned after migration"
    assert pd.isna(df.iloc[0]["sentiment_score"]), "old row corrupted by migration"
    return "narrow log widened in place; old rows preserved, new row aligned"


# ----------------------------------------------------------------------
@check("Q", "Sentiment caching still saves quota")
def _():
    import os
    calls = []

    def fake(t, **kw):
        calls.append(t)
        return {"decision": "PROCEED", "gate_multiplier": 1.0, "reason": "ok"}
    p = os.path.join(tempfile.mkdtemp(), "c.json")
    t0 = datetime(2026, 8, 1, tzinfo=timezone.utc)
    for i in range(20):
        se.cached_sentiment_check("BTC", ttl_hours=4, cache_path=p,
                                  fetcher=fake, now=t0 + timedelta(minutes=30 * i))
    assert len(calls) == 3, f"expected 3 requests over 10h at 4h TTL, got {len(calls)}"

    def broken(t, **kw):
        raise ConnectionError("down")
    err_calls = []

    def erroring(t, **kw):
        err_calls.append(t)
        return {"decision": "LOW_CONFIDENCE", "gate_multiplier": 1.0, "reason": "err"}
    p2 = os.path.join(tempfile.mkdtemp(), "c2.json")
    se.cached_sentiment_check("BTC", ttl_hours=4, cache_path=p2, fetcher=erroring)
    se.cached_sentiment_check("BTC", ttl_hours=4, cache_path=p2, fetcher=erroring)
    assert len(err_calls) == 2, \
        "an error result was CACHED — the gate would be silently off for hours"
    return "20 runs over 10h -> 3 requests; error results correctly not cached"


# ----------------------------------------------------------------------
print()
counts = {}
for r in RESULTS:
    counts[r["status"]] = counts.get(r["status"], 0) + 1
n_fail = counts.get("FAIL", 0)
summary = ", ".join(f"{v} {k}" for k, v in sorted(counts.items()))
print(f"{len(RESULTS)} checks: {summary}")

if n_fail:
    print("\nMISSING OR BROKEN:")
    for r in RESULTS:
        if r["status"] == "FAIL":
            print(f"  #{r['weakness']} {r['name']} — {r['detail']}")
    print("\nMost likely cause: a file did not get copied into place. "
          "Run: python install_update.py")
else:
    print("\nAll fixes present and functioning.")
    print("Next: python audit.py --offline   (health, not installation)")

sys.exit(1 if n_fail else 0)
