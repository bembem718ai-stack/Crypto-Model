"""
research/portfolio_harness.py
=============================
Portfolio-level scoring: turn a WEIGHT SERIES into daily returns, net of
turnover-aware costs, with fold splits and two placebo generators.

This is the machinery the ROTATION and ALLOCATION programs need and the
existing harness cannot provide. research/harness.py scores a per-ticker
EVENT series through the incumbent's trade machinery; nothing in the project
until now could score a cross-sectional allocation, where the object being
tested is a matrix of weights rather than a list of trades.

NO-LOOKAHEAD, structurally
--------------------------
Weights dated t are the weights you HOLD INTO t+1, and they earn t+1's
return. A weight computed from information available at t therefore cannot
capture t's own move. The alignment is enforced in one place --
`portfolio_returns` shifts weights forward exactly once -- so it cannot be
got wrong per-caller.

COSTS
-----
Charged on TRADED NOTIONAL, not on gross exposure: cost_t =
sum(|w_target_t - w_drifted_t|) * cost_bps / 1e4. Between rebalances weights
drift with prices, and drift is FREE -- charging it would invent turnover
that never happened, which is the most common way a backtest overstates its
own costs and then congratulates itself for surviving them.

NOTE ON THE RATE. The default here is 8bps PER SIDE, as specified for the
portfolio programs. Elsewhere this project uses 2bps fee + 2bps slippage =
4bps per side, 8bps round trip. The portfolio default is therefore 2x the
per-side rate used by the trade-level work, which is deliberate for
cross-sectional trading in thinner alts but must not be confused with it
when comparing numbers. It is a parameter; nothing hardcodes it.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASKET = os.path.join(ROOT, "data", "basket")
DEFAULT_COST_BPS_PER_SIDE = 8.0


# ----------------------------------------------------------------------
# DATA
# ----------------------------------------------------------------------
def load_daily_closes(tickers, source=BASKET):
    """Daily closes (UTC days, last 4h bar of each day) for `tickers`."""
    cols = {}
    for t in tickers:
        p = os.path.join(source, "%s_4h.csv.gz" % t)
        if not os.path.exists(p):
            continue
        b = pd.read_csv(p, index_col=0, parse_dates=True).sort_index()
        cols[t] = b["Close"].resample("1D").last()
    if not cols:
        return pd.DataFrame()
    return pd.DataFrame(cols).sort_index()


# ----------------------------------------------------------------------
# CORE
# ----------------------------------------------------------------------
def drift_weights(w_prev, ret):
    """Weights after one period of price drift, unnormalised.

    A portfolio holding w_prev that earns `ret` ends the period holding
    w_prev*(1+ret) in value terms, renormalised by the portfolio's own
    growth. Cash (1 - sum(w_prev)) earns nothing and is carried along.
    """
    invested = np.nansum(w_prev)
    grown = w_prev * (1.0 + np.nan_to_num(ret))
    total = np.nansum(grown) + (1.0 - invested)
    if total == 0:
        return w_prev
    return grown / total


def portfolio_returns(weights: pd.DataFrame, prices: pd.DataFrame,
                      cost_bps_per_side: float = DEFAULT_COST_BPS_PER_SIDE):
    """Daily net returns from a weight series.

    weights : DataFrame indexed by date, columns = assets. Row t is the
              target held INTO t+1.
    prices  : DataFrame of daily closes, same columns.

    Returns a DataFrame with gross, turnover, cost and net per day.
    """
    px = prices.reindex(columns=weights.columns).sort_index()
    w = weights.reindex(px.index).fillna(0.0)
    rets = px.pct_change().fillna(0.0)

    dates = list(px.index)
    gross = np.zeros(len(dates))
    turn = np.zeros(len(dates))
    prev = np.zeros(w.shape[1])

    for i, dt in enumerate(dates):
        tgt = w.loc[dt].to_numpy(dtype=float)
        if i == 0:
            # Establishing the first position IS traded notional.
            turn[i] = float(np.nansum(np.abs(tgt - prev)))
            prev = tgt
            continue
        r = rets.loc[dt].to_numpy(dtype=float)
        # Yesterday's holding earns today's return. One shift, one place.
        gross[i] = float(np.nansum(prev * np.nan_to_num(r)))
        drifted = drift_weights(prev, r)
        turn[i] = float(np.nansum(np.abs(tgt - drifted)))
        prev = tgt

    cost = turn * (cost_bps_per_side / 1e4)
    out = pd.DataFrame({"gross": gross, "turnover": turn, "cost": cost,
                        "net": gross - cost}, index=px.index)
    return out


def summarise(res: pd.DataFrame, periods_per_year: int = 365):
    """Headline statistics from a portfolio_returns frame."""
    net = res["net"].to_numpy(dtype=float)
    if not len(net):
        return {"n_days": 0}
    curve = np.cumprod(1.0 + net)
    peak = np.maximum.accumulate(curve)
    dd = (curve - peak) / peak
    ann = float(net.mean() * periods_per_year)
    vol = float(net.std(ddof=0) * np.sqrt(periods_per_year))
    return {"n_days": int(len(net)),
            "total_return": float(curve[-1] - 1.0),
            "ann_return": ann, "ann_vol": vol,
            "sharpe": (ann / vol) if vol > 0 else float("nan"),
            "max_drawdown": float(dd.min()),
            "avg_turnover": float(res["turnover"].mean()),
            "total_cost": float(res["cost"].sum())}


def time_folds(index, folds: int = 4):
    """Sequential equal-duration splits, same convention as
    pipeline.walkforward_folds."""
    idx = pd.DatetimeIndex(index)
    edges = pd.date_range(idx.min(), idx.max(), periods=folds + 1)
    out = []
    for k in range(folds):
        lo, hi = edges[k], edges[k + 1]
        m = (idx >= lo) & (idx < hi) if k < folds - 1 else (idx >= lo)
        out.append(idx[m])
    return out


# ----------------------------------------------------------------------
# PLACEBOS
# ----------------------------------------------------------------------
def rank_permutation_placebo(weights: pd.DataFrame, seed: int):
    """Permute WHICH ASSET gets each weight, ONE permutation per rebalance.

    Preserves exactly: the weight distribution each day, the number of
    positions, gross exposure, and THE TURNOVER PROFILE. Destroys exactly
    one thing -- the identity of the asset selected. So it isolates
    SELECTION skill from everything else the strategy does, which is what a
    rotation rule claims.

    A NEW PERMUTATION IS DRAWN ONLY WHEN THE TARGET WEIGHTS CHANGE, and held
    while they do not. This is the whole correctness of the instrument, and
    the first version got it wrong: it re-permuted every ROW. For a weekly
    rebalanced portfolio -- which holds one target for seven days -- that
    turned "hold these 5 names for a week" into "hold 5 DIFFERENT random
    names every day". Measured on #187/CONFIRMATION, the placebo's average
    turnover was 1.566 against the real rule's 0.116, a 13.6x inflation, and
    it paid 13x the transaction costs. That dragged the null to -0.38/yr
    almost entirely through fabricated trading, making the bar trivially
    beatable and the whole test a false-positive generator.

    Detecting the change from the weights themselves keeps this cadence-
    agnostic: a genuinely daily strategy changes its target every row and
    gets a fresh permutation every row, exactly as before.
    """
    rng = np.random.default_rng(seed)
    vals = weights.to_numpy(dtype=float).copy()
    perm = None
    prev = None
    for i in range(vals.shape[0]):
        row = vals[i]
        if np.nansum(np.abs(row)) == 0:      # cash — nothing to permute
            prev = row.copy()
            continue
        if prev is None or perm is None or not np.array_equal(row, prev):
            perm = rng.permutation(row.shape[0])
        prev = row.copy()                    # the ORIGINAL row, not the permuted one
        vals[i] = row[perm]
    return pd.DataFrame(vals, index=weights.index, columns=weights.columns)


def rank_permutation_fixed_placebo(weights: pd.DataFrame, seed: int):
    """The same weight PATH, pointed at a relabelled universe.

    ONE permutation of the asset labels, held for the whole window. This is
    the construction that differs from the strategy in EXACTLY ONE respect --
    which asset each weight lands on -- and it is the primary null for a
    selection claim.

    Why this and not the per-rebalance version. Permuting at each rebalance
    destroys two things at once: which assets were picked, AND the fact that
    a momentum rule tends to KEEP its winners week to week. The second is a
    turnover property, not a selection one, and paying for it makes the null
    poorer than the strategy for reasons that have nothing to do with skill.
    Measured on #187/CONFIRMATION, per-rebalance permutation still ran ~1.9x
    the real turnover after the row-wise bug was fixed, a residual drag of
    roughly 3 percentage points a year charged to the null alone. A fixed
    relabelling preserves the turnover path exactly, because it is the same
    path.

    It is also the control that stays INFORMATIVE next to #191b. Random-5
    redrawn weekly is already the "reshuffle every rebalance" null; a
    per-rebalance permutation would largely duplicate it. Two controls should
    answer two questions.
    """
    rng = np.random.default_rng(seed)
    perm = rng.permutation(weights.shape[1])
    vals = weights.to_numpy(dtype=float)[:, perm]
    return pd.DataFrame(vals, index=weights.index, columns=weights.columns)


def block_shuffle_placebo(weights: pd.DataFrame, seed: int, block_days: int = 21):
    """Shuffle contiguous BLOCKS of the weight path in time.

    Preserves the path's own autocorrelation and persistence within a block
    -- an allocation rule that ramps exposure slowly still ramps slowly --
    while destroying its alignment with what the market actually did. So it
    isolates TIMING from the shape of the exposure profile, which is what an
    allocation rule claims.
    """
    rng = np.random.default_rng(seed)
    n = len(weights)
    starts = list(range(0, n, block_days))
    order = rng.permutation(len(starts))
    pieces = [weights.iloc[s:s + block_days].to_numpy(dtype=float) for s in starts]
    stacked = np.vstack([pieces[i] for i in order])[:n]
    return pd.DataFrame(stacked, index=weights.index, columns=weights.columns)


def placebo_distribution(weights, prices, generator, seeds: int = 300,
                         cost_bps_per_side: float = DEFAULT_COST_BPS_PER_SIDE,
                         stat: str = "ann_return", **gen_kw):
    vals = []
    for s in range(seeds):
        wp = generator(weights, seed=s, **gen_kw)
        vals.append(summarise(portfolio_returns(wp, prices, cost_bps_per_side))[stat])
    a = np.array([v for v in vals if v == v])
    return {"seeds": seeds, "valid": int(len(a)),
            "mean": float(a.mean()) if len(a) else float("nan"),
            "p95": float(np.percentile(a, 95)) if len(a) else float("nan"),
            "p99": float(np.percentile(a, 99)) if len(a) else float("nan"),
            "values": a}


# ----------------------------------------------------------------------
# EQUIVALENCE GATE
# ----------------------------------------------------------------------
def buy_and_hold_weights(prices: pd.DataFrame, initial: dict):
    """The weight PATH of a buy-and-hold portfolio: set once, then drift.

    Used by the gate. If `portfolio_returns` handles drift correctly, feeding
    it this path produces ZERO turnover after day 0 and reproduces the
    analytic buy-and-hold return exactly.
    """
    px = prices.reindex(columns=list(initial.keys())).sort_index()
    rets = px.pct_change().fillna(0.0)
    rows, prev = [], np.array([initial[c] for c in px.columns], dtype=float)
    for i, dt in enumerate(px.index):
        if i == 0:
            rows.append(prev.copy())
            continue
        prev = drift_weights(prev, rets.loc[dt].to_numpy(dtype=float))
        rows.append(prev.copy())
    return pd.DataFrame(rows, index=px.index, columns=px.columns)


def equivalence_gate(prices: pd.DataFrame, tol: float = 1e-12):
    """Reproduce buy-and-hold and equal-weight-N to machine precision.

    A portfolio engine that cannot reproduce the two portfolios whose
    answers are known analytically has no business scoring one whose answer
    is not.
    """
    out = {}
    px = prices.dropna(how="any")
    cols = list(px.columns)

    # 1. Single-asset buy and hold, zero cost.
    a = cols[0]
    w = buy_and_hold_weights(px[[a]], {a: 1.0})
    res = portfolio_returns(w, px[[a]], cost_bps_per_side=0.0)
    got = float(np.cumprod(1.0 + res["net"].to_numpy())[-1] - 1.0)
    want = float(px[a].iloc[-1] / px[a].iloc[0] - 1.0)
    out["single_buy_and_hold"] = {"asset": a, "got": got, "want": want,
                                  "abs_err": abs(got - want),
                                  "pass": abs(got - want) <= tol,
                                  "turnover_after_day0": float(res["turnover"].iloc[1:].sum())}

    # 2. Equal-weight N buy and hold, zero cost.
    n = len(cols)
    init = {c: 1.0 / n for c in cols}
    w = buy_and_hold_weights(px, init)
    res = portfolio_returns(w, px, cost_bps_per_side=0.0)
    got = float(np.cumprod(1.0 + res["net"].to_numpy())[-1] - 1.0)
    want = float(np.mean([px[c].iloc[-1] / px[c].iloc[0] for c in cols]) - 1.0)
    out["equal_weight_buy_and_hold"] = {
        "n_assets": n, "got": got, "want": want, "abs_err": abs(got - want),
        "pass": abs(got - want) <= tol,
        "turnover_after_day0": float(res["turnover"].iloc[1:].sum())}

    # 3. Turnover accounting: a daily-rebalanced equal weight must charge
    #    exactly cost_bps * realised turnover, no more.
    ew = pd.DataFrame(1.0 / n, index=px.index, columns=cols)
    r0 = portfolio_returns(ew, px, cost_bps_per_side=0.0)
    r8 = portfolio_returns(ew, px, cost_bps_per_side=8.0)
    implied = float((r0["net"] - r8["net"]).sum())
    expected = float(r8["turnover"].sum() * 8.0 / 1e4)
    out["cost_accounting"] = {"implied": implied, "expected": expected,
                              "abs_err": abs(implied - expected),
                              "pass": abs(implied - expected) <= tol}

    out["all_pass"] = all(v["pass"] for k, v in out.items() if isinstance(v, dict))
    return out


if __name__ == "__main__":
    tick = [l.strip() for l in open(os.path.join(ROOT, "research",
                                                 "basket_tradable.txt"))
            if l.strip()]
    px = load_daily_closes(tick)
    print("EQUIVALENCE GATE — portfolio_harness")
    print("  assets loaded: %d, days: %d (%s -> %s)"
          % (px.shape[1], px.shape[0], px.index.min().date(), px.index.max().date()))
    g = equivalence_gate(px)
    for k in ("single_buy_and_hold", "equal_weight_buy_and_hold", "cost_accounting"):
        v = g[k]
        print("  %-28s got=%.15f want=%.15f abs_err=%.2e -> %s"
              % (k, v["got"] if "got" in v else v["implied"],
                 v["want"] if "want" in v else v["expected"],
                 v["abs_err"], "PASS" if v["pass"] else "FAIL"))
        if "turnover_after_day0" in v:
            print("  %-28s turnover after day 0: %.2e (must be 0 — drift is free)"
                  % ("", v["turnover_after_day0"]))
    print("\n  ALL PASS: %s" % g["all_pass"])
