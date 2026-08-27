"""
live_tools.py
=============
CONSOLIDATED: monitor_with_alerts.py + signal_graph.py, merged into one
"watch it running" module. Both write to / read from the SAME
signal_log.csv, so a monitor loop and a graph replay share one history.

SECTIONS:
  1. MONITOR + ALERTS   (from monitor_with_alerts.py) - loops the pipeline,
                         fires a desktop notification + sound on BUY/SELL
                         transitions, and logs every ping.
  2. SIGNAL GRAPH        (from signal_graph.py) - plots the logged pings
                         against price (keyless Binance, so replay mode
                         works with ZERO Adanos cost even before you've
                         bought a tier). --live mode re-pings + redraws.

CLI (subcommands):
    python live_tools.py monitor BTC ETH SOL [--interval-seconds 300]
    python live_tools.py graph BTC                      # replay, no key needed
    python live_tools.py graph BTC --live                # re-pings + redraws

Requires: pip install plyer matplotlib pandas
(winsound is stdlib on Windows only -- monitor's beep is Windows-only,
 same as the original monitor_with_alerts.py)
"""

import os
import sys
import time
import argparse
from datetime import datetime, timezone

import pandas as pd

import pipeline as pl              # run_full_pipeline lives here now
import signal_engines as cf        # to_binance_symbol / fetch_klines_paginated

# winsound (Windows-only, stdlib) and plyer (desktop notifications) are only
# needed by the MONITOR half's alerting -- imported lazily inside
# fire_alert() so the GRAPH half (and everything else in this file) still
# works on any OS / without plyer installed. This preserves the original
# property that price/graphing works everywhere, only the alert sound is
# platform-limited.


# ======================================================================
# SECTION 1 — monitor_with_alerts.py (continuous monitor + desktop alerts)
# ======================================================================

ACTIONABLE = {"BUY", "STRONG_BUY", "SELL", "STRONG_SELL"}


def fire_alert(ticker: str, direction: str, decision: str, final_score: float):
    title = f"{ticker}: {direction}"
    message = f"Entry decision: {decision}\nFinal score: {final_score}"

    try:
        from plyer import notification
        notification.notify(title=title, message=message, app_name="unified_model",
                             timeout=15)
    except Exception as e:  # noqa: BLE001 - don't let a notification failure kill the loop
        print(f"  [alert] desktop notification failed ({type(e).__name__}: {e}) — "
              f"is plyer installed? pip install plyer")

    try:
        import winsound
        # Different tone for bullish vs bearish so you can tell which
        # without looking at the screen.
        if direction in ("BUY", "STRONG_BUY"):
            winsound.Beep(1000, 300)
            winsound.Beep(1400, 300)
        else:
            winsound.Beep(600, 300)
            winsound.Beep(400, 300)
    except Exception as e:  # noqa: BLE001
        print(f"  [alert] sound failed ({type(e).__name__}: {e}) — "
              f"winsound is Windows-only, this is expected on Mac/Linux")


def check_persistence(log_path: str, ticker: str, direction: str,
                      confirm_days: int = 2) -> dict:
    """
    Live counterpart to the backtest's --confirm-days filter: require the
    SAME direction on `confirm_days` consecutive DAYS before a signal counts.

    Validated on both tickers (3.0xATR/1.5x, long side, bar 60):
        BTC  116 trades +0.17R  ->  62 trades +0.28R
        ETH  104 trades +0.08R  ->  51 trades +0.23R
    Pooled: 220 trades +0.127R -> 113 trades +0.258R, with total return
    slightly HIGHER from half the exposure. What it removes is not losers
    but non-contributors (the dropped BTC trades averaged +0.04R each).

    WHY DAYS, NOT CHECKS: Step 1 uses 4h bars and Step 3 uses DAILY data,
    so two hourly checks are one observation sampled twice. Days are the
    shortest spacing at which the inputs have actually refreshed.

    Reads the shared signal log, collapses it to one reading per calendar
    day (the last of each day), and compares the most recent
    `confirm_days` days. If there aren't that many distinct days on
    record yet, it returns confirmed=False — being unable to verify is
    treated as not confirmed, never as confirmed.
    """
    if confirm_days <= 1:
        return {"confirmed": True, "reason": "persistence filter off"}

    try:
        log = load_log(log_path, ticker=ticker)
    except Exception as e:  # noqa: BLE001
        return {"confirmed": False, "reason": f"could not read log ({type(e).__name__})"}

    if log.empty:
        return {"confirmed": False, "reason": "no history logged yet"}

    daily = (log.set_index("timestamp_utc")
                .sort_index()["direction"]
                .resample("D").last()
                .dropna())
    if len(daily) < confirm_days - 1:
        return {"confirmed": False,
                "reason": f"only {len(daily)} day(s) of history, need "
                          f"{confirm_days - 1} prior day(s)"}

    prior = list(daily.iloc[-(confirm_days - 1):])
    if all(d == direction for d in prior):
        return {"confirmed": True,
                "reason": f"{direction} held {confirm_days} days running"}
    return {"confirmed": False,
            "reason": f"{direction} today but prior day(s) were "
                      f"{', '.join(prior)} — not {confirm_days} days running"}


def passes_confluence(result: dict, ml_bull_min: float = 55.0,
                      ml_bear_max: float = 45.0, long_only: bool = False) -> dict:
    """
    Confluence gate: qualifies a run ONLY when the direction score and the
    ML probability agree on the same side.

      Bullish qualify: direction in {BUY, STRONG_BUY}  AND  ML >= ml_bull_min
      Bearish qualify: direction in {SELL, STRONG_SELL} AND ML <= ml_bear_max

    ML score = P(+2% avg move over next 10 days), so a LOW ML confirms a
    bearish call (it agrees the up-move is unlikely). WATCH, or any case
    where score and ML point different ways, does NOT qualify.

    Returns {"qualifies": bool, "reason": str, "side": "bullish"/"bearish"/None}.
    Requires the run to have been produced with use_ml=True; if ML is
    missing, it cannot confirm and the run does NOT qualify.
    """
    combined = result.get("combined", {})
    direction = combined.get("direction")
    ml = combined.get("ml_confidence")

    if ml is None:
        return {"qualifies": False, "side": None,
                "reason": "no ML score (run with use_ml=True)"}

    bullish = direction in ("BUY", "STRONG_BUY")
    bearish = direction in ("SELL", "STRONG_SELL")

    if bullish and ml >= ml_bull_min:
        return {"qualifies": True, "side": "bullish",
                "reason": f"{direction} + ML {ml:.0f}% >= {ml_bull_min:.0f}%"}
    display = direction
    if bearish and long_only:
        return {"qualifies": False, "side": None,
                "reason": f"{display} suppressed — long-only mode. Measured "
                          f"Aug 2026: SELL ex-best-fold net was NEGATIVE on "
                          f"all three tickers (BTC -0.142R, ETH -0.140R, "
                          f"SOL -0.103R over ~80 trades each) and CONCENTRATED "
                          f"on all three — the entire apparent short edge was "
                          f"one recent fold. Logged for evaluation, not "
                          f"published."}
    if bearish and ml <= ml_bear_max:
        return {"qualifies": True, "side": "bearish",
                "reason": f"{direction} + ML {ml:.0f}% <= {ml_bear_max:.0f}%"}

    if bullish:
        return {"qualifies": False, "side": None,
                "reason": f"{direction} but ML only {ml:.0f}% (< {ml_bull_min:.0f}% — ML doesn't confirm)"}
    if bearish:
        return {"qualifies": False, "side": None,
                "reason": f"{direction} but ML {ml:.0f}% (> {ml_bear_max:.0f}% — ML doesn't confirm)"}
    return {"qualifies": False, "side": None,
            "reason": f"{direction} — not an actionable direction"}


def run_single_check(tickers: list, log_file: str = "signal_log.csv",
                     confluence: bool = False, ml_bull_min: float = 55.0,
                     ml_bear_max: float = 45.0, log_all: bool = False,
                     long_only: bool = False, confirm_days: int = 1) -> list:
    """
    ONE pass over `tickers` — no loop, no sleep, no desktop alerts. Built for
    headless/scheduled environments (GitHub Actions, cron, etc.) where an
    external scheduler provides the "every N hours" cadence instead of an
    internal while-loop.

    LOGGING BEHAVIOR:
      confluence=True, log_all=False (default) -> only QUALIFYING runs get
          logged to log_file. Quiet by design — signal_log.csv only fills
          up when score+ML genuinely agree.
      confluence=True, log_all=True -> EVERY run gets logged (including
          WATCH / non-qualifying), but the confluence gate is still
          evaluated and printed, so you can see which ones would have
          qualified without losing the rest of the history.
      confluence=False -> every run logged, no gate evaluated. (ML is only
          computed if log_all or confluence is set, since it's the more
          expensive step — pass log_all=True if you want ML numbers
          without confluence gating.)

    Returns the list of results that were actually LOGGED this call.
    """
    logged = []
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    mode = " (confluence mode)" if confluence else ""
    mode += ", logging everything" if log_all else ""
    print(f"--- {timestamp} --- checking {', '.join(tickers)}{mode}")

    want_ml = confluence or log_all

    # ADANOS QUOTA. The gate is dampen-only, so on a day whose Step 1 score
    # is below the DERIVED cutoff (sentiment_call_cutoff -- 33.3 at
    # production weights) even perfect indicators cannot reach the buy bar,
    # and dampening provably cannot change the label. The request is a pure
    # no-op there, so it is not made; the row logs
    # gate_decision=SKIPPED_BELOW_THRESHOLD.
    #
    # NOT the buy bar itself: between 33.3 and 60 a VETO genuinely does flip
    # a BUY (see test_cutoff_must_not_be_the_buy_bar), so skipping that band
    # would silently disable real vetoes to save quota.
    #
    # Measured on 1,769 logged runs: 52.9% of runs clear the cutoff, so
    # hourly single-ticker spend drops ~720 -> ~381 requests/month.
    cf.reset_run_cache()           # one process = one run; do not reuse readings
    for ticker in tickers:
        try:
            result = pl.run_full_pipeline(ticker, verbose=False, use_ml=want_ml,
                                          lazy_sentiment=True)
            direction = result["combined"]["direction"]
            decision = result["combined"]["decision"]
            final_score = result["combined"]["final_score"]
            ml_conf = result["combined"].get("ml_confidence")
            ml_str = f", ML={ml_conf:.0f}%" if ml_conf is not None else ""

            # Persistence check runs BEFORE logging, so today's own entry
            # can't be mistaken for yesterday's confirmation.
            persist = check_persistence(log_file, ticker, direction, confirm_days)
            if confirm_days > 1 and direction in ("BUY", "STRONG_BUY", "SELL", "STRONG_SELL"):
                mark = "confirmed" if persist["confirmed"] else "UNCONFIRMED"
                print(f"      persistence: {mark} — {persist['reason']}")

            should_log = True
            if confluence:
                gate = passes_confluence(result, ml_bull_min, ml_bear_max,
                                         long_only=long_only)
                if gate["qualifies"]:
                    print(f"  ✓ {ticker}: {direction} ({decision}, score={final_score}{ml_str}) "
                          f"— QUALIFIED: {gate['reason']}")
                else:
                    should_log = log_all  # only log a non-qualifier if log_all is set
                    tag = "logged (log-all)" if log_all else "skip, not logged"
                    print(f"  {ticker}: {direction} ({decision}, score={final_score}{ml_str}) "
                          f"— {tag}: {gate['reason']}")
            else:
                print(f"  {ticker}: {direction} ({decision}, score={final_score}{ml_str})")

            if should_log:
                try:
                    append_ping_to_log(result, log_file)
                    logged.append(result)
                except Exception as e:  # noqa: BLE001
                    print(f"  [log] append failed ({type(e).__name__}: {e})")

        except Exception as e:  # noqa: BLE001 - one bad ticker shouldn't kill the run
            print(f"  {ticker}: FAILED — {type(e).__name__}: {e}")

    if confluence and not log_all and not logged:
        print("  (no confluence signals this check — nothing logged; "
              "use --log-all to log every check regardless)")

    return logged


