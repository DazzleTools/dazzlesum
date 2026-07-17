#!/usr/bin/env python3
"""Fail the build if a distribution leaks private/ content or local state files.

The privacy guarantee for dazzlesum's PyPI artifacts is the clean-checkout
build: ``private/`` design-doc trees are gitignored, so a fresh CI checkout
simply does not contain them. This script is the enforcing backstop -- it
scans the actually-built sdist (``.tar.gz``) and wheel (``.whl``) for any
path that must never ship and exits non-zero so the publish workflow aborts
before upload.

It is depth-proof by construction: it matches path *components* (``private``
anywhere in a member path), not MANIFEST.in globs, so nested content cannot
slip through regardless of how deep it sits.

Usage:
    python scripts/check_dist_no_leak.py [DIR_OR_FILE ...]   # default: dist/

Exit codes:
    0  all artifacts clean
    1  at least one forbidden path found (a leak)
    2  no .tar.gz/.whl artifacts found at the given targets
"""
import sys
import tarfile
import zipfile
from pathlib import Path

# A member path is forbidden if any of its components is one of these
# directory names, or its basename matches a local-state file.
FORBIDDEN_DIRS = {"private"}
FORBIDDEN_BASENAMES = {".dazzle-cache.sqlite", ".env"}


def is_forbidden(member: str):
    """Return a short reason string if ``member`` must not ship, else None."""
    parts = [p for p in member.replace("\\", "/").split("/") if p]
    for p in parts:
        if p in FORBIDDEN_DIRS:
            return "component '%s'" % p
    if parts and parts[-1] in FORBIDDEN_BASENAMES:
        return "basename '%s'" % parts[-1]
    return None


def members(artifact: Path):
    """Yield member path strings from an sdist (.tar.gz) or wheel (.whl)."""
    name = artifact.name.lower()
    if name.endswith((".tar.gz", ".tgz", ".tar")):
        with tarfile.open(artifact, "r:*") as tf:
            for m in tf.getmembers():
                yield m.name
    elif name.endswith((".whl", ".zip")):
        with zipfile.ZipFile(artifact) as zf:
            for n in zf.namelist():
                yield n


def iter_artifacts(targets):
    for t in targets:
        p = Path(t)
        if p.is_dir():
            yield from sorted(p.rglob("*.tar.gz"))
            yield from sorted(p.rglob("*.whl"))
        elif p.is_file():
            yield p


def scan(artifact: Path):
    """Return a list of (member, reason) for forbidden paths in one artifact."""
    bad = []
    for member in members(artifact):
        reason = is_forbidden(member)
        if reason:
            bad.append((member, reason))
    return bad


def main(argv):
    targets = argv[1:] or ["dist"]
    artifacts = list(iter_artifacts(targets))
    if not artifacts:
        print("check_dist_no_leak: no .tar.gz/.whl artifacts found under %s" % targets,
              file=sys.stderr)
        return 2
    total_leaks = 0
    for art in artifacts:
        bad = scan(art)
        if bad:
            total_leaks += len(bad)
            print("LEAK: %s ships %d forbidden path(s):" % (art, len(bad)))
            for member, reason in bad[:50]:
                print("  - %s  [%s]" % (member, reason))
            if len(bad) > 50:
                print("  ... and %d more" % (len(bad) - 50))
        else:
            print("OK:   %s (no private/ or local-state paths)" % art)
    if total_leaks:
        print("\nFAIL: %d forbidden path(s) found -- refusing to publish." % total_leaks)
        return 1
    print("\nPASS: %d artifact(s) clean." % len(artifacts))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
