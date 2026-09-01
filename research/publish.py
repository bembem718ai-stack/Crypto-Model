"""research/publish.py — episode alerts and the monthly transparency post.

READ-ONLY AGAINST THE LIVE SIGNAL PATH. This module consumes
`signal_log.csv` and `signal_outcomes.csv` and emits TEXT. It writes nothing
the signal path reads, imports no live decision code, and cannot influence a
signal. **No Discord API, no tokens, no automation** — a human posts what
this generates.

docs/claims.md's WORDING section is the SOURCE OF TRUTH. No text emitted here
may make a claim outside its SUPPORTED list.

THE ONE PLACE THIS DEPARTS FROM THE TEMPLATES, AND WHY
------------------------------------------------------
claims.md's templates carry a frozen tally ("8 closed long episodes, 3 target
/ 5 stop, +1.00R net"). That was true when the document was written. **The
DISCLOSURES are reproduced verbatim; the NUMBERS are computed live from
`signal_outcomes.csv`.** A template that hard-codes its own record starts
publishing a false one the moment an episode resolves, and a stale tally is a
claim outside the SUPPORTED list even though every word of it was once true.

WHAT NEVER PUBLISHES
--------------------
* **Shorts.** The live path runs `--long-only`; shorts are logged and never
  issued. The 0-for-11 short record is why.
* **Refused rows.** `REFUSED_UNTRADABLE` (fails #167 tradability) and
  `SKIPPED_COST_FLOOR` (stop tighter than the 0.80% floor, so costs would
  exceed 10% of 1R) are refusals, not signals.
* **WATCH / AVOID.** Not a signal.
* **The shadow basket.** `shadow_log.csv` is never read here and is asserted
  absent from this module by test. It is research, has published nothing, and
  its evaluation is sealed until 30 episodes.
"""
import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTCOMES = os.path.join(ROOT, "signal_outcomes.csv")
SIGNAL_LOG = os.path.join(ROOT, "signal_log.csv")

PUBLISHED_TIERS = ("BUY", "STRONG_BUY")
REFUSALS = ("REFUSED_UNTRADABLE", "SKIPPED_COST_FLOOR")
EPISODE_THRESHOLD = 15          # claims.md's "not enough trades" bar
REPO = "https://github.com/bembem718ai-stack/Crypto-Model"


# ----------------------------------------------------------------------
# WHAT MAY BE PUBLISHED
# ----------------------------------------------------------------------
def is_publishable(row) -> bool:
    """Long-only, published tiers only, refusals excluded."""
    decision = str(row.get("decision", "")).upper()
    direction = str(row.get("direction", "")).upper()
    if decision in REFUSALS:
        return False
    if direction not in PUBLISHED_TIERS:
        return False
    return decision in PUBLISHED_TIERS


# ----------------------------------------------------------------------
# THE LIVE RECORD — computed, never hard-coded
# ----------------------------------------------------------------------
def _streak(outcomes):
    """Longest run of consecutive losses."""
    best = cur = 0
    for o in outcomes:
        if str(o) in ("stop", "ambiguous_stop"):
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def load_record(path=OUTCOMES, log_path=SIGNAL_LOG):
    d = pd.read_csv(path)
    closed = d[d["status"] == "closed"].copy()
    closed = closed.sort_values("entry_time_utc")
    lon = closed[closed["side"] == "long"]
    sho = closed[closed["side"] == "short"]

    def w(x):
        return int((x["outcome"] == "target").sum())

    def l(x):
        return int(x["outcome"].isin(["stop", "ambiguous_stop"]).sum())

    sb = 0
    try:
        lg = pd.read_csv(log_path, usecols=["direction"])
        sb = int((lg["direction"] == "STRONG_BUY").sum())
    except Exception:                                   # noqa: BLE001
        pass

    return {"long_n": len(lon), "long_wins": w(lon), "long_losses": l(lon),
            "long_net_r": float(lon["pnl_r"].sum()),
            "long_streak": _streak(lon["outcome"]),
            "short_n": len(sho), "short_wins": w(sho),
            "short_net_r": float(sho["pnl_r"].sum()),
            "all_n": len(closed), "all_wins": w(closed), "all_losses": l(closed),
            "all_net_r": float(closed["pnl_r"].sum()),
            "all_streak": _streak(closed["outcome"]),
            "strong_buy_log_rows": sb,
            "tickers": dict(closed["ticker"].value_counts())}


