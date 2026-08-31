"""#220-#234 — BINANCE FUNDING. Locked in docs/cleanroom.md before this ran.

EXECUTION ORDER (registered §7): all fifteen tests run in ONE batch from ONE
invocation, and ALL results are written to disk BEFORE ANY is read. main()
therefore scores everything, dumps JSON, and only then prints. A crash
mid-batch voids the run -- it is fixed and the whole batch re-run.

Every constant is inherited verbatim from #172-#186. Nothing here is chosen.
"""
import os
import sys
import json
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import harness as H
import pipeline as p

warnings.filterwarnings("ignore")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FUNDING = os.path.join(ROOT, "data", "derivatives", "binance_funding.csv")
RESULTS = os.path.join(ROOT, "research", "h220_results.json")

TICKERS = [("BTC", "BTCUSDT"), ("ETH", "ETHUSDT"), ("SOL", "SOLUSDT")]
TIER = {"BUY", "STRONG_BUY"}
G = p.LIVE_GEOMETRY
SEEDS = 3000                      # registered
K_TESTS = 15                      # registered
ALPHA = 0.05 / K_TESTS
ADJ_PCTILE = 100.0 * (1.0 - ALPHA)        # 99.6667
FOLDS = 4
MIN_SETTLEMENTS = 2               # registered §6, signed off: >= 2 of 3
LOCKBOX_MONTHS = 6
BURN_IN_MONTHS = 4
DISCOVERY_FRAC = 0.55
XVENUE_BAR = 0.80                 # inherited cross-venue flag


# ======================================================================
# FUNDING FEATURES
# ======================================================================
def load_funding():
    d = pd.read_csv(FUNDING)
    d["ts"] = pd.to_datetime(d["timestamp"], utc=True, format="mixed")
    return d


def daily_features(g):
    """Daily funding features for one symbol. All definitions inherited."""
    g = g.sort_values("ts").reset_index(drop=True)
    day = g["ts"].dt.tz_localize(None).dt.normalize()

    # --- daily mean, with the registered >=2 of 3 coverage rule ---------
    n_per_day = g.groupby(day)["funding_rate"].size()
    mean_per_day = g.groupby(day)["funding_rate"].mean()
    eligible = n_per_day >= MIN_SETTLEMENTS
    dm = mean_per_day.where(eligible)
    excluded = int((~eligible).sum())

    # --- 8h-equivalent, last settlement of each day (registered §2) -----
    # Binance settles natively at 8h, so a row IS the 8h-equivalent; shorter
    # stress intervals are SUMMED to 8h. Rolling sum over the trailing rows
    # covering 8 hours, evaluated at the last settlement of the day.
    hrs = g["funding_interval_hours"].to_numpy(dtype=float)
    rate = g["funding_rate"].to_numpy(dtype=float)
    eq8 = np.full(len(g), np.nan)
    for i in range(len(g)):
        acc_h, acc_r, j = 0.0, 0.0, i
        while j >= 0 and acc_h < 8.0 - 1e-9:
            acc_h += hrs[j]
            acc_r += rate[j]
            j -= 1
        if abs(acc_h - 8.0) < 1e-9:
            eq8[i] = acc_r
    g = g.assign(_eq8=eq8, _day=day)
    eq8_daily = g.groupby("_day")["_eq8"].last()

    # --- cumulative trailing-7-day funding (168h) -----------------------
    cum7 = g.set_index("ts")["funding_rate"].rolling("168h").sum()
    cum7_daily = cum7.groupby(g["_day"].values).last()

    # --- consecutive NEGATIVE hours, NO gap tolerance -------------------
    ts = g["ts"].to_numpy()
    neg_h = np.zeros(len(g))
    run = 0.0
    for i in range(len(g)):
        contiguous = True
        if i > 0:
            gap = (ts[i] - ts[i - 1]) / np.timedelta64(1, "h")
            contiguous = abs(gap - hrs[i - 1]) < 1e-6
        if rate[i] < 0 and (i == 0 or contiguous):
            run += hrs[i]
        elif rate[i] < 0:
            run = hrs[i]          # gap broke the run; start fresh
        else:
            run = 0.0
        neg_h[i] = run
    g = g.assign(_negh=neg_h)
    negh_daily = g.groupby("_day")["_negh"].last()
    # first positive day after >=72h negative (F2) needs yesterday's run
    prev_negh = negh_daily.shift(1)

    out = pd.DataFrame({"dm": dm, "eq8": eq8_daily, "cum7": cum7_daily,
                        "negh": negh_daily, "prev_negh": prev_negh})
    out["pctl30"] = out["dm"].rolling(30).rank(pct=True) * 100.0
    m = out["dm"].rolling(30).mean()
    s = out["dm"].rolling(30).std(ddof=0)
    out["z30"] = (out["dm"] - m) / s
    out["mean7"] = out["dm"].rolling(7).mean()
    out.index = pd.to_datetime(out.index)
    return out, excluded