def monitor(tickers: list, interval_seconds: int, alert_every_time: bool,
            log_file: str = "signal_log.csv", confluence: bool = False,
            ml_bull_min: float = 55.0, ml_bear_max: float = 45.0):
    last_direction = {t: None for t in tickers}

    print(f"Monitoring {', '.join(tickers)} every {interval_seconds}s. Ctrl+C to stop.")
    if confluence:
        print(f"CONFLUENCE MODE: only printing/logging runs where score direction AND "
              f"ML agree\n  (bullish: BUY/STRONG_BUY + ML>={ml_bull_min:.0f}%  |  "
              f"bearish: SELL/STRONG_SELL + ML<={ml_bear_max:.0f}%)")
        print("  Non-qualifying runs are silently skipped (checked, but not shown or logged).\n")
    else:
        print(f"Alert mode: {'every loop while actionable' if alert_every_time else 'on change into actionable state'}\n")

    try:
        while True:
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            header_printed = False

            for ticker in tickers:
                try:
                    # Confluence needs ML, so force use_ml on in that mode.
                    result = pl.run_full_pipeline(ticker, verbose=False, use_ml=confluence)
                    direction = result["combined"]["direction"]
                    decision = result["combined"]["decision"]
                    final_score = result["combined"]["final_score"]
                    ml_conf = result["combined"].get("ml_confidence")

                    # --- Confluence gate: skip entirely if it doesn't qualify ---
                    if confluence:
                        gate = passes_confluence(result, ml_bull_min, ml_bear_max)
                        if not gate["qualifies"]:
                            continue  # not shown, not logged, not alerted
                        if not header_printed:
                            print(f"--- {timestamp} ---"); header_printed = True
                        try:
                            append_ping_to_log(result, log_file)
                        except Exception as e:  # noqa: BLE001
                            print(f"  [log] append failed ({type(e).__name__}: {e})")
                        ml_str = f", ML={ml_conf:.0f}%" if ml_conf is not None else ""
                        print(f"  ✓ {ticker}: {direction} ({decision}, score={final_score}{ml_str})")
                        print(f"      QUALIFIED — {gate['reason']}")
                        fire_alert(ticker, direction, decision, final_score)
                        last_direction[ticker] = direction
                        continue

                    # --- Normal (non-confluence) mode: original behavior ---
                    if not header_printed:
                        print(f"--- {timestamp} ---"); header_printed = True
                    try:
                        append_ping_to_log(result, log_file)
                    except Exception as e:  # noqa: BLE001
                        print(f"  [log] failed to append ping ({type(e).__name__}: {e})")

                    changed = direction != last_direction[ticker]
                    print(f"  {ticker}: {direction} ({decision}, score={final_score})"
                          f"{'  <- CHANGED' if changed else ''}")

                    is_actionable = direction in ACTIONABLE
                    should_alert = is_actionable and (alert_every_time or changed)
                    if should_alert:
                        fire_alert(ticker, direction, decision, final_score)
                    last_direction[ticker] = direction

                except Exception as e:  # noqa: BLE001 - one bad ticker shouldn't kill the loop
                    if not header_printed:
                        print(f"--- {timestamp} ---"); header_printed = True
                    print(f"  {ticker}: FAILED — {type(e).__name__}: {e}")

            if confluence and not header_printed:
                # Nothing qualified this loop — one quiet line so you know it's alive.
                print(f"--- {timestamp} --- (no confluence signals)")

            print()
            time.sleep(interval_seconds)

    except KeyboardInterrupt:
        print("\nStopped. Generating chart(s) from what was logged...")
        import webbrowser
        chart_dir = None
        chart_files = []
        for ticker in tickers:
            try:
                log = load_log(log_file, ticker=ticker)
                ohlcv = fetch_price_ohlcv(ticker, interval="4h", bars=500)
                out_name = f"{ticker.lower()}_signals.html"
                chart_path = generate_html_chart(ticker, ohlcv, log,
                                                 output_path=out_name, interval="4h")
                chart_dir = os.path.dirname(chart_path) or "."
                chart_files.append(out_name)
                n = len(log)
                print(f"  {ticker}: {n} signal{'s' if n != 1 else ''} logged -> {out_name}")
            except Exception as e:  # noqa: BLE001 - don't let one ticker's chart fail the rest
                print(f"  {ticker}: chart generation failed ({type(e).__name__}: {e})")

        if chart_files:
            server, port = _start_server(chart_dir)
            print(f"\nChart server running at http://localhost:{port} — opening "
                  f"{len(chart_files)} chart(s) in your browser.")
            print("Press Ctrl+C again once you're done viewing to shut the server down.\n")
            for name in chart_files:
                webbrowser.open(f"http://localhost:{port}/{name}")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                server.shutdown()
                print("\nChart server stopped.")
        else:
            print("No charts could be generated.")


def main_monitor():
    parser = argparse.ArgumentParser(description="Continuously monitor tickers and alert on "
                                                   "BUY/SELL signals")
    parser.add_argument("tickers", nargs="+", help="One or more tickers, e.g. BTC ETH SOL")
    parser.add_argument("--interval-seconds", type=int, default=300,
                         help="Seconds between checks (default 300 = 5 min)")
    parser.add_argument("--alert-every-time", action="store_true",
                         help="Alert every loop while a signal is actionable, "
                              "instead of only on change")
    parser.add_argument("--log-file", default="signal_log.csv",
                         help="Shared ping log CSV for signal_graph.py (default "
                              "signal_log.csv). Each successful ping is appended here.")
    parser.add_argument("--confluence", action="store_true",
                         help="Only print/log/alert runs where the score direction AND "
                              "the ML probability agree (needs xgboost). Non-qualifying "
                              "runs are silently skipped.")
    parser.add_argument("--ml-bull-min", type=float, default=55.0,
                         help="Min ML %% to confirm a BUY/STRONG_BUY (default 55)")
    parser.add_argument("--ml-bear-max", type=float, default=45.0,
                         help="Max ML %% to confirm a SELL/STRONG_SELL (default 45)")
    args = parser.parse_args()

    monitor(args.tickers, args.interval_seconds, args.alert_every_time,
            log_file=args.log_file, confluence=args.confluence,
            ml_bull_min=args.ml_bull_min, ml_bear_max=args.ml_bear_max)


# ======================================================================
# SECTION 2 — signal_graph.py (plot logged pings against price)
# ======================================================================

DEFAULT_LOG = "signal_log.csv"

LOG_COLUMNS = [
    "timestamp_utc", "ticker", "price", "initial_score", "gated_score",
    "indicator_final_score", "final_score", "decision", "direction",
    "vix_level", "gate_decision", "gate_multiplier",
    "target_price", "stop_price", "atr", "risk_reward", "ml_confidence",
    # Added 2026-08: raw sentiment (makes the never-fired gate evaluable)
    # and cache provenance. append_ping_to_log migrates old headers.
    "sentiment_score", "sentiment_mentions", "gate_cache_hit",
]

# How each direction label is drawn on the price panel.
DIRECTION_STYLE = {
    "STRONG_BUY":  dict(color="#00e676", marker="^", s=180, zorder=6, label="STRONG BUY"),
    "BUY":         dict(color="#66bb6a", marker="^", s=100, zorder=5, label="BUY"),
    "WATCH":       dict(color="#78909c", marker="D", s=25,  zorder=3, label="WATCH", alpha=0.5),
    "SELL":        dict(color="#ffa726", marker="v", s=100, zorder=5, label="SELL"),
    "STRONG_SELL": dict(color="#ef5350", marker="v", s=180, zorder=6, label="STRONG SELL"),
}


# ======================================================================
# LOGGING — one row per ping. Importable so other scripts (e.g.
# monitor_with_alerts.py) can feed the same shared history.
# ======================================================================

