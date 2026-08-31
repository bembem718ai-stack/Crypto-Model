"""
shadow_basket.py
================
Runs the incumbent across the #167 tradable-26 in SHADOW: scored, logged,
never published, never alerted, never charted.

WHY SHADOW AND NOT LIVE. The basket has never been run forward. Everything
known about it (#163-#167) is backtest on a frozen file. A shadow log is the
only way to accumulate FORWARD out-of-sample evidence on 26 tickers without
publishing a single signal that no registered result supports.

FOUR PROPERTIES, ENFORCED HERE
------------------------------
1. SEPARATE FILE. Writes shadow_log.csv. It never touches signal_log.csv,
   and nothing downstream of the live path reads it. The live 3-ticker path
   is not modified by this module at all.
2. NEVER PUBLISHED. No alerts, no charts, no Discord, no index.html. The
   only consumer is outcome resolution and, eventually, SHADOW-EVAL.
3. ZERO ADANOS. The sentiment gate is not called. Scores are UNGATED --
   see the superset property below.
4. DAILY INDICATORS CACHED ONCE PER DAY. Step 3 is a daily quantity; asking
   Yahoo for it 26 times an hour would be 624 redundant pulls a day.

THE SUPERSET PROPERTY -- why ungating is sound, and what it costs
----------------------------------------------------------------
The sentiment gate is DAMPEN-ONLY: its multiplier is in [0.5, 1.0], so
gated_score <= ungated_score always. The combined score is monotone in the
Step 1 component, so:

    ungated_final >= gated_final,   for every ticker, every hour.

Therefore the set of days this shadow log marks BUY is a strict SUPERSET of
the set the gated pipeline would have marked BUY. Nothing the gate would
have passed is missed here; some days are included that the gate would have
dampened out.

That is the honest cost and it is stated before the first row exists: shadow
BUY counts are an UPPER BOUND on gated BUY counts, and any shadow result is
a result about the ungated construction. It is NOT a drop-in estimate of
what the gated live system would have done, and SHADOW-EVAL's registration
says so. Given the gate has never once changed a score in production
(gate_multiplier == 1.0 on every logged row to date), the two are expected
to coincide -- but "expected to" is not "verified to", and the superset
direction is the one that cannot silently lose a signal.
"""
import os
import sys
import argparse
import tempfile
from datetime import datetime, timezone

import pandas as pd

import pipeline as pl
import signal_engines as cf
import live_tools as lt

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

ROOT = os.path.dirname(os.path.abspath(__file__))
SHADOW_LOG = "shadow_log.csv"
SHADOW_OUTCOMES = "shadow_outcomes.csv"
UNIVERSE_FILE = os.path.join(ROOT, "research", "basket_tradable.txt")

SHADOW_COLUMNS = [
    "timestamp_utc", "ticker", "price", "initial_score", "indicator_final_score",
    "final_score", "decision", "direction", "vix_level",
    "target_price", "stop_price", "atr", "risk_reward",
    # ARM 2 -- SQUEEZE_ONLY (#203). Same bar, same price, same indicator
    # pull; only the blend weights differ. See TWO ARMS above.
    "sq_final_score", "sq_decision", "sq_direction",
    "sq_target_price", "sq_stop_price", "sq_risk_reward",
    "gate_decision", "ind_cache_date", "tradable", "guard_reason",
]

# Each arm's columns, mapped onto the canonical names live_tools reads.
# Resolution reuses live_tools.extract_episodes UNCHANGED -- an arm is
# resolved by RENAMING its columns onto the ones that function already
# reads, never by a second copy of the episode logic that could drift.
ARM_COLUMNS = {
    "incumbent": {},                      # already canonical — identity
    "squeeze": {"sq_direction": "direction",
                "sq_target_price": "target_price",
                "sq_stop_price": "stop_price",
                "sq_risk_reward": "risk_reward",
                "sq_final_score": "final_score",
                "sq_decision": "decision"},
}

# Step 3 is a DAILY quantity. One pull per ticker per UTC day, reused by
# every hourly run that day. 26 tickers x 24 runs = 624 Yahoo pulls/day
# without this; 26 with it.
_IND_CACHE = {}


def universe():
    if not os.path.exists(UNIVERSE_FILE):
        return []
    return [l.strip() for l in open(UNIVERSE_FILE, encoding="utf-8") if l.strip()]


def _cache_key(ticker, now):
    return (ticker, now.strftime("%Y-%m-%d"))


def daily_indicators(ticker, now=None, period="2y"):
    """Step 3 for `ticker`, cached once per UTC day. Zero Adanos."""
    now = now or datetime.now(timezone.utc)
    key = _cache_key(ticker, now)
    if key in _IND_CACHE:
        return _IND_CACHE[key], True
    step3 = pl.apply_indicator_step(ticker, {"step": 2, "gated_score": 0.0},
                                    period=period, use_ml=False)
    _IND_CACHE[key] = step3
    return step3, False


