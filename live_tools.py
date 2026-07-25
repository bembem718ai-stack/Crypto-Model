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


def passes_confluence(result: dict, ml_bull_min: float = 55.0,
                      ml_bear_max: float = 45.0) -> dict:
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
                     ml_bear_max: float = 45.0) -> list:
    """
    ONE pass over `tickers` — no loop, no sleep, no desktop alerts. Built for
    headless/scheduled environments (GitHub Actions, cron, etc.) where an
    external scheduler provides the "every N hours" cadence instead of an
    internal while-loop. Returns the list of qualifying results (empty if
    none qualified, or all results if confluence=False).
    """
    qualifying = []
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"--- {timestamp} --- checking {', '.join(tickers)}"
          f"{' (confluence mode)' if confluence else ''}")

    for ticker in tickers:
        try:
            result = pl.run_full_pipeline(ticker, verbose=False, use_ml=confluence)
            direction = result["combined"]["direction"]
            decision = result["combined"]["decision"]
            final_score = result["combined"]["final_score"]
            ml_conf = result["combined"].get("ml_confidence")

            if confluence:
                gate = passes_confluence(result, ml_bull_min, ml_bear_max)
                if not gate["qualifies"]:
                    print(f"  {ticker}: skip — {gate['reason']}")
                    continue
                ml_str = f", ML={ml_conf:.0f}%" if ml_conf is not None else ""
                print(f"  ✓ {ticker}: {direction} ({decision}, score={final_score}{ml_str}) "
                      f"— QUALIFIED: {gate['reason']}")
            else:
                print(f"  {ticker}: {direction} ({decision}, score={final_score})")

            try:
                append_ping_to_log(result, log_file)
            except Exception as e:  # noqa: BLE001
                print(f"  [log] append failed ({type(e).__name__}: {e})")

            qualifying.append(result)

        except Exception as e:  # noqa: BLE001 - one bad ticker shouldn't kill the run
            print(f"  {ticker}: FAILED — {type(e).__name__}: {e}")

    if confluence and not qualifying:
        print("  (no confluence signals this check)")

    return qualifying


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
    }

    header_needed = not os.path.exists(log_path) or os.path.getsize(log_path) == 0
    pd.DataFrame([row], columns=LOG_COLUMNS).to_csv(
        log_path, mode="a", header=header_needed, index=False)
    return row


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
<div id="toolbar">
  <span class="ticker">%%TICKER%%</span>
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
  <div class="toggle on" id="tog-vol"><span class="dot"></span>Vol</div>
  <div class="toggle on" id="tog-sig"><span class="dot"></span>Signals</div>
  <div class="toggle on" id="tog-lvl"><span class="dot"></span>Levels</div>
  <div class="toggle" id="tog-trades"><span class="dot"></span>Trades</div>
  <span class="sep"></span>
  <button class="btn" id="reset-zoom-btn" title="Fit all data / reset zoom">Reset Zoom</button>
  <span class="spacer"></span>
  <span class="status">Last: <b>%%LAST_INFO%%</b></span>
  <div id="live-dot" title="Live connection"></div>
</div>

<div id="price-wrap">
  <div id="price-chart"></div>
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
const initCandles=%%CANDLES%%, initVolumes=%%VOLUMES%%, signalMarkers=%%MARKERS%%, scoreData=%%SCORES%%;
let currentInterval='%%INTERVAL%%';

// ---- Chart setup ----
const OPTS={layout:{background:{type:'solid',color:'#0a0e17'},textColor:'#9ca3af',fontSize:11},grid:{vertLines:{color:'#1f293720'},horzLines:{color:'#1f293720'}},crosshair:{mode:LightweightCharts.CrosshairMode.Normal,vertLine:{color:'#3b82f640',labelBackgroundColor:'#3b82f6'},horzLine:{color:'#3b82f640',labelBackgroundColor:'#3b82f6'}},rightPriceScale:{borderColor:'#1f2937',scaleMargins:{top:0.05,bottom:0.12}},timeScale:{borderColor:'#1f2937',timeVisible:true,secondsVisible:false},handleScroll:{mouseWheel:true,pressedMouseMove:true,horzTouchDrag:true,vertTouchDrag:true},handleScale:{mouseWheel:true,pinch:true,axisPressedMouseMove:{time:true,price:true},axisDoubleClickReset:{time:true,price:true}},kineticScroll:{touch:true,mouse:false}};

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
  const base=document.getElementById('tog-sig').classList.contains('on')?signalMarkers:[];
  // Add trade markers (gold squares)
  const tradeM=trades.map(t=>({time:t.time,position:t.direction.includes('SELL')?'aboveBar':'belowBar',color:'#fbbf24',shape:'square',text:'TRADE',size:2}));
  const all=[...base,...tradeM].sort((a,b)=>a.time-b.time);
  const series=lineSeries||areaSeries||candleSeries;
  series.setMarkers(all);
  drawTradeLines();
}

function renderTradesPanel(){
  const list=document.getElementById('trades-list');
  if(!trades.length){list.innerHTML='<div id="no-trades">Click a signal marker to mark a trade</div>';return;}
  list.innerHTML=trades.map((t,i)=>{
    const isBuy=!t.direction.includes('SELL');
    return `<div class="trade-row"><span class="trade-dir ${isBuy?'buy':'sell'}">${isBuy?'▲':'▼'}</span><span class="trade-price">$${Number(t.price).toLocaleString()}</span><span style="color:var(--dim)">${new Date(t.time*1000).toLocaleDateString()}</span><span class="trade-del" onclick="removeTrade(${i})">✕</span></div>`;
  }).join('');
}

function removeTrade(i){trades.splice(i,1);saveTrades(trades);buildMarkers();renderTradesPanel();}

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
buildMarkers();renderTradesPanel();
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

    html = (_HTML_TEMPLATE
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
                         help="Only log runs where score direction AND ML agree")
    parser.add_argument("--ml-bull-min", type=float, default=55.0)
    parser.add_argument("--ml-bear-max", type=float, default=45.0)
    args = parser.parse_args()

    run_single_check(args.tickers, log_file=args.log_file, confluence=args.confluence,
                     ml_bull_min=args.ml_bull_min, ml_bear_max=args.ml_bear_max)


# ======================================================================
# CLI DISPATCHER — subcommands: monitor / graph / check
# ======================================================================

def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("monitor", "graph", "check"):
        print("Usage: python live_tools.py <monitor|graph|check> [args...]\n"
              "  monitor BTC ETH ...  - continuous loop + desktop alerts (needs a machine that stays on)\n"
              "  graph BTC            - interactive chart with live price\n"
              "  check BTC ETH ...    - ONE-SHOT check, no loop (for cron / GitHub Actions)\n"
              "Run 'python live_tools.py <command> --help' for details.")
        sys.exit(1)

    command = sys.argv.pop(1)
    if command == "monitor":
        main_monitor()
    elif command == "graph":
        main_graph()
    elif command == "check":
        main_check()


if __name__ == "__main__":
    main()