def _record_line(r):
    """The one-line published record, in claims.md's own phrasing."""
    return ("%d closed long episodes, %d target / %d stop, %+.2fR net"
            % (r["long_n"], r["long_wins"], r["long_losses"], r["long_net_r"]))


def _px(v):
    return "—" if v != v else format(round(float(v)), ",")


# ----------------------------------------------------------------------
# OPEN ALERT
# ----------------------------------------------------------------------
def open_alert(ep, record):
    """First confirmed bar of an episode. Text only."""
    tier = str(ep.get("entry_direction", "BUY")).upper()
    if tier not in PUBLISHED_TIERS:
        raise ValueError("open_alert called for a non-published tier: %s" % tier)
    rr = 2.667 if tier == "STRONG_BUY" else 2.0
    geom = ("wider target, same stop, 15-day max hold" if tier == "STRONG_BUY"
            else "ATR-derived, 15-day max hold")
    L = ["%s — %s" % (ep["ticker"], tier),
         "Score %.1f / 100   (bar is 60)" % float(ep.get("entry_score", float("nan"))),
         "Entry %s   Target %s   Stop %s"
         % (_px(ep["entry_price"]), _px(ep["target_price"]), _px(ep["stop_price"])),
         "Risk:reward %s : 1   |   %s" % (("2.667" if tier == "STRONG_BUY" else "2.0"), geom),
         ""]
    if tier == "STRONG_BUY":
        # claims.md (c) — verbatim disclosure, live counts substituted
        L += ["STRONG_BUY is the model's rarest tier and it is NOT a validated edge.",
              "Read this before treating it as a stronger signal:",
              "  - It has fired %d times in the entire live log." % record["strong_buy_log_rows"],
              "  - Exactly one live episode has ever peaked at STRONG_BUY. It stopped out",
              "    at -1.0R.",
              "  - In backtest it looks strong (78% target rate on BTC against a ~35%",
              "    baseline) but that is 18 trades from 2 independent episodes, and the",
              "    project's own concentration test cannot be computed on it at all.",
              "  - Across 82 tickers, zero reach enough trades to measure this tier.",
              "",
              "The wider target is a geometry choice, not a confidence measurement.",
              "Outcome will be added to the public tally either way."]
    else:
        # claims.md (b) — verbatim, live record substituted
        L += ["This is a research signal, published as-is and tracked publicly.",
              "Live record to date: %s." % _record_line(record),
              "That is not enough trades to establish an edge, in either direction.",
              "No claim is made that this trade will work.",
              "Outcome will be added to the public tally either way."]
    return "\n".join(L)


# ----------------------------------------------------------------------
# CLOSE ALERT
# ----------------------------------------------------------------------
def close_alert(ep, record):
    """Resolution of an episode. Text only."""
    out = str(ep.get("outcome", "")).lower()
    label = {"target": "TARGET", "stop": "STOP",
             "ambiguous_stop": "STOP (ambiguous bar)",
             "timeout": "TIMEOUT"}.get(out, out.upper())
    tier = str(ep.get("entry_direction", "BUY")).upper()
    peak = str(ep.get("peak_direction", tier)).upper()
    L = ["%s — CLOSED: %s" % (ep["ticker"], label),
         "Opened %s as %s%s"
         % (str(ep.get("entry_time_utc", ""))[:16], tier,
            ("" if peak == tier else ", peaked at %s" % peak)),
         "Entry %s   Exit basis %s   Held %.1f days"
         % (_px(ep["entry_price"]),
            _px(ep["target_price"] if out == "target" else ep["stop_price"]),
            float(ep.get("days_held", float("nan")))),
         "Result: %+.2fR" % float(ep.get("pnl_r", float("nan"))),
         "",
         "Updated live record: %s." % _record_line(record),
         "That is not enough trades to establish an edge, in either direction.",
         "Outcome added to the public tally."]
    return "\n".join(L)


