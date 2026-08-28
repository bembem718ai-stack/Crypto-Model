"""#171 — BTC INC_BUY_ALL revalidation on the refreshed full-depth dataset.

Registered direction, BTC alone, BOTH windows: ex_best > 0 AND net_all above
the episode-matched placebo p95 (300 seeds).

Trades come from pipeline via research/harness.py. The placebo uses a
day -> trade lookup built from ONE pipeline call per conviction, verified
here against harness.incumbent_rows before use.
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import harness as H
import pipeline as p

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEEDS = 300
TIER = {"BUY", "STRONG_BUY"}
G = p.LIVE_GEOMETRY


def lookup_for(mwin, bars, label):
    """day -> trade, from ONE pipeline call with every day painted `label`."""
    f = mwin[["Open", "High", "Low", "Close", "Volume"]].copy()
    f["direction"] = label
    r = p.backtest_exit_geometry(
        f, bars, atr_source=G["atr_source"], stop_mult=G["stop_mult"],
        target_mult=G["target_mult"], max_hold_days=G["max_hold_days"],
        short_sma_filter=G["short_sma_filter"], confirm_days=G["confirm_days"],
        fee_bps=2.0, slippage_bps=2.0)
    return {pd.Timestamp(t["date"]): t for t in r.get("trades", [])}


def observed_trades(mwin, lk_s, lk_b):
    """Confirmed days under the real labels, resolved at their own conviction."""
    lab = mwin["direction"]
    same = lab.eq(lab.shift(1)) & lab.isin(TIER)
    out = []
    for d in mwin.index[same.values]:
        src = lk_s if lab.get(d) == "STRONG_BUY" else lk_b
        t = src.get(d)
        if t is not None:
            out.append(t)
    return out


def runs_of(mask):
    out, cur = [], 0
    for v in mask:
        if v:
            cur += 1
        elif cur:
            out.append(cur); cur = 0
    if cur:
        out.append(cur)
    return out


def stats(trades, window, folds=4):
    if not trades:
        return {"n": 0}
    df = pd.DataFrame(trades)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date")
    hold = pd.Timedelta(days=G["max_hold_days"])
    d = list(df["date"])
    eps = 1 + sum(1 for i in range(1, len(d)) if (d[i] - d[i - 1]) > hold)
    edges = pd.date_range(window[0], window[1], periods=folds + 1)
    fi = pd.cut(df["date"], edges, labels=False, include_lowest=True)
    counted = [(len(df[fi == k]), float(df[fi == k]["pnl_r_net"].mean()))
               for k in range(folds) if len(df[fi == k]) >= 10]
    ex = float("nan")
    if len(counted) >= 3:
        tn = sum(n for n, _ in counted); tr = sum(n * m for n, m in counted)
        bn, bm = max(counted, key=lambda c: c[0] * c[1])
        rest = tn - bn
        ex = (tr - bn * bm) / rest if rest else float("nan")
    return {"n": len(df), "episodes": eps,
            "win_pct": 100 * (df["outcome"] == "target").mean(),
            "net_all": float(df["pnl_r_net"].mean()),
            "total_R": float(df["pnl_r_net"].sum()),
            "folds_counted": len(counted),
            "folds_pos": sum(1 for n, m in counted if m > 0),
            "ex_best": ex}


def placebo(mwin, lk_s, lk_b, seeds=SEEDS):
    """Episode-matched: same run-lengths, same conviction mix."""
    lab = mwin["direction"]
    mask = lab.isin(TIER).values
    rl = runs_of(mask)
    n_strong = int(lab.eq("STRONG_BUY").sum())
    n_all = int(mask.sum())
    p_strong = (n_strong / n_all) if n_all else 0.0
    idx = mwin.index
    n = len(idx)
    nets = []
    for s in range(seeds):
        rng = np.random.default_rng(171000 + s)
        taken = np.zeros(n, dtype=bool)
        picked = []
        for L in rl:
            for _ in range(12):
                st = int(rng.integers(0, max(1, n - L)))
                if not taken[st:st + L].any():
                    taken[st:st + L] = True
                    strong = rng.random() < p_strong      # whole run's conviction
                    for j in range(st + 1, st + L):       # confirm_days=2
                        picked.append((idx[j], strong))
                    break
        tr = []
        for d, strong in picked:
            t = (lk_s if strong else lk_b).get(d)
            if t is not None:
                tr.append(t["pnl_r_net"])
        if tr:
            nets.append(float(np.mean(tr)))
    a = np.array(nets)
    return {"seeds": seeds, "valid": len(a),
            "mean": float(a.mean()) if len(a) else float("nan"),
            "p95": float(np.percentile(a, 95)) if len(a) else float("nan")}


def main():
    bars, merged, daily = H.load_ticker("BTC")
    w = H.make_windows(daily)
    bars_sealed = bars[bars.index < w.lockbox[0]]
    print("#171 — BTC INC_BUY_ALL on the REFRESHED dataset")
    print("  DISCOVERY    %s -> %s" % (w.discovery[0].date(), w.discovery[1].date()))
    print("  CONFIRMATION %s -> %s" % (w.confirmation[0].date(), w.confirmation[1].date()))
    print("  LOCKBOX      %s -> %s  (never read)\n" % (w.lockbox[0].date(), w.lockbox[1].date()))

    out = {}
    for wname, win in (("DISCOVERY", w.discovery), ("CONFIRMATION", w.confirmation)):
        mwin = H.slice_window(merged, win)
        lk_s = lookup_for(mwin, bars_sealed, "STRONG_BUY")
        lk_b = lookup_for(mwin, bars_sealed, "BUY")

        # verify the lookup reproduces the incumbent trade-for-trade
        obs = observed_trades(mwin, lk_s, lk_b)
        ref = H.incumbent_rows(mwin, bars_sealed, folds=1)[1]
        rt = [x for r in ref["_results"] for x in r.get("trades", [])]
        a = sorted((str(x["date"]), x["outcome"], round(x["pnl_r_net"], 6)) for x in obs)
        b = sorted((str(x["date"]), x["outcome"], round(x["pnl_r_net"], 6)) for x in rt)
        assert a == b, "lookup does not reproduce incumbent_rows on %s" % wname
        print("  [%s] lookup verified against incumbent_rows: %d trades MATCH" % (wname, len(obs)))

        st = stats(obs, win)
        st["placebo"] = placebo(mwin, lk_s, lk_b)
        out[wname] = st

    with open(os.path.join(ROOT, "research", "h171_results.json"), "w") as fh:
        json.dump(out, fh, indent=2, default=str)

    print("\n" + "=" * 92)
    print("#171 RESULTS — BTC INC_BUY_ALL, refreshed dataset")
    print("=" * 92)
    print("%-14s %6s %9s %7s %10s %10s %9s %11s" %
          ("window", "n", "episodes", "win%", "net_all", "ex_best", "folds", "plc p95"))
    print("-" * 92)
    for wn in ("DISCOVERY", "CONFIRMATION"):
        s = out[wn]
        eb = s.get("ex_best", float("nan"))
        print("%-14s %6d %9d %7.1f %+10.3f %10s %4d/%-4d %+11.3f" %
              (wn, s["n"], s["episodes"], s["win_pct"], s["net_all"],
               ("—" if eb != eb else "%+.3f" % eb),
               s["folds_pos"], s["folds_counted"], s["placebo"]["p95"]))
    print("\nREGISTERED CONDITIONS (BTC, both windows):")
    ok = True
    for wn in ("DISCOVERY", "CONFIRMATION"):
        s = out[wn]
        eb = s.get("ex_best", float("nan"))
        c1 = (eb == eb) and eb > 0
        c2 = s["net_all"] > s["placebo"]["p95"]
        ok &= (c1 and c2)
        print("  %-13s ex_best > 0: %-8s -> %s   |   net > plc p95: %+.3f vs %+.3f -> %s"
              % (wn, ("—" if eb != eb else "%+.3f" % eb), "PASS" if c1 else "FAIL",
                 s["net_all"], s["placebo"]["p95"], "PASS" if c2 else "FAIL"))
    print("\n  VERDICT: %s" % ("PASS" if ok else "FAIL"))


if __name__ == "__main__":
    main()
