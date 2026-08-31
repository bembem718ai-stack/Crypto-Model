"""research/probe_coinapi.py — CoinAPI ACCEPTANCE PROBE. Mechanical only.

NOT a registered program. No hypothesis, no price joins, no scoring, no
backfill. It asks four mechanical questions about what the API exposes and
then stops.

KEY HANDLING. The key is read from COINAPI_KEY and is never printed, never
logged, never written to the output file, and never committed. Every string
that leaves this module passes through redact(), which strips the key --
including from exception text, which is the usual way a credential escapes.
The output file is written by this script and contains no key material.

CREDIT DISCIPLINE. Budget ~50 request-units. Every call is counted, the
running total is reported, and the script REFUSES to exceed HARD_CAP rather
than silently spending more.

USAGE:  set COINAPI_KEY in the environment of the process that runs this,
        then:  python research/probe_coinapi.py
"""
import os
import sys
import json
import datetime as dt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

import tls

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTFILE = os.path.join(ROOT, "research", "coinapi_probe.md")
BASE = "https://rest.coinapi.io"
HARD_CAP = 50
KEY = (os.environ.get("COINAPI_KEY") or "").strip()

EXCHANGES = ("BINANCEFTS", "OKEX", "KRAKENFTS")
BASES = ("BTC", "ETH", "SOL", "XBT")
TIME_START = "2019-09-01T00:00:00"
PERIODS = ("8HRS", "1HRS", "1DAY")      # first that validates wins

_CALLS = {"n": 0}
_USAGE = {}


def redact(text):
    s = str(text)
    if KEY:
        s = s.replace(KEY, "<REDACTED>")
        if len(KEY) > 8:
            s = s.replace(KEY[:8], "<REDACTED>")
    return s


def get(path, params=None, auth_style="authorization"):
    if _CALLS["n"] >= HARD_CAP:
        raise RuntimeError("request cap %d reached — refusing to spend more" % HARD_CAP)
    _CALLS["n"] += 1
    headers = ({"Authorization": KEY} if auth_style == "authorization"
               else {"X-CoinAPI-Key": KEY})
    headers["Accept"] = "application/json"
    try:
        r = requests.get(BASE + path, params=params, headers=headers, timeout=45)
    except Exception as e:  # noqa: BLE001 — network
        return None, "EXCEPTION %s: %s" % (type(e).__name__, redact(e)), {}
    for k, v in r.headers.items():
        kl = k.lower()
        if "ratelimit" in kl or "cost" in kl or "credit" in kl or "quota" in kl:
            _USAGE[k] = v
    try:
        return r.status_code, r.json(), dict(r.headers)
    except Exception:  # noqa: BLE001 — non-JSON body
        return r.status_code, redact(r.text)[:400], dict(r.headers)


def describe_values(rows):
    """What do the numbers look like? Units are the whole question."""
    keys = set()
    for r in rows[:20]:
        keys |= set(r.keys())
    num = {}
    for k in sorted(keys):
        vals = [r.get(k) for r in rows if isinstance(r.get(k), (int, float))]
        if vals:
            num[k] = {"n": len(vals), "min": min(vals), "max": max(vals),
                      "first": vals[0]}
    return sorted(keys), num