# ======================================================================
# RULES — inherited verbatim
# ======================================================================
def rule_events(f, merged):
    """Boolean daily condition series per rule id. f=funding, merged=price."""
    close = merged["Close"].reindex(f.index)
    high20 = close >= close.rolling(20).max()
    return {
        "F1": f["pctl30"] <= 10,
        "F2": (f["dm"] > 0) & (f["prev_negh"] >= 72),
        "F3": f["eq8"] <= -0.0001,
        "F4": (f["pctl30"] >= 90) & high20,          # SUPPRESSION condition
        "F5": f["cum7"] <= 0,
        "F6": f["z30"] <= -2.0,
        "F7": high20 & (f["mean7"] <= 0),
        "F8": f["negh"] >= 168,
    }


TESTS = [("#220", "F1", "standalone"), ("#221", "F1", "overlay"),
         ("#222", "F2", "standalone"), ("#223", "F2", "overlay"),
         ("#224", "F3", "standalone"), ("#225", "F3", "overlay"),
         ("#226", "F4", "suppress"),
         ("#227", "F5", "standalone"), ("#228", "F5", "overlay"),
         ("#229", "F6", "standalone"), ("#230", "F6", "overlay"),
         ("#231", "F7", "standalone"), ("#232", "F7", "overlay"),
         ("#233", "F8", "standalone"), ("#234", "F8", "overlay")]


def labels_for(mode, cond, mwin):
    """Painted direction labels for one test on one window."""
    idx = mwin.index
    c = cond.reindex(idx).fillna(False).astype(bool)
    inc = mwin["direction"]
    inc_buy = inc.isin(TIER)
    if mode == "standalone":
        ev = c
        base = pd.Series("BUY", index=idx)
    elif mode == "overlay":
        ev = c & inc_buy
        base = inc.where(inc_buy, "BUY")
    else:                                    # suppress (F4, #226)
        ev = inc_buy & ~c
        base = inc.where(inc_buy, "BUY")
    painted = ev | ev.shift(1, fill_value=False)
    return pd.Series(np.where(painted.values, base.values, "WATCH"), index=idx), int(ev.sum())


# ======================================================================
# SCORING
# ======================================================================
def lookup_for(mwin, bars, label):
    f = mwin[["Open", "High", "Low", "Close", "Volume"]].copy()
    f["direction"] = label
    r = p.backtest_exit_geometry(
        f, bars, atr_source=G["atr_source"], stop_mult=G["stop_mult"],
        target_mult=G["target_mult"], max_hold_days=G["max_hold_days"],
        short_sma_filter=G["short_sma_filter"], confirm_days=G["confirm_days"],
        fee_bps=H.FEE_BPS, slippage_bps=H.SLIPPAGE_BPS)
    return {pd.Timestamp(t["date"]): t for t in r.get("trades", [])}


def confirmed_days(lab):
    return lab.eq(lab.shift(1)) & lab.isin(TIER)


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


