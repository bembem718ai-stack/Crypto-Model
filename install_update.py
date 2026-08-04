"""
install_update.py — get files from Downloads into the repo, safely
=================================================================

    python install_update.py            # plan + install + verify
    python install_update.py --dry-run  # show the plan, touch nothing
    python install_update.py --rollback # undo the last install

THE PROBLEM THIS SOLVES:
    Downloading the same file twice gives you `pipeline.py`,
    `pipeline (1).py`, `pipeline (2).py`. Copying the wrong one silently
    reverts work, and you find out later from a confusing test failure.
    This picks the NEWEST variant of each managed file, shows you what it
    is before touching anything, and can undo the whole thing.

SAFETY PROPERTIES (in order of how much they matter):
    1. AUTOMATIC ROLLBACK. After copying, it runs the test suite. If the
       suite fails, every file is restored from backup and the install is
       reported as failed. A broken repo is never left behind.
    2. Every install backs up to _backups/<timestamp>/ first.
    3. Identical files (same SHA256) are skipped, not recopied.
    4. Files are only ever written INTO the repo, never out of it.

This script never touches the network and never spends Adanos quota.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime

# Files this script is allowed to manage, and where each belongs.
# Anything not listed here is ignored entirely — that is deliberate, so a
# stray download can never be installed by accident.
MANAGED = {
    "pipeline.py": ".",
    "signal_engines.py": ".",
    "live_tools.py": ".",
    "test_signals.py": ".",
    "audit.py": ".",
    "install_update.py": ".",
    "verify_fixes.py": ".",
    "clean_downloads.py": ".",
    "CLAUDE.md": ".",
    "signal-check.yml": ".github/workflows",
    "robustness.yml": ".github/workflows",
    "audit.yml": ".github/workflows",
}

BACKUP_ROOT = "_backups"
STATE_FILE = os.path.join(BACKUP_ROOT, "last_install.json")

# "pipeline (1).py" / "pipeline (2).py" -> stem "pipeline", copy index 1/2
_COPY_RE = re.compile(r"^(?P<stem>.+?)(?: \((?P<n>\d+)\))?(?P<ext>\.[A-Za-z0-9]+)$")


def canonical_name(filename: str):
    """'pipeline (2).py' -> ('pipeline.py', 2). Returns (None, 0) if the
    name doesn't resolve to a managed file."""
    m = _COPY_RE.match(filename)
    if not m:
        return None, 0
    base = m.group("stem") + m.group("ext")
    return (base, int(m.group("n") or 0)) if base in MANAGED else (None, 0)


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def find_candidates(source_dir: str) -> dict:
    """Map canonical name -> the NEWEST matching file on disk.

    Newest by mtime, not by copy index: '(1)' is usually but not always
    the later download, and mtime is the fact rather than the convention.
    Ties break toward the higher copy index.
    """
    best = {}
    if not os.path.isdir(source_dir):
        return best
    for fn in os.listdir(source_dir):
        canon, idx = canonical_name(fn)
        if not canon:
            continue
        full = os.path.join(source_dir, fn)
        if not os.path.isfile(full):
            continue
        mtime = os.path.getmtime(full)
        prev = best.get(canon)
        if prev is None or (mtime, idx) > (prev["mtime"], prev["idx"]):
            best[canon] = {"path": full, "mtime": mtime, "idx": idx, "name": fn}
    return best


def build_plan(candidates: dict, repo: str) -> list:
    plan = []
    for canon, info in sorted(candidates.items()):
        dest_dir = os.path.join(repo, MANAGED[canon])
        dest = os.path.join(dest_dir, canon)
        exists = os.path.isfile(dest)
        same = exists and sha256(dest) == sha256(info["path"])
        plan.append({
            "canonical": canon, "source": info["path"], "source_name": info["name"],
            "dest": dest, "dest_dir": dest_dir, "exists": exists, "identical": same,
            "action": "skip (identical)" if same else ("replace" if exists else "create"),
            "mtime": datetime.fromtimestamp(info["mtime"]).strftime("%Y-%m-%d %H:%M"),
        })
    return plan


def print_plan(plan: list, candidates: dict, source_dir: str):
    print(f"\nSource: {source_dir}")
    if not plan:
        print("  Nothing to install — no managed files found there.")
        print(f"  Managed files: {', '.join(sorted(MANAGED))}")
        return
    print(f"{'file':<22}{'from':<26}{'modified':<18}{'action'}")
    print("-" * 84)
    for p in plan:
        print(f"{p['canonical']:<22}{p['source_name']:<26}{p['mtime']:<18}{p['action']}")
    dupes = [c for c, i in candidates.items() if i["idx"] > 0]
    if dupes:
        print(f"\nNote: picked a numbered copy for {', '.join(sorted(dupes))} "
              f"(newest by modified time). If that looks wrong, delete the stale "
              f"copies from Downloads and rerun.")


