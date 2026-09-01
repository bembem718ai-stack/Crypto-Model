"""research/premia.py — #257 THE PREMIA INSTRUMENT.

A DESCRIPTIVE program in the #249 style. NO hypotheses, NO verdicts, NO
pass rules. Its sole product is a dated measurement table appended to
docs/premia.md, plus a monthly summary block the transparency post may
include.

WHAT THESE NUMBERS ARE. Risk premia: payment for bearing crash risk and
balance-sheet risk. Someone is compensated for holding an exposure that
hurts precisely when it is most painful to hold, or for lending balance
sheet to someone who must be levered.

WHAT THESE NUMBERS ARE NOT.
  * NOT alpha. A premium is a fee for a risk actually borne, not a
    mispricing. Harvesting it means taking the loss when it comes.
  * NOT signals. Nothing here enters the published signal path, ever.
  * NOT tradeable by this operator. Every one of these requires venue
    access, margin, and a balance sheet this project does not have. The
    instrument exists to MEASURE what professionals harvest, on data we
    manufacture ourselves.

THE #249 CI RULE APPLIES TO EVERY NUMBER: it carries an uncertainty
interval, or it is explicitly labelled a RAW SAMPLE. There is no third
category, and "the number is probably about right" is not one.

DATA IS READ ONLY FROM OUR OWN ARCHIVES. No network call, no live fetch,
no lockbox read. If an archive is too young to support a statistic, this
module says so and reports what IS available instead of quietly widening
a window until something appears.
"""
import os
import sys
import argparse
import datetime as dt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DERIV = os.path.join(ROOT, "data", "derivatives")
OUT_MD = os.path.join(ROOT, "docs", "premia.md")

HOURS_PER_YEAR = 24 * 365                    # 8760, no leap-day convention
DAYS_PER_YEAR = 365.0

# UNCERTAINTY. Funding is strongly autocorrelated -- regimes persist for
# weeks -- so an iid bootstrap would report an interval several times too
# narrow and every carry number would look far more certain than it is.
# A MOVING-BLOCK bootstrap at ~30 days of observations keeps the
# within-block dependence intact. The block is stated, not tuned.
BLOCK_DAYS = 30
BOOT_DRAWS = 2000
BOOT_SEED = 257000

# Below this many observations no interval is reported and the number is
# labelled a RAW SAMPLE. 3 blocks is the floor at which a block bootstrap
# is resampling anything at all rather than reprinting the sample.
MIN_BLOCKS = 3

# Kraken marks an instrument AT INDEX when it has no book. Those rows
# produce a basis of exactly 0.00%, which looks like a measurement and is
# not one. Liveness is required and is stated as a rule, not applied by
# hand. Measured 2026-09-01: all 8 FI_ (inverse dated) rows were dead by
# this test, and all 9 FF_ (linear dated) rows were live.
MIN_OI = 0.0
MIN_VOL24H = 0.0


# ----------------------------------------------------------------------
# UNCERTAINTY
# ----------------------------------------------------------------------

def time_weighted_carry(rates, hours):
    """Annualised carry actually received: total paid / total elapsed.

    THE ESTIMATOR THIS REPLACED WAS ROW-WEIGHTED AND WRONG, and it was
    wrong in the worst available way. Averaging per-row annualised rates
    gives every row equal weight, but a 2-hour funding row covers a
    QUARTER of the time an 8-hour row covers while being scaled by 4x as
    much. Binance's SOLUSDT archive carries 99 two-hour rows and 2
    four-hour rows out of 6,610 -- and those 101 rows dragged the
    six-year mean to -12.98%/yr against a time-weighted truth of
    +0.17%/yr.

    A negative six-year carry on a major alt is entirely plausible: it
    reads as "SOL perps were structurally in backwardation", which a
    reader accepts without blinking. It raised no error and no warning,
    and it agreed with the correct answer to 0.000pp on BTCUSDT and
    ETHUSDT -- the two symbols anyone checks first -- because those are
    all-8h. That is exactly the failure shape this instrument is supposed
    to catch, and it was in the instrument.

    The identity that makes the fix obvious once seen:
        sum_i(ann_i * hours_i) / sum_i(hours_i)
          = sum_i(rate_i * 8760/hours_i * hours_i) / sum_i(hours_i)
          = 8760 * sum_i(rate_i) / sum_i(hours_i)
    i.e. total funding paid, over total time elapsed. No per-row
    annualisation survives into the aggregate at all.
    """
    r = np.asarray(rates, dtype=float)
    h = np.asarray(hours, dtype=float)
    ok = (r == r) & (h == h) & (h > 0)
    if not ok.any():
        return float("nan")
    return float(HOURS_PER_YEAR * r[ok].sum() / h[ok].sum())


