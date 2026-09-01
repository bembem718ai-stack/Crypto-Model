"""
audit.py — full-model health check
==================================

ONE command that walks every known issue in this model and reports where
each one currently stands:

    python audit.py BTC ETH SOL

WHAT THIS IS FOR:
    The model has accumulated a list of things that failed, things that
    were fixed, and things that were never resolved. Re-deriving the
    status of each one by hand every time is how findings quietly rot.
    This runs them all and prints a status table.

DESIGN RULES (these are the whole point):
    1. NO CHECK CAN SILENTLY PASS. A check with too little data returns
       INSUFFICIENT, never PASS. A check that can't reach the network
       returns SKIP, never PASS.
    2. NOTHING HERE CHANGES A DEFAULT. It measures; you decide.
    3. Comparisons are re-measured live, not read from old notes. If the
       short trend filter stopped helping, this says so.
    4. Statuses are about the CURRENT data, not about whether the code
       matches what was written down last month.

STATUS VOCABULARY:
    PASS         - the check's criterion is met on current data
    FAIL         - criterion clearly not met; needs a decision
    DEGRADED     - works, but materially worse than when it was accepted
    INSUFFICIENT - not enough trades/rows to make an honest call
    SKIP         - couldn't run (no network, missing dep, no key)

COST: zero Adanos requests. Every check uses Binance klines or Yahoo
daily data, both free and unmetered. The Adanos-quota check is a
read-only accounting check, not a live call.

EXIT CODE: 1 if any check is FAIL, else 0 — so CI can gate on it.
"""

import argparse
import io
import json
import os
import re
import subprocess
import sys
import time
import warnings
from contextlib import redirect_stdout

import pandas as pd

warnings.filterwarnings("ignore")

PASS, FAIL, DEGRADED, INSUFFICIENT, SKIP = (
    "PASS", "FAIL", "DEGRADED", "INSUFFICIENT", "SKIP")

# Thresholds that define "still good enough". These are the numbers the
# findings were originally accepted at — a check DEGRADES when current
# data falls materially below the level that justified the decision.
BASELINES = {
    "ml_auc_ceiling": 0.60,      # above this, ML would deserve re-promotion
    "ml_auc_floor": 0.55,        # below this it's coin-flipping, stays display-only
    "min_trades_for_verdict": 10,
    "min_trades_for_sizing": 15,
    "log_stale_hours": 6,        # hourly checks: >6h old means the cron broke
    "buy_bar": 60.0,
    "sell_bar": 40.0,
}

_results = []


def record(section, name, status, detail, evidence=None):
    _results.append({"section": section, "name": name, "status": status,
                     "detail": detail, "evidence": evidence or {}})
    icon = {PASS: "PASS ", FAIL: "FAIL ", DEGRADED: "DEGR ",
            INSUFFICIENT: "INSUF", SKIP: "SKIP "}[status]
    print(f"  [{icon}] {name}: {detail}")
    return status


