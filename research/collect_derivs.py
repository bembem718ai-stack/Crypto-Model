"""
research/collect_derivs.py
==========================
DATA COLLECTION. Not a hypothesis: no number, no registered direction,
nothing here is scored. It exists to start the clock on a series that
cannot be bought back later.

WHY MERGE-DEDUPE AND NOT APPEND
-------------------------------
Every free source here serves a ROLLING window, not an archive:

    Kraken Futures funding   ~1 year rolling, hourly
    OKX funding              ~3 months, 8h settlements
    OKX open interest        180 daily rows (~6 months)

So each run fetches the FULL available history and merges it into the
existing file on (symbol, timestamp). Three consequences, all wanted:

  * The first run backfills a whole year of Kraken funding for free.
  * A missed run creates no hole, as long as the gap is shorter than the
    venue's window. Miss a week of dailies and the next run still has it.
  * Re-running is harmless. The operation is idempotent.

EXISTING ROWS WIN. On a (symbol, timestamp) collision the value already on
disk is kept and the incoming one is discarded, with the collision counted
and printed. A venue quietly revising its own history is something to find
out about, not something to silently adopt into an archive that older
results may already depend on.

Public endpoints, no keys. `research/tls.py` is used so local runs work
behind the TLS-intercepting proxy on the dev machine; on CI it is a no-op.
"""
import argparse
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import requests

try:
    import tls
    tls.enable()
except Exception:                                   # never fail on TLS setup
    pass

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "data", "derivatives")

KRAKEN_SYMBOLS = ["PF_XBTUSD", "PF_ETHUSD", "PF_SOLUSD"]
OKX_SWAPS = ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"]
OKX_CCYS = ["BTC", "ETH", "SOL"]

KEY = ["symbol", "timestamp"]
TIMEOUT = 40


# ----------------------------------------------------------------------
# PURE MERGE — the part that must be right, and is tested without network
# ----------------------------------------------------------------------
def merge_rows(existing: pd.DataFrame, incoming: pd.DataFrame) -> tuple:
    """Merge `incoming` into `existing` on (symbol, timestamp).

    Returns (merged, n_added, n_collisions). Sorted by timestamp then
    symbol so the file is stable and diffs stay readable. Existing rows
    take precedence; a collision whose values DIFFER is counted so a
    venue revising history is visible rather than silent.
    """
    if existing is None or len(existing) == 0:
        if incoming is None or len(incoming) == 0:
            return pd.DataFrame(columns=KEY), 0, 0
        out = incoming.drop_duplicates(subset=KEY, keep="first")
        return out.sort_values(KEY[::-1]).reset_index(drop=True), len(out), 0
    if incoming is None or len(incoming) == 0:
        return existing.sort_values(KEY[::-1]).reset_index(drop=True), 0, 0

    ex = existing.copy()
    inc = incoming.copy()
    for f in (ex, inc):
        for c in KEY:
            f[c] = f[c].astype(str)

    ex_keys = set(map(tuple, ex[KEY].values))
    fresh = inc[[tuple(r) not in ex_keys for r in inc[KEY].values]]

    # Collisions: same key, different payload. Counted, not applied.
    overlap = inc[[tuple(r) in ex_keys for r in inc[KEY].values]]
    collisions = 0
    if len(overlap):
        cols = [c for c in inc.columns if c in ex.columns and c not in KEY]
        if cols:
            a = ex.set_index(KEY)[cols].astype(str)
            b = overlap.drop_duplicates(subset=KEY).set_index(KEY)[cols].astype(str)
            common = a.index.intersection(b.index)
            if len(common):
                collisions = int((a.loc[common] != b.loc[common]).any(axis=1).sum())

    merged = pd.concat([ex, fresh], ignore_index=True)
    merged = merged.drop_duplicates(subset=KEY, keep="first")
    merged = merged.sort_values(KEY[::-1]).reset_index(drop=True)
    return merged, len(fresh), collisions


