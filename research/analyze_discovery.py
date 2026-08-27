"""
research/analyze_discovery.py
=============================
Read the DISCOVERY grid and the placebo curve; answer the four registered
questions. Reports every rule, filters nothing, and states the null
expectation next to every observed count so a number can be read against
what chance alone produces.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, pandas as pd

R = os.path.dirname(os.path.abspath(__file__))
TICKERS = ["BTC", "ETH", "SOL"]
GUARD_N = 20

grid = pd.read_csv(os.path.join(R, "discovery_results.csv"))
pl = pd.read_csv(os.path.join(R, "placebo_curve.csv"))
n_grid = sorted(pl.n_events.unique())


def p95_curve(col):
    """p95 of `col` per ticker at each grid n, for interpolation."""
    return {t: np.array([np.nanpercentile(pl[pl.n_events == n][f"{t}_{col}"], 95)
                         for n in n_grid]) for t in TICKERS}


def interp(curve, t, n):
    return float(np.interp(n, n_grid, curve[t]))


net95, ex95 = p95_curve("net"), p95_curve("ex")

piv = {k: grid.pivot(index="rule", columns="ticker", values=k)
       for k in ("n", "n_events", "net_all", "ex_best")}
ids = grid.groupby("rule")["id"].first()
rules = piv["n"].index

# ---- observed counts -------------------------------------------------
ex_pos_all3 = (piv["ex_best"] > 0).all(axis=1) & piv["ex_best"].notna().all(axis=1)
net_pos_all3 = (piv["net_all"] > 0).all(axis=1)

beat_net = pd.DataFrame({t: [piv["net_all"].loc[r, t] > interp(net95, t, piv["n_events"].loc[r, t])
                             for r in rules] for t in TICKERS}, index=rules)
beat_ex = pd.DataFrame({t: [(piv["ex_best"].loc[r, t] == piv["ex_best"].loc[r, t]) and
                            piv["ex_best"].loc[r, t] > interp(ex95, t, piv["n_events"].loc[r, t])
                            for r in rules] for t in TICKERS}, index=rules)

# ---- null expectation, measured with the SHARED-DRAW placebo ---------
def joint_null(col, curve):
    """Fraction of placebo draws that clear their own p95 on ALL THREE
    tickers at once. Correlation between tickers is baked in, because one
    draw picks the same calendar days for all three."""
    hits = []
    for n in n_grid:
        sub = pl[pl.n_events == n]
        ok = np.ones(len(sub), dtype=bool)
        for t in TICKERS:
            thr = np.nanpercentile(sub[f"{t}_{col}"], 95)
            ok &= (sub[f"{t}_{col}"] > thr).values
        hits.append(ok.mean())
    return float(np.mean(hits)), dict(zip(n_grid, np.round(hits, 4)))

def joint_pos(col):
    """Fraction of placebo draws with col > 0 on all three at once."""
    hits = []
    for n in n_grid:
        sub = pl[pl.n_events == n]
        ok = np.ones(len(sub), dtype=bool)
        for t in TICKERS:
            ok &= (sub[f"{t}_{col}"] > 0).fillna(False).values
        hits.append(ok.mean())
    return float(np.mean(hits)), dict(zip(n_grid, np.round(hits, 4)))

jn_net, per_n_net = joint_null("net", net95)
jn_ex, per_n_ex = joint_null("ex", ex95)
jp_ex, _ = joint_pos("ex")
jp_net, _ = joint_pos("net")

N = len(rules)
print("=" * 78)
print(f"DISCOVERY — {N} rules x 3 tickers, {len(pl)} placebo draws "
      f"({pl.seed.nunique()} seeds x {len(n_grid)} counts)")
print("=" * 78)
print(f"\nex_best computable on all three tickers : "
      f"{int(piv['ex_best'].notna().all(axis=1).sum())} of {N} "
      f"(needs >=3 folds with >=10 trades)")
print(f"rules passing rarity guard n>={GUARD_N} all 3 : "
      f"{int((piv['n'].min(axis=1) >= GUARD_N).sum())} of {N}")

print("\n--- Q1: ex_best > 0 on ALL THREE tickers ---")
print(f"  observed : {int(ex_pos_all3.sum())} of {N}")
print(f"  placebo  : {jp_ex*100:.2f}% of draws -> {N*jp_ex:.1f} rules expected by chance")

print("\n--- Q2: beats placebo p95 on ALL THREE tickers ---")
print(f"  by net expectancy : observed {int(beat_net.all(axis=1).sum())} of {N}")
for r in beat_net[beat_net.all(axis=1)].index:
    print(f"      #{int(ids[r])} {r}")
print(f"  by ex_best        : observed {int(beat_ex.all(axis=1).sum())} of {N}")
for r in beat_ex[beat_ex.all(axis=1)].index:
    print(f"      #{int(ids[r])} {r}")

print("\n--- Q3: what the placebo ALONE predicts ---")
print(f"  one ticker, per rule            : 5% by construction -> {N*0.05:.1f} of {N}")
print(f"  all three, IF independent       : 0.05^3 -> {N*0.05**3:.3f} of {N}")
print(f"  all three, MEASURED (net)       : {jn_net*100:.2f}% -> {N*jn_net:.2f} of {N}")
print(f"  all three, MEASURED (ex_best)   : {jn_ex*100:.2f}% -> {N*jn_ex:.2f} of {N}")
print(f"     per-n joint rate (net): {per_n_net}")
print(f"  -> the measured rate is the honest one: the same calendar days drive")
print(f"     all three tickers, so 'all three agree' is far weaker than 0.05^3.")

print("\n--- Q4: TOP 5 by MINIMUM ex_best across tickers (guard n>=%d/ticker) ---" % GUARD_N)
elig = piv["ex_best"][(piv["n"].min(axis=1) >= GUARD_N) & piv["ex_best"].notna().all(axis=1)].copy()
elig["MIN"] = elig.min(axis=1)
elig = elig.sort_values("MIN", ascending=False)
print(f"  {len(elig)} rules eligible; {int((elig['MIN']>0).sum())} have MIN ex_best > 0")
print(f"\n  {'#':>4} {'rule':<32}{'BTC':>9}{'ETH':>9}{'SOL':>9}{'MIN':>9}  n(B/E/S)")
for r, row in elig.head(5).iterrows():
    ns = piv["n"].loc[r]
    print(f"  {int(ids[r]):>4} {r:<32}{row['BTC']:>+9.3f}{row['ETH']:>+9.3f}"
          f"{row['SOL']:>+9.3f}{row['MIN']:>+9.3f}  {int(ns.BTC)}/{int(ns.ETH)}/{int(ns.SOL)}")