def block_bootstrap_ci(values, block, draws=BOOT_DRAWS, seed=BOOT_SEED,
                        lo=2.5, hi=97.5, hours=None):
    """Percentile CI under serial dependence.

    With `hours`, resamples (rate, hours) blocks and recomputes the
    TIME-WEIGHTED carry inside each draw, so the interval is an interval
    on the statistic actually published. Without it, a plain block mean.

    Returns (lo, hi, n_blocks) or (nan, nan, n_blocks) when the series is
    too short to resample. The caller must label a nan interval as a RAW
    SAMPLE -- never print the point estimate bare.
    """
    v = np.asarray(values, dtype=float)
    h = np.asarray(hours, dtype=float) if hours is not None else None
    if h is None:
        keep = v == v
    else:
        keep = (v == v) & (h == h) & (h > 0)
    v = v[keep]
    h = h[keep] if h is not None else None
    n = len(v)
    block = max(1, min(int(block), n)) if n else 1
    n_blocks = n // block if block else 0
    if n == 0 or n_blocks < MIN_BLOCKS:
        return float("nan"), float("nan"), n_blocks
    rng = np.random.default_rng(seed)
    starts_max = n - block
    k = int(np.ceil(n / block))
    stat = np.empty(draws, dtype=float)
    for i in range(draws):
        starts = rng.integers(0, starts_max + 1, size=k)
        idx = np.concatenate([np.arange(st, st + block) for st in starts])[:n]
        if h is None:
            stat[i] = v[idx].mean()
        else:
            stat[i] = HOURS_PER_YEAR * v[idx].sum() / h[idx].sum()
    return float(np.percentile(stat, lo)), float(np.percentile(stat, hi)), n_blocks


def fmt_pct(x, dp=2):
    return "n/a" if x is None or x != x else "%+.*f%%" % (dp, 100.0 * x)


def fmt_ci(lo, hi, dp=2):
    if lo != lo or hi != hi:
        return "RAW SAMPLE"
    return "[%s, %s]" % (fmt_pct(lo, dp), fmt_pct(hi, dp))


def _read(name):
    p = os.path.join(DERIV, "%s.csv" % name)
    if not os.path.exists(p):
        return None
    d = pd.read_csv(p)
    if "timestamp" in d.columns:
        d["timestamp"] = pd.to_datetime(d["timestamp"], format="mixed",
                                        utc=True, errors="coerce")
    return d


# ----------------------------------------------------------------------
# (a) VARIANCE RISK PREMIUM — BTC, ETH
# ----------------------------------------------------------------------

def variance_risk_premium():
    """Implied vol now versus vol realised SUBSEQUENTLY over the horizon.

    THIS IS NOT COMPUTABLE YET AND THE HONEST OUTPUT IS TO SAY SO.

    A VRP needs implied at time t compared with what realises AFTER t. Our
    option-chain series began 2026-09-01 and holds ONE daily snapshot per
    currency, so there is no t with a subsequent realisation to compare it
    to. The first genuine VRP observation exists once one horizon has
    elapsed past the first snapshot; a usable DISTRIBUTION of them needs
    many more, and this instrument will keep reporting NOT COMPUTABLE until
    the count is stated as adequate here rather than assumed.

    A SECOND, DEEPER PROBLEM, recorded now so it is not discovered later as
    a surprise: `oi_weighted_mark_iv` is weighted across the ENTIRE live
    chain -- every strike AND every expiry. It therefore has no single
    horizon, so there is no "matching horizon" to realise against. Fixing
    that needs a per-expiry IV term structure the collector does not
    currently store. Until it does, even a long options archive would only
    support a HORIZON-BLENDED premium, and that is a weaker quantity than
    the name "variance risk premium" implies.

    WHAT IS COMPUTABLE TODAY is implied vol against TRAILING realised vol
    -- Deribit's own ~16-day rolling historical volatility, backward
    looking. That is a spread between two contemporaneous observations,
    NOT a risk premium, and it is reported under its own name with N
    stated. It may not be called a VRP anywhere.
    """
    d = _read("deribit_options")
    out = {"status": "NOT COMPUTABLE", "rows": [], "notes": []}
    if d is None or d.empty:
        out["notes"].append("deribit_options.csv absent")
        return out

    chain = d[d["symbol"].str.endswith("-OPTIONS")]
    hv = d[d["symbol"].str.endswith("-HISTVOL")]

    for ccy in ("BTC", "ETH"):
        c = chain[chain["symbol"] == "%s-OPTIONS" % ccy].sort_values("timestamp")
        h = hv[hv["symbol"] == "%s-HISTVOL" % ccy].sort_values("timestamp")
        if c.empty:
            out["notes"].append("%s: no option-chain rows" % ccy)
            continue
        last = c.iloc[-1]
        iv = last.get("oi_weighted_mark_iv")
        # Deribit serves mark_iv and historical_volatility in PERCENT.
        # Dividing one and not the other is a 100x error that still looks
        # like a plausible volatility number, so both convert here.
        iv = float(iv) / 100.0 if iv == iv else float("nan")
        rv = float("nan")
        rv_obs = 0
        if not h.empty:
            # ANCHOR ON observed_utc, NOT timestamp. The chain row's
            # `timestamp` is floored to 00:00Z while the read actually
            # happened hours later (02:42Z on the first row). Matching on
            # the floored value picks a realised reading from BEFORE the
            # implied one existed -- small today, but it is a look-back
            # against a forward-looking measurement, which is the one
            # direction of error this instrument may never make.
            anchor = pd.to_datetime(last.get("observed_utc"), utc=True,
                                    errors="coerce")
            if anchor != anchor:
                anchor = last["timestamp"]
            hh = h[h["timestamp"] <= anchor]
            hh = hh if not hh.empty else h
            rv = float(hh.iloc[-1]["historical_volatility"]) / 100.0
            rv_obs = int(len(h))
        out["rows"].append({
            "ccy": ccy,
            "as_of": str(pd.Timestamp(last["timestamp"]).date()),
            "iv": iv, "n_iv": int(len(c)),
            "rv_trailing": rv, "n_rv": rv_obs,
            "spread": (iv - rv) if (iv == iv and rv == rv) else float("nan"),
            "n_options": last.get("n_options"),
            "put_call_oi": last.get("put_call_oi_ratio"),
        })

    n_days = int(chain["timestamp"].dt.date.nunique()) if not chain.empty else 0
    out["notes"].append(
        "VRP needs implied at t vs realised AFTER t. The option-chain "
        "archive holds %d distinct observation day(s) per currency, so no "
        "observation has a subsequent realisation yet." % n_days)
    out["notes"].append(
        "oi_weighted_mark_iv is OI-weighted across ALL strikes AND ALL "
        "expiries, so it has no single horizon to realise against. A true "
        "matched-horizon VRP additionally requires a per-expiry IV term "
        "structure the collector does not yet store.")
    out["notes"].append(
        "The spread below is IMPLIED minus TRAILING realised, in VOL "
        "POINTS (annualised percentage points), not variance points. The "
        "two nearly coincide at BTC's current level -- iv^2-rv^2 = "
        "(iv+rv)(iv-rv) and (iv+rv) is about 0.97 near 48% vol -- so a "
        "maintainer who swapped them would see a 3% discrepancy on BTC "
        "and a 30% one on ETH. The unit is therefore named on the column, "
        "never left bare.")
    out["notes"].append(
        "Deribit's realised series is described everywhere in this repo as "
        "a ~16-day window. MEASURED against the chain it is about 356h "
        "(~14.8d) with a +/-20h band, so it is labelled ~15d here. The "
        "distinction is operational rather than cosmetic: it sets the "
        "forward shift once a genuine VRP becomes computable, and shifting "
        "by more than the true window inserts a dead gap while shifting by "
        "less puts already-realised returns inside the 'subsequent' leg.")
    out["notes"].append(
        "It is a contemporaneous spread, NOT a variance risk premium, and "
        "carries no uncertainty at N=1.")
    return out


