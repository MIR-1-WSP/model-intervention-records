#!/usr/bin/env python3
"""Generate the MIR-1.1 patch examples and their artifact store.

Two records and two patches on a tiny `wpp-array-0.1` base:

  record-a  applies patch 1 to the base, with an exact inverse
  record-b  applies patch 2 on top of record-a's patch, so the dependency and
            the application order are both exercised

The store under `patch/artifacts` holds the base container, both patches, and
record-a's canonical body (record-b cites it as a lineage entry), plus copies of
the manifest and harness from `../artifacts` so each example is self-contained.

Deterministic and idempotent: running it again produces the same bytes.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PATCH_DIR = os.path.join(HERE, "patch")
STORE = os.path.join(PATCH_DIR, "artifacts")
PARENT_STORE = os.path.join(ROOT, "artifacts")

sys.path.insert(0, ROOT)
from validate import canonical_bytes  # noqa: E402

MANIFEST_HASH = "sha256:51c4d15ab06179fa080b34c3215cbe9d7a3fb3c5e9fcc2a82ee676dfab62055e"
HARNESS_HASH = "sha256:9cef3828bbb16da7d1296edd8d8ce6d2cd54107d5437d7af8496c65a12873f34"

INVARIANTS = [
    {"property": "mean_tokens", "measurement": "instruct-set/mean-tokens",
     "metric": "mean_tokens", "direction": "delta", "bound": 0.1},
    {"property": "math_accuracy", "measurement": "math500/exact",
     "metric": "math_accuracy", "direction": "floor", "bound": 0.5},
    {"property": "gsm8k_accuracy", "measurement": "gsm8k/exact",
     "metric": "gsm8k_accuracy", "direction": "floor", "bound": 0.3},
    {"property": "format", "measurement": "leading-token-check",
     "metric": "format", "direction": "ceiling", "bound": 0.0},
]

CLAIM = {
    "behavior": "mean_tokens",
    "distribution": "instruct-set",
    "direction": "decrease",
    "threshold": 0.9,
    "scoring_metrics": ["mean_tokens"],
}

CLAIMANT = {"operator": "operator-a", "funding_source": "example-fund-a"}

RUNS = [
    {
        "operator": "operator-b",
        "funding_source": "example-fund-b",
        "cost": 4.0,
        "wall_time_s": 14400.0,
        "started_at": "2026-11-18T00:00:00Z",
        "result": {"n_units": 500, "samples_per_unit": 4, "mean_tokens": 0.62,
                   "math_accuracy": 0.78, "gsm8k_accuracy": 0.44},
    },
    {
        "operator": "operator-c",
        "funding_source": "example-fund-c",
        "cost": 3.0,
        "wall_time_s": 12600.0,
        "started_at": "2026-11-19T00:00:00Z",
        "result": {"n_units": 500, "samples_per_unit": 4, "mean_tokens": 0.63,
                   "math_accuracy": 0.79, "gsm8k_accuracy": 0.45},
    },
]


def sha256_hex(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, obj):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(obj, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def put_artifact(data):
    digest = sha256_hex(data)
    with open(os.path.join(STORE, digest), "wb") as handle:
        handle.write(data)
    return "sha256:" + digest


def put_body(body):
    payload = canonical_bytes(body)
    digest = sha256_hex(payload)
    with open(os.path.join(STORE, digest), "wb") as handle:
        handle.write(payload)
    return digest


def build_patch(body):
    """Fill in the id from the canonical body without it, then return the bytes."""
    patch_id = sha256_hex(canonical_bytes(body))
    body = dict(body)
    body["id"] = "wpp:sha256:" + patch_id
    payload = canonical_bytes(body)
    put_artifact(payload)
    return body, patch_id, "sha256:" + sha256_hex(payload)


def build_record(body, path):
    record_id = put_body(body)
    record = dict(body)
    record["id"] = "sha256:" + record_id
    write_json(path, record)
    return record_id


def main():
    if os.path.isdir(STORE):
        shutil.rmtree(STORE)
    os.makedirs(STORE, exist_ok=True)

    # The base: one 2x3 float32 tensor, values 1..6 in row-major order.
    values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    container = {
        "wpp_array_version": "0.1",
        "tensors": {
            "w": {
                "shape": [2, 3],
                "dtype": "float32",
                "data_b64": base64.b64encode(
                    struct.pack("<6f", *values)).decode("ascii"),
            }
        },
    }
    base_hash = put_artifact(canonical_bytes(container))
    write_json(os.path.join(PATCH_DIR, "base.wpp-array.json"), container)

    for name in (MANIFEST_HASH, HARNESS_HASH):
        source = os.path.join(PARENT_STORE, name[7:])
        shutil.copyfile(source, os.path.join(STORE, name[7:]))

    falsifier_a = {
        "command": "python3 examples/falsify_example.py examples/patch/record-a.json",
        "returns": "boolean",
    }
    patch1_body = {
        "wpp_version": "0.1",
        "base": {"checkpoint_hash": base_hash,
                 "model_id": "example/tiny-2x3",
                 "format": "wpp-array-0.1"},
        "dependencies": [],
        "edit": {
            "type": "sparse_delta",
            "ops": [
                {"op": "add", "tensor": "w", "indices": [0, 4], "deltas": [0.5, -1.0]},
                {"op": "scale", "tensor": "w", "indices": [5], "factor": 2.0},
            ],
            "num_changed": 3,
            "sparsity": 0.5,
        },
        "inverse": {
            "kind": "exact",
            "prior": [{"tensor": "w", "indices": [0, 4, 5],
                       "values": [1.0, 5.0, 6.0]}],
        },
        "invariants": INVARIANTS,
        "falsifier": falsifier_a,
        "metadata": {
            "title": "nudge two weights and double a third",
            "author": "MIR-1.1 example",
            "created": "2026-11-18",
            "license": "CC0-1.0",
        },
    }
    _patch1, patch1_id, patch1_hash = build_patch(patch1_body)

    record_a_body = {
        "mir_version": "1",
        "manifest_hash": MANIFEST_HASH,
        "base": {
            "hash": base_hash,
            "location": "examples/patch/base.wpp-array.json",
            "license": "example-only",
        },
        "intervention": {"type": "weights", "payload_hash": patch1_hash},
        "claimant": CLAIMANT,
        "claim": CLAIM,
        "falsifier": falsifier_a,
        "invariants": INVARIANTS,
        "harness": {"hash": HARNESS_HASH, "location": "examples/harness"},
        "runs": [dict(run, harness_hash=HARNESS_HASH, base_hash=base_hash,
                      intervention_hash=patch1_hash) for run in RUNS],
        "lineage": [],
        "supersedes": None,
        "status": "replicated",
    }
    record_a_id = build_record(record_a_body, os.path.join(PATCH_DIR, "record-a.json"))

    falsifier_b = {
        "command": "python3 examples/falsify_example.py examples/patch/record-b.json",
        "returns": "boolean",
    }
    patch2_body = {
        "wpp_version": "0.1",
        "base": {"checkpoint_hash": base_hash,
                 "model_id": "example/tiny-2x3",
                 "format": "wpp-array-0.1"},
        "dependencies": ["wpp:sha256:" + patch1_id],
        "edit": {
            "type": "operator",
            "ops": [
                {"op": "add_vector", "tensor": "w", "rows": [0],
                 "vector": [0.25, 0.25, 0.25], "scale": 2.0},
            ],
            "num_changed": 3,
        },
        "inverse": {
            "kind": "exact",
            "prior": [{"tensor": "w", "indices": [0, 1, 2],
                       "values": [1.5, 2.0, 3.0]}],
        },
        "invariants": INVARIANTS,
        "falsifier": falsifier_b,
        "metadata": {
            "title": "add a scaled direction to the first row",
            "author": "MIR-1.1 example",
            "created": "2026-11-18",
            "license": "CC0-1.0",
            "depends_on": "the nudge-and-scale patch",
        },
    }
    _patch2, patch2_id, patch2_hash = build_patch(patch2_body)

    record_b_body = dict(record_a_body)
    record_b_body["intervention"] = {"type": "weights", "payload_hash": patch2_hash}
    record_b_body["falsifier"] = falsifier_b
    record_b_body["lineage"] = ["sha256:" + record_a_id]
    record_b_body["runs"] = [
        dict(run, harness_hash=HARNESS_HASH, base_hash=base_hash,
             intervention_hash=patch2_hash) for run in RUNS
    ]
    record_b_id = build_record(record_b_body, os.path.join(PATCH_DIR, "record-b.json"))

    print("base        %s" % base_hash)
    print("patch 1     wpp:sha256:%s  payload %s" % (patch1_id, patch1_hash))
    print("patch 2     wpp:sha256:%s  payload %s" % (patch2_id, patch2_hash))
    print("record-a    sha256:%s  (expected: PASS, patch-executable, reversible)" % record_a_id)
    print("record-b    sha256:%s  (expected: PASS, stackable)" % record_b_id)


if __name__ == "__main__":
    main()