def episodes_of(dates):
    if not len(dates):
        return 0
    d = sorted(pd.to_datetime(list(dates)))
    hold = pd.Timedelta(days=G["max_hold_days"])
    return 1 + sum(1 for i in range(1, len(d)) if (d[i] - d[i - 1]) > hold)


def fold_stats(trades, window):
    if not trades:
        return {"n": 0, "episodes": 0, "win_pct": float("nan"),
                "net_all": float("nan"), "ex_best": float("nan"),
                "folds_counted": 0, "folds_pos": 0}
    df = pd.DataFrame(trades)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date")
    edges = pd.date_range(window[0], window[1], periods=FOLDS + 1)
    fi = pd.cut(df["date"], edges, labels=False, include_lowest=True)
    counted = [(len(df[fi == k]), float(df[fi == k]["pnl_r_net"].mean()))
               for k in range(FOLDS) if len(df[fi == k]) >= 10]
    ex = float("nan")
    if len(counted) >= 3:
        tn = sum(n for n, _ in counted)
        tr = sum(n * m for n, m in counted)
        bn, bm = max(counted, key=lambda c: c[0] * c[1])
        rest = tn - bn
        ex = (tr - bn * bm) / rest if rest else float("nan")
    return {"n": len(df), "episodes": episodes_of(df["date"]),
            "win_pct": 100 * float((df["outcome"] == "target").mean()),
            "net_all": float(df["pnl_r_net"].mean()),
            "ex_best": ex, "folds_counted": len(counted),
            "folds_pos": sum(1 for n, m in counted if m > 0)}


# ======================================================================
# PLACEBO — episode-matched, pooled across tickers (registered)
# ======================================================================
def placebo_pooled(per_ticker, seeds=SEEDS):
    """One pooled draw per seed: for every ticker draw runs of the observed
    lengths at random non-overlapping starts, pool the resulting trades, take
    the mean. Matches the observed conviction mix per ticker."""
    nets = []
    for s in range(seeds):
        rng = np.random.default_rng(220000 + s)
        pooled = []
        for t in per_ticker:
            idx, n, rl, p_strong, lk_s, lk_b = (
                t["idx"], t["n"], t["runs"], t["p_strong"], t["lk_s"], t["lk_b"])
            if not rl:
                continue
            taken = np.zeros(n, dtype=bool)
            for L in rl:
                for _ in range(12):
                    st = int(rng.integers(0, max(1, n - L)))
                    if not taken[st:st + L].any():
                        taken[st:st + L] = True
                        strong = rng.random() < p_strong
                        src = lk_s if strong else lk_b
                        for j in range(st + 1, st + L):
                            tr = src.get(idx[j])
                            if tr is not None:
                                pooled.append(tr["pnl_r_net"])
                        break
        if pooled:
            nets.append(float(np.mean(pooled)))
    a = np.array(nets)
    return a


