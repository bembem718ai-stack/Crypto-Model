"""research/collect_binance_vision.py — Binance Vision funding backfill.

DATA COLLECTION ONLY. No hypothesis, no registered direction, no scoring,
no price joins. Nothing this module writes is scored by anything.

SOURCE AND ITS FLOOR
--------------------
Monthly `fundingRate` archives from the **Binance Vision** static bucket,
USDT-margined perpetual futures:

    data/futures/um/monthly/fundingRate/<SYMBOL>/<SYMBOL>-fundingRate-YYYY-MM.zip

The archive **floor is 2020-01**, and that is an ARCHIVE FLOOR, **NOT
CONTRACT INCEPTION**. Verified rather than assumed: every 2019 month returns
HTTP 404 for both `fundingRate` and `klines/1d`, and the first 1d-klines file
is a FULL 31-row January opening on the 1st at ~$7,189 — a contract that
listed that month would leave a partial file. So Binance Vision begins its
USD-M collection at 2020-01 across datasets, and anything earlier is absent
from this source regardless of when the contract began trading. Recorded in
`research/funding_source_probe.md`.

LISTING GOTCHA, recorded because it manufactures a false negative:
`https://data.binance.vision/?prefix=...` returns HTTP 200 and the SAME
~2.7KB JavaScript shell for every prefix. Parsing it finds zero objects and
reads exactly like "this bucket has no funding data" — it has 79 per symbol.
The machine-readable listing is the S3 endpoint, which is what is used here.

MERGE DISCIPLINE
----------------
Reuses `collect_derivs.merge_rows` / `write_merged` unchanged, so this source
obeys the same contract as Kraken and OKX: merge on (symbol, timestamp),
**existing rows win**, and a collision whose payload DIFFERS is COUNTED so a
venue revising history is visible rather than silent. A failed pull leaves
the archive untouched rather than truncating one it could not read.

Monthly archives are immutable once published, so re-running is cheap and
idempotent; the current month is served as daily files and is picked up by
the next monthly roll-up.
"""
import io
import os
import re
import sys
import zipfile
import datetime as dt
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import requests

import tls

warnings.filterwarnings("ignore", category=UserWarning)
from collect_derivs import write_merged, gh_warn

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "data", "derivatives")
OUT_FILE = os.path.join(OUT_DIR, "binance_funding.csv")

S3 = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
CDN = "https://data.binance.vision/"
PREFIX = "data/futures/um/monthly/fundingRate/%s/"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
TIMEOUT = 60
COLUMNS = ["symbol", "timestamp", "funding_rate", "funding_interval_hours"]


def list_months(symbol):
    """Months available for `symbol`, from the S3 XML listing."""
    r = requests.get(S3, params={"delimiter": "/", "prefix": PREFIX % symbol},
                     timeout=TIMEOUT)
    r.raise_for_status()
    pat = r"%s-fundingRate-(\d{4}-\d{2})\.zip$" % symbol
    return sorted(set(m for k in re.findall(r"<Key>([^<]+)</Key>", r.text)
                      for m in re.findall(pat, k)))


def fetch_month(symbol, month):
    """One monthly archive -> DataFrame in the merged schema."""
    url = CDN + (PREFIX % symbol) + "%s-fundingRate-%s.zip" % (symbol, month)
    r = requests.get(url, timeout=TIMEOUT)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    raw = zf.read(zf.namelist()[0]).decode("utf-8", "replace")
    lines = [l for l in raw.splitlines() if l.strip()]
    if not lines:
        return None
    # Binance ships a header on some months and not others; detect it.
    start = 1 if lines[0].lower().startswith("calc_time") else 0
    recs = []
    for line in lines[start:]:
        parts = line.split(",")
        if len(parts) < 3:
            continue
        try:
            ts = int(parts[0])
            interval = int(float(parts[1]))
            rate = float(parts[2])
        except ValueError:
            continue
        recs.append((symbol, _iso(ts), rate, interval))
    if not recs:
        return None
    return pd.DataFrame(recs, columns=COLUMNS)


