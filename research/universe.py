"""
research/universe.py
====================
Enumerate a GRAMMAR of entry rules and score every one of them. There is
no curation step: the grid is defined by the grammar, registered in
docs/cleanroom.md in full, and then scored in full. Rules are not dropped
for looking silly, and parameters are the conventional textbook values —
nothing here is tuned.

    base setups (30)  x  context filters (4)  =  120 rules,  #42 .. #161

Two of the 120 are logically identical to their own base rule (the
"close > SMA200" trend-pullback bases crossed with the "close > SMA200"
context). They are kept, not pruned — dropping them would be curation,
and their duplicate numbers are a free internal consistency check.

All scoring goes through research/harness.py, which goes through
pipeline.py. No trade logic lives here; this file only produces boolean
event series.

LOOKAHEAD DISCIPLINE
--------------------
Every feature is backward-looking, and a rule firing on day t is decided
from data through day t's close. The harness enters at the close of t+1.
Features are computed on the frame TRUNCATED AT THE LOCKBOX BOUNDARY, so
no rolling window ever touches a sealed row.

Usage:
    python research/universe.py --register        # write the grid to cleanroom
    python research/universe.py --score-discovery # score all 120 x 3 tickers
"""

import os
import sys
import argparse

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import signal_engines as cf          # noqa: E402  (_rsi, _obv, compute_atr)
import harness as H                  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESEARCH = os.path.join(ROOT, "research")
DOCS = os.path.join(ROOT, "docs")
FIRST_ID = 42
TICKERS = ["BTC", "ETH", "SOL"]


# ======================================================================
# FEATURES
# ======================================================================

def build_features(daily: pd.DataFrame, btc_daily: pd.DataFrame) -> pd.DataFrame:
    """Every column any rule needs. All rolling, all backward-looking."""
    f = daily.copy()
    c, h, l, v = f["Close"], f["High"], f["Low"], f["Volume"]

    for n in (10, 20, 50, 100, 200):
        f[f"SMA{n}"] = c.rolling(n).mean()
    for n in (9, 10, 20, 21, 50, 200):
        f[f"EMA{n}"] = c.ewm(span=n, adjust=False).mean()
    for n in (10, 20, 55):
        f[f"DON{n}"] = h.rolling(n).max().shift(1)
    for n in (7, 14):
        f[f"RSI{n}"] = cf._rsi(c, n)
    for n in (10, 20, 60):
        f[f"ROC{n}"] = c.pct_change(n) * 100

    f["ATR14"] = cf.compute_atr(f, period=14)
    f["ATR20"] = cf.compute_atr(f, period=20)

    # Bollinger 20/2 and Keltner 20/1.5ATR -> TTM squeeze
    sd = c.rolling(20).std(ddof=0)
    f["BB_UP"], f["BB_LO"] = f["SMA20"] + 2 * sd, f["SMA20"] - 2 * sd
    f["KC_UP"] = f["EMA20"] + 1.5 * f["ATR20"]
    f["KC_LO"] = f["EMA20"] - 1.5 * f["ATR20"]
    f["SQUEEZE_ON"] = (f["BB_UP"] < f["KC_UP"]) & (f["BB_LO"] > f["KC_LO"])
    f["BBW"] = (f["BB_UP"] - f["BB_LO"]) / f["SMA20"]
    f["BBW_PCTL"] = f["BBW"].rolling(100).rank(pct=True) * 100

    f["RANGE"] = h - l
    f["NR7"] = f["RANGE"] == f["RANGE"].rolling(7).min()
    f["NR4"] = f["RANGE"] == f["RANGE"].rolling(4).min()
    f["INSIDE"] = (h < h.shift(1)) & (l > l.shift(1))
    f["CLOSE_POS"] = np.where(f["RANGE"] > 0, (c - l) / f["RANGE"].replace(0, np.nan), np.nan)

    f["VOL_SMA20"] = v.rolling(20).mean()
    f["OBV"] = cf._obv(c, v)
    f["OBV_MAX20"] = f["OBV"].rolling(20).max().shift(1)

    # Weekly close vs its 10-week SMA, stamped on the week's last day
    wk = c.resample("W-SUN").last().dropna()
    wk_sma = wk.rolling(10).mean()
    wk_cross = (wk > wk_sma) & (wk.shift(1) <= wk_sma.shift(1))
    last_day = c.resample("W-SUN").apply(lambda s: s.index.max() if len(s) else pd.NaT).dropna()
    stamp = pd.Series(False, index=f.index)
    for wk_end, fired in wk_cross.items():
        if fired and wk_end in last_day.index:
            d = last_day.loc[wk_end]
            if d in stamp.index:
                stamp.loc[d] = True
    f["WK_CROSS_10W"] = stamp

    # Realized vol: 30d stdev of daily log returns, vs its own 100d median
    lr = np.log(c / c.shift(1))
    f["RV30"] = lr.rolling(30).std(ddof=0)
    f["RV30_MED100"] = f["RV30"].rolling(100).median()

    # BTC market regime, aligned onto this ticker's index
    btc_c = btc_daily["Close"]
    btc_ok = (btc_c > btc_c.rolling(200).mean())
    f["BTC_ABOVE_SMA200"] = btc_ok.reindex(f.index).ffill().fillna(False)
    return f


