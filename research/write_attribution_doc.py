"""Render the Attribution section into docs/cleanroom.md from attribution.csv."""
import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
att = pd.read_csv(os.path.join(ROOT, "research", "attribution.csv"))

L = []
A = L.append
A("\n## Attribution - where does the expectancy come from?\n")
A("Produced by `research/attribution.py`. Nothing here decides a trade: every")
A("trade dissected was produced by `pipeline.evaluate_geometry_folds` through")
A("`research/harness.py`. The module only measures properties of those trades.\n")
A("**Scope.** `INC_STRONG_BUY` plus the top 3 DISCOVERY rules - nothing survived")
A("CONFIRMATION (#162), so the fallback applies. Window is the full non-lockbox")
A("span, DISCOVERY + CONFIRMATION (2020-09-21 -> 2026-02-26 for the resampled")
A("daily frame; 2021-10-24 -> 2026-02-26 for the incumbent's merged frame, which")
A("starts later). Pooled because `INC_STRONG_BUY` fires 8/3/1 times on DISCOVERY")
A("and 10/5/0 on CONFIRMATION - split any finer and there is nothing to")
A("attribute. The lockbox stays sealed in both the daily frames and the 4h feed.\n")
A("**Two notes on how to read the numbers.**\n")
A("- `best fold share` above 100% is not an error. It means the single best fold")
A("  contributes more R than the strategy made in total, i.e. the other three")
A("  folds are net NEGATIVE. 139% means: remove the best fold and you lose money.")
A("- MFE/MAE are in R. `pipeline` stores only favourable excursion as a fraction")
A("  of TARGET distance and no MAE at all, so MFE_R is rescaled by the R:R (2.0")
A("  for BUY, 2.667 for STRONG_BUY) and MAE is measured directly off the 4h bars")
A("  between pipeline's own entry and exit.\n")

A("### The headline: for the three rules, the edge IS mostly drift plus geometry\n")
A("Under this geometry a trade can only end three ways, and timeouts are ~0-1%.")
A("So gross expectancy is almost exactly `2 x P(target) - P(stop)` - a mechanical")
A("function of the hit rate. That makes the comparison below the whole story:\n")
A("| ticker | row | n | target% | stop% | net exp |")
A("|--------|-----|---|---------|-------|---------|")
base = {"BTC": (1979, 34.9, 64.4, 0.016), "ETH": (1979, 35.1, 64.5, 0.031),
        "SOL": (1979, 34.4, 64.7, 0.024)}
for t, (n, tg, st, e) in base.items():
    A("| %s | ALWAYS_LONG (drift baseline) | %d | %.1f | %.1f | %+.3f |" % (t, n, tg, st, e))
for _, r in att[att.row != "INC_STRONG_BUY"].sort_values(["ticker", "row"]).iterrows():
    A("| %s | `%s` | %d | %.1f | %.1f | %+.3f |"
      % (r.ticker, r.row, r.n, 100 * r.share_target,
         100 * (r.share_stop + r.share_ambiguous_stop), r.exp_net))
A("")
A("Being long every single day already hits target ~35% of the time and earns")
A("+0.016 to +0.031R per trade. The three rules hit target 33-40% of the time.")
A("**The entire contribution of the signal is a 2-4 percentage point lift in hit")
A("rate** - everything else in their expectancy is the 2:1 payoff structure")
A("applied to a market that drifted up. On SOL, `donchian10+none` does not even")
A("manage that: 33.0% target vs the 34.4% you get from buying every day, which is")
A("why its expectancy (-0.009R) is BELOW the drift baseline (+0.024R).\n")
A("And the 2-4pp lift does not hold together across time:\n")
A("| row | ticker | total R | best fold R | best fold share | excess over drift |")
A("|-----|--------|---------|-------------|-----------------|-------------------|")
for _, r in att[att.row != "INC_STRONG_BUY"].sort_values(["row", "ticker"]).iterrows():
    bs = ("n/a (total R <= 0)" if r.best_fold_share != r.best_fold_share
          else "%.0f%%" % (100 * r.best_fold_share))
    A("| `%s` | %s | %+.1f | %+.1f | %s | %+.3f |"
      % (r.row, r.ticker, r.total_R, r.best_fold_R, bs, r.excess_over_drift))
A("")
A("`roc10_zero+none` on ETH (131%) and SOL (139%) makes money in one fold and")
A("loses it in the other three. `donchian10+none` on BTC takes 93% of its total R")
A("from a single fold. This is the same concentration that made `ex_best` negative")
A("on DISCOVERY, now visible as a share of profit rather than a summary statistic.\n")

