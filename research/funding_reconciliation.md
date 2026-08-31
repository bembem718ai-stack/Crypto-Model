# Funding reconciliation — Binance Vision vs Kraken Futures

Descriptive record. **No hypothesis, no pass/fail threshold, nothing
registered, no price joins.** Its purpose is to be the record #220's
registration cites when it names its primary series.

## Framing: cross-VENUE, not same-feed

Binance USD-M perpetuals and Kraken Futures perpetuals are different
contracts, on different venues, with different funding mechanics and
different intervals. **The rates should differ.** Testing equality
would test the wrong thing, and a large mean difference is not evidence
of a defect in either feed. What is worth knowing is whether the two
agree STRUCTURALLY: do they rank the same days expensive, do they agree
on sign, do their stamps land where the stated interval says.

## The lockbox split

| statistic class | window | reason |
|---|---|---|
| **VALUES** — Spearman, quintile agreement, sign agreement | `2025-08-27` -> `2026-02-28` | reads funding values |
| **STRUCTURE** — gap census, UTC alignment, event counts | `2025-08-27` -> `2026-07-31` (full overlap) | reads timestamps and counts only |

Dataset end `2026-08-31`; lockbox opens `2026-02-28` (end minus 6 months).

**Why the split is drawn at values and not at judgement.** #220's
registration is drafted immediately after this report, and its
hypotheses are about funding **percentiles and signs**. Reading the
sealed funding DISTRIBUTION would be reading exactly the quantity those
hypotheses are about. The bright line — no sealed values read by
research — admits no carve-outs, so it is drawn at *values*, not at
*values that felt informative*. Timestamps and row counts are not the
sealed quantity and never have been.

**Carried into #220's drafting:** #220 fixes its thresholds by
INHERITANCE from the locked #172–#186 verbatim — same rules, same
constants, new data, corrected null, its own Bonferroni. Nothing in its
registration is choosable at drafting time, so this reconciliation read
cannot anchor what is not being chosen.

## 1. VALUES-based agreement — pre-lockbox overlap only

| symbol | n days | Spearman (daily mean) | quintile agreement | ±1 quintile | sign agreement |
|---|---|---|---|---|---|
| **BTC** | 186 | **+0.595** | 34.4% | 75.8% | 87.1% |
| **ETH** | 186 | **+0.512** | 33.9% | 73.1% | 83.9% |
| **SOL** | 186 | **+0.492** | 38.7% | 73.1% | 73.1% |

Chance baselines, for reading the columns honestly: exact-quintile
agreement by chance is **20%**, within-one-quintile **~52%**, and sign
agreement would be **50%** only if signs were balanced. Funding is
predominantly positive, so a high sign-agreement number is close to
free — it is the WEAKEST of the three columns, not the headline.

## 2. STRUCTURE-only checks — full overlap year

Timestamps and counts only. No funding value inside the sealed span is
read by anything below.

### Gap census, both feeds side by side

| symbol | feed | rows | modal spacing | spacings seen | gaps > expected | largest | hours missing |
|---|---|---|---|---|---|---|---|
| BTC | Binance | 1016 | 8.0h | 8h×1015 | 0 | 0.0h | 0.0h |
| BTC | Kraken | 8112 | 1.0h | 1h×8103, 2h×7, 3h×1 | 8 | 3.0h | 9.0h |
| ETH | Binance | 1016 | 8.0h | 8h×1015 | 0 | 0.0h | 0.0h |
| ETH | Kraken | 8112 | 1.0h | 1h×8103, 2h×7, 3h×1 | 8 | 3.0h | 9.0h |
| SOL | Binance | 1016 | 8.0h | 8h×1015 | 0 | 0.0h | 0.0h |
| SOL | Kraken | 8113 | 1.0h | 1h×8105, 2h×6, 3h×1 | 7 | 3.0h | 8.0h |

### UTC alignment — do Binance 8h stamps land where expected?

Binance's documented funding times are 00:00, 08:00 and 16:00 UTC.

| symbol | rows in overlap | on 00/08/16 UTC | off-schedule | distinct hours seen |
|---|---|---|---|---|
| **BTC** | 1016 | **1016 (100.0%)** | 0 | [0, 8, 16] |
| **ETH** | 1016 | **1016 (100.0%)** | 0 | [0, 8, 16] |
| **SOL** | 1016 | **1016 (100.0%)** | 0 | [0, 8, 16] |

### Per-month event counts vs the stated interval

Coverage test, not a row count: does the SUM of each month's stated
`funding_interval_hours` account for the hours in that month? That is
interval-aware, so a month that legitimately ran a denser schedule is
not flagged as broken.

| symbol | months in overlap | months fully covered | shortfalls |
|---|---|---|---|
| **BTC** | 12 | 12 | **none** (boundary months partial by construction) |
| **ETH** | 12 | 12 | **none** (boundary months partial by construction) |
| **SOL** | 12 | 12 | **none** (boundary months partial by construction) |

## 3. What this record does and does not establish

It is a **data-quality record**, not evidence about funding. It says
whether two independent feeds describe the same underlying phenomenon
closely enough that choosing one as a primary series is a defensible
choice rather than an arbitrary one. **No threshold is applied and no
verdict is reached**, deliberately: a pass rule here would be a
hypothesis, and this is not one.

The values section rests on the pre-lockbox overlap only: **186 paired days per symbol**, not the full overlap year.

Nothing here is registered. Nothing here is scored. #220's registration
is drafted after this is read, and inherits its constants from
#172–#186 rather than choosing them.