def append_ping_to_log(result: dict, log_path: str = DEFAULT_LOG,
                        timestamp: datetime = None) -> dict:
    """
    Extracts the plottable fields from a pl.run_full_pipeline() result and
    appends them as one row to `log_path` (creating it with a header if
    needed). Returns the row dict. Safe to call from any script that has
    a pipeline result.
    """
    ts = (timestamp or datetime.now(timezone.utc))
    step1 = result.get("step1_initial_scoring", {})
    step2 = result.get("step2_reddit_data", {})
    step3 = result.get("step3_indicators", {})
    combined = result.get("combined", {})
    exits = combined.get("exit_levels", {}) or {}

    row = {
        "timestamp_utc": ts.astimezone(timezone.utc).replace(tzinfo=None).isoformat(),
        "ticker": result.get("ticker"),
        "price": step1.get("close"),
        "initial_score": step1.get("initial_score"),
        "gated_score": step2.get("gated_score"),
        "indicator_final_score": step3.get("indicator_final_score"),
        "final_score": combined.get("final_score"),
        "decision": combined.get("decision"),
        "direction": combined.get("direction"),
        "vix_level": step3.get("vix_level"),
        "gate_decision": step2.get("gate_decision"),
        "gate_multiplier": step2.get("gate_multiplier"),
        "target_price": exits.get("target") if exits.get("applicable") else None,
        "stop_price": exits.get("stop") if exits.get("applicable") else None,
        "atr": exits.get("atr") if exits.get("applicable") else step1.get("atr"),
        "risk_reward": exits.get("risk_reward") if exits.get("applicable") else None,
        "ml_confidence": combined.get("ml_confidence"),
        "sentiment_score": step2.get("sentiment_score"),
        "sentiment_mentions": step2.get("sentiment_mentions"),
        "gate_cache_hit": step2.get("gate_cache_hit"),
    }

    header_needed = not os.path.exists(log_path) or os.path.getsize(log_path) == 0
    if not header_needed:
        # ONE-TIME MIGRATION: if the file predates newer LOG_COLUMNS,
        # appending wider rows would silently misalign every column.
        # Rewrite once with the new header; old rows get NaN in new cols.
        existing_cols = list(pd.read_csv(log_path, nrows=0).columns)
        if existing_cols != LOG_COLUMNS:
            old = pd.read_csv(log_path)
            for c in LOG_COLUMNS:
                if c not in old.columns:
                    old[c] = None
            old[LOG_COLUMNS].to_csv(log_path, index=False)
            print(f"  [log] migrated {log_path} to {len(LOG_COLUMNS)}-column schema")
    pd.DataFrame([row], columns=LOG_COLUMNS).to_csv(
        log_path, mode="a", header=header_needed, index=False)
    return row


# ======================================================================
# OUTCOME TRACKING — scoring the LIVE system (weakness #3)
# ======================================================================
# The log had 373 rows and zero outcome columns: nothing ever recorded
# whether a signal hit its target or its stop. Worse, the 30-minute
# cadence logs the same standing signal dozens of times, so "43 BUY
# rows" was really ~4 events. This section fixes both:
#
#   1. extract_episodes() collapses consecutive same-family rows into
#      EPISODES — one tradeable event each, entered at the first row's
#      logged price/target/stop.
#   2. resolve_episode() walks daily bars AFTER the entry date using the
#      SAME rules as backtest_exits (target if High>=target, stop if
#      Low<=stop, both in one bar = ambiguous_stop, pessimistic), so
#      live results are directly comparable to backtest results. Any
#      rule drift here would make the comparison meaningless.
#   3. resolve_outcomes() writes/updates signal_outcomes.csv. Costs ZERO
#      Adanos requests — daily klines only.
#
# Live forward outcomes are the one kind of evidence immune to every
# in-sample problem the backtests have. This file is the project's
# ground truth from now on; it just needs months to accumulate.

OUTCOMES_FILE = "signal_outcomes.csv"
_LONG_FAMILY = ("BUY", "STRONG_BUY")
_SHORT_FAMILY = ("SELL", "STRONG_SELL")


def _family(direction: str):
    if direction in _LONG_FAMILY:
        return "long"
    if direction in _SHORT_FAMILY:
        return "short"
    return None


def extract_episodes(log_df: pd.DataFrame) -> list:
    """Collapse the ping log into signal episodes. Pure.

    An episode starts when a ticker's direction ENTERS the long or short
    family and ends when it LEAVES that family (WATCH/AVOID or the
    opposite family). Strength changes within a family (BUY ->
    STRONG_BUY) do NOT start a new episode — same position, higher
    conviction. Entry price/target/stop are the FIRST row's logged
    values: that is what a follower of the system would actually have
    acted on. Episodes without logged target+stop are skipped (WATCH
    rows carry none)."""
    if log_df is None or log_df.empty:
        return []
    df = log_df.copy()
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], format="mixed")
    episodes = []
    for ticker, g in df.groupby("ticker"):
        g = g.sort_values("timestamp_utc")
        cur = None
        for _, row in g.iterrows():
            fam = _family(row.get("direction"))
            if cur is None:
                if fam is not None:
                    cur = {"row": row, "fam": fam,
                           "last_ts": row["timestamp_utc"],
                           "n_rows": 1, "peak_dir": row["direction"]}
            else:
                if fam == cur["fam"]:
                    cur["last_ts"] = row["timestamp_utc"]
                    cur["n_rows"] += 1
                    if str(row["direction"]).startswith("STRONG"):
                        cur["peak_dir"] = row["direction"]
                else:
                    episodes.append(cur)
                    cur = ({"row": row, "fam": fam,
                            "last_ts": row["timestamp_utc"],
                            "n_rows": 1, "peak_dir": row["direction"]}
                           if fam is not None else None)
        if cur is not None:
            episodes.append(cur)

    out = []
    for ep in episodes:
        r = ep["row"]
        tgt, stp = r.get("target_price"), r.get("stop_price")
        if tgt != tgt or stp != stp or tgt is None or stp is None:
            continue  # no exit levels logged (e.g. WATCH-band entries)
        out.append({
            "episode_id": f"{r['ticker']}_{r['timestamp_utc'].strftime('%Y%m%dT%H%M%S')}",
            "ticker": r["ticker"],
            "side": ep["fam"],
            "entry_time_utc": r["timestamp_utc"].isoformat(),
            "entry_direction": r["direction"],
            "peak_direction": ep["peak_dir"],
            "entry_price": float(r["price"]),
            "target_price": float(tgt),
            "stop_price": float(stp),
            "entry_score": float(r["final_score"]),
            "atr": float(r["atr"]) if r.get("atr") == r.get("atr") else float("nan"),
            "vix_level": float(r["vix_level"]) if r.get("vix_level") == r.get("vix_level") else float("nan"),
            "n_log_rows": ep["n_rows"],
            "signal_last_seen_utc": ep["last_ts"].isoformat(),
        })
    return out


def resolve_episode(episode: dict, bars: pd.DataFrame,
                     max_hold_days: int = 15, now=None,
                     bars_per_day: int = 6) -> dict:
    """Resolve one episode against OHLC bars. Pure.

    *** GRANULARITY MUST MATCH THE LEVELS. *** Live exit levels come from
    4h ATR: stops sit ~1.2% from entry. A DAILY bar routinely spans more
    than that, so scanning daily bars marks almost every episode as an
    immediate stop no matter what the market did — an artifact, not a
    result. (This was a real bug here: the first live run reported 4/4
    stops, every one on day 1.) So live episodes are resolved against 4h
    bars, matching the 4h ATR their levels were built from. The backtest
    is internally consistent the other way: daily ATR, daily bars.

    bars_per_day converts the max_hold_days budget into bars (6 for 4h).

    Rules otherwise mirror backtest_exits: scan bars strictly AFTER the
    entry timestamp, target/stop both touched in one bar ->
    ambiguous_stop (pessimistic), budget exhausted -> timeout at last
    close, not enough bars yet -> "open" with MFE so far. Intraday
    timestamps let us cut at the exact entry moment rather than dropping
    the whole entry day, so this is if anything less conservative than
    the daily backtest — noted so the comparison stays honest."""
    now = now or datetime.now(timezone.utc)
    entry_ts = pd.to_datetime(episode["entry_time_utc"])
    if entry_ts.tzinfo is not None:
        entry_ts = entry_ts.tz_localize(None)
    entry = episode["entry_price"]
    target, stop = episode["target_price"], episode["stop_price"]
    is_long = episode["side"] == "long"
    tgt_dist = abs(target - entry)
    stop_dist = abs(entry - stop)

    d = bars.copy()
    d.index = pd.to_datetime(d.index)
    if getattr(d.index, "tz", None) is not None:
        d.index = d.index.tz_localize(None)
    max_bars = max(1, int(max_hold_days * bars_per_day))
    fwd = d[d.index > entry_ts].iloc[:max_bars]

    res = dict(episode)
    res.update({"status": "open", "outcome": None, "exit_date": None,
                "bars_held": len(fwd),
                "days_held": round(len(fwd) / bars_per_day, 2), "pnl_r": None,
                "mfe_pct_of_target": 0.0, "resolved_at_utc": now.isoformat()})
    mfe = 0.0
    for day, row in fwd.iterrows():
        hi, lo = row["High"], row["Low"]
        fav = (hi - entry) if is_long else (entry - lo)
        if tgt_dist:
            mfe = max(mfe, fav / tgt_dist)
        hit_t = hi >= target if is_long else lo <= target
        hit_s = lo <= stop if is_long else hi >= stop
        if hit_t or hit_s:
            if hit_t and hit_s:
                outcome, pnl_r = "ambiguous_stop", -1.0
            elif hit_t:
                outcome, pnl_r = "target", (tgt_dist / stop_dist if stop_dist else float("nan"))
            else:
                outcome, pnl_r = "stop", -1.0
            n_bars = list(fwd.index).index(day) + 1
            res.update({"status": "closed", "outcome": outcome,
                        "exit_date": day.isoformat(),
                        "bars_held": n_bars,
                        "days_held": round(n_bars / bars_per_day, 2),
                        "pnl_r": round(pnl_r, 3),
                        "mfe_pct_of_target": round(mfe * 100, 1)})
            return res
    if len(fwd) >= max_bars:
        last_close = fwd.iloc[-1]["Close"]
        pnl = ((last_close - entry) if is_long else (entry - last_close))
        res.update({"status": "closed", "outcome": "timeout",
                    "exit_date": fwd.index[-1].isoformat(),
                    "bars_held": max_bars, "days_held": max_hold_days,
                    "pnl_r": round(pnl / stop_dist, 3) if stop_dist else None,
                    "mfe_pct_of_target": round(mfe * 100, 1)})
    else:
        res["mfe_pct_of_target"] = round(mfe * 100, 1)
    return res


def resolve_outcomes(log_path: str = DEFAULT_LOG, out_path: str = OUTCOMES_FILE,
                      max_hold_days: int = 15, fetcher=None, now=None,
                      interval: str = "4h", bars_per_day: int = 6) -> pd.DataFrame:
    """Extract episodes from the log, resolve each against 4h klines, and
    write signal_outcomes.csv. Open episodes are re-resolved every run;
    closed ones can only stay closed (past bars don't change).

    4h, not daily: live levels come from 4h ATR (see resolve_episode)."""
    need = int(max_hold_days * bars_per_day) + 40
    fetcher = fetcher or (lambda tkr: cf.fetch_klines(
        cf.to_binance_symbol(tkr), interval=interval, limit=min(need, 1000)))
    log_df = pd.read_csv(log_path)
    episodes = extract_episodes(log_df)
    if not episodes:
        print("No resolvable episodes in the log yet.")
        return pd.DataFrame()
    daily_by_ticker, results = {}, []
    for ep in episodes:
        t = ep["ticker"]
        if t not in daily_by_ticker:
            daily_by_ticker[t] = fetcher(t)
        results.append(resolve_episode(ep, daily_by_ticker[t],
                                        max_hold_days=max_hold_days, now=now,
                                        bars_per_day=bars_per_day))
    out = pd.DataFrame(results)
    out.to_csv(out_path, index=False)
    closed = out[out["status"] == "closed"]
    print(f"{len(out)} episodes ({len(closed)} closed, {len(out)-len(closed)} open) "
          f"-> {out_path}")
    if len(closed):
        print(f"  closed: target {(closed['outcome']=='target').mean()*100:.0f}%, "
              f"stop {(closed['outcome'].isin(['stop','ambiguous_stop'])).mean()*100:.0f}%, "
              f"mean {closed['pnl_r'].mean():+.2f}R over {len(closed)} episodes")
    return out


