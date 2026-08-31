"""NULL-CALIBRATION #217-#219 — a methods program. No edge claims.

Registered and LOCKED in docs/cleanroom.md before this ran. Changes no
verdict. Every registered FAIL stands.

#217 measures how much of each historical clause-2 bar was inherited effect.
#218 measures the time-rotation null's own fidelity on all four axes.
#219 re-scores clause 2 as CALIBRATION ONLY.
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import portfolio_harness as PH
import harness as H
import run_rotation as RT
import run_equities as EQ

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEEDS = 1200            # registered, matching every prior program
MIN_OFFSET_MONTHS = 24  # registered, twice the longest formation horizon


# ----------------------------------------------------------------------
# THE TIME-ROTATION NULL (#218)
# ----------------------------------------------------------------------
def offset_bounds(n_periods, periods_per_month):
    """Registered offset range [24 months, T-24 months], in periods.

    Returns (lo, hi) or None when the range is EMPTY -- which happens on any
    window shorter than 48 months. That is not a bug to route around: the
    bound is locked, and a window too short to satisfy it cannot carry this
    null (research rule 4).
    """
    lo = int(round(MIN_OFFSET_MONTHS * periods_per_month))
    hi = int(round(n_periods - MIN_OFFSET_MONTHS * periods_per_month))
    return (lo, hi) if hi > lo else None


def time_rotation(sig, seed, bounds):
    """Circular shift of the WHOLE signal matrix; every asset moves together.

    Preserves the full cross-section at every date, each asset's
    autocorrelation, and every marginal distribution. Breaks only the
    alignment between signal and the returns that followed it.
    """
    lo, hi = bounds
    rng = np.random.default_rng(seed)
    k = int(rng.integers(lo, hi + 1))
    return np.roll(sig, k, axis=0), k


# ----------------------------------------------------------------------
# #217 — INHERITANCE MEASUREMENT
# ----------------------------------------------------------------------
def rho_bar(px_win):
    """Mean off-diagonal daily-return correlation, assets present throughout."""
    full = px_win.columns[px_win.notna().all()]
    if len(full) < 2:
        full = px_win.columns[px_win.notna().mean() > 0.99]
    r = px_win[full].pct_change().dropna(how="all")
    c = r.corr().to_numpy()
    iu = np.triu_indices_from(c, k=1)
    v = c[iu]
    v = v[np.isfinite(v)]
    return float(v.mean()), int(len(full))



def eq_windows():
    """The EXACT boundaries run_equities computes, not date-string round trips.

    Round-tripping cut/lock through "YYYY-MM-DD" drops the sub-day component
    and shifts a window edge by part of a trading day, which moved the real
    returns in the 4th decimal. A calibration report has to compare against
    the registered numbers, not near-copies of them.
    """
    px_all, elig_from, freeze = EQ.load()
    me = EQ.month_end_closes(px_all)
    sigs = {12: EQ.signal(me, 12), 6: EQ.signal(me, 6)}
    elig = EQ.eligibility(me, elig_from)
    ok12 = (sigs[12].notna() & elig).sum(axis=1)
    start = ok12[ok12 >= EQ.MIN_ELIGIBLE].index[0].to_timestamp()
    lock = freeze - pd.DateOffset(months=EQ.LOCKBOX_MONTHS)
    cut = start + (lock - start) * EQ.DISCOVERY_FRAC
    return px_all, sigs, elig, [("DISCOVERY", start, cut), ("CONFIRMATION", cut, lock)]


def crypto_inheritance():
    """#217 for crypto ROTATION #187-#190."""
    uni = [l.strip() for l in
           open(os.path.join(ROOT, "research", "basket_tradable.txt"),
                encoding="utf-8") if l.strip()]
    px = PH.load_daily_closes(uni)
    bars, merged, daily = H.load_ticker("BTC")
    w = H.make_windows(daily)
    stored = json.load(open(os.path.join(ROOT, "research", "rotation_results.json")))

    rows = []
    for wname, win in (("DISCOVERY", w.discovery), ("CONFIRMATION", w.confirmation)):
        seg = px[(px.index >= win[0]) & (px.index < win[1])]
        Rm = seg.pct_change().fillna(0.0).to_numpy(dtype=float)
        rb, n_full = rho_bar(seg)
        eq = stored[wname]["#191"]["ann_return"]
        for rid, label, kw, is_top5 in RT.RULES:
            if rid == "#192":
                continue
            W, _, _ = RT.momentum_weights(seg, **kw)
            vals = [RT.ann_from_fast(
                PH.rank_permutation_fixed_placebo(W, seed=s).to_numpy(dtype=float),
                Rm)[0] for s in range(SEEDS)]
            centre = float(np.median(vals))
            lb = str(kw["lookback"])
            rn = (stored[wname]["_random5"][lb]["p50"]
                  if kw["n"] == 5 else float("nan"))
            rows.append({"program": "ROTATION", "rule": rid, "label": label,
                         "window": wname, "null_centre": centre,
                         "random_n": rn, "equal_weight": eq,
                         "excess_random": (centre - rn) if rn == rn else float("nan"),
                         "excess_eq": centre - eq,
                         "rho_bar": rb, "n_assets": n_full,
                         "matched_n": kw["n"]})
    return rows


