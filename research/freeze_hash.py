"""research/freeze_hash.py — content hashes for frozen datasets.

THE STANDARD FOR EVERY FREEZE. A manifest that records row counts and
spans but no hash says what a file was SUPPOSED to contain, not what it
DOES contain. Two files can agree on 15,177 rows spanning 2019-09-23 to
2026-08-27 and differ in every price.

That gap was real: `data/MANIFEST.json`, `data/MANIFEST_1h.json` and
`data/basket/MANIFEST.json` recorded no hashes at all, while
`MANIFEST_equities.json` and `MANIFEST_macro.json` did -- the same
project, two standards, and each export script carrying its own copy of
the same six-line `sha256()`. This module is the one copy.

USE IT AT FREEZE TIME. A hash computed later can only ever attest to what
the file holds NOW; it cannot prove the file has not moved since, and any
such retrofit must say so in the manifest itself (see `hashed_at` and
`hashed_note`).
"""
import os
import hashlib

CHUNK = 65536


def sha256(path):
    """Streaming sha256 of one file. Chunked so a multi-GB freeze does not
    have to fit in memory."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_or_none(path):
    """sha256, or None when the file is absent or unreadable.

    RETURNS None RATHER THAN RAISING because a manifest is written at the
    END of an export: a ticker that failed mid-run has a record but no
    file, and a hash step is not the place to lose the whole freeze. A
    None is visible in the manifest; a crash loses everything above it.
    """
    try:
        return sha256(path)
    except OSError:
        return None


def hash_into(record, out_dir, files):
    """Write `sha256_<key>` into `record` for each (key, filename) pair.

    Mutates and returns `record`, so it drops into an existing manifest
    block without restructuring it -- which matters because the three core
    manifests are already committed and their existing keys must survive
    untouched.
    """
    for key, name in files:
        if name is None:
            continue
        record["sha256_" + key] = sha256_or_none(os.path.join(out_dir, name))
    return record


def stamp(meta, hashed_at=None, note=None):
    """Record WHEN the hashes were taken, and whether at freeze time.

    `hashed_at=None` means now, i.e. freeze time, and stamps
    `hashed_at_freeze: true`. Passing an explicit date means the hashes
    were computed after the fact, which is a materially weaker claim: it
    attests to the file's content at that date, not to its content when
    the freeze was written. The distinction is recorded in the manifest
    rather than left for a reader to infer from two timestamps.
    """
    import datetime as dt
    if hashed_at is None:
        meta["hashed_at"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
        meta["hashed_at_freeze"] = True
    else:
        meta["hashed_at"] = hashed_at
        meta["hashed_at_freeze"] = False
    if note:
        meta["hashed_note"] = note
    return meta