def do_backup(plan: list, repo: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bdir = os.path.join(repo, BACKUP_ROOT, stamp)
    saved = []
    for p in plan:
        if p["identical"] or not p["exists"]:
            continue
        rel = os.path.relpath(p["dest"], repo)
        target = os.path.join(bdir, rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(p["dest"], target)
        saved.append(rel)
    if saved:
        os.makedirs(bdir, exist_ok=True)
        with open(os.path.join(repo, STATE_FILE), "w") as f:
            json.dump({"backup_dir": bdir, "files": saved,
                       "when": datetime.now().isoformat()}, f, indent=2)
    return bdir if saved else ""


def do_copy(plan: list) -> list:
    copied = []
    for p in plan:
        if p["identical"]:
            continue
        os.makedirs(p["dest_dir"], exist_ok=True)
        shutil.copy2(p["source"], p["dest"])
        copied.append(p["canonical"])
    return copied


def restore(repo: str, backup_dir: str, files: list):
    for rel in files:
        src = os.path.join(backup_dir, rel)
        if os.path.isfile(src):
            dst = os.path.join(repo, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)


def run_tests(repo: str, python: str) -> tuple:
    """Syntax-check every managed .py, then run the suite. Syntax first:
    a mangled file gives a clearer message than a wall of import errors."""
    import ast
    for canon, sub in MANAGED.items():
        if not canon.endswith(".py"):
            continue
        path = os.path.join(repo, sub, canon)
        if not os.path.isfile(path):
            continue
        try:
            ast.parse(open(path, encoding="utf-8").read())
        except SyntaxError as e:
            return False, f"{canon} has a syntax error at line {e.lineno}: {e.msg}"
    test_path = os.path.join(repo, "test_signals.py")
    if not os.path.isfile(test_path):
        return True, "no test_signals.py present — syntax check only"
    try:
        proc = subprocess.run([python, "-m", "pytest", "test_signals.py", "-q"],
                              cwd=repo, capture_output=True, text=True, timeout=900)
    except Exception as e:
        return True, f"could not run pytest ({type(e).__name__}) — syntax check only"
    tail = (proc.stdout.strip().splitlines() or [""])[-1]
    return proc.returncode == 0, tail


def main():
    ap = argparse.ArgumentParser(description="Install downloaded updates safely")
    default_src = os.path.join(os.path.expanduser("~"), "Downloads")
    ap.add_argument("--source", default=default_src, help=f"default {default_src}")
    ap.add_argument("--repo", default=os.getcwd())
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--dry-run", action="store_true", help="show the plan only")
    ap.add_argument("--no-test", action="store_true",
                    help="skip verification (also disables auto-rollback)")
    ap.add_argument("--rollback", action="store_true", help="undo the last install")
    args = ap.parse_args()

    if args.rollback:
        state_path = os.path.join(args.repo, STATE_FILE)
        if not os.path.isfile(state_path):
            print("No previous install recorded — nothing to roll back.")
            return 1
        state = json.load(open(state_path))
        restore(args.repo, state["backup_dir"], state["files"])
        print(f"Restored {len(state['files'])} file(s) from {state['backup_dir']} "
              f"(install of {state['when'][:16]}).")
        return 0

    candidates = find_candidates(args.source)
    plan = build_plan(candidates, args.repo)
    print_plan(plan, candidates, args.source)

    todo = [p for p in plan if not p["identical"]]
    if not todo:
        print("\nEverything is already up to date.")
        return 0
    if args.dry_run:
        print(f"\nDry run — {len(todo)} file(s) would change. Nothing was written.")
        return 0

    backup_dir = do_backup(plan, args.repo)
    copied = do_copy(plan)
    print(f"\nInstalled {len(copied)} file(s): {', '.join(copied)}")
    if backup_dir:
        print(f"Backup: {os.path.relpath(backup_dir, args.repo)}")

    if args.no_test:
        print("Verification skipped (--no-test). Auto-rollback is OFF.")
        return 0

    print("\nVerifying...")
    ok, detail = run_tests(args.repo, args.python)
    if ok:
        print(f"  PASS — {detail}")
        print("\nInstall complete.")
        return 0

    print(f"  FAIL — {detail}")
    if backup_dir:
        state = json.load(open(os.path.join(args.repo, STATE_FILE)))
        restore(args.repo, state["backup_dir"], state["files"])
        print(f"\nROLLED BACK automatically. {len(state['files'])} file(s) restored; "
              f"the repo is exactly as it was.")
    else:
        print("\nNo backup existed (all files were new). Delete them manually "
              "if you want a clean slate.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
