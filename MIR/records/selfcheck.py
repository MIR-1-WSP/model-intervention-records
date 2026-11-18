#!/usr/bin/env python3
"""Show that a check fails when the condition it checks is removed.

A check that has never been seen to fail is not known to work. Each case below
takes the real record, removes exactly one thing, recomputes the content address
so that C-01 stays green where the mutation is not C-01 itself, and asserts
which check reports the removal.

Every check that reads a record field has a case that makes it fail. C-09 is the
serializer's round-trip and cannot be removed by mutating a record; it is
exercised on every run and by the two-implementation differential test.

    python3 records/selfcheck.py
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
VALIDATOR = os.path.join(ROOT, "validate.py")
STORE = os.path.join(HERE, "artifacts")
RECORD = os.path.join(HERE, "MIR-R1.json")

sys.path.insert(0, ROOT)
from validate import SCHEMA_KEYWORDS, SCHEMA_METADATA, canonical_bytes  # noqa: E402


def reidentify(record):
    """Recompute the id so that a mutation does not also trip C-01."""
    body = {k: v for k, v in record.items() if k != "id"}
    record["id"] = "sha256:" + hashlib.sha256(canonical_bytes(body)).hexdigest()
    return record


def run(record, store=STORE):
    handle, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(handle, "w", encoding="utf-8") as fh:
        json.dump(record, fh)
    command = [sys.executable, VALIDATOR, path, "--json"]
    if store:
        command += ["--artifacts", store]
    try:
        proc = subprocess.run(command, capture_output=True, text=True)
    finally:
        os.unlink(path)
    report = json.loads(proc.stdout)
    return {c["id"] for c in report["checks"] if not c["ok"]}


def bad_id(record):
    """Change the declared id without changing the content it addresses."""
    record["id"] = "sha256:" + "00" * 32


def bad_falsifier(record):
    """Declare a falsifier whose verdict is not a boolean."""
    record["falsifier"]["returns"] = "string"


def drop_cost(record):
    """Disclose a number on every run.

    Zero cost is legitimate on owned hardware, so the control keeps it and
    supplies a real duration. A record that declares zero for both is a record
    that did not run, and C-07 rejects that pair.
    """
    for run_ in record["runs"]:
        run_["cost"] = 0.0
        if run_["wall_time_s"] is None:
            run_["wall_time_s"] = 1800.0


def drop_population(record):
    del record["runs"][0]["result"]["n_units"]


def dart_into_nothing(record):
    record["runs"][3]["result"]["artifact"] = "sha256:" + "ab" * 32


def drop_invariant(record):
    scored = set(record["claim"]["scoring_metrics"])
    record["invariants"] = [i for i in record["invariants"] if i["metric"] in scored]


def relabel_metric(record):
    """Keep the property names, point every metric at the claim's own metric.

    This is the degenerate form of the Section 2 failure: the property that must
    not change is the property being optimized. In v1 the same record passed by
    setting one boolean; there is no boolean to set now, because the metric is
    compared against the declared scoring function.
    """
    for inv in record["invariants"]:
        inv["metric"] = record["claim"]["behavior"]


def drop_manifest(record):
    record["manifest_hash"] = "sha256:" + "cd" * 32


def drop_lineage(record):
    record["base"] = {"hash": "sha256:" + "ef" * 32, "location": "gone", "license": "gone"}
    record["lineage"] = []


def null_intervention(record):
    """Claim a change while the payload is the base.

    Every hash still resolves, so every check that asks "does this resolve?"
    passes. Nothing in the suite asks whether the payload differs from the base,
    or whether it was derived from it. See NOTES.md, D-6.
    """
    record["intervention"]["payload_hash"] = record["base"]["hash"]


def extra_field(record):
    """Carry a field the schema does not declare.

    The schema says additionalProperties false. Before C-02 ran the schema, an
    unknown field was accepted everywhere and the published shape was advisory.
    """
    record["notes"] = "unexpected"


def drop_claim_metric(record):
    """Stop reporting the quantity the claim is about.

    The record still parses, the lineage still resolves, and every hash still
    resolves. Nothing else notices: before C-11, the number in the claim did not
    have to appear anywhere in the record.
    """
    del record["runs"][0]["result"][record["claim"]["behavior"]]


def orphan_status(record):
    """Declare the status for broken lineage while the lineage resolves."""
    record["status"] = "orphan"


def claim_replication(record):
    """Declare the strongest status without a run that could support it.

    The record carries two operators and neither funding source is disclosed,
    so independence cannot be established against the claimant. Before C-10
    existed, this record passed every check but C-07.
    """
    record["status"] = "replicated"


def schema_keywords(node, found):
    """Collect the keywords a schema uses, in schema positions only."""
    if not isinstance(node, dict):
        return found
    for key, value in node.items():
        found.add(key)
        if key in ("properties", "definitions") and isinstance(value, dict):
            for sub in value.values():
                schema_keywords(sub, found)
        elif key == "items":
            schema_keywords(value, found)
        elif key in ("oneOf", "allOf", "anyOf") and isinstance(value, list):
            for sub in value:
                schema_keywords(sub, found)
    return found


def zero_wall_time(record):
    """Declare that a run which produced results took no time."""
    record["runs"][0]["wall_time_s"] = 0.0


def bare_hex_lineage(record):
    """Name a parent without the `sha256:` prefix.

    The schema accepts both spellings, so both have to be content-addressed. A
    bare-hex entry that escapes C-03 lets a file whose bytes do not match its
    name carry the lineage.
    """
    record["lineage"] = ["cd" * 32]


def huge_unit_count(record):
    """An integer too large to convert to float is still an integer."""
    record["runs"][0]["result"]["n_units"] = 10 ** 400


def baseline_as_replication(record):
    """A run that never applies the intervention cannot support `replicated`."""
    record["runs"][0]["intervention_hash"] = None


def respell_operator(record):
    """Sign every run with the claimant's own name in a different case.

    Case and surrounding whitespace are not identity. While operators were
    compared case-sensitively, a claimant could reach `replicated` by adding a
    run signed with its own name re-spelled, which is the degenerate independence
    the funding rule already prevents on the other field.
    """
    name = record["claimant"]["operator"]
    for run_ in record["runs"]:
        run_["operator"] = "  " + name.upper() + "  "


def reordered_unresolved_hashes(record):
    """Two hashes C-03 finds by walking, written in non-canonical key order.

    A malformed lineage entry is not collected by the structural pass, so both
    it and manifest_hash are discovered by the walk. Canonical form sorts keys,
    so a detail that lists them in document order changes on export/import and
    C-09 reports a round-trip that did not preserve the result.
    """
    record["manifest_hash"] = "sha256:" + "ab" * 32
    record["lineage"] = ["sha256:xyz"]
    ordered = {"manifest_hash": record["manifest_hash"], "lineage": record["lineage"]}
    for key, value in record.items():
        if key not in ordered:
            ordered[key] = value
    record.clear()
    record.update(ordered)


CASES = [
    ("change the id without changing the content", bad_id, {"C-01", "C-07"}, False),
    ("disclose cost as zero and a real duration", drop_cost, set(), True),
    ("remove the population from a run", drop_population, {"C-02", "C-07"}, True),
    ("cite a hash to content that is not there", dart_into_nothing, {"C-03", "C-07"}, True),
    ("declare a falsifier that does not return a boolean", bad_falsifier, {"C-02", "C-04", "C-07"}, True),
    ("keep only invariants inside the scoring function", drop_invariant, {"C-02", "C-05", "C-07"}, True),
    ("name the claim's own metric as an invariant", relabel_metric, {"C-05", "C-07"}, True),
    ("point the base at nothing and keep the lineage empty", drop_lineage, {"C-03", "C-06", "C-07", "C-10"}, True),
    ("name a manifest that does not exist", drop_manifest, {"C-03", "C-07", "C-08"}, True),
    ("make the intervention the base itself", null_intervention, {"C-07"}, True),
    ("declare 'replicated' without an independent run", claim_replication, {"C-07", "C-10"}, True),
    ("declare 'orphan' while the lineage resolves", orphan_status, {"C-07", "C-10"}, True),
    ("stop reporting the metric the claim is about", drop_claim_metric, {"C-07", "C-11"}, True),
    ("add a field the schema does not declare", extra_field, {"C-02", "C-07"}, True),
    ("name a parent without the sha256: prefix", bare_hex_lineage, {"C-03", "C-06", "C-07", "C-10"}, True),
    ("declare a unit count larger than a float can hold", huge_unit_count, {"C-07"}, True),
    ("list unresolved hashes in non-canonical key order", reordered_unresolved_hashes,
     {"C-02", "C-03", "C-06", "C-07", "C-08", "C-10"}, True),
]


POSITIVE_CASES = [
    # The run stops counting toward independence too: MIR-1-04 says an
    # undisclosed run counts toward no requirement.
    ("a run that took no time", zero_wall_time, {"C-02", "C-07", "C-10"}),
    ("count a baseline run as a replication", baseline_as_replication, {"C-10"}),
    ("re-spell the claimant as the independent operator", respell_operator, {"C-10"}),
]


def main():
    with open(RECORD, "r", encoding="utf-8") as fh:
        original = json.load(fh)

    print("%-52s %-14s %s" % ("mutation", "fails", "expected"))
    ok = True
    for label, mutate, expected, reid in CASES:
        record = copy.deepcopy(original)
        mutate(record)
        if reid:
            reidentify(record)
        actual = run(record)
        good = actual == expected
        ok = ok and good
        print("%-52s %-14s %-14s %s" % (
            label, ",".join(sorted(actual)) or "none",
            ",".join(sorted(expected)) or "none", "ok" if good else "MISMATCH"))

    baseline = run(original)
    good = baseline == {"C-07"}
    ok = ok and good
    print("%-52s %-14s %-14s %s" % (
        "the record as published", ",".join(sorted(baseline)) or "none", "C-07",
        "ok" if good else "MISMATCH"))

    # The positive fixture, on its own store. A check seen only to fail is as
    # unknown as one seen only to pass, and the fixture is the only record in
    # the repository that passes everything.
    with open(os.path.join(ROOT, "examples", "conforming.json"), "r", encoding="utf-8") as fh:
        positive = json.load(fh)
    print()
    print("%-52s %-14s %s" % ("positive fixture", "fails", "expected"))
    actual = run(positive, None)
    good = actual == set()
    ok = ok and good
    print("%-52s %-14s %-14s %s" % (
        "examples/conforming.json", ",".join(sorted(actual)) or "none", "none",
        "ok" if good else "MISMATCH"))
    for label, mutate, expected in POSITIVE_CASES:
        record = copy.deepcopy(positive)
        mutate(record)
        reidentify(record)
        actual = run(record, None)
        good = actual == expected
        ok = ok and good
        print("%-52s %-14s %-14s %s" % (
            label, ",".join(sorted(actual)) or "none",
            ",".join(sorted(expected)) or "none", "ok" if good else "MISMATCH"))

    # The schema is the published contract; the validator is one implementation
    # of it. They drifted once: `claimant` was required by the schema and absent
    # from the validator's list, and both implementations carried the same
    # omission, so the differential test could not see it.
    with open(os.path.join(ROOT, "schema.json"), "r", encoding="utf-8") as fh:
        schema = json.load(fh)
    print()
    print("%-52s %-14s %s" % ("schema agreement", "state", "expected"))
    found = schema_keywords(schema, set()) - set(SCHEMA_METADATA)
    unsupported = sorted(found - set(SCHEMA_KEYWORDS))
    good = not unsupported
    ok = ok and good
    print("%-52s %-14s %-14s %s" % (
        "every schema keyword is implemented",
        "yes" if good else "no", "yes", "ok" if good else "MISMATCH: %s" % unsupported))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
