"""Run ARM A (#168). Registered conditions, all three required on BTC:
   (a) excess over 1h ALWAYS_LONG > 0, net of measured costs
   (b) target rate >= 15pp above the 1h ALWAYS_LONG base rate
   (c) net_all above the episode-matched placebo p95 on the same window
ETH and SOL reported for information; they carry no pass condition.
"""
import os
import sys
import json
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import arm1h as A
import fast_resolver as FR

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEEDS = 300


def all_bar_lookup(f, bars, arm, label):
    """Resolve EVERY bar as if it were a confirmed entry of `label`.
    Placebo draws then become index selections, not re-simulations."""
    import signal_engines as cf
    atr = cf.compute_atr(bars, period=arm["atr_period"]).reindex(f.index)
    ok = atr.notna() & (atr > 0)
    idx = f.index[ok.values]
    rr = 1.333 if label == "STRONG_BUY" else 1.0
    entry = f.loc[idx, "Close"].astype(float).values
    a = atr.loc[idx].astype(float).values
    stop_d = arm["stop_mult"] * a
    tgt_d = arm["target_mult"] * rr * a
    ent = pd.DataFrame({"ts": idx, "entry_ts": idx + pd.Timedelta(hours=1),
                        "entry": entry, "target": entry + tgt_d,
                        "stop": entry - stop_d, "stop_dist": stop_d})
    res = FR.resolve_many(bars, ent, max_bars=arm["max_hold_bars"], is_long=True)
    t = ent.join(res)
    t = t[t["resolved"]].copy()
    sf = (t["stop_dist"] / t["entry"]).astype(float)
    t["stop_pct"] = 100 * sf
    t["cost_r"] = (2.0 * (A.FEE + A.SLIP) / 1e4) / sf
    t["pnl_r_net"] = t["pnl_r"] - t["cost_r"]
    return t.set_index("ts")


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


def episode_placebo(lookup, index, run_lengths, arm, window, seeds=SEEDS):
    """Draw runs matching the observed run-length distribution."""
    n = len(index)
    C = arm["confirm_bars"]
    pos = {ts: i for i, ts in enumerate(index)}
    nets = []
    for s in range(seeds):
        rng = np.random.default_rng(880000 + s)
        taken = np.zeros(n, dtype=bool)
        picked = []
        for L in run_lengths:
            for _ in range(12):
                st = int(rng.integers(0, max(1, n - L)))
                if not taken[st:st + L].any():
                    taken[st:st + L] = True
                    # a run of L confirmed bars yields L - C + 1 entries
                    for j in range(st + C - 1, st + L):
                        picked.append(index[j])
                    break
        if not picked:
            continue
        sel = lookup.reindex(pd.Index(picked)).dropna(subset=["pnl_r_net"])
        if len(sel):
            nets.append(float(sel["pnl_r_net"].mean()))
    a = np.array(nets)
    return {"seeds": seeds, "valid": len(a),
            "mean": float(a.mean()) if len(a) else float("nan"),
            "p95": float(np.percentile(a, 95)) if len(a) else float("nan")}