# ----------------------------------------------------------------------
# (b) PERP CARRY YIELD — funding, annualised
# ----------------------------------------------------------------------

def _skew_flag(v, published_mean):
    """True when the PUBLISHED carry sits far from the typical interval.

    Compares the time-weighted number actually printed against the median
    per-interval rate, scaled by the interquartile spread. A wide gap
    means the window's total is dominated by a minority of intervals: the
    mean is still the yield genuinely received, but a reader must be told
    when it is a few unusual weeks wearing a multi-year label.

    IT COMPARES THE PUBLISHED STATISTIC ON PURPOSE. An earlier version
    flagged the mean of per-row annualised rates -- a quantity this
    module no longer publishes -- so the warning could have fired for, or
    stayed silent about, a number no reader ever saw.
    """
    v = np.asarray([x for x in v if x == x], dtype=float)
    if len(v) < 10 or published_mean != published_mean:
        return False
    med = float(np.median(v))
    spread = float(np.percentile(v, 75) - np.percentile(v, 25))
    return bool(spread > 0 and abs(published_mean - med) > spread)


def _annualise_binance(d):
    """Per-row annualised rate. The INTERVAL IS PER ROW, not per venue.

    Binance's funding interval is not a constant: this archive carries
    8h on 21,119 rows, 2h on 99 and 4h on 2 -- SOL's FTX-window episode.
    Multiplying everything by 3/day would overstate those 101 rows by 4x
    and 2x. The factor is derived from the row's own interval column.
    """
    iv = pd.to_numeric(d["funding_interval_hours"], errors="coerce")
    iv = iv.where(iv > 0)
    return pd.to_numeric(d["funding_rate"], errors="coerce") * (HOURS_PER_YEAR / iv)


