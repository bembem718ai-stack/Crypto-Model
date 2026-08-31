"""EQUITIES #204-#216 — instrument validation on ETFs.

Registered and LOCKED in docs/cleanroom.md before this ran. Touches nothing
in the crypto model: no pipeline, no signal_engines, no live_tools, no crypto
data. Reads only data/equities/.

Fidelity checks run FIRST and their measured numbers are printed before any
placebo draw is scored (the standing rule from the architectural close-out,
now on three axes for the TS shuffle).
"""
import os
import sys
import json
import glob

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import portfolio_harness as PH
import window_stability as WS

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EQ = os.path.join(ROOT, "data", "equities")
MANIFEST = os.path.join(EQ, "MANIFEST_equities.json")

COST_BPS = 5.0          # registered, per side
SEEDS = 1200            # registered
DRAWS = 1200            # registered, random-N
K_BONF = 6              # registered
ALPHA = 0.05 / K_BONF
ADJ_PCTILE = 100.0 * (1.0 - ALPHA)      # 99.1667
MIN_ELIGIBLE = 12       # registered
TS_BLOCK_MONTHS = 12    # registered, with derivation
CASH_TOL = 0.02         # registered, +/-2% relative
TRADING_DAYS = 252      # equities annualisation
DISCOVERY_FRAC = 0.55
LOCKBOX_MONTHS = 6


# ----------------------------------------------------------------------
# DATA
# ----------------------------------------------------------------------
def load():
    man = json.load(open(MANIFEST, encoding="utf-8"))
    cols = {}
    for f in sorted(glob.glob(os.path.join(EQ, "*.csv.gz"))):
        t = os.path.basename(f).split(".")[0]
        cols[t] = pd.read_csv(f, index_col=0, parse_dates=True)["Close"]
    px = pd.DataFrame(cols).sort_index()
    elig_from = {}
    for t, v in man["etfs"].items():
        first = pd.Timestamp(v["first"])
        ffm = (first.to_period("M") + 1) if first.day != 1 else first.to_period("M")
        elig_from[t] = ffm + 1
    return px, elig_from, pd.Timestamp(man["freeze_date"])


def month_end_closes(px):
    me = px.resample("ME").last()
    me.index = me.index.to_period("M")
    return me


def signal(me, lookback):
    """12-1: me[M-2]/me[M-13]. 6-1: me[M-2]/me[M-7]. Skips month M-1."""
    return me.shift(2) / me.shift(1 + lookback) - 1.0


def eligibility(me, elig_from):
    return pd.DataFrame({t: [p >= elig_from[t] for p in me.index]
                         for t in me.columns}, index=me.index)


# ----------------------------------------------------------------------
# SCORING — vectorised, verified against portfolio_returns
# ----------------------------------------------------------------------
def fast_returns(Wv, R, cost_bps=COST_BPS):
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
    R = px.pct_change().fillna(0.0).to_numpy(dtype=float)
    worst = 0.0
    for name, W in paths:
        ref = PH.portfolio_returns(W, px, cost_bps_per_side=COST_BPS)
        g, t, c, net = fast_returns(W.to_numpy(dtype=float), R)
        for a, b in ((g, ref["gross"].to_numpy()), (t, ref["turnover"].to_numpy()),
                     (net, ref["net"].to_numpy())):
            e = float(np.nanmax(np.abs(a - b)))
            worst = max(worst, e)
            assert e < tol, "%s differs by %.2e" % (name, e)
    return worst


def score(W, R):
    g, t, c, net = fast_returns(W.to_numpy(dtype=float), R)
    ann = float(net.mean() * TRADING_DAYS)
    vol = float(net.std(ddof=0) * np.sqrt(TRADING_DAYS))
    curve = np.cumprod(1.0 + net)
    peak = np.maximum.accumulate(curve)
    return {"ann_return": ann, "ann_vol": vol,
            "sharpe": (ann / vol) if vol > 0 else float("nan"),
            "max_dd": float(((curve - peak) / peak).min()),
            "avg_turnover": float(t.mean()),
            "avg_gross": float(W.abs().sum(axis=1).mean())}


def drag_pp(extra_turnover):
    return extra_turnover * (COST_BPS / 1e4) * TRADING_DAYS * 100.0