def _quiet(fn, *a, **kw):
    """Run a chatty pipeline function without its print() noise."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        out = fn(*a, **kw)
    return out


# ======================================================================
# SECTION A — OFFLINE / STRUCTURAL
# These need no network. If these fail, nothing downstream is trustworthy.
# ======================================================================

def check_test_suite():
    """The 190-test suite is the model's load-bearing safety net. Anything
    else in this audit is meaningless if the decision logic is broken."""
    try:
        proc = subprocess.run([sys.executable, "-m", "pytest", "test_signals.py", "-q"],
                              capture_output=True, text=True, timeout=600)
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return record("A. Structural", "Unit test suite", SKIP,
                      f"could not run pytest ({type(e).__name__})")
    tail = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    m = re.search(r"(\d+) passed", tail)
    n_pass = int(m.group(1)) if m else 0
    if proc.returncode == 0:
        return record("A. Structural", "Unit test suite", PASS,
                      f"{n_pass} tests passed", {"summary": tail})
    return record("A. Structural", "Unit test suite", FAIL,
                  f"pytest exited {proc.returncode} — {tail}", {"summary": tail})


def check_ml_is_display_only():
    """ML failed cross-ticker replication (BTC ~0.596 / ETH ~0.514 AUC) and
    was demoted to display-only. Grepping for the string is not enough —
    `ml_confidence` legitimately appears as an OUTPUT field. So this is
    behavioral: at production defaults, feeding wildly different ML values
    through the scorer must produce the SAME score and direction. It also
    checks nothing ships with ml_weight > 0, which would re-arm it."""
    try:
        import pipeline as um
    except ImportError as e:
        return record("A. Structural", "ML stays display-only", SKIP, str(e))

    step2 = {"gated_score": 72.0}
    outs = []
    for ml in (1.0, 50.0, 99.0, None):
        step3 = {"indicator_final_score": 68.0, "vix_level": 18.0,
                 "ai_confidence_score": ml, "ml_ok": ml is not None}
        c = um.combine_and_decide(step2, step3)   # production defaults
        outs.append((c["final_score"], c["direction"], c["ml_applied"]))
    scores = {o[0] for o in outs}
    dirs = {o[1] for o in outs}
    applied = any(o[2] for o in outs)
    ev = {"variants": outs}
    if len(scores) > 1 or len(dirs) > 1 or applied:
        return record("A. Structural", "ML stays display-only", FAIL,
                      f"ML changes the output at defaults: scores={sorted(scores)}, "
                      f"directions={sorted(dirs)} — the demoted engine is deciding", ev)

    # Nothing in the shipped code should default ml_weight above zero.
    armed = []
    for path in ("pipeline.py", "live_tools.py"):
        for i, line in enumerate(open(path, errors="ignore"), 1):
            m = re.search(r"ml_weight\s*[:=]\s*([0-9.]+)", line)
            if m and float(m.group(1)) > 0:
                armed.append(f"{path}:{i}")
    if armed:
        return record("A. Structural", "ML stays display-only", FAIL,
                      f"ml_weight defaults above 0 at {', '.join(armed)}",
                      {"locations": armed})
    return record("A. Structural", "ML stays display-only", PASS,
                  "score/direction identical across ML 1%/50%/99%/absent; "
                  "ml_weight defaults to 0")


def check_squeeze_depth_scaling():
    """REGRESSION GUARD for the bug that made the 4-year backtest impossible:
    run_backtest used a fixed 4000-bar (~1.8y) squeeze pull, and the inner
    join silently truncated every longer window to that. Depth must now
    scale with the requested period."""
    try:
        import pipeline as um
    except ImportError as e:
        return record("A. Structural", "Backtest window not capped", SKIP, str(e))
    if not hasattr(um, "_period_to_years"):
        return record("A. Structural", "Backtest window not capped", FAIL,
                      "_period_to_years missing — the depth fix is not present")
    bars_2y = int(um._period_to_years("2y") * 365 * 6 * 1.15)
    bars_5y = int(um._period_to_years("5y") * 365 * 6 * 1.15)
    if bars_5y <= bars_2y or bars_5y <= 4000:
        return record("A. Structural", "Backtest window not capped", FAIL,
                      f"depth does not scale with period (2y={bars_2y}, 5y={bars_5y})")
    return record("A. Structural", "Backtest window not capped", PASS,
                  f"depth scales with period (2y={bars_2y} bars, 5y={bars_5y} bars)",
                  {"bars_2y": bars_2y, "bars_5y": bars_5y})


def check_exit_math():
    """The R:R promise and the long/short mirror. NOTE: STRONG_* signals
    intentionally scale the target 1.333x with an unchanged stop, so their
    designed R:R is 2.667, not 2.0 — this asserts the DESIGNED value per
    label rather than flattening the conviction scaling into a false alarm."""
    try:
        import signal_engines as cf
    except ImportError as e:
        return record("A. Structural", "Exit level arithmetic", SKIP, str(e))
    expected = {"BUY": 2.0, "SELL": 2.0, "STRONG_BUY": 2.666, "STRONG_SELL": 2.666}
    problems, seen = [], {}
    for direction, want_rr in expected.items():
        lvl = cf.compute_exit_levels(100.0, direction, 2.0,
                                     stop_mult=1.5, target_mult=3.0)
        if not lvl.get("applicable"):
            problems.append(f"{direction}: not applicable")
            continue
        tgt_d, stop_d = abs(lvl["target"] - 100.0), abs(lvl["stop"] - 100.0)
        rr = tgt_d / stop_d
        seen[direction] = round(rr, 3)
        if abs(rr - want_rr) > 0.01:
            problems.append(f"{direction}: R:R {rr:.3f} != designed {want_rr}")
        is_long = direction in ("BUY", "STRONG_BUY")
        if is_long and not (lvl["target"] > 100.0 > lvl["stop"]):
            problems.append(f"{direction}: long levels on wrong side")
        if not is_long and not (lvl["target"] < 100.0 < lvl["stop"]):
            problems.append(f"{direction}: short levels on wrong side")
    if seen.get("STRONG_BUY", 0) <= seen.get("BUY", 99):
        problems.append("conviction scaling absent: STRONG_BUY R:R not above BUY")
    if cf.compute_exit_levels(100.0, "WATCH", 2.0).get("applicable"):
        problems.append("WATCH produced exit levels (should be inapplicable)")
    if problems:
        return record("A. Structural", "Exit level arithmetic", FAIL,
                      "; ".join(problems), {"observed_rr": seen})
    return record("A. Structural", "Exit level arithmetic", PASS,
                  f"designed R:R holds both sides (plain {seen['BUY']}, "
                  f"STRONG {seen['STRONG_BUY']}); WATCH inapplicable",
                  {"observed_rr": seen})


def check_secret_hygiene():
    """An Adanos key was pasted in chat and the repo is PUBLIC. Any live
    key committed to source is a live key on the internet."""
    hits = []
    for path in ("pipeline.py", "signal_engines.py", "live_tools.py",
                 "test_signals.py", "audit.py"):
        if not os.path.exists(path):
            continue
        for i, line in enumerate(open(path, errors="ignore"), 1):
            if re.search(r"sk_live_[A-Za-z0-9]{8,}", line):
                hits.append(f"{path}:{i}")
    if os.path.isdir(".github/workflows"):
        for f in os.listdir(".github/workflows"):
            for i, line in enumerate(open(f".github/workflows/{f}", errors="ignore"), 1):
                if re.search(r"sk_live_[A-Za-z0-9]{8,}", line):
                    hits.append(f".github/workflows/{f}:{i}")
    if hits:
        return record("A. Structural", "No hardcoded API keys", FAIL,
                      f"live-looking key found at {', '.join(hits)} — rotate it now",
                      {"locations": hits})
    return record("A. Structural", "No hardcoded API keys", PASS,
                  "no sk_live_ pattern in tracked source")


# ======================================================================
# SECTION B — LIVE DATA
# These re-measure every empirical claim the model rests on.
# ======================================================================

def load_window(ticker, years):
    """Pull the joined backtest frame for `years` and verify the window
    actually spans it — this is the check the old depth bug would fail."""
    import pipeline as um
    yf_period = next((p for y, p in ((1, "1y"), (2, "2y"), (5, "5y"), (10, "10y"))
                      if years <= y), "max")
    bars = min(int(years * 365 * 6 * 1.15), 30000)
    merged = _quiet(um.run_backtest, ticker, period=yf_period, squeeze_bars=bars)
    cutoff = pd.Timestamp.now().normalize() - pd.Timedelta(days=int(years * 365))
    merged = merged[merged.index >= cutoff]
    return merged


def check_window_integrity(ticker, merged, years):
    span_days = (merged.index.max() - merged.index.min()).days
    want = years * 365 * 0.85  # allow 15% for exchange gaps / listing date
    ev = {"rows": len(merged), "span_days": span_days,
          "start": str(merged.index.min().date()), "end": str(merged.index.max().date())}
    if span_days < want:
        return record("B. Live data", f"{ticker} window spans {years:g}y", FAIL,
                      f"only {span_days}d joined ({ev['start']}→{ev['end']}) — "
                      f"squeeze/technical join is truncating the window", ev)
    return record("B. Live data", f"{ticker} window spans {years:g}y", PASS,
                  f"{len(merged)} rows, {span_days}d ({ev['start']}→{ev['end']})", ev)


def check_headline_degradation(ticker, cells):
    """THE headline failure: over ~4 years BUY win rate fell toward 50% and
    SELL expectancy flipped sign. This restates it in current numbers,
    per time-half, so it can't be forgotten or hand-waved."""
    import pipeline as um
    h1l, h2l = um.subset_stats(cells.get("h1_long", [])), um.subset_stats(cells.get("h2_long", []))
    allx = um.subset_stats(cells.get("all", []))
    ev = {"h1_long": h1l, "h2_long": h2l, "all": allx}
    if min(h1l["n"], h2l["n"]) < BASELINES["min_trades_for_verdict"]:
        return record("B. Live data", f"{ticker} long side stable across halves",
                      INSUFFICIENT, f"h1 n={h1l['n']}, h2 n={h2l['n']}", ev)
    both_pos = h1l["expectancy_r"] > 0 and h2l["expectancy_r"] > 0
    gap = abs(h1l["expectancy_r"] - h2l["expectancy_r"])
    if both_pos and gap < 0.5:
        return record("B. Live data", f"{ticker} long side stable across halves", PASS,
                      f"h1 {h1l['expectancy_r']:+.3f}R vs h2 {h2l['expectancy_r']:+.3f}R", ev)
    if both_pos:
        return record("B. Live data", f"{ticker} long side stable across halves", DEGRADED,
                      f"both halves positive but far apart: h1 {h1l['expectancy_r']:+.3f}R "
                      f"vs h2 {h2l['expectancy_r']:+.3f}R — regime-dependent", ev)
    return record("B. Live data", f"{ticker} long side stable across halves", FAIL,
                  f"h1 {h1l['expectancy_r']:+.3f}R (n={h1l['n']}), "
                  f"h2 {h2l['expectancy_r']:+.3f}R (n={h2l['n']}) — sign differs by half; "
                  f"the edge is regime-conditional, not general", ev)