def perp_carry():
    """Annualised funding, per symbol. Binance PRIMARY, Kraken BESIDE it.

    ARITHMETIC annualisation, not compounded: funding is paid out at each
    interval and is not reinvested into the position, so rate x
    intervals-per-year is the yield actually received. Compounding would
    report a number nobody collects.

    THE KRAKEN UNIT TRAP, verified empirically rather than assumed.
    kraken_funding.csv carries BOTH `funding_rate` and
    `relative_funding_rate`. `funding_rate` is in PRICE UNITS -- median
    0.309 for PF_XBTUSD against a ~$78k index, i.e. 0.309/78000 = 3.96e-6,
    which matches `relative_funding_rate`'s median 3.85e-6. So the
    FRACTIONAL rate is `relative_funding_rate`. Using `funding_rate`
    instead would report BTC carry as roughly 270,000% a year -- absurd
    enough to catch, but the same error on a low-priced symbol lands in
    the plausible range and would not be caught at all.

    Kraken's series is HOURLY (8,874 rows over ~370 days), so its factor
    is 8760, not the 1,095 that an assumed 8-hour interval would give.
    """
    res = {"binance": [], "kraken": [], "okx": [], "notes": []}

    b = _read("binance_funding")
    if b is not None and not b.empty:
        b = b.dropna(subset=["timestamp"])
        b["ann"] = _annualise_binance(b)
        per_day = 1  # rows/day varies with interval; block in ROWS below
        for sym, g in b.groupby("symbol"):
            g = g.sort_values("timestamp")
            iv_med = float(pd.to_numeric(g["funding_interval_hours"],
                                         errors="coerce").median())
            rows_per_day = 24.0 / iv_med if iv_med else 3.0
            block = max(1, int(round(BLOCK_DAYS * rows_per_day)))
            v = g["ann"].to_numpy(dtype=float)
            rate = pd.to_numeric(g["funding_rate"], errors="coerce").to_numpy(float)
            hrs = pd.to_numeric(g["funding_interval_hours"],
                                errors="coerce").to_numpy(float)
            lo, hi, nb = block_bootstrap_ci(rate, block, hours=hrs)
            tw = time_weighted_carry(rate, hrs)
            res["binance"].append({
                "symbol": sym, "n": int(len(g)),
                "skew_flag": _skew_flag(v, tw),
                "span": "%s -> %s" % (g["timestamp"].min().date(),
                                       g["timestamp"].max().date()),
                "mean_ann": tw,
                "row_mean_ann": float(np.nanmean(v)),
                "median_ann": float(np.nanmedian(v)),
                "ci": (lo, hi), "n_blocks": nb,
                "intervals": sorted(set(int(x) for x in
                                        g["funding_interval_hours"].dropna())),
            })

    k = _read("kraken_funding")
    if k is not None and not k.empty:
        k = k.dropna(subset=["timestamp"])
        for sym, g in k.groupby("symbol"):
            g = g.sort_values("timestamp")
            # HOURLY series -> 8760. Derived below from the observed
            # spacing rather than assumed, so a venue change is caught.
            if len(g) > 2:
                spacing_h = float(g["timestamp"].diff().dt.total_seconds()
                                  .median()) / 3600.0
            else:
                spacing_h = 1.0
            spacing_h = spacing_h if spacing_h and spacing_h > 0 else 1.0
            rate = pd.to_numeric(g["relative_funding_rate"], errors="coerce").to_numpy(float)
            v = rate * (HOURS_PER_YEAR / spacing_h)
            hrs = np.full(len(rate), spacing_h, dtype=float)
            block = max(1, int(round(BLOCK_DAYS * 24.0 / spacing_h)))
            lo, hi, nb = block_bootstrap_ci(rate, block, hours=hrs)
            tw = time_weighted_carry(rate, hrs)
            res["kraken"].append({
                "symbol": sym, "n": int(len(g)),
                "skew_flag": _skew_flag(v, tw),
                "span": "%s -> %s" % (g["timestamp"].min().date(),
                                       g["timestamp"].max().date()),
                "mean_ann": tw,
                "row_mean_ann": float(np.nanmean(v)),
                "median_ann": float(np.nanmedian(v)),
                "ci": (lo, hi), "n_blocks": nb,
                "spacing_h": round(spacing_h, 3),
            })

    o = _read("okx_funding")
    if o is not None and not o.empty:
        o = o.dropna(subset=["timestamp"])
        for sym, g in o.groupby("symbol"):
            g = g.sort_values("timestamp")
            if len(g) > 2:
                spacing_h = float(g["timestamp"].diff().dt.total_seconds()
                                  .median()) / 3600.0
            else:
                spacing_h = 8.0
            spacing_h = spacing_h if spacing_h and spacing_h > 0 else 8.0
            rate = pd.to_numeric(g["funding_rate"], errors="coerce").to_numpy(float)
            v = rate * (HOURS_PER_YEAR / spacing_h)
            hrs = np.full(len(rate), spacing_h, dtype=float)
            block = max(1, int(round(BLOCK_DAYS * 24.0 / spacing_h)))
            lo, hi, nb = block_bootstrap_ci(rate, block, hours=hrs)
            tw = time_weighted_carry(rate, hrs)
            res["okx"].append({
                "symbol": sym, "n": int(len(g)),
                "skew_flag": _skew_flag(v, tw),
                "span": "%s -> %s" % (g["timestamp"].min().date(),
                                       g["timestamp"].max().date()),
                "mean_ann": tw,
                "row_mean_ann": float(np.nanmean(v)),
                "median_ann": float(np.nanmedian(v)),
                "ci": (lo, hi), "n_blocks": nb,
                "spacing_h": round(spacing_h, 3),
            })

    res["notes"].append(
        "TIME-WEIGHTED: total funding paid over total time elapsed "
        "(8760 x sum(rate) / sum(interval_hours)), not a mean of per-row "
        "annualised rates. Under mixed intervals a row-mean over-weights "
        "the short rows -- it put SOLUSDT's six-year carry at -12.98%/yr "
        "against a time-weighted +0.17%/yr, while agreeing to 0.000pp on "
        "the all-8h BTC and ETH.")
    res["notes"].append(
        "Arithmetic annualisation, not compounded: funding is paid out per "
        "interval and not reinvested.")
    res["notes"].append(
        "Binance interval is taken PER ROW from funding_interval_hours; "
        "SOL carries 2h and 4h episodes where a flat 3x/day would "
        "overstate by 4x and 2x.")
    res["notes"].append(
        "Kraken uses relative_funding_rate (the FRACTIONAL rate); its "
        "funding_rate column is in price units and would misstate carry by "
        "roughly the index price.")
    if any(r.get("skew_flag") for r in
           res["binance"] + res["kraken"] + res["okx"]):
        res["notes"].append(
            "WHERE FLAGGED, THE PUBLISHED CARRY SITS MORE THAN AN "
            "INTERQUARTILE SPREAD FROM THE TYPICAL INTERVAL -- the window's "
            "total is dominated by a minority of intervals. The mean is "
            "still the yield genuinely received; the median is the typical "
            "one. Both are shown; neither is dropped.")
    res["notes"].append(
        "CIs are moving-block bootstrap, %d-day blocks, %d draws. Funding "
        "regimes persist for weeks; an iid bootstrap would report an "
        "interval several times too narrow." % (BLOCK_DAYS, BOOT_DRAWS))
    return res


