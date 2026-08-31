"""research/export_equities.py — freeze the EQUITIES universe to data/equities/.

For the EQUITIES program (#204+): instrument validation on a genuinely
different asset class. This script touches NOTHING in the crypto model. It
imports no pipeline, no signal_engines, no live_tools; it reads no crypto
data and writes only under data/equities/.

ADJUSTED CLOSE, NOT RAW CLOSE
-----------------------------
`auto_adjust=True` adjusts OHLC for splits AND dividends. Raw close is
disqualifying for an equities momentum study: dividends are a material
fraction of equity total return, and dropping them biases every ranking
toward low-yield names in a way that has nothing to do with momentum. The
size of that effect is MEASURED at export time and written into the
manifest, so the requirement is evidenced rather than asserted.

ETFs ONLY -- AND THE REASON MATTERS
-----------------------------------
Single stocks via free data carry survivorship bias that INFLATES momentum
and cannot be repaired after the fact: Yahoo serves the tickers that still
exist, so the losers that delisted are simply absent from the cross-section.
A momentum rule scored on survivors is measuring "past winners kept winning"
on a sample selected for not having failed. There is no correction available
without a point-in-time constituent database, so the universe is restricted
to ETFs, which persist.

ETFs carry their own smaller bias -- funds do close -- but the 21 here all
survive to the freeze, and the alternative is not a cleaner sample, it is an
uncorrectable one.
"""
import os
import sys
import json
import time
import hashlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import tls

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "equities")
MANIFEST = os.path.join(OUT, "MANIFEST_equities.json")

# Fixed in the registration. 9 sector SPDRs + 12 broad/regional/asset-class.
SECTORS = ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY"]
BROAD = ["SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "IEF", "GLD", "DBC",
         "EWJ", "EWG", "EWU"]
UNIVERSE = SECTORS + BROAD

COLUMNS = ["Open", "High", "Low", "Close", "Volume"]


def fetch(ticker, max_retries=3):
    """Daily adjusted OHLCV, full history. Standalone -- no crypto imports."""
    import yfinance as yf
    last = None
    for attempt in range(1, max_retries + 1):
        try:
            df = yf.download(ticker, period="max", interval="1d",
                             progress=False, auto_adjust=True)
            if df is not None and not df.empty:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                return df
            last = "empty dataframe"
        except Exception as e:  # noqa: BLE001 — network call
            last = "%s: %s" % (type(e).__name__, e)
        if attempt < max_retries:
            time.sleep(2 * attempt)
    raise ValueError("no data for %s after %d attempts (%s)"
                     % (ticker, max_retries, last))


def fetch_raw_close(ticker):
    """Unadjusted close, for measuring what adjustment is worth."""
    import yfinance as yf
    df = yf.download(ticker, period="max", interval="1d",
                     progress=False, auto_adjust=False)
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df["Close"]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    tls.enable(verbose=True)
    os.makedirs(OUT, exist_ok=True)
    rows, failed = {}, []

    print("EQUITIES EXPORT — %d ETFs, daily, ADJUSTED (auto_adjust=True)" % len(UNIVERSE))
    print("=" * 96)
    for t in UNIVERSE:
        try:
            df = fetch(t)
        except Exception as e:  # noqa: BLE001
            failed.append((t, str(e)[:80]))
            print("  %-5s FAILED: %s" % (t, str(e)[:70]))
            continue
        df = df[[c for c in COLUMNS if c in df.columns]].dropna(subset=["Close"])
        df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
        df = df[~df.index.duplicated(keep="last")].sort_index()
        # gzipped, matching data/basket/ -- this is a public repo.
        path = os.path.join(OUT, "%s.csv.gz" % t)
        df.to_csv(path, compression="gzip")

        # What did adjustment actually change? Total return, adjusted vs raw.
        adj_tr = float(df["Close"].iloc[-1] / df["Close"].iloc[0] - 1.0)
        raw_tr = float("nan")
        try:
            raw = fetch_raw_close(t)
            if raw is not None and len(raw) > 1:
                raw = raw.dropna()
                raw_tr = float(raw.iloc[-1] / raw.iloc[0] - 1.0)
        except Exception:  # noqa: BLE001 — diagnostic only
            pass

        rows[t] = {"first": str(df.index.min().date()),
                   "last": str(df.index.max().date()),
                   "rows": int(len(df)),
                   "years": round((df.index.max() - df.index.min()).days / 365.25, 2),
                   "adjusted_total_return": adj_tr,
                   "raw_total_return": raw_tr,
                   "sha256": sha256(path)}
        print("  %-5s %s -> %s  %5d rows  %5.1fy   adj TR %+9.1f%%   raw TR %+9.1f%%"
              % (t, rows[t]["first"], rows[t]["last"], rows[t]["rows"],
                 rows[t]["years"], 100 * adj_tr,
                 float("nan") if raw_tr != raw_tr else 100 * raw_tr))

    if not rows:
        print("\nNO DATA EXPORTED — nothing written, no manifest.")
        return 1

    freeze = max(pd.Timestamp(v["last"]) for v in rows.values())
    man = {"freeze_date": str(freeze.date()),
           "n_etfs": len(rows),
           "requested": UNIVERSE,
           "failed": failed,
           "adjustment": "yfinance auto_adjust=True (splits AND dividends)",
           "etfs": rows}
    with open(MANIFEST, "w", encoding="utf-8") as fh:
        json.dump(man, fh, indent=2)

    print("\nfreeze date: %s   exported %d/%d ETFs   -> %s"
          % (man["freeze_date"], len(rows), len(UNIVERSE), MANIFEST))
    if failed:
        print("FAILED: %s" % ", ".join(t for t, _ in failed))

    # Dividend contribution, the reason adjusted close is required.
    both = {t: v for t, v in rows.items()
            if v["raw_total_return"] == v["raw_total_return"]}
    if both:
        print("\nWHAT ADJUSTMENT IS WORTH (total return over each ETF's full history)")
        gaps = []
        for t, v in sorted(both.items(),
                           key=lambda kv: -(kv[1]["adjusted_total_return"]
                                            - kv[1]["raw_total_return"])):
            gap = v["adjusted_total_return"] - v["raw_total_return"]
            gaps.append(gap)
            print("  %-5s adjusted %+9.1f%%   raw %+9.1f%%   difference %+9.1f pp"
                  % (t, 100 * v["adjusted_total_return"],
                     100 * v["raw_total_return"], 100 * gap))
        print("  median difference across %d ETFs: %+.1f pp of total return"
              % (len(gaps), 100 * float(np.median(gaps))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
