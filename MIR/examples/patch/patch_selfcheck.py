#!/usr/bin/env python3
"""Each MIR-1.1 check, observed failing on a real patch and a real store.

The patch is content-addressed, so a mutation cannot be made by editing a file
in place: the store would then hold bytes that do not hash to their name and
C-03 would fail for a reason unrelated to the check under test. Every case here
rewrites the patch, files it under its new digest, and repoints the record at
it — so the patch block is what changes, not the store's integrity.

    python3 examples/patch/patch_selfcheck.py

Each row asserts the check that must fail, the qualifier that must be absent,
and that both implementations produce the same bytes.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
STORE = os.path.join(HERE, "artifacts")

sys.path.insert(0, ROOT)
from validate import canonical_bytes  # noqa: E402

ZERO = "0" * 64


def sha256_hex(data):
    return hashlib.sha256(data).hexdigest()


def reidentify(record):
    body = {key: value for key, value in record.items() if key != "id"}
    record["id"] = "sha256:" + sha256_hex(canonical_bytes(body))


def refile(record, store, patch, canonical=True):
    """Store the patch under its digest and point the record at those bytes."""
    payload = canonical_bytes(patch) if canonical else json.dumps(
        patch, indent=2).encode("utf-8")
    digest = sha256_hex(payload)
    with open(os.path.join(store, digest), "wb") as handle:
        handle.write(payload)
    record["intervention"]["payload_hash"] = "sha256:" + digest
    for run in record["runs"]:
        run["intervention_hash"] = "sha256:" + digest
    return "sha256:" + digest


def _ops(patch):
    return patch["edit"]["ops"]


# Each mutation receives (patch, record, store) and changes what the case needs.
def p01_other_base(patch, record, store):
    patch["base"]["checkpoint_hash"] = record["manifest_hash"]


def p01_unresolvable(patch, record, store):
    patch["base"]["checkpoint_hash"] = ZERO
    record["base"]["hash"] = "sha256:" + ZERO
    for run in record["runs"]:
        run["base_hash"] = "sha256:" + ZERO


def p02_bad_id(patch, record, store):
    patch["id"] = "wpp:sha256:" + "f" * 64
    return False  # do not recompute the id: the mismatch is the case


def p02_num_changed(patch, record, store):
    patch["edit"]["num_changed"] = 99


def p02_order(patch, record, store):
    _ops(patch)[0]["indices"] = [4, 0]
    _ops(patch)[0]["deltas"] = [-1.0, 0.5]


def p02_type(patch, record, store):
    patch["edit"]["type"] = "operator"


def p03_dependency_missing(patch, record, store):
    record["lineage"] = []


def p03_dependency_unknown(patch, record, store):
    patch["dependencies"] = ["wpp:sha256:" + ZERO]


def p04_invariant_differs(patch, record, store):
    patch["invariants"] = copy.deepcopy(patch["invariants"])
    patch["invariants"][0]["bound"] = 0.42


def p04_reference_missing(patch, record, store):
    del patch["falsifier"]
    patch["falsifier_hash"] = "sha256:" + ZERO


def p05_wrong_prior(patch, record, store):
    patch["inverse"]["prior"][0]["values"][0] = 1.25


def p05_no_inverse(patch, record, store):
    del patch["inverse"]


def p05_no_change(patch, record, store):
    _ops(patch)[0]["deltas"] = [0.0, 0.0]
    _ops(patch)[1]["factor"] = 1.0


def p05_out_of_range(patch, record, store):
    _ops(patch)[0]["deltas"] = [1e39, -1.0]


def p03_external(patch, record, store):
    patch["external_dependencies"] = list(patch["dependencies"])
    patch["dependencies"] = []


def p04_reference(patch, record, store):
    payload = canonical_bytes(record["falsifier"])
    digest = sha256_hex(payload)
    with open(os.path.join(store, digest), "wb") as handle:
        handle.write(payload)
    del patch["falsifier"]
    patch["falsifier_hash"] = "sha256:" + digest


def p05_not_container(patch, record, store):
    patch["base"]["checkpoint_hash"] = record["manifest_hash"]
    record["base"]["hash"] = record["manifest_hash"]
    for run in record["runs"]:
        run["base_hash"] = record["manifest_hash"]


def p02_not_canonical(patch, record, store):
    return "pretty"  # file the patch as pretty-printed JSON


# (label, record, mutate, check id, expected state, qualifier that must be absent)
CASES = [
    ("P-01: base names a different artifact",
     "a", p01_other_base, "P-01", "fail", ""),
    ("P-01: base does not resolve",
     "a", p01_unresolvable, "P-01", "fail", ""),
    ("P-02: id does not match the content address",
     "a", p02_bad_id, "P-02", "fail", "patch-executable"),
    ("P-02: num_changed disagrees with the operations",
     "a", p02_num_changed, "P-02", "fail", "patch-executable"),
    ("P-02: indices are not ascending",
     "a", p02_order, "P-02", "fail", "patch-executable"),
    ("P-02: edit type does not match its operations",
     "a", p02_type, "P-02", "fail", "patch-executable"),
    ("P-03: the dependency is not in the lineage",
     "b", p03_dependency_missing, "P-03", "fail", "stackable"),
    ("P-03: the dependency names nothing",
     "b", p03_dependency_unknown, "P-03", "fail", "stackable"),
    ("P-04: the patch's invariants differ from the record's",
     "a", p04_invariant_differs, "P-04", "fail", ""),
    ("P-04: the falsifier reference does not resolve",
     "a", p04_reference_missing, "P-04", "fail", ""),
    ("P-03: a dependency declared external is not required in the lineage",
     "b", p03_external, "P-03", "pass", ""),
    ("P-04: the falsifier is referenced by content hash",
     "a", p04_reference, "P-04", "pass", ""),
    ("P-05: the exact inverse restores the wrong value",
     "a", p05_wrong_prior, "P-05", "fail", "reversible"),
    ("P-05: no exact inverse is supplied",
     "a", p05_no_inverse, "P-05", "not run", "reversible"),
    ("P-05: the patch changes no weights",
     "a", p05_no_change, "P-05", "fail", "reversible"),
    ("P-05: an operand has no finite binary32 value",
     "a", p05_out_of_range, "P-05", "fail", "reversible"),
    ("P-05: the base is not an array container",
     "a", p05_not_container, "P-05", "not run", ""),
    ("P-02: stored bytes are not canonical",
     "a", p02_not_canonical, "P-02", "pass", ""),
]


def materialise(case):
    """Build one case in a temporary directory: (label, record path, store)."""
    label, target, mutate, _check, _state, _absent = case
    temp = tempfile.mkdtemp(prefix="mir-patch-")
    store = os.path.join(temp, "artifacts")
    shutil.copytree(STORE, store)
    name = "record-a.json" if target == "a" else "record-b.json"
    with open(os.path.join(HERE, name), encoding="utf-8") as handle:
        record = json.load(handle)
    payload = record["intervention"]["payload_hash"][len("sha256:"):]
    with open(os.path.join(store, payload), encoding="utf-8") as handle:
        patch = json.load(handle)

    verdict = mutate(patch, record, store)
    if verdict is not False:
        patch_id = sha256_hex(canonical_bytes(
            {key: value for key, value in patch.items() if key != "id"}))
        patch["id"] = "wpp:sha256:" + patch_id
    refile(record, store, patch, canonical=(verdict != "pretty"))
    reidentify(record)
    path = os.path.join(temp, name)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2)
        handle.write("\n")
    return label, path, store, temp


def report(record_path, store):
    output = {}
    for name, command in (
        ("python", [sys.executable, os.path.join(ROOT, "validate.py")]),
        ("go", [os.path.join(ROOT, "impl2", "mir-validate")]),
    ):
        result = subprocess.run(command + [record_path, "--artifacts", store, "--json"],
                                capture_output=True, text=True)
        output[name] = (result.stdout, result.returncode)
    return output


def main():
    if not os.path.isfile(os.path.join(ROOT, "impl2", "mir-validate")):
        build = subprocess.run(["go", "build", "-o", "mir-validate", "."],
                               cwd=os.path.join(ROOT, "impl2"))
        if build.returncode != 0:
            print("cannot build the Go implementation")
            return 2
    failures = 0
    for case in CASES:
        label, path, store, temp = materialise(case)
        try:
            results = report(path, store)
            python_text, python_code = results["python"]
            go_text, go_code = results["go"]
            same = python_text == go_text and python_code == go_code
            parsed = json.loads(python_text)
            patch = parsed.get("patch") or {"checks": [], "qualifiers": []}
            states = {check["id"]: check["result"] for check in patch["checks"]}
            _label, _target, _mutate, check_id, expected, absent = case
            state_ok = states.get(check_id) == expected
            absent_ok = absent == "" or absent not in patch["qualifiers"]
            ok = same and state_ok and absent_ok
            print("%-56s %s" % (label, "ok" if ok else "FAILED"))
            if not ok:
                failures += 1
                if not same:
                    print("  python and go disagree")
                if not state_ok:
                    print("  %s: expected %s, got %s"
                          % (check_id, expected, states.get(check_id)))
                if not absent_ok:
                    print("  qualifier %s should be absent: %s"
                          % (absent, patch["qualifiers"]))
        finally:
            shutil.rmtree(temp, ignore_errors=True)
    print()
    print("%d cases, %s" % (len(CASES), "ok" if not failures else "%d FAILED" % failures))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