def compare_live_to_backtest(outcomes_df: pd.DataFrame, min_n: int = 15) -> str:
    """Live target-rate by score band vs the empirical calibration table.
    Honest by construction: below min_n closed episodes total it says so
    and refuses to draw conclusions."""
    closed = outcomes_df[outcomes_df["status"] == "closed"] if len(outcomes_df) else outcomes_df
    lines = ["LIVE vs BACKTEST calibration", "=" * 34]
    if len(closed) < min_n:
        lines.append(f"INSUFFICIENT: {len(closed)} closed episodes (need {min_n}). "
                     f"No conclusions yet — this is the file to watch, not a verdict.")
        return "\n".join(lines)
    band = (closed["entry_score"] // 10 * 10).astype(int)
    for b, g in closed.groupby(band):
        lines.append(f"  score {b}-{b+10}: n={len(g)}, target {(g['outcome']=='target').mean()*100:.0f}%, "
                     f"mean {g['pnl_r'].mean():+.2f}R")
    return "\n".join(lines)


def load_log(log_path: str = DEFAULT_LOG, ticker: str = None) -> pd.DataFrame:
    """Loads the ping log (optionally filtered to one ticker), with
    timestamp parsed to a tz-naive UTC datetime column, sorted by time."""
    if not os.path.exists(log_path) or os.path.getsize(log_path) == 0:
        return pd.DataFrame(columns=LOG_COLUMNS)

    df = pd.read_csv(log_path)
    if "timestamp_utc" in df.columns:
        df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], errors="coerce")
    if ticker is not None and "ticker" in df.columns:
        df = df[df["ticker"].str.upper() == ticker.upper()]
    return df.dropna(subset=["timestamp_utc"]).sort_values("timestamp_utc")


# ======================================================================
# PRICE — keyless Binance klines (no Adanos cost)
# ======================================================================

def fetch_price_series(ticker: str, interval: str = "4h", bars: int = 180) -> pd.Series:
    """Returns a Close-price Series indexed by (tz-naive UTC) datetime."""
    symbol = cf.to_binance_symbol(ticker)
    klines = cf.fetch_klines_paginated(symbol, interval=interval, target_bars=bars)
    if klines.empty:
        return pd.Series(dtype=float, name="Close")
    close = klines["Close"].copy()
    close.index = pd.to_datetime(close.index)  # already tz-naive UTC
    return close.tail(bars)


def fetch_price_ohlcv(ticker: str, interval: str = "4h", bars: int = 180) -> pd.DataFrame:
    """Returns full OHLCV DataFrame indexed by tz-naive UTC datetime."""
    symbol = cf.to_binance_symbol(ticker)
    klines = cf.fetch_klines_paginated(symbol, interval=interval, target_bars=bars)
    if klines.empty:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    klines.index = pd.to_datetime(klines.index)
    return klines[["Open", "High", "Low", "Close", "Volume"]].tail(bars)



# ======================================================================
# INTERACTIVE HTML CHART — live WebSocket price, trade marking, intervals
# ======================================================================