def _cross_above(a: pd.Series, b) -> pd.Series:
    """a crosses strictly above b on this bar."""
    b = b if isinstance(b, pd.Series) else pd.Series(b, index=a.index)
    return (a > b) & (a.shift(1) <= b.shift(1))


# ======================================================================
# BASE SETUPS — 30
# ======================================================================

def base_rules() -> list:
    """(key, description, fn(features) -> boolean Series)."""
    R = []

    for n in (10, 20, 55):
        R.append((f"donchian{n}", f"Donchian breakout: close > prior {n}-day high",
                  lambda f, n=n: f["Close"] > f[f"DON{n}"]))

    for fa, sl in ((9, 21), (20, 50), (50, 200)):
        R.append((f"emacross{fa}_{sl}", f"EMA{fa} crosses above EMA{sl}",
                  lambda f, fa=fa, sl=sl: _cross_above(f[f"EMA{fa}"], f[f"EMA{sl}"])))

    for s in (100, 200):
        for e in (10, 20):
            R.append((f"pullback_sma{s}_ema{e}",
                      f"Trend pullback: close > SMA{s} and close crosses above EMA{e}",
                      lambda f, s=s, e=e: (f["Close"] > f[f"SMA{s}"])
                      & _cross_above(f["Close"], f[f"EMA{e}"])))

    for th in (25, 30, 35):
        R.append((f"rsi14_exit{th}", f"RSI14 crosses back above {th} (exit from oversold)",
                  lambda f, th=th: _cross_above(f["RSI14"], th)))

    for n in (7, 14):
        R.append((f"rsi{n}_cross50", f"RSI{n} crosses above 50",
                  lambda f, n=n: _cross_above(f[f"RSI{n}"], 50)))

    for n in (10, 20, 60):
        R.append((f"roc{n}_zero", f"ROC{n} crosses above zero",
                  lambda f, n=n: _cross_above(f[f"ROC{n}"], 0)))

    R.append(("ttm_release", "TTM squeeze release: BB(20,2) exits Keltner(20,1.5ATR)",
              lambda f: f["SQUEEZE_ON"].shift(1).fillna(False) & ~f["SQUEEZE_ON"].fillna(False)))
    R.append(("nr7", "NR7: narrowest range of the last 7 days",
              lambda f: f["NR7"].fillna(False)))
    R.append(("nr4", "NR4: narrowest range of the last 4 days",
              lambda f: f["NR4"].fillna(False)))
    for th in (10, 20):
        R.append((f"bbw_p{th}_expand",
                  f"BB bandwidth below its {th}th 100-day percentile, then expansion on an up day",
                  lambda f, th=th: (f["BBW_PCTL"].shift(1) < th)
                  & (f["BBW"] > f["BBW"].shift(1)) & (f["Close"] > f["Close"].shift(1))))

    for k in (1.0, 1.5):
        R.append((f"volbreak{k:g}", f"Close > prior close + {k:g} x ATR14",
                  lambda f, k=k: f["Close"] > f["Close"].shift(1) + k * f["ATR14"].shift(1)))

    R.append(("wide_range_up", "Wide-range up day: close in top 10% of range, range > 1.5 x ATR14",
              lambda f: (f["CLOSE_POS"] >= 0.9) & (f["RANGE"] > 1.5 * f["ATR14"])))
    R.append(("three_inside_up", "Three inside days then an up close",
              lambda f: f["INSIDE"].shift(3).fillna(False) & f["INSIDE"].shift(2).fillna(False)
              & f["INSIDE"].shift(1).fillna(False) & (f["Close"] > f["Close"].shift(1))))
    R.append(("vol_thrust", "Up close with volume > 2x its 20-day average",
              lambda f: (f["Close"] > f["Close"].shift(1))
              & (f["Volume"] > 2 * f["VOL_SMA20"].shift(1))))
    R.append(("obv_break20", "OBV breaks its own 20-day high",
              lambda f: f["OBV"] > f["OBV_MAX20"]))
    R.append(("weekly_cross10w", "Weekly close crosses above its 10-week SMA",
              lambda f: f["WK_CROSS_10W"].fillna(False)))
    return R


