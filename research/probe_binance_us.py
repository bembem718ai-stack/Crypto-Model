"""
research/probe_binance_us.py -- PROBE ONLY.

(2) Every Binance.US spot USDT pair with >= 4 years of 4h history.
(3) 1h kline availability and depth for BTC/ETH/SOL.

One request per symbol for the earliest bar (startTime=0, limit=1), which
is what actually establishes listing depth. Nothing registered, nothing
scored.
"""
import subprocess
import json
import datetime as dt

BASE = "https://api.binance.us"
NOW = dt.datetime.now(dt.timezone.utc)


def get(url, timeout=30):
    try:
        p = subprocess.run(["curl", "-s", "-w", "\n%{http_code}",
                            "--max-time", str(timeout), url],
                           capture_output=True, text=True, timeout=timeout + 15)
    except subprocess.TimeoutExpired:
        return None, "000"
    out = p.stdout.rsplit("\n", 1)
    body, code = (out[0], out[1].strip()) if len(out) == 2 else (p.stdout, "000")
    if code != "200":
        return None, code
    try:
        return json.loads(body), code
    except Exception:
        return None, code


def first_bar(sym, interval):
    d, code = get("%s/api/v3/klines?symbol=%s&interval=%s&startTime=0&limit=1"
                  % (BASE, sym, interval))
    if not d:
        return None, code
    return dt.datetime.fromtimestamp(d[0][0] / 1000, dt.timezone.utc), code


def last_bar(sym, interval):
    d, code = get("%s/api/v3/klines?symbol=%s&interval=%s&limit=1" % (BASE, sym, interval))
    if not d:
        return None, code
    return dt.datetime.fromtimestamp(d[0][0] / 1000, dt.timezone.utc), code


if __name__ == "__main__":
    print("=" * 74)
    print("(3) Binance.US 1h klines for BTC/ETH/SOL")
    print("=" * 74)
    for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
        f, c1 = first_bar(sym, "1h")
        l, c2 = last_bar(sym, "1h")
        if f and l:
            yrs = (l - f).days / 365.25
            print("  %-9s 1h  %s -> %s  (~%.2f y, ~%d bars)"
                  % (sym, f.date(), l.date(), yrs, (l - f).total_seconds() / 3600))
        else:
            print("  %-9s 1h  FAILED (http %s/%s)" % (sym, c1, c2))

    print()
    print("=" * 74)
    print("(2) Binance.US spot USDT pairs with >= 4 years of 4h history")
    print("=" * 74)
    info, code = get("%s/api/v3/exchangeInfo" % BASE, timeout=60)
    if not info:
        raise SystemExit("exchangeInfo failed: http %s" % code)
    syms = [s["symbol"] for s in info["symbols"]
            if s.get("quoteAsset") == "USDT" and s.get("status") == "TRADING"
            and s.get("isSpotTradingAllowed")]
    syms.sort()
    print("  TRADING spot *USDT pairs on Binance.US: %d" % len(syms))
    print("  querying earliest 4h bar for each ...")

    rows, failed = [], []
    for i, s in enumerate(syms, 1):
        f, c = first_bar(s, "4h")
        if f is None:
            failed.append((s, c))
            continue
        rows.append((s, f, (NOW - f).days / 365.25))
        if i % 25 == 0:
            print("    %d/%d" % (i, len(syms)))

    rows.sort(key=lambda r: r[1])
    ok4 = [r for r in rows if r[2] >= 4.0]
    print()
    print("  RESULT: %d of %d pairs have >= 4 years of 4h history" % (len(ok4), len(rows)))
    if failed:
        print("  (%d symbols returned no kline data: %s)"
              % (len(failed), ", ".join(s for s, _ in failed[:10])))
    print()
    print("  %-13s %-12s %s" % ("symbol", "first 4h bar", "years"))
    print("  " + "-" * 40)
    for s, f, y in ok4:
        print("  %-13s %-12s %.2f" % (s, f.date(), y))

    with open("research/binance_us_universe.txt", "w", encoding="utf-8") as fh:
        fh.write("# Binance.US spot USDT pairs with >=4y of 4h history\n")
        fh.write("# probed %s\n" % NOW.strftime("%Y-%m-%d"))
        for s, f, y in ok4:
            fh.write("%s\t%s\t%.2f\n" % (s, f.date(), y))
    print("\n  wrote research/binance_us_universe.txt")

    print()
    print("  next 15 just BELOW the 4y bar (for reference):")
    below = [r for r in rows if r[2] < 4.0][:15]
    for s, f, y in below:
        print("    %-13s %-12s %.2f" % (s, f.date(), y))
