"""
research/attribution.py
=======================
"Where does the expectancy come from?" for INC_STRONG_BUY and the top 3
DISCOVERY rules (nothing survived CONFIRMATION, so the spec's fallback
applies).

This module DECIDES NO TRADES. Every trade it dissects was produced by
pipeline.evaluate_geometry_folds via research/harness.py. It only measures
properties of those trades.

WINDOW. The full non-lockbox span (DISCOVERY + CONFIRMATION). Attribution
is descriptive, not a hypothesis test, and INC_STRONG_BUY is so rare
(8/3/1 on DISCOVERY, 10/5/0 on CONFIRMATION) that splitting it further
would leave nothing to attribute. The lockbox stays sealed, both in the
daily frames and in the 4h feed.

MFE / MAE. pipeline stores `mfe_pct_of_target` (favourable excursion as a
fraction of TARGET distance) and no MAE at all. Converting to R:
    MFE_R = (mfe_pct_of_target / 100) * (target_dist / stop_dist)
where target_dist/stop_dist is 2.0 for BUY and 2.667 for STRONG_BUY (the
1.333x conviction scale). MAE has to be measured from the 4h bars between
entry and exit, using pipeline's OWN entry timestamp, entry price and stop
distance, so it describes the same trade pipeline resolved.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import harness as H
import universe as U

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

TICKERS = ["BTC", "ETH", "SOL"]
TOP3 = ["donchian10+none", "obv_break20+none", "roc10_zero+none"]
RR = {"BUY": 2.0, "STRONG_BUY": 3.0 * 1.333 / 1.5}
OHLCV = ["Open", "High", "Low", "Close", "Volume"]


def regime_frame(frame):
    """SMA200 position and 30d realized vol, on the SAME frame the trades
    came from, so a trade's date always joins."""
    c = frame["Close"]
    out = pd.DataFrame(index=frame.index)
    out["sma200"] = c.rolling(200).mean()
    out["above200"] = c > out["sma200"]
    lr = np.log(c / c.shift(1))
    out["rv30"] = lr.rolling(30).std(ddof=0)
    return out


def mae_r(bars_4h, trade, entry_px):
    """Max adverse excursion in R, walked over the trade's own 4h bars.
    Long-only: every row here is a BUY or STRONG_BUY."""
    stop_dist = entry_px * (trade["stop_pct"] / 100.0)
    if not stop_dist or stop_dist != stop_dist:
        return float("nan")
    e = pd.Timestamp(trade["date"]).normalize() + pd.Timedelta(hours=24)
    fwd = bars_4h[bars_4h.index > e].iloc[:int(trade["bars_held"])]
    if fwd.empty:
        return 0.0
    return float(max(0.0, (entry_px - fwd["Low"].min()) / stop_dist))


def dissect(results, frame, bars_4h, reg):
    """Per-trade table with regime tags, MFE_R and MAE_R, plus fold ids."""
    rows = []
    for k, r in enumerate(results, 1):
        for t in r.get("trades", []):
            d = pd.Timestamp(t["date"])
            entry_px = float(frame["Close"].loc[d]) if d in frame.index else float("nan")
            rr = RR.get(t["direction"], 2.0)
            rows.append({
                "fold": k, "date": d, "direction": t["direction"],
                "outcome": t["outcome"], "pnl_r_net": t["pnl_r_net"],
                "mfe_r": (t["mfe_pct_of_target"] / 100.0) * rr,
                "mae_r": mae_r(bars_4h, t, entry_px),
                "above200": bool(reg["above200"].get(d, False)),
                "rv30": float(reg["rv30"].get(d, float("nan"))),
            })
    return pd.DataFrame(rows)


def summarize(td, always_long_exp, jaccard):
    """The five attribution answers for one (row, ticker)."""
    if td.empty:
        return None
    exp = td.pnl_r_net.mean()
    out = {"n": len(td), "exp_net": exp}

    # 1. regime
    for key, mask in (("above200", td.above200), ("below200", ~td.above200)):
        out["n_" + key] = int(mask.sum())
        out["exp_" + key] = float(td.pnl_r_net[mask].mean()) if mask.any() else float("nan")
    # Vol terciles need enough DISTINCT rv30 values to cut. With 1-2 trades
    # the two edges collapse onto each other; reporting a "tercile split" of
    # a single trade would be noise dressed as structure, so it is n/a.
    q = td.rv30.quantile([1 / 3, 2 / 3]).values
    if len(td) >= 6 and np.isfinite(q).all() and q[0] < q[1]:
        terc = pd.cut(td.rv30, [-np.inf, q[0], q[1], np.inf], labels=["lo", "mid", "hi"])
        for lv in ("lo", "mid", "hi"):
            m = (terc == lv).values
            out["n_vol_" + lv] = int(m.sum())
            out["exp_vol_" + lv] = float(td.pnl_r_net[m].mean()) if m.any() else float("nan")
        out["vol_terciles_ok"] = True
    else:
        for lv in ("lo", "mid", "hi"):
            out["n_vol_" + lv] = 0
            out["exp_vol_" + lv] = float("nan")
        out["vol_terciles_ok"] = False

    # 2. exit mix
    for oc in ("target", "stop", "ambiguous_stop", "timeout"):
        m = td.outcome == oc
        out["share_" + oc] = float(m.mean())
        out["mfe_" + oc] = float(td.mfe_r[m].mean()) if m.any() else float("nan")
        out["mae_" + oc] = float(td.mae_r[m].mean()) if m.any() else float("nan")

    # 3. drift share
    out["always_long_exp"] = always_long_exp
    out["excess_over_drift"] = exp - always_long_exp

    # 4. overlap
    out["jaccard_vs_inc_buy"] = jaccard

    # 5. fold concentration
    fr = td.groupby("fold").pnl_r_net.sum()
    tot = float(fr.sum())
    best = float(fr.max()) if len(fr) else float("nan")
    out["total_R"] = tot
    out["best_fold_R"] = best
    out["best_fold_share"] = (best / tot) if tot > 0 else float("nan")
    out["n_folds_with_trades"] = int(len(fr))
    return out


