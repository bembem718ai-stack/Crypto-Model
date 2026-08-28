"""
export_data.py
==============
Freeze the offline research dataset into data/: full-depth Binance.US 4h
bars plus the incumbent's daily frame, per ticker, with a MANIFEST.

Run with BINANCE_REGION=US.

TLS. This machine runs a TLS-intercepting filter driver whose root lives
in the Windows certificate store, which Python's certifi bundle does not
contain. research/tls.py routes verification through the OS trust store.
Verification stays ON -- there is no verify=False anywhere in this repo.

DEPTH. N is the 4h bar target. Binance.US actually holds ~6.93y for
BTC/ETH (from 2019-09-23) and ~5.94y for SOL; the previous freeze asked
for 12,600 bars and so stopped at ~5.9y for everyone, truncating BTC/ETH
by about a year for no reason other than the request size. The paginator's
ceiling is 20 requests x 1000 bars returned by Binance.US = 20,000, so
N=20000 takes everything available. `period="max"` does the same for the
daily side, which otherwise capped the merged frame at 5y.
"""
import json
import os
import sys
import datetime as dt

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "research"))
import tls  # noqa: E402
tls.enable(verbose=True)

import pipeline as p          # noqa: E402
import signal_engines as cf   # noqa: E402

import argparse                                       # noqa: E402

_ap = argparse.ArgumentParser(description="Freeze the offline dataset")
_ap.add_argument("--interval", default="4h", choices=("4h", "1h"),
                 help="kline interval to export (default 4h)")
_args, _ = _ap.parse_known_args()

INTERVAL = _args.interval
# 1h needs ~60,730 bars for BTC/ETH; 4h needs ~15,177. max_requests now
# defaults to 70 (see fetch_klines_paginated), so both are reachable.
N = 70000 if INTERVAL == "1h" else 20000
PERIOD = "max"
TICKERS = ["BTC", "ETH", "SOL"]

os.makedirs("data", exist_ok=True)
man = {
    "_meta": {
        "written_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "binance_region": os.environ.get("BINANCE_REGION", "GLOBAL"),
        "rest_base": cf.BINANCE_REST_BASE,
        "klines_path": cf.BINANCE_KLINES_PATH,
        "interval": INTERVAL,
        "target_bars": N,
        "daily_period": PERIOD,
    }
}

for t in TICKERS:
    print("=== " + t)
    bars = cf.fetch_klines_paginated(cf.to_binance_symbol(t), interval=INTERVAL,
                                     target_bars=N)
    # LOUD ON TRUNCATION. A short return that did NOT reach the start of
    # history means the paginator gave up early; writing it would put a
    # silently shortened history into data/ and every number derived from it
    # would rest on a fraction of the available bars. Fail instead.
    cf.assert_not_truncated(cf.to_binance_symbol(t), requested=N,
                            returned=len(bars),
                            reached_start=bars.attrs.get("reached_start", False))
    bars.to_csv("data/" + t + "_" + INTERVAL + ".csv")
    print("  bars %d (%s)  %s -> %s" % (len(bars), INTERVAL, bars.index.min(), bars.index.max()))

    if INTERVAL != "4h":
        # A 1h export writes 1h BARS ONLY. The daily merged frame is derived
        # from the 4h feed and is interval-independent, so re-running it here
        # would rewrite a FROZEN artifact for no reason -- and it does change:
        # yfinance's most recent row recomputes slightly between pulls, which
        # would silently move the dataset every prior result was computed on.
        man[t] = {"bars": len(bars), "interval": INTERVAL,
                  "bars_first": str(bars.index.min()),
                  "bars_last": str(bars.index.max()),
                  "bars_years": round((bars.index.max() - bars.index.min()).days / 365.25, 2)}
        continue

    merged = p.run_backtest(t, period=PERIOD, squeeze_bars=N)
    merged.to_csv("data/" + t + "_merged.csv")
    print("  daily %d  %s -> %s" % (len(merged), merged.index.min(), merged.index.max()))

    man[t] = {
        "bars": len(bars),
        "interval": INTERVAL,
        "bars_first": str(bars.index.min()),
        "bars_last": str(bars.index.max()),
        "bars_years": round((bars.index.max() - bars.index.min()).days / 365.25, 2),
        "daily_rows": len(merged),
        "daily_first": str(merged.index.min()),
        "daily_last": str(merged.index.max()),
        "daily_years": round((merged.index.max() - merged.index.min()).days / 365.25, 2),
        "directions": {k: int(v) for k, v in merged["direction"].value_counts().to_dict().items()},
    }

MANIFEST_NAME = "MANIFEST.json" if INTERVAL == "4h" else "MANIFEST_%s.json" % INTERVAL
with open("data/" + MANIFEST_NAME, "w", encoding="utf-8") as f:
    json.dump(man, f, indent=2)
print("done -> data/" + MANIFEST_NAME)
