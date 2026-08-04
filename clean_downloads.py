"""
clean_downloads.py — see and tidy duplicate copies in Downloads
===============================================================

    python clean_downloads.py            # show every copy, pick nothing
    python clean_downloads.py --tidy     # move stale copies to quarantine
    python clean_downloads.py --undo     # put quarantined files back

WHY THIS EXISTS:
    Downloading the same file repeatedly gives pipeline.py,
    pipeline (1).py, pipeline (2).py. install_update.py already picks the
    newest of each automatically — but you should be able to SEE that
    judgment before trusting it, especially if a copy is stale enough to
    silently revert work.

WHAT IT DOES NOT DO:
    It never deletes. --tidy MOVES stale copies into
    Downloads/_stale_copies/ so --undo can put them back. It never
    touches your repo, only the source folder. Files not on the managed
    list are listed but never moved.
"""

import argparse
import hashlib
import os
import re
import shutil
import sys
from datetime import datetime

try:
    from install_update import MANAGED, canonical_name
except ImportError:
    # Standalone fallback so this still works if run before the installer
    # is in place — the two lists must agree, so keep them in sync.
    MANAGED = {
        "pipeline.py": ".", "signal_engines.py": ".", "live_tools.py": ".",
        "test_signals.py": ".", "audit.py": ".", "install_update.py": ".",
        "verify_fixes.py": ".", "clean_downloads.py": ".", "CLAUDE.md": ".",
        "signal-check.yml": ".github/workflows",
        "robustness.yml": ".github/workflows", "audit.yml": ".github/workflows",
    }
    _COPY_RE = re.compile(r"^(?P<stem>.+?)(?: \((?P<n>\d+)\))?(?P<ext>\.[A-Za-z0-9]+)$")

    def canonical_name(filename):
        m = _COPY_RE.match(filename)
        if not m:
            return None, 0
        base = m.group("stem") + m.group("ext")
        return (base, int(m.group("n") or 0)) if base in MANAGED else (None, 0)

QUARANTINE = "_stale_copies"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def survey(source):
    """canonical name -> list of copies, newest first."""
    groups = {}
    for fn in sorted(os.listdir(source)):
        full = os.path.join(source, fn)
        if not os.path.isfile(full):
            continue
        canon, idx = canonical_name(fn)
        if not canon:
            continue
        groups.setdefault(canon, []).append({
            "name": fn, "path": full, "idx": idx,
            "mtime": os.path.getmtime(full),
            "size": os.path.getsize(full),
            "sha": sha256(full),
        })
    for canon in groups:
        groups[canon].sort(key=lambda c: (c["mtime"], c["idx"]), reverse=True)
    return groups


def report(groups, repo):
    if not groups:
        print("No managed files found here.")
        print(f"Expected any of: {', '.join(sorted(MANAGED))}")
        return [], []
    keep, stale = [], []
    print(f"{'':2}{'file':<26}{'modified':<18}{'size':>8}  status")
    print("-" * 74)
    for canon in sorted(groups):
        copies = groups[canon]
        winner = copies[0]
        installed_sha = None
        dest = os.path.join(repo, MANAGED[canon], canon)
        if os.path.isfile(dest):
            installed_sha = sha256(dest)
        for i, c in enumerate(copies):
            when = datetime.fromtimestamp(c["mtime"]).strftime("%Y-%m-%d %H:%M")
            if i == 0:
                if installed_sha == c["sha"]:
                    status = "WOULD USE — already installed, no change"
                else:
                    status = "WOULD USE — newest"
                keep.append(c)
                mark = "->"
            else:
                same = "identical to newest" if c["sha"] == winner["sha"] else \
                       "DIFFERENT content — older"
                status = f"stale ({same})"
                stale.append(c)
                mark = "  "
            print(f"{mark}{c['name']:<26}{when:<18}{c['size']:>8}  {status}")
        print()   # blank after every group, so groups read as groups
    return keep, stale


def main():
    ap = argparse.ArgumentParser(description="Inspect/tidy duplicate downloads")
    default_src = os.path.join(os.path.expanduser("~"), "Downloads")
    ap.add_argument("--source", default=default_src)
    ap.add_argument("--repo", default=os.getcwd())
    ap.add_argument("--tidy", action="store_true",
                    help="move stale copies into a quarantine subfolder")
    ap.add_argument("--undo", action="store_true",
                    help="restore everything from quarantine")
    args = ap.parse_args()

    qdir = os.path.join(args.source, QUARANTINE)

    if args.undo:
        if not os.path.isdir(qdir):
            print("Nothing quarantined.")
            return 0
        moved = 0
        for fn in os.listdir(qdir):
            src, dst = os.path.join(qdir, fn), os.path.join(args.source, fn)
            if os.path.exists(dst):
                print(f"  skipped {fn} (a file with that name is back already)")
                continue
            shutil.move(src, dst)
            moved += 1
        print(f"Restored {moved} file(s) to {args.source}")
        if not os.listdir(qdir):
            os.rmdir(qdir)
        return 0

    if not os.path.isdir(args.source):
        print(f"Source folder does not exist: {args.source}")
        return 1

    print(f"\nSource: {args.source}\n")
    groups = survey(args.source)
    keep, stale = report(groups, args.repo)

    if not stale:
        print("No duplicate copies. Nothing to tidy.")
        return 0

    identical = [c for c in stale
                 if c["sha"] == groups[canonical_name(c["name"])[0]][0]["sha"]]
    different = [c for c in stale if c not in identical]
    print(f"{len(stale)} stale copy(ies): {len(identical)} identical to the newest, "
          f"{len(different)} with DIFFERENT content.")
    if different:
        print("  The different ones are the dangerous kind — installing one by "
              "hand would silently revert work.")

    if not args.tidy:
        print("\nNothing was moved. Run with --tidy to quarantine the stale "
              "copies, or just run install_update.py — it already picks the "
              "newest of each automatically.")
        return 0

    os.makedirs(qdir, exist_ok=True)
    for c in stale:
        target = os.path.join(qdir, c["name"])
        if os.path.exists(target):
            os.remove(target) if sha256(target) == c["sha"] else None
        shutil.move(c["path"], target)
    print(f"\nMoved {len(stale)} stale copy(ies) to {os.path.join(QUARANTINE, '')}")
    print("Nothing was deleted — 'python clean_downloads.py --undo' puts them back.")
    print("\nNext: python install_update.py --dry-run")
    return 0


if __name__ == "__main__":
    sys.exit(main())