# ----------------------------------------------------------------------
# WEIGHTS
# ----------------------------------------------------------------------
class MonthGrid:
    """Per-window scaffolding built ONCE and reused by every weight build.

    The first version called pandas .loc per month inside every chooser, and
    every placebo draw rebuilt the whole thing: ~9,600 weight builds x ~170
    months of pandas indexing. Everything here is a pure numpy view, so a
    draw costs an array slice instead of a few hundred pandas lookups.
    """

    def __init__(self, px, sig_by_lb, elig):
        self.px = px
        self.cols = list(px.columns)
        self.idx = px.index
        per = self.idx.to_period("M")
        self.per = per
        firsts = pd.Series(np.arange(len(self.idx)), index=per).groupby(level=0).first()
        self.months = list(firsts.index)                    # Periods, in order
        self.first_pos = firsts.to_numpy()                  # row of each decision
        # signal / eligibility as aligned numpy, one row per decision month
        self.sig = {lb: s.reindex(self.months).to_numpy(dtype=float)
                    for lb, s in sig_by_lb.items()}
        self.elig = elig.reindex(self.months).to_numpy(dtype=bool)
        self.n_assets = px.shape[1]

    def valid(self, lb, sig_override=None):
        s = self.sig[lb] if sig_override is None else sig_override
        return np.isfinite(s) & self.elig

    def to_frame(self, dec):
        """Decision rows -> daily weight path, held between rebalances."""
        W = np.zeros((len(self.idx), self.n_assets))
        for k, pos in enumerate(self.first_pos):
            end = self.first_pos[k + 1] if k + 1 < len(self.first_pos) else len(self.idx)
            W[pos:end] = dec[k]
        if self.first_pos[0] > 0:
            W[:self.first_pos[0]] = 0.0
        return pd.DataFrame(W, index=self.idx, columns=self.cols)


def _decide(grid, sig, ok, pick_fn):
    """Run pick_fn over months; returns (decisions, executed, skipped)."""
    dec = np.zeros((len(grid.months), grid.n_assets))
    ex = sk = 0
    for k in range(len(grid.months)):
        cand = np.flatnonzero(ok[k])
        w = pick_fn(k, cand, sig[k])
        if w is None:
            sk += 1
        else:
            dec[k] = w
            ex += 1
    return dec, ex, sk


CS_PARAMS = {"#204": (12, 3), "#205": (12, 5), "#206": (6, 3), "#207": (6, 5)}


def cs_weights(grid, lb, n, bottom=False, sig_override=None):
    sig = grid.sig[lb] if sig_override is None else sig_override
    ok = grid.valid(lb, sig_override=sig)

    def pick(k, cand, row):
        if len(cand) < MIN_ELIGIBLE or len(cand) <= n:
            return None
        vals = row[cand]
        order = np.argsort(vals)
        sel = cand[order[:n]] if bottom else cand[order[-n:]]
        w = np.zeros(grid.n_assets)
        w[sel] = 1.0 / n
        return w

    dec, ex, sk = _decide(grid, sig, ok, pick)
    return grid.to_frame(dec), ex, sk


def ts_weights(grid, sig_override=None, invert=False, only_idx=None):
    """Long if 12-1 > 0, else that slot sits in CASH (not redistributed)."""
    sig = grid.sig[12] if sig_override is None else sig_override
    ok = grid.valid(12, sig_override=sig)

    def pick(k, cand, row):
        if only_idx is not None:
            cand = cand[cand == only_idx]
            if not len(cand):
                return None
        elif len(cand) < MIN_ELIGIBLE:
            return None
        n = len(cand)
        vals = row[cand]
        on = cand[(vals < 0) if invert else (vals > 0)]
        w = np.zeros(grid.n_assets)
        w[on] = 1.0 / n
        return w

    dec, ex, sk = _decide(grid, sig, ok, pick)
    return grid.to_frame(dec), ex, sk


def equal_weight_weights(grid):
    sig, ok = grid.sig[12], grid.valid(12)

    def pick(k, cand, row):
        if len(cand) < MIN_ELIGIBLE:
            return None
        w = np.zeros(grid.n_assets)
        w[cand] = 1.0 / len(cand)
        return w

    dec, ex, sk = _decide(grid, sig, ok, pick)
    return grid.to_frame(dec), ex, sk