# ----------------------------------------------------------------------
# (c) BASIS — Kraken tickers, the ~05:20 UTC snapshot
# ----------------------------------------------------------------------

def _oi_unit(sym):
    """Units for openInterest / vol24h, which DIFFER BY PREFIX.

    PF_ and FF_ are linear (multi-collateral) and quote size in BASE
    units; PI_ and FI_ are inverse and quote size in $1 USD contracts.
    PF_XBTUSD OI 1,977 BTC is about $155M; PI_XBTUSD OI 3,530,220
    contracts is about $3.5M. Bare, the inverse looks 1,786x larger and
    is in fact 44x smaller.

    This is why liveness is a UNIT-FREE SIGN TEST (> 0) and never a
    threshold, and why every published size cell carries its unit.
    """
    if sym.startswith(("PI_", "FI_")):
        return "USD-contracts"
    base = sym.split("_")[1] if "_" in sym else ""
    for b in ("XBT", "ETH", "SOL", "LTC", "XRP"):
        if base.startswith(b):
            return "BTC" if b == "XBT" else b
    return base[:-3] if base.endswith("USD") else "base"


def _expiry_from_symbol(sym):
    """FF_XBTUSD_261225 -> 2026-12-25. Returns None for a perpetual."""
    parts = (sym or "").split("_")
    if len(parts) < 3:
        return None
    tail = parts[-1]
    if not (len(tail) == 6 and tail.isdigit()):
        return None
    try:
        return dt.date(2000 + int(tail[:2]), int(tail[2:4]), int(tail[4:6]))
    except ValueError:
        return None


