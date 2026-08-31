"""research/reconcile_funding.py — Binance vs Kraken funding reconciliation.

DESCRIPTIVE RECORD. No hypothesis, no pass/fail threshold, nothing
registered, no price joins. Its only purpose is to be the record #220's
registration cites when it names its primary series.

CROSS-VENUE, NOT SAME-FEED. Binance USD-M perpetuals and Kraken Futures
perpetuals are different contracts on different venues with different
funding mechanics and different intervals. The rates SHOULD differ. Testing
equality would be testing the wrong thing, and a large mean difference is
not evidence of a defect. What is worth knowing is whether the two feeds
agree STRUCTURALLY -- do they rank the same days as expensive, do they agree
on sign, do their stamps land where the stated interval says.

THE LOCKBOX SPLIT (ruled 2026-08-31, stated because it constrains what is
computed where)
-------------------------------------------------------------------------
VALUES-based statistics -- Spearman, quintile agreement, sign agreement --
run on the PRE-LOCKBOX overlap only. STRUCTURE-only checks -- gap census,
UTC alignment, per-month event counts against the stated interval -- run on
the FULL overlap, because they read timestamps and counts and never a
funding VALUE inside the sealed span.

The reason is not squeamishness. #220's registration is drafted immediately
after this report, and its hypotheses are about funding PERCENTILES and
SIGNS. Reading the sealed funding DISTRIBUTION would be reading exactly the
quantity those hypotheses are about. The bright line -- no sealed values
read by research -- admits no carve-outs, so it is drawn at values and not
at "values that felt informative".

Timestamps and row counts are not the sealed quantity and never have been;
that is the established precedent this split relies on.
"""
import os
import sys
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DERIV = os.path.join(ROOT, "data", "derivatives")
OUT = os.path.join(ROOT, "research", "funding_reconciliation.md")

PAIRS = [("BTC", "BTCUSDT", "PF_XBTUSD"),
         ("ETH", "ETHUSDT", "PF_ETHUSD"),
         ("SOL", "SOLUSDT", "PF_SOLUSD")]
LOCKBOX_MONTHS = 6
QUINTILES = 5

LINES = []


def say(s=""):
    print(s)
    LINES.append(s)


def load():
    b = pd.read_csv(os.path.join(DERIV, "binance_funding.csv"))
    b["ts"] = pd.to_datetime(b["timestamp"], utc=True, format="mixed")
    k = pd.read_csv(os.path.join(DERIV, "kraken_funding.csv"))
    k["ts"] = pd.to_datetime(k["timestamp"], utc=True, format="mixed")
    return b, k


def daily_mean(df, col="funding_rate"):
    return df.set_index("ts")[col].resample("1D").mean()


def gap_census(ts, expected_hours):
    """Spacing census on timestamps ONLY. No values read."""
    d = ts.sort_values().diff().dropna().dt.total_seconds() / 3600.0
    vc = d.round(2).value_counts().sort_index()
    over = d[d > expected_hours + 0.01]
    return {"n": int(len(ts)), "modal_spacing_h": float(d.mode().iloc[0]) if len(d) else float("nan"),
            "spacings": {float(k): int(v) for k, v in list(vc.items())[:6]},
            "n_over_expected": int(len(over)),
            "largest_h": float(over.max()) if len(over) else 0.0,
            "total_hours_missing": float(max(0.0, (over - expected_hours).sum()))}


