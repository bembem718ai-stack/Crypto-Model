"""ROTATION #187-#192 plus control #191b — cross-sectional momentum on the
tradable-26, scored through research/portfolio_harness.py.

Registered and LOCKED in docs/cleanroom.md. Nothing here may change on the
basis of a result.

TWO SPECIFICATION COMPLETIONS, PINNED BEFORE THE FIRST RUN
----------------------------------------------------------
The locked text fixes the rules but is silent on two things the data forces.
Both are decided here, in advance, and both are disclosed in the write-up.

(1) ELIGIBILITY. The tradable-26 did not all exist in 2019 -- 6 of 26 have
    prices at DISCOVERY's start, 25 by CONFIRMATION. An asset is ELIGIBLE at
    a rebalance if it has a COMPLETE price history over that rule's own
    (lookback + skip) window ending at the rebalance date. A rule trades only
    when it has strictly MORE eligible candidates than slots -- a top-5 rule
    needs at least 6 to be selecting anything -- and otherwise holds CASH.
    Executed and skipped rebalances are both reported.

    Chosen over the alternatives deliberately: requiring 2N eligible would
    leave the top-10 rules untestable on 72% of DISCOVERY, and ranking N of
    exactly N is not a selection at all.

(2) MATCHED CONTROLS. #191b exists to randomise ONLY which five, so it draws
    from the SAME eligible set as the rule it nulls -- computed separately
    for the 30d and 90d families. #191 equal-weights every asset with a
    complete 33-day history (the shortest registered lookback), one
    benchmark for all rules as registered.

WHAT IS NOT CHANGED: lookbacks, skip, selection sizes, weighting, weekly
Monday cadence, 8bps per side, both windows, k=6, and every pass clause.
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import portfolio_harness as PH
import window_stability as WS
import harness as H

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COST_BPS = 8.0          # registered, per side
SKIP = 3                # registered
SEEDS = 1200            # registered (raised from 300 for the adjusted pctile)
RANDOM5_DRAWS = 1200    # registered
K_BONF = 6              # registered
ALPHA = 0.05 / K_BONF   # 0.008333
ADJ_PCTILE = 100.0 * (1.0 - ALPHA)   # 99.1667
N_STARTS = 50


# ----------------------------------------------------------------------
# SIGNAL + WEIGHTS
# ----------------------------------------------------------------------
def momentum_signal(px, lookback, skip=SKIP):
    """Return from t-(lookback+skip) to t-skip. Strictly past-only."""
    fwd = px.shift(skip)
    return fwd / fwd.shift(lookback) - 1.0


def eligible_mask(px, lookback, skip=SKIP):
    """Complete price history over the whole lookback+skip window."""
    need = lookback + skip
    return px.notna().rolling(need).sum() >= need


def fast_returns(Wv, R, cost_bps=COST_BPS):
    """Vectorised twin of PH.portfolio_returns. VERIFIED, not trusted.

    The reference loops over days, but its `prev` is simply the previous
    TARGET row -- there is no accumulated state -- so every quantity is a
    row-wise function of (W[i-1], W[i], R[i]) and the loop is removable
    exactly. verify_fast_path() asserts agreement to 1e-12 against the
    reference on real weight paths before any result below uses this.
    """
    n, m = Wv.shape
    prev = np.vstack([np.zeros((1, m)), Wv[:-1]])
    Rz = np.nan_to_num(R)
    gross = (prev * Rz).sum(axis=1)
    invested = prev.sum(axis=1)
    grown = prev * (1.0 + Rz)
    total = grown.sum(axis=1) + (1.0 - invested)
    safe = np.where(total == 0, 1.0, total)
    drifted = grown / safe[:, None]
    drifted = np.where((total == 0)[:, None], prev, drifted)
    turn = np.abs(Wv - drifted).sum(axis=1)
    gross[0] = 0.0
    turn[0] = np.abs(Wv[0]).sum()
    cost = turn * (cost_bps / 1e4)
    return gross, turn, cost, gross - cost


def verify_fast_path(px, paths, tol=1e-12):
    """Assert the fast path reproduces the reference exactly."""
    R = px.pct_change().fillna(0.0).to_numpy(dtype=float)
    worst = 0.0
    for name, W in paths:
        ref = PH.portfolio_returns(W, px, cost_bps_per_side=COST_BPS)
        g, t, c, net = fast_returns(W.to_numpy(dtype=float), R)
        for label, a, b in (("gross", g, ref["gross"].to_numpy()),
                            ("turnover", t, ref["turnover"].to_numpy()),
                            ("net", net, ref["net"].to_numpy())):
            e = float(np.nanmax(np.abs(a - b)))
            worst = max(worst, e)
            assert e < tol, "%s %s differs by %.2e" % (name, label, e)
    print("  fast path VERIFIED against portfolio_returns: max abs err %.2e" % worst)
    return worst


def ann_from_fast(Wv, R):
    _, turn, _, net = fast_returns(Wv, R)
    return float(net.mean() * 365), float(turn.mean())


def hold_weekly(px, chooser):
    """Build a daily weight path from a Monday-only chooser.

    chooser(date) -> Series of weights, or None to hold cash. The chosen
    weights are held unchanged until the next Monday, which is what makes
    this a WEEKLY rebalance rather than a daily one.
    """
    # Only Mondays are decisions; every other day inherits. Building the
    # decision rows and forward-filling is the same object as the day loop
    # and is ~50x cheaper, which matters at 1,200 draws x 2 windows.
    mondays = [d for d in px.index if d.weekday() == 0]
    rows, executed, skipped = {}, 0, 0
    for d in mondays:
        pick = chooser(d)
        if pick is None:
            rows[d] = np.zeros(px.shape[1])
            skipped += 1
        else:
            rows[d] = pick.to_numpy(dtype=float)
            executed += 1
    W = pd.DataFrame(0.0, index=px.index, columns=px.columns)
    if rows:
        dec = pd.DataFrame(rows, index=px.columns).T.sort_index()
        W = dec.reindex(px.index).ffill().fillna(0.0)
    return W, executed, skipped


def momentum_weights(px, lookback, n, bottom=False):
    sig = momentum_signal(px, lookback)
    elig = eligible_mask(px, lookback)
    sig = sig.where(elig)

    def chooser(d):
        s = sig.loc[d].dropna()
        if len(s) <= n:                    # must have MORE candidates than slots
            return None
        pick = (s.nsmallest(n) if bottom else s.nlargest(n)).index
        w = pd.Series(0.0, index=px.columns)
        w[pick] = 1.0 / n
        return w

    return hold_weekly(px, chooser)


def equal_weight_weights(px, min_history=33):
    """#191 — equal-weight every asset with a complete `min_history` window."""
    elig = px.notna().rolling(min_history).sum() >= min_history

    def chooser(d):
        names = elig.columns[elig.loc[d].to_numpy()]
        if not len(names):
            return None
        w = pd.Series(0.0, index=px.columns)
        w[names] = 1.0 / len(names)
        return w

    return hold_weekly(px, chooser)


