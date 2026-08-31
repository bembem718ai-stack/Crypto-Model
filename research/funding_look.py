"""PRELIMINARY DESCRIPTIVE LOOK — funding rate quintiles vs forward returns.

NOT A HYPOTHESIS. NOT REGISTERED. NOTHING HERE MAY BE PROMOTED.

No placebo, no thresholds, no pass rule, no verdict. This prints a table and
stops. It exists to show what the funding archive looks like, nothing more.

THREE THINGS IT EXPLICITLY DOES NOT DO
--------------------------------------
1. It does NOT reduce the Bonferroni burden of #172-#186. That program's k
   is fixed by its registration and is unaffected by anything printed here.
   Looking at data before a registered program runs does not buy down its
   correction; if anything it is the reason the correction exists.
2. It does NOT touch #172-#186's data-depth trigger. The trigger is on
   MEASURED SPAN (>=22 months for all three symbols, expected ~2027-06-27)
   and this look moves it by exactly zero days.
3. It does NOT create a precedent for looking again. A second look at the
   same data with a different cut is a hypothesis wearing a table's clothes.

THE LOCKBOX HALVES THE ARCHIVE, AND THAT IS NOT NEGOTIABLE
----------------------------------------------------------
The Kraken funding archive spans 2025-08-27 -> 2026-08-30 (12.1 months). The
lockbox opens 2026-02-26. Research rule 2 is absolute -- "not for fitting,
not for plotting, not for a sanity check, not just to look" -- so this uses
the PRE-LOCKBOX HALF ONLY: 2025-08-27 -> 2026-02-26, 183 days.

That is thin: ~36 days per quintile per ticker. Read the table accordingly.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import harness as H

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FUNDING = os.path.join(ROOT, "data", "derivatives", "kraken_funding.csv")
SYMBOL = {"PF_XBTUSD": "BTC", "PF_ETHUSD": "ETH", "PF_SOLUSD": "SOL"}
HORIZONS = (1, 3, 7)
QUINTILES = 5


def daily_funding():
    """Daily-mean funding rate per ticker, UTC days."""
    d = pd.read_csv(FUNDING)
    d["timestamp"] = pd.to_datetime(d["timestamp"], format="mixed", utc=True)
    d["ticker"] = d["symbol"].map(SYMBOL)
    d = d.dropna(subset=["ticker"])
    d["day"] = d["timestamp"].dt.tz_convert("UTC").dt.normalize().dt.tz_localize(None)
    g = d.groupby(["ticker", "day"])["funding_rate"].mean().unstack(0)
    return g.sort_index()


def daily_closes(tickers):
    cols = {}
    for t in tickers:
        b = pd.read_csv(os.path.join(ROOT, "data", "%s_4h.csv" % t),
                        index_col=0, parse_dates=True).sort_index()
        cols[t] = b["Close"].resample("1D").last()
    return pd.DataFrame(cols).sort_index()


def main():
    bars, merged, daily = H.load_ticker("BTC")
    w = H.make_windows(daily)
    seal = w.lockbox[0]

    fund = daily_funding()
    tickers = [t for t in ("BTC", "ETH", "SOL") if t in fund.columns]
    px = daily_closes(tickers)

    print("PRELIMINARY DESCRIPTIVE LOOK — funding quintiles vs forward returns")
    print("=" * 100)
    print("NOT REGISTERED. No placebo, no thresholds, no verdict, nothing promotable.")
    print("Does NOT reduce #172-#186's Bonferroni burden and does NOT move its trigger.")
    print()
    print("archive span      : %s -> %s (%.1f months)"
          % (fund.index.min().date(), fund.index.max().date(),
             (fund.index.max() - fund.index.min()).days / 30.44))
    print("LOCKBOX opens     : %s  — sealed, not read (research rule 2)" % seal.date())
    fund = fund[fund.index < seal]
    px = px[px.index < seal]
    print("usable span       : %s -> %s (%d days, ~%d per quintile per ticker)"
          % (fund.index.min().date(), fund.index.max().date(), len(fund),
             len(fund) // QUINTILES))
    print("source            : Kraken Futures hourly funding, daily mean, UTC days")
    print()

    for t in tickers:
        f = fund[t].dropna()
        p = px[t].reindex(f.index)
        ok = f.index[p.notna()]
        f, p = f.reindex(ok), p.reindex(ok)
        if len(f) < QUINTILES * 5:
            print("%s: too few overlapping days (%d) — skipped" % (t, len(f)))
            continue

        q = pd.qcut(f, QUINTILES, labels=False, duplicates="drop")
        full = px[t].dropna()
        fwd = {N: (full.shift(-N) / full - 1.0).reindex(f.index) for N in HORIZONS}

        print("%s  (%d days with both funding and price)" % (t, len(f)))
        print("  %-9s %6s %11s %11s %s"
              % ("quintile", "n", "funding lo", "funding hi",
                 "".join("%14s" % ("mean fwd %dd" % N) for N in HORIZONS)))
        print("  " + "-" * 84)
        for k in sorted(pd.Series(q).dropna().unique()):
            m = (q == k).to_numpy()
            sub = f[m]
            cells = ""
            for N in HORIZONS:
                v = fwd[N][m].dropna()
                cells += "%13s " % ("—" if not len(v) else "%+.2f%%" % (100 * v.mean()))
            print("  Q%-8d %6d %+11.5f %+11.5f %s"
                  % (k + 1, int(m.sum()), sub.min(), sub.max(), cells))
        # spread, descriptive only
        line = "  %-9s %6s %11s %11s " % ("Q5 - Q1", "", "", "")
        for N in HORIZONS:
            a = fwd[N][(q == 0).to_numpy()].dropna()
            b = fwd[N][(q == q.max()).to_numpy()].dropna()
            line += "%13s " % ("—" if not (len(a) and len(b))
                               else "%+.2f%%" % (100 * (b.mean() - a.mean())))
        print(line)
        print("  median daily funding %+.6f   mean %+.6f\n"
              % (float(f.median()), float(f.mean())))

    print("=" * 100)
    print("Descriptive only. ~%d observations per quintile per ticker and no null"
          % (len(fund) // QUINTILES))
    print("distribution, so no cell above is distinguishable from noise by anything")
    print("computed here, and no ordering in it may be called a finding.")
    print("#172-#186 remains REGISTERED and DORMANT until its measured-span trigger.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
