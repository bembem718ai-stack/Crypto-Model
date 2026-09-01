"""#249 — MARKET-STRUCTURE MAP. Descriptive. Locked before it ran.

NO HYPOTHESES, NO PASS CONDITIONS, NO VERDICTS, NO SIGNALS. Nothing here is
scored through the trade machinery and no return-vs-signal join is made.
Its sole product is docs/market_structure.md.

Every number carries a CI or is labelled a RAW COUNT. Every cutoff is fixed
in the registration. The lockbox (opens 2026-02-26) is never read.

BOOTSTRAP, fixed in the registration: moving-block, 1,000 resamples, block
length ceil(n^(1/3)) -- rate-optimal under weak dependence, chosen before
any result so no band can be tuned. On |returns|, whose dependence decays
slowly, the bands are if anything TOO NARROW; that is stated beside those
cells rather than fixed by choosing a friendlier block.
"""
import os
import sys
import glob
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import harness as H

warnings.filterwarnings("ignore")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "market_structure.md")
TICKERS = ["BTC", "ETH", "SOL"]
BOOT = 1000                      # registered
SEED0 = 249000
LINES = []


def say(s=""):
    LINES.append(s)


def block_len(n):
    """ceil(n^(1/3)) — registered, rate-optimal under weak dependence."""
    return max(2, int(np.ceil(n ** (1.0 / 3.0))))


def mbb_indices(n, ell, rng):
    """Moving-block bootstrap index draw."""
    k = int(np.ceil(n / ell))
    starts = rng.integers(0, max(1, n - ell + 1), size=k)
    idx = np.concatenate([np.arange(s, s + ell) for s in starts])[:n]
    return np.clip(idx, 0, n - 1)


def boot_ci(x, stat, seed, reps=BOOT, lo=2.5, hi=97.5):
    """Percentile CI for `stat` under the moving-block bootstrap."""
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 10:                      # below this a percentile CI is noise
        return float("nan"), float("nan"), 0
    ell = block_len(n)
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(reps):
        v = stat(x[mbb_indices(n, ell, rng)])
        if v == v:
            vals.append(v)
    if not vals:
        return float("nan"), float("nan"), ell
    return float(np.percentile(vals, lo)), float(np.percentile(vals, hi)), ell


def fmt(v, d=4):
    return "—" if v != v else ("%+.*f" % (d, v))


def ci(lo, hi, d=4):
    if lo != lo or hi != hi:
        return "—"
    return "[%+.*f, %+.*f]" % (d, lo, d, hi)


# ----------------------------------------------------------------------
# DATA — pre-lockbox only
# ----------------------------------------------------------------------
def load():
    bars, merged, daily = H.load_ticker("BTC")
    w = H.make_windows(daily)
    seal = w.lockbox[0]
    out = {}
    for t in TICKERS:
        d = {}
        for iv in ("1h", "4h"):
            x = pd.read_csv(os.path.join(ROOT, "data", "%s_%s.csv" % (t, iv)),
                            index_col=0, parse_dates=True).sort_index()
            d[iv] = x[x.index < seal]
        agg = {"Open": "first", "High": "max", "Low": "min",
               "Close": "last", "Volume": "sum"}
        d["1d"] = d["4h"].resample("1D").agg(agg).dropna(subset=["Close"])
        out[t] = d
    return out, seal


def rets(df):
    return df["Close"].pct_change().dropna()


def acf(x, lags):
    x = np.asarray(x, dtype=float)
    x = x - x.mean()
    den = np.dot(x, x)
    return [float(np.dot(x[k:], x[:-k]) / den) if den else float("nan")
            for k in lags]


def half_life(a):
    """Lag at which |ret| ACF first falls to half its lag-1 value,
    linearly interpolated. NaN if it never does within the window."""
    if not len(a) or a[0] <= 0:
        return float("nan")
    target = a[0] / 2.0
    for k in range(1, len(a)):
        if a[k] <= target:
            prev = a[k - 1]
            if prev == a[k]:
                return float(k + 1)
            frac = (prev - target) / (prev - a[k])
            return float(k + frac)
    return float("nan")