def run():
    rules = {r["name"]: r for r in U.enumerate_rules()}
    btc = U.btc_reference_daily()
    recs, per_trade = [], {}
    for t in TICKERS:
        bars, merged, daily, feats, w = U.features_for(t, btc)   # bars sealed
        full = (w.discovery[0], w.lockbox[0])                    # DISCOVERY+CONFIRMATION
        fwin = H.slice_window(feats, full)
        mwin = H.slice_window(merged, full)

        inc_buy = set(mwin.index[mwin["direction"].isin(["BUY", "STRONG_BUY"])])
        common = set(fwin.index) & set(mwin.index)

        # drift baselines, one per frame, SAME window
        al_rule = H.always_long(fwin, bars, folds=4)
        al_inc = H.always_long(mwin[OHLCV], bars, folds=4)

        reg_r, reg_i = regime_frame(fwin), regime_frame(mwin)

        for name in TOP3:
            r = rules[name]
            ev = r["fn"](feats).reindex(fwin.index).fillna(False)
            res = H.score_events(fwin, bars, ev, folds=4, name=name)
            A = set(fwin.index[ev.values]) & common
            B = inc_buy & common
            jac = len(A & B) / len(A | B) if (A | B) else float("nan")
            td = dissect(res["_results"], fwin, bars, reg_r)
            s = summarize(td, al_rule["net_all"], jac)
            if s:
                s.update({"row": name, "ticker": t})
                recs.append(s)
            per_trade[(name, t)] = td

        inc = H.incumbent_rows(mwin, bars, folds=4)[0]            # INC_STRONG_BUY
        sb = set(mwin.index[mwin["direction"] == "STRONG_BUY"])
        jac = len(sb & inc_buy) / len(sb | inc_buy) if (sb | inc_buy) else float("nan")
        td = dissect(inc["_results"], mwin, bars, reg_i)
        s = summarize(td, al_inc["net_all"], jac)
        if s:
            s.update({"row": "INC_STRONG_BUY", "ticker": t})
            recs.append(s)
        per_trade[("INC_STRONG_BUY", t)] = td
        print("  %s done  (window %s -> %s)" % (t, full[0].date(), full[1].date()))

    df = pd.DataFrame(recs)
    df.to_csv(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "attribution.csv"), index=False)
    return df, per_trade


def report(df):
    for row in ["INC_STRONG_BUY"] + TOP3:
        s = df[df.row == row]
        if s.empty:
            continue
        print("\n" + "=" * 100)
        print(row)
        print("=" * 100)
        for _, r in s.iterrows():
            print("  %s: n=%d exp=%+.3fR  ALWAYS_LONG=%+.3fR  excess=%+.3fR"
                  % (r.ticker, r.n, r.exp_net, r.always_long_exp, r.excess_over_drift))
            print("     regime : above200 n=%d exp=%+.3f | below200 n=%d exp=%+.3f"
                  % (r.n_above200, r.exp_above200, r.n_below200, r.exp_below200))
            print("     vol    : lo n=%d %+.3f | mid n=%d %+.3f | hi n=%d %+.3f"
                  % (r.n_vol_lo, r.exp_vol_lo, r.n_vol_mid, r.exp_vol_mid,
                     r.n_vol_hi, r.exp_vol_hi))
            print("     exits  : tgt %.0f%% (MFE %.2fR/MAE %.2fR) | stop %.0f%% "
                  "(MFE %.2fR/MAE %.2fR) | ambig %.0f%% | timeout %.0f%% "
                  "(MFE %.2fR/MAE %.2fR)"
                  % (100 * r.share_target, r.mfe_target, r.mae_target,
                     100 * r.share_stop, r.mfe_stop, r.mae_stop,
                     100 * r.share_ambiguous_stop,
                     100 * r.share_timeout, r.mfe_timeout, r.mae_timeout))
            print("     overlap: Jaccard vs incumbent BUY days = %.3f" % r.jaccard_vs_inc_buy)
            bs = ("n/a (total R <= 0)" if r.best_fold_share != r.best_fold_share
                  else "%.0f%%" % (100 * r.best_fold_share))
            print("     folds  : total %+.1fR, best fold %+.1fR, share %s"
                  % (r.total_R, r.best_fold_R, bs))


if __name__ == "__main__":
    d, _ = run()
    report(d)