# ======================================================================
# FIDELITY AXES — measured before any test is scored
# ======================================================================
def fidelity(per_ticker, observed_pooled, seeds=200):
    """Four axes, mapped to a single-ticker event series (registered §3)."""
    # axis 1: turnover -- event/trade count and mean cost_r, real vs null
    real_costs, real_n = [], 0
    for t in per_ticker:
        real_costs += [x["cost_r"] for x in t["obs"]]
        real_n += len(t["obs"])
    null_n, null_costs, off_eligible = [], [], []
    for s in range(seeds):
        rng = np.random.default_rng(999000 + s)
        cnt, costs, bad = 0, [], 0
        for t in per_ticker:
            idx, n, rl, p_strong = t["idx"], t["n"], t["runs"], t["p_strong"]
            elig = t["eligible"]
            taken = np.zeros(n, dtype=bool)
            for L in rl:
                for _ in range(12):
                    st = int(rng.integers(0, max(1, n - L)))
                    if not taken[st:st + L].any():
                        taken[st:st + L] = True
                        strong = rng.random() < p_strong
                        src = t["lk_s"] if strong else t["lk_b"]
                        for j in range(st + 1, st + L):
                            if not elig[j]:
                                bad += 1
                            tr = src.get(idx[j])
                            if tr is not None:
                                cnt += 1
                                costs.append(tr["cost_r"])
                        break
        null_n.append(cnt)
        null_costs += costs
        off_eligible.append(bad)
    # axis 4: inheritance -- episode-matched centre vs independent-day draw
    ind = []
    for s in range(400):
        rng = np.random.default_rng(555000 + s)
        pooled = []
        for t in per_ticker:
            idx, n = t["idx"], t["n"]
            k = sum(t["runs"]) - len(t["runs"])       # confirmed-day count
            if k <= 0:
                continue
            pick = rng.choice(n, size=min(k, n), replace=False)
            for j in pick:
                strong = rng.random() < t["p_strong"]
                tr = (t["lk_s"] if strong else t["lk_b"]).get(idx[j])
                if tr is not None:
                    pooled.append(tr["pnl_r_net"])
        if pooled:
            ind.append(float(np.mean(pooled)))
    return {
        "axis1_real_trades": real_n,
        "axis1_null_trades_mean": float(np.mean(null_n)) if null_n else 0.0,
        "axis1_trade_ratio": (float(np.mean(null_n)) / real_n) if real_n else float("nan"),
        "axis1_real_cost_r": float(np.mean(real_costs)) if real_costs else float("nan"),
        "axis1_null_cost_r": float(np.mean(null_costs)) if null_costs else float("nan"),
        "axis2_off_eligible_events": int(np.sum(off_eligible)),
        "axis2_null_events_total": int(np.sum(null_n)),
        "axis3": "N/A - event series has no exposure budget",
        "axis4_episode_centre": float(np.median(observed_pooled)) if len(observed_pooled) else float("nan"),
        "axis4_independent_centre": float(np.median(ind)) if ind else float("nan"),
        "axis4_inheritance": (float(np.median(observed_pooled)) - float(np.median(ind)))
        if len(observed_pooled) and ind else float("nan"),
    }