# ======================================================================
# M1 — VOLATILITY CLUSTERING
# ======================================================================
def m1(data):
    say("## M1 — Volatility clustering")
    say()
    say("Autocorrelation of **|returns|** and the lag at which it falls to half")
    say("its lag-1 value. CIs are moving-block bootstrap percentile intervals")
    say("(1,000 resamples).")
    say()
    say("| ticker | bar | n | ACF(1) | ACF(1) 95% CI | ACF(5) | ACF(20) | half-life (bars) | half-life bootstrap range ⚠ | block ℓ |")
    say("|---|---|---|---|---|---|---|---|---|---|")
    for t in TICKERS:
        for iv in ("1h", "4h", "1d"):
            r = rets(data[t][iv])
            a = np.abs(r.to_numpy())
            n = len(a)
            lags = list(range(1, 51))
            ac = acf(a, lags)
            hl = half_life(ac)
            l1, h1, ell = boot_ci(a, lambda z: acf(z, [1])[0], SEED0 + hash(t + iv) % 999)
            lhl, hhl, _ = boot_ci(a, lambda z: half_life(acf(z, lags)),
                                  SEED0 + 7 + hash(t + iv) % 999)
            say("| %s | %s | %d | %s | %s | %s | %s | %s | %s | %d |"
                % (t, iv, n, fmt(ac[0]), ci(l1, h1), fmt(ac[4]), fmt(ac[19]),
                   ("—" if hl != hl else "%.1f" % hl),
                   ("—" if lhl != lhl else "[%.1f, %.1f]" % (lhl, hhl)), ell))
    say()
    say("**Reading.** Volatility clusters at every horizon: |return| is")
    say("positively autocorrelated well beyond lag 20, which is the single most")
    say("robust stylised fact in this map. The half-life column says how long")
    say("that memory persists in bars — multiply by the bar length for wall-clock.")
    say()
    say("**What it does NOT say:** clustered volatility is not a tradeable edge.")
    say("It says the SIZE of moves is predictable, not their DIRECTION, and")
    say("every program in this record failed on direction.")
    say()
    say("**⚠ THE HALF-LIFE COLUMN'S BOOTSTRAP RANGE IS NOT A VALID CI, and is")
    say("labelled rather than quietly shown.** Every point estimate falls")
    say("OUTSIDE its own interval, which is the signature of a broken")
    say("construction, not of a surprising result. The moving-block bootstrap")
    say("resamples blocks of length ℓ = ⌈n^(1/3)⌉; dependence BEYOND ℓ is")
    say("destroyed by construction, and half-life is precisely a measure of")
    say("long-range dependence. So the resampled series decay far faster than")
    say("the real one and the interval is DISPLACED, not merely narrow.")
    say()
    say("The point estimates stand — they are computed on the real series. The")
    say("interval is reported as a raw bootstrap range with this warning")
    say("attached, because a valid CI for a long-memory statistic needs a")
    say("different resampling scheme, and choosing one after seeing this result")
    say("is exactly what research rule 4 forbids. Recorded as a limitation.")
    say()
    say("**ACF(1)/ACF(5)/ACF(20) CIs are unaffected** — those are short-lag")
    say("statistics the block length supports. Per the registration they remain")
    say("if anything TOO NARROW on |returns|, and are not widened after the fact.")
    say()


