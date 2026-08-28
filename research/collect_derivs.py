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


SOURCES = [
    ("kraken_funding", fetch_kraken_funding),
    ("okx_funding", fetch_okx_funding),
    ("okx_oi", fetch_okx_oi),
]


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
        print("  %-16s %6d rows | %s -> %s | symbols: %s"
              % (name, len(d), d.timestamp.min(), d.timestamp.max(),
                 ", ".join("%s=%d" % (s, n) for s, n in
                           d.symbol.value_counts().sort_index().items())))
    if failures:
        print("\n  venues that failed this run: %s (others collected normally)"
              % ", ".join(failures))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", default=OUT_DIR)
    a = ap.parse_args()
    sys.exit(run(a.out_dir))
