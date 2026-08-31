# Funding-history source reconnaissance — mechanical probe

Not a registered program. No hypothesis, no price joins, no backfill,
nothing scored. Run from a US machine with the OS trust store enabled.

Run: 2026-08-31 19:43 UTC

## 1. Bybit public API

Endpoint: `GET /v5/market/funding/history?category=linear&symbol=BTCUSDT`

Response: **HTTP 403**

```
{
    error:The Amazon CloudFront distribution is configured to block access from your country
}
```

**Geo-blocked from this US machine.** The body names a CloudFront
country block, so the rejection happens at the CDN edge before any
API logic runs. This is decided by source IP: no header, key, or TLS
setting changes it, and it is the same class of block Binance global
returns as HTTP 451. The endpoint may well exist and serve deep
history elsewhere — this probe cannot see it from here, which is a
fact about **this machine's location**, not about Bybit's coverage.

## 2. Binance Vision (`data.binance.vision`)

**A listing gotcha, recorded because it manufactures a false negative.**
`https://data.binance.vision/?prefix=...` returns HTTP 200 and the same
2,712-byte HTML shell for *every* prefix — the file list is rendered
client-side by JavaScript. Parsing that page finds zero objects and
reads exactly like *this bucket has no funding data*. It has 79 files.
The machine-readable listing is the S3 endpoint, used below.

Reachable from this US machine: **HTTP 200**, no key, no geo-block.
Datasets under `data/futures/um/monthly/`:

- `aggTrades`
- `bookTicker`
- `fundingRate`
- `indexPriceKlines`
- `klines`
- `markPriceKlines`
- `premiumIndexKlines`
- `trades`

### Funding-rate archives, USDT-margined futures

| symbol | zip files | earliest | latest | gaps |
|---|---|---|---|---|
| `BTCUSDT` | 79 | 2020-01 | 2026-07 | **none** |
| `ETHUSDT` | 79 | 2020-01 | 2026-07 | **none** |
| `SOLUSDT` | 71 | 2020-09 | 2026-07 | **none** |

### Does the archive reach back to listing?

| dataset | earliest month |
|---|---|
| `klines/1d` | **`2020-01`** |
| `fundingRate` | **`2020-01`** |

Both begin the same month, so **no funding is missing relative to what
the bucket carries**. But that is a weaker statement than *reaches
listing*, and the two must not be conflated — so it was tested.

**Probing 2019 directly (HEAD, no body downloaded):**

| month | `klines/1d` | `fundingRate` |
|---|---|---|
| `2019-09` | HTTP 404 | HTTP 404 |
| `2019-10` | HTTP 404 | HTTP 404 |
| `2019-12` | HTTP 404 | HTTP 404 |
| `2020-01` | HTTP 200 | HTTP 200 |

**Every 2019 month is 404 in both datasets**, and the first 1d-klines
file is a **full 31-row January opening on the 1st at ~$7,189** — not a
partial first month. A contract that listed in January 2020 would
produce a partial file; a full one means it was already trading.

**Conclusion: 2020-01 is an ARCHIVE FLOOR, not a listing date.** Binance
Vision appears to start its USD-M futures collection at 2020-01 across
datasets. So the monthly funding archive does **NOT** demonstrably reach
back to contract listing, and any period before 2020-01 is absent from
this source regardless of when the contract began trading.


### Sample download — one file

`BTCUSDT-fundingRate-2020-01.zip` -> HTTP 200, **825 bytes** compressed.

Inner file `BTCUSDT-fundingRate-2020-01.csv`, 94 lines.

**Columns, verbatim header:** `calc_time,funding_interval_hours,last_funding_rate`

First three data rows:

```
1577836800000,8,-0.00012359
1577865600000,8,-0.00012383
1577894400000,8,-0.00009664
```

**93 funding events** in 2020-01.

### Units

Column `last_funding_rate`: min `-0.00012383`, max `0.00108193`, smallest non-zero `8.4e-07`.

That reads as a **per-interval fraction** — `0.0001` = 1 basis point
charged over one funding interval — **not** percent and **not**
annualised. 93 events in the month is consistent with an 8-hour
interval (3/day), and the `funding_interval_hours` column states the interval per row.

This is a **magnitude reading, not a confirmation**. Settling the
units means reconciling against our own Kraken archive on
overlapping dates — a separate step, not part of this probe.

Timestamp column `calc_time` spans `2020-01-01 00:00 UTC` -> `2020-01-31 16:00 UTC` (epoch ms).

## 3. Verdicts

| source | reachable from here | funding history | depth | notes |
|---|---|---|---|---|
| **Bybit** `/v5/market/funding/history` | **NO** — HTTP 403 | unknown | unknown | CloudFront country block |
| **Binance Vision** monthly `fundingRate` | **YES** | **yes** | **2020-01 -> 2026-07**, 79 files, no gaps | static bucket, no key, no geo-block, no rate limit; archive FLOOR 2020-01, not a listing date |

Bybit is recorded as **unknown**, not *no*: a CDN country block says
nothing about what the endpoint would serve from a permitted IP.

### Spend

- HTTP requests issued: **16**
- Bytes downloaded: **183,266** (0.183 MB)
- Monetary cost: **zero** — both sources are public and unauthenticated.

Nothing registered, nothing scored, no backfill performed.