def _iso(ms):
    return dt.datetime.fromtimestamp(
        ms / 1000, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_binance_vision_funding(symbols=None, since=None):
    """Every published monthly archive for `symbols`. None on total failure."""
    symbols = symbols or SYMBOLS
    frames, failures = [], []
    for sym in symbols:
        try:
            months = list_months(sym)
        except Exception as e:  # noqa: BLE001 — network
            failures.append("%s listing: %s" % (sym, str(e)[:120]))
            continue
        if since:
            months = [m for m in months if m >= since]
        got = 0
        for m in months:
            try:
                df = fetch_month(sym, m)
            except Exception as e:  # noqa: BLE001 — network
                failures.append("%s %s: %s" % (sym, m, str(e)[:100]))
                continue
            if df is not None and len(df):
                frames.append(df)
                got += len(df)
        print("  %-8s %3d months, %6d events" % (sym, len(months), got))
    if failures:
        gh_warn("binance_vision: %d fetch failure(s): %s"
                % (len(failures), "; ".join(failures[:4])))
    if not frames:
        return None
    return pd.concat(frames, ignore_index=True)


# ----------------------------------------------------------------------
# INTEGRITY
# ----------------------------------------------------------------------
def integrity(path=OUT_FILE):
    """Checks that must hold on the merged archive. Reported, not assumed.

    COVERAGE, NOT ROW COUNTS. The funding interval is NOT constant: SOLUSDT
    ran a 2-HOUR interval from 2022-11-09 20:00Z to 2022-11-18 08:00Z (the
    FTX window -- Binance shortens intervals under stress), 101 non-8h rows
    in the whole archive. A "rows per month vs 24/interval" test using a
    modal interval flags that month as broken when it is simply denser. So
    the test is instead: does the SUM of each month's stated interval hours
    account for the hours in the month? That is interval-aware, and it
    catches both missing rows and duplicated ones.
    """
    if not os.path.exists(path):
        return {"ok": False, "reason": "file missing"}
    d = pd.read_csv(path)
    ts = pd.to_datetime(d["timestamp"], utc=True, format="mixed")
    d = d.assign(_ts=ts, _m=ts.dt.tz_localize(None).dt.to_period("M"))

    dup = int(d.duplicated(subset=["symbol", "timestamp"]).sum())
    is_sorted = bool(
        d["timestamp"].reset_index(drop=True).equals(
            d.sort_values(["timestamp", "symbol"])["timestamp"].reset_index(drop=True)))

    per_symbol = {}
    for sym, g in d.groupby("symbol"):
        g = g.sort_values("_ts")
        first_m, last_m = g["_m"].iloc[0], g["_m"].iloc[-1]
        short = []
        for m, gm in g.groupby("_m"):
            hrs_in_month = gm["_ts"].dt.days_in_month.iloc[0] * 24
            covered = float(gm["funding_interval_hours"].sum())
            if abs(covered - hrs_in_month) > 8:          # one interval of slack
                short.append({"month": str(m), "covered_h": covered,
                              "month_h": int(hrs_in_month),
                              "boundary": bool(m in (first_m, last_m))})
        gaps = g["_ts"].diff().dropna()
        step = pd.to_timedelta(g["funding_interval_hours"].shift(-1).fillna(8),
                               unit="h").iloc[:-1]
        over = gaps.reset_index(drop=True) > step.reset_index(drop=True)
        n_over = int(over.sum())
        big = gaps.reset_index(drop=True)[over]
        intervals = dict(g["funding_interval_hours"].value_counts().sort_index())
        per_symbol[sym] = {
            "rows": int(len(g)),
            "first": str(g["_ts"].min()), "last": str(g["_ts"].max()),
            "months": int(g["_m"].nunique()),
            "interval_mix": {int(k): int(v) for k, v in intervals.items()},
            "coverage_shortfalls": short,
            "n_gaps_over_interval": n_over,
            "largest_gap_hours": (round(big.max().total_seconds() / 3600, 2)
                                  if n_over else 0.0),
        }
    return {"ok": dup == 0, "duplicate_keys": dup, "sorted": is_sorted,
            "total_rows": int(len(d)), "per_symbol": per_symbol}


def run(out_file=OUT_FILE, since=None):
    tls.enable(verbose=False)
    print("Binance Vision funding backfill — monthly archives, floor 2020-01")
    print("=" * 78)
    inc = fetch_binance_vision_funding(since=since)
    res = write_merged(out_file, inc)
    print("\n  %s: %d rows (+%d new, %d revisions counted)%s"
          % (os.path.basename(res["path"]), res["rows"], res["added"],
             res["collisions"], "  [SKIPPED — fetch failed]" if res["skipped"] else ""))
    if res["collisions"]:
        gh_warn("binance_vision: %d rows differ from the archived copy "
                "(existing rows kept)" % res["collisions"])

    print("\nINTEGRITY")
    ig = integrity(out_file)
    print("  duplicate keys : %s" % ig.get("duplicate_keys"))
    print("  sorted         : %s" % ig.get("sorted"))
    print("  total rows     : %s" % ig.get("total_rows"))
    for sym, s in (ig.get("per_symbol") or {}).items():
        print("  %-8s %6d rows  %s -> %s  months %d  intervals %s"
              % (sym, s["rows"], s["first"][:10], s["last"][:10],
                 s["months"], s["interval_mix"]))
        sf = s["coverage_shortfalls"]
        edge = sum(1 for x in sf if x["boundary"])
        print("           coverage shortfalls: %d (%d at a first/last-month "
              "boundary)  |  gaps > interval: %d (largest %.1fh)"
              % (len(sf), edge, s["n_gaps_over_interval"], s["largest_gap_hours"]))
        for x in sf:
            if not x["boundary"]:
                print("             INTERIOR SHORTFALL %s: %.0fh covered of %dh"
                      % (x["month"], x["covered_h"], x["month_h"]))
    if ig.get("duplicate_keys"):
        gh_warn("binance_vision: %d duplicate keys in the merged archive"
                % ig["duplicate_keys"])
    return 0


def recent_floor(months_back=2):
    """YYYY-MM two months back — enough to span a month roll-over."""
    today = dt.datetime.now(dt.timezone.utc)
    y, m = today.year, today.month - months_back
    while m <= 0:
        y, m = y - 1, m + 12
    return "%04d-%02d" % (y, m)


if __name__ == "__main__":
    # `recent` is what the daily workflow runs: monthly archives are
    # immutable once published, so re-downloading 229 of them every day
    # would spend bandwidth to rewrite bytes that cannot have changed.
    # Two months back covers the roll-over. A full backfill is the
    # no-argument form, used once and whenever a gap needs closing.
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    sys.exit(run(since=recent_floor() if arg == "recent" else arg))
