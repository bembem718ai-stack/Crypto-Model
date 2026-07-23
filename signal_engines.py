"""
signal_engines.py
==================
CONSOLIDATED: crypto_features.py + entry_point_model2.py + reddit_sentiment.py
+ adanos_sentiment.py, merged into one "data + scoring" module.

This file answers ONE question per section: "given a ticker, what's the raw
score/data for this step of the pipeline?" It does NOT orchestrate the
3-step order or make BUY/SELL decisions -- that's pipeline.py, which imports
this module.

SECTIONS (each is the original file's content, header preserved below):
  1. CRYPTO FEATURES     (Step 1 source) - Binance klines, squeeze pattern
  2. ENTRY POINT MODEL    (Step 3 source) - Yahoo daily technical + macro,
                           optional ML probability engine
  3. REDDIT SENTIMENT     (sentiment gate primitives: sentiment_gate(),
                           apply_gate_to_score() -- kept for the gate logic
                           and as historical reference; the Reddit fetchers
                           themselves are dead per the module's own notes)
  4. ADANOS SENTIMENT     (Step 2 source, the live data path) - calls
                           reddit_sentiment's sentiment_gate() directly
                           since it's in this same file now, no import needed

Requires: pip install requests vaderSentiment pandas numpy yfinance
(xgboost/scikit-learn only needed if you use use_ml=True in analyze())
"""

import os
import time
import argparse
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import requests


# ======================================================================
# SECTION 1 — crypto_features.py (Step 1: squeeze/pattern source)
# ======================================================================

"""
crypto_features.py
-------------------
Crypto-specific microstructure & derivatives features, pulled from
Binance's public Futures API (no API key required for these endpoints):

  - 4-hour momentum          (price-derived, computed from native 4h candles)
  - Funding rate             (perpetual futures funding, real historical data)
  - Long/short account ratio (proxy for crowd positioning / liquidation
                               pressure — see caveat below)
  - Hour-of-day (cyclical)   (cos/sin encoding of each bar's hour-of-day)

WHY INTRADAY: these features are all more meaningful at intraday
resolution than daily. Hour-of-day in particular is close to a constant
on a daily bar (there's only one "hour" per calendar day) — it only
carries real signal if the model is scoring bars throughout the day.
That's why this is a separate companion module operating on 4h candles,
rather than being bolted onto entry_point_model.py's daily pipeline.

CAVEAT on "liquidation ratio": Binance's free public REST API does not
expose historical liquidation VOLUME (only a live websocket stream of
new liquidation events, with no history endpoint). What IS available
historically for free is the "global long/short account ratio" — the
ratio of accounts net-long vs net-short. This is a reasonable PROXY for
liquidation pressure (heavily one-sided positioning is what usually gets
liquidated in a squeeze), but it is not the same as realized liquidation
volume. If you get access to a real liquidation data provider (e.g.
Coinglass), swap fetch_liquidation_ratio_stub()'s body for a real call —
everything downstream just expects a pd.Series indexed by timestamp, so
nothing else needs to change.

Requires: pip install requests pandas numpy
(xgboost/scikit-learn only needed if you use train_intraday_model_with_holdout)
"""



# ======================================================================
# BINANCE REGION CONFIGURATION
# ======================================================================
# The US blocks Binance.com. Set BINANCE_REGION=US in your environment
# to route all requests to Binance.US instead. Everything else
# (symbol format, intervals, response shape) is identical.
#
# Binance.US has no futures API (fapi), so in US mode klines are fetched
# from spot (/api/v3/klines). Spot vs futures price on BTC/ETH is
# negligible for squeeze/BB width detection.
#
# How to set it (PowerShell, once per terminal session):
#   $env:BINANCE_REGION="US"
# Or permanently in Windows: System Properties -> Environment Variables.

_REGION = os.environ.get("BINANCE_REGION", "GLOBAL").upper()

if _REGION == "US":
    BINANCE_REST_BASE = "https://api.binance.us"
    BINANCE_KLINES_PATH = "/api/v3/klines"
    BINANCE_WS_BASE = "wss://stream.binance.us:9443"
    BINANCE_CHART_REST = "https://api.binance.us"
else:
    BINANCE_REST_BASE = "https://fapi.binance.com"
    BINANCE_KLINES_PATH = "/fapi/v1/klines"
    BINANCE_WS_BASE = "wss://stream.binance.com:9443"
    BINANCE_CHART_REST = "https://api.binance.com"

# Keep old name as alias so anything that imported it directly still works
BINANCE_FAPI_BASE = BINANCE_REST_BASE


def _binance_get(path: str, params: dict, max_retries: int = 4) -> list:
    """
    GET a Binance endpoint with retry-with-backoff on transient network
    failures (timeouts, connection resets). Routes to Binance.US or
    Binance global depending on BINANCE_REGION env var.
    """
    url = f"{BINANCE_REST_BASE}{path}"
    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(url, params=params, timeout=20)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            last_error = e
            if attempt < max_retries:
                wait = 3 * attempt
                print(f"  [network] {path} attempt {attempt}/{max_retries} failed "
                      f"({type(e).__name__}); retrying in {wait}s...")
                time.sleep(wait)

    raise ConnectionError(
        f"Binance {'US' if _REGION == 'US' else 'global'} request to {path} failed "
        f"after {max_retries} attempts. Last error: {last_error}. "
        f"{'Make sure BINANCE_REGION=US is set and you have a US connection.' if _REGION == 'US' else ''}"
    )


def to_binance_symbol(ticker: str) -> str:
    """
    Converts a Yahoo-Finance-style crypto ticker (e.g. 'BTC-USD') into a
    Binance USDT-margined perpetual futures symbol (e.g. 'BTCUSDT') —
    that's what Binance's public derivatives endpoints are keyed on.
    """
    base = ticker.split("-")[0].upper()
    return f"{base}USDT"


# ======================================================================
# RAW DATA FETCHERS
# ======================================================================

def fetch_klines(symbol: str, interval: str = "4h", limit: int = 1000,
                  end_time_ms: int = None) -> pd.DataFrame:
    """Fetch OHLCV candles at a given interval (e.g. '4h', '1h', '1d')."""
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    if end_time_ms is not None:
        params["endTime"] = end_time_ms
    raw = _binance_get(BINANCE_KLINES_PATH, params)
    if not raw:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    df = pd.DataFrame(raw, columns=[
        "open_time", "Open", "High", "Low", "Close", "Volume",
        "close_time", "quote_volume", "trades", "taker_buy_base", "taker_buy_quote", "ignore",
    ])
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    df = df.set_index("open_time")
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        df[col] = df[col].astype(float)
    return df[["Open", "High", "Low", "Close", "Volume"]].sort_index()


def fetch_klines_paginated(symbol: str, interval: str = "4h", target_bars: int = 1000,
                            max_requests: int = 20, page_limit: int = 1500) -> pd.DataFrame:
    """
    Walks backward in time to pull more klines than a single call allows
    (Binance caps a single /fapi/v1/klines call at 1500 bars). Stops at
    `target_bars` or when an empty page signals the true start of
    available history for this symbol.
    """
    pages = []
    end_time_ms = None
    seen_earliest = None

    for i in range(max_requests):
        page = fetch_klines(symbol, interval=interval, limit=page_limit, end_time_ms=end_time_ms)
        if page.empty:
            print(f"  [klines] page {i + 1}: empty — reached the start of available history.")
            break

        pages.append(page)
        earliest = page.index.min()
        if seen_earliest is not None and earliest >= seen_earliest:
            break
        seen_earliest = earliest

        total_so_far = len(pd.concat(pages).drop_duplicates())
        print(f"  [klines] page {i + 1}: got {len(page)} bars back to {earliest} ({total_so_far} total so far)")

        if total_so_far >= target_bars:
            break
        end_time_ms = int(earliest.timestamp() * 1000) - 1

    if not pages:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    combined = pd.concat(pages).sort_index()
    return combined[~combined.index.duplicated(keep="first")]


def fetch_funding_rate(symbol: str, limit: int = 1000, end_time_ms: int = None) -> pd.Series:
    """Historical funding rate settlements (roughly every 8 hours). Real data."""
    params = {"symbol": symbol, "limit": limit}
    if end_time_ms is not None:
        params["endTime"] = end_time_ms
    raw = _binance_get("/fapi/v1/fundingRate", params)
    if not raw:
        return pd.Series(dtype=float)
    df = pd.DataFrame(raw)
    df["fundingTime"] = pd.to_datetime(df["fundingTime"], unit="ms")
    df["fundingRate"] = df["fundingRate"].astype(float)
    return df.set_index("fundingTime")["fundingRate"].sort_index()


def fetch_funding_rate_paginated(symbol: str, target_bars: int = 1000,
                                  max_requests: int = 20) -> pd.Series:
    """Paginated version of fetch_funding_rate — same walk-backward pattern."""
    pages = []
    end_time_ms = None
    seen_earliest = None

    for i in range(max_requests):
        page = fetch_funding_rate(symbol, limit=1000, end_time_ms=end_time_ms)
        if page.empty:
            print(f"  [funding rate] page {i + 1}: empty — reached the start of available history.")
            break

        pages.append(page)
        earliest = page.index.min()
        if seen_earliest is not None and earliest >= seen_earliest:
            break
        seen_earliest = earliest

        total_so_far = len(pd.concat(pages).drop_duplicates())
        print(f"  [funding rate] page {i + 1}: got {len(page)} rows back to {earliest} ({total_so_far} total so far)")

        if total_so_far >= target_bars:
            break
        end_time_ms = int(earliest.timestamp() * 1000) - 1

    if not pages:
        return pd.Series(dtype=float)
    combined = pd.concat(pages).sort_index()
    return combined[~combined.index.duplicated(keep="first")]


def fetch_long_short_ratio(symbol: str, period: str = "4h", limit: int = 500,
                            end_time_ms: int = None) -> pd.Series:
    """
    Global long/short ACCOUNT ratio — real historical data, used here as a
    proxy for crowd positioning / liquidation pressure. See module
    docstring caveat re: this vs. true liquidation volume.

    Binance's /futures/data/* statistics endpoints only return their most
    recent ~30 days by default when no endTime is given — this single call
    will silently cap out there. Use fetch_long_short_ratio_paginated()
    below to walk further back in time.
    """
    params = {"symbol": symbol, "period": period, "limit": limit}
    if end_time_ms is not None:
        params["endTime"] = end_time_ms
    raw = _binance_get("/futures/data/globalLongShortAccountRatio", params)
    df = pd.DataFrame(raw)
    if df.empty:
        return pd.Series(dtype=float)
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df["longShortRatio"] = df["longShortRatio"].astype(float)
    return df.set_index("timestamp")["longShortRatio"].sort_index()


def fetch_long_short_ratio_paginated(symbol: str, period: str = "4h",
                                      target_bars: int = 1000, max_requests: int = 20) -> pd.Series:
    """
    Walks backward in time, repeatedly calling fetch_long_short_ratio with
    an earlier `endTime` each time, to pull more history than a single
    call's default ~30-day window allows.

    Stops when either:
      - `target_bars` worth of history has been collected, or
      - Binance returns an empty page (the true start of its retained
        data for this symbol/period — going further back won't help).

    Prints a short progress line per page so you can see how far back it
    actually got, since Binance's real retention limit for this endpoint
    isn't publicly documented and may vary by symbol.
    """
    all_pages = []
    end_time_ms = None
    seen_earliest = None

    for i in range(max_requests):
        page = fetch_long_short_ratio(symbol, period=period, limit=500, end_time_ms=end_time_ms)
        if page.empty:
            print(f"  [long/short ratio] page {i + 1}: empty — reached the start of available history.")
            break

        all_pages.append(page)
        earliest = page.index.min()

        if seen_earliest is not None and earliest >= seen_earliest:
            # Binance stopped giving us anything new/older — bail out.
            break
        seen_earliest = earliest

        total_so_far = len(pd.concat(all_pages).drop_duplicates())
        print(f"  [long/short ratio] page {i + 1}: got {len(page)} bars back to {earliest} "
              f"({total_so_far} total so far)")

        if total_so_far >= target_bars:
            break

        # Next page ends right before this page's earliest bar.
        end_time_ms = int(earliest.timestamp() * 1000) - 1

    if not all_pages:
        return pd.Series(dtype=float)

    combined = pd.concat(all_pages).sort_index()
    combined = combined[~combined.index.duplicated(keep="first")]
    return combined


def fetch_liquidation_ratio_stub(symbol: str) -> pd.Series:
    """
    PLACEHOLDER for a real liquidation-VOLUME-based ratio (e.g. from
    Coinglass or another paid provider with historical liquidation data).
    Binance's free public REST API does not expose historical liquidation
    volume — only a live websocket stream of new liquidations, no history
    endpoint.

    Wire in a real provider here if you get access to one: return a
    pd.Series indexed by timestamp (same shape as fetch_long_short_ratio's
    output) and it drops straight into build_intraday_feature_set() in
    place of the long/short ratio proxy.
    """
    raise NotImplementedError(
        "No free historical liquidation-volume data source is wired up. "
        "build_intraday_feature_set() uses fetch_long_short_ratio() as the "
        "closest free proxy for now — replace this stub if/when you have a "
        "real liquidation data provider."
    )