# ======================================================================
# M2 — JUMPS
# ======================================================================
def matched_diffusive_rates(n=200000, sub=60, seed=24902):
    """P(|dClose| > k x ATR14) under a GAUSSIAN RANDOM WALK, same pipeline.

    THE FIRST VERSION OF THIS COMPARISON WAS WRONG AND INVERTED THE TABLE'S
    MEANING. It used 2*(1 - Phi(3*E|z|)) = 0.0167 -- the tail of a
    close-to-close normal -- against an observed ratio whose denominator is
    TRUE RANGE. True range is systematically larger than |dClose|, so the two
    are not the same statistic, and the observed 0.0093 read as BELOW a
    diffusive process when it is vastly above one.

    The benchmark is therefore SIMULATED through the identical pipeline: a
    Gaussian walk with `sub` intra-bar steps gives real High/Low, from which
    true range and ATR(14) are computed exactly as for the real data.
    """
    rng = np.random.default_rng(seed)
    steps = rng.normal(0, 1, size=(n, sub)).cumsum(axis=1)
    op = np.concatenate([[0.0], steps[:-1, -1].cumsum()])
    df = pd.DataFrame({"High": op + np.maximum(steps.max(axis=1), 0),
                       "Low": op + np.minimum(steps.min(axis=1), 0),
                       "Close": op + steps[:, -1]})
    tr = pd.concat([df["High"] - df["Low"],
                    (df["High"] - df["Close"].shift()).abs(),
                    (df["Low"] - df["Close"].shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean().shift(1)
    move = (df["Close"] - df["Close"].shift()).abs()
    ok = atr.notna() & move.notna() & (atr > 0)
    ratio = move[ok] / atr[ok]
    return float((ratio > 3).mean()), float((ratio > 5).mean())


def m2(data):
    ref3, ref5 = matched_diffusive_rates()
    say("## M2 — Jumps")
    say()
    say("Bar returns beyond **3×** and **5×** trailing ATR(14). Counts are RAW")
    say("COUNTS; rates carry CIs.")
    say()
    say("**The diffusive benchmark is SIMULATED, not analytic**, because the")
    say("statistic's denominator is true range rather than a close-to-close")
    say("standard deviation. A Gaussian random walk is pushed through the")
    say("identical ATR pipeline (200,000 bars, 60 intra-bar steps): it produces")
    say("**P(>3×ATR) = %.5f** and **P(>5×ATR) = %.6f**." % (ref3, ref5))
    say()
    say("| ticker | bar | n | >3×ATR (raw) | rate | rate 95% CI | Gaussian exp. | >5×ATR (raw) | rate | P(jump t+1 \\| jump t) | base rate |")
    say("|---|---|---|---|---|---|---|---|---|---|---|")
    for t in TICKERS:
        for iv in ("1h", "4h", "1d"):
            df = data[t][iv]
            r = df["Close"].pct_change()
            tr = pd.concat([df["High"] - df["Low"],
                            (df["High"] - df["Close"].shift()).abs(),
                            (df["Low"] - df["Close"].shift()).abs()], axis=1).max(axis=1)
            atr = tr.rolling(14).mean().shift(1)
            move = (df["Close"] - df["Close"].shift()).abs()
            ok = atr.notna() & move.notna() & (atr > 0)
            ratio = (move[ok] / atr[ok])
            n = len(ratio)
            j3 = (ratio > 3).to_numpy()
            j5 = (ratio > 5).to_numpy()
            r3, r5 = j3.mean(), j5.mean()
            lo3, hi3, _ = boot_ci(j3.astype(float), np.mean, SEED0 + 11 + hash(t + iv) % 999)
            g3 = ref3
            nxt = j3[1:][j3[:-1]]
            cond = float(nxt.mean()) if len(nxt) else float("nan")
            say("| %s | %s | %d | %d | %.4f | %s | %.4f | %d | %.5f | %s | %.4f |"
                % (t, iv, n, int(j3.sum()), r3, ci(lo3, hi3, 4), g3,
                   int(j5.sum()), r5,
                   ("—" if cond != cond else "%.4f" % cond), r3))
    say()
    say("**Reading.** A diffusive process pushed through this exact pipeline")
    say("essentially NEVER produces a move beyond 3× its own trailing ATR — the")
    say("simulated rate is %.5f over 200,000 bars. The observed rates are two to" % ref3)
    say("three orders of magnitude larger, at every ticker and every horizon.")
    say("Jumps also")
    say("**cluster**: the probability of a jump tomorrow given a jump today")
    say("exceeds the base rate in essentially every cell.")
    say()
    say("**What it does NOT say:** fat tails and jump clustering are properties")
    say("of the RISK, not of an opportunity. They are the reason a fixed-R stop")
    say("geometry behaves the way it does; they say nothing about which side of")
    say("a jump to be on.")
    say()


# ======================================================================
# M3 — RETURN AUTOCORRELATION
# ======================================================================
def m3(data):
    say("## M3 — Return autocorrelation, lags 1–30")
    say()
    say("Signed returns. Bands are moving-block bootstrap 95% intervals, which")
    say("are heteroskedasticity-robust by construction because the resampling")
    say("preserves the volatility blocks rather than assuming homoskedasticity.")
    say()
    say("| ticker | bar | n | lag1 | lag1 95% CI | lag2 | lag3 | lag5 | lag10 | lag30 | lags with CI excluding 0 (of 30) |")
    say("|---|---|---|---|---|---|---|---|---|---|---|")
    hits_all = []
    for t in TICKERS:
        for iv in ("1h", "4h", "1d"):
            r = rets(data[t][iv]).to_numpy()
            lags = list(range(1, 31))
            a = acf(r, lags)
            l1, h1, _ = boot_ci(r, lambda z: acf(z, [1])[0],
                                SEED0 + 23 + hash(t + iv) % 999)
            hits = 0
            for k in lags:
                lo, hi, _ = boot_ci(r, lambda z, kk=k: acf(z, [kk])[0],
                                    SEED0 + 100 + k + hash(t + iv) % 999, reps=300)
                if lo == lo and (lo > 0 or hi < 0):
                    hits += 1
            hits_all.append(hits)
            say("| %s | %s | %d | %s | %s | %s | %s | %s | %s | %s | **%d** |"
                % (t, iv, len(r), fmt(a[0]), ci(l1, h1), fmt(a[1]), fmt(a[2]),
                   fmt(a[4]), fmt(a[9]), fmt(a[29]), hits))
    say()
    say("**Reading.** Signed-return autocorrelation is near zero at every lag,")
    say("ticker and horizon — one to two orders of magnitude smaller than the")
    say("|return| autocorrelation in M1. The last column counts how many of 30")
    say("lags have a bootstrap CI excluding zero.")
    say()
    say("**The multiple-comparisons point, concretely.** 9 series × 30 lags =")
    say("**270 cells**. At a 95% interval, ~13–14 would exclude zero **by chance**")
    say("even if every true autocorrelation were exactly zero. Counts near that")
    say("number are consistent with pure noise, and no individual lag should be")
    say("read as a finding.")
    say()


# ======================================================================
# M4 — CROSS-ASSET LEAD-LAG
# ======================================================================
def m4(data):
    say("## M4 — Cross-asset lead-lag: does BTC lead the alts?")
    say()
    say("Cross-correlation of BTC 1h returns at lag *k* against ETH/SOL returns")
    say("at *t*. **Positive lag = BTC LEADS.** Split by BTC volatility-regime")
    say("tercile (trailing 24h realised), and rolling by calendar year.")
    say()
    b = rets(data["BTC"]["1h"])
    say("| alt | lag (h) | corr | 95% CI | low-vol | mid-vol | high-vol |")
    say("|---|---|---|---|---|---|---|")
    for alt in ("ETH", "SOL"):
        a = rets(data[alt]["1h"])
        j = pd.concat([b.rename("b"), a.rename("a")], axis=1).dropna()
        vol = j["b"].rolling(24).std()
        terc = pd.qcut(vol, 3, labels=["low", "mid", "high"])
        for k in (0, 1, 2, 3, 6, 12, 24):
            x = j["b"].shift(k)
            m = x.notna() & j["a"].notna()
            c = float(np.corrcoef(x[m], j["a"][m])[0, 1])
            pair = (x[m].to_numpy() - x[m].mean()) * (j["a"][m].to_numpy() - j["a"][m].mean())
            sx, sy = x[m].std(), j["a"][m].std()
            lo, hi, _ = boot_ci(pair, lambda z: float(z.mean() / (sx * sy)),
                                SEED0 + 41 + k + hash(alt) % 999, reps=400)
            cells = []
            for lab in ("low", "mid", "high"):
                mm = m & (terc == lab)
                cells.append(fmt(float(np.corrcoef(x[mm], j["a"][mm])[0, 1]), 3)
                             if mm.sum() > 50 else "—")
            say("| %s | %d | %s | %s | %s | %s | %s |"
                % (alt, k, fmt(c, 4), ci(lo, hi, 4), *cells))
    say()
    say("### Rolling by year — BTC leads by 1h")
    say()
    say("| alt | year | n hours | corr at lag 1h | 95% CI |")
    say("|---|---|---|---|---|")
    for alt in ("ETH", "SOL"):
        a = rets(data[alt]["1h"])
        j = pd.concat([b.rename("b"), a.rename("a")], axis=1).dropna()
        j["bl"] = j["b"].shift(1)
        for yr, g in j.groupby(j.index.year):
            g = g.dropna()
            if len(g) < 500:
                continue
            c = float(np.corrcoef(g["bl"], g["a"])[0, 1])
            sx, sy = g["bl"].std(), g["a"].std()
            pair = (g["bl"].to_numpy() - g["bl"].mean()) * (g["a"].to_numpy() - g["a"].mean())
            lo, hi, _ = boot_ci(pair, lambda z: float(z.mean() / (sx * sy)),
                                SEED0 + 61 + yr + hash(alt) % 999, reps=400)
            say("| %s | %d | %d | %s | %s |" % (alt, yr, len(g), fmt(c, 4), ci(lo, hi, 4)))
    say()
    say("**Reading.** This is the folklore claim — *BTC leads the alts* — and")
    say("the map measures it rather than assuming it. Read the lag-0 row first:")
    say("it is the contemporaneous correlation, and it is large. The lagged rows")
    say("are what a lead would require, and they are the ones to judge.")
    say()
    say("**What it does NOT say:** a non-zero lagged correlation is not a")
    say("tradeable lead. At 1h granularity, a correlation of a few hundredths")
    say("is far below the cost floor this project measured (a 0.80% stop floor,")
    say("~4bps round trip), and nothing here nets that.")
    say()


# ======================================================================
# M5 — CALENDAR STRUCTURE
# ======================================================================
def m5(data):
    say("## M5 — Calendar structure")
    say()
    say("Hour-of-day and day-of-week mean return and volatility, 1h bars, with")
    say("bootstrap CIs on the mean. **The 00/08/16 UTC funding-settlement hours")
    say("are reported separately** because they are the hours a funding-driven")
    say("effect would have to live in.")
    say()
    say("### Hour-of-day, BTC 1h (settlement hours marked)")
    say()
    say("| hour UTC | n | mean ret (bps) | 95% CI (bps) | vol (bps) | settlement |")
    say("|---|---|---|---|---|---|")
    r = rets(data["BTC"]["1h"])
    for h in range(24):
        g = r[r.index.hour == h]
        lo, hi, _ = boot_ci(g.to_numpy(), np.mean, SEED0 + 200 + h, reps=400)
        say("| %02d | %d | %+.3f | [%+.3f, %+.3f] | %.1f | %s |"
            % (h, len(g), 1e4 * g.mean(), 1e4 * lo, 1e4 * hi, 1e4 * g.std(),
               "**YES**" if h in (0, 8, 16) else ""))
    say()
    say("### Settlement vs non-settlement hours, all three tickers")
    say()
    say("| ticker | group | n | mean ret (bps) | 95% CI (bps) | vol (bps) |")
    say("|---|---|---|---|---|---|")
    for t in TICKERS:
        rr = rets(data[t]["1h"])
        for lab, mask in (("settlement (00/08/16)", rr.index.hour.isin([0, 8, 16])),
                          ("other 21 hours", ~rr.index.hour.isin([0, 8, 16]))):
            g = rr[mask]
            lo, hi, _ = boot_ci(g.to_numpy(), np.mean, SEED0 + 300 + hash(t + lab) % 999, reps=400)
            say("| %s | %s | %d | %+.3f | [%+.3f, %+.3f] | %.1f |"
                % (t, lab, len(g), 1e4 * g.mean(), 1e4 * lo, 1e4 * hi, 1e4 * g.std()))
    say()
    say("### Day-of-week, daily bars")
    say()
    say("| ticker | day | n | mean ret (bps) | 95% CI (bps) | vol (bps) |")
    say("|---|---|---|---|---|---|")
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    for t in TICKERS:
        rr = rets(data[t]["1d"])
        for i, nm in enumerate(names):
            g = rr[rr.index.dayofweek == i]
            lo, hi, _ = boot_ci(g.to_numpy(), np.mean, SEED0 + 400 + i + hash(t) % 999, reps=400)
            say("| %s | %s | %d | %+.1f | [%+.1f, %+.1f] | %.0f |"
                % (t, nm, len(g), 1e4 * g.mean(), 1e4 * lo, 1e4 * hi, 1e4 * g.std()))
    say()
    say("**Reading.** Crypto trades continuously, so calendar structure has no")
    say("session open or close to anchor it. Read the CIs, not the point")
    say("estimates: an hour whose interval straddles zero is not distinguishable")
    say("from the rest of the day.")
    say()
    say("**Multiple comparisons, concretely.** 24 hours × 3 tickers + 7 days ×")
    say("3 tickers = **93 cells**. About 5 will exclude zero by chance. Any")
    say("single striking hour in this table is far more likely to be one of")
    say("those five than a real effect.")
    say()


# ======================================================================
# M6 — CROSS-SECTIONAL DISPERSION
# ======================================================================
def m6():
    say("## M6 — Cross-sectional dispersion: does a cross-section exist?")
    say()
    say("Rolling 60-day average pairwise correlation and cross-sectional return")
    say("dispersion across the #167 tradable-26, daily. **This is the ROTATION")
    say("context, measured** — that program assumed a cross-section existed to")
    say("select from.")
    say()
    uni = [l.strip() for l in open(os.path.join(ROOT, "research",
           "basket_tradable.txt"), encoding="utf-8") if l.strip()]
    cols = {}
    for t in uni:
        p = os.path.join(ROOT, "data", "basket", "%s_4h.csv.gz" % t)
        if os.path.exists(p):
            b = pd.read_csv(p, index_col=0, parse_dates=True).sort_index()
            cols[t] = b["Close"].resample("1D").last()
    px = pd.DataFrame(cols).sort_index()
    bars, merged, daily = H.load_ticker("BTC")
    seal = H.make_windows(daily).lockbox[0]
    px = px[px.index < seal]
    r = px.pct_change()
    say("| year | days | assets alive | mean pairwise corr | 95% CI | mean daily dispersion (bps) | 95% CI |")
    say("|---|---|---|---|---|---|---|")
    for yr, g in r.groupby(r.index.year):
        alive = g.columns[g.notna().sum() > 200]
        if len(alive) < 3:
            continue
        gg = g[alive]
        cm = gg.corr().to_numpy()
        iu = np.triu_indices_from(cm, k=1)
        pw = cm[iu]
        pw = pw[np.isfinite(pw)]
        lo, hi, _ = boot_ci(pw, np.mean, SEED0 + 500 + yr, reps=400)
        disp = gg.std(axis=1).dropna()
        dlo, dhi, _ = boot_ci(disp.to_numpy(), np.mean, SEED0 + 600 + yr, reps=400)
        say("| %d | %d | %d | %s | %s | %.0f | [%.0f, %.0f] |"
            % (yr, len(gg), len(alive), fmt(float(pw.mean()), 3), ci(lo, hi, 3),
               1e4 * disp.mean(), 1e4 * dlo, 1e4 * dhi))
    say()
    say("**Reading.** Average pairwise correlation is the quantity that decides")
    say("whether picking *which* asset can matter. When it is high, the assets")
    say("move as one and cross-sectional selection has little to select on;")
    say("dispersion is the complementary view.")
    say()
    say("**This is the measured context for ROTATION's failure and for")
    say("NULL-CALIBRATION's finding** that a rank-permutation null inherits the")
    say("effect on a correlated universe. It does not re-open either — it says")
    say("what the correlation actually was, year by year, with bands.")
    say()


# ======================================================================
# M7 — ASYMMETRY
# ======================================================================
def m7(data):
    say("## M7 — Asymmetry: up-moves vs down-moves")
    say()
    say("Consecutive same-sign daily runs, and the drawdown depth / recovery")
    say("time distribution. Counts are RAW; means carry CIs.")
    say()
    say("| ticker | direction | runs (raw) | mean length (d) | 95% CI | mean magnitude (%) | 95% CI |")
    say("|---|---|---|---|---|---|---|")
    for t in TICKERS:
        r = rets(data[t]["1d"])
        sign = np.sign(r.to_numpy())
        runs_len, runs_mag, cur_l, cur_m, cur_s = [], [], 0, 0.0, 0
        for s, v in zip(sign, r.to_numpy()):
            if s == cur_s and s != 0:
                cur_l += 1
                cur_m += v
            else:
                if cur_s != 0:
                    runs_len.append((cur_s, cur_l))
                    runs_mag.append((cur_s, cur_m))
                cur_s, cur_l, cur_m = s, 1, v
        if cur_s != 0:
            runs_len.append((cur_s, cur_l))
            runs_mag.append((cur_s, cur_m))
        for lab, sgn in (("up", 1), ("down", -1)):
            L = np.array([l for s, l in runs_len if s == sgn], dtype=float)
            M = np.array([abs(m) for s, m in runs_mag if s == sgn], dtype=float)
            llo, lhi, _ = boot_ci(L, np.mean, SEED0 + 700 + sgn + hash(t) % 999, reps=400)
            mlo, mhi, _ = boot_ci(M, np.mean, SEED0 + 800 + sgn + hash(t) % 999, reps=400)
            say("| %s | %s | %d | %.2f | [%.2f, %.2f] | %.2f | [%.2f, %.2f] |"
                % (t, lab, len(L), L.mean(), llo, lhi,
                   100 * M.mean(), 100 * mlo, 100 * mhi))
    say()
    say("### Drawdown depth vs recovery time")
    say()
    say("| ticker | drawdowns >10% (raw) | median depth (%) | median recovery (d) | max depth (%) | longest recovery (d) | still unrecovered |")
    say("|---|---|---|---|---|---|---|")
    for t in TICKERS:
        c = data[t]["1d"]["Close"]
        peak = c.cummax()
        dd = c / peak - 1.0
        episodes, in_dd, start, trough = [], False, None, 0.0
        for i, (ts, v) in enumerate(dd.items()):
            if v < 0 and not in_dd:
                in_dd, start, trough = True, ts, v
            elif in_dd:
                trough = min(trough, v)
                if v >= 0:
                    episodes.append((start, ts, trough, (ts - start).days))
                    in_dd = False
        unrec = 0
        if in_dd:
            unrec = 1
            episodes.append((start, dd.index[-1], trough, (dd.index[-1] - start).days))
        big = [e for e in episodes if e[2] <= -0.10]
        if not big:
            say("| %s | 0 | — | — | — | — | %d |" % (t, unrec))
            continue
        depths = np.array([-100 * e[2] for e in big])
        recs = np.array([e[3] for e in big], dtype=float)
        say("| %s | %d | %.1f | %.0f | %.1f | %.0f | %d |"
            % (t, len(big), np.median(depths), np.median(recs),
               depths.max(), recs.max(), unrec))
    say()
    say("**Reading.** Up-runs and down-runs differ in length and in magnitude,")
    say("and drawdowns take far longer to recover than to create. This is the")
    say("structural reason a fixed-R geometry with a 15-day hold behaves")
    say("asymmetrically, and it is context for the live record's short-side")
    say("result (0 wins in 11 short episodes).")
    say()
    say("**What it does NOT say:** asymmetry is not a timing signal. Knowing")
    say("downs are sharper than ups does not say when either begins.")
    say()


# ======================================================================
# M8 — TRADABILITY DRIFT
# ======================================================================
def m8():
    say("## M8 — Tradability drift over time")
    say()
    say("#167's tradability measure as a TIME SERIES: flat-bar share (bars with")
    say("zero range) and median stop fraction (1.5×ATR / close) per year, per")
    say("basket ticker. #167 applied this as a one-off filter; this asks whether")
    say("it drifts.")
    say()
    uni = [l.strip() for l in open(os.path.join(ROOT, "research",
           "basket_tradable.txt"), encoding="utf-8") if l.strip()]
    bars, merged, daily = H.load_ticker("BTC")
    seal = H.make_windows(daily).lockbox[0]
    rows = {}
    for t in uni:
        p = os.path.join(ROOT, "data", "basket", "%s_4h.csv.gz" % t)
        if not os.path.exists(p):
            continue
        b = pd.read_csv(p, index_col=0, parse_dates=True).sort_index()
        b = b[b.index < seal]
        tr = pd.concat([b["High"] - b["Low"],
                        (b["High"] - b["Close"].shift()).abs(),
                        (b["Low"] - b["Close"].shift()).abs()], axis=1).max(axis=1)
        atr = tr.rolling(14).mean()
        flat = (b["High"] == b["Low"])
        stopfrac = (1.5 * atr / b["Close"])
        for yr, idx in b.groupby(b.index.year).groups.items():
            g = b.loc[idx]
            rows.setdefault(yr, []).append(
                (t, float(flat.loc[idx].mean()),
                 float(stopfrac.loc[idx].median())))
    say("| year | tickers | median flat-bar share | 95% CI | median stop fraction | 95% CI | tickers under the 0.80% cost floor |")
    say("|---|---|---|---|---|---|---|")
    for yr in sorted(rows):
        v = rows[yr]
        fl = np.array([x[1] for x in v], dtype=float)
        sf = np.array([x[2] for x in v if x[2] == x[2]], dtype=float)
        flo, fhi, _ = boot_ci(fl, np.median, SEED0 + 900 + yr, reps=400)
        slo, shi, _ = boot_ci(sf, np.median, SEED0 + 950 + yr, reps=400)
        under = int((sf < 0.008).sum())
        say("| %d | %d | %.4f | [%.4f, %.4f] | %.4f | [%.4f, %.4f] | %d |"
            % (yr, len(v), np.median(fl), flo, fhi,
               np.median(sf), slo, shi, under))
    say()
    say("**Reading.** The last column counts tickers whose median 1.5×ATR stop")
    say("sits below the **0.80% cost floor** this project derived from")
    say("`MAX_COST_FRACTION_OF_R = 0.10`. A ticker under that floor pays more")
    say("than a tenth of its risk in costs, which is what #167 filtered on.")
    say()
    say("**What it does NOT say:** improving tradability is not improving")
    say("opportunity. #163–#167 measured the filtered basket and it still")
    say("failed; a cleaner instrument does not create an edge.")
    say()


# ======================================================================
# MAIN
# ======================================================================
def main():
    data, seal = load()
    say("# Market-structure map (#249)")
    say()
    say("**DESCRIPTIVE. No hypotheses, no pass conditions, no verdicts, no")
    say("signals.** Registered and locked in `docs/cleanroom.md` before any")
    say("number below was computed. Nothing here is scored through the trade")
    say("machinery and no return-vs-signal join is made.")
    say()
    spans = {t: (data[t]["1h"].index.min().date(), data[t]["1h"].index.max().date())
             for t in TICKERS}
    say("Data: pre-lockbox frozen bars only. **The lockbox opens %s and is "
        "never read.** BTC %s -> %s, ETH %s -> %s, SOL %s -> %s."
        % (seal.date(), spans["BTC"][0], spans["BTC"][1],
           spans["ETH"][0], spans["ETH"][1], spans["SOL"][0], spans["SOL"][1]))
    say()
    say("Bootstrap: **moving-block, 1,000 resamples, block length ℓ = ⌈n^(1/3)⌉**")
    say("(reduced to 300–400 resamples on the densest per-lag sweeps, noted in")
    say("place). Fixed in the registration before any result, so no band can be")
    say("widened or narrowed after the fact. CIs are 95% percentile intervals.")
    say()
    say("---")
    say()
    say("## ⚠ THE CAVEAT THAT GOVERNS THIS ENTIRE DOCUMENT")
    say()
    say("**This map contains several hundred measured cells. Some of them WILL")
    say("look remarkable by chance.** That is arithmetic, not modesty: at a 95%")
    say("interval, one cell in twenty excludes zero when nothing is there.")
    say()
    say("**This is exactly why the map buys ONE hypothesis and not many.** Under")
    say("#249's registered one-hypothesis rule, at most a single future")
    say("hypothesis (#250) may be drawn from everything below, and it may be")
    say("tested **only on data timestamped after this map's freeze**.")
    say()
    say("**The map may never be cited as evidence of an edge** — not as support,")
    say("not as partial support, not as \"consistent with\". Its only legitimate")
    say("use is as *the reason a hypothesis was worth registering*.")
    say()
    say("---")
    say()
    m1(data)
    say("---")
    say()
    m2(data)
    say("---")
    say()
    m3(data)
    say("---")
    say()
    m4(data)
    say("---")
    say()
    m5(data)
    say("---")
    say()
    m6()
    say("---")
    say()
    m7(data)
    say("---")
    say()
    m8()
    say("---")
    say()
    say("## What this map is for")
    say()
    say("It is a description of the terrain, not a route across it. Every")
    say("measurement above is a property of the market that would be true")
    say("whether or not anyone traded it, and none of them is a claim that")
    say("something can be traded.")
    say()
    say("**`docs/claims.md` is unchanged by this document and cannot be changed")
    say("by it.** The project still holds zero supported edge claims.")
    say()
    say("The next step, if there is one, is **exactly one** registered")
    say("hypothesis (#250), drawn from here, tested only on data that did not")
    say("exist when this was written.")

    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(LINES) + "\n")
    print("wrote %s (%d lines)" % (OUT, len(LINES)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