def equities_inheritance():
    """#217 for equities CS #204-#207."""
    stored = json.load(open(os.path.join(ROOT, "research", "equities_results.json")))
    px_all, sigs, elig, wins = eq_windows()

    rows = []
    for wname, lo, hi in wins:
        seg = px_all[(px_all.index >= lo) & (px_all.index < hi)]
        R = seg.pct_change().fillna(0.0).to_numpy(dtype=float)
        grid = EQ.MonthGrid(seg, sigs, elig)
        rb, n_full = rho_bar(seg)
        eq = stored[wname]["#210"]["ann_return"]
        for rid, (lb, n) in EQ.CS_PARAMS.items():
            vals = []
            for s in range(SEEDS):
                sp = EQ.cs_signal_permutation(grid.sig[lb], seed=s)
                Wp, _, _ = EQ.cs_weights(grid, lb, n, sig_override=sp)
                vals.append(EQ.score(Wp, R)["ann_return"])
            centre = float(np.median(vals))
            rn = stored[wname]["_random"][str(n)]["p50"]
            rows.append({"program": "EQUITIES", "rule": rid,
                         "label": "CS top-%d %d-1" % (n, lb),
                         "window": wname, "null_centre": centre,
                         "random_n": rn, "equal_weight": eq,
                         "excess_random": centre - rn,
                         "excess_eq": centre - eq,
                         "rho_bar": rb, "n_assets": n_full, "matched_n": n})
    return rows


# ----------------------------------------------------------------------
# #218 — FIDELITY OF THE TIME-ROTATION NULL, all four axes
# ----------------------------------------------------------------------
def rotation_fidelity(grid, seg, R, rid, lb, n, stored_rand_p50, n_probe=16):
    """All four axes, measured before any draw scores anything."""
    bounds = offset_bounds(len(grid.months), 1.0)      # signal is monthly
    if bounds is None:
        return None
    real_W, _, _ = EQ.cs_weights(grid, lb, n)
    real = EQ.score(real_W, R)
    real_cash = EQ.cash_eligible_months(real_W, grid)
    turns, inelig, cash, offs = [], [], [], []
    for s in range(n_probe):
        sp, k = time_rotation(grid.sig[lb], seed=s, bounds=bounds)
        Wp, _, _ = EQ.cs_weights(grid, lb, n, sig_override=sp)
        turns.append(EQ.score(Wp, R)["avg_turnover"])
        inelig.append(EQ.weight_on_ineligible(Wp, seg, grid_elig_frame(grid)))
        cash.append(EQ.cash_eligible_months(Wp, grid))
        offs.append(k)
    # axis 4 needs the full distribution centre
    vals = []
    for s in range(SEEDS):
        sp, _ = time_rotation(grid.sig[lb], seed=s, bounds=bounds)
        Wp, _, _ = EQ.cs_weights(grid, lb, n, sig_override=sp)
        vals.append(EQ.score(Wp, R)["ann_return"])
    a = np.array(vals)
    dev = abs(float(np.mean(cash)) - real_cash) / max(real_cash, 1)
    return {"bounds_months": bounds, "offsets_used": (min(offs), max(offs)),
            "real_turn": real["avg_turnover"], "plc_turn": float(np.mean(turns)),
            "ratio": float(np.mean(turns) / real["avg_turnover"]),
            "drag_pp": EQ.drag_pp(float(np.mean(turns)) - real["avg_turnover"]),
            "real_inelig": EQ.weight_on_ineligible(real_W, seg, grid_elig_frame(grid)),
            "plc_inelig": float(np.mean(inelig)),
            "real_cash": real_cash, "plc_cash": float(np.mean(cash)),
            "cash_dev": dev, "cash_ok": bool(dev <= EQ.CASH_TOL),
            "centre": float(np.median(a)), "random_p50": stored_rand_p50,
            "inheritance": float(np.median(a)) - stored_rand_p50,
            "p95": float(np.percentile(a, 95)),
            "p_adj": float(np.percentile(a, EQ.ADJ_PCTILE)),
            "real_ann": real["ann_return"],
            "pctile": float(100.0 * (a < real["ann_return"]).mean())}