# ======================================================================
# CONTEXT FILTERS — 4
# ======================================================================

def context_filters() -> list:
    return [
        ("none", "no context filter", lambda f: pd.Series(True, index=f.index)),
        ("above_sma200", "close > SMA200 (own trend)",
         lambda f: (f["Close"] > f["SMA200"]).fillna(False)),
        ("btc_above_sma200", "BTC close > BTC SMA200 (market regime)",
         lambda f: f["BTC_ABOVE_SMA200"].astype(bool)),
        ("lowvol", "30-day realized vol below its 100-day median",
         lambda f: (f["RV30"] < f["RV30_MED100"]).fillna(False)),
    ]


def enumerate_rules() -> list:
    """The full grid, numbered from FIRST_ID. No filtering, ever."""
    out, hid = [], FIRST_ID
    for bkey, bdesc, bfn in base_rules():
        for ckey, cdesc, cfn in context_filters():
            out.append({"id": hid,
                        "name": f"{bkey}+{ckey}",
                        "base": bkey, "base_desc": bdesc,
                        "context": ckey, "context_desc": cdesc,
                        "fn": (lambda f, bfn=bfn, cfn=cfn: bfn(f).fillna(False) & cfn(f))})
            hid += 1
    return out


# ======================================================================
# REGISTRATION — must run BEFORE any scoring
# ======================================================================

def register(windows_note: str) -> str:
    rules = enumerate_rules()
    lines = []
    lines.append("### Hypotheses #%d-#%d — the enumerated rule grid\n" % (
        rules[0]["id"], rules[-1]["id"]))
    lines.append("Registered BEFORE any rule was scored. The grid is a grammar, "
                 "not a shortlist: %d base setups x %d context filters = %d rules, "
                 "every one of which gets scored and reported whatever it does.\n"
                 % (len(base_rules()), len(context_filters()), len(rules)))
    lines.append("**Parameters are conventional and fixed.** Nothing below was "
                 "chosen by looking at a result, and nothing may be changed after "
                 "one is seen (rule 4 of the Research rules).\n")
    lines.append(windows_note + "\n")
    lines.append("**Protocol.** Each rule produces a daily boolean event series. "
                 "An event on day E labels day E and day E+1 as BUY; the "
                 "incumbent's 2-day confirm therefore enters at the close of E+1. "
                 "Scoring runs through `research/harness.py` into "
                 "`pipeline.evaluate_geometry_folds` with `LIVE_GEOMETRY`, 4 folds, "
                 "and walkforward's 2bps fee + 2bps slippage per side. `ex_best` is "
                 "`pipeline.concentration_report`'s excluding-best-fold expectancy "
                 "(folds count at >=10 trades; needs >=3 counted folds).\n")
    lines.append("**Discovery selection rule, fixed in advance:** rank by the "
                 "MINIMUM `ex_best` across the three tickers, with a rarity guard "
                 "of n >= 20 trades per ticker. The top 5 are then frozen and go to "
                 "CONFIRMATION unchanged.\n")
    lines.append("| # | rule | base setup | context |")
    lines.append("|---|------|-----------|---------|")
    for r in rules:
        lines.append(f"| {r['id']} | `{r['name']}` | {r['base_desc']} | {r['context_desc']} |")
    lines.append("")
    return "\n".join(lines)


