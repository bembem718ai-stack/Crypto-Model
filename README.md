# Crypto-Model

A cryptocurrency trading signal pipeline, and the research program that
audited it to destruction.

The pipeline is real and runs hourly: Bollinger-squeeze detection, technical
and macro indicators, a sentiment gate, ATR-derived exit levels, published
signals with tracked outcomes. The research program asked whether any of it
finds a tradeable edge.

**It does not. That is the finding, and it is the point of this repository.**

## The headline numbers

| | |
|---|---|
| registered hypotheses | **256**, each written to [`docs/cleanroom.md`](docs/cleanroom.md) **before it ran** |
| automated tests | **545** |
| supported edge claims | **zero** — [`docs/claims.md`](docs/claims.md) |

A negative result is only worth anything if the instrument that produced it
was trustworthy. Most of this repository is the work of making that true.

## Seven instrument defects — six caught before they could manufacture a false positive, one that was not

The first six were found by checking a null against the property it claimed
to have — not by a test failing. The seventh was found twelve weeks late.

1. **A permutation null re-shuffled every row**, so a weekly-rebalanced
   portfolio became a daily one: **13.6× the real turnover**, a null crippled
   by costs the strategy never paid. It would have crowned failures as
   passes. *(ROTATION)*
2. **A block-shuffle null moved the cross-section through time**, holding
   **15.4% of its weight in assets that had not listed yet** — earning zero
   through a silent `fillna(0.0)`. *(ALLOCATION)*
3. **On a growing universe, the same family held ~30% dead weight**, making
   the crypto bar *far too easy*. The project's only clause-2 pass was
   measured against it and is now marked uncitable. *(NULL-CALIBRATION)*
4. **Correlation inheritance ran the other way** — on correlated universes a
   null inherits the effect it exists to destroy, setting the bar **too
   hard** by ~2.5 pp/yr. It survived five programs unnoticed, because nobody
   audits a null that is producing failures. *(EQUITIES)*
5. **The shadow logger read exit levels from a function that never returned
   them.** Every row would have logged `target_price=None`, accruing labels
   forever and **zero resolvable episodes**, while looking healthy. Caught
   before the first row was written.
6. **Prices rounded to two decimals** collapsed entry and stop onto each
   other on low-priced assets: **185 of 645 trades with NaN P&L**, averaged
   over survivors while rates were computed over all.
7. **The live path failed silently for 78 days, twice over.** The hourly
   check threw on every run after 2026-09-01 and exited green, so no signal
   was logged or published until 2026-11-18. Separately, the outcome
   resolver re-resolved *closed* episodes against a rolling 22-day window,
   so the published long record drifted from the true **2 targets / 6
   stops** to **8 / 0** without a single new trade. The weekly audit
   reported the stale log eleven weeks running — as comments under an
   issue titled for August. **This one was not caught in time: this page
   quoted a wrong record (+1.00R) for twelve weeks.**
   *([DEFECT #7](docs/cleanroom.md))*

Of the four null defects, two made a bar *easier* and two made it *harder*. That is why all four
[placebo fidelity axes](CLAUDE.md) are now measured before any draw is scored.

## What makes the zeros trustworthy

- **Pre-registration.** Parameters, thresholds and pass conditions are
  recorded before the run. No parameter changes after seeing a result.
- **The lockbox.** The most recent six months are sealed — not for fitting,
  not for plotting, not "just to look".
- **No partial credit.** The closest result cleared four of four clauses on
  one window and failed the other. It is recorded as a failure, with its
  numbers, so the temptation stays legible.
- **Negatives get the same detail as positives**, which is what makes a
  survivor mean anything.

## The forward book

Everything on the frozen data is closed. What remains is **six clocks**, all
calendar-gated and none inspectable before its gate: the shadow basket at 30
episodes, the live record, and three programs registered **before their test
data exists** — [#172–#186](docs/cleanroom.md) (~2027-06-27),
[#235–#242](docs/cleanroom.md) (~2028-01-05),
[#243–#248](docs/cleanroom.md) (~2028-07-01).

Three archives now hold data available nowhere else: venue endpoints serve
rolling windows of 16 to 365 days, or nothing at all, so what is not
collected is gone. **26,602** funding rows, **20,941** from a static archive,
plus positioning snapshots accruing daily.

## The live service

Every published signal, its computed exit levels, and its resolved outcome go
into a public tally **including the losses**. Current published record:
**8 long episodes, 2 winners, 6 losers, −2.00R net** — four weeks, essentially
one ticker, and far too small to mean anything. *(Corrected 2026-11-18: this
line read "3 winners, 5 losers, +1.00R", a resolver artifact — see defect 7
above. No signals were published from 2026-09-01 to 2026-11-18.)* A further 11 short episodes
were logged and never published; they went 0 for 11, which is why shorts are
off.

Not a win rate, not a profit claim, not financial advice. See
[`docs/claims.md`](docs/claims.md) for what may and may not be said, and
[`docs/market_structure.md`](docs/market_structure.md) for what this market
measurably is.