def random5_weights(px, lookback, n, seed):
    """#191b — n assets drawn uniformly from the SAME eligible set the rule
    it nulls draws from, redrawn at every weekly rebalance."""
    sig = momentum_signal(px, lookback)
    elig = eligible_mask(px, lookback)
    sig = sig.where(elig)
    rng = np.random.default_rng(seed)

    def chooser(d):
        s = sig.loc[d].dropna()
        if len(s) <= n:
            return None
        pick = rng.choice(s.index.to_numpy(), size=n, replace=False)
        w = pd.Series(0.0, index=px.columns)
        w[pick] = 1.0 / n
        return w

    return hold_weekly(px, chooser)


# ----------------------------------------------------------------------
# SCORING
# ----------------------------------------------------------------------
def score(W, px):
    res = PH.portfolio_returns(W, px, cost_bps_per_side=COST_BPS)
    return PH.summarise(res), res


def rank_perm_distribution(W, px, seeds=SEEDS, generator=None, R=None):
    generator = generator or PH.rank_permutation_fixed_placebo
    R = px.pct_change().fillna(0.0).to_numpy(dtype=float) if R is None else R
    vals, turns = [], []
    for s in range(seeds):
        wp = generator(W, seed=s)
        a, t = ann_from_fast(wp.to_numpy(dtype=float), R)
        vals.append(a)
        turns.append(t)
    a = np.array([v for v in vals if v == v])
    return {"seeds": seeds, "valid": int(len(a)),
            "mean": float(a.mean()), "p95": float(np.percentile(a, 95)),
            "p_adj": float(np.percentile(a, ADJ_PCTILE)),
            "avg_turnover": float(np.mean(turns))}


def random5_distribution(px, lookback, n, draws=RANDOM5_DRAWS, R=None):
    R = px.pct_change().fillna(0.0).to_numpy(dtype=float) if R is None else R
    vals, turns = [], []
    for s in range(draws):
        W, _, _ = random5_weights(px, lookback, n, seed=900000 + s)
        a, t = ann_from_fast(W.to_numpy(dtype=float), R)
        vals.append(a)
        turns.append(t)
    a = np.array([v for v in vals if v == v])
    return {"draws": draws, "mean": float(a.mean()),
            "p05": float(np.percentile(a, 5)),
            "p50": float(np.percentile(a, 50)),
            "p95": float(np.percentile(a, 95)),
            "avg_turnover": float(np.mean(turns))}