# ======================================================================
# MAIN — one batch, everything written before anything is read
# ======================================================================
def main():
    fund = load_funding()
    feats, excluded = {}, {}
    for label, sym in TICKERS:
        f, ex = daily_features(fund[fund.symbol == sym])
        feats[label] = f
        excluded[label] = ex

    freeze = fund["ts"].max()
    lock = freeze - pd.DateOffset(months=LOCKBOX_MONTHS)
    starts = {}
    for label, sym in TICKERS:
        starts[label] = (fund[fund.symbol == sym]["ts"].min()
                         + pd.DateOffset(months=BURN_IN_MONTHS))
    common = max(starts.values()).tz_localize(None).normalize()
    lock_n = lock.tz_localize(None).normalize()
    cut = common + (lock_n - common) * DISCOVERY_FRAC
    WINDOWS = [("DISCOVERY", common, cut), ("CONFIRMATION", cut, lock_n)]

    # cross-venue flag (inherited): Pearson on daily means vs Kraken
    kr = pd.read_csv(os.path.join(ROOT, "data", "derivatives", "kraken_funding.csv"))
    kr["ts"] = pd.to_datetime(kr["timestamp"], utc=True, format="mixed")
    kmap = {"BTC": "PF_XBTUSD", "ETH": "PF_ETHUSD", "SOL": "PF_SOLUSD"}
    xvenue = {}
    for label, sym in TICKERS:
        kk = kr[kr.symbol == kmap[label]].set_index("ts")["relative_funding_rate"]
        kd = kk.resample("1D").mean()
        kd.index = kd.index.tz_localize(None)
        bd = feats[label]["dm"]
        j = pd.concat([bd.rename("b"), kd.rename("k")], axis=1).dropna()
        j = j[j.index < lock_n]                      # pre-lockbox values only
        r = float(j["b"].corr(j["k"])) if len(j) > 2 else float("nan")
        xvenue[label] = {"pearson": r, "n_days": int(len(j)),
                         "flag": bool(not (r == r) or r < XVENUE_BAR)}

    # ---- per ticker per window scaffolding -----------------------------
    scaffold = {}
    for wname, lo, hi in WINDOWS:
        scaffold[wname] = {}
        for label, sym in TICKERS:
            bars, merged, daily = H.load_ticker(label)
            w = H.make_windows(daily)
            bars_sealed = H.seal_bars(bars, w, "discovery")
            mwin = merged[(merged.index >= lo) & (merged.index < hi)]
            scaffold[wname][label] = {
                "mwin": mwin, "bars": bars_sealed,
                "lk_s": lookup_for(mwin, bars_sealed, "STRONG_BUY"),
                "lk_b": lookup_for(mwin, bars_sealed, "BUY"),
                "cond": rule_events(feats[label], mwin),
                "elig": feats[label]["dm"].reindex(mwin.index).notna().to_numpy(),
            }

    # ---- SCORE ALL FIFTEEN, ONE BATCH ----------------------------------
    out = {"_windows": {"freeze": str(freeze), "lockbox": str(lock_n.date()),
                        "discovery": [str(common.date()), str(cut.date())],
                        "confirmation": [str(cut.date()), str(lock_n.date())]},
           "_excluded_days": excluded, "_xvenue": xvenue, "_tests": {}}
    fid_done = {}

    for tid, rule, mode in TESTS:
        out["_tests"][tid] = {"rule": rule, "mode": mode}
        for wname, lo, hi in WINDOWS:
            per_ticker, per_stats = [], {}
            for label, sym in TICKERS:
                sc = scaffold[wname][label]
                lab, n_ev = labels_for(mode, sc["cond"][rule], sc["mwin"])
                conf = confirmed_days(lab)
                obs = []
                for d in lab.index[conf.values]:
                    src = sc["lk_s"] if lab.get(d) == "STRONG_BUY" else sc["lk_b"]
                    t = src.get(d)
                    if t is not None:
                        obs.append(t)
                per_stats[label] = fold_stats(obs, (lo, hi))
                per_stats[label]["events"] = n_ev
                mask = lab.isin(TIER).to_numpy()
                n_all = int(mask.sum())
                per_ticker.append({
                    "idx": list(lab.index), "n": len(lab),
                    "runs": runs_of(mask),
                    "p_strong": (float((lab == "STRONG_BUY").sum()) / n_all)
                    if n_all else 0.0,
                    "lk_s": sc["lk_s"], "lk_b": sc["lk_b"],
                    "obs": obs, "eligible": sc["elig"]})
            pooled_trades = [t for x in per_ticker for t in x["obs"]]
            pooled_net = (float(np.mean([t["pnl_r_net"] for t in pooled_trades]))
                          if pooled_trades else float("nan"))
            dist = placebo_pooled(per_ticker)
            row = {"per_ticker": per_stats,
                   "pooled_n": len(pooled_trades),
                   "pooled_episodes": sum(v["episodes"] for v in per_stats.values()),
                   "pooled_net": pooled_net,
                   "placebo_p95": float(np.percentile(dist, 95)) if len(dist) else float("nan"),
                   "placebo_adj": float(np.percentile(dist, ADJ_PCTILE)) if len(dist) else float("nan"),
                   "placebo_valid": int(len(dist)),
                   "observed_pctile": (float(100.0 * (dist < pooled_net).mean())
                                       if len(dist) and pooled_net == pooled_net else float("nan"))}
            out["_tests"][tid][wname] = row
            if tid == "#220" and wname not in fid_done:
                fid_done[wname] = fidelity(per_ticker, dist)

    out["_fidelity"] = fid_done

    # EVERYTHING WRITTEN BEFORE ANYTHING IS READ (registered §7)
    with open(RESULTS, "w") as fh:
        json.dump(out, fh, indent=2, default=str)
    print("BATCH COMPLETE — 15 tests x 2 windows written to %s" % RESULTS)
    print("Nothing above was read during scoring.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