def main():
    b, k = load()

    # ---- window arithmetic ------------------------------------------------
    overlap_start = max(b["ts"].min(), k["ts"].min())
    overlap_end = min(b["ts"].max(), k["ts"].max())
    dataset_end = k["ts"].max()
    lockbox_start = dataset_end - pd.DateOffset(months=LOCKBOX_MONTHS)
    values_end = min(overlap_end, lockbox_start)

    say("# Funding reconciliation — Binance Vision vs Kraken Futures")
    say()
    say("Descriptive record. **No hypothesis, no pass/fail threshold, nothing")
    say("registered, no price joins.** Its purpose is to be the record #220's")
    say("registration cites when it names its primary series.")
    say()
    say("## Framing: cross-VENUE, not same-feed")
    say()
    say("Binance USD-M perpetuals and Kraken Futures perpetuals are different")
    say("contracts, on different venues, with different funding mechanics and")
    say("different intervals. **The rates should differ.** Testing equality")
    say("would test the wrong thing, and a large mean difference is not evidence")
    say("of a defect in either feed. What is worth knowing is whether the two")
    say("agree STRUCTURALLY: do they rank the same days expensive, do they agree")
    say("on sign, do their stamps land where the stated interval says.")
    say()

    say("## The lockbox split")
    say()
    say("| statistic class | window | reason |")
    say("|---|---|---|")
    say("| **VALUES** — Spearman, quintile agreement, sign agreement | `%s` -> `%s` | reads funding values |"
        % (overlap_start.date(), values_end.date()))
    say("| **STRUCTURE** — gap census, UTC alignment, event counts | `%s` -> `%s` (full overlap) | reads timestamps and counts only |"
        % (overlap_start.date(), overlap_end.date()))
    say()
    say("Dataset end `%s`; lockbox opens `%s` (end minus %d months)."
        % (dataset_end.date(), lockbox_start.date(), LOCKBOX_MONTHS))
    say()
    say("**Why the split is drawn at values and not at judgement.** #220's")
    say("registration is drafted immediately after this report, and its")
    say("hypotheses are about funding **percentiles and signs**. Reading the")
    say("sealed funding DISTRIBUTION would be reading exactly the quantity those")
    say("hypotheses are about. The bright line — no sealed values read by")
    say("research — admits no carve-outs, so it is drawn at *values*, not at")
    say("*values that felt informative*. Timestamps and row counts are not the")
    say("sealed quantity and never have been.")
    say()
    say("**Carried into #220's drafting:** #220 fixes its thresholds by")
    say("INHERITANCE from the locked #172–#186 verbatim — same rules, same")
    say("constants, new data, corrected null, its own Bonferroni. Nothing in its")
    say("registration is choosable at drafting time, so this reconciliation read")
    say("cannot anchor what is not being chosen.")
    say()

    # ---- VALUES (pre-lockbox only) ---------------------------------------
    say("## 1. VALUES-based agreement — pre-lockbox overlap only")
    say()
    say("| symbol | n days | Spearman (daily mean) | quintile agreement | ±1 quintile | sign agreement |")
    say("|---|---|---|---|---|---|")
    val_rows = []
    for label, bsym, ksym in PAIRS:
        bb = b[(b.symbol == bsym) & (b.ts >= overlap_start) & (b.ts < values_end)]
        kk = k[(k.symbol == ksym) & (k.ts >= overlap_start) & (k.ts < values_end)]
        if not len(bb) or not len(kk):
            say("| %s | 0 | — | — | — | — |" % label)
            continue
        db, dk = daily_mean(bb), daily_mean(kk)
        j = pd.concat([db.rename("bin"), dk.rename("krk")], axis=1).dropna()
        n = len(j)
        rho = float(j["bin"].corr(j["krk"], method="spearman"))
        qb = pd.qcut(j["bin"], QUINTILES, labels=False, duplicates="drop")
        qk = pd.qcut(j["krk"], QUINTILES, labels=False, duplicates="drop")
        exact = float((qb == qk).mean())
        within1 = float((abs(qb - qk) <= 1).mean())
        sign = float((np.sign(j["bin"]) == np.sign(j["krk"])).mean())
        val_rows.append((label, n, rho, exact, within1, sign))
        say("| **%s** | %d | **%+.3f** | %.1f%% | %.1f%% | %.1f%% |"
            % (label, n, rho, 100 * exact, 100 * within1, 100 * sign))
    say()
    say("Chance baselines, for reading the columns honestly: exact-quintile")
    say("agreement by chance is **20%**, within-one-quintile **~52%**, and sign")
    say("agreement would be **50%** only if signs were balanced. Funding is")
    say("predominantly positive, so a high sign-agreement number is close to")
    say("free — it is the WEAKEST of the three columns, not the headline.")
    say()

    # ---- STRUCTURE (full overlap) ----------------------------------------
    say("## 2. STRUCTURE-only checks — full overlap year")
    say()
    say("Timestamps and counts only. No funding value inside the sealed span is")
    say("read by anything below.")
    say()
    say("### Gap census, both feeds side by side")
    say()
    say("| symbol | feed | rows | modal spacing | spacings seen | gaps > expected | largest | hours missing |")
    say("|---|---|---|---|---|---|---|---|")
    for label, bsym, ksym in PAIRS:
        bb = b[(b.symbol == bsym) & (b.ts >= overlap_start) & (b.ts <= overlap_end)]
        kk = k[(k.symbol == ksym) & (k.ts >= overlap_start) & (k.ts <= overlap_end)]
        for feed, df, exp in (("Binance", bb, 8.0), ("Kraken", kk, 1.0)):
            if not len(df):
                say("| %s | %s | 0 | — | — | — | — | — |" % (label, feed))
                continue
            g = gap_census(df["ts"], exp)
            say("| %s | %s | %d | %.1fh | %s | %d | %.1fh | %.1fh |"
                % (label, feed, g["n"], g["modal_spacing_h"],
                   ", ".join("%.0fh×%d" % (kk2, vv)
                             for kk2, vv in list(g["spacings"].items())[:3]),
                   g["n_over_expected"], g["largest_h"], g["total_hours_missing"]))
    say()

    say("### UTC alignment — do Binance 8h stamps land where expected?")
    say()
    say("Binance's documented funding times are 00:00, 08:00 and 16:00 UTC.")
    say()
    say("| symbol | rows in overlap | on 00/08/16 UTC | off-schedule | distinct hours seen |")
    say("|---|---|---|---|---|")
    for label, bsym, _k in PAIRS:
        bb = b[(b.symbol == bsym) & (b.ts >= overlap_start) & (b.ts <= overlap_end)]
        if not len(bb):
            say("| %s | 0 | — | — | — |" % label)
            continue
        hrs = bb["ts"].dt.hour
        onsched = int(hrs.isin([0, 8, 16]).sum())
        mins = int((bb["ts"].dt.minute != 0).sum())
        say("| **%s** | %d | **%d (%.1f%%)** | %d | %s%s |"
            % (label, len(bb), onsched, 100 * onsched / len(bb),
               len(bb) - onsched, sorted(hrs.unique().tolist()),
               "" if not mins else " (%d rows off the hour)" % mins))
    say()

    say("### Per-month event counts vs the stated interval")
    say()
    say("Coverage test, not a row count: does the SUM of each month's stated")
    say("`funding_interval_hours` account for the hours in that month? That is")
    say("interval-aware, so a month that legitimately ran a denser schedule is")
    say("not flagged as broken.")
    say()
    say("| symbol | months in overlap | months fully covered | shortfalls |")
    say("|---|---|---|---|")
    for label, bsym, _k in PAIRS:
        bb = b[(b.symbol == bsym) & (b.ts >= overlap_start) & (b.ts <= overlap_end)].copy()
        if not len(bb):
            say("| %s | 0 | — | — |" % label)
            continue
        bb["_m"] = bb["ts"].dt.tz_localize(None).dt.to_period("M")
        ok, bad = 0, []
        for m, gm in bb.groupby("_m"):
            hrs = gm["ts"].dt.days_in_month.iloc[0] * 24
            cov = float(gm["funding_interval_hours"].sum())
            # boundary months of the overlap are partial by construction
            boundary = m in (bb["_m"].iloc[0], bb["_m"].iloc[-1])
            if abs(cov - hrs) <= 8 or boundary:
                ok += 1
            else:
                bad.append("%s (%.0f/%dh)" % (m, cov, hrs))
        say("| **%s** | %d | %d | %s |"
            % (label, bb["_m"].nunique(), ok,
               ", ".join(bad) if bad else "**none** (boundary months partial by construction)"))
    say()

    say("## 3. What this record does and does not establish")
    say()
    say("It is a **data-quality record**, not evidence about funding. It says")
    say("whether two independent feeds describe the same underlying phenomenon")
    say("closely enough that choosing one as a primary series is a defensible")
    say("choice rather than an arbitrary one. **No threshold is applied and no")
    say("verdict is reached**, deliberately: a pass rule here would be a")
    say("hypothesis, and this is not one.")
    say()
    say("The values section rests on the pre-lockbox overlap only: **%d paired "
        "days per symbol**, not the full overlap year."
        % (val_rows[0][1] if val_rows else 0))
    say()
    say("Nothing here is registered. Nothing here is scored. #220's registration")
    say("is drafted after this is read, and inherits its constants from")
    say("#172–#186 rather than choosing them.")

    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(LINES) + "\n")
    print("\nwrote %s" % OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