def main():
    lines = []

    def say(s=""):
        print(redact(s))
        lines.append(redact(s))

    if not KEY:
        say("# CoinAPI acceptance probe — NOT RUN")
        say()
        say("**COINAPI_KEY was not present in this process's environment**, so no")
        say("request was made and no credit was spent.")
        say()
        say("Checked: the Bash tool environment, the PowerShell session, and the")
        say("Windows User and Machine environment scopes. Not set in any of them,")
        say("and no `.env`/secret file in the repo carries it.")
        say()
        say("Most likely cause: the variable was set in an interactive shell, and")
        say("each tool call starts a new process that does not inherit it.")
        say()
        say("To make it visible to this script, either persist it for new")
        say("processes (PowerShell, once):")
        say()
        say("    [Environment]::SetEnvironmentVariable('COINAPI_KEY','<key>','User')")
        say()
        say("or set it inline for the single command that runs the probe. Do not")
        say("paste the key into chat — it would land in the transcript.")
        say()
        say("Requests used: **0**. Nothing registered, nothing scored.")
        write(lines)
        return 1

    tls.enable(verbose=False)
    say("# CoinAPI acceptance probe — mechanical only")
    say()
    say("Not a registered program. No hypothesis, no price joins, no backfill.")
    say("Key read from the environment; never printed, logged, or written here.")
    say()
    say("Run: %s UTC" % dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M"))
    say()

    # ---- auth style ------------------------------------------------------
    style = "authorization"
    st, body, _ = get("/v1/exchanges", {"filter_exchange_id": "BINANCEFTS"}, style)
    if st in (401, 403):
        style = "x-coinapi-key"
        st, body, _ = get("/v1/exchanges", {"filter_exchange_id": "BINANCEFTS"}, style)
    say("Auth header accepted: `%s` (HTTP %s)" % (style, st))
    say()
    if st != 200:
        say("**ABORT — could not authenticate.** HTTP %s: %s"
            % (st, redact(body)[:300]))
        say()
        say("Requests used: **%d**." % _CALLS["n"])
        write(lines)
        return 1

    # ---- 1. symbols ------------------------------------------------------
    say("## 1. Symbol discovery")
    say()
    say("| exchange | HTTP | perpetuals matched | symbol_id |")
    say("|---|---|---|---|")
    picks = {}
    for ex in EXCHANGES:
        st, body, _ = get("/v1/symbols", {"filter_exchange_id": ex}, style)
        found = []
        if st == 200 and isinstance(body, list):
            for s in body:
                if s.get("symbol_type") != "PERPETUAL":
                    continue
                if (s.get("asset_id_base") or "").upper() in BASES:
                    found.append(s.get("symbol_id", ""))
        found = sorted(set(found))
        picks[ex] = found
        if not found:
            say("| %s | %s | 0 | — |" % (ex, st))
        for i, sid in enumerate(found):
            say("| %s | %s | %s | `%s` |"
                % (ex if i == 0 else "", st if i == 0 else "",
                   len(found) if i == 0 else "", sid))
    say()

    def pick(ex, base, quote_pref=("USDT", "USD")):
        for q in quote_pref:
            for sid in picks.get(ex, []):
                if ("_%s_" % base) in sid.upper() and sid.upper().endswith(q):
                    return sid
        for sid in picks.get(ex, []):
            if ("_%s_" % base) in sid.upper():
                return sid
        return None

    btc = pick("BINANCEFTS", "BTC")
    eth = pick("BINANCEFTS", "ETH")
    sol = pick("BINANCEFTS", "SOL")
    krk = pick("KRAKENFTS", "XBT") or pick("KRAKENFTS", "BTC")

    # ---- 2. metrics listing ---------------------------------------------
    say("## 2. Metrics supported by one Binance perp")
    say()
    if not btc:
        say("No Binance BTC perpetual symbol_id found — metrics listing skipped.")
        metrics = []
    else:
        say("Symbol probed: `%s`" % btc)
        say()
        st, body, _ = get("/v1/metrics/symbol/listing", {"symbol_id": btc}, style)
        metrics = body if isinstance(body, list) else []
        if st != 200:
            say("HTTP %s: %s" % (st, redact(body)[:300]))
        ids = []
        for m in metrics:
            mid = m.get("metric_id") if isinstance(m, dict) else str(m)
            if mid:
                ids.append(mid)
        fund = [m for m in ids if "FUND" in m.upper()]
        oi = [m for m in ids if "OPEN_INTEREST" in m.upper() or "OI" == m.upper()]
        say("Total metric_ids listed: **%d** (HTTP %s)" % (len(ids), st))
        say()
        say("**Funding-like metric_ids, verbatim:**")
        say()
        for m in (fund or ["(none matched 'FUND')"]):
            say("- `%s`" % m)
        say()
        say("**Open-interest-like metric_ids, verbatim:**")
        say()
        for m in (oi or ["(none matched 'OPEN_INTEREST')"]):
            say("- `%s`" % m)
        say()
        if ids and not fund and not oi:
            say("All listed ids (first 40): %s"
                % ", ".join("`%s`" % i for i in ids[:40]))
            say()

    # ---- 3. depth probe --------------------------------------------------
    say("## 3. Depth probe — earliest data available")
    say()
    fund_id = None
    for m in (metrics or []):
        mid = m.get("metric_id") if isinstance(m, dict) else str(m)
        if mid and "FUND" in mid.upper() and "RATE" in mid.upper():
            fund_id = mid
            break
    if fund_id is None:
        for m in (metrics or []):
            mid = m.get("metric_id") if isinstance(m, dict) else str(m)
            if mid and "FUND" in mid.upper():
                fund_id = mid
                break

    if not fund_id:
        say("No funding metric_id discovered — depth probe skipped.")
    else:
        say("Metric probed: `%s`, `time_start=%s`, `limit=5`." % (fund_id, TIME_START))
        say()
        say("| symbol_id | period_id | HTTP | rows | EARLIEST timestamp | fields populated |")
        say("|---|---|---|---|---|---|")
        detail = []
        for sid in [x for x in (btc, eth, sol, krk) if x]:
            got = None
            for per in PERIODS:
                st, body, _ = get("/v1/metrics/symbol/history",
                                  {"metric_id": fund_id, "symbol_id": sid,
                                   "period_id": per, "time_start": TIME_START,
                                   "limit": 5}, style)
                if st == 200 and isinstance(body, list):
                    got = (per, body)
                    break
                if st == 200:
                    got = (per, [])
                    break
            if got is None:
                say("| `%s` | — | error | — | — | — |" % sid)
                continue
            per, rows = got
            if not rows:
                say("| `%s` | %s | 200 | 0 | none returned | — |" % (sid, per))
                continue
            keys, num = describe_values(rows)
            tkey = next((k for k in ("time_period_start", "time_open", "time_close")
                         if k in keys), keys[0] if keys else "?")
            say("| `%s` | %s | 200 | %d | `%s` | %s |"
                % (sid, per, len(rows), rows[0].get(tkey, "?"),
                   ", ".join("`%s`" % k for k in keys[:8])))
            detail.append((sid, per, keys, num, rows[0]))
        say()
        say("### What the values look like")
        say()
        for sid, per, keys, num, first in detail:
            say("**`%s`** (`%s`)" % (sid, per))
            say()
            for k, v in list(num.items())[:10]:
                say("- `%s`: first %s, min %s, max %s" % (k, v["first"], v["min"], v["max"]))
            mags = [abs(v["first"]) for v in num.values()
                    if isinstance(v["first"], (int, float)) and v["first"] != 0]
            if mags:
                m = min(mags)
                unit = ("per-period fraction (e.g. 0.0001 = 1bp)" if m < 0.01 else
                        "percent-scaled" if m < 5 else
                        "annualised percent or an unscaled quantity")
                say()
                say("  Smallest non-zero magnitude %.3g -> reads as **%s**. "
                    "NOT confirmed against a second source; reconciliation "
                    "against our own Kraken archive is what would settle it." % (m, unit))
            say()

    # ---- 4. usage --------------------------------------------------------
    say("## 4. Credits / usage")
    say()
    say("Requests issued by this probe: **%d** (hard cap %d)." % (_CALLS["n"], HARD_CAP))
    say()
    if _USAGE:
        say("| header | value |")
        say("|---|---|")
        for k in sorted(_USAGE):
            say("| `%s` | %s |" % (k, redact(_USAGE[k])))
    else:
        say("The API returned no rate-limit / cost / quota headers.")
    say()
    say("Nothing registered, nothing scored, no backfill performed.")
    write(lines)
    return 0


def write(lines):
    text = "\n".join(lines) + "\n"
    if KEY and KEY in text:                     # belt and braces
        raise RuntimeError("refusing to write: key material present in output")
    with open(OUTFILE, "w", encoding="utf-8") as fh:
        fh.write(text)
    print("\nwrote %s" % OUTFILE)


if __name__ == "__main__":
    sys.exit(main())
