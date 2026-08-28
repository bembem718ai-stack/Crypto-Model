"""
research/audit_funding_gaps.py
==============================
Data-completeness audit of the archived Kraken funding year.

DELIBERATELY BLIND TO VALUES. It reads the `symbol` and `timestamp` columns
and NOTHING ELSE -- not funding_rate, not relative_funding_rate, and it
performs no join against price. The FUNDING program (#172-#186) is
registered before its test data exists, and that property only holds if
nobody inspects the series it will be tested on. Counting timestamps is
feed behaviour; reading values would be a peek.

Its output is registered beside the no-gap-tolerance rule so that F2
(72h negative run) and F8 (168h negative run) are registered against KNOWN
feed behaviour rather than an assumption about it. A run is broken by a
missing hour, so how often hours go missing is a property of the
hypothesis, not a detail of the data.
"""
import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "data", "derivatives", "kraken_funding.csv")

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass


def audit(path=PATH):
    # usecols is the enforcement, not a convention: the value columns are
    # never loaded into memory at all.
    d = pd.read_csv(path, usecols=["symbol", "timestamp"])
    d["ts"] = pd.to_datetime(d["timestamp"], utc=True)
    out = {}
    for sym, g in d.groupby("symbol"):
        t = g["ts"].sort_values().drop_duplicates()
        span_h = (t.max() - t.min()).total_seconds() / 3600.0
        expected = int(round(span_h)) + 1
        deltas = t.diff().dropna()
        gaps = deltas[deltas > pd.Timedelta(hours=1)]
        missing = int(sum((g.total_seconds() / 3600.0) - 1 for g in gaps))
        out[sym] = {
            "rows": int(len(t)),
            "first": str(t.min()), "last": str(t.max()),
            "span_days": round(span_h / 24.0, 1),
            "expected_hours": expected,
            "missing_hours": missing,
            "completeness_pct": round(100.0 * len(t) / expected, 3),
            "gap_count": int(len(gaps)),
            "longest_gap_hours": (round(gaps.max().total_seconds() / 3600.0, 1)
                                  if len(gaps) else 0.0),
            "gaps_over_8h": int((gaps > pd.Timedelta(hours=8)).sum()),
        }
    return out


if __name__ == "__main__":
    r = audit()
    print("KRAKEN FUNDING ARCHIVE — TIMESTAMP COMPLETENESS (values not read)")
    print("=" * 96)
    print("%-11s %7s %11s %9s %8s %7s %10s %9s" %
          ("symbol", "rows", "span(days)", "complete%", "missing", "gaps",
           "longest(h)", ">8h gaps"))
    print("-" * 96)
    for sym in sorted(r):
        s = r[sym]
        print("%-11s %7d %11.1f %8.3f%% %8d %7d %10.1f %9d" %
              (sym, s["rows"], s["span_days"], s["completeness_pct"],
               s["missing_hours"], s["gap_count"], s["longest_gap_hours"],
               s["gaps_over_8h"]))
    print()
    for sym in sorted(r):
        print("  %-11s %s -> %s" % (sym, r[sym]["first"][:16], r[sym]["last"][:16]))
