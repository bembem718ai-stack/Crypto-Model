"""research/probe_depth.py -- PROBE ONLY. History depth of the non-price sources."""
import subprocess
import json
import datetime as dt


def get(url, timeout=60):
    p = subprocess.run(["curl", "-s", "--max-time", str(timeout), url],
                       capture_output=True, text=True, timeout=timeout + 20)
    return p.stdout


def span(name, lo, hi, n, note=""):
    try:
        y = (hi - lo).days / 365.25
    except Exception:
        y = float("nan")
    print("  %-30s %s -> %s  %6.2f y  n=%-7s %s"
          % (name, lo.date(), hi.date(), y, n, note))


D = dt.datetime.utcfromtimestamp

print("=" * 92)
print("HISTORY DEPTH — non-price sources")
print("=" * 92)

# Fear & Greed
d = json.loads(get("https://api.alternative.me/fng/?limit=0"))["data"]
ts = sorted(int(x["timestamp"]) for x in d)
span("Fear & Greed (daily)", D(ts[0]), D(ts[-1]), len(d), "BTC-wide, partly price-derived")

# blockchain.info charts (BTC on-chain)
for cid, label in [("hash-rate", "BTC hash rate"),
                   ("n-unique-addresses", "BTC active addresses"),
                   ("n-transactions", "BTC tx/day"),
                   ("miners-revenue", "BTC miner revenue")]:
    v = json.loads(get("https://api.blockchain.info/charts/%s?timespan=all&format=json&sampled=true" % cid))["values"]
    span(label, D(v[0]["x"]), D(v[-1]["x"]), len(v), "on-chain, BTC only")

# DefiLlama
sc = json.loads(get("https://stablecoins.llama.fi/stablecoincharts/all"))
t = sorted(int(x["date"]) for x in sc)
span("Stablecoin total supply", D(t[0]), D(t[-1]), len(sc), "flows proxy, market-wide")

tv = json.loads(get("https://api.llama.fi/v2/historicalChainTvl/Ethereum"))
t = sorted(int(x["date"]) for x in tv)
span("Ethereum chain TVL", D(t[0]), D(t[-1]), len(tv), "on-chain, ETH")

# OKX derived stats
for path, label in [
        ("rubik/stat/contracts/long-short-account-ratio?ccy=BTC&period=1D", "OKX long/short acct ratio"),
        ("rubik/stat/taker-volume?ccy=BTC&instType=SPOT&period=1D", "OKX taker buy/sell volume")]:
    r = json.loads(get("https://www.okx.com/api/v5/%s" % path))
    rows = r.get("data", [])
    if rows:
        t = sorted(int(x[0]) for x in rows)
        span(label, D(t[0] / 1000), D(t[-1] / 1000), len(rows), "CAPPED by API")

# FRED macro
csv = get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10").strip().splitlines()
if len(csv) > 2:
    f, l = csv[1].split(",")[0], csv[-1].split(",")[0]
    print("  %-30s %s -> %s  %6.2f y  n=%-7s %s"
          % ("FRED DGS10 (10y yield)", f, l,
             (dt.date.fromisoformat(l) - dt.date.fromisoformat(f)).days / 365.25,
             len(csv) - 1, "macro, no key"))

print()
print("=" * 92)
print("For contrast — what the PERP sources actually give (measured earlier)")
print("=" * 92)
print("  OKX funding rate                2026-05-25 -> now     0.26 y   (3-month API cap)")
print("  OKX open interest (daily)       2026-03-01 -> now     0.49 y   (180-row cap)")
print("  Kraken Futures funding (hourly) 2025-08-27 -> now     1.00 y   (365-day cap)")
print("  Binance fapi (full history)     BLOCKED http 451 (geo)")
print("  Bybit                           BLOCKED http 403 (CloudFront geo)")