def write_merged(path: str, incoming: pd.DataFrame) -> dict:
    """Merge into `path`. An empty/None incoming leaves the file UNTOUCHED.

    A failed venue must not truncate an archive it could not read.
    """
    existed = os.path.exists(path)
    if incoming is None or len(incoming) == 0:
        if existed:
            cur = pd.read_csv(path)
            return {"path": path, "rows": len(cur), "added": 0, "collisions": 0,
                    "skipped": True}
        return {"path": path, "rows": 0, "added": 0, "collisions": 0, "skipped": True}

    existing = pd.read_csv(path) if existed else None
    merged, added, collisions = merge_rows(existing, incoming)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    merged.to_csv(path, index=False)
    return {"path": path, "rows": len(merged), "added": added,
            "collisions": collisions, "skipped": False}


# ----------------------------------------------------------------------
# FETCHERS — each returns a DataFrame, or None on failure
# ----------------------------------------------------------------------
def _iso(ms) -> str:
    return dt.datetime.fromtimestamp(int(ms) / 1000, dt.timezone.utc
                                     ).strftime("%Y-%m-%dT%H:%M:%SZ")


def _get(url, **kw):
    r = requests.get(url, timeout=TIMEOUT, **kw)
    r.raise_for_status()
    return r.json()


def fetch_kraken_funding(symbols=None) -> pd.DataFrame:
    """Full rolling year of hourly funding, one call per symbol."""
    rows = []
    for sym in (symbols or KRAKEN_SYMBOLS):
        d = _get("https://futures.kraken.com/derivatives/api/v4/"
                 "historicalfundingrates?symbol=%s" % sym)
        for r in d.get("rates", []):
            rows.append({"symbol": sym, "timestamp": r["timestamp"],
                         "funding_rate": r.get("fundingRate"),
                         "relative_funding_rate": r.get("relativeFundingRate")})
    return pd.DataFrame(rows)


def fetch_okx_funding(instids=None, max_pages: int = 40) -> pd.DataFrame:
    """Paginate back through OKX's ~3-month funding window."""
    rows = []
    for inst in (instids or OKX_SWAPS):
        cursor, oldest, pages = None, None, 0
        while pages < max_pages:
            url = ("https://www.okx.com/api/v5/public/funding-rate-history"
                   "?instId=%s&limit=100" % inst)
            if cursor:
                url += "&after=%d" % cursor
            data = _get(url).get("data", [])
            if not data:
                break
            for r in data:
                rows.append({"symbol": inst,
                             "timestamp": _iso(r["fundingTime"]),
                             "funding_rate": r.get("fundingRate"),
                             "realized_rate": r.get("realizedRate")})
            lo = min(int(r["fundingTime"]) for r in data)
            if oldest is not None and lo >= oldest:
                break
            oldest, cursor = lo, lo
            pages += 1
    return pd.DataFrame(rows)


def fetch_okx_oi(ccys=None) -> pd.DataFrame:
    """Daily open interest + volume, ~180 rows per currency."""
    rows = []
    for ccy in (ccys or OKX_CCYS):
        d = _get("https://www.okx.com/api/v5/rubik/stat/contracts/"
                 "open-interest-volume?ccy=%s&period=1D" % ccy)
        for r in d.get("data", []):
            rows.append({"symbol": ccy, "timestamp": _iso(r[0]),
                         "open_interest": r[1], "volume": r[2]})
    return pd.DataFrame(rows)




