"""
research/probe_sources.py  -- PROBE ONLY. No hypotheses, no scoring.

Measures what external data is reachable from THIS machine and how much
history exists. Uses curl (Schannel / Windows cert store) rather than
requests, because a TLS-intercepting filter driver on this box
(SSLKEYLOGFILE=\\.\nllMonFltProxy) presents a root CA that the Windows
store trusts and Python's certifi bundle does not.

Nothing here is registered and nothing is scored.
"""
import subprocess
import json
import datetime as dt
import sys


def get(url, timeout=30):
    """curl -> (ok, parsed_json_or_text, http_code)."""
    try:
        p = subprocess.run(
            ["curl", "-s", "-w", "\n%{http_code}", "--max-time", str(timeout), url],
            capture_output=True, text=True, timeout=timeout + 15)
    except subprocess.TimeoutExpired:
        return False, "timeout", "000"
    out = p.stdout.rsplit("\n", 1)
    body = out[0] if len(out) == 2 else p.stdout
    code = out[1].strip() if len(out) == 2 else "000"
    if code != "200":
        return False, body[:160], code
    try:
        return True, json.loads(body), code
    except Exception:
        return True, body, code


def ms(d):
    return int(dt.datetime(*d, tzinfo=dt.timezone.utc).timestamp() * 1000)


def when(x):
    return dt.datetime.fromtimestamp(int(x) / 1000, dt.timezone.utc).strftime("%Y-%m-%d")


# ------------------------------------------------------------------ OKX
def okx_funding_span(inst):
    """Walk back through funding history to the true first record."""
    oldest, pages, cur = None, 0, None
    while pages < 400:
        url = ("https://www.okx.com/api/v5/public/funding-rate-history"
               "?instId=%s&limit=100" % inst)
        if cur:
            url += "&after=%d" % cur
        ok, d, code = get(url)
        if not ok or not isinstance(d, dict):
            return oldest, pages, "http " + code
        rows = d.get("data", [])
        if not rows:
            break
        ts = [int(r["fundingTime"]) for r in rows]
        lo = min(ts)
        if oldest is not None and lo >= oldest:
            break
        oldest, cur = lo, lo
        pages += 1
    return oldest, pages, "ok"


def okx_oi_span(ccy):
    ok, d, code = get("https://www.okx.com/api/v5/rubik/stat/contracts/"
                      "open-interest-volume?ccy=%s&period=1D" % ccy)
    if not ok or not isinstance(d, dict):
        return None, None, 0, "http " + code
    rows = d.get("data", [])
    if not rows:
        return None, None, 0, "empty"
    ts = [int(r[0]) for r in rows]
    return min(ts), max(ts), len(rows), "ok"


# --------------------------------------------------------------- Kraken
def kraken_funding_span(sym):
    ok, d, code = get("https://futures.kraken.com/derivatives/api/v4/"
                      "historicalfundingrates?symbol=%s" % sym, timeout=60)
    if not ok or not isinstance(d, dict):
        return None, None, 0, "http " + code
    rows = d.get("rates", [])
    if not rows:
        return None, None, 0, "empty"
    t = sorted(r["timestamp"] for r in rows)
    return t[0][:10], t[-1][:10], len(rows), "ok"


if __name__ == "__main__":
    print("=" * 78)
    print("OKX perpetual funding history (8h settlements)")
    print("=" * 78)
    for inst in ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"]:
        oldest, pages, st = okx_funding_span(inst)
        if oldest:
            yrs = (dt.datetime.now(dt.timezone.utc)
                   - dt.datetime.fromtimestamp(oldest / 1000, dt.timezone.utc)).days / 365.25
            print("  %-16s earliest %s  (~%.2f y, %d pages x100)  [%s]"
                  % (inst, when(oldest), yrs, pages, st))
        else:
            print("  %-16s FAILED [%s]" % (inst, st))

    print()
    print("=" * 78)
    print("OKX open-interest history (daily)")
    print("=" * 78)
    for ccy in ["BTC", "ETH", "SOL"]:
        lo, hi, n, st = okx_oi_span(ccy)
        if lo:
            print("  %-6s %s -> %s  (%d rows, ~%.2f y)  [%s]"
                  % (ccy, when(lo), when(hi), n, (hi - lo) / 86400000 / 365.25, st))
        else:
            print("  %-6s FAILED [%s]" % (ccy, st))

    print()
    print("=" * 78)
    print("Kraken Futures funding history")
    print("=" * 78)
    for sym in ["PF_XBTUSD", "PF_ETHUSD", "PF_SOLUSD", "PI_XBTUSD", "PI_ETHUSD"]:
        lo, hi, n, st = kraken_funding_span(sym)
        if lo:
            span = (dt.date.fromisoformat(hi) - dt.date.fromisoformat(lo)).days / 365.25
            print("  %-11s %s -> %s  (%d rows, ~%.2f y)  [%s]" % (sym, lo, hi, n, span, st))
        else:
            print("  %-11s FAILED [%s]" % (sym, st))