def random_n_weights(grid, n, seed):
    sig, ok = grid.sig[12], grid.valid(12)
    rng = np.random.default_rng(seed)

    def pick(k, cand, row):
        if len(cand) < MIN_ELIGIBLE or len(cand) <= n:
            return None
        sel = rng.choice(cand, size=n, replace=False)
        w = np.zeros(grid.n_assets)
        w[sel] = 1.0 / n
        return w

    dec, ex, sk = _decide(grid, sig, ok, pick)
    return grid.to_frame(dec), ex, sk










# ----------------------------------------------------------------------
# PLACEBOS
# ----------------------------------------------------------------------
def cs_signal_permutation(v, seed):
    """THE CS NULL. Relabel the universe in SIGNAL space, then run the real
    selection rule so the rule's own eligibility mask still applies.

    The registered generator was rank_permutation_fixed_placebo, which
    permutes the OUTPUT WEIGHTS. Measured here before any draw, on DISCOVERY
    that placed 7.06-7.86% of gross weight in ETFs that were not yet
    eligible (real rule: 0.000%), because a single fixed relabelling cannot
    respect a universe that grows from 13 ETFs to 21. Those holdings earn
    exactly zero through fillna(0.0) -- the ALLOCATION defect, in a new
    costume. On CONFIRMATION the universe is complete and the figure was
    0.000%, so the defect is confined to DISCOVERY and would have made
    exactly one window's bar easier.

    Repaired on the standing principle: permute the DECISION INPUT and let
    the strategy's own constraints apply to the result. One fixed
    permutation per seed, held for the whole window, so the weight path's
    texture and turnover are preserved; eligibility is enforced downstream
    by the same code the real rule uses, so ineligible weight is 0.000% by
    construction rather than by luck.
    """
    rng = np.random.default_rng(seed)
    return v[:, rng.permutation(v.shape[1])]


def ts_signal_block_shuffle(v, seed, block=TS_BLOCK_MONTHS):
    """Block-shuffle the SIGNAL path in time; cross-section stays put.

    Operates on the month x asset numpy grid. Whole blocks are permuted, so
    the multiset of signal rows -- and therefore the cash-month count -- is
    preserved exactly apart from truncation of a final partial block.
    """
    rng = np.random.default_rng(seed)
    n = len(v)
    starts = list(range(0, n, block))
    order = rng.permutation(len(starts))
    pieces = [v[s:s + block] for s in starts]
    return np.vstack([pieces[i] for i in order])[:n]


def weight_on_ineligible(W, px, elig):
    """Gross weight held in ETFs not yet eligible that month."""
    per = W.index.to_period("M")
    ok = elig.reindex(per).to_numpy()
    Wv = np.abs(W.to_numpy(dtype=float))
    tot = Wv.sum()
    return 0.0 if tot <= 0 else float(Wv[~ok].sum() / tot)


def cash_eligible_months(W, grid):
    """ELIGIBLE asset-months in which the rule holds nothing.

    The registered axis is the CASH-ELIGIBLE-month count. Counting every
    zero cell instead would count ETFs that had not launched yet, which are
    trivially zero for the rule and the null alike and which vary with the
    growing universe rather than with anything either one decides. Masking
    to eligible cells measures the quantity the axis is about: how often the
    rule chose to stand aside from something it could have held.
    """
    dec = W.to_numpy()[grid.first_pos]
    return int(((dec == 0) & grid.elig).sum())


# ----------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------
RULES_CS = [("#204", "CS top-3 12-1", 12, 3), ("#205", "CS top-5 12-1", 12, 5),
            ("#206", "CS top-3 6-1", 6, 3), ("#207", "CS top-5 6-1", 6, 5)]
CTRL_CS = [("#211", "CS bottom-3 12-1", 12, 3), ("#212", "CS bottom-5 12-1", 12, 5),
           ("#213", "CS bottom-3 6-1", 6, 3), ("#214", "CS bottom-5 6-1", 6, 5)]


def build(grid):
    """All weight paths for one window."""
    W, meta = {}, {}
    for rid, label, lb, n in RULES_CS:
        W[rid], ex, sk = cs_weights(grid, lb, n)
        meta[rid] = (label, ex, sk)
    for rid, label, lb, n in CTRL_CS:
        W[rid], ex, sk = cs_weights(grid, lb, n, bottom=True)
        meta[rid] = (label, ex, sk)
    W["#208"], ex, sk = ts_weights(grid)
    meta["#208"] = ("TS-MOM eligible 12-1", ex, sk)
    spy = grid.cols.index("SPY")
    W["#209"], ex, sk = ts_weights(grid, only_idx=spy)
    meta["#209"] = ("SPY absolute mom", ex, sk)
    W["#210"], ex, sk = equal_weight_weights(grid)
    meta["#210"] = ("equal-weight eligible", ex, sk)
    W["#216"], ex, sk = ts_weights(grid, invert=True)
    meta["#216"] = ("TS INVERTED 12-1", ex, sk)
    return W, meta


