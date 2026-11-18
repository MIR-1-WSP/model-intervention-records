#!/usr/bin/env python3
"""Each MIR-1.2 qualifier, observed present and absent, in both implementations.

A qualifier is derived, so a case is a record plus the exact list it must
produce. The script runs the Python and the Go validator on every case and
requires their bytes to match, so a qualifier that is implemented in one
language and not the other fails here rather than in a reader's hands.

    python3 records/qualifier_selfcheck.py
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STORE = os.path.join(HERE, "artifacts")

sys.path.insert(0, ROOT)
from validate import canonical_bytes  # noqa: E402


def reidentify(record):
    body = {key: value for key, value in record.items() if key != "id"}
    record["id"] = "sha256:" + hashlib.sha256(canonical_bytes(body)).hexdigest()


def load(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as handle:
        return json.load(handle)


def add_baseline(record):
    record["runs"][0]["intervention_hash"] = None


def measure_format(record):
    for run in record["runs"]:
        run["result"]["format"] = 0.0


def unprice_one(record):
    record["runs"][0]["cost"] = None


def same_population(record):
    record["runs"][0]["result"]["n_units"] = 500


def claimant_only(record):
    record["runs"][3]["operator"] = record["claimant"]["operator"]


def no_runs(record):
    record["runs"] = []


# (label, source record, mutation, expected qualifiers in order)
CASES = [
    ("the worked example: a baseline, and a rebuild that cannot be priced",
     "records/MIR-R1.json", None,
     ["baseline-present", "unpriced-reproduction"]),
    ("the positive fixture: one population, no baseline",
     "examples/conforming.json", None,
     ["single-population"]),
    ("a baseline is present", "examples/conforming.json", add_baseline,
     ["baseline-present", "single-population"]),
    ("every invariant is re-measured by the independent run",
     "examples/conforming.json", measure_format,
     ["single-population", "invariants-replicated"]),
    ("an independent run reports the claim but not its cost",
     "examples/conforming.json", unprice_one,
     ["single-population", "unpriced-reproduction"]),
    ("every run measured one population", "records/MIR-R1.json", same_population,
     ["baseline-present", "single-population", "unpriced-reproduction"]),
    ("the rebuild is signed by the claimant itself",
     "records/MIR-R1.json", claimant_only,
     ["baseline-present"]),
    ("no runs at all", "examples/conforming.json", no_runs, []),
]


def report(path, store):
    outputs = {}
    for name, command in (
        ("python", [sys.executable, os.path.join(ROOT, "validate.py")]),
        ("go", [os.path.join(ROOT, "impl2", "mir-validate")]),
    ):
        proc = subprocess.run(command + [path, "--artifacts", store, "--json"],
                              capture_output=True, text=True)
        outputs[name] = (proc.stdout, proc.returncode)
    return outputs


def main():
    binary = os.path.join(ROOT, "impl2", "mir-validate")
    if not os.path.isfile(binary):
        build = subprocess.run(["go", "build", "-o", "mir-validate", "."],
                               cwd=os.path.join(ROOT, "impl2"))
        if build.returncode != 0:
            print("cannot build the Go implementation")
            return 2
    failures = 0
    for label, source, mutate, expected in CASES:
        record = copy.deepcopy(load(source))
        if mutate is not None:
            mutate(record)
        reidentify(record)
        handle, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(record, stream)
        try:
            outputs = report(path, STORE)
            python_text, python_code = outputs["python"]
            go_text, go_code = outputs["go"]
            same = python_text == go_text and python_code == go_code
            actual = json.loads(python_text).get("qualifiers", [])
            ok = same and actual == expected
            print("%-62s %s" % (label, "ok" if ok else "FAILED"))
            if not ok:
                failures += 1
                if not same:
                    print("  python and go disagree")
                if actual != expected:
                    print("  expected %s, got %s" % (expected, actual))
        finally:
            os.unlink(path)
    print()
    print("%d cases, %s" % (len(CASES), "ok" if not failures else "%d FAILED" % failures))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