RULES = [
    ("#187", "top-5 by 30d",    dict(lookback=30, n=5,  bottom=False), True),
    ("#188", "top-10 by 30d",   dict(lookback=30, n=10, bottom=False), False),
    ("#189", "top-5 by 90d",    dict(lookback=90, n=5,  bottom=False), True),
    ("#190", "top-10 by 90d",   dict(lookback=90, n=10, bottom=False), False),
    ("#192", "bottom-5 by 30d", dict(lookback=30, n=5,  bottom=True),  False),
]


def run_window(px_win, wname):
    print("\n%s  (%s -> %s, %d days)"
          % (wname, px_win.index.min().date(), px_win.index.max().date(), len(px_win)))
    out = {}
    # Verify the fast path on THIS window's own weight paths before it is
    # used for a single placebo draw.
    checks = [(rid, momentum_weights(px_win, **kw)[0]) for rid, _l, kw, _t in RULES]
    checks.append(("#191", equal_weight_weights(px_win)[0]))
    checks.append(("perm", PH.rank_permutation_fixed_placebo(checks[0][1], seed=1)))
    verify_fast_path(px_win, checks)
    Rm = px_win.pct_change().fillna(0.0).to_numpy(dtype=float)

    # ---- #191 equal-weight benchmark first: conditions 3 depends on it ----
    W191, ex, sk = equal_weight_weights(px_win)
    s191, r191 = score(W191, px_win)
    out["#191"] = {"label": "equal-weight all eligible", "ann_return": s191["ann_return"],
                   "sharpe": s191["sharpe"], "max_dd": s191["max_drawdown"],
                   "avg_turnover": s191["avg_turnover"], "total_cost": s191["total_cost"],
                   "rebal_executed": ex, "rebal_skipped": sk}
    print("  #191  equal-weight all eligible      ann %+.3f  turn %.4f  (rebal %d/%d)"
          % (s191["ann_return"], s191["avg_turnover"], ex, ex + sk))

    # ---- #191b random-5, per lookback family -----------------------------
    out["_random5"] = {}
    for lb in (30, 90):
        d = random5_distribution(px_win, lb, 5, R=Rm)
        out["_random5"][str(lb)] = d
        print("  #191b random-5 (%dd elig set)  p05 %+.3f  p50 %+.3f  p95 %+.3f  turn %.4f"
              % (lb, d["p05"], d["p50"], d["p95"], d["avg_turnover"]))

    # ---- the rules -------------------------------------------------------
    for rid, label, kw, is_top5 in RULES:
        W, ex, sk = momentum_weights(px_win, **kw)
        s, r = score(W, px_win)
        # PRIMARY null: fixed relabelling (differs in exactly one respect).
        # SECONDARY, reported for transparency and NEVER used for a verdict:
        # per-rebalance permutation, which also destroys the rule's week-to-
        # week persistence and so charges the null turnover it should not.
        plc = rank_perm_distribution(W, px_win, R=Rm)
        plc2 = rank_perm_distribution(W, px_win, seeds=300, R=Rm,
                                      generator=PH.rank_permutation_placebo)
        out[rid] = {"label": label, "ann_return": s["ann_return"],
                    "placebo_secondary": plc2,
                    "sharpe": s["sharpe"], "max_dd": s["max_drawdown"],
                    "avg_turnover": s["avg_turnover"], "total_cost": s["total_cost"],
                    "total_return": s["total_return"],
                    "rebal_executed": ex, "rebal_skipped": sk,
                    "placebo": plc, "is_top5": is_top5}
        print("  %s  %-18s ann %+.3f  turn %.4f (plc turn %.4f)  plc p_adj %+.3f  (rebal %d/%d)"
              % (rid, label, s["ann_return"], s["avg_turnover"],
                 plc["avg_turnover"], plc["p_adj"], ex, ex + sk))
    return out


def main():
    uni = [l.strip() for l in
           open(os.path.join(ROOT, "research", "basket_tradable.txt"),
                encoding="utf-8") if l.strip()]
    px = PH.load_daily_closes(uni)
    assert px.shape[1] == 26, "expected the tradable-26, got %d" % px.shape[1]

    bars, merged, daily = H.load_ticker("BTC")
    w = H.make_windows(daily)
    print("ROTATION #187-#192 + control #191b — tradable-26, weekly, %.0fbps/side"
          % COST_BPS)
    print("=" * 104)
    print("Bonferroni k=%d -> alpha %.5f -> placebo percentile %.4f (%d seeds)"
          % (K_BONF, ALPHA, ADJ_PCTILE, SEEDS))
    H.print_windows(w, daily, "windows from BTC, applied to the basket")

    out = {}
    for wname, win in (("DISCOVERY", w.discovery), ("CONFIRMATION", w.confirmation)):
        seg = px[(px.index >= win[0]) & (px.index < win[1])]
        out[wname] = run_window(seg, wname)

    with open(os.path.join(ROOT, "research", "rotation_results.json"), "w") as fh:
        json.dump(out, fh, indent=2, default=str)
    print("\nwrote research/rotation_results.json")
    return out


if __name__ == "__main__":
    main()