def fetch_order_book_imbalance(symbol: str, limit: int = 100) -> float:
    """
    LIVE snapshot only: (bid_volume - ask_volume) / (bid_volume + ask_volume)
    over the top `limit` order book levels, at this instant.

    Binance's public REST API only exposes the CURRENT order book, not a
    historical time series of it — there's no free way to backtest this
    feature over the past. Use this for LIVE scoring only (e.g. in the
    webapp's "analyze now" flow); it has no place in historical training
    data unless you've been recording snapshots yourself over time.
    """
    raw = _binance_get("/fapi/v1/depth", {"symbol": symbol, "limit": limit})
    bid_vol = sum(float(qty) for _, qty in raw["bids"])
    ask_vol = sum(float(qty) for _, qty in raw["asks"])
    total = bid_vol + ask_vol
    if total == 0:
        return 0.0
    return (bid_vol - ask_vol) / total


# ======================================================================
# FEATURE ENGINEERING
# ======================================================================

def compute_momentum(close: pd.Series, bars: int = 1) -> pd.Series:
    """Rate-of-change over `bars` candles, at whatever resolution `close` is."""
    return close.pct_change(bars) * 100


def add_hour_of_day_cyclical(index: pd.DatetimeIndex) -> pd.DataFrame:
    """
    Cyclical (cos/sin) encoding of hour-of-day. Used instead of the raw
    hour number so the model sees hour 23 and hour 0 as close together (as
    they actually are on a 24-hour clock), rather than as far apart as the
    plain integers 23 and 0 would otherwise look.
    """
    hours = index.hour + index.minute / 60.0
    cos_hour = np.cos(2 * np.pi * hours / 24)
    sin_hour = np.sin(2 * np.pi * hours / 24)
    return pd.DataFrame({"HOUR_COS": cos_hour, "HOUR_SIN": sin_hour}, index=index)


# ======================================================================
# VOLATILITY CONTRACTION / "SQUEEZE" PATTERN DETECTION
# ======================================================================
# Unlike every other feature in this file, this is a genuine PATTERN
# (a shape across a window of bars), not a single-bar snapshot value.
# The idea: periods of unusually LOW volatility (price coiling into a
# tight range) tend to precede periods of HIGH volatility (a breakout in
# either direction) — a well-documented setup in technical analysis,
# unlike most single-value oscillators. Needs no new data source, since
# it's computed purely from Close prices you already have.

def _bollinger_band_width(close: pd.Series, period: int = 20, num_std: float = 2.0) -> pd.Series:
    """Bollinger Band width, normalized by the middle band (SMA) so it's
    comparable across different price levels."""
    sma = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = sma + num_std * std
    lower = sma - num_std * std
    return (upper - lower) / sma


