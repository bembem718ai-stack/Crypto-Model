"""
research/placebo_curve.py
=========================
A placebo distribution for the DISCOVERY grid.

WHY A CURVE AND NOT ONE PLACEBO PER RULE: a count-matched placebo depends
almost entirely on HOW MANY trades a rule fires, not on which rule fired
them. So the distribution is estimated once per (ticker, n) on a grid of
counts and interpolated to each rule's own n. 120 rules x 3 tickers x S
seeds would be ~75k backtests for the same information.

WHY THE SAME DRAW DRIVES ALL THREE TICKERS: on DISCOVERY the three
resampled daily frames share an identical index, so one seed can pick the
SAME calendar days for BTC, ETH and SOL. That reproduces the thing that
makes an "all three tickers" filter weak -- the tickers are correlated, so
a lucky stretch is lucky for all of them at once. Measuring the joint null
rate this way is honest; multiplying 0.05^3 as if the tickers were
independent is not, and understates the false-positive rate by orders of
magnitude.

Never reads the lockbox: frames come from universe.features_for, which
cuts at the seal, and the 4h feed is sealed by harness.seal_bars.
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np, pandas as pd
import universe as U, harness as H

try: sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError): pass

N_GRID = [10, 20, 40, 80, 120, 200, 300]
SEEDS = 200


def build(seeds=SEEDS, n_grid=N_GRID):
    btc = U.btc_reference_daily()
    frames = {}
    for t in U.TICKERS:
        bars, _, _, feats, w = U.features_for(t, btc)
        frames[t] = (H.slice_window(feats, w.discovery), bars)
    index = frames[U.TICKERS[0]][0].index
    assert all(frames[t][0].index.equals(index) for t in U.TICKERS), \
        "tickers must share a daily index for a shared-draw placebo"
    pool = len(index) - 1                      # last day has no confirm day

    rows, t0 = [], time.time()
    for n in n_grid:
        for s in range(seeds):
            rng = np.random.default_rng(1_000_003 * n + s)
            pick = np.sort(rng.choice(pool, size=min(n, pool), replace=False))
            ev = pd.Series(False, index=index); ev.iloc[pick] = True
            rec = {"n_events": n, "seed": s}
            for t in U.TICKERS:
                fw, bars = frames[t]
                r = H.score_events(fw, bars, ev, folds=4, name=f"pl{n}_{s}")
                rec[f"{t}_net"] = r["net_all"]
                rec[f"{t}_ex"] = r["ex_best"]
                rec[f"{t}_n"] = r["n"]
            rows.append(rec)
        print(f"  n={n:>4} done ({time.time()-t0:.0f}s)")
    df = pd.DataFrame(rows)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "placebo_curve.csv")
    df.to_csv(out, index=False)
    print(f"wrote {out} ({len(df)} draws)")
    return df


if __name__ == "__main__":
    build()