_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%%TICKER%% Signal Monitor</title>
<script src="https://unpkg.com/lightweight-charts@4.1.0/dist/lightweight-charts.standalone.production.js"></script>
<style>
:root{--bg:#0a0e17;--panel:#111827;--border:#1f2937;--text:#e5e7eb;--dim:#6b7280;--accent:#3b82f6;--green:#22c55e;--red:#ef4444}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:var(--text);font-family:'Segoe UI',system-ui,sans-serif;overflow:hidden;height:100vh;display:flex;flex-direction:column}
#toolbar{display:flex;align-items:center;gap:6px;padding:7px 16px;background:var(--panel);border-bottom:1px solid var(--border);flex-shrink:0;flex-wrap:wrap}
.ticker{font-size:18px;font-weight:700;color:#fff;margin-right:6px}
.btn-group{display:flex;gap:1px;background:var(--border);border-radius:5px;overflow:hidden}
.btn{padding:4px 10px;font-size:11px;font-weight:500;background:#1e293b;color:var(--dim);border:none;cursor:pointer;transition:all .15s;letter-spacing:.3px}
.btn:hover{background:#2d3748;color:var(--text)}
.btn.active{background:var(--accent);color:#fff}
.sep{width:1px;height:20px;background:var(--border);margin:0 6px}
.toggle{display:flex;align-items:center;gap:4px;padding:3px 8px;font-size:11px;color:var(--dim);cursor:pointer;border-radius:4px;user-select:none}
.toggle:hover{background:#1e293b}
.toggle.on{color:var(--text)}
.toggle .dot{width:7px;height:7px;border-radius:50%;background:var(--dim);transition:background .15s}
.toggle.on .dot{background:var(--green)}
.spacer{flex:1}
.status{font-size:11px;color:var(--dim);padding:3px 8px;background:#1e293b;border-radius:4px;border:1px solid var(--border)}
.status b{color:var(--text);font-weight:600}
#live-dot{width:8px;height:8px;border-radius:50%;background:var(--green);animation:pulse 2s infinite;margin-left:4px}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
#header{display:flex;align-items:center;gap:10px;padding:14px 26px;background:var(--panel);border-bottom:1px solid var(--border);flex-shrink:0}
#header .ticker{font-size:22px;font-weight:700;color:#fff;letter-spacing:.5px}
#header .spacer{flex:1}
#header .status{font-size:12px;color:var(--dim);padding:6px 12px;background:#1e293b;border-radius:6px;border:1px solid var(--border)}
#header .status b{color:var(--text);font-weight:600}

/* --- big tabs across the top --- */
#tabbar{display:flex;background:var(--panel);border-bottom:1px solid var(--border);flex-shrink:0;padding:0 18px}
.tab{flex:1;max-width:260px;padding:16px 20px;font-size:14px;font-weight:600;background:transparent;color:var(--dim);border:none;border-bottom:3px solid transparent;cursor:pointer;transition:all .15s;letter-spacing:.3px}
.tab:hover{color:var(--text);background:#151f2e}
.tab.active{color:#fff;border-bottom-color:var(--accent);background:#16202f}
.tab .count{display:inline-block;font-size:11px;font-weight:700;margin-left:9px;padding:2px 8px;border-radius:10px;background:#1e293b;color:var(--dim)}
.tab.active .count{background:var(--accent);color:#fff}

.pane{display:none;flex:1;min-height:0;flex-direction:column}
.pane.active{display:flex}

/* --- chart controls: only rendered inside the Chart pane --- */
#chart-toolbar{display:flex;align-items:center;gap:8px;padding:12px 26px;border-bottom:1px solid var(--border);flex-shrink:0;flex-wrap:wrap}
#chart-toolbar .sep{width:1px;height:22px;background:var(--border);margin:0 6px}
#chart-toolbar .spacer{flex:1}
.btn-group{display:flex;gap:1px;background:var(--border);border-radius:6px;overflow:hidden}
.btn{padding:7px 15px;font-size:12px;font-weight:600;background:#1e293b;color:var(--dim);border:none;cursor:pointer;transition:all .15s}
.btn:hover{background:#2d3748;color:var(--text)}
.btn.active{background:var(--accent);color:#fff}
#reset-zoom-btn{border-radius:6px;border:1px solid var(--border)}
.toggle{display:flex;align-items:center;gap:6px;padding:7px 12px;font-size:12px;color:var(--dim);cursor:pointer;border-radius:6px;user-select:none;transition:all .15s}
.toggle:hover{background:#1e293b}
.toggle.on{color:var(--text)}
.toggle .dot{width:8px;height:8px;border-radius:50%;background:var(--dim);transition:background .15s}
.toggle.on .dot{background:#22c55e}

/* --- log rows as stacked cards, newest on top --- */
.tablewrap{flex:1;overflow-y:auto;padding:20px 26px 26px}
.logcard{display:flex;align-items:center;gap:18px;padding:14px 18px;margin-bottom:9px;background:var(--panel);border:1px solid var(--border);border-left:3px solid var(--border);border-radius:8px;transition:all .15s}
.logcard:hover{background:#16202f;border-color:#2d3a4d;transform:translateX(2px)}
.logcard.marked{border-left-color:#f59e0b;background:#1a1710}
.logcard.c-STRONG_BUY,.logcard.c-BUY{border-left-color:#22c55e}
.logcard.c-SELL,.logcard.c-STRONG_SELL{border-left-color:#ef4444}
.lc-time{font-size:12px;color:var(--dim);font-family:ui-monospace,Consolas,monospace;min-width:118px}
.lc-dir{font-weight:700;font-size:12px;padding:5px 11px;border-radius:5px;min-width:104px;text-align:center}
.d-STRONG_BUY{background:#052e16;color:#22c55e}.d-BUY{background:#08301a;color:#4ade80}
.d-WATCH{background:#1e293b;color:#8b98a9}
.d-SELL{background:#3a2408;color:#fb923c}.d-STRONG_SELL{background:#3b0d0d;color:#ef4444}
.lc-stat{display:flex;flex-direction:column;gap:3px;min-width:82px}
.lc-label{font-size:9px;color:#5b6675;text-transform:uppercase;letter-spacing:.8px}
.lc-val{font-size:13px;color:var(--text);font-family:ui-monospace,Consolas,monospace}
.lc-val.up{color:#22c55e}.lc-val.down{color:#ef4444}.lc-val.dim{color:#5b6675}
.lc-spacer{flex:1}
.markbtn{padding:9px 18px;font-size:12px;font-weight:600;border:1px solid var(--border);background:#1e293b;color:var(--dim);border-radius:6px;cursor:pointer;transition:all .15s;white-space:nowrap}
.markbtn:hover{background:#2d3748;color:var(--text);border-color:#3d4a5d}
.markbtn.marked{background:#78350f;border-color:#f59e0b;color:#fbbf24}
.markbtn.marked:hover{background:#8b3f10}
.empty{padding:70px;text-align:center;color:var(--dim);font-size:14px}
.logcard{cursor:pointer}
.lc-hint{font-size:10px;color:#465264;letter-spacing:.5px;margin-right:4px}
/* --- signal detail panel, shown on the chart tab --- */
#detail{position:absolute;top:12px;left:12px;z-index:30;width:290px;background:rgba(17,24,39,.97);border:1px solid var(--border);border-radius:10px;padding:16px 18px;box-shadow:0 12px 40px rgba(0,0,0,.55);display:none}
#detail.open{display:block}
#detail h4{font-size:11px;color:var(--dim);text-transform:uppercase;letter-spacing:1px;margin-bottom:3px}
#detail .dtime{font-size:12px;color:var(--text);font-family:ui-monospace,Consolas,monospace;margin-bottom:12px}
#detail .dbadge{display:inline-block;font-weight:700;font-size:13px;padding:6px 13px;border-radius:6px;margin-bottom:14px}
#detail .drow{display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #1b2534;font-size:12px}
#detail .drow:last-of-type{border:none}
#detail .dk{color:#5b6675}
#detail .dv{color:var(--text);font-family:ui-monospace,Consolas,monospace}
#detail .dv.up{color:#22c55e}#detail .dv.down{color:#ef4444}#detail .dv.dim{color:#5b6675}
#detail .dsec{font-size:9px;color:#465264;text-transform:uppercase;letter-spacing:1px;margin:13px 0 5px}
#detail .dclose{position:absolute;top:11px;right:13px;color:#5b6675;cursor:pointer;font-size:17px;line-height:1}
#detail .dclose:hover{color:var(--text)}
#price-wrap{flex:1;min-height:0;position:relative}
#price-chart{width:100%;height:100%}
#divider{height:3px;background:var(--border);cursor:ns-resize;flex-shrink:0}
#divider:hover,#divider.dragging{background:var(--accent)}
#divider::after{content:'';position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);width:30px;height:3px;border-radius:2px;background:var(--dim)}
#score-wrap{height:30vh;min-height:80px;max-height:60vh;flex-shrink:0;position:relative}
#score-chart{width:100%;height:100%}
#score-label{position:absolute;top:6px;left:12px;font-size:10px;color:var(--dim);text-transform:uppercase;letter-spacing:1px;z-index:10;pointer-events:none}
/* Trade modal */
.modal-bg{display:none;position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:100;justify-content:center;align-items:center}
.modal-bg.open{display:flex}
.modal{background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:20px 24px;width:320px;box-shadow:0 20px 60px rgba(0,0,0,.5)}
.modal h3{font-size:14px;margin-bottom:12px;color:var(--text)}
.modal p{font-size:12px;color:var(--dim);margin-bottom:6px}
.modal .price-tag{font-size:20px;font-weight:700;margin:8px 0 16px}
.modal .price-tag.buy{color:var(--green)} .modal .price-tag.sell{color:var(--red)}
.modal .row{display:flex;gap:8px}
.modal button{flex:1;padding:8px;border:none;border-radius:6px;font-size:12px;font-weight:600;cursor:pointer;transition:all .15s}
.modal .confirm{background:var(--accent);color:#fff} .modal .confirm:hover{background:#2563eb}
.modal .cancel{background:#1e293b;color:var(--dim);border:1px solid var(--border)} .modal .cancel:hover{background:#2d3748}
/* Trades panel */
#trades-panel{position:absolute;top:8px;right:12px;background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:10px 14px;z-index:20;min-width:200px;max-height:250px;overflow-y:auto;display:none;font-size:11px}
#trades-panel.open{display:block}
#trades-panel h4{font-size:11px;color:var(--dim);text-transform:uppercase;letter-spacing:1px;margin-bottom:8px}
.trade-row{display:flex;justify-content:space-between;align-items:center;padding:4px 0;border-bottom:1px solid var(--border)}
.trade-row:last-child{border:none}
.trade-dir{font-weight:600;width:20px}
.trade-dir.buy{color:var(--green)} .trade-dir.sell{color:var(--red)}
.trade-price{color:var(--text);font-family:monospace}
.trade-del{color:var(--dim);cursor:pointer;font-size:13px;padding:0 4px}
.trade-del:hover{color:var(--red)}
#no-trades{color:var(--dim);font-style:italic}
</style>
</head>
<body>
<div id="header">
  <span class="ticker">%%TICKER%%</span>
  <span class="spacer"></span>
  <span class="status">Last: <b>%%LAST_INFO%%</b></span>
  <div id="live-dot" title="Live connection"></div>
</div>

<div id="tabbar">
  <button class="tab active" data-pane="all">All Logs<span class="count" id="c-all"></span></button>
  <button class="tab" data-pane="flag">Flagged<span class="count" id="c-flag"></span></button>
  <button class="tab" data-pane="chart">Chart<span class="count" id="c-chart"></span></button>
</div>

<div class="pane active" id="pane-all"><div class="tablewrap"><div id="tbl-all"></div></div></div>
<div class="pane" id="pane-flag"><div class="tablewrap"><div id="tbl-flag"></div></div></div>

<div class="pane" id="pane-chart">
<div id="chart-toolbar">
  <div class="btn-group" id="interval-btns">
    <button class="btn" data-iv="1h">1H</button>
    <button class="btn" data-iv="4h">4H</button>
    <button class="btn" data-iv="1d">1D</button>
    <button class="btn" data-iv="1w">1W</button>
  </div>
  <span class="sep"></span>
  <div class="btn-group">
    <button class="btn active" data-chart="candle">Candles</button>
    <button class="btn" data-chart="line">Line</button>
    <button class="btn" data-chart="area">Area</button>
  </div>
  <span class="sep"></span>
  <div class="toggle on" id="tog-vol"><span class="dot"></span>Volume</div>
  <div class="toggle on" id="tog-sig"><span class="dot"></span>Signals</div>
  <div class="toggle on" id="tog-lvl"><span class="dot"></span>Levels</div>
  <div class="toggle" id="tog-trades"><span class="dot"></span>Trade list</div>
  <span class="spacer"></span>
  <button class="btn" id="reset-zoom-btn" title="Fit all data">Reset Zoom</button>
</div>
<div id="price-wrap">
  <div id="price-chart"></div>
  <div id="detail">
    <span class="dclose" onclick="closeDetail()">&times;</span>
    <h4>Signal detail</h4>
    <div class="dtime" id="d-time"></div>
    <div class="dbadge" id="d-dir"></div>
    <div id="d-body"></div>
  </div>
  <div id="trades-panel">
    <h4>Marked Trades</h4>
    <div id="trades-list"></div>
  </div>
</div>
<div id="divider"></div>
<div id="score-wrap">
  <span id="score-label">Signal Score</span>
  <div id="score-chart"></div>
</div>
</div>

<div class="modal-bg" id="trade-modal">
  <div class="modal">
    <h3 id="modal-title">Mark as Trade?</h3>
    <p id="modal-dir"></p>
    <div class="price-tag" id="modal-price"></div>
    <p id="modal-exits" style="font-size:12px;margin-bottom:10px;display:none"></p>
    <p id="modal-time" style="margin-bottom:16px"></p>
    <div class="row">
      <button class="cancel" onclick="closeModal()">Cancel</button>
      <button class="confirm" onclick="confirmTrade()">Mark Trade</button>
    </div>
  </div>
</div>

<script>
const TICKER='%%TICKER%%', SYMBOL='%%SYMBOL%%';
const LOGROWS=%%ROWS%%;
const initCandles=%%CANDLES%%, initVolumes=%%VOLUMES%%, signalMarkers=%%MARKERS%%, scoreData=%%SCORES%%;
let currentInterval='%%INTERVAL%%';

// ---- Chart setup ----
const OPTS={layout:{background:{type:'solid',color:'#0a0e17'},textColor:'#9ca3af',fontSize:11},grid:{vertLines:{color:'#1f293720'},horzLines:{color:'#1f293720'}},crosshair:{mode:LightweightCharts.CrosshairMode.Normal,vertLine:{color:'#3b82f640',labelBackgroundColor:'#3b82f6'},horzLine:{color:'#3b82f640',labelBackgroundColor:'#3b82f6'}},rightPriceScale:{borderColor:'#1f2937',scaleMargins:{top:0.05,bottom:0.12}},timeScale:{borderColor:'#1f2937',timeVisible:true,secondsVisible:false},handleScroll:{mouseWheel:true,pressedMouseMove:true,horzTouchDrag:true,vertTouchDrag:true},handleScale:{mouseWheel:false,pinch:true,axisPressedMouseMove:{time:true,price:true},axisDoubleClickReset:{time:true,price:true}},kineticScroll:{touch:true,mouse:false}};

const pc=LightweightCharts.createChart(document.getElementById('price-chart'),OPTS);
let candleSeries=pc.addCandlestickSeries({upColor:'#22c55e',downColor:'#ef4444',borderUpColor:'#22c55e',borderDownColor:'#ef4444',wickUpColor:'#22c55e80',wickDownColor:'#ef444480'});
candleSeries.setData(initCandles);

const volSeries=pc.addHistogramSeries({priceFormat:{type:'volume'},priceScaleId:'vol'});
pc.priceScale('vol').applyOptions({scaleMargins:{top:0.85,bottom:0}});
volSeries.setData(initVolumes);

let lineSeries=null, areaSeries=null, activeChartType='candle';
let lineData=initCandles.map(c=>({time:c.time,value:c.close}));

// ---- Score chart ----
const sc=LightweightCharts.createChart(document.getElementById('score-chart'),{...OPTS,rightPriceScale:{borderColor:'#1f2937',scaleMargins:{top:0.08,bottom:0.08}},layout:{...OPTS.layout,fontSize:10}});
const anchor=sc.addLineSeries({color:'transparent',lineWidth:0,crosshairMarkerVisible:false,lastValueVisible:false,priceLineVisible:false});
if(initCandles.length>=2)anchor.setData([{time:initCandles[0].time,value:0},{time:initCandles[initCandles.length-1].time,value:100}]);
const TH=[{p:75,c:'#22c55e',t:'Strong Buy'},{p:60,c:'#4ade80',t:'Buy'},{p:40,c:'#fb923c',t:'Sell'},{p:25,c:'#ef4444',t:'Strong Sell'}];
const pLines=[];TH.forEach(l=>{pLines.push(anchor.createPriceLine({price:l.p,color:l.c,lineWidth:1,lineStyle:LightweightCharts.LineStyle.Dashed,axisLabelVisible:true,title:l.t}));});
if(scoreData.length){const bs=sc.addBaselineSeries({baseValue:{type:'price',price:50},topLineColor:'#22c55e',bottomLineColor:'#ef4444',topFillColor1:'rgba(34,197,94,0.18)',topFillColor2:'rgba(34,197,94,0.02)',bottomFillColor1:'rgba(239,68,68,0.02)',bottomFillColor2:'rgba(239,68,68,0.18)',lineWidth:2});bs.setData(scoreData);}

// Sync
pc.timeScale().subscribeVisibleLogicalRangeChange(r=>{if(r)sc.timeScale().setVisibleLogicalRange(r)});
sc.timeScale().subscribeVisibleLogicalRangeChange(r=>{if(r)pc.timeScale().setVisibleLogicalRange(r)});
pc.timeScale().fitContent();sc.timeScale().fitContent();

// ---- Trades (localStorage) ----
const TRADE_KEY='signal_trades_'+TICKER;
function loadTrades(){try{return JSON.parse(localStorage.getItem(TRADE_KEY))||[];}catch(e){return[];}}
function saveTrades(t){localStorage.setItem(TRADE_KEY,JSON.stringify(t));}
let trades=loadTrades();

let tradePriceLines=[];
function clearTradeLines(){
  const series=lineSeries||areaSeries||candleSeries;
  tradePriceLines.forEach(pl=>{try{series.removePriceLine(pl);}catch(e){}});
  tradePriceLines=[];
}
function drawTradeLines(){
  clearTradeLines();
  const series=lineSeries||areaSeries||candleSeries;
  trades.forEach(t=>{
    if(t.target!=null){
      tradePriceLines.push(series.createPriceLine({price:+t.target,color:'#22c55e',lineWidth:1,lineStyle:LightweightCharts.LineStyle.Dotted,axisLabelVisible:true,title:'TP'}));
    }
    if(t.stop!=null){
      tradePriceLines.push(series.createPriceLine({price:+t.stop,color:'#ef4444',lineWidth:1,lineStyle:LightweightCharts.LineStyle.Dotted,axisLabelVisible:true,title:'SL'}));
    }
  });
}

function buildMarkers(){
  // CHART SHOWS ONLY MARKED TRADES — a signal appears here only after you
  // mark it from the All Logs / Flagged tab. Unmarked signals stay in the
  // tables so the chart reflects decisions, not raw model output.
  const M2 = trades.map(t=>({
    time:t.time,
    position:(t.direction||'').includes('SELL')?'aboveBar':'belowBar',
    color:'#fbbf24', shape:'square', text:'TRADE', size:2
  })).sort((a,b)=>a.time-b.time);
  const series=lineSeries||areaSeries||candleSeries;
  series.setMarkers(M2);
  drawTradeLines();
  const el=document.getElementById('c-chart');
  if(el) el.textContent = trades.length ? trades.length : '';
}

function isMarked(time){ return trades.some(t=>t.time===time); }

function toggleMark(time){
  const i = trades.findIndex(t=>t.time===time);
  if(i>=0){ trades.splice(i,1); }
  else {
    const r = LOGROWS.find(x=>x.time===time);
    if(!r) return;
    trades.push({time:r.time, direction:r.dir, price:r.price,
                 target:r.target, stop:r.stop, rr:r.rr});
  }
  saveTrades(trades); buildMarkers(); renderTables(); renderTradesPanel();
}

function fmt(v,d){ return (v===null||v===undefined) ? '—' : Number(v).toLocaleString(undefined,{maximumFractionDigits:d===undefined?2:d}); }

function renderTable(rows, elId){
  const el=document.getElementById(elId);
  if(!rows.length){ el.innerHTML='<div class="empty">Nothing logged yet.</div>'; return; }
  // rows arrive newest-first; render as stacked cards so the most recent
  // check is always at the top of the list.
  el.innerHTML = rows.map(r=>{
    const m=isMarked(r.time);
    const tgt = r.target===null||r.target===undefined ? '<span class="lc-val dim">—</span>'
              : '<span class="lc-val up">'+fmt(r.target,2)+'</span>';
    const stp = r.stop===null||r.stop===undefined ? '<span class="lc-val dim">—</span>'
              : '<span class="lc-val down">'+fmt(r.stop,2)+'</span>';
    const ml  = r.ml===null||r.ml===undefined ? '<span class="lc-val dim">—</span>'
              : '<span class="lc-val">'+fmt(r.ml,0)+'%</span>';
    return '<div class="logcard c-'+r.dir+(m?' marked':'')+'" onclick="openDetail('+r.time+')">'+
      '<span class="lc-time">'+r.ts+'</span>'+
      '<span class="lc-dir d-'+r.dir+'">'+r.dir.replace('_',' ')+'</span>'+
      '<div class="lc-stat"><span class="lc-label">Score</span>'+
        '<span class="lc-val">'+fmt(r.score,2)+'</span></div>'+
      '<div class="lc-stat"><span class="lc-label">ML</span>'+ml+'</div>'+
      '<div class="lc-stat"><span class="lc-label">Price</span>'+
        '<span class="lc-val">'+fmt(r.price,2)+'</span></div>'+
      '<div class="lc-stat"><span class="lc-label">Target</span>'+tgt+'</div>'+
      '<div class="lc-stat"><span class="lc-label">Stop</span>'+stp+'</div>'+
      '<span class="lc-spacer"></span>'+
      '<span class="lc-hint">click for detail</span>'+
      '<button class="markbtn'+(m?' marked':'')+'" onclick="event.stopPropagation();toggleMark('+r.time+')">'+
        (m?'✓ Marked':'Mark Trade')+'</button>'+
    '</div>';
  }).join('');
}

function renderTables(){
  const flagged = LOGROWS.filter(r=>r.flagged);
  renderTable(LOGROWS,'tbl-all');
  renderTable(flagged,'tbl-flag');
  document.getElementById('c-all').textContent = LOGROWS.length;
  document.getElementById('c-flag').textContent = flagged.length;
}

function fmtOr(v,d,cls){
  if(v===null||v===undefined) return '<span class="dv dim">—</span>';
  return '<span class="dv'+(cls?' '+cls:'')+'">'+fmt(v,d)+'</span>';
}
function drow(k,v){ return '<div class="drow"><span class="dk">'+k+'</span>'+v+'</div>'; }

function openDetail(time){
  const r = LOGROWS.find(x=>x.time===time);
  if(!r) return;
  // Jump to the Chart tab first so the chart has real dimensions to work with
  document.querySelector('.tab[data-pane="chart"]').click();

  document.getElementById('d-time').textContent = r.ts + ' UTC';
  const badge = document.getElementById('d-dir');
  badge.textContent = r.dir.replace('_',' ');
  badge.className = 'dbadge d-' + r.dir;

  let h = '';
  h += '<div class="dsec">Score build-up</div>';
  h += drow('Step 1 · pattern', fmtOr(r.initial,2));
  h += drow('Step 2 · after gate', fmtOr(r.gated,2));
  h += drow('Step 3 · indicators', fmtOr(r.indicator,2));
  h += drow('Final score', fmtOr(r.score,2));
  h += '<div class="dsec">Context</div>';
  h += drow('Decision', '<span class="dv">'+(r.decision||'—')+'</span>');
  h += drow('Sentiment gate', '<span class="dv">'+(r.gate||'—')+
            (r.gate_mult!==null&&r.gate_mult!==undefined?' ×'+fmt(r.gate_mult,2):'')+'</span>');
  h += drow('ML confidence', r.ml===null||r.ml===undefined?fmtOr(null):'<span class="dv">'+fmt(r.ml,0)+'%</span>');
  h += drow('VIX', fmtOr(r.vix,1));
  h += drow('ATR', fmtOr(r.atr,2));
  h += '<div class="dsec">Trade levels</div>';
  h += drow('Price at signal', fmtOr(r.price,2));
  h += drow('Target', fmtOr(r.target,2,'up'));
  h += drow('Stop', fmtOr(r.stop,2,'down'));
  h += drow('Risk : reward', fmtOr(r.rr,1));
  document.getElementById('d-body').innerHTML = h;
  document.getElementById('detail').classList.add('open');

  // Centre the chart on that moment (~40 bars of context either side)
  setTimeout(()=>{
    const bar = (C.length>1) ? (C[1].time - C[0].time) : 14400;
    pc.timeScale().setVisibleRange({from: time - bar*40, to: time + bar*40});
  }, 60);
}
function closeDetail(){ document.getElementById('detail').classList.remove('open'); }

// --- Wheel zoom anchored to the CURSOR, not the chart edge -------------
// The built-in mouseWheel scaling is disabled below so these don't fight;
// this keeps whatever is under the pointer pinned while zooming around it.
(function(){
  const el = document.getElementById('price-chart');
  el.addEventListener('wheel', e => {
    const r = pc.timeScale().getVisibleLogicalRange();
    if(!r) return;
    e.preventDefault();
    const rect = el.getBoundingClientRect();
    const frac = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
    const span = r.to - r.from;
    const anchor = r.from + span * frac;      // logical index under the cursor
    const k = e.deltaY > 0 ? 1.15 : 1/1.15;   // out : in
    pc.timeScale().setVisibleLogicalRange({
      from: anchor - (anchor - r.from) * k,
      to:   anchor + (r.to - anchor) * k
    });
  }, {passive:false});
})();

// Tab switching — charts need a resize nudge when their pane becomes visible
document.querySelectorAll('.tab').forEach(b=>b.addEventListener('click',()=>{
  document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));
  document.querySelectorAll('.pane').forEach(x=>x.classList.remove('active'));
  b.classList.add('active');
  document.getElementById('pane-'+b.dataset.pane).classList.add('active');
  if(b.dataset.pane==='chart'){
    setTimeout(()=>{
      const pc_el=document.getElementById('price-chart'), sc_el=document.getElementById('score-chart');
      pc.applyOptions({width:pc_el.clientWidth,height:pc_el.clientHeight});
      sc.applyOptions({width:sc_el.clientWidth,height:sc_el.clientHeight});
      pc.timeScale().fitContent(); sc.timeScale().fitContent();
    },30);
  }
}));

function renderTradesPanel(){
  const list=document.getElementById('trades-list');
  if(!trades.length){list.innerHTML='<div id="no-trades">Click a signal marker to mark a trade</div>';return;}
  list.innerHTML=trades.map((t,i)=>{
    const isBuy=!t.direction.includes('SELL');
    return `<div class="trade-row"><span class="trade-dir ${isBuy?'buy':'sell'}">${isBuy?'▲':'▼'}</span><span class="trade-price">$${Number(t.price).toLocaleString()}</span><span style="color:var(--dim)">${new Date(t.time*1000).toLocaleDateString()}</span><span class="trade-del" onclick="removeTrade(${i})">✕</span></div>`;
  }).join('');
}

function removeTrade(i){trades.splice(i,1);saveTrades(trades);renderTables();buildMarkers();renderTradesPanel();}

// ---- Click to mark trade ----
let pendingTrade=null;
pc.subscribeClick(param=>{
  if(!param.time)return;
  // Find closest signal marker
  const closest=signalMarkers.reduce((best,m)=>{const d=Math.abs(m.time-param.time);return d<best.d?{d,m}:best;},{d:Infinity,m:null});
  if(!closest.m||closest.d>86400*2)return; // within 2 days
  const m=closest.m;
  // Find price at that candle
  const candle=initCandles.find(c=>c.time===m.time);
  const price=candle?candle.close:param.point?param.point.y:0;
  const dir=m.text==='SB'?'STRONG_BUY':m.text==='B'?'BUY':m.text==='S'?'SELL':m.text==='SS'?'STRONG_SELL':'WATCH';
  if(dir==='WATCH')return;
  pendingTrade={time:m.time,direction:dir,price,target:m.target,stop:m.stop,rr:m.rr};
  // Show modal
  const isBuy=!dir.includes('SELL');
  document.getElementById('modal-title').textContent=isBuy?'Mark Buy Trade?':'Mark Sell Trade?';
  document.getElementById('modal-dir').textContent=dir.replace('_',' ');
  const priceEl=document.getElementById('modal-price');
  priceEl.textContent='$'+Number(price).toLocaleString(undefined,{maximumFractionDigits:2});
  priceEl.className='price-tag '+(isBuy?'buy':'sell');
  // Exit levels line
  const exitEl=document.getElementById('modal-exits');
  if(m.target!=null&&m.stop!=null){
    exitEl.innerHTML=`<span style="color:#22c55e">Target $${Number(m.target).toLocaleString()}</span> &nbsp;·&nbsp; <span style="color:#ef4444">Stop $${Number(m.stop).toLocaleString()}</span>${m.rr?` &nbsp;·&nbsp; <span style="color:#9ca3af">R:R ${m.rr}</span>`:''}`;
    exitEl.style.display='block';
  } else { exitEl.style.display='none'; }
  document.getElementById('modal-time').textContent=new Date(m.time*1000).toLocaleString();
  document.getElementById('trade-modal').classList.add('open');
});

function closeModal(){document.getElementById('trade-modal').classList.remove('open');pendingTrade=null;}
function confirmTrade(){
  if(!pendingTrade)return;
  if(!trades.find(t=>t.time===pendingTrade.time)){trades.push(pendingTrade);saveTrades(trades);}
  // pendingTrade already carries target/stop/rr from the clicked marker
  buildMarkers();renderTradesPanel();closeModal();
  // Open trades panel
  document.getElementById('trades-panel').classList.add('open');
  document.getElementById('tog-trades').classList.add('on');
}

// ---- Chart type switching ----
function switchChart(type){
  activeChartType=type;
  if(lineSeries){pc.removeSeries(lineSeries);lineSeries=null;}
  if(areaSeries){pc.removeSeries(areaSeries);areaSeries=null;}
  if(type==='candle'){candleSeries.applyOptions({upColor:'#22c55e',downColor:'#ef4444',borderUpColor:'#22c55e',borderDownColor:'#ef4444',wickUpColor:'#22c55e80',wickDownColor:'#ef444480'});}
  else{candleSeries.applyOptions({upColor:'transparent',downColor:'transparent',borderUpColor:'transparent',borderDownColor:'transparent',wickUpColor:'transparent',wickDownColor:'transparent'});
  if(type==='line'){lineSeries=pc.addLineSeries({color:'#3b82f6',lineWidth:2});lineSeries.setData(lineData);}
  else{areaSeries=pc.addAreaSeries({lineColor:'#3b82f6',lineWidth:2,topColor:'#3b82f620',bottomColor:'#3b82f602'});areaSeries.setData(lineData);}}
  buildMarkers();
  document.querySelectorAll('[data-chart]').forEach(b=>b.classList.toggle('active',b.dataset.chart===type));
}
document.querySelectorAll('[data-chart]').forEach(b=>b.addEventListener('click',()=>switchChart(b.dataset.chart)));

// ---- Interval switching (fetches from Binance REST) ----
async function switchInterval(iv){
  try{
    const r=await fetch(`%%REST_BASE%%/api/v3/klines?symbol=${SYMBOL}&interval=${iv}&limit=500`);
    const d=await r.json();
    const candles=d.map(k=>({time:Math.floor(k[0]/1000),open:+k[1],high:+k[2],low:+k[3],close:+k[4]}));
    const vols=d.map(k=>({time:Math.floor(k[0]/1000),value:+k[5],color:+k[4]>=+k[1]?'#22c55e30':'#ef444430'}));
    lineData=candles.map(c=>({time:c.time,value:c.close}));
    candleSeries.setData(candles);volSeries.setData(vols);
    if(lineSeries)lineSeries.setData(lineData);
    if(areaSeries)areaSeries.setData(lineData);
    buildMarkers();
    // Reconnect WebSocket
    currentInterval=iv;connectWS();
    document.querySelectorAll('[data-iv]').forEach(b=>b.classList.toggle('active',b.dataset.iv===iv));
    pc.timeScale().fitContent();
  }catch(e){console.error('interval switch failed',e);}
}
document.querySelectorAll('[data-iv]').forEach(b=>b.addEventListener('click',()=>switchInterval(b.dataset.iv)));
document.getElementById('reset-zoom-btn').addEventListener('click',()=>{pc.timeScale().fitContent();sc.timeScale().fitContent();});

// ---- Toggles ----
function tog(id,on,off){document.getElementById(id).addEventListener('click',function(){this.classList.toggle('on');this.classList.contains('on')?on():off();});}
tog('tog-vol',()=>volSeries.applyOptions({visible:true}),()=>volSeries.applyOptions({visible:false}));
tog('tog-sig',()=>buildMarkers(),()=>{const s=lineSeries||areaSeries||candleSeries;s.setMarkers(trades.map(t=>({time:t.time,position:t.direction.includes('SELL')?'aboveBar':'belowBar',color:'#fbbf24',shape:'square',text:'TRADE',size:2})));});
tog('tog-lvl',()=>pLines.forEach((pl,i)=>pl.applyOptions({color:TH[i].c})),()=>pLines.forEach(pl=>pl.applyOptions({color:'transparent'})));
tog('tog-trades',()=>document.getElementById('trades-panel').classList.add('open'),()=>document.getElementById('trades-panel').classList.remove('open'));

// ---- WebSocket live price ----
let ws=null;
function connectWS(){
  if(ws){ws.close();ws=null;}
  const url=`%%WS_BASE%%/ws/${SYMBOL.toLowerCase()}@kline_${currentInterval}`;
  ws=new WebSocket(url);
  ws.onmessage=e=>{
    const k=JSON.parse(e.data).k;
    const c={time:Math.floor(k.t/1000),open:+k.o,high:+k.h,low:+k.l,close:+k.c};
    candleSeries.update(c);
    if(lineSeries)lineSeries.update({time:c.time,value:c.close});
    if(areaSeries)areaSeries.update({time:c.time,value:c.close});
    volSeries.update({time:c.time,value:+k.v,color:c.close>=c.open?'#22c55e30':'#ef444430'});
  };
  ws.onclose=()=>{document.getElementById('live-dot').style.background='#ef4444';setTimeout(connectWS,5000);};
  ws.onopen=()=>{document.getElementById('live-dot').style.background='#22c55e';};
}
connectWS();

// ---- Divider drag ----
const dv=document.getElementById('divider'),sw=document.getElementById('score-wrap');let drag=false;
dv.addEventListener('mousedown',e=>{drag=true;dv.classList.add('dragging');e.preventDefault();});
document.addEventListener('mousemove',e=>{if(!drag)return;const h=Math.max(80,Math.min(window.innerHeight*.6,window.innerHeight-e.clientY-2));sw.style.height=h+'px';pc.applyOptions({height:document.getElementById('price-chart').clientHeight});sc.applyOptions({height:h});});
document.addEventListener('mouseup',()=>{drag=false;dv.classList.remove('dragging');});

// ---- Resize ----
new ResizeObserver(()=>{pc.applyOptions({width:document.getElementById('price-chart').clientWidth,height:document.getElementById('price-chart').clientHeight});sc.applyOptions({width:document.getElementById('score-chart').clientWidth,height:sw.clientHeight});}).observe(document.body);

// ---- Init ----
document.querySelectorAll('[data-iv]').forEach(b=>b.classList.toggle('active',b.dataset.iv===currentInterval));
renderTables();buildMarkers();renderTradesPanel();
</script>
</body>
</html>"""


def generate_html_chart(ticker: str, ohlcv: pd.DataFrame, log: pd.DataFrame,
                        output_path: str = "signal_chart.html",
                        interval: str = "4h") -> str:
    """Generates an interactive HTML chart and returns the absolute path."""
    import json

    binance_symbol = cf.to_binance_symbol(ticker)

    candles, volumes = [], []
    for ts, row in ohlcv.iterrows():
        t = int(ts.timestamp())
        candles.append({"time": t, "open": row["Open"], "high": row["High"],
                        "low": row["Low"], "close": row["Close"]})
        clr = "#22c55e30" if row["Close"] >= row["Open"] else "#ef444430"
        volumes.append({"time": t, "value": row["Volume"], "color": clr})

    markers, scores = [], []
    MMAP = {
        "STRONG_BUY":  ("belowBar", "#22c55e", "arrowUp",   "SB", 2),
        "BUY":         ("belowBar", "#4ade80", "arrowUp",   "B",  1),
        "WATCH":       ("belowBar", "#6b7280", "circle",    "",   0),
        "SELL":        ("aboveBar", "#fb923c", "arrowDown", "S",  1),
        "STRONG_SELL": ("aboveBar", "#ef4444", "arrowDown", "SS", 2),
    }
    def _num(v):
        try:
            f = float(v)
            return f if f == f else None  # drop NaN
        except (TypeError, ValueError):
            return None

    if not log.empty:
        for _, row in log.iterrows():
            t = int(row["timestamp_utc"].timestamp())
            d = row.get("direction", "WATCH")
            pos, clr, shp, txt, sz = MMAP.get(d, MMAP["WATCH"])
            markers.append({
                "time": t, "position": pos, "color": clr,
                "shape": shp, "text": txt, "size": max(sz, 1),
                # exit-level data travels with the marker for click-to-view
                "entry": _num(row.get("price")),
                "target": _num(row.get("target_price")),
                "stop": _num(row.get("stop_price")),
                "rr": _num(row.get("risk_reward")),
            })
            scores.append({"time": t, "value": float(row["final_score"])})

    if not log.empty:
        last = log.iloc[-1]
        last_info = f'{last.get("direction", "—")} &middot; {last.get("final_score", 0):.1f}'
        ml_val = last.get("ml_confidence")
        if ml_val is not None and pd.notna(ml_val):
            last_info += f' &middot; ML {float(ml_val):.0f}%'
    else:
        last_info = "No signals yet"

    # Full log rows for the All Logs / Flagged tables
    rows = []
    if not log.empty:
        for _, r in log.iterrows():
            d = r.get("direction", "WATCH")
            rows.append({
                "time": int(r["timestamp_utc"].timestamp()),
                "ts": r["timestamp_utc"].strftime("%Y-%m-%d %H:%M"),
                "dir": d,
                "score": _num(r.get("final_score")),
                "ml": _num(r.get("ml_confidence")),
                "price": _num(r.get("price")),
                "target": _num(r.get("target_price")),
                "stop": _num(r.get("stop_price")),
                "rr": _num(r.get("risk_reward")),
                "flagged": d in ("BUY", "STRONG_BUY", "SELL", "STRONG_SELL"),
                # full model output, for the detail view
                "decision": r.get("decision"),
                "initial": _num(r.get("initial_score")),
                "gated": _num(r.get("gated_score")),
                "indicator": _num(r.get("indicator_final_score")),
                "vix": _num(r.get("vix_level")),
                "gate": r.get("gate_decision"),
                "gate_mult": _num(r.get("gate_multiplier")),
                "atr": _num(r.get("atr")),
            })
        rows.reverse()  # newest first

    html = (_HTML_TEMPLATE
            .replace("%%ROWS%%", json.dumps(rows))
            .replace("%%TICKER%%", ticker)
            .replace("%%SYMBOL%%", binance_symbol)
            .replace("%%INTERVAL%%", interval)
            .replace("%%LAST_INFO%%", last_info)
            .replace("%%WS_BASE%%", cf.BINANCE_WS_BASE)
            .replace("%%REST_BASE%%", cf.BINANCE_CHART_REST)
            .replace("%%CANDLES%%", json.dumps(candles))
            .replace("%%VOLUMES%%", json.dumps(volumes))
            .replace("%%MARKERS%%", json.dumps(markers))
            .replace("%%SCORES%%", json.dumps(scores)))

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    return os.path.abspath(output_path)


# ======================================================================
# LOCAL SERVER + REPLAY/LIVE MODES
# ======================================================================

def _start_server(directory, port=8089):
    """Start a simple HTTP server in a background thread, returns (server, port)."""
    import http.server
    import functools
    import threading

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=directory)
    handler.log_message = lambda *a: None  # suppress request logs

    for p in range(port, port + 20):
        try:
            server = http.server.HTTPServer(("localhost", p), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            return server, p
        except OSError:
            continue
    raise RuntimeError("Could not find an open port for the chart server")


def run_replay(ticker: str, log_path: str, price_interval: str, price_bars: int,
               save: str = None):
    import webbrowser

    print(f"Loading price for {ticker} (Binance {price_interval}, {price_bars} bars)...")
    ohlcv = fetch_price_ohlcv(ticker, interval=price_interval, bars=price_bars)
    log = load_log(log_path, ticker=ticker)
    print(f"Loaded {len(log)} logged ping(s) for {ticker} from {log_path}.")

    out_name = f"{ticker.lower()}_signals.html"
    chart_path = generate_html_chart(ticker, ohlcv, log, output_path=out_name,
                                     interval=price_interval)
    chart_dir = os.path.dirname(chart_path) or "."

    server, port = _start_server(chart_dir)
    url = f"http://localhost:{port}/{out_name}"
    print(f"Chart server running at {url}")
    print("Press Ctrl+C to stop.\n")
    webbrowser.open(url)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        server.shutdown()
        print("\nServer stopped.")


def run_live(ticker: str, log_path: str, interval_seconds: int,
             price_interval: str, price_bars: int, save: str = None):
    """Live mode: runs the pipeline periodically, logs pings, and serves the chart.
    The HTML chart auto-updates price via WebSocket; re-run this command or
    refresh the browser to pick up newly logged signal pings."""
    import webbrowser

    if not os.environ.get("ADANOS_API_KEY"):
        print("WARNING: ADANOS_API_KEY not set — Step 2 pings will fail.\n")

    # Initial chart generation
    print(f"Loading price for {ticker} (Binance {price_interval}, {price_bars} bars)...")
    ohlcv = fetch_price_ohlcv(ticker, interval=price_interval, bars=price_bars)
    log = load_log(log_path, ticker=ticker)

    out_name = f"{ticker.lower()}_signals.html"
    chart_path = generate_html_chart(ticker, ohlcv, log, output_path=out_name,
                                     interval=price_interval)
    chart_dir = os.path.dirname(chart_path) or "."

    server, port = _start_server(chart_dir)
    url = f"http://localhost:{port}/{out_name}"
    print(f"Chart at {url} — price updates live via WebSocket.")
    print(f"Pipeline re-runs every {interval_seconds}s. Refresh browser to see new signals.")
    print("Press Ctrl+C to stop.\n")
    webbrowser.open(url)

    try:
        while True:
            time.sleep(interval_seconds)
            stamp = datetime.now(timezone.utc)
            print(f"--- {stamp.strftime('%Y-%m-%d %H:%M:%S UTC')} ---")
            try:
                result = pl.run_full_pipeline(ticker, verbose=False)
                row = append_ping_to_log(result, log_path, timestamp=stamp)
                print(f"  {ticker}: {row['direction']} ({row['decision']}, "
                      f"score={row['final_score']}) — logged. Refresh browser to see it.")
                # Regenerate HTML with updated log
                log = load_log(log_path, ticker=ticker)
                ohlcv = fetch_price_ohlcv(ticker, interval=price_interval, bars=price_bars)
                generate_html_chart(ticker, ohlcv, log, output_path=out_name,
                                    interval=price_interval)
            except Exception as e:
                print(f"  {ticker}: FAILED — {type(e).__name__}: {e}")
    except KeyboardInterrupt:
        server.shutdown()
        print("\nStopped.")


def main_graph():
    parser = argparse.ArgumentParser(
        description="Interactive signal chart with live price feed.")
    parser.add_argument("ticker", help="e.g. BTC or ETH")
    parser.add_argument("--log-file", default=DEFAULT_LOG,
                         help=f"Ping log CSV (default {DEFAULT_LOG})")
    parser.add_argument("--live", action="store_true",
                         help="Also re-run the pipeline periodically and log pings")
    parser.add_argument("--interval-seconds", type=int, default=900,
                         help="Seconds between live pipeline pings (default 900)")
    parser.add_argument("--price-interval", default="4h",
                         help="Initial Binance kline interval (default 4h)")
    parser.add_argument("--price-bars", type=int, default=500,
                         help="How many historical bars to load (default 500)")
    parser.add_argument("--save", default=None)
    args = parser.parse_args()

    if args.live:
        run_live(args.ticker, args.log_file, args.interval_seconds,
                 args.price_interval, args.price_bars, save=args.save)
    else:
        run_replay(args.ticker, args.log_file, args.price_interval,
                   args.price_bars, save=args.save)


# ======================================================================
# CLI DISPATCHER — subcommands: monitor / graph
# ======================================================================

def main_check():
    parser = argparse.ArgumentParser(
        description="ONE-SHOT check across tickers — no loop, no desktop alerts. "
                    "Built for scheduled/headless runs (GitHub Actions, cron).")
    parser.add_argument("tickers", nargs="+", help="One or more tickers, e.g. BTC ETH SOL")
    parser.add_argument("--log-file", default="signal_log.csv")
    parser.add_argument("--confluence", action="store_true",
                         help="Evaluate the score+ML agreement gate")
    parser.add_argument("--log-all", action="store_true",
                         help="Log EVERY check (WATCH included), not just qualifying "
                              "confluence signals. Combine with --confluence to still see "
                              "which ones qualified, while keeping full history.")
    parser.add_argument("--ml-bull-min", type=float, default=55.0)
    parser.add_argument("--ml-bear-max", type=float, default=45.0)
    parser.add_argument("--confirm-days", type=int, default=1,
                         help="Require the same direction N days running before a "
                              "signal counts as confirmed (1 = off). Validated at 2 "
                              "on both BTC and ETH.")
    parser.add_argument("--long-only", action="store_true",
                         help="Suppress SELL/STRONG_SELL qualifications (short side "
                              "showed ~0R edge in the exit backtest)")
    args = parser.parse_args()

    run_single_check(args.tickers, log_file=args.log_file, confluence=args.confluence,
                     ml_bull_min=args.ml_bull_min, ml_bear_max=args.ml_bear_max,
                     log_all=args.log_all, long_only=args.long_only,
                     confirm_days=args.confirm_days)


# ======================================================================
# CLI DISPATCHER — subcommands: monitor / graph / check
# ======================================================================

def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("monitor", "graph", "check", "outcomes"):
        print("Usage: python live_tools.py <monitor|graph|check> [args...]\n"
              "  monitor BTC ETH ...  - continuous loop + desktop alerts (needs a machine that stays on)\n"
              "  graph BTC            - interactive chart with live price\n"
              "  check BTC ETH ...    - ONE-SHOT check, no loop (for cron / GitHub Actions)\n"
              "Run 'python live_tools.py <command> --help' for details.")
        sys.exit(1)

    command = sys.argv.pop(1)
    if command == "monitor":
        main_monitor()
    elif command == "outcomes":
        import argparse as _ap
        p = _ap.ArgumentParser(description="Resolve live signal episodes against "
                                            "daily bars and write signal_outcomes.csv "
                                            "(0 Adanos requests)")
        p.add_argument("--log-file", default=DEFAULT_LOG)
        p.add_argument("--out", default=OUTCOMES_FILE)
        p.add_argument("--max-hold-days", type=int, default=15)
        p.add_argument("--compare", action="store_true",
                       help="Also print live-vs-backtest calibration by score band")
        a = p.parse_args(sys.argv[2:])
        odf = resolve_outcomes(a.log_file, a.out, max_hold_days=a.max_hold_days)
        if a.compare and len(odf):
            print("\n" + compare_live_to_backtest(odf))
    elif command == "graph":
        main_graph()
    elif command == "check":
        main_check()


if __name__ == "__main__":
    main()
