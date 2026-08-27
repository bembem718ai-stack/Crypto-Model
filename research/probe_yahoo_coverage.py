"""
research/probe_yahoo_coverage.py -- PROBE ONLY.

pipeline.run_backtest builds its daily frame from Yahoo
(to_yahoo_crypto_symbol -> epm.analyze) and INNER-JOINs it against the
Binance 4h squeeze history. So the incumbent can only run on a Binance.US
pair that Yahoo ALSO lists with comparable depth. This measures that
overlap for the 93 pairs with >=4y of Binance.US 4h history.

A price-only research model built on research/harness.py has no such
constraint -- it reads Binance klines only.
"""
import subprocess
import json
import datetime as dt

SRC = "research/binance_us_universe.txt"


def yahoo_span(sym):
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/%s"
           "?range=max&interval=1d" % sym)
    p = subprocess.run(["curl", "-s", "--max-time", "25",
                        "-H", "User-Agent: Mozilla/5.0", url],
                       capture_output=True, text=True, timeout=45)
    try:
        d = json.loads(p.stdout)
    except Exception:
        return None, "unparseable"
    ch = d.get("chart") or {}
    if ch.get("error"):
        return None, (ch["error"] or {}).get("code", "error")
    res = ch.get("result")
    if not res:
        return None, "no result"
    ts = res[0].get("timestamp")
    if not ts:
        return None, "no timestamps"
    return dt.datetime.fromtimestamp(ts[0], dt.timezone.utc), "ok"


if __name__ == "__main__":
    pairs = []
    for line in open(SRC, encoding="utf-8"):
        if line.startswith("#"):
            continue
        s, first, yrs = line.split("\t")
        pairs.append((s, s[:-4], first, float(yrs)))   # strip USDT

    now = dt.datetime.now(dt.timezone.utc)
    ok, missing, shallow = [], [], []
    for i, (sym, base, bfirst, byrs) in enumerate(pairs, 1):
        ysym = base + "-USD"
        f, st = yahoo_span(ysym)
        if f is None:
            missing.append((sym, ysym, st))
        else:
            yyrs = (now - f).days / 365.25
            (ok if yyrs >= 4.0 else shallow).append((sym, ysym, f.date(), yyrs, byrs))
        if i % 20 == 0:
            print("  ...%d/%d" % (i, len(pairs)))

    print()
    print("=" * 78)
    print("Yahoo coverage of the 93 Binance.US pairs with >=4y of 4h history")
    print("=" * 78)
    print("  BOTH Binance.US >=4y AND Yahoo >=4y : %d" % len(ok))
    print("  Yahoo listed but <4y                : %d" % len(shallow))
    print("  NOT on Yahoo (incumbent cannot run) : %d" % len(missing))
    print()
    print("  Usable by the INCUMBENT (both feeds >=4y):")
    for sym, ysym, f, yy, by in sorted(ok, key=lambda r: -r[3]):
        print("    %-12s %-11s yahoo from %s (%.2fy)  binance %.2fy" % (sym, ysym, f, yy, by))
    if shallow:
        print()
        print("  Yahoo too shallow:")
        for sym, ysym, f, yy, by in shallow:
            print("    %-12s %-11s yahoo from %s (%.2fy)" % (sym, ysym, f, yy))
    if missing:
        print()
        print("  Absent from Yahoo:")
        print("   ", ", ".join(s for s, _, _ in missing))

    with open("research/incumbent_portable_universe.txt", "w", encoding="utf-8") as fh:
        fh.write("# Binance.US >=4y AND Yahoo >=4y -- runnable by pipeline.run_backtest\n")
        for sym, ysym, f, yy, by in sorted(ok, key=lambda r: -r[3]):
            fh.write("%s\t%s\t%s\t%.2f\n" % (sym, ysym, f, yy))
    print("\n  wrote research/incumbent_portable_universe.txt")