# ----------------------------------------------------------------------
# MONTHLY TRANSPARENCY POST
# ----------------------------------------------------------------------
def premia_block(month_label):
    """#257's monthly summary, or None if it cannot be built.

    RETURNS None RATHER THAN RAISING. The monthly tally is the post's
    reason to exist; a measurement section is an addition to it. If the
    derivatives archive is missing, stale or unreadable, the post must
    still go out with the record intact. dry_run() reports whether the
    block was present, so a silent disappearance shows up in the weekly
    audit instead of being discovered by its absence.
    """
    try:
        import premia
        return premia.build()["summary"]
    except Exception:                                 # noqa: BLE001
        return None


# THE TWO LINES THAT MUST PRECEDE ANY PREMIA NUMBER IN A PUBLISHED POST.
# Verbatim, not paraphrased: they are the whole reason these numbers are
# safe to publish beside a signal record. Without them a reader has every
# reason to assume a measured double-digit yield is something this service
# is offering them.
PREMIA_PREAMBLE = [
    "**These are RISK PREMIA — the fee paid to whoever bears crash and",
    "balance-sheet risk. They are NOT signals, NOT an edge this project has,",
    "and NOT tradeable by this operator: each needs venue access, posted",
    "margin and a balance sheet this project does not have.**",
    "**The variance risk premium is NOT COMPUTABLE yet** — our options",
    "archive is too young for any implied reading to have a realised",
    "counterpart — and it stays marked so until it matures.",
]


def transparency_post(record, month_label, premia=None):
    """The full honest tally, per claims.md's LIVE RECORD rules.

    BOTH records appear side by side, with the standing explanation. The
    published-long row is what a follower experienced; the full-log row is
    the honest denominator for how often the model was wrong.

    `premia` is #257's monthly measurement block. Pass a string to
    include it, None to build it, or False to omit it. It is separated
    from the record by its own heading and preceded by PREMIA_PREAMBLE,
    because the one genuine hazard in publishing it is a reader taking a
    measured market yield for something on offer here.
    """
    r = record
    lw = (100.0 * r["long_wins"] / r["long_n"]) if r["long_n"] else float("nan")
    aw = (100.0 * r["all_wins"] / r["all_n"]) if r["all_n"] else float("nan")
    remaining = max(0, EPISODE_THRESHOLD - r["long_n"])
    L = [
        "**Monthly transparency post — %s**" % month_label,
        "",
        "Every signal this service published, and every one it resolved.",
        "Losses included, because a tally without them is not a tally.",
        "",
        "```",
        "                        n   win   loss   win%    net R   worst losing streak",
        "LONG (published)     %4d  %4d   %4d  %5.1f%%  %+7.2fR   %d"
        % (r["long_n"], r["long_wins"], r["long_losses"], lw,
           r["long_net_r"], r["long_streak"]),
        "SHORT (logged only)  %4d  %4d   %4d  %5.1f%%  %+7.2fR   —"
        % (r["short_n"], r["short_wins"], r["short_n"] - r["short_wins"],
           (100.0 * r["short_wins"] / r["short_n"]) if r["short_n"] else 0.0,
           r["short_net_r"]),
        "ALL (full log)       %4d  %4d   %4d  %5.1f%%  %+7.2fR   %d"
        % (r["all_n"], r["all_wins"], r["all_losses"], aw,
           r["all_net_r"], r["all_streak"]),
        "```",
        "",
        "**Your number is the LONG row.** The live path runs long-only, so the",
        "short episodes were logged by the outcome tracker and never issued as",
        "signals. Nobody was ever told to take one.",
        "",
        "**So why show the full log at all?** Three reasons, none of them padding:",
        "",
        "1. The short suppression is a decision, and decisions should be",
        "   auditable. The %d-for-%d short record is the evidence that switching"
        % (r["short_wins"], r["short_n"]),
        "   shorts off was right. Deleting it would delete the justification.",
        "2. It is the honest denominator for *how often is the model wrong*. The",
        "   model formed a directional opinion %d times and %d resolved against it."
        % (r["all_n"], r["all_losses"]),
        "3. Publishing only the filtered row is how selective reporting starts.",
        "   The filter here is defensible and pre-existing. It would stop being",
        "   defensible the moment it were chosen *because* it improved the number.",
        "",
        "**Sample size: %d of %d published episodes toward the point where this"
        % (r["long_n"], EPISODE_THRESHOLD),
        "record could begin to mean anything.** %s"
        % ("%d to go." % remaining if remaining else
           "Threshold reached — it is still a small sample."),
        "Below that, the tally is a record of what happened, not evidence of an",
        "edge in either direction.",
        "",
    ]

    block = premia_block(month_label) if premia is None else premia
    if block:
        L += ["---", "", "### What the market paid — measured, not traded", ""]
        L += PREMIA_PREAMBLE
        L += ["", block, "",
              "Measured from archives this project collects itself; the full",
              "dated table with every uncertainty interval is in docs/premia.md.",
              ""]

    L += [
        "---",
        "**The research record is public at %s** — every hypothesis is written" % REPO,
        "down before it runs and reported afterwards whether it worked or not.",
        "**The project currently holds zero supported edge claims.**",
        "**This service publishes signals, not promises.** Not financial advice.",
    ]
    return "\n".join(L)