def check_param_helps(ticker, merged, label, base_kw, test_kw, min_gain=0.05):
    """Generic A/B: re-measure whether a previously-accepted parameter still
    earns its place. Same frame, same exits, one parameter changed."""
    import pipeline as um
    common = dict(stop_mult=1.5, target_mult=3.0, max_hold_days=15)
    a = _quiet(um.backtest_exits, merged, **common, **base_kw)
    b = _quiet(um.backtest_exits, merged, **common, **test_kw)
    if a.get("n", 0) < BASELINES["min_trades_for_verdict"] or \
       b.get("n", 0) < BASELINES["min_trades_for_verdict"]:
        return record("B. Live data", f"{ticker} {label}", INSUFFICIENT,
                      f"off n={a.get('n',0)}, on n={b.get('n',0)}")
    gain = b["expectancy_r"] - a["expectancy_r"]
    ev = {"off_expectancy": round(a["expectancy_r"], 3), "off_n": a["n"],
          "on_expectancy": round(b["expectancy_r"], 3), "on_n": b["n"],
          "gain_r": round(gain, 3)}
    msg = (f"off {a['expectancy_r']:+.3f}R (n={a['n']}) → "
           f"on {b['expectancy_r']:+.3f}R (n={b['n']}), gain {gain:+.3f}R")
    if gain >= min_gain:
        return record("B. Live data", f"{ticker} {label}", PASS, msg, ev)
    if gain > 0:
        return record("B. Live data", f"{ticker} {label}", DEGRADED,
                      msg + " — still positive but below the bar that justified it", ev)
    return record("B. Live data", f"{ticker} {label}", FAIL,
                  msg + " — no longer helps on current data", ev)