def basis():
    """Annualised basis on DATED futures; perp premium reported separately.

    THE SNAPSHOT LAW (#243-#248) APPLIES: kraken_tickers is a CURRENT-ONLY
    endpoint sampled once daily at ~05:20 UTC. Every number here describes
    that one instant, not the day. It is never called "daily basis".

    ANNUALISATION NEEDS AN EXPIRY, so it is applied ONLY to dated futures
    (FF_ linear, FI_ inverse), where days-to-expiry is parsed from the
    symbol. A PERPETUAL HAS NO EXPIRY, so annualising its mark-index gap
    is meaningless -- the gap is a spot premium that funding resets, not a
    term structure. Perps are therefore reported as an UN-ANNUALISED
    premium, and the carry section above is where their term economics
    actually live.

    THE DEAD-INSTRUMENT TRAP. Kraken marks an instrument AT INDEX when it
    has no book. Such a row yields a basis of exactly 0.0000%, which reads
    as a precise measurement and is the absence of one. Measured
    2026-09-01: all 8 FI_ rows had openInterest 0, vol24h 0 and mark
    EXACTLY equal to index; all 9 FF_ rows were live. Liveness is enforced
    as a stated rule below, and excluded instruments are REPORTED, never
    silently dropped.
    """
    k = _read("kraken_tickers")
    out = {"dated": [], "perp": [], "excluded": [], "notes": []}
    if k is None or k.empty:
        out["notes"].append("kraken_tickers.csv absent")
        return out

    obs_days = k["timestamp"].dt.date.nunique() if "timestamp" in k else 0
    latest = k["timestamp"].max()
    snap = k[k["timestamp"] == latest].copy()
    observed = snap["observed_utc"].dropna().iloc[0] if snap["observed_utc"].notna().any() else "?"
    asof = pd.Timestamp(latest).date()

    for _, r in snap.iterrows():
        sym = r["symbol"]
        mark = pd.to_numeric(r.get("markPrice"), errors="coerce")
        index = pd.to_numeric(r.get("indexPrice"), errors="coerce")
        oi = pd.to_numeric(r.get("openInterest"), errors="coerce")
        vol = pd.to_numeric(r.get("vol24h"), errors="coerce")
        if not (mark == mark and index == index and index):
            continue
        prem = mark / index - 1.0
        exp = _expiry_from_symbol(sym)

        live = (oi == oi and oi > MIN_OI) and (vol == vol and vol > MIN_VOL24H)
        if exp is not None and not live:
            out["excluded"].append({
                "symbol": sym, "expiry": str(exp), "oi": oi, "vol24h": vol,
                "premium": prem,
                "why": "no book: openInterest=%s vol24h=%s, mark marked AT "
                       "index" % (oi, vol)})
            continue

        if exp is None:
            out["perp"].append({"symbol": sym, "premium": prem,
                                "oi": oi, "vol24h": vol,
                                "oi_unit": _oi_unit(sym)})
        else:
            days = (exp - asof).days
            if days <= 0:
                out["excluded"].append({
                    "symbol": sym, "expiry": str(exp), "oi": oi,
                    "vol24h": vol, "premium": prem,
                    "why": "expiry not in the future (%d days)" % days})
                continue
            out["dated"].append({
                "symbol": sym, "expiry": str(exp), "days": days,
                "oi_unit": _oi_unit(sym),
                "premium": prem,
                # ACT/365 simple, not compounded: matches the arithmetic
                # convention used for carry above so the two columns are
                # read on the same basis.
                "annualised": prem * (DAYS_PER_YEAR / days),
                "oi": oi, "vol24h": vol})

    out["dated"].sort(key=lambda x: (x["symbol"]))
    # TRACKED UNIVERSE FIRST. Sorting 274 perps by |premium| surfaces only
    # illiquid alts -- a real cross-section, but not the one this project
    # has any other measurement of. The three it tracks go first by name;
    # the cross-sectional shape is summarised below rather than by
    # printing the extremes as though they were representative.
    TRACKED = ("PF_XBTUSD", "PF_ETHUSD", "PF_SOLUSD")
    out["tracked_perp"] = [r for r in out["perp"] if r["symbol"] in TRACKED]
    out["tracked_perp"].sort(key=lambda x: TRACKED.index(x["symbol"]))
    prem = np.array([r["premium"] for r in out["perp"]
                     if r["premium"] == r["premium"]], dtype=float)
    out["perp_cross"] = ({
        "n": int(len(prem)),
        "median": float(np.median(prem)),
        "q25": float(np.percentile(prem, 25)),
        "q75": float(np.percentile(prem, 75)),
        "min": float(prem.min()), "max": float(prem.max())}
        if len(prem) else None)
    out["perp"].sort(key=lambda x: -abs(x["premium"]))
    out["as_of"] = str(asof)
    out["observed_utc"] = str(observed)
    out["obs_days"] = int(obs_days)
    out["notes"].append(
        "SNAPSHOT LAW (#243-#248): a point sample at ~05:20 UTC, not a "
        "daily average. Observed %s." % observed)
    out["notes"].append(
        "The archive holds %d distinct observation day(s), so every number "
        "here is a RAW SAMPLE with no uncertainty attached. It stays that "
        "way until the archive is deep enough to resample."
        % obs_days)
    out["notes"].append(
        "Annualisation is ACT/365 simple on dated futures only. Perpetuals "
        "have no expiry, so their mark-index gap is reported UN-annualised. "
        "Annualising it by the funding interval instead would print "
        "PF_XBTUSD at +79.5%/yr, PF_ETHUSD +116.8%/yr and PF_SOLUSD "
        "+17.8%/yr -- and +17.8% is an utterly ordinary crypto basis that "
        "would be accepted without a second look. PROHIBITED.")
    out["notes"].append(
        "openInterest and vol24h are in DIFFERENT UNITS by prefix: PF_/FF_ "
        "(linear) in base units, PI_/FI_ (inverse) in $1 USD contracts. "
        "Every size cell carries its unit, and liveness is a unit-free "
        "sign test (> 0), never a threshold.")
    out["notes"].append(
        "markPrice and indexPrice are both quote-currency for all four "
        "prefixes, so mark/index-1 is dimensionless and prefix-safe. The "
        "index is taken FROM THE ROW: FF_/FI_ and PF_/PI_ carry slightly "
        "different index values (0.2-1.0 bps apart), and substituting one "
        "for the other moves a 3-day annualised basis by ~8% relative.")
    out["notes"].append(
        "%d instrument(s) excluded as dead (no book; Kraken marks those AT "
        "index, which fabricates a 0.0000%% basis)." % len(out["excluded"]))
    return out


# ----------------------------------------------------------------------
# RENDER
# ----------------------------------------------------------------------

def _carry_rows(rows, venue, top=None):
    lines = []
    for r in sorted(rows, key=lambda x: -abs(x["mean_ann"]))[:top]:
        lo, hi = r["ci"]
        raw = " **RAW SAMPLE**" if lo != lo else ""
        extra = ("intervals %s" % r.get("intervals")) if "intervals" in r \
            else ("spacing %.3gh" % r.get("spacing_h", float("nan")))
        flag = " ⚠ mean driven by extremes" if r.get("skew_flag") else ""
        lines.append("| %s | %s | %s | %s | %s | %d | %s | %s%s |%s"
                     % (venue, r["symbol"], fmt_pct(r["mean_ann"]),
                        fmt_pct(r["median_ann"]), fmt_ci(lo, hi), r["n"],
                        r["span"], extra, flag, raw))
    return lines


