"""ALLOCATION #193-#196 — exposure scaling on the tradable-26.

Registered and LOCKED in docs/cleanroom.md. Not which assets: how much.

THE STANDING RULE FROM ROTATION APPLIES HERE FIRST. A placebo must pay what
the strategy pays and be constrained the way the strategy is constrained.
ROTATION found rank_permutation_placebo fabricating 13.6x the real turnover;
block_shuffle_placebo is checked against the same property BEFORE a single
draw is scored -- see check_block_shuffle() and the repair it justifies.

Eligibility follows ROTATION's pinned completion: an asset joins the
equal-weight base once it has a complete 33-day price history, so the base
portfolio never holds an asset that does not yet exist.
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
import run_rotation as RT

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COST_BPS = 8.0          # registered
VOL_WINDOW = 30         # registered — 30-day realised stdev
ANNUALISE = np.sqrt(365.0)
CAP = 1.5               # registered, hard gross cap
FLOOR = 0.0             # registered, cash permitted
BLOCK_DAYS = 21         # registered
SEEDS = 1200            # registered
K_BONF = 4              # registered
ALPHA = 0.05 / K_BONF   # 0.0125
ADJ_PCTILE = 100.0 * (1.0 - ALPHA)   # 98.75
MIN_HISTORY = 33        # ROTATION's pinned eligibility


# ----------------------------------------------------------------------
# BASE PORTFOLIO AND SCALE PATHS
# ----------------------------------------------------------------------
def base_weights(px, min_history=MIN_HISTORY):
    """Equal-weight every eligible asset, weekly rebalance. Gross = 1.0."""
    return RT.equal_weight_weights(px, min_history=min_history)


def realised_vol(base_W, px):
    """30-day realised stdev of the BASE portfolio's daily returns,
    annualised by sqrt(365). Uses returns known at t; the weight built from
    it is held into t+1, so there is no lookahead."""
    _, _, _, net = RT.fast_returns(base_W.to_numpy(dtype=float),
                                   px.pct_change().fillna(0.0).to_numpy(dtype=float))
    r = pd.Series(net, index=px.index)
    return r.rolling(VOL_WINDOW).std(ddof=0) * ANNUALISE


def scale_path(vol, target, mode="target", cap=CAP, floor=FLOOR):
    """Weekly scale, held between Mondays.

    mode 'target'   : scale = target / realised   (scale DOWN when vol is high)
    mode 'inverted' : scale = realised / target   (#196 — scale UP when high)
    """
    raw = pd.Series(np.nan, index=vol.index)
    ok = vol.notna() & (vol > 0)
    if mode == "target":
        raw[ok] = target / vol[ok]
    elif mode == "inverted":
        raw[ok] = vol[ok] / target
    else:
        raise ValueError("mode must be 'target' or 'inverted'")
    raw = raw.clip(lower=floor, upper=cap)
    # Decide on Mondays only, hold through the week. Before the estimator
    # has warmed up there is no decision, so the position is 0 (cash).
    dec = raw[[d.weekday() == 0 for d in raw.index]]
    return dec.reindex(vol.index).ffill().fillna(0.0)


def scaled_weights(base_W, scale):
    return base_W.mul(scale, axis=0)


def matched_exposure_benchmark(base_W, rule_W):
    """Constant-weight equal-26 scaled by ONE constant c so its average
    gross exposure equals the tested rule's.

    c is computed from the rule's own realised exposure. It is not a free
    parameter and nothing is chosen by looking at returns.
    """
    base_gross = base_W.abs().sum(axis=1)
    rule_gross = rule_W.abs().sum(axis=1)
    denom = float(base_gross.mean())
    if denom <= 0:
        return base_W * 0.0, float("nan")
    c = float(rule_gross.mean()) / denom
    return base_W * c, c


# ----------------------------------------------------------------------
# THE STANDING PLACEBO CHECK
# ----------------------------------------------------------------------
def held_nonexistent_weight(W, px):
    """Fraction of gross weight placed on assets with no price that day.

    A time-shuffled weight path can land a late block on an early date and
    hold assets that had not listed yet. portfolio_returns fills missing
    returns with 0.0, so that weight would sit in a silent zero-return
    bucket -- a drag the real strategy never pays, invisible in the output.
    """
    alive = px.notna().to_numpy()
    Wv = np.abs(W.to_numpy(dtype=float))
    tot = Wv.sum()
    if tot <= 0:
        return 0.0
    return float(Wv[~alive].sum() / tot)


def scale_block_shuffle(scale: pd.Series, seed: int, block_days=BLOCK_DAYS):
    """THE REPAIR. Shuffle blocks of the SCALE path, not of the full weight
    matrix, then re-apply to the time-correct cross-section.

    An allocation rule's decision IS the scale; the cross-section is fixed
    and is not its claim. Shuffling the whole weight matrix moves the
    cross-section through time too, which on this dataset means holding
    assets that had not listed yet. Shuffling the scale destroys exactly the
    thing #193/#194 assert -- that exposure was raised and lowered at the
    right moments -- while preserving the exposure profile's shape, the
    investable universe, and the turnover the strategy actually pays.
    """
    rng = np.random.default_rng(seed)
    v = scale.to_numpy(dtype=float)
    n = len(v)
    starts = list(range(0, n, block_days))
    order = rng.permutation(len(starts))
    pieces = [v[s:s + block_days] for s in starts]
    stacked = np.concatenate([pieces[i] for i in order])[:n]
    return pd.Series(stacked, index=scale.index)


def check_block_shuffle(base_W, rule_W, scale, px, seeds=8):
    """Turnover fidelity + universe fidelity, both placebos, before any draw."""
    R = px.pct_change().fillna(0.0).to_numpy(dtype=float)
    real_turn = RT.ann_from_fast(rule_W.to_numpy(dtype=float), R)[1]
    rows = {}
    wt, wn = [], []
    st, sn = [], []
    for s in range(seeds):
        Wb = PH.block_shuffle_placebo(rule_W, seed=s, block_days=BLOCK_DAYS)
        wt.append(RT.ann_from_fast(Wb.to_numpy(dtype=float), R)[1])
        wn.append(held_nonexistent_weight(Wb, px))
        Ws = scaled_weights(base_W, scale_block_shuffle(scale, seed=s))
        st.append(RT.ann_from_fast(Ws.to_numpy(dtype=float), R)[1])
        sn.append(held_nonexistent_weight(Ws, px))
    rows["real_turnover"] = real_turn
    rows["weight_shuffle"] = {"turnover": float(np.mean(wt)),
                              "ratio": float(np.mean(wt) / real_turn),
                              "weight_on_nonexistent": float(np.mean(wn))}
    rows["scale_shuffle"] = {"turnover": float(np.mean(st)),
                             "ratio": float(np.mean(st) / real_turn),
                             "weight_on_nonexistent": float(np.mean(sn))}
    rows["real_weight_on_nonexistent"] = held_nonexistent_weight(rule_W, px)
    return rows


def placebo_distribution(base_W, scale, px, R, seeds=SEEDS):
    vals, turns = [], []
    for s in range(seeds):
        W = scaled_weights(base_W, scale_block_shuffle(scale, seed=s))
        a, t = RT.ann_from_fast(W.to_numpy(dtype=float), R)
        vals.append(a)
        turns.append(t)
    a = np.array([v for v in vals if v == v])
    return {"seeds": seeds, "mean": float(a.mean()),
            "p95": float(np.percentile(a, 95)),
            "p_adj": float(np.percentile(a, ADJ_PCTILE)),
            "avg_turnover": float(np.mean(turns))}


RULES = [("#193", "vol target 30%", 0.30, "target"),
         ("#194", "vol target 50%", 0.50, "target"),
         ("#196", "INVERTED 30% (control)", 0.30, "inverted")]


def drag_pp_per_year(extra_turnover, cost_bps=COST_BPS):
    """Turnover inflation expressed where it matters: annualised return."""
    return extra_turnover * (cost_bps / 1e4) * 365.0 * 100.0


def score(W, R):
    ann, turn = RT.ann_from_fast(W.to_numpy(dtype=float), R)
    g, t, c, net = RT.fast_returns(W.to_numpy(dtype=float), R)
    vol = float(net.std(ddof=0) * ANNUALISE)
    curve = np.cumprod(1.0 + net)
    peak = np.maximum.accumulate(curve)
    return {"ann_return": ann, "ann_vol": vol,
            "sharpe": (ann / vol) if vol > 0 else float("nan"),
            "max_dd": float(((curve - peak) / peak).min()),
            "avg_turnover": turn,
            "avg_gross": float(W.abs().sum(axis=1).mean())}


def run_window(px_win, wname):
    R = px_win.pct_change().fillna(0.0).to_numpy(dtype=float)
    base, ex, sk = base_weights(px_win)
    vol = realised_vol(base, px_win)
    out = {"base_rebal": [ex, ex + sk], "mean_realised_vol": float(vol.mean())}

    print("\n%s  (%s -> %s, %d days)  base rebal %d/%d  mean realised vol %.3f"
          % (wname, px_win.index.min().date(), px_win.index.max().date(),
             len(px_win), ex, ex + sk, float(vol.mean())))

    # ---- #195 constant 1.0x -------------------------------------------
    s195 = score(base, R)
    out["#195"] = dict(s195, label="constant 1.0x equal-weight-26")
    print("  #195  constant 1.0x            ann %+.3f  vol %.3f  sharpe %+.3f  gross %.3f"
          % (s195["ann_return"], s195["ann_vol"], s195["sharpe"], s195["avg_gross"]))

    for rid, label, target, mode in RULES:
        sc = scale_path(vol, target, mode)
        W = scaled_weights(base, sc)
        s = score(W, R)
        bench, c = matched_exposure_benchmark(base, W)
        sb = score(bench, R)
        # VERIFY the benchmark is exposure-matched, not merely intended to be
        gap = abs(float(bench.abs().sum(axis=1).mean()) -
                  float(W.abs().sum(axis=1).mean()))
        plc = placebo_distribution(base, sc, px_win, R)
        out[rid] = dict(s, label=label, target=target, mode=mode,
                        mean_scale=float(sc.mean()),
                        matched_c=c, matched_gap=gap,
                        matched_sharpe=sb["sharpe"], matched_ann=sb["ann_return"],
                        matched_vol=sb["ann_vol"], placebo=plc)
        print("  %s  %-24s ann %+.3f  vol %.3f  sharpe %+.3f  gross %.3f  "
              "| matched c=%.4f gap=%.2e sharpe %+.3f | plc p_adj %+.3f"
              % (rid, label, s["ann_return"], s["ann_vol"], s["sharpe"],
                 s["avg_gross"], c, gap, sb["sharpe"], plc["p_adj"]))
    return out


def main():
    uni = [l.strip() for l in
           open(os.path.join(ROOT, "research", "basket_tradable.txt"),
                encoding="utf-8") if l.strip()]
    px = PH.load_daily_closes(uni)
    bars, merged, daily = H.load_ticker("BTC")
    w = H.make_windows(daily)

    print("ALLOCATION #193-#196 — tradable-26, weekly, %.0fbps/side" % COST_BPS)
    print("=" * 104)
    print("Bonferroni k=%d -> alpha %.4f -> block-shuffle percentile %.2f (%d seeds)"
          % (K_BONF, ALPHA, ADJ_PCTILE, SEEDS))
    H.print_windows(w, daily, "windows from BTC, applied to the basket")

    out = {}
    for wname, win in (("DISCOVERY", w.discovery), ("CONFIRMATION", w.confirmation)):
        seg = px[(px.index >= win[0]) & (px.index < win[1])]
        base, _, _ = base_weights(seg)
        vol = realised_vol(base, seg)
        sc = scale_path(vol, 0.30, "target")
        chk = check_block_shuffle(base, scaled_weights(base, sc), sc, seg)
        chk["weight_shuffle"]["drag_pp"] = drag_pp_per_year(
            chk["weight_shuffle"]["turnover"] - chk["real_turnover"])
        chk["scale_shuffle"]["drag_pp"] = drag_pp_per_year(
            chk["scale_shuffle"]["turnover"] - chk["real_turnover"])
        out.setdefault("_fidelity", {})[wname] = chk
        out[wname] = run_window(seg, wname)

    with open(os.path.join(ROOT, "research", "allocation_results.json"), "w") as fh:
        json.dump(out, fh, indent=2, default=str)
    print("\nwrote research/allocation_results.json")
    return out


if __name__ == "__main__":
    main()