def main():
    px_all, elig_from, freeze = load()
    me = month_end_closes(px_all)
    sig12, sig6 = signal(me, 12), signal(me, 6)
    elig_all = eligibility(me, elig_from)

    ok12 = (sig12.notna() & elig_all).sum(axis=1)
    start = ok12[ok12 >= MIN_ELIGIBLE].index[0].to_timestamp()
    lock = freeze - pd.DateOffset(months=LOCKBOX_MONTHS)
    cut = start + (lock - start) * DISCOVERY_FRAC

    print("EQUITIES #204-#216 — instrument validation, 21 ETFs, monthly, %.0fbps/side"
          % COST_BPS)
    print("=" * 118)
    print("Bonferroni k=%d -> alpha %.6f -> placebo percentile %.4f (%d seeds)"
          % (K_BONF, ALPHA, ADJ_PCTILE, SEEDS))
    print("  freeze       %s" % freeze.date())
    print("  DISCOVERY    %s -> %s  (%.2fy)"
          % (start.date(), cut.date(), (cut - start).days / 365.25))
    print("  CONFIRMATION %s -> %s  (%.2fy)"
          % (cut.date(), lock.date(), (lock - cut).days / 365.25))
    print("  LOCKBOX      %s -> %s  *** SEALED, never read ***"
          % (lock.date(), freeze.date()))

    out = {}
    for wname, lo, hi in (("DISCOVERY", start, cut), ("CONFIRMATION", cut, lock)):
        px = px_all[(px_all.index >= lo) & (px_all.index < hi)]
        R = px.pct_change().fillna(0.0).to_numpy(dtype=float)
        grid = MonthGrid(px, {12: sig12, 6: sig6}, elig_all)
        spy_idx = grid.cols.index("SPY")
        W, meta = build(grid)

        print("\n%s  (%s -> %s, %d trading days)"
              % (wname, px.index.min().date(), px.index.max().date(), len(px)))
        err = verify_fast_path(px, [(k, W[k]) for k in ("#204", "#207", "#208", "#210")])
        print("  fast path VERIFIED against portfolio_returns: max abs err %.2e" % err)

        # ---------- FIDELITY, BEFORE ANY DRAW ----------
        print("\n  PLACEBO FIDELITY — measured before a single draw is scored")
        fid = {}
        for rid in ("#204", "#205", "#206", "#207"):
            real = score(W[rid], R)
            rt, ru = [], []
            lb, n = CS_PARAMS[rid]
            for s in range(8):
                sp = cs_signal_permutation(grid.sig[lb], seed=s)
                wp, _, _ = cs_weights(grid, lb, n, sig_override=sp)
                rt.append(score(wp, R)["avg_turnover"])
                ru.append(weight_on_ineligible(wp, px, elig_all))
            f = {"real_turn": real["avg_turnover"], "plc_turn": float(np.mean(rt)),
                 "ratio": float(np.mean(rt) / real["avg_turnover"]),
                 "drag_pp": drag_pp(float(np.mean(rt)) - real["avg_turnover"]),
                 "real_inelig": weight_on_ineligible(W[rid], px, elig_all),
                 "plc_inelig": float(np.mean(ru))}
            fid[rid] = f
            print("    %s CS  turn %.4f -> %.4f (%.2fx, drag %+.3f pp/yr) | "
                  "ineligible weight real %.3f%% plc %.3f%%"
                  % (rid, f["real_turn"], f["plc_turn"], f["ratio"], f["drag_pp"],
                     100 * f["real_inelig"], 100 * f["plc_inelig"]))

        for rid, only in (("#208", None), ("#209", spy_idx)):
            real = score(W[rid], R)
            real_cash = cash_eligible_months(W[rid], grid)
            rt, ru, rc = [], [], []
            for s in range(8):
                sp = ts_signal_block_shuffle(grid.sig[12], seed=s)
                Wp, _, _ = ts_weights(grid, sig_override=sp, only_idx=only)
                rt.append(score(Wp, R)["avg_turnover"])
                ru.append(weight_on_ineligible(Wp, px, elig_all))
                rc.append(cash_eligible_months(Wp, grid))
            dev = abs(float(np.mean(rc)) - real_cash) / max(real_cash, 1)
            f = {"real_turn": real["avg_turnover"], "plc_turn": float(np.mean(rt)),
                 "ratio": float(np.mean(rt) / max(real["avg_turnover"], 1e-12)),
                 "drag_pp": drag_pp(float(np.mean(rt)) - real["avg_turnover"]),
                 "real_inelig": weight_on_ineligible(W[rid], px, elig_all),
                 "plc_inelig": float(np.mean(ru)),
                 "real_cash_months": real_cash,
                 "plc_cash_months": float(np.mean(rc)),
                 "cash_dev": dev, "cash_ok": bool(dev <= CASH_TOL)}
            fid[rid] = f
            print("    %s TS  turn %.4f -> %.4f (%.2fx, drag %+.3f pp/yr) | "
                  "ineligible %.3f%%/%.3f%% | cash-months %d -> %.1f "
                  "(dev %.2f%%, tol 2%%) %s"
                  % (rid, f["real_turn"], f["plc_turn"], f["ratio"], f["drag_pp"],
                     100 * f["real_inelig"], 100 * f["plc_inelig"],
                     f["real_cash_months"], f["plc_cash_months"], 100 * dev,
                     "PASS" if f["cash_ok"] else "FAIL"))
        out.setdefault("_fidelity", {})[wname] = fid

        # ---------- SCORES ----------
        res = {}
        for rid in W:
            res[rid] = dict(score(W[rid], R), label=meta[rid][0],
                            rebal_executed=meta[rid][1], rebal_skipped=meta[rid][2])

        print("\n  scoring placebos (%d seeds each)..." % SEEDS)
        for rid in ("#204", "#205", "#206", "#207"):
            lb, n = CS_PARAMS[rid]
            a = np.array([score(cs_weights(grid, lb, n,
                                           sig_override=cs_signal_permutation(
                                               grid.sig[lb], seed=s))[0],
                                R)["ann_return"] for s in range(SEEDS)])
            res[rid]["placebo"] = {"p95": float(np.percentile(a, 95)),
                                   "p_adj": float(np.percentile(a, ADJ_PCTILE)),
                                   "mean": float(a.mean()),
                                   "pctile": float(100.0 * (a < res[rid]["ann_return"]).mean())}
        for rid, only in (("#208", None), ("#209", spy_idx)):
            vals = []
            for s in range(SEEDS):
                sp = ts_signal_block_shuffle(grid.sig[12], seed=s)
                Wp, _, _ = ts_weights(grid, sig_override=sp, only_idx=only)
                vals.append(score(Wp, R)["ann_return"])
            a = np.array(vals)
            res[rid]["placebo"] = {"p95": float(np.percentile(a, 95)),
                                   "p_adj": float(np.percentile(a, ADJ_PCTILE)),
                                   "mean": float(a.mean()),
                                   "pctile": float(100.0 * (a < res[rid]["ann_return"]).mean())}

        res["_random"] = {}
        for n in (3, 5):
            vals = []
            for s in range(DRAWS):
                Wr, _, _ = random_n_weights(grid, n, seed=700000 + s)
                vals.append(score(Wr, R)["ann_return"])
            a = np.array(vals)
            res["_random"][str(n)] = {"draws": DRAWS, "p05": float(np.percentile(a, 5)),
                                      "p50": float(np.percentile(a, 50)),
                                      "p95": float(np.percentile(a, 95)),
                                      "mean": float(a.mean())}
            d = res["_random"][str(n)]
            print("    #215 random-%d: p05 %+.4f  p50 %+.4f  p95 %+.4f"
                  % (n, d["p05"], d["p50"], d["p95"]))
        out[wname] = res

    out["_windows"] = {"start": str(start.date()), "cut": str(cut.date()),
                       "lock": str(lock.date()), "freeze": str(freeze.date())}
    with open(os.path.join(ROOT, "research", "equities_results.json"), "w") as fh:
        json.dump(out, fh, indent=2, default=str)
    print("\nwrote research/equities_results.json")
    return out


if __name__ == "__main__":
    main()