# ----------------------------------------------------------------------
# KRAKEN TICKERS — a once-daily SNAPSHOT, never a daily mean
# ----------------------------------------------------------------------
# WHAT THIS IS AND IS NOT. `/tickers` serves the venue's CURRENT state: one
# unauthenticated call returns openInterest, markPrice, indexPrice and
# fundingRatePrediction for every instrument. There is no history endpoint
# and no public archive, so what is not sampled is gone forever.
#
# EVERY ROW IS A POINT SAMPLE TAKEN AT WORKFLOW TIME. It is NOT the day's
# mean, median, close or VWAP of anything, and must never be described as
# one. `openInterest` in this file is OI as it stood at roughly 05:20 UTC,
# nothing more. Any future analysis that wants a daily average of these
# quantities needs a higher collection cadence -- it cannot be recovered
# from this file.
#
# The key is (symbol, snapshot DAY), not the instant, so re-running inside
# the same day is idempotent and the first snapshot of a day wins under the
# disk-wins rule. The true instant is preserved in `observed_utc`.
#
# All ~294 instruments are stored: one request already returns them, storage
# is ~16 MB/year, and it means the tradable-26 are covered from day one
# without a second call. If that growth ever matters, trim OLD rows -- do
# not narrow the symbol set, because the un-sampled instruments cannot be
# back-filled.
KRAKEN_TICKERS_URL = "https://futures.kraken.com/derivatives/api/v3/tickers"
TICKER_FIELDS = ["openInterest", "markPrice", "indexPrice",
                 "fundingRate", "fundingRatePrediction",
                 "bid", "ask", "bidSize", "askSize", "vol24h"]


