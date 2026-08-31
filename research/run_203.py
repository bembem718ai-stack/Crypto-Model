"""#203 — SQUEEZE-ONLY PROMOTION, in-sample legs.

Registered in docs/cleanroom.md before this ran. BTC only, both windows of
the frozen dataset, LOCKBOX sealed and unread.

PASS = ex_best > 0 AND net_all above the episode-matched placebo p95
(1,200 seeds), on BOTH windows. A 50-start window-stability profile of
net_all is attached to the result whatever the outcome.

The placebo machinery is #171's, unchanged: one pipeline call per conviction
builds a day -> trade lookup, and that lookup is VERIFIED trade-for-trade
against the scored construction before a single draw is taken. Episode
matching reproduces the observed run-length distribution and conviction mix,
per #167 -- independent-day draws are lower-variance than clustered signals
and would flatter any clustered rule.
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
import pipeline as p

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEEDS = 1200            # registered
N_STARTS = 50           # registered
TIER = {"BUY", "STRONG_BUY"}
G = p.LIVE_GEOMETRY


def squeeze_frame(mwin):
    """mwin with `direction` rebuilt at 1.0 pattern / 0.0 indicators."""
    d, combined = A.rebuild_direction(mwin, w_pattern=1.0, w_ind=0.0)
    f = mwin.copy()
    f["direction"] = d.values
    f["combined_final_score"] = combined.values
    return f


def lookup_for(frame, bars, label):
    """day -> trade, from ONE pipeline call with every day painted `label`."""
    f = frame[["Open", "High", "Low", "Close", "Volume"]].copy()
    f["direction"] = label
    r = p.backtest_exit_geometry(
        f, bars, atr_source=G["atr_source"], stop_mult=G["stop_mult"],
        target_mult=G["target_mult"], max_hold_days=G["max_hold_days"],
        short_sma_filter=G["short_sma_filter"], confirm_days=G["confirm_days"],
        fee_bps=H.FEE_BPS, slippage_bps=H.SLIPPAGE_BPS)
    return {pd.Timestamp(t["date"]): t for t in r.get("trades", [])}


def observed_trades(frame, lk_s, lk_b):
    """Confirmed days under the real labels, resolved at their own conviction."""
    lab = frame["direction"]
    same = lab.eq(lab.shift(1)) & lab.isin(TIER)
    out = []
    for d in frame.index[same.values]:
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
            out.append(cur)
            cur = 0
    if cur:
        out.append(cur)
    return out


def placebo(frame, lk_s, lk_b, seeds=SEEDS, observed=None):
    """Episode-matched: same run-lengths, same conviction mix (#167)."""
    lab = frame["direction"]
    mask = lab.isin(TIER).values
    rl = runs_of(mask)
    n_all = int(mask.sum())
    p_strong = (int(lab.eq("STRONG_BUY").sum()) / n_all) if n_all else 0.0
    idx = frame.index
    n = len(idx)
    nets = []
    for s in range(seeds):
        rng = np.random.default_rng(203000 + s)
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
        tr = [(lk_s if strong else lk_b)[d]["pnl_r_net"]
              for d, strong in picked if d in (lk_s if strong else lk_b)]
        if tr:
            nets.append(float(np.mean(tr)))
    a = np.array(nets)
    pct = float("nan")
    if observed is not None and len(a) and observed == observed:
        pct = float(100.0 * (a < observed).mean())
    return {"seeds": seeds, "valid": len(a),
            "mean": float(a.mean()) if len(a) else float("nan"),
            "p50": float(np.percentile(a, 50)) if len(a) else float("nan"),
            "p95": float(np.percentile(a, 95)) if len(a) else float("nan"),
            "pctile": pct}


def main():
    bars, merged, daily = H.load_ticker("BTC")
    w = H.make_windows(daily)
    bars_sealed = H.seal_bars(bars, w, "discovery")

    print("#203 — SQUEEZE-ONLY (1.0 pattern / 0.0 indicators), BTC BUY_ALL")
    print("=" * 96)
    H.print_windows(w, daily, "BTC")

    # ---- the same reconstruction gate ABLATION used --------------------
    scored = merged[merged.index < w.lockbox[0]]
    rebuilt, combined = A.rebuild_direction(scored)
    mism = int((rebuilt.values != scored["direction"].values).sum())
    cmax = float((combined - scored["combined_final_score"]).abs().max())
    print("\nRECONSTRUCTION GATE — production weights vs the stored column")
    print("  combined_final_score max abs err : %.2e" % cmax)
    print("  direction mismatches             : %d of %d" % (mism, len(scored)))
    if mism or cmax > 1e-9:
        print("  GATE FAILED — refusing to score. No result reported.")
        return 1
    print("  GATE PASSED")

    out = {}
    for wname, win in (("DISCOVERY", w.discovery), ("CONFIRMATION", w.confirmation)):
        mwin = H.slice_window(merged, win)
        f = squeeze_frame(mwin)

        row = A.score_rung(mwin, bars_sealed, direction=f["direction"], folds=4)

        lk_s = lookup_for(f, bars_sealed, "STRONG_BUY")
        lk_b = lookup_for(f, bars_sealed, "BUY")
        obs = observed_trades(f, lk_s, lk_b)

        # VERIFY the lookup reproduces the scored construction trade-for-trade
        ref = A.score_rung(mwin, bars_sealed, direction=f["direction"], folds=1)
        a = sorted((str(t["date"]), t["outcome"], round(t["pnl_r_net"], 6))
                   for t in obs)
        b = sorted((str(t["date"]), t["outcome"], round(t["pnl_r_net"], 6))
                   for t in ref["_trades"])
        assert a == b, "placebo lookup does not reproduce the construction on %s" % wname
        print("\n[%s] lookup verified: %d trades MATCH the scored construction"
              % (wname, len(obs)))

        row["placebo"] = placebo(f, lk_s, lk_b, observed=row["net_all"])
        row.pop("_trades", None)
        out[wname] = row
        print("  n=%d episodes=%d net_all=%+.3f ex_best=%s placebo p95=%+.3f"
              % (row["n"], row["episodes"], row["net_all"],
                 ("—" if row["ex_best"] != row["ex_best"] else "%+.3f" % row["ex_best"]),
                 row["placebo"]["p95"]))

    # ---- window-stability of net_all, attached whatever the outcome -----
    print("\nWINDOW-STABILITY of squeeze-only net_all (%d starts, end pinned)" % N_STARTS)
    stab = {}
    for wname, win in (("DISCOVERY", w.discovery), ("CONFIRMATION", w.confirmation)):
        end = win[1]

        def stat(start, _end):
            m = merged[(merged.index >= start) & (merged.index < end)]
            if len(m) < 120:
                return float("nan")
            r = A.score_rung(m, bars_sealed,
                             direction=squeeze_frame(m)["direction"], folds=1)
            return r["net_all"] if r["n"] >= 20 else float("nan")

        r = WS.profile(stat, merged.index.min(), end, n_starts=N_STARTS,
                       min_span_frac=0.5)
        stab[wname] = {k: v for k, v in r.items() if k != "table"}
        print("  %-13s defined=%2d/%d  sign-stability %3.0f%% (%s)  "
              "range %+.3f..%+.3f  median %+.3f"
              % (wname, r["n_defined"], r["n_starts"], 100 * r["sign_stability"],
                 r["modal_sign"], r["min"], r["max"], r["median"]))
    out["_stability"] = stab

    # ---- verdict --------------------------------------------------------
    print("\n" + "=" * 96)
    print("#203 RESULTS — SQUEEZE_ONLY, BTC BUY_ALL")
    print("=" * 96)
    print("%-14s %5s %9s %7s %10s %10s %8s %11s %10s"
          % ("window", "n", "episodes", "win%", "net_all", "ex_best", "folds",
             "plc p95", "plc pctile"))
    print("-" * 96)
    for wn in ("DISCOVERY", "CONFIRMATION"):
        s = out[wn]
        eb = s["ex_best"]
        print("%-14s %5d %9d %7.1f %+10.3f %10s %4d/%-3d %+11.3f %+10.3f"
              % (wn, s["n"], s["episodes"], s["win_pct"], s["net_all"],
                 ("—" if eb != eb else "%+.3f" % eb),
                 s["folds_pos"], s["folds_counted"],
                 s["placebo"]["p95"], s["placebo"]["pctile"]))

    print("\nREGISTERED CONDITIONS (BTC, both windows):")
    ok = True
    for wn in ("DISCOVERY", "CONFIRMATION"):
        s = out[wn]
        eb = s["ex_best"]
        c1 = (eb == eb) and eb > 0
        c2 = s["net_all"] > s["placebo"]["p95"]
        ok &= (c1 and c2)
        print("  %-13s ex_best > 0: %-8s -> %-11s | net > plc p95: %+.3f vs %+.3f -> %s"
              % (wn, ("UNMEASURABLE" if eb != eb else "%+.3f" % eb),
                 "PASS" if c1 else ("UNMEASURABLE" if eb != eb else "FAIL"),
                 s["net_all"], s["placebo"]["p95"], "PASS" if c2 else "FAIL"))
    out["_verdict"] = "PASS" if ok else "FAIL"
    print("\n  VERDICT: %s" % out["_verdict"])

    with open(os.path.join(ROOT, "research", "h203_results.json"), "w") as fh:
        json.dump(out, fh, indent=2, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
