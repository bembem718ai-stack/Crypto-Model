"""
research/basket_data.py
=======================
Export the EVENT RATE basket: the incumbent's own frames for ~86 tickers,
frozen so every later run is reproducible offline.

The incumbent's scoring is used UNCHANGED -- this module calls
pipeline.run_backtest itself rather than reimplementing it. What it adds
is the three guards, all on the research side (research rule 1: never
edit pipeline.py):

1. MACRO HOISTED. signal_engines.analyze calls fetch_macro on EVERY
   ticker, and fetch_macro pulls ^VIX and DX-Y.NYB. Across 86 tickers
   that is 172 redundant Yahoo downloads of two series that do not depend
   on the ticker at all. Memoized here, so it happens ONCE per run. Same
   pattern research rule 8 already sanctions for the 4h ATR: cache around
   pipeline, do not edit it.

2. THIN-TICKER GUARD. add_all_indicators computes SMA200 and friends; a
   ticker with under 200 daily rows produces an all-NaN trend column and
   a frame that silently scores on nothing. Such tickers are SKIPPED and
   REPORTED, never truncated into the pool.

3. OVERLAP ASSERTION. pipeline.py:931 joins the Yahoo daily frame to the
   4h squeeze history with how="inner". If the two feeds barely overlap,
   the result is a short frame and NOTHING says so -- the same bug class
   already fixed once at pipeline.py:919-926. Every ticker's tech span,
   squeeze span and merged span are recorded, and a merged frame covering
   less than OVERLAP_MIN_FRAC of the shorter input is flagged.

Nothing here decides a trade or changes a threshold.
"""
import os
import sys
import json
import time
import datetime as dt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tls                      # noqa: E402
tls.enable(verbose=True)

import pandas as pd             # noqa: E402
import pipeline as p            # noqa: E402
import signal_engines as cf     # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "basket")
UNIVERSE = os.path.join(ROOT, "research", "basket_universe.txt")

PERIOD = "max"
SQUEEZE_BARS = 20000
MIN_DAILY_ROWS = 200            # add_all_indicators needs >=200 for SMA200
OVERLAP_MIN_FRAC = 0.90
SLIM_COLS = ["Open", "High", "Low", "Close", "Volume",
             "direction", "combined_final_score"]


# ----------------------------------------------------------------------
# CACHES  (guard 1)
# ----------------------------------------------------------------------
_FETCH_CACHE = {}
_MACRO_CACHE = {}
_KLINE_CACHE = {}
_orig_fetch_data = cf.fetch_data
_orig_fetch_macro = cf.fetch_macro
_orig_klines = cf.fetch_klines_paginated


def _cached_fetch_data(ticker, period, interval, max_retries=3):
    k = (ticker, period, interval)
    if k not in _FETCH_CACHE:
        _FETCH_CACHE[k] = _orig_fetch_data(ticker, period, interval, max_retries)
    return _FETCH_CACHE[k]


def _cached_fetch_macro(period, interval):
    k = (period, interval)
    if k not in _MACRO_CACHE:
        print("  [macro] fetching ^VIX / DX-Y.NYB ONCE for the whole run")
        _MACRO_CACHE[k] = _orig_fetch_macro(period, interval)
    return _MACRO_CACHE[k]


def _cached_klines(symbol, interval="4h", target_bars=1000, **kw):
    k = (symbol, interval, target_bars)
    if k not in _KLINE_CACHE:
        _KLINE_CACHE[k] = _orig_klines(symbol, interval=interval,
                                       target_bars=target_bars, **kw)
    return _KLINE_CACHE[k]


def install_caches():
    cf.fetch_data = _cached_fetch_data
    cf.fetch_macro = _cached_fetch_macro
    cf.fetch_klines_paginated = _cached_klines
    p.cf.fetch_data = _cached_fetch_data
    p.cf.fetch_macro = _cached_fetch_macro
    p.cf.fetch_klines_paginated = _cached_klines


def clear_ticker_cache(keep_macro=True):
    """Drop per-ticker frames between tickers; keep the macro pull."""
    _FETCH_CACHE.clear()
    _KLINE_CACHE.clear()
    if not keep_macro:
        _MACRO_CACHE.clear()


# ----------------------------------------------------------------------
def universe():
    return [l.strip() for l in open(UNIVERSE, encoding="utf-8")
            if l.strip() and not l.startswith("#")]


def base_of(sym):
    return sym[:-4] if sym.endswith("USDT") else sym