def fetch_kraken_tickers(url: str = KRAKEN_TICKERS_URL) -> pd.DataFrame:
    """One snapshot of every Kraken Futures instrument."""
    now = dt.datetime.now(dt.timezone.utc)
    day = now.strftime("%Y-%m-%dT00:00:00Z")
    d = _get(url)
    rows = []
    for t in d.get("tickers", []):
        sym = t.get("symbol")
        if not sym:
            continue
        row = {"symbol": sym, "timestamp": day,
               "observed_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
        for f in TICKER_FIELDS:
            row[f] = t.get(f)
        rows.append(row)
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------
# OKX RUBIK — positioning, 180-day rolling window
# ----------------------------------------------------------------------
# Three daily series per currency, served as a HARD 180-day rolling window.
# Verified, not assumed: passing `after=<2020>` returns the same 180 rows and
# `begin=<2020>` returns ZERO, so nothing older can be back-filled at any
# price. The first run therefore banks ~180 days free, and every day not
# collected after that costs 1/180th of an unrecoverable series.
#
# Stored WIDE -- one row per (ccy, day) carrying all three series -- because
# the endpoints share the same daily timestamps and a long format would
# collide on the (symbol, timestamp) merge key.
OKX_RUBIK = "https://www.okx.com/api/v5/rubik/stat"


def fetch_okx_rubik(ccys=None) -> pd.DataFrame:
    """long/short account ratio + taker volume + OI/volume, 1D, per currency."""
    frames = []
    for ccy in (ccys or OKX_CCYS):
        cols = {}
        try:
            d = _get("%s/contracts/long-short-account-ratio?ccy=%s&period=1D"
                     % (OKX_RUBIK, ccy)).get("data", [])
            cols["long_short_ratio"] = {r[0]: r[1] for r in d if len(r) >= 2}
        except Exception as e:                       # noqa: BLE001
            gh_warn("okx_rubik long-short %s: %s" % (ccy, str(e)[:120]))
        try:
            d = _get("%s/taker-volume?ccy=%s&instType=CONTRACTS&period=1D"
                     % (OKX_RUBIK, ccy)).get("data", [])
            cols["taker_sell_vol"] = {r[0]: r[1] for r in d if len(r) >= 3}
            cols["taker_buy_vol"] = {r[0]: r[2] for r in d if len(r) >= 3}
        except Exception as e:                       # noqa: BLE001
            gh_warn("okx_rubik taker-volume %s: %s" % (ccy, str(e)[:120]))
        try:
            d = _get("%s/contracts/open-interest-volume?ccy=%s&period=1D"
                     % (OKX_RUBIK, ccy)).get("data", [])
            cols["open_interest"] = {r[0]: r[1] for r in d if len(r) >= 3}
            cols["volume"] = {r[0]: r[2] for r in d if len(r) >= 3}
        except Exception as e:                       # noqa: BLE001
            gh_warn("okx_rubik oi-volume %s: %s" % (ccy, str(e)[:120]))
        if not cols:
            continue
        stamps = sorted({t for m in cols.values() for t in m})
        for ts in stamps:
            row = {"symbol": ccy, "timestamp": _iso(int(ts))}
            for name, m in cols.items():
                row[name] = m.get(ts)
            frames.append(row)
    return pd.DataFrame(frames)


# ----------------------------------------------------------------------
# DERIBIT — options positioning + realised-volatility series
# ----------------------------------------------------------------------
# TWO SERIES IN ONE FILE, separated by a symbol suffix so the
# (symbol, timestamp) key stays unique:
#
#   <CCY>-OPTIONS  daily aggregate of the live option chain -- put/call OI
#                  ratio, call/put OI, OI-weighted mark IV. A point SAMPLE
#                  of a current-only endpoint, exactly like Kraken tickers.
#   <CCY>-HISTVOL  the historical-volatility series, ~16-DAY ROLLING window
#                  at hourly spacing. The SHORTEST window of any source
#                  here: a missed day costs 1/16th of it.
#
# SOL COVERAGE, MEASURED 2026-09-01 AND RECORDED AS A FACT: Deribit lists
# SOL as SPOT ONLY -- 0 options, 0 futures (`get_instruments` returns 2 spot
# instruments and nothing else). So there is NO SOL-OPTIONS row and there
# never will be until Deribit lists them. SOL-HISTVOL *is* served and is
# collected, but it is REALISED volatility derived from spot, NOT
# options-implied. It must never be pooled with BTC/ETH mark IV as though
# they were the same quantity.
DERIBIT = "https://www.deribit.com/api/v2/public"
DERIBIT_OPT_CCYS = ["BTC", "ETH"]                    # SOL has no options
DERIBIT_HV_CCYS = ["BTC", "ETH", "SOL"]


def _opt_kind(instrument_name: str) -> str:
    """BTC-1SEP26-85000-C -> 'C'. Deribit names end in -C or -P."""
    tail = (instrument_name or "").rsplit("-", 1)
    return tail[-1].upper() if len(tail) == 2 else ""


def fetch_deribit_options(opt_ccys=None, hv_ccys=None) -> pd.DataFrame:
    """Daily option-chain aggregate + the rolling historical-vol series."""
    now = dt.datetime.now(dt.timezone.utc)
    day = now.strftime("%Y-%m-%dT00:00:00Z")
    rows = []

    for ccy in (opt_ccys or DERIBIT_OPT_CCYS):
        try:
            res = _get("%s/get_book_summary_by_currency?currency=%s&kind=option"
                       % (DERIBIT, ccy)).get("result", []) or []
        except Exception as e:                       # noqa: BLE001
            gh_warn("deribit options %s: %s" % (ccy, str(e)[:120]))
            continue
        call_oi = put_oi = 0.0
        iv_num = iv_den = 0.0
        under = None
        for o in res:
            oi = o.get("open_interest") or 0.0
            k = _opt_kind(o.get("instrument_name"))
            if k == "C":
                call_oi += oi
            elif k == "P":
                put_oi += oi
            iv = o.get("mark_iv")
            if iv is not None and oi:
                iv_num += iv * oi
                iv_den += oi
            under = o.get("underlying_price") or under
        if not res:
            continue
        rows.append({
            "symbol": "%s-OPTIONS" % ccy, "timestamp": day,
            "observed_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "n_options": len(res),
            "call_oi": round(call_oi, 4), "put_oi": round(put_oi, 4),
            "put_call_oi_ratio": (round(put_oi / call_oi, 6) if call_oi else None),
            "oi_weighted_mark_iv": (round(iv_num / iv_den, 4) if iv_den else None),
            "underlying_price": under})

    for ccy in (hv_ccys or DERIBIT_HV_CCYS):
        try:
            res = _get("%s/get_historical_volatility?currency=%s"
                       % (DERIBIT, ccy)).get("result", []) or []
        except Exception as e:                       # noqa: BLE001
            gh_warn("deribit histvol %s: %s" % (ccy, str(e)[:120]))
            continue
        for point in res:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                continue
            rows.append({"symbol": "%s-HISTVOL" % ccy,
                         "timestamp": _iso(int(point[0])),
                         "historical_volatility": point[1]})
    return pd.DataFrame(rows)


SOURCES = [
    ("kraken_funding", fetch_kraken_funding),
    ("kraken_tickers", fetch_kraken_tickers),
    ("okx_funding", fetch_okx_funding),
    ("okx_oi", fetch_okx_oi),
    ("okx_rubik", fetch_okx_rubik),
    ("deribit_options", fetch_deribit_options),
]

# WHAT A MISSED DAY COSTS, PER SOURCE. Stated so a future outage is priced
# correctly instead of guessed at. audit.py reads this to word its staleness
# failures, and every window here was MEASURED, not taken from docs.
SOURCE_WINDOWS = {
    "kraken_funding":  ("~365-day rolling", "1/365 of the archive"),
    "kraken_tickers":  ("CURRENT-ONLY snapshot", "the whole day - there is no window to recover it from"),
    "okx_funding":     ("~90-day rolling", "1/90 of the archive"),
    "okx_oi":          ("~180-day rolling", "1/180 of the archive"),
    "okx_rubik":       ("~180-day rolling", "1/180 of the archive"),
    "deribit_options": ("CURRENT-ONLY chain + ~16-day rolling hist-vol",
                        "the whole day of chain data, and 1/16 of the hist-vol series"),
}


def gh_warn(msg: str) -> None:
    if os.environ.get("GITHUB_ACTIONS"):
        safe = str(msg).replace("\r", " ").replace("\n", " ").replace("::", ":")
        print("::warning title=Derivatives collector::%s" % safe[:700], flush=True)


def run(out_dir: str = OUT_DIR) -> int:
    """Collect every source. A failed venue warns; the others still run and
    the process still exits 0 -- a dead venue must not fail the job or stop
    its neighbours collecting."""
    os.makedirs(out_dir, exist_ok=True)
    failures, results = [], []
    for name, fetcher in SOURCES:
        path = os.path.join(out_dir, "%s.csv" % name)
        try:
            df = fetcher()
            if df is None or len(df) == 0:
                raise ValueError("empty response")
        except Exception as e:
            failures.append(name)
            msg = "%s FAILED (%s: %s) — existing file left untouched" % (
                name, type(e).__name__, str(e)[:160])
            print("  " + msg)
            gh_warn(msg)
            res = write_merged(path, None)          # explicit no-op
            results.append((name, res))
            continue
        res = write_merged(path, df)
        results.append((name, res))
        print("  %-16s fetched %5d rows -> %5d on disk (+%d new, %d collisions)"
              % (name, len(df), res["rows"], res["added"], res["collisions"]))

    print("\nSUMMARY")
    for name, res in results:
        p = res["path"]
        if not os.path.exists(p):
            print("  %-16s (no file)" % name)
            continue
        d = pd.read_csv(p)
        if not len(d):
            print("  %-16s 0 rows" % name)
            continue
        # kraken_tickers carries ~294 instruments; printing every one buries
        # the other five sources in a wall of text. Cap the listing.
        vc = d.symbol.value_counts().sort_index()
        shown = ", ".join("%s=%d" % (s, n) for s, n in list(vc.items())[:6])
        if len(vc) > 6:
            shown += ", ... +%d more symbols" % (len(vc) - 6)
        print("  %-16s %6d rows | %s -> %s | %d symbols: %s"
              % (name, len(d), d.timestamp.min(), d.timestamp.max(),
                 len(vc), shown))
    if failures:
        print("\n  venues that failed this run: %s (others collected normally)"
              % ", ".join(failures))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", default=OUT_DIR)
    a = ap.parse_args()
    sys.exit(run(a.out_dir))