def render(vrp, carry, bas, today):
    L = []
    L.append("")
    L.append("## %s" % today)
    L.append("")
    L.append("*Risk premia, measured from this project's own archives. "
             "**Not alpha, not signals, not tradeable by this operator.** "
             "Every number carries an interval or is labelled a RAW "
             "SAMPLE.*")
    L.append("")

    # ---- (a) VRP
    L.append("### (a) Variance risk premium — BTC, ETH")
    L.append("")
    L.append("> **STATUS: NOT COMPUTABLE.** A VRP compares implied vol at "
             "*t* with vol realised **after** *t*. The option-chain archive "
             "is too young for any observation to have a subsequent "
             "realisation.")
    L.append("")
    for n in vrp["notes"]:
        L.append("- %s" % n)
    L.append("")
    if vrp["rows"]:
        L.append("What *is* available today — **implied vs TRAILING "
                 "realised**, which is a contemporaneous spread and **not a "
                 "risk premium**:")
        L.append("")
        L.append("| ccy | as of | OI-wtd mark IV | trailing RV (~15d) | spread | "
                 "options in chain | put/call OI | label |")
        L.append("|---|---|---|---|---|---|---|---|")
        for r in vrp["rows"]:
            L.append("| %s | %s | %s | %s | %s | %s | %s | **RAW SAMPLE "
                     "(N=%d)** |"
                     % (r["ccy"], r["as_of"], fmt_pct(r["iv"], 2),
                        fmt_pct(r["rv_trailing"], 2),
                        fmt_pct(r["spread"], 2),
                        ("%d" % r["n_options"]) if r["n_options"] == r["n_options"]
                        else "n/a",
                        ("%.3f" % r["put_call_oi"]) if r["put_call_oi"] == r["put_call_oi"]
                        else "n/a",
                        r["n_iv"]))
        L.append("")

    # ---- (b) carry
    L.append("### (b) Perp carry yield — funding, annualised")
    L.append("")
    L.append("| venue | symbol | mean ann. | median ann. | 95% CI | n | "
             "span | interval |")
    L.append("|---|---|---|---|---|---|---|---|")
    L += _carry_rows(carry["binance"], "Binance*")
    L += _carry_rows(carry["kraken"], "Kraken")
    L += _carry_rows(carry["okx"], "OKX")
    L.append("")
    L.append("\\* Binance is the PRIMARY series (deepest archive). Kraken "
             "and OKX are shown beside it, not pooled with it — two feeds "
             "of the same quantity correlate at 0.37–0.72 (#220–#234), so "
             "one is not a proxy for another.")
    L.append("")
    L.append("**THE SPANS DIFFER, so these rows are NOT a venue "
             "comparison.** Binance reaches back to 2020 and Kraken about a "
             "year; a lower Kraken number is mostly a different era, not a "
             "cheaper venue. Only same-span rows may be read against each "
             "other.")
    L.append("")
    for n in carry["notes"]:
        L.append("- %s" % n)
    L.append("")

    # ---- (c) basis
    L.append("### (c) Basis — Kraken dated futures, ~05:20 UTC snapshot")
    L.append("")
    if bas.get("dated"):
        L.append("| instrument | expiry | days | premium | annualised | OI | "
                 "24h vol | label |")
        L.append("|---|---|---|---|---|---|---|---|")
        for r in bas["dated"]:
            L.append("| %s | %s | %d | %s | %s | %.4g %s | %.4g %s | "
                     "**RAW SAMPLE** |"
                     % (r["symbol"], r["expiry"], r["days"],
                        fmt_pct(r["premium"], 3), fmt_pct(r["annualised"], 2),
                        r["oi"], r["oi_unit"], r["vol24h"], r["oi_unit"]))
        L.append("")
    if bas.get("tracked_perp"):
        L.append("Perpetuals, tracked universe — **un-annualised** "
                 "mark-vs-index premium. A perpetual has no expiry, so a "
                 "term rate is undefined; its term economics are the "
                 "funding above.")
        L.append("")
        L.append("| instrument | premium | OI | 24h vol | label |")
        L.append("|---|---|---|---|---|")
        for r in bas["tracked_perp"]:
            L.append("| %s | %s | %.4g %s | %.4g %s | **RAW SAMPLE** |"
                     % (r["symbol"], fmt_pct(r["premium"], 4), r["oi"],
                        r["oi_unit"], r["vol24h"], r["oi_unit"]))
        L.append("")
    c = bas.get("perp_cross")
    if c:
        L.append("Across all %d live perpetuals in the same snapshot the "
                 "premium runs %s (25th) / %s (median) / %s (75th), min %s, "
                 "max %s. **The tails are illiquid alts, not a market-wide "
                 "signal** — they are given as the cross-sectional shape, "
                 "and this project has no other measurement of any of them."
                 % (c["n"], fmt_pct(c["q25"], 3), fmt_pct(c["median"], 3),
                    fmt_pct(c["q75"], 3), fmt_pct(c["min"], 3),
                    fmt_pct(c["max"], 3)))
        L.append("")
    if bas.get("excluded"):
        L.append("**Excluded as dead, reported not dropped** — Kraken marks "
                 "a bookless instrument AT index, fabricating a 0.0000% "
                 "basis:")
        L.append("")
        for r in bas["excluded"]:
            L.append("- `%s` (%s): %s" % (r["symbol"], r["expiry"], r["why"]))
        L.append("")
    for n in bas["notes"]:
        L.append("- %s" % n)
    L.append("")
    return "\n".join(L)