# ======================================================================
# SCORING
# ======================================================================

def features_for(ticker: str, btc_daily_cut: pd.DataFrame):
    """Features built on data STRICTLY BEFORE the lockbox boundary."""
    bars_4h, merged, daily = H.load_ticker(ticker)
    w = H.make_windows(daily)
    cut = daily[daily.index < w.lockbox[0]]          # sealed rows never read
    feats = build_features(cut, btc_daily_cut)
    # The 4h feed is sealed too: exit resolution runs on it, and a trade
    # near a window's end keeps resolving afterwards, so an unsealed feed
    # would let a boundary trade resolve on lockbox bars. Proven a no-op on
    # DISCOVERY (harness --unsealed diff); it binds on CONFIRMATION.
    bars_4h = H.seal_bars(bars_4h, w, "discovery")
    return bars_4h, merged, daily, feats, w


def btc_reference_daily():
    _, _, btc_daily = H.load_ticker("BTC")
    w = H.make_windows(btc_daily)
    return btc_daily[btc_daily.index < w.lockbox[0]]


def score_window(window_name: str, out_csv: str, folds: int = 4,
                 rules: list = None, tickers: list = None) -> pd.DataFrame:
    rules = rules if rules is not None else enumerate_rules()
    tickers = tickers or TICKERS
    btc_cut = btc_reference_daily()
    rows = []
    for t in tickers:
        bars_4h, merged, daily, feats, w = features_for(t, btc_cut)
        win = getattr(w, window_name)
        fwin = H.slice_window(feats, win)
        print(f"\n=== {t} — {window_name.upper()} "
              f"{win[0].date()} -> {win[1].date()} ({len(fwin)} days) ===")
        for i, r in enumerate(rules, 1):
            ev = r["fn"](feats).reindex(fwin.index).fillna(False)
            res = H.score_events(fwin, bars_4h, ev, folds=folds, name=r["name"])
            rows.append({"id": r["id"], "rule": r["name"], "base": r["base"],
                         "context": r["context"], "ticker": t,
                         "n_events": res["n_events"], "n": res["n"],
                         "win_pct": res["win_pct"], "stop_pct": res["stop_pct"],
                         "net_all": res["net_all"], "net_counted": res.get("net_counted"),
                         "ex_best": res["ex_best"],
                         "folds_pos": res["folds_pos"],
                         "folds_counted": res["folds_counted"],
                         "total_R": res["total_R"], "maxDD_R": res["maxDD_R"],
                         "worst_streak": res["worst_streak"]})
            if i % 20 == 0:
                print(f"  {i}/{len(rules)} rules scored")
    df = pd.DataFrame(rows)
    df.to_csv(out_csv, index=False)
    print(f"\nwrote {out_csv}  ({len(df)} rows, {df['rule'].nunique()} rules "
          f"x {df['ticker'].nunique()} tickers)")
    return df


# ======================================================================
# CLI
# ======================================================================

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--register", action="store_true")
    ap.add_argument("--score-discovery", action="store_true")
    ap.add_argument("--folds", type=int, default=4)
    a = ap.parse_args()

    if a.register:
        _, _, daily = H.load_ticker("BTC")
        w = H.make_windows(daily)
        note = ("**Windows** (anchored on the dataset's last date, "
                f"{w.last_date.date()}, never the wall clock): "
                f"DISCOVERY {w.discovery[0].date()} -> {w.discovery[1].date()}; "
                f"CONFIRMATION {w.confirmation[0].date()} -> {w.confirmation[1].date()}; "
                f"LOCKBOX {w.lockbox[0].date()} -> {w.lockbox[1].date()} (SEALED). "
                "Features are computed on data strictly before the lockbox "
                "boundary, so no rolling window touches a sealed row.")
        print(register(note))

    if a.score_discovery:
        score_window("discovery", os.path.join(RESEARCH, "discovery_results.csv"),
                     folds=a.folds)


if __name__ == "__main__":
    main()
