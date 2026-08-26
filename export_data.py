import json, os
import pipeline as p, signal_engines as cf

N = 12600
os.makedirs("data", exist_ok=True)
man = {}
for t in ["BTC", "ETH", "SOL"]:
    print("=== " + t)
    bars = cf.fetch_klines_paginated(cf.to_binance_symbol(t), interval="4h", target_bars=N)
    bars.to_csv("data/" + t + "_4h.csv")
    print("  bars " + str(len(bars)) + " " + str(bars.index.min()) + " to " + str(bars.index.max()))
    merged = p.run_backtest(t, period="5y", squeeze_bars=N)
    merged.to_csv("data/" + t + "_merged.csv")
    print("  daily " + str(len(merged)) + " " + str(merged.index.min()) + " to " + str(merged.index.max()))
    man[t] = {"bars_4h": len(bars), "daily_rows": len(merged),
              "bars_last": str(bars.index.max()), "daily_last": str(merged.index.max()),
              "directions": {k: int(v) for k, v in merged["direction"].value_counts().to_dict().items()}}
with open("data/MANIFEST.json", "w", encoding="utf-8") as f:
    json.dump(man, f, indent=2)
print("done")
