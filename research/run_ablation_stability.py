"""ABLATION — the registered window-stability profile beside each delta.

The registration requires each rung's delta to be reported with a 50-start
profile, "because #171 demonstrated that a single-window delta on this
construction can reverse". This is that instrument applied to the deltas
themselves, not to the levels: the quantity being interpreted is
`rung_net_all - full_net_all`, so that is what gets profiled.

END PINNED, START MOVES — the same one degree of freedom #171's profiler
varies, for the same reason: it is the boundary the dataset re-export
actually moved.

Descriptive. Sign-stability has no registered threshold and none may be
invented from it.
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import harness as H
import window_stability as WS
import run_ablation as A

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
N_STARTS = 50           # registered
MIN_DAYS = 120          # same floors as the #171 profiler
MIN_TRADES = 20


def main():
    bars, merged, daily = H.load_ticker("BTC")
    w = H.make_windows(daily)
    bars_sealed = H.seal_bars(bars, w, "discovery")

    print("ABLATION — window-stability profile of each DELTA (%d starts)" % N_STARTS)
    print("=" * 96)
    print("statistic: rung net_all MINUS full net_all, end pinned at each")
    print("window's own close, only the START moving.\n")

    out = {}
    for wname, win in (("DISCOVERY", w.discovery), ("CONFIRMATION", w.confirmation)):
        end = win[1]
        full_cache = {}

        def net_for(start, kw):
            m = merged[(merged.index >= start) & (merged.index < end)]
            if len(m) < MIN_DAYS:
                return float("nan")
            r = A.score_rung(m, bars_sealed, folds=1, **kw)
            if r["n"] < MIN_TRADES:
                return float("nan")
            return r["net_all"]

        def full_at(start):
            k = pd.Timestamp(start)
            if k not in full_cache:
                full_cache[k] = net_for(k, {})
            return full_cache[k]

        def make_stat(rid):
            def stat(start, _end):
                m = merged[(merged.index >= start) & (merged.index < end)]
                if len(m) < MIN_DAYS:
                    return float("nan")
                # build_rungs returns (id, label, kwargs) triples. The
                # ablated direction columns are rebuilt per sub-window, so
                # each start gets the surgery applied to its own data.
                kw = {t[0]: t[2] for t in A.build_rungs(m)}[rid]
                base = full_at(start)
                if base != base:
                    return float("nan")
                v = net_for(start, kw)
                return v - base if v == v else float("nan")
            return stat

        print("%s   (window %s -> %s)" % (wname, win[0].date(), end.date()))
        print("-" * 96)
        rows = {}
        for rid in A.RUNG_IDS[1:]:
            r = WS.profile(make_stat(rid), merged.index.min(), end,
                           n_starts=N_STARTS, min_span_frac=0.5)
            rows[rid] = {k: v for k, v in r.items() if k != "table"}
            if not r.get("n_defined"):
                print("  %-5s undefined at every start" % rid)
                continue
            print("  %-5s defined=%2d/%d  sign-stability %3.0f%% (%s)  "
                  "range %+.3f..%+.3f  median %+.3f"
                  % (rid, r["n_defined"], r["n_starts"],
                     100 * r["sign_stability"], r["modal_sign"],
                     r["min"], r["max"], r["median"]))
        out[wname] = rows
        print()

    with open(os.path.join(ROOT, "research", "ablation_stability.json"), "w") as fh:
        json.dump(out, fh, indent=2, default=str)
    print("wrote research/ablation_stability.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
