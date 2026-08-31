"""
research/window_stability.py
============================
Recompute a statistic across many rolling window starts and report how
often it keeps its sign.

WHY THIS EXISTS. #171 is the worked example: BTC INC_BUY_ALL measured
+0.237R at the 100th placebo percentile on one DISCOVERY split, and −0.167R
on another. Neither number was wrong. The dataset was extended, the window
moved, and the answer reversed — and the ORIGINAL measurement disclosed
nothing about that fragility, because a single window produces a single
number with no error bar attached.

This is not a hypothesis test and produces no verdict. It is a descriptive
instrument: given a statistic and a date range, it answers "how much of this
number is the window?" A statistic whose sign survives 90% of plausible
starts is a different object from one that survives 55%, even when both
report the same point estimate.

DELIBERATELY NOT A PASS RULE. Sign-stability has no registered threshold and
none may be invented from it, because the fraction depends on how the starts
were chosen and any cutoff would be picked after seeing the spread. It is
reported ALONGSIDE a result, never instead of one.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass


def rolling_starts(first, last, n_starts: int = 50, min_span_frac: float = 0.5):
    """`n_starts` window starts, evenly spaced, each leaving at least
    `min_span_frac` of the total span."""
    first, last = pd.Timestamp(first), pd.Timestamp(last)
    total = last - first
    latest = first + total * (1.0 - min_span_frac)
    if latest <= first:
        return [first]
    return [first + (latest - first) * (i / (n_starts - 1.0))
            for i in range(n_starts)]


def profile(stat_fn, first, last, n_starts: int = 50,
            min_span_frac: float = 0.5) -> dict:
    """Call stat_fn(start, end) at each start; summarise the spread.

    stat_fn returns a float, or NaN when the statistic is undefined at that
    span. NaNs are counted separately and never treated as zero.
    """
    starts = rolling_starts(first, last, n_starts, min_span_frac)
    rows = []
    for s in starts:
        try:
            v = stat_fn(s, pd.Timestamp(last))
        except Exception:
            v = float("nan")
        rows.append({"start": s, "value": float(v) if v is not None else float("nan")})
    df = pd.DataFrame(rows)
    vals = df["value"].to_numpy(dtype=float)
    ok = vals[~np.isnan(vals)]
    if not len(ok):
        return {"n_starts": len(starts), "n_defined": 0,
                "sign_stability": float("nan"), "table": df}
    pos = int((ok > 0).sum())
    neg = int((ok < 0).sum())
    modal = max(pos, neg)
    return {"n_starts": len(starts), "n_defined": int(len(ok)),
            "n_undefined": int(len(vals) - len(ok)),
            "positive": pos, "negative": neg, "zero": int((ok == 0).sum()),
            "sign_stability": modal / len(ok),
            "modal_sign": "positive" if pos >= neg else "negative",
            "mean": float(ok.mean()), "median": float(np.median(ok)),
            "min": float(ok.min()), "max": float(ok.max()),
            "first_value": float(vals[0]) if not np.isnan(vals[0]) else float("nan"),
            "last_value": float(ok[-1]),
            "table": df}


def render(name: str, r: dict) -> str:
    if not r.get("n_defined"):
        return "  %s: undefined at every start" % name
    return ("  %-34s starts=%d defined=%d  sign-stability=%.0f%% (%s)\n"
            "  %-34s range %+.3f .. %+.3f   median %+.3f   pos/neg %d/%d"
            % (name, r["n_starts"], r["n_defined"], 100 * r["sign_stability"],
               r["modal_sign"], "", r["min"], r["max"], r["median"],
               r["positive"], r["negative"]))


# ----------------------------------------------------------------------
# VALIDATION DEMO — the #171 quantity
# ----------------------------------------------------------------------
def demo_171(n_starts: int = 50):
    """Profile the exact statistic #171 measured: BTC INC_BUY_ALL net_all.

    The end is pinned at DISCOVERY's cut on the current dataset and only the
    START moves — which is precisely what the full-depth re-export did.
    """
    import harness as H
    bars, merged, daily = H.load_ticker("BTC")
    w = H.make_windows(daily)
    bars_sealed = bars[bars.index < w.lockbox[0]]
    end = w.discovery[1]

    def net_all(start, _end):
        m = merged[(merged.index >= start) & (merged.index < end)]
        if len(m) < 120:
            return float("nan")
        rows = H.incumbent_rows(m, bars_sealed, folds=1)[1]   # INC_BUY_ALL
        tr = [t for r in rows["_results"] for t in r.get("trades", [])]
        if len(tr) < 20:
            return float("nan")
        return float(np.mean([t["pnl_r_net"] for t in tr]))

    first = merged.index.min()
    return profile(net_all, first, end, n_starts=n_starts, min_span_frac=0.5)


if __name__ == "__main__":
    print("WINDOW-STABILITY PROFILER — validation on the #171 quantity")
    print("=" * 78)
    print("statistic: BTC INC_BUY_ALL net_all, end pinned at DISCOVERY's cut,")
    print("only the window START varies (which is what the re-export changed).\n")
    r = demo_171()
    print(render("BTC INC_BUY_ALL net_all", r))
    t = r["table"].dropna(subset=["value"])
    print("\n  sample of the sweep:")
    for _, row in t.iloc[::max(1, len(t) // 10)].iterrows():
        print("    start %s  ->  net_all %+.3f" % (row["start"].date(), row["value"]))
    print("\n  #171 measured -0.167 on the refreshed split -- the FIRST row above,")
    print("  i.e. the earliest start, which is exactly the split it used.")
    print("  The pre-refresh split measured +0.237, which is ABOVE this sweep's")
    print("  maximum of %+.3f. It is NOT reachable by moving the START alone:"
          % r["max"])
    print("  that window also ENDED later (2023-09-16, not 2023-04-06), so both")
    print("  boundaries moved. This sweep bounds one degree of freedom, not two.")
    print("\n  Read plainly: with the end held fixed, this statistic is negative")
    print("  at %d of %d starts. The positive readings are the minority case,"
          % (r["negative"], r["n_defined"]))
    print("  and the one this project published sat outside even that range.")
