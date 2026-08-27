"""
research/reference_pctile.py
============================
Prompt 1's reference rows on DISCOVERY, each with its OWN count-matched
placebo percentile.

The Prompt 1 run only ever computed a percentile for INC_STRONG_BUY
(harness.py:507 sets it on rows[0] alone). INC_BUY_ALL and ALWAYS_LONG
carried a placebo_p95 borrowed from the STRONG_BUY draw, which is a
different trade count AND a different conviction geometry -- not a
percentile those rows could honestly be ranked against. Each row gets its
own draw here.

GEOMETRY MATCHING. compute_exit_levels scales the target by conviction:
STRONG_BUY reaches 1.333x further (R:R 2.667) than BUY (R:R 2.0). So:
  INC_STRONG_BUY -> placebo painted entirely STRONG_BUY
  INC_BUY_ALL    -> placebo painted with the SAME STRONG_BUY/BUY mix the
                    incumbent actually had, so the placebo's average R:R
                    matches rather than being flattered or damned by it
  ALWAYS_LONG    -> DEGENERATE, and reported as such: its "count" is every
                    eligible day, so there is exactly one possible draw
                    (all of them) and it equals ALWAYS_LONG itself. A
                    percentile there would be a tie against a sample of
                    one. Not fabricated.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np, pandas as pd
import harness as H, pipeline as p

try: sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError): pass

SEEDS = 300
TICKERS = ["BTC", "ETH", "SOL"]


def paint_mixed(index, picks, n_strong, rng):
    """Paint picked days (and each one's following day) BUY, with n_strong
    of them STRONG_BUY instead -- the incumbent's own conviction mix."""
    lab = pd.Series("WATCH", index=index)
    strong = set(rng.choice(picks, size=min(n_strong, len(picks)), replace=False).tolist()) \
        if len(picks) and n_strong else set()
    for i in picks:
        L = "STRONG_BUY" if i in strong else "BUY"
        lab.iloc[i] = L
        if i + 1 < len(index):
            lab.iloc[i + 1] = L
    return lab


def placebo_pctile(frame, bars, n_events, n_strong, observed, seeds=SEEDS):
    """Distribution of net expectancy over `seeds` count-matched draws."""
    pool = len(frame.index) - 1
    n_events = int(min(n_events, pool))
    nets = []
    for s in range(seeds):
        rng = np.random.default_rng(90210 + s)
        picks = np.sort(rng.choice(pool, size=n_events, replace=False))
        lab = paint_mixed(frame.index, picks, n_strong, rng)
        r = H.score_labels(frame, bars, lab, folds=4,
                           wanted={"BUY", "STRONG_BUY"}, name=f"pl{s}")
        nets.append(r["net_all"])
    a = np.array([x for x in nets if x == x])
    return {"mean": float(a.mean()) if len(a) else float("nan"),
            "p95": float(np.percentile(a, 95)) if len(a) else float("nan"),
            "pctile": float(100.0 * (a < observed).mean()) if len(a) and observed == observed else float("nan"),
            "valid": len(a)}


def run():
    out = []
    for t in TICKERS:
        bars, merged, daily = H.load_ticker(t)
        w = H.make_windows(daily)
        bars = H.seal_bars(bars, w, "discovery")
        mw = H.slice_window(merged, w.discovery)
        dw = H.slice_window(daily, w.discovery)
        dw = dw[dw.index >= mw.index.min()]        # shared span (Prompt 1 fix)

        rows = H.incumbent_rows(mw, bars, folds=4)        # [STRONG_BUY, BUY_ALL]
        al = H.always_long(dw, bars, folds=4)

        n_strong_days = int(mw["direction"].eq("STRONG_BUY").sum())
        n_buyall_days = int(mw["direction"].isin(["BUY", "STRONG_BUY"]).sum())

        pl_s = placebo_pctile(mw, bars, n_strong_days, n_strong_days, rows[0]["net_all"])
        pl_b = placebo_pctile(mw, bars, n_buyall_days, n_strong_days, rows[1]["net_all"])

        for row, pl, nev in ((rows[0], pl_s, n_strong_days),
                             (rows[1], pl_b, n_buyall_days),
                             (al, None, len(dw) - 1)):
            out.append({"ticker": t, "row": row["name"], "n_event_days": nev,
                        "n": row["n"], "win_pct": row["win_pct"],
                        "net_all": row["net_all"], "ex_best": row["ex_best"],
                        "placebo_mean": pl["mean"] if pl else float("nan"),
                        "placebo_p95": pl["p95"] if pl else float("nan"),
                        "pctile": pl["pctile"] if pl else float("nan"),
                        "degenerate": pl is None})
        print(f"  {t} done")
    df = pd.DataFrame(out)
    df.to_csv(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "reference_pctile.csv"), index=False)
    return df


if __name__ == "__main__":
    df = run()
    print(f"\n{'ticker':<7}{'row':<17}{'n':>5}{'win%':>7}{'net_all':>9}"
          f"{'ex_best':>9}{'plcMean':>9}{'plc95':>8}{'pctile':>8}")
    print("-" * 79)
    for _, r in df.iterrows():
        pct = "n/a" if r.degenerate else f"{r.pctile:.1f}"
        eb = "—" if r.ex_best != r.ex_best else f"{r.ex_best:+.3f}"
        pm = "—" if r.placebo_mean != r.placebo_mean else f"{r.placebo_mean:+.3f}"
        p95 = "—" if r.placebo_p95 != r.placebo_p95 else f"{r.placebo_p95:+.3f}"
        print(f"{r.ticker:<7}{r.row:<17}{int(r.n):>5}{r.win_pct:>7.1f}"
              f"{r.net_all:>+9.3f}{eb:>9}{pm:>9}{p95:>8}{pct:>8}")