def main():
    t0 = time.time()
    bars_btc = A.load_1h("BTC")
    w = A.windows_1h(bars_btc)
    full = (w["discovery"][0], w["lockbox"][0])
    print("ARM A (#168) — time-equivalent 1h, SEALED span %s -> %s"
          % (full[0], full[1]))
    print("lockbox %s -> %s NEVER read\n" % (w["lockbox"][0], w["lockbox"][1]))

    out = {}
    for tk in A.TICKERS:
        f, bars = A.build_scores(tk, A.ARM_A, w)
        f = f[(f.index >= full[0]) & (f.index < full[1])]

        sb = A.score(A.entries_for(f, bars, A.ARM_A, "STRONG_BUY"), bars, A.ARM_A)
        s_sb = A.stats(sb, A.ARM_A, window=full)

        al_lookup = all_bar_lookup(f, bars, A.ARM_A, "BUY")
        al = al_lookup.reset_index()
        s_al = A.stats(al, A.ARM_A, window=full)

        pl = {"p95": float("nan"), "mean": float("nan"), "valid": 0}
        if len(sb):
            lk = all_bar_lookup(f, bars, A.ARM_A, "STRONG_BUY")
            mask = f["direction"].eq("STRONG_BUY").values
            pl = episode_placebo(lk, f.index, runs_of(mask), A.ARM_A, full)

        rec = {"ticker": tk, "strong_buy": s_sb, "always_long": s_al,
               "placebo": pl,
               "ind_age_h": {"min": float(f.ind_age_h.min()),
                             "median": float(f.ind_age_h.median()),
                             "max": float(f.ind_age_h.max())}}
        out[tk] = rec
        print("  %s done (%.0fs)" % (tk, time.time() - t0))

    with open(os.path.join(ROOT, "research", "arm_a_results.json"), "w") as fh:
        json.dump(out, fh, indent=2, default=str)

    print("\n" + "=" * 100)
    print("ARM A (#168) RESULTS — 1h, time-equivalent")
    print("=" * 100)
    hdr = ("%-5s %-14s %6s %6s %7s %9s %9s %8s %8s %9s"
           % ("tkr", "row", "n", "eps", "win%", "net_all", "ex_best", "medStop", "cost_r", "totR"))
    print(hdr); print("-" * 100)
    for tk in A.TICKERS:
        r = out[tk]
        for nm, st in (("STRONG_BUY", r["strong_buy"]), ("ALWAYS_LONG", r["always_long"])):
            if not st.get("n"):
                print("%-5s %-14s %6s" % (tk, nm, "0")); continue
            eb = st.get("ex_best", float("nan"))
            print("%-5s %-14s %6d %6d %7.1f %+9.3f %9s %7.3f%% %8.3f %+9.1f"
                  % (tk, nm, st["n"], st["episodes"], st["win_pct"], st["net_all"],
                     ("—" if eb != eb else "%+.3f" % eb),
                     st["med_stop_pct"], st["med_cost_r"], st["total_R"]))
        p = r["placebo"]
        print("%-5s %-14s placebo mean=%+.3f p95=%+.3f (%d/%d seeds valid)"
              % (tk, "", p["mean"], p["p95"], p["valid"], SEEDS))
        print("%-5s %-14s indicator staleness: %.0f-%.0fh (median %.0fh)"
              % (tk, "", r["ind_age_h"]["min"], r["ind_age_h"]["max"], r["ind_age_h"]["median"]))
        print("-" * 100)

    b = out["BTC"]
    sb, al, pl = b["strong_buy"], b["always_long"], b["placebo"]
    print("\n#168 REGISTERED CONDITIONS (BTC):")
    if sb.get("n"):
        c1 = sb["net_all"] - al["net_all"]
        c2 = sb["win_pct"] - al["win_pct"]
        c3 = sb["net_all"] > pl["p95"] if pl["p95"] == pl["p95"] else False
        print("  (a) excess over ALWAYS_LONG > 0      : %+.3f - %+.3f = %+.3f  -> %s"
              % (sb["net_all"], al["net_all"], c1, "PASS" if c1 > 0 else "FAIL"))
        print("  (b) target rate >= +15pp over base   : %.1f%% - %.1f%% = %+.1fpp  -> %s"
              % (sb["win_pct"], al["win_pct"], c2, "PASS" if c2 >= 15 else "FAIL"))
        print("  (c) net_all > episode placebo p95    : %+.3f vs %+.3f  -> %s"
              % (sb["net_all"], pl["p95"], "PASS" if c3 else "FAIL"))
        ok = (c1 > 0) and (c2 >= 15) and c3
        print("\n  VERDICT: %s" % ("PASS" if ok else "FAIL"))
    else:
        print("  BTC produced 0 STRONG_BUY trades — cannot evaluate. VERDICT: FAIL")
    print("\ntotal %.0fs" % (time.time() - t0))


if __name__ == "__main__":
    main()
