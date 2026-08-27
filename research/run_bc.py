"""Run H-basket-B (#164), H-basket-C (#165), H-tier-curve (#166) under the
#167 tradable subset, with B also on the full 82 for contrast."""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import basket as B
import basket_bc as BC

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUARTILE_SEED = 20260827

w = B.basket_windows()
SEALED = (w.discovery[0], w.lockbox[0])
DISC, CONF = w.discovery, w.confirmation

TRADABLE = [l.strip() for l in open(os.path.join(ROOT, "research", "basket_tradable.txt"))
            if l.strip()]
FULL = B.available()
OUT = {}


def line(st, pl=None):
    eb = "—" if st["ex_best"] != st["ex_best"] else "%+.3f" % st["ex_best"]
    s = ("n=%-5d eps=%-4d win=%5.1f%%  net=%+.3f  ex_best=%-8s folds=%d/%d  "
         "totR=%+8.1f  maxDD=%7.1f"
         % (st["n"], st["episodes"], st["win_pct"], st["net_all"], eb,
            st["folds_pos"], st["folds_counted"], st["total_R"], st["maxDD_R"]))
    if pl:
        s += "  | placebo mean=%+.3f p95=%+.3f" % (pl["mean"], pl["p95"])
    return s


def run_B(label, bases, tier):
    print("\n" + "=" * 108)
    print("H-basket-B (#164) — %s — %s pooled" % (label, tier))
    print("=" * 108)
    rows = {}
    for wname, win in (("DISCOVERY", DISC), ("CONFIRMATION", CONF)):
        trades, specs = BC.gather(bases, win, tier=tier)
        st = BC.pooled_stats(trades, win)
        pl = BC.episode_placebo(specs, win)
        st["placebo_mean"], st["placebo_p95"] = pl["mean"], pl["p95"]
        st["beats_p95"] = bool(st["net_all"] == st["net_all"] and st["net_all"] > pl["p95"])
        st["ex_pos"] = bool(st["ex_best"] == st["ex_best"] and st["ex_best"] > 0)
        rows[wname] = st
        print("  %-13s %s" % (wname, line(st, pl)))
        print("  %-13s ex_best>0=%s  net>p95=%s"
              % ("", "Y" if st["ex_pos"] else "N", "Y" if st["beats_p95"] else "N"))
    ok = all(rows[k]["ex_pos"] and rows[k]["beats_p95"] for k in rows)
    print("  VERDICT: %s" % ("PASS" if ok else "FAIL"))
    OUT["B_%s_%s" % (label.replace(" ", "_"), tier)] = {
        k: {kk: (None if isinstance(vv, float) and vv != vv else vv)
            for kk, vv in v.items()} for k, v in rows.items()}
    OUT["B_%s_%s_verdict" % (label.replace(" ", "_"), tier)] = "PASS" if ok else "FAIL"
    return rows, ok


def run_C():
    print("\n" + "=" * 108)
    print("H-basket-C (#165) — replication across 4 random quartiles, SEALED, tradable subset")
    print("=" * 108)
    uni = [l.strip() for l in open(os.path.join(ROOT, "research", "basket_universe.txt"))
           if l.strip() and not l.startswith("#")]
    rng = np.random.default_rng(QUARTILE_SEED)
    order = rng.permutation(len(uni))
    quarts = [sorted(uni[i][:-4] for i in order[k::4]) for k in range(4)]
    res, allpos = {}, True
    for k, q in enumerate(quarts, 1):
        members = [t for t in q if t in TRADABLE]
        trades, _ = BC.gather(members, SEALED)
        st = BC.pooled_stats(trades, SEALED)
        res["Q%d" % k] = st
        pos = (st["net_all"] == st["net_all"] and st["net_all"] > 0
               and st["ex_best"] == st["ex_best"] and st["ex_best"] > 0)
        allpos &= bool(pos)
        print("  Q%d (%2d tradable of %2d): %s" % (k, len(members), len(q), line(st)))
        print("      members: %s" % " ".join(members))
    print("  VERDICT: %s (registered direction: positive in ALL FOUR)"
          % ("PASS" if allpos else "FAIL"))
    OUT["C"] = {k: {kk: (None if isinstance(vv, float) and vv != vv else vv)
                    for kk, vv in v.items()} for k, v in res.items()}
    OUT["C_verdict"] = "PASS" if allpos else "FAIL"
    return res, allpos


def run_tier_curve():
    print("\n" + "=" * 108)
    print("H-tier-curve (#166) — DESCRIPTIVE ONLY, selects nothing — DISCOVERY, tradable subset")
    print("=" * 108)
    rows = {}
    for thr in (75, 70, 65, 60):
        trades = []
        for base in TRADABLE:
            lk, m = BC.day_trade_lookup(base, DISC)
            if m.empty or "combined_final_score" not in m.columns:
                continue
            flags = m["combined_final_score"] >= thr
            for d in BC.confirmed_days(flags):
                t = lk.get(d)
                if t is not None:
                    trades.append(dict(t, ticker=base))
            B._CACHE.pop(base, None)
        st = BC.pooled_stats(trades, DISC)
        rows[thr] = st
        print("  score >= %d : %s" % (thr, line(st)))
    OUT["tier_curve"] = {str(k): {kk: (None if isinstance(vv, float) and vv != vv else vv)
                                  for kk, vv in v.items()} for k, v in rows.items()}
    print("  (No threshold may be selected from this curve — #166 is descriptive.)")
    return rows


if __name__ == "__main__":
    print("SEALED %s -> %s | DISCOVERY %s -> %s | CONFIRMATION %s -> %s"
          % (SEALED[0].date(), SEALED[1].date(), DISC[0].date(), DISC[1].date(),
             CONF[0].date(), CONF[1].date()))
    print("tradable (#167): %d    full basket: %d" % (len(TRADABLE), len(FULL)))
    run_B("tradable 26", TRADABLE, "STRONG_BUY")
    run_B("FULL 82", FULL, "STRONG_BUY")
    run_B("tradable 26", TRADABLE, "INC_BUY_ALL")
    run_B("FULL 82", FULL, "INC_BUY_ALL")
    run_C()
    run_tier_curve()
    with open(os.path.join(ROOT, "research", "basket_bc_results.json"), "w") as f:
        json.dump(OUT, f, indent=2, default=str)
    print("\nwrote research/basket_bc_results.json")