def _rolling_percentile_rank(series: pd.Series, lookback: int = 120) -> pd.Series:
    """
    Where does the CURRENT value rank (0=lowest, 1=highest) within its own
    trailing `lookback` window? This is what makes "squeeze" relative to
    each asset's own recent behavior rather than an absolute threshold —
    a coin that's normally volatile and one that's normally calm need
    different absolute band-width cutoffs, but percentile rank adapts
    automatically.
    """
    def pct_rank(window):
        current = window[-1]
        if len(window) <= 1:
            return np.nan
        return (window < current).sum() / (len(window) - 1)

    return series.rolling(lookback).apply(pct_rank, raw=True)


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Average True Range — the standard volatility measure. True Range is the
    largest of: (high-low), |high-prev_close|, |low-prev_close|; ATR is its
    rolling average (Wilder's smoothing via EMA). Returned as a Series
    aligned to df's index; the last value is "current" volatility per bar.
    """
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def compute_exit_levels(entry_price: float, direction: str, atr: float,
                        stop_mult: float = 1.5, target_mult: float = 3.0) -> dict:
    """
    Turns a direction label + current ATR into a profit target and stop-loss.
    These are VOLATILITY BANDS, not price predictions: "if this move plays
    out at typical recent volatility, here's a target/stop with a fixed
    reward:risk ratio." They do NOT claim price WILL reach the target.

    Bullish (BUY/STRONG_BUY): target above entry, stop below.
    Bearish (SELL/STRONG_SELL): mirrored — target below, stop above.
    WATCH / INSUFFICIENT_DATA: no actionable level (returns applicable=False).

    Conviction scales the target: STRONG_* signals reach 1.33x further than
    a plain BUY/SELL, since higher conviction justifies a wider target. The
    stop distance is unchanged, so STRONG signals carry a higher R:R.
    """
    if atr is None or not (atr == atr) or atr <= 0:  # NaN-safe
        return {"applicable": False, "reason": "ATR unavailable"}

    conviction_scale = {"STRONG_BUY": 1.333, "BUY": 1.0,
                        "SELL": 1.0, "STRONG_SELL": 1.333}
    if direction not in conviction_scale:
        return {"applicable": False,
                "reason": f"No exit levels for '{direction}' (not an actionable signal)"}

    scaled_target_mult = target_mult * conviction_scale[direction]
    stop_dist = stop_mult * atr
    target_dist = scaled_target_mult * atr

    bullish = direction in ("STRONG_BUY", "BUY")
    if bullish:
        target = entry_price + target_dist
        stop = entry_price - stop_dist
    else:
        target = entry_price - target_dist
        stop = entry_price + stop_dist

    rr = target_dist / stop_dist if stop_dist else float("nan")
    return {
        "applicable": True,
        "direction": direction,
        "side": "long" if bullish else "short",
        "entry": round(entry_price, 2),
        "target": round(target, 2),
        "stop": round(stop, 2),
        "atr": round(atr, 2),
        "stop_mult": stop_mult,
        "target_mult": round(scaled_target_mult, 3),
        "risk_reward": round(rr, 2),
        "target_pct": round((target / entry_price - 1) * 100, 2),
        "stop_pct": round((stop / entry_price - 1) * 100, 2),
    }


def add_squeeze_features(df: pd.DataFrame, bb_period: int = 20, num_std: float = 2.0,
                          percentile_lookback: int = 120, squeeze_threshold: float = 0.2) -> pd.DataFrame:
    """
    Adds:
        BB_WIDTH_PCTL    — current band width's percentile rank (0-1)
                            against its own trailing history. Low = coiled.
        SQUEEZE_DURATION — consecutive bars spent below `squeeze_threshold`
                            percentile. Captures "how long has this been
                            coiling" — the idea being a longer squeeze
                            means more energy stored for the eventual move.
    """
    out = df.copy()
    bb_width = _bollinger_band_width(out["Close"], period=bb_period, num_std=num_std)
    bb_pctl = _rolling_percentile_rank(bb_width, lookback=percentile_lookback)

    out["BB_WIDTH_PCTL"] = bb_pctl

    is_squeeze = (bb_pctl < squeeze_threshold).astype(int)
    # Count consecutive squeeze bars: group by runs of the same value,
    # then count position within each run, zeroing out non-squeeze bars.
    run_id = (is_squeeze != is_squeeze.shift()).cumsum()
    duration = is_squeeze.groupby(run_id).cumcount() + 1
    out["SQUEEZE_DURATION"] = duration.where(is_squeeze == 1, 0)

    return out


def build_intraday_feature_set(ticker: str, interval: str = "4h", limit: int = 1000,
                                momentum_bars: int = 1) -> pd.DataFrame:
    """
    Assembles the full intraday microstructure feature set for one ticker,

    all aligned to the same `interval` (e.g. 4h) index:

        Close, Volume                    raw (kept for your own indicators)
        MOM_{interval}_{momentum_bars}    momentum at this bar resolution
        FUNDING_RATE                      forward-filled onto the interval grid
        LSR_RATIO                         forward-filled onto the interval grid
        HOUR_COS, HOUR_SIN                cyclical hour-of-day
        BB_WIDTH_PCTL                     volatility contraction percentile (low = coiled)
        SQUEEZE_DURATION                  consecutive bars spent in a squeeze

    Funding rate and long/short ratio update on their own schedules
    (funding roughly every 8h; long/short ratio at whatever `period` you
    fetch it at) so both are forward-filled onto the requested `interval`
    grid — each bar sees the most recent funding/positioning reading
    available AS OF that bar's timestamp, never a future one.

    All THREE network sources (klines, funding, long/short ratio) are
    pulled via pagination, each walking backward until it hits `limit`
    bars or its own true retention wall. Prints a summary at the end
    showing how much history each source actually provided — whichever
    is shortest is your real bottleneck.

    BB_WIDTH_PCTL/SQUEEZE_DURATION need no network call at all — they're
    computed purely from Close, so they're never the bottleneck.
    """
    symbol = to_binance_symbol(ticker)

    print(f"Fetching klines for {symbol}...")
    ohlcv = fetch_klines_paginated(symbol, interval=interval, target_bars=limit)
    print(f"Fetching funding rate for {symbol}...")
    funding = fetch_funding_rate_paginated(symbol, target_bars=limit)
    print(f"Fetching long/short ratio for {symbol}...")
    lsr = fetch_long_short_ratio_paginated(symbol, period=interval, target_bars=limit)

    print()
    print("Source history summary:")
    print(f"  klines         : {len(ohlcv)} bars"
          + (f", from {ohlcv.index.min()}" if not ohlcv.empty else ""))
    print(f"  funding rate   : {len(funding)} rows"
          + (f", from {funding.index.min()}" if not funding.empty else ""))
    print(f"  long/short rat.: {len(lsr)} rows"
          + (f", from {lsr.index.min()}" if not lsr.empty else ""))

    out = ohlcv.copy()
    mom_col = f"MOM_{interval}_{momentum_bars}"
    out[mom_col] = compute_momentum(out["Close"], bars=momentum_bars)

    out["FUNDING_RATE"] = funding.reindex(out.index, method="ffill")
    out["LSR_RATIO"] = lsr.reindex(out.index, method="ffill")

    hour_feats = add_hour_of_day_cyclical(out.index)
    out = out.join(hour_feats)

    out = add_squeeze_features(out)

    usable = out.dropna(subset=[mom_col, "FUNDING_RATE", "LSR_RATIO"])
    print(f"\nFinal usable rows after aligning all sources: {len(usable)}"
          + (f" (from {usable.index.min()} to {usable.index.max()})" if not usable.empty else ""))
    print()

    return out



def merge_daily_context_onto_intraday(
    df_intraday: pd.DataFrame,
    daily_result_df: pd.DataFrame,
    daily_cols=("technical_score", "final_score", "macro_score", "vix_score", "dxy_score"),
) -> pd.DataFrame:
    """
    Merges your existing DAILY technical_score/macro columns (from
    entry_point_model.run_model()) onto the intraday grid, so one model
    can see both daily-level context and finer-grained microstructure.
    Each intraday bar gets its own calendar day's daily score — no
    forward-looking leakage, since a given day's technical_score only
    ever reflects that day's own closing data or earlier, same as before.
    """
    daily_cols = [c for c in daily_cols if c in daily_result_df.columns]
    daily = daily_result_df[daily_cols].copy()
    daily.index = daily.index.date  # collapse to calendar date for the join

    out = df_intraday.copy()
    out["_date"] = out.index.date
    out = out.join(daily, on="_date")
    out = out.drop(columns=["_date"])
    return out


def build_intraday_feature_target(df_intraday: pd.DataFrame, lookahead_bars: int = 6,
                                   threshold_pct: float = 0.02, feature_cols=None):
    """
    Intraday analogue of entry_point_model.build_feature_target(), operating
    on bars (e.g. 4h candles) instead of trading days.

    lookahead_bars: how many bars ahead to average the close over
                    (e.g. 6 bars of 4h candles = 24 hours ahead)
    threshold_pct:  required forward average move to count as a positive label
    """
    if feature_cols is None:
        candidate_cols = [c for c in df_intraday.columns if c.startswith("MOM_")]
        candidate_cols += ["FUNDING_RATE", "LSR_RATIO", "HOUR_COS", "HOUR_SIN"]
        candidate_cols += [c for c in df_intraday.columns if c.endswith("_score")]
        feature_cols = [c for c in candidate_cols if c in df_intraday.columns]

    df = df_intraday.copy()
    future_close_avg = df["Close"].shift(-lookahead_bars).rolling(lookahead_bars).mean()
    df["Target"] = (future_close_avg > df["Close"] * (1 + threshold_pct)).astype(int)

    ml_df = df.dropna(subset=["Target"] + feature_cols)
    return ml_df[feature_cols], ml_df["Target"], feature_cols, ml_df


def train_intraday_model_with_holdout(df_intraday: pd.DataFrame, test_size: float = 0.2,
                                       xgb_params=None, lookahead_bars: int = 6,
                                       threshold_pct: float = 0.02, feature_cols=None):
    """
    Same idea as entry_point_model.train_ml_model_with_holdout(), but for
    the intraday microstructure feature set. Chronological split (the
    most recent `test_size` fraction of bars is the untouched holdout),
    trained and evaluated with the same honesty rules as the daily model.

    feature_cols: override which columns to train on. Useful for excluding
    LSR_RATIO (Binance's free long/short ratio history is capped at ~30
    days, which otherwise bottlenecks your entire dataset down to a
    couple hundred rows even though klines/funding have years of history).
    e.g. feature_cols=['MOM_4h_1', 'FUNDING_RATE', 'HOUR_COS', 'HOUR_SIN']

    CLASS IMBALANCE: breakout events are rare (often <10% of bars), so a
    model can get high accuracy just by always predicting "no breakout."
    scale_pos_weight is auto-computed from the TRAIN split's actual
    imbalance (never the test split — that would leak label information)
    and passed to XGBoost so it penalizes missing a real positive more
    heavily than a false alarm. Override it via xgb_params={'scale_pos_weight': ...}
    if you want to tune it yourself (e.g. via grid search).

    Because accuracy is misleading under imbalance, this also reports
    PR-AUC (average precision) — a metric that specifically reflects how
    well the model finds the rare positive class, unlike accuracy or even
    ROC AUC, both of which can look fine while recall on class 1 is near
    zero (as an all-negative classifier trivially proves).

    Requires: pip install xgboost scikit-learn
    """
    from xgboost import XGBClassifier
    from sklearn.metrics import (
        classification_report, accuracy_score, roc_auc_score, average_precision_score,
    )

    X, y, feature_cols, ml_df = build_intraday_feature_target(
        df_intraday, lookahead_bars=lookahead_bars, threshold_pct=threshold_pct,
        feature_cols=feature_cols,
    )

    split_idx = int(len(ml_df) * (1 - test_size))
    if split_idx < 10 or (len(ml_df) - split_idx) < 10:
        raise ValueError(
            f"Not enough bars ({len(ml_df)}) for a meaningful chronological "
            f"split with test_size={test_size}. Pull more history (larger "
            f"`limit` in build_intraday_feature_set) or lower test_size."
        )

    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]
    train_dates = ml_df.index[:split_idx]
    test_dates = ml_df.index[split_idx:]

    n_pos_train = int(y_train.sum())
    n_neg_train = len(y_train) - n_pos_train
    auto_scale_pos_weight = n_neg_train / max(n_pos_train, 1)

    default_params = dict(
        max_depth=5, learning_rate=0.1, n_estimators=100, eval_metric="logloss",
        scale_pos_weight=auto_scale_pos_weight,
    )
    params = {**default_params, **(xgb_params or {})}

    model = XGBClassifier(**params)
    model.fit(X_train, y_train)

    test_proba = model.predict_proba(X_test)[:, 1]
    test_pred = model.predict(X_test)

    report = classification_report(y_test, test_pred, zero_division=0)
    acc = accuracy_score(y_test, test_pred)
    try:
        auc = roc_auc_score(y_test, test_proba)
    except ValueError:
        auc = float("nan")
    try:
        pr_auc = average_precision_score(y_test, test_proba)
    except ValueError:
        pr_auc = float("nan")

    return {
        "model": model,
        "feature_cols": feature_cols,
        "lookahead_bars": lookahead_bars,
        "threshold_pct": threshold_pct,
        "train_dates": train_dates,
        "test_dates": test_dates,
        "X_train": X_train, "y_train": y_train,
        "X_test": X_test, "y_test": y_test,
        "test_confidence_pct": test_proba * 100,
        "test_predictions": test_pred,
        "accuracy": acc,
        "roc_auc": auc,
        "pr_auc": pr_auc,
        "scale_pos_weight_used": params["scale_pos_weight"],
        "train_positive_rate": n_pos_train / len(y_train),
        "test_positive_rate": float(y_test.mean()),
        "classification_report": report,
        "feature_importances": dict(zip(feature_cols, model.feature_importances_)),
    }


def analyze_thresholds(y_test, test_proba, candidate_thresholds=None):
    """
    The model's .predict() uses a fixed 0.5 cutoff by default, which has
    no relationship to your data's actual class balance or your real
    priorities (catching more real breakouts vs. fewer false alarms).

    This scans a range of probability cutoffs and reports precision/
    recall/F1 at each, plus which cutoff maximizes F1 — so you can pick
    an operating point deliberately instead of accepting XGBoost's
    default. Higher thresholds trade recall for precision (fewer, more
    confident signals); lower thresholds do the opposite.
    """
    from sklearn.metrics import precision_score, recall_score, f1_score

    if candidate_thresholds is None:
        candidate_thresholds = np.arange(0.1, 0.95, 0.05)

    rows = []
    for t in candidate_thresholds:
        pred = (test_proba >= t).astype(int)
        if pred.sum() == 0:
            precision = float("nan")
        else:
            precision = precision_score(y_test, pred, zero_division=0)
        recall = recall_score(y_test, pred, zero_division=0)
        f1 = f1_score(y_test, pred, zero_division=0)
        n_flagged = int(pred.sum())
        rows.append({
            "threshold": round(float(t), 2), "precision": precision, "recall": recall,
            "f1": f1, "n_flagged": n_flagged,
        })

    results = pd.DataFrame(rows)
    best_row = results.loc[results["f1"].idxmax()]
    return results, best_row


def print_intraday_holdout_report(holdout_result: dict, ticker: str):
    print("\n" + "=" * 60)
    print(f"  {ticker} — Intraday Holdout Evaluation (out-of-sample)")
    print("=" * 60)
    print(f"  Label       : {holdout_result['lookahead_bars']}-bar lookahead, "
          f"+{holdout_result['threshold_pct'] * 100:.1f}% threshold")
    print(f"  Train period: {holdout_result['train_dates'][0]} → "
          f"{holdout_result['train_dates'][-1]}  ({len(holdout_result['train_dates'])} bars, "
          f"{holdout_result['train_positive_rate']:.1%} positive)")
    print(f"  Test period : {holdout_result['test_dates'][0]} → "
          f"{holdout_result['test_dates'][-1]}  ({len(holdout_result['test_dates'])} bars, "
          f"{holdout_result['test_positive_rate']:.1%} positive)")
    print(f"  scale_pos_weight used: {holdout_result['scale_pos_weight_used']:.2f} "
          f"(auto-computed from train imbalance, corrects for rare breakouts)")
    print(f"  Accuracy    : {holdout_result['accuracy']:.3f}  "
          f"(CAUTION: misleading under class imbalance — see PR-AUC instead)")
    print(f"  ROC AUC     : {holdout_result['roc_auc']:.3f}")
    print(f"  PR-AUC      : {holdout_result['pr_auc']:.3f}  "
          f"(vs. baseline of {holdout_result['test_positive_rate']:.3f} for a random guesser — "
          f"this is the metric that actually reflects catching real breakouts)")
    print("-" * 60)
    print("  Feature importances:")
    for name, importance in sorted(holdout_result["feature_importances"].items(),
                                    key=lambda kv: kv[1], reverse=True):
        print(f"    {name:20s}: {importance:.4f}")
    print("-" * 60)
    print("  Decision threshold analysis (default cutoff is 0.5):")
    y_test = holdout_result["y_test"]
    test_proba = holdout_result["test_confidence_pct"] / 100
    threshold_table, best_row = analyze_thresholds(y_test, test_proba)
    print(threshold_table.to_string(index=False))
    print(f"\n  Best F1 at threshold {best_row['threshold']:.2f}: "
          f"precision={best_row['precision']:.3f}, recall={best_row['recall']:.3f}, "
          f"f1={best_row['f1']:.3f}, flags {int(best_row['n_flagged'])}/{len(y_test)} bars as breakouts")
    print("-" * 60)
    print(holdout_result["classification_report"])
    print("=" * 60 + "\n")


def walk_forward_validate(df_intraday: pd.DataFrame, n_folds: int = 5,
                           lookahead_bars: int = 6, threshold_pct: float = 0.02,
                           feature_cols=None, xgb_params=None,
                           min_test_positives: int = 15) -> pd.DataFrame:
    """
    Rolling-forward validation: instead of trusting one static 80/20
    holdout, splits the data into `n_folds` sequential EXPANDING-WINDOW
    folds (via sklearn's TimeSeriesSplit) - fold 1 trains on the earliest
    chunk and tests on the chunk right after it; fold 2 trains on
    everything up to a later point and tests on the next chunk; and so
    on. Every test fold is always strictly after its own training data,
    same no-leakage principle as the single holdout, but now you get
    N independent looks at different stretches of market history instead
    of one.

    Folds with fewer than `min_test_positives` real positive examples in
    their test slice are marked unreliable and excluded from the summary
    statistics - same reasoning as the grid search's reliability filter,
    applied per-fold here.

    scale_pos_weight is recomputed independently for EACH fold from that
    fold's own training data, since the positive rate can drift across
    market regimes.
    """
    from xgboost import XGBClassifier
    from sklearn.model_selection import TimeSeriesSplit
    from sklearn.metrics import roc_auc_score, average_precision_score

    X, y, feature_cols, ml_df = build_intraday_feature_target(
        df_intraday, lookahead_bars=lookahead_bars, threshold_pct=threshold_pct,
        feature_cols=feature_cols,
    )
    dates = ml_df.index

    tscv = TimeSeriesSplit(n_splits=n_folds)
    fold_rows = []

    for fold_i, (train_idx, test_idx) in enumerate(tscv.split(X), start=1):
        X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
        y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]
        train_start, train_end = dates[train_idx[0]], dates[train_idx[-1]]
        test_start, test_end = dates[test_idx[0]], dates[test_idx[-1]]

        n_pos_train = int(y_train.sum())
        n_pos_test = int(y_test.sum())
        n_neg_train = len(y_train) - n_pos_train

        base_row = {
            "fold": fold_i, "train_start": train_start, "train_end": train_end,
            "test_start": test_start, "test_end": test_end,
            "n_train": len(y_train), "n_test": len(y_test),
            "n_test_positive": n_pos_test,
            "test_positive_rate": float(y_test.mean()) if len(y_test) else float("nan"),
        }

        if n_pos_train < 5 or n_pos_test < min_test_positives:
            fold_rows.append({
                **base_row, "reliable": False,
                "pr_auc": float("nan"), "roc_auc": float("nan"), "relative_lift": float("nan"),
            })
            continue

        scale_pos_weight = n_neg_train / max(n_pos_train, 1)
        default_params = dict(max_depth=5, learning_rate=0.1, n_estimators=100,
                               eval_metric="logloss", scale_pos_weight=scale_pos_weight)
        params = {**default_params, **(xgb_params or {})}

        model = XGBClassifier(**params)
        model.fit(X_train, y_train)
        proba = model.predict_proba(X_test)[:, 1]

        try:
            roc = roc_auc_score(y_test, proba)
        except ValueError:
            roc = float("nan")
        try:
            pr_auc = average_precision_score(y_test, proba)
        except ValueError:
            pr_auc = float("nan")

        baseline = base_row["test_positive_rate"]
        relative_lift = pr_auc / baseline if baseline and baseline > 0 else float("nan")

        fold_rows.append({
            **base_row, "reliable": True,
            "pr_auc": pr_auc, "roc_auc": roc, "relative_lift": relative_lift,
        })

    return pd.DataFrame(fold_rows)


def print_walk_forward_report(fold_results: pd.DataFrame, ticker: str):
    print("\n" + "=" * 70)
    print(f"  {ticker} - Walk-Forward Validation ({len(fold_results)} folds)")
    print("=" * 70)
    display_cols = ["fold", "train_end", "test_start", "test_end", "n_test",
                     "n_test_positive", "test_positive_rate", "pr_auc", "roc_auc", "relative_lift"]
    print(fold_results[display_cols].to_string(index=False))

    reliable = fold_results[fold_results["reliable"]]
    unreliable_count = len(fold_results) - len(reliable)
    if unreliable_count:
        print(f"\n  {unreliable_count} fold(s) excluded from summary stats "
              f"(too few test-set positives to trust).")

    if reliable.empty:
        print("\n  No reliable folds at all - try fewer folds (more data per fold), "
              "a less rare label, or more total history.")
        print("=" * 70 + "\n")
        return

    print("\n" + "-" * 70)
    print("  SUMMARY ACROSS RELIABLE FOLDS")
    print("-" * 70)
    for metric in ["pr_auc", "roc_auc", "relative_lift"]:
        vals = reliable[metric]
        print(f"  {metric:<15}: mean={vals.mean():.4f}  std={vals.std():.4f}  "
              f"min={vals.min():.4f}  max={vals.max():.4f}")

    roc_vals = reliable["roc_auc"]
    above_chance = (roc_vals > 0.52).sum()
    print(f"\n  Folds with ROC AUC > 0.52: {above_chance}/{len(reliable)}")
    if above_chance == len(reliable):
        print("  -> Edge appears CONSISTENT across all tested time periods.")
    elif above_chance >= len(reliable) * 0.6:
        print("  -> Edge appears PARTIALLY consistent - present in most but not all periods.")
    else:
        print("  -> Edge appears INCONSISTENT - may be specific to one time period/regime "
              "rather than a durable pattern. Treat the single-holdout result with real skepticism.")
    print("=" * 70 + "\n")


# ======================================================================
# SECTION 2 — entry_point_model2.py (Step 3: technical + macro source)
# ======================================================================

"""
entry_point_model.py
=====================
Single-file version of the Technical + Macro Entry Point Model.
(Combined from config.py / indicators.py / macro.py / engine.py / main.py /
backtest.py for easier grid-search / experimentation.)

Usage:
    python entry_point_model.py analyze BTC-USD
    python entry_point_model.py analyze ETH-USD --save eth_signals.csv
    python entry_point_model.py backtest BTC-USD --hold-days 10
    python entry_point_model.py train BTC-USD --test-size 0.2
    python entry_point_model.py smoketest        # offline, no network needed
"""




# ======================================================================
# CONFIG — every tunable weight/threshold/period lives here
# ======================================================================

LOOKBACK_PERIOD = "2y"
INTERVAL = "1d"

MACRO_TICKERS = {
    "VIX": "^VIX",
    "DXY": "DX-Y.NYB",
}

# --- Technical indicator periods ---
RSI_PERIODS = [5, 10, 15]
ROC_PERIOD = 10
MOM_PERIOD = 10
CCI_PERIOD = 20
WR_PERIOD = 14
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9
SMA_PERIODS = [5, 10, 20]
EMA_PERIODS = [5, 10, 20]
VWMA_PERIOD = 20
NVI_SMA_PERIOD = 255
CMF_PERIOD = 20
MFI_PERIOD = 14

# --- Technical sub-score weights ---
TECH_WEIGHTS = {
    "rsi": 0.20,
    "momentum": 0.12,
    "cci": 0.10,
    "williams_r": 0.10,
    "macd": 0.18,
    "ma_stack": 0.15,
    "vwma": 0.08,
    "nvi": 0.07,
}

RSI_OVERSOLD, RSI_OVERBOUGHT = 30, 70
CCI_OVERSOLD, CCI_OVERBOUGHT = -100, 100
WR_OVERSOLD, WR_OVERBOUGHT = -80, -20

# --- Macro regime thresholds ---
# Crypto-specific note: VIX still works as a broad "risk appetite" gauge
# (crypto tends to sell off alongside equities in risk-off shocks), and a
# strengthening dollar (DXY) has historically been a headwind for crypto
# as a risk asset. TNX/Gold/Oil are disabled below since they're weaker,
# noisier signals for crypto specifically.
VIX_LOW, VIX_HIGH, VIX_EXTREME = 15, 25, 35

DXY_ROC_LOOKBACK = 20
DXY_ROC_STRONG = 2.0

# Weights re-normalized to sum to 1.0 across just these two filters.
# VIX kept as the heavier weight since it's the broader risk-on/risk-off
# signal; tune this ratio once you've backtested against your crypto data.
MACRO_WEIGHTS = {
    "vix": 0.65,
    "dxy": 0.35,
}

# --- Final decision thresholds (0-100 scale) ---
STRONG_BUY_THRESHOLD = 75
BUY_THRESHOLD = 60
WATCH_THRESHOLD = 45
EXTREME_FEAR_MIN_SCORE = 80


# ======================================================================
# INDICATORS — pure calculation layer
# ======================================================================


def _rsi(close: pd.Series, period: int) -> pd.Series:
    """Wilder's RSI."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.where(avg_loss != 0, 100)
    return rsi


def _cci(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    tp = (high + low + close) / 3
    sma_tp = tp.rolling(period).mean()
    mean_dev = tp.rolling(period).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    cci = (tp - sma_tp) / (0.015 * mean_dev.replace(0, np.nan))
    return cci


def _williams_r(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    highest_high = high.rolling(period).max()
    lowest_low = low.rolling(period).min()
    wr = (highest_high - close) / (highest_high - lowest_low).replace(0, np.nan) * -100
    return wr


def _macd(close: pd.Series, fast: int, slow: int, signal: int):
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def _vwma(close: pd.Series, volume: pd.Series, period: int) -> pd.Series:
    return (close * volume).rolling(period).sum() / volume.rolling(period).sum()


def _nvi(close: pd.Series, volume: pd.Series) -> pd.Series:
    """Negative Volume Index. Starts at 1000; only updates on days where
    volume falls versus the prior day."""
    nvi = pd.Series(index=close.index, dtype=float)
    nvi.iloc[0] = 1000.0
    pct_change = close.pct_change()
    vol_change = volume.diff()

    for i in range(1, len(close)):
        if vol_change.iloc[i] < 0:
            nvi.iloc[i] = nvi.iloc[i - 1] * (1 + pct_change.iloc[i])
        else:
            nvi.iloc[i] = nvi.iloc[i - 1]
    return nvi


def _obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """
    On-Balance Volume. Running cumulative total: add the day's volume when
    price closes higher than the prior close, subtract it when price
    closes lower, leave it unchanged on an unchanged close. Starts at 0.
    """
    direction = np.sign(close.diff()).fillna(0)
    return (direction * volume).cumsum()


def _cmf(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series, period: int) -> pd.Series:
    """
    Chaikin Money Flow. Volume-weighted average, over `period` days, of the
    Money Flow Multiplier — a measure of where the close sits within each
    day's high-low range (+1 = closed at the high, -1 = closed at the low).
    """
    hl_range = (high - low).replace(0, np.nan)
    mf_multiplier = ((close - low) - (high - close)) / hl_range
    mf_volume = mf_multiplier * volume
    return mf_volume.rolling(period).sum() / volume.rolling(period).sum()


def _mfi(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series, period: int) -> pd.Series:
    """
    Money Flow Index. Volume-weighted RSI: typical price x volume gives
    "raw money flow" for each day, which is bucketed into positive/negative
    flow based on whether typical price rose or fell versus the prior day,
    then the ratio of the two rolling sums is scaled 0-100 like RSI.
    """
    tp = (high + low + close) / 3
    raw_money_flow = tp * volume

    tp_change = tp.diff()
    positive_flow = raw_money_flow.where(tp_change > 0, 0.0)
    negative_flow = raw_money_flow.where(tp_change < 0, 0.0)

    positive_sum = positive_flow.rolling(period).sum()
    negative_sum = negative_flow.rolling(period).sum()

    money_ratio = positive_sum / negative_sum.replace(0, np.nan)
    mfi = 100 - (100 / (1 + money_ratio))
    mfi = mfi.where(negative_sum != 0, 100)
    return mfi


def add_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of df (OHLCV) with every indicator column appended."""
    out = df.copy()
    close, high, low, volume = out["Close"], out["High"], out["Low"], out["Volume"]

    for p in RSI_PERIODS:
        out[f"RSI_{p}"] = _rsi(close, p)

    out[f"ROC_{ROC_PERIOD}"] = close.pct_change(ROC_PERIOD) * 100
    out[f"MOM_{MOM_PERIOD}"] = close.diff(MOM_PERIOD)

    out[f"CCI_{CCI_PERIOD}"] = _cci(high, low, close, CCI_PERIOD)
    out[f"WR_{WR_PERIOD}"] = _williams_r(high, low, close, WR_PERIOD)

    macd_line, signal_line, hist = _macd(close, MACD_FAST, MACD_SLOW, MACD_SIGNAL)
    out["MACD"] = macd_line
    out["MACD_SIGNAL"] = signal_line
    out["MACD_HIST"] = hist

    for p in SMA_PERIODS:
        out[f"SMA_{p}"] = close.rolling(p).mean()
    for p in EMA_PERIODS:
        out[f"EMA_{p}"] = close.ewm(span=p, adjust=False).mean()

    out[f"VWMA_{VWMA_PERIOD}"] = _vwma(close, volume, VWMA_PERIOD)

    out["NVI"] = _nvi(close, volume)
    out["NVI_SIGNAL"] = out["NVI"].rolling(NVI_SMA_PERIOD, min_periods=30).mean()

    out["OBV"] = _obv(close, volume)
    out[f"CMF_{CMF_PERIOD}"] = _cmf(high, low, close, volume, CMF_PERIOD)
    out[f"MFI_{MFI_PERIOD}"] = _mfi(high, low, close, volume, MFI_PERIOD)


    return out


# ======================================================================
# MACRO — converts VIX/TNX/DXY/Gold/Oil into a regime multiplier
# ======================================================================

def _roc(series: pd.Series, lookback: int) -> pd.Series:
    return series.pct_change(lookback) * 100


def compute_macro_scores(macro_data: dict) -> pd.DataFrame:
    """
    macro_data: dict of {"VIX": df, "DXY": df}
    Each df must have a "Close" column indexed by date.
    """
    vix = macro_data["VIX"]["Close"]
    dxy = macro_data["DXY"]["Close"]

    result = pd.DataFrame(index=vix.index)

    def vix_to_score(v):
        if pd.isna(v):
            return np.nan
        if v <= VIX_LOW:
            return 1.0
        if v >= VIX_EXTREME:
            return -1.0
        if v <= VIX_HIGH:
            return 1.0 - (v - VIX_LOW) / (VIX_HIGH - VIX_LOW)
        return -(v - VIX_HIGH) / (VIX_EXTREME - VIX_HIGH)

    result["vix_level"] = vix
    result["vix_score"] = vix.apply(vix_to_score)

    dxy_roc = _roc(dxy, DXY_ROC_LOOKBACK)
    result["dxy_score"] = (-dxy_roc / DXY_ROC_STRONG).clip(-1, 1)

    weights = MACRO_WEIGHTS
    composite = (
        result["vix_score"] * weights["vix"]
        + result["dxy_score"] * weights["dxy"]
    )
    result["macro_composite"] = composite
    result["macro_score"] = (composite + 1) * 50

    result["macro_multiplier"] = 1.0 + (composite * 0.4) - np.where(composite < 0, composite * -0.15, 0)
    result["macro_multiplier"] = result["macro_multiplier"].clip(0.55, 1.15)

    return result


def align_macro_to_stock(stock_index: pd.DatetimeIndex, macro_df: pd.DataFrame) -> pd.DataFrame:
    """Reindex macro data onto the stock's trading calendar, forward-filling gaps."""
    return macro_df.reindex(stock_index, method="ffill")


# ======================================================================
# ENGINE — combines technicals + macro into scores and decisions
# ======================================================================

def _scale(series: pd.Series, lo, hi) -> pd.Series:
    """Map <=lo -> +1 (bullish/oversold), >=hi -> -1 (bearish/overbought)."""
    span = hi - lo
    scaled = 1 - 2 * (series - lo) / span
    return scaled.clip(-1, 1)


def _rsi_subscore(df: pd.DataFrame) -> pd.Series:
    cols = [f"RSI_{p}" for p in RSI_PERIODS]
    blended = df[cols].mean(axis=1)
    return _scale(blended, RSI_OVERSOLD, RSI_OVERBOUGHT)


def _momentum_subscore(df: pd.DataFrame) -> pd.Series:
    roc = df[f"ROC_{ROC_PERIOD}"]
    mom = df[f"MOM_{MOM_PERIOD}"]
    roc_z = (roc / roc.rolling(60, min_periods=20).std()).clip(-2, 2) / 2
    mom_z = (mom / mom.rolling(60, min_periods=20).std()).clip(-2, 2) / 2
    return ((roc_z + mom_z) / 2).clip(-1, 1)


def _cci_subscore(df: pd.DataFrame) -> pd.Series:
    cci = df[f"CCI_{CCI_PERIOD}"]
    return _scale(cci, CCI_OVERSOLD, CCI_OVERBOUGHT)


def _williams_subscore(df: pd.DataFrame) -> pd.Series:
    wr = df[f"WR_{WR_PERIOD}"]
    return _scale(wr, WR_OVERSOLD, WR_OVERBOUGHT)


def _macd_subscore(df: pd.DataFrame) -> pd.Series:
    hist = df["MACD_HIST"]
    hist_std = hist.rolling(60, min_periods=20).std().replace(0, np.nan)
    return (hist / hist_std).clip(-1.5, 1.5) / 1.5


def _ma_stack_subscore(df: pd.DataFrame) -> pd.Series:
    close = df["Close"]
    ma_cols = [f"SMA_{p}" for p in SMA_PERIODS] + [f"EMA_{p}" for p in EMA_PERIODS]
    above = pd.concat([(close > df[c]).astype(int) for c in ma_cols], axis=1)
    frac_above = above.mean(axis=1)
    return frac_above * 2 - 1


def _vwma_subscore(df: pd.DataFrame) -> pd.Series:
    vwma = df[f"VWMA_{VWMA_PERIOD}"]
    pct_diff = (df["Close"] - vwma) / vwma
    return (pct_diff / 0.03).clip(-1, 1)


def _nvi_subscore(df: pd.DataFrame) -> pd.Series:
    nvi, sig = df["NVI"], df["NVI_SIGNAL"]
    rel = (nvi - sig) / sig.replace(0, np.nan)
    return (rel / 0.02).clip(-1, 1)


def _ranked_context_score(series: pd.Series, lookback: int = 60) -> pd.Series:
    """Convert a directional subscore into a relative-strength score versus
    its own recent history. A value near +1 means the current signal is
    unusually bullish compared with the prior `lookback` bars; near -1 means
    unusually bearish.
    """
    min_periods = max(10, lookback // 2)
    rolling_rank = series.rolling(lookback, min_periods=min_periods).rank(pct=True, method="average")
    return ((rolling_rank - 0.5) * 2).clip(-1, 1)


def compute_technical_score(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["sub_rsi"] = _rsi_subscore(out)
    out["sub_momentum"] = _momentum_subscore(out)
    out["sub_cci"] = _cci_subscore(out)
    out["sub_williams_r"] = _williams_subscore(out)
    out["sub_macd"] = _macd_subscore(out)
    out["sub_ma_stack"] = _ma_stack_subscore(out)
    out["sub_vwma"] = _vwma_subscore(out)
    out["sub_nvi"] = _nvi_subscore(out)

    # Convert each subscore from a fixed-threshold signal into a relative
    # signal strength score versus the recent history. This makes the
    # composite more adaptive across different market regimes while leaving
    # the underlying indicators and their formulas intact.
    subscore_columns = [
        "sub_rsi", "sub_momentum", "sub_cci", "sub_williams_r",
        "sub_macd", "sub_ma_stack", "sub_vwma", "sub_nvi",
    ]
    ranked_subscores = {
        col: _ranked_context_score(out[col], lookback=60)
        for col in subscore_columns
    }

    w = TECH_WEIGHTS
    weighted_mean = sum(
        ranked_subscores[col] * w[col.split("sub_")[1].replace("williams_r", "williams_r")]
        for col in subscore_columns
    )

    # Agreement term: if several indicators are simultaneously extreme in the
    # same direction, amplify the signal; if the pack is mixed, dampen it.
    agreement = pd.concat(ranked_subscores.values(), axis=1).abs().mean(axis=1)
    composite = weighted_mean * (0.6 + 0.4 * agreement)

    out["technical_composite"] = composite.clip(-1, 1)
    out["technical_score"] = (out["technical_composite"] + 1) * 50
    return out


def _decide_row(row) -> str:
    score = row.get("final_score")
    vix_level = row.get("vix_level")

    if pd.isna(score):
        return "INSUFFICIENT_DATA"

    extreme_fear = pd.notna(vix_level) and vix_level >= VIX_EXTREME
    strong_buy_bar = EXTREME_FEAR_MIN_SCORE if extreme_fear else STRONG_BUY_THRESHOLD
    buy_bar = EXTREME_FEAR_MIN_SCORE - 10 if extreme_fear else BUY_THRESHOLD

    if score >= strong_buy_bar:
        return "STRONG_BUY"
    if score >= buy_bar:
        return "BUY"
    if score >= WATCH_THRESHOLD:
        return "WATCH"
    return "AVOID"


def combine_with_macro(tech_df: pd.DataFrame, macro_df: pd.DataFrame) -> pd.DataFrame:
    out = tech_df.join(macro_df, how="left")
    out["final_score"] = (out["technical_score"] * out["macro_multiplier"]).clip(0, 100)
    out["decision"] = out.apply(_decide_row, axis=1)
    return out


def run_model(stock_df_with_indicators: pd.DataFrame, macro_scores_aligned: pd.DataFrame) -> pd.DataFrame:
    tech = compute_technical_score(stock_df_with_indicators)
    combined = combine_with_macro(tech, macro_scores_aligned)
    return combined


# ======================================================================
# ML PROBABILISTIC ENGINE — XGBoost-based confidence score (optional,
# runs on top of / instead of the manual technical_score)
# ======================================================================

def run_ml_probabilistic_engine(df_with_features):
    """
    Replaces the manual scoring math with a true Machine Learning engine
    that outputs a probability-based confidence score.

    Feature set: any RSI_*, SMA_* column, plus every *_score column
    (the -1..+1 technical sub-scores and macro filter scores already
    computed by compute_technical_score / compute_macro_scores).

    Target: 1 if the average Close over the *next* 10 trading days is
    at least 2% above today's Close, 0 otherwise (a "does this lead to
    a decent move" label, not next-day direction).

    NOTE: This trains and scores on the same data (no train/test split
    applied here, though train_test_split is imported and ready for you
    to wire in for a proper holdout evaluation before trusting the
    probabilities out of sample).

    Requires: pip install xgboost scikit-learn
    (imported lazily here so the rest of the script works without them
    unless you actually use --ml).
    """
    from xgboost import XGBClassifier
    # train_test_split is available for you to wire in a proper holdout split:
    from sklearn.model_selection import train_test_split  # noqa: F401

    # 1. Define ML features (technical and macro data columns)
    feature_cols = [
        col for col in df_with_features.columns
        if col.startswith('RSI_') or col.startswith('SMA_') or col.endswith('_score')
    ]

    # 2. Create the target label (look-ahead window)
    # 1 = price average in next 10 days goes up by 2%, 0 = otherwise
    future_close_avg = df_with_features['Close'].shift(-10).rolling(10).mean()
    df_with_features['Target'] = (future_close_avg > df_with_features['Close'] * 1.02).astype(int)

    # Drop rows without future data or unfilled feature NaNs
    ml_df = df_with_features.dropna(subset=['Target'] + feature_cols)

    X = ml_df[feature_cols]
    y = ml_df['Target']

    # 3. Initialize and train the classifier
    model = XGBClassifier(max_depth=5, learning_rate=0.1, n_estimators=100, eval_metric='logloss')
    model.fit(X, y)

    # 4. Get the probability score
    # predict_proba returns a matrix: [Probability of 0, Probability of 1]
    probabilities = model.predict_proba(X)

    # Grab the confidence score for the "Up" direction (Class 1)
    df_with_features.loc[ml_df.index, 'ai_confidence_score'] = probabilities[:, 1] * 100

    return df_with_features


def build_feature_target(df_with_features, feature_cols=None, lookahead_days=10, threshold_pct=0.02):
    """
    Shared helper: builds the feature matrix X and target vector y from a
    dataframe that already has indicators/scores computed. Used by both
    the holdout trainer below and grid_search.py, so the feature/target
    definition only lives in one place.

    lookahead_days: how many trading days ahead to average the close over
                    when checking for a "breakout" move.
    threshold_pct:  how big that average forward move needs to be (as a
                    fraction, e.g. 0.02 = 2%) to count as a positive label.

    Both are tunable — see grid_search.py's LABEL_GRID for searching over
    combinations of these alongside the model's hyperparameters.
    """
    if feature_cols is None:
        # Exclude the pipeline's OWN output scores from the feature set —
        # final_score/technical_score/macro_score are what the ML is meant
        # to be an INDEPENDENT check on, so feeding them in would be
        # circular. Keep only the raw sub-scores and indicators.
        _circular = {"final_score", "technical_score", "macro_score", "macro_multiplier"}
        base_cols = [
            col for col in df_with_features.columns
            if (col.startswith('RSI_') or col.startswith('SMA_') or col.endswith('_score'))
            and col not in _circular
        ]
        # Explicitly add the volume-based indicators — their names don't
        # match the RSI_/SMA_/_score patterns above, so they'd otherwise
        # be silently excluded from the ML feature set.
        volume_cols = [
            c for c in ['OBV', f'CMF_{CMF_PERIOD}', f'MFI_{MFI_PERIOD}']
            if c in df_with_features.columns
        ]
        feature_cols = base_cols + volume_cols

    df = df_with_features.copy()
    future_close_avg = df['Close'].shift(-lookahead_days).rolling(lookahead_days).mean()
    df['Target'] = (future_close_avg > df['Close'] * (1 + threshold_pct)).astype(int)

    ml_df = df.dropna(subset=['Target'] + feature_cols)
    return ml_df[feature_cols], ml_df['Target'], feature_cols, ml_df


def train_ml_model_with_holdout(df_with_features, test_size=0.2, xgb_params=None,
                                 lookahead_days=10, threshold_pct=0.02):
    """
    The "actually train it properly" version of run_ml_probabilistic_engine.

    Splits chronologically (NOT sklearn's random train_test_split — that
    would shuffle rows across time and leak information, since rolling
    indicators on nearby days overlap). The last `test_size` fraction of
    rows becomes the holdout; everything before it is training data.

    Returns a dict with the fitted model, both splits, holdout
    probabilities, and a classification_report computed ONLY on the
    holdout — this is your honest, out-of-sample confidence check.

    Requires: pip install xgboost scikit-learn
    """
    from xgboost import XGBClassifier
    from sklearn.metrics import classification_report, accuracy_score, roc_auc_score

    X, y, feature_cols, ml_df = build_feature_target(
        df_with_features, lookahead_days=lookahead_days, threshold_pct=threshold_pct
    )

    split_idx = int(len(ml_df) * (1 - test_size))
    if split_idx < 10 or (len(ml_df) - split_idx) < 10:
        raise ValueError(
            f"Not enough rows ({len(ml_df)}) to make a meaningful chronological "
            f"split with test_size={test_size}. Pull more history or lower test_size."
        )

    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]
    train_dates = ml_df.index[:split_idx]
    test_dates = ml_df.index[split_idx:]

    params = xgb_params or dict(max_depth=5, learning_rate=0.1, n_estimators=100, eval_metric='logloss')
    model = XGBClassifier(**params)
    model.fit(X_train, y_train)

    test_proba = model.predict_proba(X_test)[:, 1]
    test_pred = model.predict(X_test)

    report = classification_report(y_test, test_pred, zero_division=0)
    acc = accuracy_score(y_test, test_pred)
    try:
        auc = roc_auc_score(y_test, test_proba)
    except ValueError:
        auc = float("nan")  # happens if the holdout has only one class present

    return {
        "model": model,
        "feature_cols": feature_cols,
        "lookahead_days": lookahead_days,
        "threshold_pct": threshold_pct,
        "train_dates": train_dates,
        "test_dates": test_dates,
        "X_train": X_train, "y_train": y_train,
        "X_test": X_test, "y_test": y_test,
        "test_confidence_pct": test_proba * 100,
        "test_predictions": test_pred,
        "accuracy": acc,
        "roc_auc": auc,
        "classification_report": report,
    }


def print_holdout_report(holdout_result: dict, ticker: str):
    print("\n" + "=" * 60)
    print(f"  {ticker} — Holdout Evaluation (out-of-sample)")
    print("=" * 60)
    print(f"  Label       : {holdout_result.get('lookahead_days', 10)}-day lookahead, "
          f"+{holdout_result.get('threshold_pct', 0.02) * 100:.1f}% threshold")
    print(f"  Train period: {holdout_result['train_dates'][0].date()} → "
          f"{holdout_result['train_dates'][-1].date()}  ({len(holdout_result['train_dates'])} rows)")
    print(f"  Test period : {holdout_result['test_dates'][0].date()} → "
          f"{holdout_result['test_dates'][-1].date()}  ({len(holdout_result['test_dates'])} rows)")
    print(f"  Accuracy    : {holdout_result['accuracy']:.3f}")
    print(f"  ROC AUC     : {holdout_result['roc_auc']:.3f}")
    print("-" * 60)
    print(holdout_result["classification_report"])
    print("=" * 60 + "\n")


# ======================================================================
# DATA FETCHING + ANALYSIS PIPELINE
# ======================================================================

def fetch_data(ticker: str, period: str, interval: str, max_retries: int = 3) -> pd.DataFrame:
    """
    Pull OHLCV data from Yahoo Finance via yfinance.

    Yahoo's API is occasionally flaky and throws a misleading "possibly
    delisted; no price data found" error on perfectly valid, active
    tickers (this happens even for things like ^VIX). Rather than fail
    the whole run on one transient hiccup, retry a few times with a short
    backoff before giving up for real.
    """
    import yfinance as yf

    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            df = yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=True)
            if not df.empty:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                return df
            last_error = "empty dataframe returned"
        except Exception as e:  # noqa: BLE001 - deliberately broad, this is a network call
            last_error = str(e)

        if attempt < max_retries:
            wait = 2 * attempt  # 2s, 4s, 6s...
            print(f"  [{ticker}] fetch attempt {attempt}/{max_retries} failed ({last_error}); "
                  f"retrying in {wait}s...")
            time.sleep(wait)

    raise ValueError(
        f"No data returned for {ticker} after {max_retries} attempts. "
        f"Last error: {last_error}. This is usually a transient Yahoo Finance "
        f"issue (try `pip install --upgrade yfinance` and rerun) rather than "
        f"an actually invalid/delisted symbol."
    )


def fetch_macro(period: str, interval: str) -> dict:
    macro_data = {}
    for key, symbol in MACRO_TICKERS.items():
        macro_data[key] = fetch_data(symbol, period, interval)
    return macro_data


def analyze(ticker: str, period: str = LOOKBACK_PERIOD, interval: str = INTERVAL,
            use_ml: bool = False) -> pd.DataFrame:
    stock_df = fetch_data(ticker, period, interval)
    macro_data = fetch_macro(period, interval)

    stock_with_ind = add_all_indicators(stock_df)

    macro_scores = compute_macro_scores(macro_data)
    macro_aligned = align_macro_to_stock(stock_with_ind.index, macro_scores)

    result = run_model(stock_with_ind, macro_aligned)

    if use_ml:
        # Honest, out-of-sample ML: train on the earlier chronological
        # portion, evaluate on a held-out tail, and attach BOTH the latest
        # probability AND the holdout accuracy/AUC so the caller can judge
        # whether the probability is trustworthy. Features are purely
        # Yahoo-derived (RSI/SMA/_score/volume) — no Binance futures data,
        # so this works fine in the US. Falls back gracefully if there
        # isn't enough history or xgboost isn't installed.
        try:
            holdout = train_ml_model_with_holdout(result)
            model = holdout["model"]
            feature_cols = holdout["feature_cols"]
            # Score the most recent rows (in-sample for the model, but this
            # is the live prediction; its RELIABILITY is quantified by the
            # holdout metrics below, which the output prints alongside it).
            live_X = result[feature_cols].dropna()
            if not live_X.empty:
                proba = model.predict_proba(live_X)[:, 1] * 100
                result.loc[live_X.index, "ai_confidence_score"] = proba
            # Stash holdout metrics on the DataFrame for the caller to read.
            result.attrs["ml_accuracy"] = holdout["accuracy"]
            result.attrs["ml_roc_auc"] = holdout["roc_auc"]
            result.attrs["ml_test_n"] = len(holdout["y_test"])
            result.attrs["ml_lookahead_days"] = holdout["lookahead_days"]
            result.attrs["ml_threshold_pct"] = holdout["threshold_pct"]
            result.attrs["ml_ok"] = True
        except Exception as e:  # noqa: BLE001 - ML must never break the base pipeline
            result.attrs["ml_ok"] = False
            result.attrs["ml_error"] = f"{type(e).__name__}: {e}"

    return result


def print_latest(result: pd.DataFrame, ticker: str):
    valid = result.dropna(subset=["final_score"])
    latest = valid.iloc[-1]
    date = valid.index[-1]

    print("\n" + "=" * 60)
    print(f"  {ticker}  —  Entry Signal as of {date.date()}")
    print("=" * 60)
    print(f"  Technical Score : {latest['technical_score']:.1f} / 100")
    print(f"  Macro Multiplier: {latest['macro_multiplier']:.2f}x  "
          f"(macro regime score: {latest['macro_score']:.1f} / 100)")
    print(f"  Final Score     : {latest['final_score']:.1f} / 100")
    print(f"  Decision        : {latest['decision']}")
    if 'ai_confidence_score' in result.columns and pd.notna(latest.get('ai_confidence_score')):
        print(f"  AI Confidence   : {latest['ai_confidence_score']:.1f}% "
              f"(XGBoost probability of +2% avg move over next 10 days)")
    print("-" * 60)
    print("  Macro filter breakdown (-1 bearish .. +1 bullish):")
    print(f"    VIX  ({latest['vix_level']:.1f}) : {latest['vix_score']:+.2f}")
    print(f"    DXY score  : {latest['dxy_score']:+.2f}")
    print("-" * 60)
    print("  Technical sub-signal breakdown (-1 bearish .. +1 bullish):")
    for name in ["rsi", "momentum", "cci", "williams_r", "macd", "ma_stack", "vwma", "nvi"]:
        print(f"    {name:12s}: {latest[f'sub_{name}']:+.2f}")
    print("=" * 60 + "\n")


# ======================================================================
# BACKTEST — simple fixed-holding-period signal check
# ======================================================================

def run_backtest(result: pd.DataFrame, hold_days: int = 10) -> pd.DataFrame:
    df = result.dropna(subset=["final_score", "decision"]).copy()
    df["prev_decision"] = df["decision"].shift(1)

    entries = df[
        (df["decision"].isin(["BUY", "STRONG_BUY"]))
        & (~df["prev_decision"].isin(["BUY", "STRONG_BUY"]))
    ].copy()

    trades = []
    close = df["Close"]
    for entry_date in entries.index:
        entry_price = close.loc[entry_date]
        pos = close.index.get_loc(entry_date)
        exit_pos = min(pos + hold_days, len(close) - 1)
        exit_date = close.index[exit_pos]
        exit_price = close.iloc[exit_pos]
        fwd_return = (exit_price - entry_price) / entry_price * 100
        trades.append({
            "entry_date": entry_date,
            "decision": entries.loc[entry_date, "decision"],
            "final_score": entries.loc[entry_date, "final_score"],
            "entry_price": entry_price,
            "exit_date": exit_date,
            "exit_price": exit_price,
            "return_pct": fwd_return,
        })

    return pd.DataFrame(trades)


def summarize_backtest(trades_df: pd.DataFrame, hold_days: int):
    if trades_df.empty:
        print("No BUY/STRONG_BUY signals were triggered in this period.")
        return

    win_rate = (trades_df["return_pct"] > 0).mean() * 100
    avg_return = trades_df["return_pct"].mean()
    median_return = trades_df["return_pct"].median()

    print("\n" + "=" * 60)
    print(f"  Backtest summary — hold period: {hold_days} trading days")
    print("=" * 60)
    print(f"  Number of signals : {len(trades_df)}")
    print(f"  Win rate          : {win_rate:.1f}%")
    print(f"  Avg forward return: {avg_return:+.2f}%")
    print(f"  Median return     : {median_return:+.2f}%")
    print(f"  Best trade        : {trades_df['return_pct'].max():+.2f}%")
    print(f"  Worst trade       : {trades_df['return_pct'].min():+.2f}%")
    print("=" * 60 + "\n")
    print(trades_df.to_string(index=False))


# ======================================================================
# OFFLINE SMOKE TEST — synthetic data, no network required
# ======================================================================

def make_synthetic_ohlcv(n=600, seed=42, start_price=100.0):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2022-01-01", periods=n, freq="B")
    returns = rng.normal(0.0004, 0.015, n)
    close = start_price * np.cumprod(1 + returns)
    high = close * (1 + np.abs(rng.normal(0, 0.005, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.005, n)))
    open_ = close * (1 + rng.normal(0, 0.003, n))
    volume = rng.integers(1_000_000, 5_000_000, n).astype(float)
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=dates,
    )


def make_synthetic_macro(index, seed_offset=0):
    rng = np.random.default_rng(100 + seed_offset)
    n = len(index)
    vix = pd.Series(18 + rng.normal(0, 4, n).cumsum() * 0.05, index=index).clip(9, 60)
    dxy = pd.Series(100 + rng.normal(0, 0.3, n).cumsum() * 0.1, index=index).clip(70, 130)
    return {
        "VIX": pd.DataFrame({"Close": vix}),
        "DXY": pd.DataFrame({"Close": dxy}),
    }


def run_smoketest():
    stock_df = make_synthetic_ohlcv()
    macro_data = make_synthetic_macro(stock_df.index)

    stock_ind = add_all_indicators(stock_df)
    rsi5_valid = stock_ind["RSI_5"].dropna()
    assert rsi5_valid.between(0, 100, inclusive="both").all(), "RSI out of bounds"

    macro_scores = compute_macro_scores(macro_data)
    macro_aligned = align_macro_to_stock(stock_ind.index, macro_scores)
    assert macro_aligned["macro_multiplier"].dropna().between(0.5, 1.2).all(), "multiplier out of range"

    result = run_model(stock_ind, macro_aligned)
    assert result["final_score"].dropna().between(0, 100).all(), "final_score out of bounds"

    print("Decision counts:")
    print(result["decision"].value_counts())
    print("\nLast 5 rows (key columns):")
    cols = ["Close", "technical_score", "macro_multiplier", "final_score", "decision"]
    print(result[cols].tail(5).to_string())
    print("\nSMOKE TEST PASSED")


# ======================================================================
# CLI
# ======================================================================

def main():
    parser = argparse.ArgumentParser(description="Technical + Macro entry point model")
    sub = parser.add_subparsers(dest="command", required=True)

    p_analyze = sub.add_parser("analyze", help="Fetch live data and print the latest signal")
    p_analyze.add_argument("ticker")
    p_analyze.add_argument("--period", default=LOOKBACK_PERIOD)
    p_analyze.add_argument("--interval", default=INTERVAL)
    p_analyze.add_argument("--save", default=None, help="Optional CSV path for full signal history")
    p_analyze.add_argument("--ml", action="store_true", help="Also compute XGBoost AI confidence score")

    p_backtest = sub.add_parser("backtest", help="Backtest BUY/STRONG_BUY signals")
    p_backtest.add_argument("ticker")
    p_backtest.add_argument("--period", default="5y")
    p_backtest.add_argument("--hold-days", type=int, default=10)
    p_backtest.add_argument("--save", default=None)
    p_backtest.add_argument("--ml", action="store_true", help="Also compute XGBoost AI confidence score")

    sub.add_parser("smoketest", help="Run offline synthetic-data sanity check")

    p_train = sub.add_parser("train", help="Train the XGBoost model with a chronological holdout and report metrics")
    p_train.add_argument("ticker")
    p_train.add_argument("--period", default="5y")
    p_train.add_argument("--test-size", type=float, default=0.2, help="Fraction of most-recent rows held out for testing")
    p_train.add_argument("--lookahead-days", type=int, default=10, help="Forward-looking window (days) for the label")
    p_train.add_argument("--threshold-pct", type=float, default=0.02, help="Required forward move (e.g. 0.02 = 2%) for a positive label")

    args = parser.parse_args()

    if args.command == "analyze":
        result = analyze(args.ticker, period=args.period, interval=args.interval, use_ml=args.ml)
        print_latest(result, args.ticker)
        if args.save:
            result.to_csv(args.save)
            print(f"Full signal history saved to {args.save}")

    elif args.command == "backtest":
        result = analyze(args.ticker, period=args.period, use_ml=args.ml)
        trades_df = run_backtest(result, hold_days=args.hold_days)
        summarize_backtest(trades_df, args.hold_days)
        if args.save and not trades_df.empty:
            trades_df.to_csv(args.save, index=False)
            print(f"\nTrade log saved to {args.save}")

    elif args.command == "smoketest":
        run_smoketest()

    elif args.command == "train":
        result = analyze(args.ticker, period=args.period)
        holdout_result = train_ml_model_with_holdout(
            result, test_size=args.test_size,
            lookahead_days=args.lookahead_days, threshold_pct=args.threshold_pct,
        )
        print_holdout_report(holdout_result, args.ticker)


if __name__ == "__main__":
    main()


# ======================================================================
# SECTION 3 — reddit_sentiment.py (sentiment_gate primitives + dead fetchers, kept for reference)
# ======================================================================

"""
reddit_sentiment.py
--------------------
A Reddit sentiment "gate" meant to run BEFORE the technical/pattern
indicators — a first-pass check on crowd mood that can veto or dampen a
signal before you even bother trusting momentum/squeeze/whatever else.

TWO WAYS TO FETCH DATA:

  1. fetch_ticker_mentions_json() — NO AUTH, but AS OF MAY 30, 2026,
     REDDIT SHUT THIS DOWN. Every unauthenticated request to a .json
     endpoint now returns 403, regardless of User-Agent — Reddit moved
     to TLS-fingerprint/IP-reputation blocking, not header-based
     throttling, so there is no client-side header fix. This path is
     kept in the code for reference / in case Reddit ever reopens it,
     but treat it as broken until proven otherwise.

  2. fetch_ticker_mentions() — uses PRAW + your own Reddit API app
     credentials (client_id/client_secret from reddit.com/prefs/apps).
     THIS IS NOW THE ONLY WORKING OPTION. Use
     first_pass_sentiment_check_auto() below, which reads credentials
     from environment variables so nothing is hardcoded:
         REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT
     Get client_id/client_secret by creating a "script" app at
     https://www.reddit.com/prefs/apps (free, takes a couple minutes).

Everything downstream (scoring, aggregation, the gate) is IDENTICAL
either way — both fetchers return the same DataFrame shape.

IMPORTANT HONEST LIMITATIONS (read before using):

1. THE NO-AUTH JSON APPROACH HAS LIMITS TOO. It's more aggressively
   rate-limited than the authenticated API (this code paces requests
   automatically, ~1 every 2 seconds, to stay well within safe bounds).
   It's a gray area for anything beyond light personal use under
   Reddit's terms — fine for what you're doing, but worth knowing.
   Reddit could tighten this up without notice, same as any
   unauthenticated scraping approach.

2. NO DEEP HISTORICAL ARCHIVE either way. Realistically this covers the
   last few weeks to a few months of posts well, and gets sparse/
   unreliable further back (Pushshift, which used to provide a full
   historical archive, is largely locked down now). That means this
   CANNOT be walk-forward validated across market regimes the way your
   price data was — treat it as a live, real-time gate you're testing
   forward from today. evaluate_sentiment_scoring_variants() below is
   intentionally a lightweight comparison tool, not a full walk-forward
   harness, for exactly this reason.

3. VADER SENTIMENT IS A BLUNT INSTRUMENT. It's a lexicon-based scorer
   (looks up words like "moon", "dump", "bullish" against a dictionary
   of sentiment scores), not a language model. It's the practical
   standard for short, informal social media text and needs no GPU/API
   calls, but it will misread sarcasm, crypto-specific slang it doesn't
   recognize, and coordinated shilling/FUD as if it were organic
   sentiment. Use it as one noisy signal, not ground truth.

Requires: pip install requests vaderSentiment pandas numpy
(praw only needed if you use the PRAW-based fetcher instead)
"""



DEFAULT_SUBREDDITS = ["CryptoCurrency", "Bitcoin", "CryptoMarkets", "ethtrader"]

TICKER_ALIASES = {
    "BTC": ["BTC", "Bitcoin", "$BTC"],
    "ETH": ["ETH", "Ethereum", "$ETH"],
    "SOL": ["SOL", "Solana", "$SOL"],
}

# Reddit requires a descriptive User-Agent on every request, authed or not.
# Change the contact bit to something identifying you if you want to be a
# good citizen about it, though it's not strictly required for read-only
# public JSON access.
JSON_USER_AGENT = "crypto-sentiment-gate/0.1 (personal project, read-only)"


def get_ticker_search_terms(ticker: str) -> list:
    """Maps a Yahoo/Binance-style ticker (e.g. 'BTC-USD') to search terms."""
    base = ticker.split("-")[0].upper()
    return TICKER_ALIASES.get(base, [base])


# ======================================================================
# NO-AUTH FETCHING (recommended starting point — nothing to set up)
# ======================================================================

def _reddit_json_get(url: str, params: dict = None, max_retries: int = 3) -> dict:
    """GET a Reddit .json endpoint with retry-with-backoff, same pattern
    as crypto_features.py's Binance fetcher."""

    headers = {"User-Agent": JSON_USER_AGENT}
    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=15)
            if resp.status_code == 429:
                wait = 5 * attempt
                print(f"  [reddit-json] rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except Exception as e:  # noqa: BLE001
            last_error = e
            if attempt < max_retries:
                wait = 3 * attempt
                print(f"  [reddit-json] attempt {attempt}/{max_retries} failed "
                      f"({type(e).__name__}); retrying in {wait}s...")
                time.sleep(wait)

    raise ConnectionError(f"Failed to fetch {url} after {max_retries} attempts: {last_error}")


def fetch_ticker_mentions_json(ticker: str, subreddits: list = None,
                                limit_per_sub: int = 100, sort: str = "new",
                                include_top_comments: int = 5,
                                pace_seconds: float = 2.0) -> pd.DataFrame:
    """
    NO-AUTH version of fetch_ticker_mentions. Pulls recent posts from each
    subreddit's public JSON feed (e.g. reddit.com/r/Bitcoin/new.json),
    filters client-side for ones mentioning the ticker, and grabs their
    top comments the same way.

    Since there's no search endpoint available without auth, this pulls
    the subreddit's recent posts (up to `limit_per_sub`, capped at 100 by
    Reddit per request) and filters for ticker mentions locally — so it
    only sees whatever's recently active, not a full historical search.
    For a high-traffic sub like r/CryptoCurrency that's usually plenty
    for a "last day or two" sentiment read; for less active subs you may
    need a higher limit or to accept sparser coverage.

    pace_seconds: delay between requests to stay well within safe rate
    limits for unauthenticated access. Don't set this too low.
    """
    if subreddits is None:
        subreddits = DEFAULT_SUBREDDITS

    search_terms = [t.lower() for t in get_ticker_search_terms(ticker)]
    rows = []

    for sub_name in subreddits:
        url = f"https://www.reddit.com/r/{sub_name}/{sort}.json"
        try:
            data = _reddit_json_get(url, params={"limit": min(limit_per_sub, 100)})
        except Exception as e:
            print(f"  [reddit-json] {sub_name} failed ({type(e).__name__}: {e}), skipping.")
            continue

        children = data.get("data", {}).get("children", [])
        matched = 0
        for child in children:
            post = child.get("data", {})
            title = post.get("title", "") or ""
            selftext = post.get("selftext", "") or ""
            combined_lower = (title + " " + selftext).lower()

            if not any(term in combined_lower for term in search_terms):
                continue
            matched += 1

            rows.append({
                "timestamp": pd.to_datetime(post.get("created_utc"), unit="s"),
                "subreddit": sub_name,
                "type": "post",
                "text": f"{title}\n{selftext}",
                "score": post.get("score", 0),
                "num_comments": post.get("num_comments", 0),
            })

            if include_top_comments > 0 and post.get("num_comments", 0) > 0:
                permalink = post.get("permalink")
                if permalink:
                    time.sleep(pace_seconds)
                    comment_url = f"https://www.reddit.com{permalink}.json"
                    try:
                        comment_data = _reddit_json_get(comment_url, params={"limit": include_top_comments})
                        if len(comment_data) > 1:
                            comment_children = comment_data[1].get("data", {}).get("children", [])
                            for c in comment_children[:include_top_comments]:
                                c_data = c.get("data", {})
                                body = c_data.get("body")
                                if not body:
                                    continue
                                rows.append({
                                    "timestamp": pd.to_datetime(c_data.get("created_utc"), unit="s"),
                                    "subreddit": sub_name,
                                    "type": "comment",
                                    "text": body,
                                    "score": c_data.get("score", 0),
                                    "num_comments": np.nan,
                                })
                    except Exception as e:
                        print(f"  [reddit-json] comments for a post in {sub_name} failed "
                              f"({type(e).__name__}), skipping that post's comments.")

        print(f"  [reddit-json] r/{sub_name}: {len(children)} recent posts checked, "
              f"{matched} mentioned {ticker}")
        time.sleep(pace_seconds)

    return pd.DataFrame(rows)


# ======================================================================
# REDDIT CLIENT + FETCHING (PRAW / authenticated — optional)
# ======================================================================

def get_reddit_client(client_id: str, client_secret: str, user_agent: str):
    """
    Read-only PRAW client. Get client_id/client_secret from
    https://www.reddit.com/prefs/apps (create a "script" app).
    user_agent should be a descriptive string, e.g. "crypto-sentiment-gate/0.1 by u/yourname"
    (Reddit requires a real, non-generic user agent or it may throttle/block you).
    """
    import praw
    reddit = praw.Reddit(
        client_id=client_id,
        client_secret=client_secret,
        user_agent=user_agent,
    )
    reddit.read_only = True
    return reddit


def fetch_ticker_mentions(reddit, ticker: str, subreddits: list = None,
                           limit_per_sub: int = 100, time_filter: str = "month",
                           include_top_comments: int = 5) -> pd.DataFrame:
    """
    Searches each subreddit for posts mentioning the ticker, and pulls the
    top N comments per matching post for extra volume/granularity.

    time_filter: one of 'hour', 'day', 'week', 'month', 'year', 'all'.
    Realistically, 'month' is close to the practical ceiling for dense,
    reliable coverage — see module docstring caveat #2.

    Returns a DataFrame: timestamp, subreddit, type ('post'/'comment'),
    text, score, num_comments (posts only, NaN for comments).
    """
    if subreddits is None:
        subreddits = DEFAULT_SUBREDDITS

    search_terms = get_ticker_search_terms(ticker)
    query = " OR ".join(f'"{t}"' for t in search_terms)

    rows = []
    for sub_name in subreddits:
        try:
            subreddit = reddit.subreddit(sub_name)
            for submission in subreddit.search(query, time_filter=time_filter,
                                                 limit=limit_per_sub, sort="new"):
                text = f"{submission.title}\n{submission.selftext or ''}"
                rows.append({
                    "timestamp": pd.to_datetime(submission.created_utc, unit="s"),
                    "subreddit": sub_name,
                    "type": "post",
                    "text": text,
                    "score": submission.score,
                    "num_comments": submission.num_comments,
                })

                if include_top_comments > 0:
                    submission.comment_sort = "top"
                    submission.comments.replace_more(limit=0)
                    for comment in submission.comments[:include_top_comments]:
                        rows.append({
                            "timestamp": pd.to_datetime(comment.created_utc, unit="s"),
                            "subreddit": sub_name,
                            "type": "comment",
                            "text": comment.body,
                            "score": comment.score,
                            "num_comments": np.nan,
                        })
        except Exception as e:  # noqa: BLE001 - keep going even if one subreddit fails
            print(f"  [reddit] {sub_name} failed ({type(e).__name__}: {e}), skipping.")
            continue

    return pd.DataFrame(rows)


# ======================================================================
# SENTIMENT SCORING
# ======================================================================

def score_sentiment_vader(text: str, analyzer=None) -> float:
    """
    VADER compound sentiment score, -1 (very negative) to +1 (very
    positive). See module docstring caveat #3 on its limitations.
    """
    if analyzer is None:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        analyzer = SentimentIntensityAnalyzer()
    if not text or not isinstance(text, str):
        return 0.0
    return analyzer.polarity_scores(text)["compound"]


def add_sentiment_scores(df_mentions: pd.DataFrame) -> pd.DataFrame:
    """Adds a 'sentiment' column (VADER compound score) to every row."""
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    analyzer = SentimentIntensityAnalyzer()

    out = df_mentions.copy()
    out["sentiment"] = out["text"].apply(lambda t: score_sentiment_vader(t, analyzer))
    return out


# ======================================================================
# DAILY AGGREGATION — three candidate scoring variants
# ======================================================================

def aggregate_daily_sentiment(df_scored: pd.DataFrame) -> pd.DataFrame:
    """
    Builds THREE candidate daily sentiment scores from the same raw
    scored mentions, so you can compare which one actually correlates
    with forward price moves once you've got some real history:

        sentiment_mean      simple average compound score that day
        sentiment_weighted  upvote-weighted average (log1p-dampened, so
                             one viral post doesn't dominate everything)
        sentiment_volume    number of mentions that day — attention/
                             interest level, independent of tone. A spike
                             in volume (regardless of sign) can itself be
                             informative (something's happening).

    Also includes sentiment_std (how much disagreement there is that
    day — consensus vs. a split crowd) and n_mentions (sample size, so
    you can tell a real signal from a day with only 2 posts).
    """
    if df_scored.empty:
        return pd.DataFrame(columns=[
            "sentiment_mean", "sentiment_weighted", "sentiment_volume",
            "sentiment_std", "n_mentions",
        ])

    df = df_scored.copy()
    df["date"] = df["timestamp"].dt.floor("D")
    df["weight"] = np.log1p(df["score"].clip(lower=0))

    def _weighted_mean(group):
        w = group["weight"]
        if w.sum() == 0:
            return group["sentiment"].mean()
        return np.average(group["sentiment"], weights=w)

    daily = df.groupby("date").apply(
        lambda g: pd.Series({
            "sentiment_mean": g["sentiment"].mean(),
            "sentiment_weighted": _weighted_mean(g),
            "sentiment_volume": len(g),
            "sentiment_std": g["sentiment"].std(),
            "n_mentions": len(g),
        }),
        include_groups=False,
    )
    return daily


# ======================================================================
# THE GATE — first-pass check, meant to run BEFORE indicators
# ======================================================================

def sentiment_gate(sentiment_mean: float, n_mentions: int,
                    bearish_threshold: float = -0.15,
                    extreme_bearish_threshold: float = -0.35,
                    min_mentions_for_confidence: int = 15) -> dict:
    """
    The actual "step check before the indicators." Call this FIRST, and
    only proceed to run your technical/squeeze/momentum model if the
    gate says PROCEED or CAUTION — a VETO means don't bother, or at
    minimum treat any resulting BUY signal with serious added skepticism.

    Mirrors the same pattern as entry_point_model.py's VIX extreme-fear
    veto: a sufficiently hostile crowd-sentiment reading can override an
    otherwise-good technical setup, same logic as "don't trust a
    technical BUY when the broader market is in a panic."

    Returns a dict with:
        decision          "PROCEED" / "CAUTION" / "VETO" / "LOW_CONFIDENCE"
        gate_multiplier    scales a downstream score (1.0 = no change,
                            <1.0 = dampened, as low as 0.5 on extreme
                            bearish readings)
        reason             human-readable explanation
    """
    if n_mentions < min_mentions_for_confidence:
        return {
            "decision": "LOW_CONFIDENCE",
            "gate_multiplier": 1.0,
            "reason": f"Only {n_mentions} mentions found (need >= "
                      f"{min_mentions_for_confidence} to trust the sentiment reading at all) "
                      f"— proceeding on indicators alone, sentiment ignored for now.",
        }

    if sentiment_mean <= extreme_bearish_threshold:
        return {
            "decision": "VETO",
            "gate_multiplier": 0.5,
            "reason": f"Sentiment ({sentiment_mean:.3f}) is extremely bearish across "
                      f"{n_mentions} mentions — treating any BUY signal with heavy skepticism "
                      f"regardless of what the indicators say.",
        }

    if sentiment_mean <= bearish_threshold:
        # Linear dampening between bearish_threshold and extreme_bearish_threshold
        span = bearish_threshold - extreme_bearish_threshold
        position = (bearish_threshold - sentiment_mean) / span if span else 0
        multiplier = 1.0 - 0.4 * position  # scales from 1.0 down to 0.6
        return {
            "decision": "CAUTION",
            "gate_multiplier": round(multiplier, 3),
            "reason": f"Sentiment ({sentiment_mean:.3f}) is negative across {n_mentions} "
                      f"mentions — dampening downstream confidence somewhat.",
        }

    return {
        "decision": "PROCEED",
        "gate_multiplier": 1.0,
        "reason": f"Sentiment ({sentiment_mean:.3f}) across {n_mentions} mentions is neutral "
                  f"or positive — no gating applied.",
    }


def apply_gate_to_score(gate_result: dict, downstream_score: float) -> float:
    """Convenience: scales any downstream score (0-100, or a raw probability)
    by the gate's multiplier."""
    return downstream_score * gate_result["gate_multiplier"]


# ======================================================================
# ORCHESTRATION — the full "check sentiment first" flow
# ======================================================================

def build_reddit_sentiment_daily(ticker: str, client_id: str, client_secret: str,
                                  user_agent: str, subreddits: list = None,
                                  time_filter: str = "month", limit_per_sub: int = 100,
                                  include_top_comments: int = 5) -> pd.DataFrame:
    """
    End-to-end: connect, fetch mentions, score, aggregate to daily. This
    is the function you'd actually call. Remember caveat #2 — this will
    only realistically cover recent history (see time_filter).
    """
    reddit = get_reddit_client(client_id, client_secret, user_agent)
    print(f"Fetching Reddit mentions of {ticker} from {subreddits or DEFAULT_SUBREDDITS}...")
    mentions = fetch_ticker_mentions(
        reddit, ticker, subreddits=subreddits, limit_per_sub=limit_per_sub,
        time_filter=time_filter, include_top_comments=include_top_comments,
    )
    print(f"Found {len(mentions)} mentions (posts + top comments).")
    if mentions.empty:
        print("No mentions found — check your search terms, subreddit list, or time_filter.")
        return pd.DataFrame()

    scored = add_sentiment_scores(mentions)
    daily = aggregate_daily_sentiment(scored)
    return daily


def first_pass_sentiment_check(ticker: str, client_id: str, client_secret: str,
                                user_agent: str, subreddits: list = None,
                                time_filter: str = "week") -> dict:
    """
    The literal "run this BEFORE your indicators" entry point. Fetches
    TODAY's/this week's sentiment, runs it through the gate, and returns
    the decision immediately — cheap enough to run first, before you
    bother pulling klines/funding/etc. for the technical side.
    """
    daily = build_reddit_sentiment_daily(
        ticker, client_id, client_secret, user_agent,
        subreddits=subreddits, time_filter=time_filter,
    )
    if daily.empty:
        return {
            "decision": "LOW_CONFIDENCE", "gate_multiplier": 1.0,
            "reason": "No Reddit data retrieved at all — proceeding on indicators alone.",
        }

    latest = daily.iloc[-1]
    return sentiment_gate(latest["sentiment_mean"], int(latest["n_mentions"]))


def build_reddit_sentiment_daily_json(ticker: str, subreddits: list = None,
                                       limit_per_sub: int = 100,
                                       include_top_comments: int = 5) -> pd.DataFrame:
    """
    NO-AUTH version of build_reddit_sentiment_daily. Same output shape,
    fetches via fetch_ticker_mentions_json instead of PRAW. This is the
    recommended entry point — no credentials needed.
    """
    print(f"Fetching Reddit mentions of {ticker} from {subreddits or DEFAULT_SUBREDDITS} "
          f"(no-auth JSON, recent posts only)...")
    mentions = fetch_ticker_mentions_json(
        ticker, subreddits=subreddits, limit_per_sub=limit_per_sub,
        include_top_comments=include_top_comments,
    )
    print(f"Found {len(mentions)} mentions (posts + top comments).")
    if mentions.empty:
        print("No mentions found — check your search terms, subreddit list, or try more subs.")
        return pd.DataFrame()

    scored = add_sentiment_scores(mentions)
    daily = aggregate_daily_sentiment(scored)
    return daily


def first_pass_sentiment_check_json(ticker: str, subreddits: list = None,
                                     limit_per_sub: int = 100) -> dict:
    """
    NO-AUTH version of first_pass_sentiment_check. AS OF MAY 30, 2026 THIS
    WILL FAIL EVERY TIME — Reddit blocks all unauthenticated .json access
    now (see module docstring). Kept only for reference; use
    first_pass_sentiment_check_auto() instead.
    """
    daily = build_reddit_sentiment_daily_json(ticker, subreddits=subreddits,
                                               limit_per_sub=limit_per_sub)
    if daily.empty:
        return {
            "decision": "LOW_CONFIDENCE", "gate_multiplier": 1.0,
            "reason": "No Reddit data retrieved at all — proceeding on indicators alone.",
        }

    latest = daily.iloc[-1]
    return sentiment_gate(latest["sentiment_mean"], int(latest["n_mentions"]))


def get_reddit_credentials_from_env() -> tuple:
    """
    Reads PRAW credentials from environment variables:
        REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT
    Returns (client_id, client_secret, user_agent), any of which may be
    None if not set. Keeping credentials out of source code/CLI args is
    just good practice (don't commit client_secret to git).
    """
    return (
        os.environ.get("REDDIT_CLIENT_ID"),
        os.environ.get("REDDIT_CLIENT_SECRET"),
        os.environ.get("REDDIT_USER_AGENT"),
    )


def first_pass_sentiment_check_auto(ticker: str, subreddits: list = None,
                                     limit_per_sub: int = 100,
                                     time_filter: str = "month") -> dict:
    """
    THE ENTRY POINT TO USE. Reads PRAW credentials from environment
    variables (REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET / REDDIT_USER_AGENT)
    and runs the authenticated fetch — the only path that still works as
    of mid-2026 (see module docstring).

    If credentials aren't set, this does NOT silently fall back to the
    now-broken no-auth JSON scraper (that would just fail anyway and
    obscure why). Instead it raises immediately with setup instructions,
    so the failure is obvious rather than a mysterious "0 mentions found."
    """
    client_id, client_secret, user_agent = get_reddit_credentials_from_env()
    if not client_id or not client_secret or not user_agent:
        raise EnvironmentError(
            "Missing Reddit API credentials. As of May 2026, Reddit requires "
            "authenticated access — the no-auth .json approach no longer works.\n"
            "  1. Create a 'script' app at https://www.reddit.com/prefs/apps\n"
            "  2. Set these environment variables:\n"
            "       REDDIT_CLIENT_ID=<the id under your app's name>\n"
            "       REDDIT_CLIENT_SECRET=<the secret>\n"
            "       REDDIT_USER_AGENT=<something descriptive, e.g. 'crypto-sentiment-gate/0.1 by u/yourname'>\n"
            "  3. pip install praw"
        )

    return first_pass_sentiment_check(
        ticker, client_id, client_secret, user_agent,
        subreddits=subreddits, time_filter=time_filter,
    )


# ======================================================================
# DIRECT MODEL INTEGRATION — proves the gate actually changes a real
# downstream score, not just an abstract multiplier sitting on its own
# ======================================================================

def apply_gate_to_result(gate_result: dict, score_before: float,
                          label: str = "score") -> dict:
    """
    Applies the sentiment gate to one concrete downstream number (e.g. a
    technical_score from entry_point_model.py, or an ai_confidence_score
    from crypto_features.py) and returns BOTH the before and after values
    side by side, so the effect is visible and provable rather than
    implicit.
    """
    score_after = apply_gate_to_score(gate_result, score_before)
    changed = round(score_before, 2) != round(score_after, 2)
    return {
        "label": label,
        "score_before": round(score_before, 2),
        "score_after": round(score_after, 2),
        "delta": round(score_after - score_before, 2),
        "gate_decision": gate_result["decision"],
        "gate_multiplier": gate_result["gate_multiplier"],
        "gate_reason": gate_result["reason"],
        "changed_outcome": changed,
    }


def print_gate_effect(effect: dict):
    print("\n" + "=" * 65)
    print(f"  SENTIMENT GATE EFFECT ON: {effect['label']}")
    print("=" * 65)
    print(f"  Gate decision   : {effect['gate_decision']}")
    print(f"  Gate multiplier : {effect['gate_multiplier']}x")
    print(f"  Reason          : {effect['gate_reason']}")
    print("-" * 65)
    print(f"  Score BEFORE gate : {effect['score_before']}")
    print(f"  Score AFTER gate  : {effect['score_after']}")
    print(f"  Delta             : {effect['delta']:+.2f}")
    print("=" * 65 + "\n")


# ======================================================================
# COMPARING SCORING VARIANTS — lightweight, honest about data limits
# ======================================================================

def evaluate_sentiment_scoring_variants(daily_sentiment: pd.DataFrame,
                                         daily_price: pd.Series,
                                         lookahead_days: int = 1) -> pd.DataFrame:
    """
    Compares the three sentiment variants (mean / weighted / volume)
    against forward price returns. NOT a full walk-forward harness like
    crypto_features.py's — deliberately lighter-weight, because Reddit's
    practical history depth (weeks to a couple months) usually isn't
    enough rows to split into multiple reliable folds the way years of
    price data was. Treat this as an early read, not a final verdict —
    rerun it periodically as you accumulate more real history.

    daily_price: a Series of Close prices indexed by date (e.g. resample
    your intraday Close to daily, or use entry_point_model's daily data).

    Returns a small table: for each variant, the correlation with the
    forward `lookahead_days`-day return, and the mean forward return
    split by whether that day's sentiment was above/below its own median
    (a simple, low-data-requirement way to see if the variant carries
    any real directional information at all).
    """
    aligned = daily_sentiment.join(daily_price.rename("Close"), how="inner")
    aligned["fwd_return"] = aligned["Close"].shift(-lookahead_days) / aligned["Close"] - 1
    aligned = aligned.dropna(subset=["fwd_return"])

    if len(aligned) < 10:
        print(f"Only {len(aligned)} aligned rows — too little overlapping history between "
              f"your sentiment data and price data to say anything meaningful yet. "
              f"Keep collecting and rerun this later.")
        return pd.DataFrame()

    rows = []
    for variant in ["sentiment_mean", "sentiment_weighted", "sentiment_volume"]:
        if variant not in aligned.columns:
            continue
        corr = aligned[variant].corr(aligned["fwd_return"])
        median = aligned[variant].median()
        high_group = aligned[aligned[variant] > median]["fwd_return"]
        low_group = aligned[aligned[variant] <= median]["fwd_return"]
        rows.append({
            "variant": variant,
            "n_days": len(aligned),
            "correlation_with_fwd_return": corr,
            "mean_fwd_return_high_half": high_group.mean(),
            "mean_fwd_return_low_half": low_group.mean(),
            "spread": high_group.mean() - low_group.mean(),
        })

    return pd.DataFrame(rows).sort_values("correlation_with_fwd_return",
                                           key=lambda s: s.abs(), ascending=False)


# ======================================================================
# SECTION 4 — adanos_sentiment.py (Step 2: live sentiment source, USES sentiment_gate() above directly)
# ======================================================================

"""
adanos_sentiment.py
---------------------
Step 2 data source, take four. Reddit closed unauthenticated access and
gated new app registration; LunarCrush's free key carries no API
credit (402 on every real call); ApeWisdom is free and keyless but
only exposes mention volume, not sentiment polarity — see the
docstrings in reddit_sentiment.py, lunarcrush_sentiment.py and
apewisdom_sentiment.py for that whole saga.

Adanos (https://adanos.org) restores what the original design wanted:
a genuine bullish/bearish sentiment score, not just buzz volume, with
a real (if small) free tier and documented, versioned endpoints.

ENDPOINT USED: GET https://api.adanos.org/reddit/crypto/v1/token/{symbol}
AUTH: header `X-API-Key: <your key>`

KEY FIELDS USED:
    sentiment_score  -> -1..+1, same scale reddit_sentiment.py's VADER
                         scores used, so it plugs directly into the
                         existing sentiment_gate() thresholds unchanged.
    mentions          -> used as the confidence/volume check, same role
                         n_mentions played in the original Reddit gate.

FREE TIER LIMITS (as of registration): 250 requests/month, 100
requests/minute, 30 days of history, non-commercial use only. That
monthly cap is tight — fine for periodic single runs of
unified_model.py, but --loop mode with a short --interval-seconds will
exhaust it fast. There's no silent overage; once quota's gone, calls
will start failing (check for 429/402-style responses and stop looping
if that happens rather than hammering it further).

SETUP:
  1. Sign up free at https://adanos.org/register (no credit card)
  2. Set the environment variable: ADANOS_API_KEY=<your key>
  3. pip install requests
"""




API_BASE = "https://api.adanos.org/reddit/crypto"


def get_api_key_from_env() -> str:
    return os.environ.get("ADANOS_API_KEY")


def fetch_token_sentiment(ticker: str, api_key: str = None, max_retries: int = 3) -> dict:
    """
    Calls GET /v1/token/{symbol}. Returns the parsed JSON response, or
    a dict with found=False if Adanos returns 404 (no mentions for
    that symbol in the lookback window) — that's a legitimate "quiet"
    result, not an error, same treatment as an empty Reddit search
    used to get.
    """
    if api_key is None:
        api_key = get_api_key_from_env()
    if not api_key:
        raise EnvironmentError(
            "Missing ADANOS_API_KEY. Sign up free at https://adanos.org/register, "
            "then set:\n  ADANOS_API_KEY=<your key>"
        )

    base = ticker.split("-")[0].upper()
    url = f"{API_BASE}/v1/token/{base}"
    headers = {"X-API-Key": api_key}
    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(url, headers=headers, timeout=15)

            if resp.status_code == 404:
                return {"symbol": base, "found": False}
            if resp.status_code == 401:
                raise PermissionError(
                    "Adanos rejected the API key (401) — check ADANOS_API_KEY is set correctly."
                )
            if resp.status_code == 429:
                wait = 5 * attempt
                print(f"  [adanos] rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue

            resp.raise_for_status()
            data = resp.json()
            data["found"] = True
            return data
        except (PermissionError,):
            raise
        except Exception as e:  # noqa: BLE001
            last_error = e
            if attempt < max_retries:
                wait = 3 * attempt
                print(f"  [adanos] attempt {attempt}/{max_retries} failed "
                      f"({type(e).__name__}); retrying in {wait}s...")
                time.sleep(wait)

    raise ConnectionError(f"Failed to fetch {url} after {max_retries} attempts: {last_error}")


def first_pass_sentiment_check_adanos(ticker: str, api_key: str = None,
                                       min_mentions_for_confidence: int = 15) -> dict:
    """
    THE ENTRY POINT TO USE. Fetches Adanos's per-token sentiment,
    then runs sentiment_score/mentions through the SAME
    sentiment_gate() logic reddit_sentiment.py originally used (same
    thresholds, same decision labels) — this is a genuine drop-in
    restoration of the original design, not a reinterpretation like
    the ApeWisdom mention-spike gate was.
    """
    print(f"Fetching Adanos Reddit-crypto sentiment for {ticker}...")
    data = fetch_token_sentiment(ticker, api_key=api_key)

    if not data.get("found", False):
        return {
            "decision": "LOW_CONFIDENCE", "gate_multiplier": 1.0,
            "reason": f"No Reddit mentions found for {ticker} on Adanos in the lookback "
                      f"window — proceeding on indicators alone.",
        }

    sentiment_score = data.get("sentiment_score")
    mentions = int(data.get("mentions", 0))
    bullish_pct = data.get("bullish_pct")
    bearish_pct = data.get("bearish_pct")

    print(f"  mentions={mentions}  sentiment_score={sentiment_score}  "
          f"bullish_pct={bullish_pct}  bearish_pct={bearish_pct}  "
          f"buzz_score={data.get('buzz_score')}")

    if sentiment_score is None:
        return {
            "decision": "LOW_CONFIDENCE", "gate_multiplier": 1.0,
            "reason": "Adanos returned no sentiment_score — proceeding on indicators alone.",
        }

    return sentiment_gate(sentiment_score, mentions,
                           min_mentions_for_confidence=min_mentions_for_confidence)