_ELIG_CACHE = {}


def grid_elig_frame(grid):
    """The eligibility frame EQ.weight_on_ineligible expects (period-indexed)."""
    key = id(grid)
    if key not in _ELIG_CACHE:
        _ELIG_CACHE[key] = pd.DataFrame(grid.elig, index=grid.months,
                                        columns=grid.cols)
    return _ELIG_CACHE[key]


def main():
    print("NULL-CALIBRATION #217-#219 — a METHODS program. No edge claims.")
    print("=" * 122)
    print("Changes no verdict. Every registered FAIL stands.\n")

    # ================= #217 =================
    print("#217 — INHERITANCE MEASUREMENT (descriptive, table only)")
    print("=" * 122)
    rows = crypto_inheritance() + equities_inheritance()
    print("%-9s %-6s %-16s %-13s %10s %10s %10s %12s %12s %8s"
          % ("program", "#", "rule", "window", "null ctr", "rand-N p50",
             "eq-wt", "exc rand pp", "exc eq pp", "rho-bar"))
    print("-" * 122)
    for r in rows:
        er = ("—" if r["excess_random"] != r["excess_random"]
              else "%+12.2f" % (100 * r["excess_random"]))
        rn = ("—" if r["random_n"] != r["random_n"] else "%+10.4f" % r["random_n"])
        print("%-9s %-6s %-16s %-13s %+10.4f %10s %+10.4f %12s %+12.2f %8.3f"
              % (r["program"], r["rule"], r["label"], r["window"],
                 r["null_centre"], rn, r["equal_weight"], er,
                 100 * r["excess_eq"], r["rho_bar"]))
    print("\n  rho-bar = mean off-diagonal daily-return correlation over assets")
    print("  present for the whole window. Excesses are in PERCENTAGE POINTS/YEAR.")
    print("  Top-10 rules (#188/#190) have no matched random-N: the ROTATION")
    print("  registration refused to invent a random-10 after seeing results,")
    print("  and that refusal is honoured here rather than quietly reversed.\n")

    out = {"217": rows}

    # ================= #218 =================
    print("#218 — TIME-ROTATION NULL, OWN FIDELITY (four axes, before any draw)")
    print("=" * 122)
    print("Registered offset range [24 months, T-24 months]. Feasibility FIRST:\n")
    feas = {}
    bars, merged, daily = H.load_ticker("BTC")
    w = H.make_windows(daily)
    for nm, lo, hi in (("crypto ROTATION DISCOVERY", w.discovery[0], w.discovery[1]),
                       ("crypto ROTATION CONFIRMATION", w.confirmation[0], w.confirmation[1])):
        T = (pd.Timestamp(hi) - pd.Timestamp(lo)).days / 30.44
        feas[nm] = bool((T - 24) > 24)
        print("  %-30s T = %6.1f months -> [24, %.1f]   %s"
              % (nm, T, T - 24, "FEASIBLE" if feas[nm] else "*** EMPTY - INFEASIBLE ***"))

    stored_eq = json.load(open(os.path.join(ROOT, "research", "equities_results.json")))
    px_all, sigs, elig, wins = eq_windows()
    for (wn0, lo, hi), nm in zip(wins, ("equities DISCOVERY", "equities CONFIRMATION")):
        T = (pd.Timestamp(hi) - pd.Timestamp(lo)).days / 30.44
        feas[nm] = bool((T - 24) > 24)
        print("  %-30s T = %6.1f months -> [24, %.1f]   %s"
              % (nm, T, T - 24, "FEASIBLE" if feas[nm] else "*** EMPTY - INFEASIBLE ***"))

    print("\n  The crypto ROTATION windows CANNOT carry this null. The bound is")
    print("  locked (research rule 4) and may not be relaxed to make a run happen,")
    print("  and rotating over the full crypto series to lengthen T would pull")
    print("  signal rows out of the LOCKBOX. #187's leg of #219 is INFEASIBLE.\n")

    fid = {}
    for wname, lo, hi in wins:
        seg = px_all[(px_all.index >= lo) & (px_all.index < hi)]
        R = seg.pct_change().fillna(0.0).to_numpy(dtype=float)
        grid = EQ.MonthGrid(seg, sigs, elig)
        for rid in ("#204", "#205"):
            lb, n = EQ.CS_PARAMS[rid]
            rp = stored_eq[wname]["_random"][str(n)]["p50"]
            f = rotation_fidelity(grid, seg, R, rid, lb, n, rp)
            fid.setdefault(wname, {})[rid] = f
            print("  %-13s %s  offsets used %d..%d months (range [%d, %d])"
                  % (wname, rid, f["offsets_used"][0], f["offsets_used"][1],
                     f["bounds_months"][0], f["bounds_months"][1]))
            print("      1 turnover     real %.4f -> null %.4f  (%.2fx)  drag %+.3f pp/yr"
                  % (f["real_turn"], f["plc_turn"], f["ratio"], f["drag_pp"]))
            print("      2 universe     ineligible weight  real %.3f%%  null %.3f%%"
                  % (100 * f["real_inelig"], 100 * f["plc_inelig"]))
            print("      3 cash-months  real %d -> null %.1f  dev %.2f%% (tol 2%%)  %s"
                  % (f["real_cash"], f["plc_cash"], 100 * f["cash_dev"],
                     "PASS" if f["cash_ok"] else "FAIL"))
            print("      4 inheritance  null centre %+.4f - random-%d p50 %+.4f = %+.2f pp/yr"
                  % (f["centre"], n, f["random_p50"], 100 * f["inheritance"]))
    out["218"] = {"feasibility": feas, "fidelity": fid}

    # ================= #219 =================
    print("\n#219 — CALIBRATION RE-SCORE (clause 2 only). NO VERDICT CHANGES.")
    print("=" * 122)
    sentences = {}
    orig_rot = json.load(open(os.path.join(ROOT, "research", "rotation_results.json")))
    o = orig_rot["DISCOVERY"]["#187"]
    sentences["#187"] = {
        "original": ("registered null: DISCOVERY %+.4f vs p_adj %+.4f -> PASS; "
                     "CONFIRMATION %+.4f vs p_adj %+.4f -> FAIL"
                     % (o["ann_return"], o["placebo"]["p_adj"],
                        orig_rot["CONFIRMATION"]["#187"]["ann_return"],
                        orig_rot["CONFIRMATION"]["#187"]["placebo"]["p_adj"])),
        "corrected": "INFEASIBLE — the locked [24, T-24] offset range is empty "
                     "on both ROTATION windows (42.4 and 34.7 months).",
    }
    for rid in ("#204", "#205"):
        parts, cor = [], []
        for wname in ("DISCOVERY", "CONFIRMATION"):
            s = stored_eq[wname][rid]
            parts.append("%s %+.4f vs p_adj %+.4f -> %s"
                         % (wname[:4], s["ann_return"], s["placebo"]["p_adj"],
                            "PASS" if s["ann_return"] > s["placebo"]["p_adj"] else "FAIL"))
            f = fid[wname][rid]
            cor.append("%s %+.4f vs p_adj %+.4f -> %s"
                       % (wname[:4], f["real_ann"], f["p_adj"],
                          "PASS" if f["real_ann"] > f["p_adj"] else "FAIL"))
        sentences[rid] = {"original": "registered null: " + "; ".join(parts),
                          "corrected": "; ".join(cor)}
    for rid in ("#187", "#204", "#205"):
        print("\n  %s" % rid)
        print("    ORIGINAL  %s" % sentences[rid]["original"])
        print("    Under the corrected null, clause 2 would have read: %s"
              % sentences[rid]["corrected"])
    out["219"] = sentences

    with open(os.path.join(ROOT, "research", "null_calibration.json"), "w") as fh:
        json.dump(out, fh, indent=2, default=str)
    print("\nwrote research/null_calibration.json")
    print("\nEVERY REGISTERED VERDICT IS UNCHANGED. #187 FAIL. #204 FAIL. #205 FAIL.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