def score_shadow(ticker, now=None):
    """Score one ticker, UNGATED, under BOTH blends. Row dict, or raises.

    The two arms share step1 and step3 — one price pull, one indicator
    pull. The second arm is a RE-BLEND of numbers already in hand, so it
    costs no extra network call and no extra Adanos request.
    """
    now = now or datetime.now(timezone.utc)
    step1 = pl.compute_initial_score(ticker)
    step3, cached = daily_indicators(ticker, now)

    # UNGATED: gated_score IS initial_score. No sentiment call, no Adanos.
    # The superset property holds for BOTH arms because both start here.
    step2 = {"step": 2, "gated_score": step1["initial_score"],
             "gate_decision": "UNGATED_SHADOW", "gate_multiplier": 1.0}

    combined = pl.combine_and_decide(step2, step3)          # 0.6 / 0.4
    squeeze = pl.combine_and_decide(step2, step3,           # 1.0 / 0.0
                                    weight_pattern=1.0, weight_indicators=0.0)

    # EXIT LEVELS ARE COMPUTED HERE, NOT READ OFF `combined`.
    #
    # combine_and_decide does NOT return exit_levels -- run_full_pipeline
    # computes them afterwards from step1's close and ATR. The first version
    # of this module read `combined.get("exit_levels")`, which is always
    # empty, so every row logged target_price=None. extract_episodes skips
    # rows with no target+stop, so the shadow basket would have accrued
    # labels forever and ZERO resolvable episodes -- silently, because a log
    # full of rows looks like a log that is working. Caught before the first
    # row was ever written.
    #
    # Same call, same multipliers (1.5 / 3.0 = LIVE_GEOMETRY) and same
    # conviction scaling as the live path, so a shadow episode's geometry is
    # the live geometry.
    exits = cf.compute_exit_levels(
        entry_price=step1["close"], direction=combined["direction"],
        atr=step1.get("atr"), stop_mult=1.5, target_mult=3.0)
    sq_exits = cf.compute_exit_levels(
        entry_price=step1["close"], direction=squeeze["direction"],
        atr=step1.get("atr"), stop_mult=1.5, target_mult=3.0)
    # NOTE: run_full_pipeline additionally downgrades SELL/STRONG_SELL to
    # WATCH when price is above its trend SMA. That filter is NOT applied
    # here, so short rows are logged as scored. It is a live publication
    # rule, and changing what shadow records is a separate decision.

    def lvl(e, key):
        return e.get(key) if e.get("applicable") else None

    return {
        "timestamp_utc": now.replace(tzinfo=None).isoformat(),
        "ticker": ticker,
        "price": step1.get("close"),
        "initial_score": step1.get("initial_score"),
        "indicator_final_score": step3.get("indicator_final_score"),
        "final_score": combined.get("final_score"),
        "decision": combined.get("decision"),
        "direction": combined.get("direction"),
        "vix_level": step3.get("vix_level"),
        "target_price": lvl(exits, "target"),
        "stop_price": lvl(exits, "stop"),
        "atr": exits.get("atr") if exits.get("applicable") else step1.get("atr"),
        "risk_reward": lvl(exits, "risk_reward"),
        # ARM 2 -- SQUEEZE_ONLY. Its own exit levels, because a label with
        # no target/stop cannot become an episode, and an arm that accrues
        # no episodes cannot answer #203's checkpoint.
        "sq_final_score": squeeze.get("final_score"),
        "sq_decision": squeeze.get("decision"),
        "sq_direction": squeeze.get("direction"),
        "sq_target_price": lvl(sq_exits, "target"),
        "sq_stop_price": lvl(sq_exits, "stop"),
        "sq_risk_reward": lvl(sq_exits, "risk_reward"),
        "gate_decision": step2["gate_decision"],
        "ind_cache_date": now.strftime("%Y-%m-%d"),
        "tradable": True,
        "guard_reason": "shadow — never published",
    }


def project_arm(df, arm):
    """Rename one arm's columns onto the canonical names live_tools reads.

    `incumbent` is already canonical, so its projection is the identity.
    `squeeze` copies its sq_* columns over the canonical ones. Either way
    extract_episodes/resolve_episode run UNCHANGED, so both arms are scored
    by exactly the rules a live episode is.
    """
    if arm not in ARM_COLUMNS:
        raise ValueError("unknown arm %r — expected one of %s"
                         % (arm, sorted(ARM_COLUMNS)))
    out = df.copy()
    for src, dst in ARM_COLUMNS[arm].items():
        if src in out.columns:
            out[dst] = out[src]
    return out


