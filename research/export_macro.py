"""research/export_macro.py — freeze the #251-#256 overlay series.

Pulls BOTH series ONCE, full available history, and writes them with a
sha256 manifest. **The freeze is permanent for that program**: the series are
never re-pulled, never merged, never revised.

WHY PERMANENT AND HASHED. DefiLlama's aggregate stablecoin supply is a
RECONSTRUCTION -- it can be restated as chains are added, re-indexed or
re-scoped. FRED revises rarely but does revise. If either moved after
scoring, a later reader could not tell whether a result came from the series
we used or a different one wearing the same name. The sha256 settles it.

FEAR & GREED IS NOT HERE AND THAT IS REGISTERED. It is built from price and
volatility inputs, so joining it to price-derived trades would be partially
circular. It is not a macro/flow series.

DATA ONLY. No hypothesis, nothing scored, no price join.
"""
import os
import sys
import json
import hashlib
import datetime as dt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import requests

import tls

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "macro")
MANIFEST = os.path.join(OUT, "MANIFEST_macro.json")

STABLE_URL = "https://stablecoins.llama.fi/stablecoincharts/all"
DGS10_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10"
TIMEOUT = 60


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch_stablecoin_supply():
    """DefiLlama aggregate stablecoin circulating supply, daily, USD."""
    r = requests.get(STABLE_URL, timeout=TIMEOUT)
    r.raise_for_status()
    rows = []
    for rec in r.json():
        ts = rec.get("date")
        tc = rec.get("totalCirculatingUSD")
        if ts is None or not isinstance(tc, dict):
            continue
        total = sum(v for v in tc.values() if isinstance(v, (int, float)))
        rows.append({"date": dt.datetime.fromtimestamp(
            int(ts), dt.timezone.utc).strftime("%Y-%m-%d"),
            "total_circulating_usd": float(total)})
    d = pd.DataFrame(rows).drop_duplicates(subset="date", keep="last")
    return d.sort_values("date").reset_index(drop=True)


def fetch_dgs10():
    """FRED DGS10, 10-year Treasury constant maturity, business days."""
    r = requests.get(DGS10_URL, timeout=TIMEOUT)
    r.raise_for_status()
    from io import StringIO
    d = pd.read_csv(StringIO(r.text))
    d.columns = [c.strip().lower() for c in d.columns]
    datecol = d.columns[0]
    valcol = [c for c in d.columns if c != datecol][0]
    d = d.rename(columns={datecol: "date", valcol: "dgs10"})
    d["dgs10"] = pd.to_numeric(d["dgs10"], errors="coerce")
    d = d.dropna(subset=["dgs10"])
    return d[["date", "dgs10"]].sort_values("date").reset_index(drop=True)


def gap_census(d, datecol="date"):
    """Missing calendar days and the longest gap. Timestamps only."""
    s = pd.to_datetime(d[datecol]).sort_values()
    gaps = s.diff().dt.days.dropna()
    over = gaps[gaps > 1]
    return {"rows": int(len(s)), "first": str(s.min().date()),
            "last": str(s.max().date()),
            "span_days": int((s.max() - s.min()).days),
            "n_gaps": int(len(over)),
            "longest_gap_days": int(over.max()) if len(over) else 1,
            "total_missing_days": int((over - 1).sum()) if len(over) else 0}


def main():
    tls.enable(verbose=False)
    if os.path.exists(MANIFEST):
        print("MANIFEST already exists — the freeze is PERMANENT and is not "
              "re-pulled.\nDelete data/macro/ deliberately if a re-freeze is "
              "genuinely intended.")
        return 1
    os.makedirs(OUT, exist_ok=True)
    print("MACRO OVERLAY EXPORT — one pull, then frozen")
    print("=" * 78)

    series = {}
    for name, fn, url in (("stablecoin_supply", fetch_stablecoin_supply, STABLE_URL),
                          ("dgs10", fetch_dgs10, DGS10_URL)):
        d = fn()
        path = os.path.join(OUT, "%s.csv" % name)
        d.to_csv(path, index=False)
        g = gap_census(d)
        series[name] = dict(g, source_url=url, sha256=sha256(path),
                            columns=list(d.columns))
        print("  %-20s %5d rows  %s -> %s  (%d gaps, longest %dd, %d missing days)"
              % (name, g["rows"], g["first"], g["last"], g["n_gaps"],
                 g["longest_gap_days"], g["total_missing_days"]))
        print("  %-20s sha256 %s" % ("", series[name]["sha256"][:32] + "..."))

    man = {"frozen_at": dt.datetime.now(dt.timezone.utc).strftime(
               "%Y-%m-%dT%H:%M:%SZ"),
           "program": "#251-#256 MACRO-OVERLAY",
           "permanence": "PERMANENT FREEZE — never re-pulled, never merged, "
                         "never revised for this program",
           "excluded": {"fear_and_greed": "price-contaminated; built from "
                                          "price and volatility inputs"},
           "series": series}
    with open(MANIFEST, "w", encoding="utf-8") as fh:
        json.dump(man, fh, indent=2)
    print("\nwrote %s" % MANIFEST)
    return 0


if __name__ == "__main__":
    sys.exit(main())
