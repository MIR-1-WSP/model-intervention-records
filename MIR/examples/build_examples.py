#!/usr/bin/env python3
"""Generate the MIR-1 example records and their artifact store.

Deterministic and idempotent: running it again produces the same bytes.

A record's `id` is the SHA-256 of its canonical body, where the body is the
record without the `id` field. The artifact store holds the canonical body under
that name, so a lineage entry is resolvable by the same address it is cited by.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STORE = os.path.join(ROOT, "artifacts")

sys.path.insert(0, ROOT)
from validate import canonical_bytes  # noqa: E402


def canonical_bytes(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def sha256_hex(data):
    return hashlib.sha256(data).hexdigest()


def put_artifact(data):
    """Write raw bytes into the store under their digest and return the hash."""
    digest = sha256_hex(data)
    os.makedirs(STORE, exist_ok=True)
    path = os.path.join(STORE, digest)
    with open(path, "wb") as fh:
        fh.write(data)
    return "sha256:" + digest


def put_record(body):
    """Store a record body under its content address and return the bare digest."""
    payload = canonical_bytes(body)
    digest = sha256_hex(payload)
    os.makedirs(STORE, exist_ok=True)
    with open(os.path.join(STORE, digest), "wb") as fh:
        fh.write(payload)
    return digest


def write_json(path, obj):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, ensure_ascii=False, sort_keys=False)
        fh.write("\n")


def main():
    if os.path.isdir(STORE):
        shutil.rmtree(STORE)
    os.makedirs(STORE, exist_ok=True)

    base_hash = put_artifact(b"mir1-example/base/checkpoint-serialization\n")
    payload_hash = put_artifact(b"mir1-example/intervention/response-length-suppressant\n")
    harness_hash = put_artifact(b"mir1-example/harness/math500-gsm8k-format/v1\n")

    manifest = {
        "mir_version": "1",
        "name": "example-registry",
        "parameters": {
            "challenge_window_days": 30,
            "bond_size": 1000,
            "min_independent_replications": 2,
            "benchmark_rotation_days": 180,
        },
    }
    manifest_bytes = canonical_bytes(manifest)
    manifest_hash = "sha256:" + sha256_hex(manifest_bytes)
    with open(os.path.join(STORE, sha256_hex(manifest_bytes)), "wb") as fh:
        fh.write(manifest_bytes)
    write_json(os.path.join(ROOT, "manifest.json"), manifest)

    # Parent record: the unmodified base, measured once. Establishes a lineage root
    # that is itself a record rather than a bare artifact.
    parent_body = {
        "mir_version": "1",
        "manifest_hash": manifest_hash,
        "base": {
            "hash": base_hash,
            "location": "examples/base/checkpoint",
            "license": "example-only",
        },
        "intervention": {"type": "harness", "payload_hash": harness_hash},
        "claimant": {
            "operator": "operator-a",
            "funding_source": "example-fund-a",
        },
        "claim": {
            "behavior": "mean_tokens",
            "distribution": "math500",
            "direction": "increase",
            "threshold": -1.0,
            "scoring_metrics": ["mean_tokens"],
        },
        "falsifier": {
            "command": "python3 examples/falsify_example.py examples/parent.json",
            "returns": "boolean",
        },
        "invariants": [
            {"property": "math_accuracy", "measurement": "math500/exact",
             "metric": "math_accuracy", "direction": "floor", "bound": 0.0},
        ],
        "harness": {"hash": harness_hash, "location": "examples/harness"},
        "runs": [{
            "operator": "operator-a",
            "funding_source": "example-fund-a",
            "cost": 0.0,
            "wall_time_s": 1800.0,
            "started_at": "2026-11-12T00:00:00Z",
            "harness_hash": harness_hash,
            "base_hash": base_hash,
            "intervention_hash": harness_hash,
            "result": {"n_units": 500, "samples_per_unit": 4, "mean_tokens": 0.0,
                       "math_accuracy": 0.0},
        }],
        "lineage": [],
        "supersedes": None,
        "status": "draft",
    }
    parent_id = put_record(parent_body)
    parent_record = dict(parent_body)
    parent_record["id"] = "sha256:" + parent_id
    write_json(os.path.join(HERE, "parent.json"), parent_record)

    common = {
        "mir_version": "1",
        "manifest_hash": manifest_hash,
        "base": {
            "hash": base_hash,
            "location": "examples/base/checkpoint",
            "license": "example-only",
        },
        "harness": {"hash": harness_hash, "location": "examples/harness"},
        "lineage": ["sha256:" + parent_id],
        "supersedes": None,
        "status": "draft",
        "falsifier": {
            "command": "python3 examples/falsify_example.py examples/conforming.json",
            "returns": "boolean",
        },
    }

    # Record 1: a synthetic record shaped after the 2026-11-08 failure, with an
    # invariant set that stays inside the scoring function. Fails C-05 only.
    terse_body = dict(common)
    terse_body["intervention"] = {"type": "weights", "payload_hash": payload_hash}
    terse_body["claimant"] = {
        "operator": "operator-b",
        "funding_source": "example-fund-b",
    }
    terse_body["claim"] = {
        "behavior": "mean_tokens",
        "distribution": "instruct-set",
        "direction": "decrease",
        "threshold": 0.9,
        "scoring_metrics": ["mean_tokens", "task_correctness"],
    }
    terse_body["invariants"] = [
        {"property": "mean_tokens", "measurement": "instruct-set/mean-tokens",
         "metric": "mean_tokens", "direction": "delta", "bound": 0.1},
        {"property": "task_correctness", "measurement": "instruct-set/correct",
         "metric": "task_correctness", "direction": "floor", "bound": 0.0},
    ]
    terse_body["falsifier"] = {
        "command": "python3 examples/falsify_example.py examples/terse-run.json",
        "returns": "boolean",
    }
    terse_body["runs"] = [{
        "operator": "operator-b",
        "funding_source": "example-fund-b",
        "cost": 4.0,
        "wall_time_s": 14400.0,
        "started_at": "2026-11-08T00:00:00Z",
        "harness_hash": harness_hash,
        "base_hash": base_hash,
        "intervention_hash": payload_hash,
        "result": {"n_units": 500, "samples_per_unit": 4, "mean_tokens": 0.62,
                           "math_accuracy": 0.23, "gsm8k_accuracy": 0.0},
    }]
    terse_id = put_record(terse_body)
    terse_record = dict(terse_body)
    terse_record["id"] = "sha256:" + terse_id
    write_json(os.path.join(HERE, "terse-run.json"), terse_record)

    # Record 2: the same intervention with the invariant that would have blocked it.
    good_body = dict(common)
    good_body["intervention"] = {"type": "weights", "payload_hash": payload_hash}
    good_body["status"] = "replicated"
    good_body["claimant"] = {
        "operator": "operator-a",
        "funding_source": "example-fund-a",
    }
    good_body["claim"] = {
        "behavior": "mean_tokens",
        "distribution": "instruct-set",
        "direction": "decrease",
        "threshold": 0.9,
        "scoring_metrics": ["mean_tokens"],
    }
    good_body["invariants"] = [
        {"property": "mean_tokens", "measurement": "instruct-set/mean-tokens",
         "metric": "mean_tokens", "direction": "delta", "bound": 0.1},
        {"property": "math_accuracy", "measurement": "math500/exact",
         "metric": "math_accuracy", "direction": "floor", "bound": 0.5},
        {"property": "gsm8k_accuracy", "measurement": "gsm8k/exact",
         "metric": "gsm8k_accuracy", "direction": "floor", "bound": 0.3},
        {"property": "format", "measurement": "leading-token-check",
         "metric": "format", "direction": "ceiling", "bound": 0.0},
    ]
    good_body["runs"] = [
        {
            "operator": "operator-b",
            "funding_source": "example-fund-b",
            "cost": 4.0,
            "wall_time_s": 14400.0,
            "started_at": "2026-11-08T00:00:00Z",
            "harness_hash": harness_hash,
            "base_hash": base_hash,
            "intervention_hash": payload_hash,
            "result": {"n_units": 500, "samples_per_unit": 4, "mean_tokens": 0.62,
                       "math_accuracy": 0.78, "gsm8k_accuracy": 0.44},
        },
        {
            "operator": "operator-c",
            "funding_source": "example-fund-c",
            "cost": 3.0,
            "wall_time_s": 12600.0,
            "started_at": "2026-11-09T00:00:00Z",
            "harness_hash": harness_hash,
            "base_hash": base_hash,
            "intervention_hash": payload_hash,
            "result": {"n_units": 500, "samples_per_unit": 4, "mean_tokens": 0.63,
                       "math_accuracy": 0.79, "gsm8k_accuracy": 0.45},
        },
    ]
    good_id = put_record(good_body)
    good_record = dict(good_body)
    good_record["id"] = "sha256:" + good_id
    write_json(os.path.join(HERE, "conforming.json"), good_record)

    print("manifest    %s" % manifest_hash)
    print("base        %s" % base_hash)
    print("payload     %s" % payload_hash)
    print("harness     %s" % harness_hash)
    print("parent      sha256:%s" % parent_id)
    print("terse-run   sha256:%s  (expected: FAIL C-05)" % terse_id)
    print("conforming  sha256:%s  (expected: PASS, status replicated)" % good_id)


if __name__ == "__main__":
    main()