def monthly_summary(carry, bas, month):
    """The block the transparency post may include. Claims-safe by
    construction: it states measured premia and says outright that the
    project neither harvests nor recommends them."""
    prim = sorted(carry["binance"], key=lambda x: -abs(x["mean_ann"]))
    L = []
    L.append("**WHAT THE MARKET PAID, %s.** These are risk premia measured "
             "from our own archives — the fee professionals collect for "
             "bearing crash and balance-sheet risk. **This project does not "
             "harvest any of them, holds no position in any of them, and "
             "makes no recommendation about them.** They are published "
             "because measuring what we cannot trade is still worth doing."
             % month)
    L.append("")
    for r in prim[:3]:
        lo, hi = r["ci"]
        L.append("- **%s perp funding** (Binance, %s): %s a year, 95%% CI %s"
                 % (r["symbol"], r["span"], fmt_pct(r["mean_ann"]),
                    fmt_ci(lo, hi)))
    live = [x for x in bas.get("dated", []) if x["days"] > 0]
    if live:
        far = max(live, key=lambda x: x["days"])
        L.append("- **Term basis** (%s, %d days to expiry): %s annualised — "
                 "a RAW SAMPLE from the ~05:20 UTC snapshot, no interval."
                 % (far["symbol"], far["days"], fmt_pct(far["annualised"])))
    L.append("- **Variance risk premium: still NOT COMPUTABLE.** Our "
             "options archive is too young for any implied reading to have "
             "a realised counterpart yet.")
    return "\n".join(L)


# ----------------------------------------------------------------------

def build(today=None):
    today = today or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    vrp = variance_risk_premium()
    carry = perp_carry()
    bas = basis()
    table = render(vrp, carry, bas, today)
    summary = monthly_summary(carry, bas, today[:7])
    return {"vrp": vrp, "carry": carry, "basis": bas,
            "table": table, "summary": summary, "date": today}


HEADER = """# Premia — what the market paid

**A DESCRIPTIVE INSTRUMENT (#257).** No hypotheses, no verdicts, no pass
rules. It measures risk premia from this project's own archives and
publishes them.

**THESE ARE NOT ALPHA AND NOT SIGNALS.** A risk premium is a fee for a
risk actually borne — crash risk, balance-sheet risk — not a mispricing.
**Nothing measured here is tradeable by this operator**, and nothing here
enters the published signal path. The instrument exists to measure what
professionals harvest, on data we manufacture ourselves.

**Every number carries an uncertainty interval or is explicitly labelled a
RAW SAMPLE** (the #249 rule). There is no third category.

Appended dated, newest last. Nothing here is ever revised.
"""


def append_to_md(built, path=OUT_MD):
    fresh = not os.path.exists(path)
    with open(path, "a", encoding="utf-8") as fh:
        if fresh:
            fh.write(HEADER)
        fh.write(built["table"])
    return path


def dry_run():
    """Render without writing. Wired into the weekly audit."""
    b = build()
    problems = []
    t = b["table"]
    if "%" not in t:
        problems.append("table rendered no numbers")
    # THE #249 RULE, ENFORCED RATHER THAN TRUSTED: every table row that
    # carries a percentage must also carry an interval or the RAW SAMPLE
    # label. A number with neither is exactly what this instrument may
    # never publish.
    # Only DATA rows are checked. A markdown header row is the line
    # directly above the |---|---| separator, and ours legitimately reads
    # "95% CI" -- flagging that would make the check fail on its own
    # column title and teach the next reader to ignore it.
    lines = t.splitlines()
    header_idx = {i - 1 for i, ln in enumerate(lines) if ln.startswith("|---")}
    for i, line in enumerate(lines):
        if not line.startswith("|") or line.startswith("|---"):
            continue
        if i in header_idx or "%" not in line:
            continue
        if "RAW SAMPLE" in line or "[" in line:
            continue
        problems.append("unlabelled number: %s" % line[:90])
    for banned in ("edge", "alpha", "profitable", "opportunity"):
        if banned in b["summary"].lower():
            problems.append("summary makes a claim: %s" % banned)
    return {"ok": not problems, "problems": problems,
            "table_chars": len(t), "summary_chars": len(b["summary"]),
            "carry_symbols": (len(b["carry"]["binance"])
                              + len(b["carry"]["kraken"])
                              + len(b["carry"]["okx"])),
            "dated_basis": len(b["basis"]["dated"]),
            "excluded_basis": len(b["basis"]["excluded"]),
            "vrp_status": b["vrp"]["status"]}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="render and validate, write nothing")
    ap.add_argument("--append", action="store_true",
                    help="append the dated table to docs/premia.md")
    a = ap.parse_args()

    if a.dry_run:
        r = dry_run()
        print("PREMIA DRY RUN — %s" % ("OK" if r["ok"] else "PROBLEMS"))
        for k, v in r.items():
            if k != "problems":
                print("  %-16s %s" % (k, v))
        for p in r["problems"]:
            print("  PROBLEM: %s" % p)
        return 0 if r["ok"] else 1

    b = build()
    print(b["table"])
    print("\n" + "=" * 70 + "\nMONTHLY SUMMARY BLOCK\n" + "=" * 70)
    print(b["summary"])
    if a.append:
        print("\nappended -> %s" % append_to_md(b))
    return 0


if __name__ == "__main__":
    sys.exit(main())