A("### Regime and exit detail\n")
A("| row | ticker | exp above SMA200 | exp below SMA200 | vol lo / mid / hi |")
A("|-----|--------|------------------|------------------|-------------------|")
for _, r in att[att.row != "INC_STRONG_BUY"].sort_values(["row", "ticker"]).iterrows():
    A("| `%s` | %s | %+.3f (n=%d) | %+.3f (n=%d) | %+.3f / %+.3f / %+.3f |"
      % (r.row, r.ticker, r.exp_above200, r.n_above200,
         r.exp_below200, r.n_below200, r.exp_vol_lo, r.exp_vol_mid, r.exp_vol_hi))
A("")
A("**No consistent regime story.** `obv_break20+none` and `roc10_zero+none` do")
A("better BELOW the 200-day SMA on BTC and ETH (+0.181/+0.271, +0.247/+0.219) -")
A("the opposite of the trend-filter intuition - but `roc10_zero+none` flips to")
A("preferring ABOVE on SOL (+0.222 vs -0.038). The vol terciles disagree across")
A("tickers the same way: `donchian10+none` is best in LOW vol on BTC (+0.218) and")
A("ETH (+0.324) but best in HIGH vol on SOL (+0.148). Three tickers, three")
A("different stories, is what noise looks like.\n")
A("**The exit mix is almost identical everywhere** - ~37% target / ~62% stop /")
A("~0-1% timeout for every rule on every ticker. The shape of a winner and the")
A("shape of a loser are also stable: winners run to MFE ~2.4-2.5R while only")
A("giving back ~0.33-0.42R against them; losers reach only ~0.52-0.65R in favour")
A("before being stopped at ~1.4R. Stopped trades never got close to target. That")
A("uniformity is the signature of geometry doing the work, not selection.\n")

A("### Overlap with the incumbent\n")
A("| row | BTC | ETH | SOL |")
A("|-----|-----|-----|-----|")
for row in ["donchian10+none", "obv_break20+none", "roc10_zero+none"]:
    s = att[att.row == row].set_index("ticker")
    A("| `%s` | %.3f | %.3f | %.3f |"
      % (row, s.loc["BTC", "jaccard_vs_inc_buy"], s.loc["ETH", "jaccard_vs_inc_buy"],
         s.loc["SOL", "jaccard_vs_inc_buy"]))
A("")
A("Jaccard similarity of signal days against the incumbent's BUY/STRONG_BUY days")
A("is 0.007-0.074 - essentially no overlap. **These rules are NOT relabellings of")
A("the incumbent.** They fire on genuinely different days. That is the one")
A("positive finding here: the grid explored new territory. It just did not find")
A("anything in it.\n")

A("### INC_STRONG_BUY - a different answer: not attributable\n")
inc = att[att.row == "INC_STRONG_BUY"].set_index("ticker")
A("| ticker | n | exp | ALWAYS_LONG | excess | target% | best fold share |")
A("|--------|---|-----|-------------|--------|---------|-----------------|")
for t in ["BTC", "ETH", "SOL"]:
    r = inc.loc[t]
    bs = "n/a" if r.best_fold_share != r.best_fold_share else "%.0f%%" % (100 * r.best_fold_share)
    A("| %s | %d | %+.3f | %+.3f | %+.3f | %.0f | %s |"
      % (t, r.n, r.exp_net, r.always_long_exp, r.excess_over_drift,
         100 * r.share_target, bs))
A("")
A("The incumbent's STRONG_BUY tier is **not** drift and **not** geometry. Drift on")
A("its window is ~0 (-0.017 / +0.007 / -0.031), so essentially all of its +1.802 /")
A("+0.788 / +2.644 is excess. And it does not get there through the 2:1 mechanism")
A("the rules rely on: it hits target 78% of the time on BTC and 50% on ETH,")
A("against a ~35% base rate. When it loses, it loses cleanly - stopped BTC trades")
A("reached only 0.10R in favour before dying.\n")
A("**But this cannot be called an edge, because there is not enough of it.** n =")
A("18, 8 and 1 over five and a half years. The BTC trades are 2 clustered")
A("episodes resolving on 4 distinct exit bars (recorded under the baseline")
A("correction above), so 18 trades are nowhere near 18 independent observations.")
A("ETH takes 92% of its R from one fold; SOL's entire record is a single trade.")
A("`ex_best` is undefined on all three tickers because no ticker reaches 3 folds")
A("with 10+ trades.\n")
A("The Jaccard figures for this row (0.098 / 0.059 / 0.022) are degenerate and")
A("should not be read as overlap: STRONG_BUY is a strict SUBSET of BUY, so the")
A("ratio just restates how rare the tier is.\n")
A("**Plain answer: the incumbent's STRONG_BUY expectancy comes from a genuinely")
A("high target-hit rate on a handful of clustered trades. It is not explained")
A("away by drift or geometry - and it is also not established. Too rare to")
A("attribute is the finding, not a verdict either way.**\n")

path = os.path.join(ROOT, "docs", "cleanroom.md")
src = open(path, encoding="utf-8").read()
open(path, "w", encoding="utf-8").write(src.rstrip("\n") + "\n" + "\n".join(L))
print("Attribution section written (%d lines)" % len(L))