def append_shadow_rows(rows, path=SHADOW_LOG):
    """Append rows, REFUSING to append under a header that does not match.

    A log written under an older schema plus rows written under a newer one
    would silently shift every column right of the insertion point, and a
    forward record is exactly the artifact where that damage is both
    invisible and unrecoverable -- there is no re-running last month's bar.
    So a schema change fails loudly here and is migrated deliberately.
    """
    if not rows:
        return 0
    fresh = not os.path.exists(path) or os.path.getsize(path) == 0
    if not fresh:
        with open(path, encoding="utf-8") as fh:
            existing = fh.readline().strip().split(",")
        if existing != SHADOW_COLUMNS:
            missing = [c for c in SHADOW_COLUMNS if c not in existing]
            extra = [c for c in existing if c not in SHADOW_COLUMNS]
            raise ValueError(
                "shadow log schema mismatch in %s: refusing to append and "
                "misalign the forward record. missing=%s extra=%s. Migrate "
                "the file deliberately (add the columns to the existing rows) "
                "before logging again." % (path, missing, extra))
    pd.DataFrame(rows, columns=SHADOW_COLUMNS).to_csv(
        path, mode="a", header=fresh, index=False)
    return len(rows)


def run_shadow(tickers=None, log_path=SHADOW_LOG, now=None):
    """One shadow pass over the universe. Never publishes anything."""
    tickers = tickers if tickers is not None else universe()
    now = now or datetime.now(timezone.utc)
    print("--- shadow basket: %d tickers, UNGATED, 0 Adanos ---" % len(tickers))
    rows, failed = [], []
    for t in tickers:
        try:
            rows.append(score_shadow(t, now=now))
        except Exception as e:  # noqa: BLE001 — one bad ticker must not stop 25 others
            failed.append((t, type(e).__name__))
            print("  %-6s FAILED %s: %s" % (t, type(e).__name__, str(e)[:90]))
    n = append_shadow_rows(rows, log_path)
    dirs = pd.Series([r["direction"] for r in rows]).value_counts().to_dict() if rows else {}
    print("  logged %d rows -> %s | directions: %s" % (n, log_path, dirs))
    if failed:
        print("  %d failed: %s" % (len(failed), ", ".join(t for t, _ in failed)))
    return rows


def outcomes_path_for(arm, out_path=SHADOW_OUTCOMES):
    """shadow_outcomes.csv for the incumbent, shadow_sq_outcomes.csv for
    the squeeze arm. Separate files: the two arms are separate records and
    must never be pooled by accident."""
    if arm == "incumbent":
        return out_path
    stem, ext = os.path.splitext(out_path)
    return "%s_sq%s" % (stem, ext)


def resolve_shadow_outcomes(log_path=SHADOW_LOG, out_path=SHADOW_OUTCOMES,
                            max_hold_days: int = 15, arm="incumbent"):
    """Outcome resolution for one arm's shadow entries.

    Reuses live_tools.extract_episodes / resolve_episode unchanged, so a
    shadow episode is scored by exactly the rules a live one is. The arm is
    selected by PROJECTING its columns onto the canonical names (see
    project_arm) and handing the result to the same resolver -- there is no
    second implementation to drift. Costs zero Adanos: 4h klines only.
    """
    if not os.path.exists(log_path):
        print("no shadow log yet")
        return pd.DataFrame()
    dest = outcomes_path_for(arm, out_path)
    if arm == "incumbent":
        return lt.resolve_outcomes(log_path=log_path, out_path=dest,
                                   max_hold_days=max_hold_days)
    # The projection is EPHEMERAL. Writing it beside the log would create a
    # second file that looks like a record and is really a view.
    projected = project_arm(pd.read_csv(log_path), arm)
    fd, tmp = tempfile.mkstemp(suffix=".csv", prefix="shadow_%s_" % arm)
    os.close(fd)
    try:
        projected.to_csv(tmp, index=False)
        return lt.resolve_outcomes(log_path=tmp, out_path=dest,
                                   max_hold_days=max_hold_days)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mode", choices=("run", "outcomes"))
    ap.add_argument("--tickers", nargs="*", default=None)
    ap.add_argument("--log", default=SHADOW_LOG)
    a = ap.parse_args()
    if a.mode == "run":
        run_shadow(a.tickers, log_path=a.log)
    else:
        # BOTH arms, always. Resolving only one would let the two records
        # drift apart in length, and #203's checkpoint compares them.
        for arm in ("incumbent", "squeeze"):
            print("--- resolving %s arm ---" % arm)
            resolve_shadow_outcomes(log_path=a.log, arm=arm)


if __name__ == "__main__":
    main()
