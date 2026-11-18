#!/usr/bin/env python3
"""Refresh the files the Space serves from their copies in the repository.

The Space is a separate build context, so the validator, the specification and
the worked example have to be present inside it. Copying is fine; copying
silently is not, because a Space running an older validator would report
conformance for a rule that has changed. --check compares every mirrored file
by digest and exits non-zero on drift, and is run by ../crosscheck.py.

    python3 space/sync.py          # copy
    python3 space/sync.py --check  # verify, do not write
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

FILES = [
    ("validate.py", "validate.py"),
    ("patchcheck.py", "patchcheck.py"),
    ("schema.json", "schema.json"),
    ("patch-schema.json", "patch-schema.json"),
    ("kernel.md", "kernel.md"),
    ("MIR-1-spec.md", "MIR-1-spec.md"),
    ("records/MIR-R1.json", "records/MIR-R1.json"),
    ("examples/patch/record-a.json", "examples/patch/record-a.json"),
]

DIRECTORIES = [
    ("records/artifacts", "records/artifacts"),
    ("artifacts", "artifacts"),
    ("examples/patch/artifacts", "examples/patch/artifacts"),
]


def digest(path):
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            hasher.update(block)
    return hasher.hexdigest()


def source_path(name):
    """The specification is published beside MIR/ in the repository and at the
    root of the arXiv archive, which flattens the two into one directory. Both
    copies are normative, so both layouts have to verify. Only the spec is
    looked for in two places; a missing validator must still be reported."""
    if name == "MIR-1-spec.md":
        beside = os.path.join(ROOT, name)
        if os.path.isfile(beside):
            return beside
        return os.path.join(os.path.dirname(ROOT), name)
    return os.path.join(ROOT, name)


def mirror():
    pairs = [(source_path(source), os.path.join(HERE, target))
             for source, target in FILES]
    for source_dir, target_dir in DIRECTORIES:
        source_root = os.path.join(ROOT, source_dir)
        for name in sorted(os.listdir(source_root)):
            source = os.path.join(source_root, name)
            if os.path.isfile(source):
                pairs.append((source, os.path.join(HERE, target_dir, name)))
    return pairs


def stale():
    """Copies whose source is gone.

    A content-addressed store never deletes, so a rebuilt record leaves its
    predecessor behind. Copying alone makes the Space a superset of the
    repository, and a superset is not a mirror: it can serve a record body in a
    format the validator no longer accepts. The stale copies are named here so
    that both modes see them.
    """
    found = []
    for source_dir, target_dir in DIRECTORIES:
        source_root = os.path.join(ROOT, source_dir)
        target_root = os.path.join(HERE, target_dir)
        if not os.path.isdir(target_root):
            continue
        for name in sorted(os.listdir(target_root)):
            path = os.path.join(target_root, name)
            if os.path.isfile(path) and not os.path.isfile(os.path.join(source_root, name)):
                found.append(path)
    return found


def main(argv):
    check = "--check" in argv
    problems = 0
    for source, target in mirror():
        if not os.path.isfile(source):
            print("missing source: %s" % os.path.relpath(source, ROOT))
            problems += 1
            continue
        if check:
            if not os.path.isfile(target):
                print("missing copy:  %s" % os.path.relpath(target, HERE))
                problems += 1
            elif digest(source) != digest(target):
                print("out of date:   %s" % os.path.relpath(target, HERE))
                problems += 1
        else:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copyfile(source, target)
    for path in stale():
        if check:
            print("stale copy:    %s" % os.path.relpath(path, HERE))
            problems += 1
        else:
            os.remove(path)
    if check:
        print("%d files checked, %s" % (len(mirror()),
                                        "in sync" if not problems else "%d problem(s)" % problems))
        return 0 if not problems else 1
    print("copied %d files" % len(mirror()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
