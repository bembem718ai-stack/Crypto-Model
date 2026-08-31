# CoinAPI acceptance probe — mechanical only

Not a registered program. No hypothesis, no price joins, no backfill.
Key read from the file; never printed, logged, or written here.

Run: 2026-08-31 19:22 UTC

**ABORT — no data retrieved.** HTTP 403 using the `authorization` header.

This is a **billing/entitlement rejection, not a bad key**: the
response names a quota, not an authentication failure. The
credential is recognised; the account has no usable credits or
active subscription, so every endpoint returns 403 before serving
any data.

Server response (key-free):

```
{
  "title": "Forbidden",
  "status": 403,
  "detail": "Quota exceeded: Insufficient Usage Credits or Subscription.",
  "error": "Forbidden (Quota exceeded: Insufficient Usage Credits or Subscription.)",
  "QuotaKey": "BA",
  "QuotaName": "Insufficient Usage Credits or Subscription",
  "QuotaType": "Organization Limit",
  "QuotaValueCurrentUsage": 0,
  "QuotaValue": 0,
  "QuotaValueUnit": "$",
  "QuotaValueAdjustable": "Yes, acquire or upgrade subscription, add service credits manually or setup auto-recharge."
}
```

**Nothing further was attempted.** Symbol discovery, the metrics
listing and the depth probes all require a served response, so they
are UNANSWERED — not answered negatively.

## Credits / usage

Requests issued: **1** (hard cap 50).

The API returned no rate-limit / cost / quota headers on the
rejected requests.

A rejected request is not expected to consume a data credit, but
that is an assumption about CoinAPI's billing, not something this
probe can verify from the outside.
