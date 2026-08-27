"""
research/confirm.py
===================
Hypothesis #162: score the 5 DISCOVERY-frozen rules ONCE on CONFIRMATION,
plus INC_STRONG_BUY on the identical window and threshold.

PASS = ex_best > 0 on all three tickers AND net_all > placebo p99 on all
three. Registered in docs/cleanroom.md before this ran. No parameter here
may be changed on the basis of a result.

The 4h feed is sealed at the lockbox boundary. On CONFIRMATION that seal
BINDS -- trades entered near the window's end cannot resolve without
reading sealed bars, so pipeline returns outcome=None and drops them. That
is the conservative direction and is reported (`dropped_tail`), not hidden.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np, pandas as pd
import harness as H, universe as U

try: sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError): pass

SEEDS = 200
FROZEN = ["donchian10+none", "obv_break20+none", "roc10_zero+none",
          "nr7+none", "rsi7_cross50+none"]
TICKERS = ["BTC", "ETH", "SOL"]


def placebo_dist(frame, bars, n_events, label, seeds=SEEDS):
    pool = len(frame.index) - 1
    n_events = int(min(max(n_events, 0), pool))
    nets, exs = [], []
    for s in range(seeds):
        rng = np.random.default_rng(70000 + s)
        ev = pd.Series(False, index=frame.index)
        if n_events:
            ev.iloc[np.sort(rng.choice(pool, size=n_events, replace=False))] = True
        r = H.score_labels(frame, bars, H.paint_labels(frame.index, ev, label),
                           folds=4, wanted={label}, name=f"pl{s}")
        nets.append(r["net_all"]); exs.append(r["ex_best"])
    a = np.array([x for x in nets if x == x])
    return {"p95": float(np.percentile(a, 95)) if len(a) else float("nan"),
            "p99": float(np.percentile(a, 99)) if len(a) else float("nan"),
            "mean": float(a.mean()) if len(a) else float("nan"),
            "valid": len(a),
            "pctile_of": (lambda o: float(100.0*(a < o).mean()) if len(a) and o == o else float("nan"))}


def run():
    rules = {r["name"]: r for r in U.enumerate_rules()}
    btc = U.btc_reference_daily()
    out = []
    for t in TICKERS:
        bars, merged, daily, feats, w = U.features_for(t, btc)   # bars already sealed
        win = w.confirmation
        fwin = H.slice_window(feats, win)
        mwin = H.slice_window(merged, win)
        print(f"\n=== {t} CONFIRMATION {win[0].date()} -> {win[1].date()} "
              f"({len(fwin)} days, merged {len(mwin)} days) ===")

        for name in FROZEN:
            r = rules[name]
            ev = r["fn"](feats).reindex(fwin.index).fillna(False)
            res = H.score_events(fwin, bars, ev, folds=4, name=name)
            pl = placebo_dist(fwin, bars, res["n_events"], "BUY")
            out.append({"ticker": t, "row": name, "id": r["id"],
                        "n_events": res["n_events"], "n": res["n"],
                        "win_pct": res["win_pct"], "net_all": res["net_all"],
                        "ex_best": res["ex_best"],
                        "folds_pos": res["folds_pos"], "folds_counted": res["folds_counted"],
                        "placebo_mean": pl["mean"], "placebo_p95": pl["p95"],
                        "placebo_p99": pl["p99"], "pctile": pl["pctile_of"](res["net_all"])})
            print(f"  {name:<22} n={res['n']:>4} net={res['net_all']:+.3f} "
                  f"ex_best={res['ex_best']:+.3f} p99={pl['p99']:+.3f}"
                  if res["ex_best"] == res["ex_best"] else
                  f"  {name:<22} n={res['n']:>4} net={res['net_all']:+.3f} "
                  f"ex_best=--- p99={pl['p99']:+.3f}")

        # Incumbent on the identical window/threshold
        inc = H.incumbent_rows(mwin, bars, folds=4)[0]           # INC_STRONG_BUY
        n_sb = int(mwin["direction"].eq("STRONG_BUY").sum())
        pl = placebo_dist(mwin, bars, n_sb, "STRONG_BUY")
        out.append({"ticker": t, "row": "INC_STRONG_BUY", "id": -1,
                    "n_events": n_sb, "n": inc["n"], "win_pct": inc["win_pct"],
                    "net_all": inc["net_all"], "ex_best": inc["ex_best"],
                    "folds_pos": inc["folds_pos"], "folds_counted": inc["folds_counted"],
                    "placebo_mean": pl["mean"], "placebo_p95": pl["p95"],
                    "placebo_p99": pl["p99"], "pctile": pl["pctile_of"](inc["net_all"])})
        print(f"  {'INC_STRONG_BUY':<22} n={inc['n']:>4} net={inc['net_all']:+.3f} "
              f"p99={pl['p99']:+.3f}")
    df = pd.DataFrame(out)
    df.to_csv(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "confirmation_results.csv"), index=False)
    return df


if __name__ == "__main__":
    df = run()
    print("\n" + "=" * 92)
    print("HYPOTHESIS #162 — VERDICTS (pass = ex_best>0 AND net_all>placebo p99, ALL THREE)")
    print("=" * 92)
    print(f"{'row':<22}{'ticker':<7}{'n':>5}{'net_all':>9}{'ex_best':>9}{'p99':>9}{'pct':>7}  cond")
    print("-" * 92)
    for row in df["row"].unique():
        sub = df[df.row == row]
        for _, r in sub.iterrows():
            eb = "—" if r.ex_best != r.ex_best else f"{r.ex_best:+.3f}"
            c1 = (r.ex_best == r.ex_best) and r.ex_best > 0
            c2 = r.net_all > r.placebo_p99
            print(f"{r.row:<22}{r.ticker:<7}{int(r.n):>5}{r.net_all:>+9.3f}{eb:>9}"
                  f"{r.placebo_p99:>+9.3f}{r.pctile:>7.1f}  "
                  f"ex_best>0={'Y' if c1 else 'N'} net>p99={'Y' if c2 else 'N'}")
        ok = bool(((sub.ex_best > 0) & (sub.net_all > sub.placebo_p99)).all()
                  and sub.ex_best.notna().all())
        print(f"{'':<22}{'VERDICT: ' + ('PASS' if ok else 'FAIL'):>40}")
        print("-" * 92)