def export_one(sym):
    """Freeze one ticker. Returns a record dict (status tells the story)."""
    base = base_of(sym)
    rec = {"symbol": sym, "base": base, "status": "ok"}

    # --- guard 2: thin ticker, checked BEFORE any scoring work
    ysym = p.to_yahoo_crypto_symbol(base)
    try:
        daily = cf.fetch_data(ysym, PERIOD, "1d")
    except Exception as e:
        rec.update(status="yahoo_failed", reason=str(e)[:120])
        return rec, None, None
    rec["yahoo_rows"] = len(daily)
    if len(daily) < MIN_DAILY_ROWS:
        rec.update(status="skipped_thin",
                   reason="only %d daily rows; add_all_indicators needs >=%d "
                          "for SMA200" % (len(daily), MIN_DAILY_ROWS))
        return rec, None, None

    # --- 4h feed
    try:
        bars = cf.fetch_klines_paginated(cf.to_binance_symbol(base),
                                         interval="4h", target_bars=SQUEEZE_BARS)
    except Exception as e:
        rec.update(status="klines_failed", reason=str(e)[:120])
        return rec, None, None
    if bars.empty:
        rec.update(status="klines_empty")
        return rec, None, None
    rec.update(bars_4h=len(bars), bars_first=str(bars.index.min())[:10],
               bars_last=str(bars.index.max())[:10])

    # --- the incumbent, UNCHANGED
    try:
        merged = p.run_backtest(base, period=PERIOD, squeeze_bars=SQUEEZE_BARS)
    except Exception as e:
        rec.update(status="backtest_failed", reason=str(e)[:160])
        return rec, None, None

    # --- guard 3: overlap assertion on the inner join
    tech_days = set(pd.to_datetime(daily.index).normalize())
    sq_days = set(pd.to_datetime(bars.index).normalize())
    expected = len(tech_days & sq_days)
    shorter = min(len(tech_days), len(sq_days))
    frac = (len(merged) / shorter) if shorter else 0.0
    rec.update(daily_rows=len(merged),
               daily_first=str(merged.index.min())[:10],
               daily_last=str(merged.index.max())[:10],
               tech_days=len(tech_days), squeeze_days=len(sq_days),
               expected_overlap=expected, overlap_frac=round(frac, 4))
    if frac < OVERLAP_MIN_FRAC:
        rec["overlap_flag"] = ("merged %d rows is %.1f%% of the shorter feed "
                               "(%d) -- inner join truncated"
                               % (len(merged), 100 * frac, shorter))
    if len(merged) < MIN_DAILY_ROWS:
        rec.update(status="skipped_thin_merged",
                   reason="merged frame only %d rows after the inner join" % len(merged))
        return rec, None, None

    return rec, bars, merged


def main():
    install_caches()
    os.makedirs(OUT, exist_ok=True)
    syms = universe()
    print("EVENT RATE basket export: %d tickers -> %s" % (len(syms), OUT))
    recs, t0 = [], time.time()
    for i, sym in enumerate(syms, 1):
        el = time.time() - t0
        eta = (el / max(i - 1, 1)) * (len(syms) - i + 1) if i > 1 else 0
        print("[%2d/%d] %-12s  (elapsed %.0fm, eta %.0fm)"
              % (i, len(syms), sym, el / 60, eta / 60))
        rec, bars, merged = export_one(sym)
        if bars is not None and merged is not None:
            b = base_of(sym)
            bars.to_csv(os.path.join(OUT, b + "_4h.csv.gz"), compression="gzip")
            keep = [c for c in SLIM_COLS if c in merged.columns]
            merged[keep].to_csv(os.path.join(OUT, b + "_merged.csv.gz"),
                                compression="gzip")
            print("      ok  4h=%d  daily=%d  %s -> %s  overlap=%.0f%%"
                  % (rec["bars_4h"], rec["daily_rows"], rec["daily_first"],
                     rec["daily_last"], 100 * rec["overlap_frac"]))
            if rec.get("overlap_flag"):
                print("      FLAG " + rec["overlap_flag"])
        else:
            print("      %s: %s" % (rec["status"], rec.get("reason", "")))
        recs.append(rec)
        clear_ticker_cache()

    man = {"_meta": {"written_utc": dt.datetime.now(dt.timezone.utc)
                     .strftime("%Y-%m-%d %H:%M:%S"),
                     "binance_region": os.environ.get("BINANCE_REGION", "GLOBAL"),
                     "rest_base": cf.BINANCE_REST_BASE,
                     "period": PERIOD, "target_4h_bars": SQUEEZE_BARS,
                     "min_daily_rows": MIN_DAILY_ROWS,
                     "overlap_min_frac": OVERLAP_MIN_FRAC,
                     "n_requested": len(syms)},
           "tickers": recs}
    with open(os.path.join(OUT, "MANIFEST.json"), "w", encoding="utf-8") as f:
        json.dump(man, f, indent=2)

    ok = [r for r in recs if r["status"] == "ok"]
    print("\n%d/%d exported ok in %.0f min" % (len(ok), len(syms), (time.time() - t0) / 60))
    for st in sorted({r["status"] for r in recs if r["status"] != "ok"}):
        bad = [r["symbol"] for r in recs if r["status"] == st]
        print("  %-22s %d: %s" % (st, len(bad), ", ".join(bad)))
    flagged = [r for r in recs if r.get("overlap_flag")]
    print("  overlap-flagged: %d%s" % (len(flagged),
          (" -> " + ", ".join(r["symbol"] for r in flagged)) if flagged else ""))


if __name__ == "__main__":
    main()