# ----------------------------------------------------------------------
# DRY RUN — wired into the weekly audit so format rot fails in CI
# ----------------------------------------------------------------------
def dry_run(outcomes=OUTCOMES, log_path=SIGNAL_LOG, verbose=False):
    """Render both generators and report shape. Raises on breakage."""
    rec = load_record(outcomes, log_path)
    post = transparency_post(rec, "dry-run")
    blk = premia_block("dry-run")
    d = pd.read_csv(outcomes)
    pub = d[(d["side"] == "long") & (d["entry_direction"].isin(PUBLISHED_TIERS))]
    if not len(pub):
        raise ValueError("no publishable episode to render")
    ep = pub.iloc[-1].to_dict()
    o = open_alert(ep, rec)
    c = close_alert(ep, rec)
    for name, txt in (("transparency", post), ("open", o), ("close", c)):
        if not txt or len(txt) < 50:
            raise ValueError("%s render is empty or truncated" % name)
        low = txt.lower()
        for banned in ("guaranteed", "risk-free", "profitable",
                       "financial advice." if name != "transparency" else "\x00"):
            if banned in low:
                raise ValueError("%s render contains a forbidden claim: %s"
                                 % (name, banned))
    if verbose:
        print(post)
        print("\n" + "=" * 60 + "\n")
        print(o)
        print("\n" + "=" * 60 + "\n")
        print(c)
    # THE PREAMBLE IS NOT OPTIONAL. If the block rendered, every one of its
    # lines must be in the post -- a premia number published without the
    # "not signals, not tradeable" framing is the one way this section can
    # do harm, so it fails here rather than reaching a subscriber.
    if blk:
        if blk not in post:
            raise ValueError("premia block built but is missing from the post")
        for line in PREMIA_PREAMBLE:
            if line not in post:
                raise ValueError("premia block published without its "
                                 "preamble line: %s" % line[:60])
        if "NOT COMPUTABLE" not in post:
            raise ValueError("premia block omits the VRP maturity caveat")
    return {"ok": True, "transparency_chars": len(post),
            "sample_open": o, "sample_close": c, "record": rec,
            "premia_block": bool(blk),
            "premia_chars": len(blk) if blk else 0}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mode", choices=("post", "alerts", "dry-run"))
    ap.add_argument("--outcomes", default=OUTCOMES)
    ap.add_argument("--log", default=SIGNAL_LOG)
    ap.add_argument("--month", default="")
    a = ap.parse_args()
    rec = load_record(a.outcomes, a.log)
    if a.mode == "post":
        print(transparency_post(rec, a.month or "current"))
    elif a.mode == "alerts":
        d = pd.read_csv(a.outcomes)
        pub = d[(d["side"] == "long") & (d["entry_direction"].isin(PUBLISHED_TIERS))]
        if not len(pub):
            print("no publishable episodes")
            return 0
        ep = pub.iloc[-1].to_dict()
        print(open_alert(ep, rec))
        print("\n" + "-" * 60 + "\n")
        print(close_alert(ep, rec))
    else:
        r = dry_run(a.outcomes, a.log, verbose=True)
        print("\nDRY RUN OK — transparency %d chars" % r["transparency_chars"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
