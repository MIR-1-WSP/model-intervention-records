#!/usr/bin/env python3
"""Falsifier for records/MIR-R1.json.

Recomputes the claim from raw per-problem observations rather than trusting any
summary in the record. Prints `true` if the claim survives, `false` if it does
not, and exits 2 with a message if it cannot decide.

Scope, stated plainly: this checks the claim against the observations that were
published. It does not check the observations against the model. That requires
the 1.7 GB checkpoint and a GPU run, and it is the falsifier that costs
something.

    python3 records/falsify.py records/MIR-R1.json
"""

from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "artifacts")


def digest_of(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    if value.startswith("sha256:"):
        value = value[7:]
    return value.lower() if len(value) == 64 else None


def load_artifact(value):
    digest = digest_of(value)
    if digest is None:
        return None
    path = os.path.join(STORE, digest)
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def recompute(blob):
    """Accuracy and unit count from per-problem correct flags, or None."""
    problems = blob.get("per_problem")
    if not isinstance(problems, list) or not problems:
        return None
    correct = 0
    samples = 0
    for entry in problems:
        flags = entry.get("correct")
        if isinstance(flags, bool):
            flags = [flags]
        if not isinstance(flags, list) or not flags:
            return None
        correct += sum(1 for f in flags if f)
        samples += len(flags)
    if samples == 0:
        return None
    return {"n_units": len(problems), "samples": samples, "acc": correct / samples}


def main(argv):
    if len(argv) != 2:
        print("usage: falsify.py RECORD.json", file=sys.stderr)
        return 2
    with open(argv[1], "r", encoding="utf-8") as fh:
        record = json.load(fh)

    threshold = record["claim"]["threshold"]
    checked = []
    for i, run in enumerate(record.get("runs", [])):
        if run.get("intervention_hash") is None:
            continue  # baseline run: it measures the base, not the claim
        blob = load_artifact((run.get("result") or {}).get("artifact"))
        if blob is None:
            continue
        measured = recompute(blob)
        if measured is None:
            continue
        stated = run["result"].get("n_units")
        if stated is not None and stated != measured["n_units"]:
            print("false")
            print("run %d states n_units=%s, raw data has %d"
                  % (i, stated, measured["n_units"]), file=sys.stderr)
            return 0
        checked.append((i, measured))
        if measured["acc"] < threshold:
            print("false")
            print("run %d recomputes to %.4f, below the threshold %.4f"
                  % (i, measured["acc"], threshold), file=sys.stderr)
            return 0

    if not checked:
        print("no run publishes per-problem observations; nothing to recompute", file=sys.stderr)
        return 2
    best = max(c[1]["acc"] for c in checked)
    print("true")
    print("recomputed %d run(s) from per-problem data; best %.4f, threshold %.4f"
          % (len(checked), best, threshold), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