def check_score_bands(ticker, cells):
    """Is the BUY bar at 60 still in the right place? Higher score bands
    should show higher expectancy. If they don't, the score isn't ranking
    anything and the bar is arbitrary."""
    import pipeline as um
    trades = cells.get("all", [])
    if len(trades) < 30:
        return record("B. Live data", f"{ticker} score ranks outcomes",
                      INSUFFICIENT, f"only {len(trades)} trades")
    df = pd.DataFrame(trades)
    band = (df["score"] // 10 * 10).astype(int)
    grp = df.groupby(band)["pnl_r"].agg(["mean", "count"])
    grp = grp[grp["count"] >= BASELINES["min_trades_for_verdict"]]
    if len(grp) < 2:
        return record("B. Live data", f"{ticker} score ranks outcomes",
                      INSUFFICIENT, "fewer than 2 bands with enough trades",
                      {"bands": grp.to_dict()})
    corr = pd.Series(grp.index, dtype=float).corr(
        pd.Series(grp["mean"].values, dtype=float))
    ev = {"bands": {int(k): {"expectancy": round(v, 3),
                             "n": int(grp.loc[k, "count"])}
                    for k, v in grp["mean"].items()},
          "rank_corr": round(float(corr), 3)}
    detail = " | ".join(f"{int(k)}-{int(k)+10}: {v:+.3f}R (n={int(grp.loc[k,'count'])})"
                        for k, v in grp["mean"].items())
    if corr >= 0.5:
        return record("B. Live data", f"{ticker} score ranks outcomes", PASS,
                      f"monotone-ish (corr {corr:+.2f}) — {detail}", ev)
    if corr > 0:
        return record("B. Live data", f"{ticker} score ranks outcomes", DEGRADED,
                      f"weak ranking (corr {corr:+.2f}) — {detail}", ev)
    return record("B. Live data", f"{ticker} score ranks outcomes", FAIL,
                  f"score does NOT rank outcomes (corr {corr:+.2f}) — "
                  f"a bar at {BASELINES['buy_bar']:g} is arbitrary — {detail}", ev)


def check_costs_survival(ticker, cells):
    """Gross expectancy that dies after 30bps of round-trip friction was
    never an edge — it was a fee subsidy from the backtest. Uses the
    pnl_r_net field now attached to every trade."""
    import pipeline as um
    trades = cells.get("all", [])
    with_net = [t for t in trades if "pnl_r_net" in t]
    if len(with_net) < BASELINES["min_trades_for_verdict"]:
        return record("B. Live data", f"{ticker} edge survives costs", INSUFFICIENT,
                      f"only {len(with_net)} trades carrying net pnl")
    gross = sum(t["pnl_r"] for t in with_net) / len(with_net)
    net = sum(t["pnl_r_net"] for t in with_net) / len(with_net)
    cost = sum(t.get("cost_r", 0) for t in with_net) / len(with_net)
    ev = {"gross_r": round(gross, 3), "net_r": round(net, 3),
          "avg_cost_r": round(cost, 3), "n": len(with_net)}
    msg = f"gross {gross:+.3f}R, net {net:+.3f}R (avg cost {cost:.3f}R, n={len(with_net)})"
    if net > 0:
        return record("B. Live data", f"{ticker} edge survives costs", PASS, msg, ev)
    if gross > 0:
        return record("B. Live data", f"{ticker} edge survives costs", FAIL,
                      msg + " — the entire gross edge is inside the friction", ev)
    return record("B. Live data", f"{ticker} edge survives costs", FAIL, msg, ev)


def check_data_integrity(ticker):
    """Weakness #5: cross-check the two independent price pipes and run
    structural sanity on each. A dead cron is caught elsewhere; this is
    for a LIVE feed quietly serving garbage."""
    try:
        import signal_engines as cf
        import pandas as pd
    except ImportError as e:
        return record("B. Live data", f"{ticker} data integrity", SKIP, str(e))
    try:
        b = cf.fetch_klines(cf.to_binance_symbol(ticker), interval="1d", limit=30)
        y = _quiet(cf.analyze, cf.to_yahoo_crypto_symbol(ticker), period="1mo")
    except Exception as e:
        return record("B. Live data", f"{ticker} data integrity", SKIP,
                      f"{type(e).__name__}: {str(e)[:100]}")
    issues = cf.validate_market_data(b, interval_hours=24,
                                     now=pd.Timestamp.now(tz="UTC"))
    issues += [f"yahoo: {i}" for i in cf.validate_market_data(y, interval_hours=24)]
    xc = cf.cross_check_price(float(b["Close"].iloc[-1]), float(y["Close"].iloc[-1]))
    ev = {"issues": issues, "cross_check": xc}
    if issues or not xc["ok"]:
        return record("B. Live data", f"{ticker} data integrity", FAIL,
                      "; ".join(issues + ([] if xc["ok"] else [xc["reason"]])), ev)
    return record("B. Live data", f"{ticker} data integrity", PASS,
                  f"both feeds structurally clean; {xc['reason']}", ev)


def check_sizing_replication(per_ticker_res):
    """Fractional-Kelly sizing was accepted because higher score bands earned
    bigger multipliers on BOTH tickers. Re-check that the ORDERING still
    replicates: if the funded bands or the direction of the size ramp
    disagree across tickers, sizing is fitting per-ticker noise.

    compute_position_sizing returns {band_string: {n, mean_r, kelly, size, ...}}
    where band_string looks like '[60.0, 70.0)'."""
    import pipeline as um
    orderings = {}
    for ticker, res in per_ticker_res.items():
        sz = _quiet(um.compute_position_sizing, res, bucket=10.0, kelly_fraction=0.25,
                    min_n=BASELINES["min_trades_for_sizing"])
        if not isinstance(sz, dict) or not sz:
            continue
        rows = []
        for band_str, v in sz.items():
            m = re.search(r"\[?\s*(-?[0-9.]+)", str(band_str))
            size = float(v.get("size", 0) or 0)
            if m and size > 0:
                rows.append((float(m.group(1)), round(size, 3)))
        if len(rows) >= 2:
            orderings[ticker] = sorted(rows)
    if len(orderings) < 2:
        return record("B. Live data", "Kelly band sizing replicates", INSUFFICIENT,
                      f"only {len(orderings)} ticker(s) produced 2+ funded bands "
                      f"(min {BASELINES['min_trades_for_sizing']} trades per band)",
                      {"orderings": orderings})
    tickers = list(orderings)
    ref = [b for b, _ in orderings[tickers[0]]]
    same_bands = all([b for b, _ in orderings[t]] == ref for t in tickers[1:])
    slopes = {t: round(orderings[t][-1][1] - orderings[t][0][1], 3) for t in tickers}
    same_dir = len({s > 0 for s in slopes.values()}) == 1
    ev = {"orderings": orderings, "slopes": slopes}
    desc = "; ".join(f"{t}: " + ", ".join(f"{int(b)}+ ->{s:.2f}x"
                                          for b, s in orderings[t]) for t in tickers)
    if same_bands and same_dir:
        return record("B. Live data", "Kelly band sizing replicates", PASS,
                      f"same funded bands, same ramp direction across "
                      f"{len(tickers)} tickers — {desc}", ev)
    return record("B. Live data", "Kelly band sizing replicates", DEGRADED,
                  f"funded bands or ramp direction differ across tickers — "
                  f"may be fitting per-ticker noise — {desc}", ev)


def check_ml_auc(ticker):
    """Re-run the honest chronological holdout. The demotion stands unless
    AUC clears the ceiling on MULTIPLE tickers — one good number is what
    got it promoted the first time."""
    try:
        import pipeline as um
        import signal_engines as epm
    except ImportError as e:
        return record("B. Live data", f"{ticker} ML holdout AUC", SKIP, str(e))
    try:
        frame = _quiet(um.build_ml_frame, ticker, period="3y")
        res = _quiet(epm.train_ml_model_with_holdout, frame, test_size=0.2)
    except Exception as e:
        return record("B. Live data", f"{ticker} ML holdout AUC", SKIP,
                      f"{type(e).__name__}: {e}")
    auc = res.get("roc_auc", float("nan"))
    if auc != auc:
        return record("B. Live data", f"{ticker} ML holdout AUC", INSUFFICIENT,
                      "AUC undefined (holdout has a single class)")
    ev = {"roc_auc": round(float(auc), 3), "accuracy": round(float(res.get("accuracy", 0)), 3)}
    if auc >= BASELINES["ml_auc_ceiling"]:
        return record("B. Live data", f"{ticker} ML holdout AUC", DEGRADED,
                      f"AUC {auc:.3f} clears {BASELINES['ml_auc_ceiling']} — worth "
                      f"re-testing on other tickers before ANY re-promotion", ev)
    if auc >= BASELINES["ml_auc_floor"]:
        return record("B. Live data", f"{ticker} ML holdout AUC", PASS,
                      f"AUC {auc:.3f} — weak, demotion to display-only still correct", ev)
    return record("B. Live data", f"{ticker} ML holdout AUC", PASS,
                  f"AUC {auc:.3f} — near coin-flip, demotion clearly correct", ev)


# ======================================================================
# SECTION C — DEPLOYMENT HEALTH
# ======================================================================

def _origin_log(path="signal_log.csv"):
    """The log as it exists on origin/main, which is what the LIVE bot
    writes to. Returns (DataFrame, note) or (None, why-not).

    WHY THIS EXISTS: this check used to read the local working copy. On any
    developer machine that has not pulled, the local file is stale BY
    DEFINITION, and the check reported a production outage that was not
    happening -- it cried wolf twice on 2026-08-27, when the live log was
    current and only the local clone was one commit behind. Local staleness
    is not deployment staleness.
    """
    try:
        subprocess.run(["git", "fetch", "origin", "--quiet"],
                       capture_output=True, timeout=60, check=False)
        r = subprocess.run(["git", "show", f"origin/main:{path}"],
                           capture_output=True, text=True, timeout=60)
        if r.returncode != 0 or not r.stdout.strip():
            return None, "origin/main copy unavailable"
        return pd.read_csv(io.StringIO(r.stdout)), "origin/main"
    except Exception as e:                     # offline, no remote, no git
        return None, f"{type(e).__name__}"


def check_log_freshness(path="signal_log.csv"):
    """Hourly checks run via cron-job.org → workflow_dispatch. A stale log
    is how you find out the cron died without anyone noticing.

    Measured against origin/main -- what the live bot actually wrote --
    falling back to the local copy only when origin is unreachable, and
    LABELLING it clearly as local-clone lag when it does.
    """
    if not os.path.exists(path):
        return record("C. Deployment", "Signal log is fresh", SKIP,
                      f"{path} not found (fine if running outside the repo)")
    df, source = _origin_log(path)
    if df is None:
        why = source
        try:
            df = pd.read_csv(path)
        except Exception as e:
            return record("C. Deployment", "Signal log is fresh", FAIL,
                          f"unreadable: {type(e).__name__}: {e}")
        source = (f"LOCAL CLONE ONLY ({why}) — this measures local-clone lag, "
                  f"NOT the live deployment; pull before believing it")
    tcol = next((c for c in df.columns
                 if "time" in c.lower() or "date" in c.lower()), None)
    if tcol is None or df.empty:
        return record("C. Deployment", "Signal log is fresh", INSUFFICIENT,
                      f"{len(df)} rows, no timestamp column found")
    last = pd.to_datetime(df[tcol], errors="coerce", utc=True).max()
    if pd.isna(last):
        return record("C. Deployment", "Signal log is fresh", INSUFFICIENT,
                      "no parseable timestamps")
    age_h = (pd.Timestamp.now(tz="UTC") - last).total_seconds() / 3600
    ev = {"rows": len(df), "last_entry": str(last),
          "age_hours": round(age_h, 1), "measured_against": source}
    if age_h <= BASELINES["log_stale_hours"]:
        return record("C. Deployment", "Signal log is fresh", PASS,
                      f"{len(df)} rows, newest {age_h:.1f}h old [{source}]", ev)
    return record("C. Deployment", "Signal log is fresh", FAIL,
                  f"newest entry {age_h:.1f}h old (> {BASELINES['log_stale_hours']}h) "
                  f"[{source}] — the trigger may have stopped firing", ev)


def check_sentiment_gate_errors(path="signal_log.csv"):
    """How many of the MOST RECENT runs ended with gate_decision == ERROR.

    A single ERROR is a blip. A run of them means Step 2 has been switched
    off in production without anything failing loudly: the gate errors,
    falls back to a neutral 1.0 multiplier, and the workflow still reports
    success. On 2026-08-27 the last 300 logged runs were ALL ERROR and the
    Actions runs were 100/100 green.
    """
    df, source = _origin_log(path)
    if df is None:
        if not os.path.exists(path):
            return record("C. Deployment", "Sentiment gate not erroring", SKIP,
                          f"{path} not found")
        try:
            df = pd.read_csv(path)
        except Exception as e:
            return record("C. Deployment", "Sentiment gate not erroring", SKIP,
                          f"unreadable: {type(e).__name__}")
        source = "LOCAL CLONE ONLY"
    if "gate_decision" not in df.columns or df.empty:
        return record("C. Deployment", "Sentiment gate not erroring", INSUFFICIENT,
                      "no gate_decision column yet")
    dec = df["gate_decision"].astype(str)
    streak = 0
    for v in reversed(dec.tolist()):
        if v.strip().upper() == "ERROR":
            streak += 1
        else:
            break
    ev = {"consecutive_error_runs": streak, "rows": len(df),
          "measured_against": source,
          "last_non_error": (None if streak >= len(dec)
                             else str(dec.iloc[len(dec) - streak - 1]))}
    if streak == 0:
        return record("C. Deployment", "Sentiment gate not erroring", PASS,
                      f"most recent run's gate is {dec.iloc[-1]} [{source}]", ev)
    if streak >= 10:
        return record("C. Deployment", "Sentiment gate not erroring", FAIL,
                      f"{streak} CONSECUTIVE runs ended gate_decision=ERROR "
                      f"[{source}] — Step 2 is neutral in production and the "
                      f"workflow still reports success. Check the Adanos "
                      f"quota/key; the run log now carries the HTTP status",
                      ev)
    return record("C. Deployment", "Sentiment gate not erroring", DEGRADED,
                  f"{streak} consecutive ERROR run(s) [{source}]", ev)


DERIVS_STALE_DAYS = 3


def _derivs_windows():
    """Per-source window + what a missed day costs, from the collector."""
    try:
        rd = os.path.join(os.path.dirname(os.path.abspath(__file__)), "research")
        if rd not in sys.path:
            sys.path.insert(0, rd)
        import collect_derivs
        return collect_derivs.SOURCE_WINDOWS
    except Exception:                                  # noqa: BLE001
        return {"kraken_funding": ("~365-day rolling", "1/365 of the archive")}


def check_derivatives_collector(out_dir="data/derivatives"):
    """Is EVERY derivatives source current?

    THIS IS DIFFERENT FROM EVERY OTHER STALENESS CHECK HERE. A stale signal
    log is recoverable -- the next run writes a fresh row and nothing is
    lost. A stale derivatives collector is NOT: these are rolling windows and
    current-only snapshots, so a day not collected falls off the venue
    permanently. There is no backfill at any price. Hence 3 days, not a week.

    Each source is checked separately and its failure message states WHAT A
    MISSED DAY COSTS for that source specifically, because the sources are
    not equally urgent: kraken_tickers is a current-only snapshot where a
    missed day is simply gone, while okx_rubik loses 1/180th. A future
    outage should be priced, not guessed at.
    """
    windows = _derivs_windows()
    results = []
    for name in sorted(windows):
        path = os.path.join(out_dir, "%s.csv" % name)
        label = "Derivatives current: %s" % name
        if not os.path.exists(path):
            results.append(record("C. Deployment", label, SKIP,
                                  f"{path} not found (source may not have run yet)"))
            continue
        try:
            df = pd.read_csv(path)
            last = pd.to_datetime(df["timestamp"], errors="coerce",
                                  utc=True, format="mixed").max()
        except Exception as e:                          # noqa: BLE001
            results.append(record("C. Deployment", label, SKIP,
                                  f"unreadable: {type(e).__name__}"))
            continue
        if pd.isna(last):
            results.append(record("C. Deployment", label, INSUFFICIENT,
                                  "no parseable timestamps"))
            continue
        window, cost = windows[name]
        age_d = (pd.Timestamp.now(tz="UTC") - last).total_seconds() / 86400.0
        ev = {"newest_row": str(last), "age_days": round(age_d, 2),
              "threshold_days": DERIVS_STALE_DAYS, "rows": int(len(df)),
              "window": window, "cost_of_a_missed_day": cost}
        if age_d <= DERIVS_STALE_DAYS:
            results.append(record("C. Deployment", label, PASS,
                                  f"newest row {age_d:.1f}d old ({window})", ev))
        else:
            results.append(record("C. Deployment", label, FAIL,
                                  f"newest row {age_d:.1f}d old (> "
                                  f"{DERIVS_STALE_DAYS}d). Window: {window}. "
                                  f"Each missed day costs {cost} and CANNOT be "
                                  f"re-fetched.", ev))
    return results


def check_adanos_accounting():
    """The binding constraint is the ~200 req/month Adanos free tier.
    Backtests use the NEUTRAL-sentiment assumption, so this whole audit
    must cost zero requests. This asserts that structurally rather than
    trusting it."""
    try:
        src = open("pipeline.py").read()
    except OSError as e:
        return record("C. Deployment", "Audit costs 0 Adanos requests", SKIP, str(e))
    start = src.find("def run_backtest")
    nxt = src.find("\ndef ", start + 1)
    body = src[start: nxt if nxt != -1 else len(src)]
    if re.search(r"apply_reddit_step|adanos|sentiment_gate", body, re.I):
        return record("C. Deployment", "Audit costs 0 Adanos requests", FAIL,
                      "run_backtest calls the sentiment step — backtests are "
                      "burning quota against a 200/month tier")
    hourly_month = 24 * 30
    return record("C. Deployment", "Audit costs 0 Adanos requests", PASS,
                  f"backtests use the neutral-sentiment assumption; note live "
                  f"hourly checks still need ~{hourly_month}/month per ticker "
                  f"vs a 200/month free tier", {"hourly_per_month": hourly_month})


def check_outcomes_tracking(path="signal_outcomes.csv", log_path="signal_log.csv"):
    """Weakness #3: the live system used to have NO scoreboard. This
    verifies the outcomes file exists and is being refreshed alongside
    the log. Sample-size honesty is built in: a young file is
    INSUFFICIENT, not PASS — months of episodes are needed before live
    numbers mean anything."""
    if not os.path.exists(path):
        return record("C. Deployment", "Live outcomes tracked", FAIL,
                      f"{path} missing — the live system is unscored; run "
                      f"'python live_tools.py outcomes'")
    try:
        df = pd.read_csv(path)
    except Exception as e:
        return record("C. Deployment", "Live outcomes tracked", FAIL,
                      f"unreadable: {type(e).__name__}")
    closed = df[df["status"] == "closed"] if "status" in df else df.iloc[0:0]
    ev = {"episodes": len(df), "closed": len(closed)}
    if os.path.exists(log_path):
        try:
            lage = pd.Timestamp.now(tz="UTC") - pd.to_datetime(
                pd.read_csv(path)["resolved_at_utc"], utc=True, format="mixed").max()
            if lage.total_seconds() / 3600 > 48:
                return record("C. Deployment", "Live outcomes tracked", DEGRADED,
                              f"{len(df)} episodes but last resolved "
                              f"{lage.total_seconds()/3600:.0f}h ago — wire "
                              f"'outcomes' into the hourly workflow", ev)
        except (KeyError, ValueError):
            pass
    if len(closed) < BASELINES["min_trades_for_sizing"]:
        return record("C. Deployment", "Live outcomes tracked", INSUFFICIENT,
                      f"tracking works: {len(df)} episodes, {len(closed)} closed — "
                      f"too few for any live-vs-backtest conclusion yet", ev)
    return record("C. Deployment", "Live outcomes tracked", PASS,
                  f"{len(df)} episodes, {len(closed)} closed", ev)


def check_sentiment_measurable(log_path="signal_log.csv"):
    """Weakness #6: the gate never fired and the log did not even record
    the raw reading, so its information content was untestable. This
    verifies the raw sentiment columns are flowing. Whether sentiment
    ultimately predicts outcomes gets answered by joining these columns
    to signal_outcomes.csv once enough episodes close."""
    try:
        cols = list(pd.read_csv(log_path, nrows=0).columns)
    except Exception as e:
        return record("C. Deployment", "Sentiment is measurable", SKIP, str(e))
    missing = [c for c in ("sentiment_score", "sentiment_mentions") if c not in cols]
    if missing:
        try:
            import live_tools as lt
            in_code = all(c in lt.LOG_COLUMNS for c in
                          ("sentiment_score", "sentiment_mentions"))
        except ImportError:
            in_code = False
        if in_code:
            return record("C. Deployment", "Sentiment is measurable", INSUFFICIENT,
                          "schema updated in code; file migrates on the next "
                          "live run — re-check after one signal check fires")
        return record("C. Deployment", "Sentiment is measurable", FAIL,
                      f"log lacks {missing} — the gate is still a black box")
    df = pd.read_csv(log_path)
    filled = df["sentiment_score"].notna().sum()
    if filled == 0:
        return record("C. Deployment", "Sentiment is measurable", INSUFFICIENT,
                      "columns exist but no readings recorded yet (fills on the "
                      "next live runs)")
    return record("C. Deployment", "Sentiment is measurable", PASS,
                  f"{filled} raw sentiment readings recorded")


def check_binance_region():
    """Binance global returns HTTP 451 from US IPs and Azure-hosted runners;
    BINANCE_REGION=US routes to Binance.US. Confirms the route works from
    wherever this is actually running."""
    try:
        import signal_engines as cf
    except ImportError as e:
        return record("C. Deployment", "Binance route reachable", SKIP, str(e))
    region = os.environ.get("BINANCE_REGION", "(unset)")
    try:
        df = cf.fetch_klines(cf.to_binance_symbol("BTC"), interval="4h", limit=5)
    except Exception as e:
        msg = str(e)
        status = FAIL if "451" in msg else SKIP
        return record("C. Deployment", "Binance route reachable", status,
                      f"BINANCE_REGION={region} → {type(e).__name__}: {msg[:120]}"
                      + (" (set BINANCE_REGION=US)" if "451" in msg else ""))
    return record("C. Deployment", "Binance route reachable", PASS,
                  f"BINANCE_REGION={region}, {len(df)} bars fetched",
                  {"region": region})


# ======================================================================
# REPORT
# ======================================================================

def render_report(tickers, years):
    order = [FAIL, DEGRADED, INSUFFICIENT, SKIP, PASS]
    counts = {s: sum(1 for r in _results if r["status"] == s) for s in order}
    lines = ["# Model Audit", "",
             f"Run: {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())} · "
             f"tickers: {' '.join(tickers)} · window: {years:g}y", "",
             "| Status | Count |", "|---|---|"]
    lines += [f"| {s} | {counts[s]} |" for s in order]
    lines += ["", "| Section | Check | Status | Detail |", "|---|---|---|---|"]
    for r in _results:
        detail = r["detail"].replace("|", "/")
        lines.append(f"| {r['section']} | {r['name']} | **{r['status']}** | {detail} |")
    lines += ["", "## How to read this", "",
              "- **FAIL** needs a decision, not a code tweak. A sign-flipping",
              "  edge is information about the market, not a bug.",
              "- **DEGRADED** means it still works but by less than the margin",
              "  that originally justified keeping it — worth re-deriving.",
              "- **INSUFFICIENT** is not a soft pass. It means the honest answer",
              "  is 'not enough trades yet'. Add tickers or extend the window.",
              "- **SKIP** means the check could not run at all (usually network).",
              "  Never read a SKIP as a PASS.", "",
              "Nothing in this audit changed a default.", ""]
    return "\n".join(lines)



def check_launch_readiness():
    """D. LAUNCH READINESS — turns "how close is the Discord bot" from a
    chat question into a checklist. Each item is a hard prerequisite
    established by the Aug 2026 validation sessions (docs/findings.md).
    None of these are style points: each one failing means launching
    would publish something known-broken or unmeasured.

    Root-cause note for three of these: the hourly workflow's commit
    step used to `git add sentiment_cache.json` unconditionally; the
    file doesn't exist until a sentiment call succeeds, git exits 128 on
    a missing pathspec, and the WHOLE commit aborted — discarding, every
    run: the outcomes update, the sentiment cache (so caching never
    persisted and every run paid full Adanos price), and the widened
    log schema. One bug, three symptoms. Fixed with per-file existence
    guards on 2026-08-05; these checks confirm the healing sticks."""
    import subprocess
    section = "D. Launch readiness"

    # 1. SELL suppression live in the workflow (measured decision:
    #    ex-best net negative on 3/3 tickers)
    wf_path = ".github/workflows/signal-check.yml"
    try:
        wf = open(wf_path).read()
        record(section, "Long-only publishing enabled in hourly workflow",
               PASS if "--long-only" in wf else FAIL,
               "--long-only " + ("present" if "--long-only" in wf else
               "MISSING — SELL signals (measured negative on 3/3 tickers) "
               "are still being published"))
        guarded = 'if [ -e "$f" ]' in wf
        record(section, "Workflow commit survives missing optional files",
               PASS if guarded else FAIL,
               "existence guard " + ("present" if guarded else
               "MISSING — one absent file aborts the commit and discards "
               "the run's log/outcomes/cache updates"))
    except OSError:
        record(section, "Hourly workflow file readable", INSUFFICIENT,
               f"{wf_path} not found in this checkout")

    # 2. Outcomes accumulating (the only overfit-immune evidence source)
    try:
        oc = pd.read_csv("signal_outcomes.csv")
        closed = int((oc["status"] == "closed").sum())
        newest = pd.to_datetime(oc["resolved_at_utc"], format="mixed",
                                 utc=True).max()
        age_h = (pd.Timestamp.now(tz="UTC") - newest).total_seconds() / 3600
        fresh = age_h <= 48
        record(section, "Outcomes file fresh (updated within 48h)",
               PASS if fresh else FAIL,
               f"last resolved {age_h:.0f}h ago" +
               ("" if fresh else " — hourly runs are not persisting "
                "outcomes; check the commit step"))
        need = BASELINES["min_trades_for_sizing"]
        record(section, f"Enough closed live episodes (>= {need})",
               PASS if closed >= need else INSUFFICIENT,
               f"{closed} closed so far" +
               ("" if closed >= need else
                f" — live-vs-backtest comparison stays silent below {need}; "
                f"this is a waiting requirement, not a coding one"))
    except (OSError, KeyError, ValueError) as e:
        record(section, "Outcomes file exists and parses", FAIL,
               f"signal_outcomes.csv unreadable ({type(e).__name__}) — no "
               f"overfit-immune evidence is accumulating")

    # 3. Log schema widened (sentiment observability)
    try:
        cols = pd.read_csv("signal_log.csv", nrows=1).columns
        widened = "sentiment_score" in cols
        record(section, "Log schema carries raw sentiment columns",
               PASS if widened else INSUFFICIENT,
               ("sentiment_score/mentions present — the never-fired gate is "
                "now evaluable on real data" if widened else
                "17-column legacy schema — widening happens on the first "
                "successful post-fix run; if this persists >24h the commit "
                "step is still broken"))
    except OSError:
        record(section, "Signal log readable", FAIL, "signal_log.csv missing")

    # 4. Sentiment cache persistence (the Adanos quota fix, for real)
    import os as _os
    cache_exists = _os.path.exists("sentiment_cache.json")
    record(section, "Sentiment cache persisted to repo",
           PASS if cache_exists else INSUFFICIENT,
           ("present — runs within the TTL reuse it instead of paying "
            "Adanos" if cache_exists else
            "absent — every run pays a fresh Adanos call (~1000+/mo at "
            "30-min cadence vs 250 free tier). Appears after the first "
            "successful sentiment call post-fix; also consider a 60-min "
            "cron-job.org interval"))

def main():
    p = argparse.ArgumentParser(description="Full-model health audit")
    p.add_argument("tickers", nargs="*", default=["BTC", "ETH", "SOL"],
                   help="Tickers to audit (default BTC ETH SOL)")
    p.add_argument("--years", type=float, default=4.0)
    p.add_argument("--vix-threshold", type=float, default=25.0)
    p.add_argument("--offline", action="store_true",
                   help="Structural checks only — no network calls")
    p.add_argument("--skip-ml", action="store_true",
                   help="Skip the ML holdout re-check (it is the slow one)")
    p.add_argument("--out", default="docs/audit.md")
    p.add_argument("--json-out", default="")
    args = p.parse_args()
    tickers = args.tickers or ["BTC", "ETH", "SOL"]

    print("\n=== A. STRUCTURAL (offline) ===")
    check_test_suite()
    check_ml_is_display_only()
    check_squeeze_depth_scaling()
    check_exit_math()
    check_secret_hygiene()

    print("\n=== C. DEPLOYMENT ===")
    check_launch_readiness()

    check_log_freshness()
    check_sentiment_gate_errors()
    check_derivatives_collector()
    check_adanos_accounting()
    check_outcomes_tracking()
    check_sentiment_measurable()
    if not args.offline:
        check_binance_region()

    if not args.offline:
        import pipeline as um
        print("\n=== B. LIVE DATA ===")
        per_ticker_cells, per_ticker_res = {}, {}
        for ticker in tickers:
            print(f"\n-- {ticker} --")
            try:
                merged = load_window(ticker, args.years)
            except Exception as e:
                record("B. Live data", f"{ticker} data pull", SKIP,
                       f"{type(e).__name__}: {str(e)[:140]}")
                continue
            check_window_integrity(ticker, merged, args.years)

            res = _quiet(um.backtest_exits, merged, stop_mult=1.5, target_mult=3.0,
                         max_hold_days=15, short_sma_filter=50, confirm_days=2)
            trades = um.attach_vix_to_trades(res.get("trades", []), merged)
            cells = um.split_trades(trades, args.vix_threshold)
            per_ticker_cells[ticker], per_ticker_res[ticker] = cells, res

            check_headline_degradation(ticker, cells)
            check_costs_survival(ticker, cells)
            check_data_integrity(ticker)
            check_score_bands(ticker, cells)
            check_param_helps(ticker, merged, "persistence filter (confirm_days 1→2)",
                              {"confirm_days": 1, "short_sma_filter": 50},
                              {"confirm_days": 2, "short_sma_filter": 50})
            check_param_helps(ticker, merged, "short trend filter (SMA50)",
                              {"confirm_days": 2, "short_sma_filter": 0, "side": "short"},
                              {"confirm_days": 2, "short_sma_filter": 50, "side": "short"})
            if not args.skip_ml:
                check_ml_auc(ticker)

        if per_ticker_cells:
            print("\n-- cross-ticker verdicts --")
            vv = um.vix_replication_verdict(per_ticker_cells)
            record("B. Live data", "VIX regime edge replicates",
                   {"REPLICATED": PASS, "NOT_REPLICATED": FAIL,
                    "INSUFFICIENT_DATA": INSUFFICIENT}[vv["verdict"]],
                   vv["verdict"] + " across " + ", ".join(per_ticker_cells), vv)
            sv = um.short_side_verdict(per_ticker_cells)
            record("B. Live data", "Short side viable",
                   {"SHORTS_HOLD_UP": PASS, "RECOMMEND_LONG_ONLY": FAIL,
                    "INSUFFICIENT_DATA": INSUFFICIENT}[sv["verdict"]],
                   f"{sv['verdict']} ({sv['tickers_passing']}/{sv['tickers_total']} "
                   f"tickers positive in both halves)", sv)
            check_sizing_replication(per_ticker_res)

    report = render_report(tickers, args.years)
    print("\n" + report)
    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        open(args.out, "w").write(report)
        print(f"Report written to {args.out}")
    if args.json_out:
        open(args.json_out, "w").write(json.dumps(_results, indent=2, default=str))
        print(f"Machine-readable results written to {args.json_out}")

    n_fail = sum(1 for r in _results if r["status"] == FAIL)
    print(f"\n{n_fail} check(s) FAILED.")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
