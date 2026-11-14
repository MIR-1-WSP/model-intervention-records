#!/usr/bin/env python3
"""Build the MIR-1 record for a published weight edit.

Source: Rikiya Takehi, Jayden Teoh, Alex Zhang, Omar Khattab. "Sparks of
Weight-Space Programming", 2026-11-02, MIT CSAIL. Experiment 8: an LLM edits
0.017% of Qwen3.5-0.8B's weights to remove a reasoning loop.

Every number in the record is taken from a file in `raw/`, which is a byte copy
of what the operators published. Nothing is estimated and nothing is rounded up.

Deterministic: run again on the same inputs and the record is byte-identical.

    python3 records/build_record.py
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RAW = os.path.join(HERE, "raw")
STORE = os.path.join(HERE, "artifacts")
RECORD = os.path.join(HERE, "MIR-R1.json")

sys.path.insert(0, ROOT)
from validate import canonical_bytes  # noqa: E402

COMMIT = "4d09ba6d6a7e891dd8063974dfe81b3d78e3494f"
CODE_REPO = "https://github.com/RikiyaT/lm_understand-logs"
HF_EDITED = "https://huggingface.co/RikiyaT/Qwen3.5-0.8B-weight-space-programming"
HF_BASE = "https://huggingface.co/Qwen/Qwen3.5-0.8B"

# Both checkpoints, as the hosts report them. The bytes are 1.7 GB each and are
# not in this repository; they are held as locators and checked over the network.
BASE_SAFETENSORS = {
    "sha256": "04b1c301231dd422b8860db31311ab2721511346a32cb1e079c4c4e5f1fe4696",
    "size": 1746942600,
    "url": HF_BASE + "/resolve/2fc06364715b967f1860aea9cf38778875588b17/"
                     "model.safetensors-00001-of-00001.safetensors",
}
EDITED_SAFETENSORS = {
    "sha256": "fd1e42acdd118ac1b300d37500fd2885e75f5a09de3a33010d802bf7f737b553",
    "size": 1746943032,
    "url": HF_EDITED + "/resolve/main/model.safetensors-00001-of-00001.safetensors",
}


def canonical_bytes(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def sha256_hex(data):
    return hashlib.sha256(data).hexdigest()


def seed_store():
    """Copy every source file into the store under its digest."""
    os.makedirs(STORE, exist_ok=True)
    for name in sorted(os.listdir(RAW)):
        path = os.path.join(RAW, name)
        if not os.path.isfile(path):
            continue
        with open(path, "rb") as fh:
            data = fh.read()
        with open(os.path.join(STORE, sha256_hex(data)), "wb") as fh:
            fh.write(data)


def artifact(name):
    """The digest of a raw source, for citing it inside the record."""
    with open(os.path.join(RAW, name), "rb") as fh:
        return "sha256:" + sha256_hex(fh.read())


def put_bytes(data):
    digest = sha256_hex(data)
    os.makedirs(STORE, exist_ok=True)
    with open(os.path.join(STORE, digest), "wb") as fh:
        fh.write(data)
    return "sha256:" + digest


def put_json(obj):
    return put_bytes(canonical_bytes(obj))


def emit(name, obj):
    """Store an object and also write it out as the exact bytes that were hashed.

    The file and the store entry are the same bytes, so `shasum -a 256` on the
    file gives the digest the record cites. An indented copy would not.
    """
    data = canonical_bytes(obj)
    with open(os.path.join(HERE, name), "wb") as fh:
        fh.write(data)
    return put_bytes(data)


def put_locator(obj):
    os.makedirs(STORE, exist_ok=True)
    path = os.path.join(STORE, obj["sha256"] + ".locator.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return "sha256:" + obj["sha256"]


def load_raw(name):
    with open(os.path.join(RAW, name), "r", encoding="utf-8") as fh:
        return json.load(fh)


def main():
    seed_store()

    base_hash = put_locator(dict(BASE_SAFETENSORS, kind="mir-locator",
                                 media_type="application/octet-stream",
                                 note="full checkpoint, not stored; HEAD the url for x-linked-etag"))
    edited_hash = put_locator(dict(EDITED_SAFETENSORS, kind="mir-locator",
                                  media_type="application/octet-stream",
                                  note="full checkpoint, not stored; HEAD the url for x-linked-etag"))

    manifest = {
        "mir_version": "1",
        "name": "mir-reference",
        "parameters": {
            "challenge_window_days": 90,
            "bond_size": 1000,
            "min_independent_replications": 1,
            "benchmark_rotation_days": 180,
        },
    }
    manifest_hash = emit("manifest.json", manifest)

    harness = {
        "kind": "mir-harness",
        "name": "qwen35-0.8b-math-eval",
        "code_repository": CODE_REPO,
        "code_commit": COMMIT,
        "command": "python3 evaluate.py run <checkpoint> <out> --protocol think35 --sets math500",
        "files": [
            {"path": "exp8_math/code/evaluate.py", "sha256": artifact("evaluate.py")[7:]},
            {"path": "exp8_math/code/build_ckpt.py", "sha256": artifact("build_ckpt.py")[7:]},
            {"path": "exp8_math/code/apply_edit.py", "sha256": artifact("apply_edit.py")[7:]},
        ],
        "dataset": {
            "name": "HuggingFaceH4/MATH-500",
            "split": "test",
            "revision": None,
            "note": "load_dataset is called without a revision; the harness hash covers the code and not the data",
        },
        "sampling": {
            "temperature": 0.6, "top_p": 0.95, "top_k": 20,
            "presence_penalty": 1.5, "max_tokens": 32768, "seed": 0,
            "samples_per_problem": 4,
        },
        "environment": {"vllm": "0.33.0", "transformers": "5.20.2", "math_verify": "0.9.0"},
        "grading": "last \\boxed{} answer, exact match after normalization",
        "thinking": True,
    }
    harness_hash = emit("harness.json", harness)

    unedited = load_raw("log_unedited_merged.json")["math500"]
    p50c = load_raw("log_p50c_merged.json")
    p50c_math = p50c["math500"]
    hf_edited = load_raw("scores_edited_math500.json")
    hf_base = load_raw("scores_base_math500.json")

    operators = {
        "csail": {
            "operator": "MIT CSAIL (Takehi, Teoh, Zhang, Khattab)",
            "funding_source": "not disclosed",
        },
        "hf": {
            "operator": "Hugging Face (A. Khaliq, rebuild from published logs)",
            "funding_source": "Hugging Face (employer); not separately disclosed",
        },
    }

    runs = [
        {
            **operators["hf"],
            "cost": None,
            "wall_time_s": None,
            "started_at": "2026-11-02",
            "harness_hash": harness_hash,
            "base_hash": base_hash,
            "intervention_hash": None,
            "result": {
                "n_units": hf_base["summary"]["n_problems"],
                "samples_per_unit": hf_base["summary"]["samples"],
                "math500_accuracy": hf_base["summary"]["acc"],
                "cut_share": hf_base["summary"]["cut_share"],
                "mean_tokens": hf_base["summary"]["mean_tokens"],
                "artifact": artifact("scores_base_math500.json"),
                "note": "smoke test of the base model, 25 of 500 problems; the model card says so, the file name does not",
            },
        },
        {
            **operators["csail"],
            "cost": None,
            "wall_time_s": None,
            "started_at": "2026-10-29",
            "harness_hash": harness_hash,
            "base_hash": base_hash,
            "intervention_hash": None,
            "result": {
                "n_units": 500,
                "samples_per_unit": 4,
                "math500_accuracy": unedited["acc"],
                "cut_share": unedited["cut_share"],
                "mean_tokens": unedited["mean_tokens"],
                "artifact": artifact("log_unedited_merged.json"),
                "timestamp_source": "log repository commit date, an upper bound; the run start is not disclosed",
                "note": "the full baseline; it is in the log repository and not in the model repository",
            },
        },
        {
            **operators["csail"],
            "cost": None,
            "wall_time_s": None,
            "started_at": "2026-10-29",
            "harness_hash": harness_hash,
            "base_hash": base_hash,
            "intervention_hash": edited_hash,
            "result": {
                "n_units": 500,
                "samples_per_unit": 4,
                "math500_accuracy": p50c_math["acc"],
                "cut_share": p50c_math["cut_share"],
                "mean_tokens": p50c_math["mean_tokens"],
                "gsm8k_accuracy": p50c["gsm8k"]["acc"],
                "ifeval_accuracy": p50c["ifeval"]["acc"],
                "artifact": artifact("log_p50c_merged.json"),
                "note": "summary only; per-problem observations for this run are not published",
            },
        },
        {
            **operators["hf"],
            "cost": None,
            "wall_time_s": hf_edited["summary"]["seconds"],
            "started_at": "2026-11-02",
            "harness_hash": harness_hash,
            "base_hash": base_hash,
            "intervention_hash": edited_hash,
            "result": {
                "n_units": hf_edited["summary"]["n_problems"],
                "samples_per_unit": hf_edited["summary"]["samples"],
                "math500_accuracy": hf_edited["summary"]["acc"],
                "cut_share": hf_edited["summary"]["cut_share"],
                "mean_tokens": hf_edited["summary"]["mean_tokens"],
                "gen_tokens": hf_edited["summary"]["gen_tokens"],
                "device": "NVIDIA H200",
                "artifact": artifact("scores_edited_math500.json"),
                "note": "per-problem observation for all 2000 samples; the only run whose accuracy can be recomputed from raw data",
            },
        },
    ]

    body = {
        "mir_version": "1",
        "manifest_hash": manifest_hash,
        "base": {
            "hash": base_hash,
            "location": HF_BASE + "/tree/2fc06364715b967f1860aea9cf38778875588b17",
            "license": "Apache-2.0",
        },
        "intervention": {
            "type": "weights",
            "payload_hash": edited_hash,
            "description": "subtraction of one direction from 64 output columns of down_proj "
                           "in layers 15 and 19 of Qwen3.5-0.8B: 131072 of 752 million weights, "
                           "0.017% of the model, applied as a bit-exact diff and rebuilt with apply_edit.py",
        },
        "claimant": {
            "operator": "MIT CSAIL (Takehi, Teoh, Zhang, Khattab)",
            "funding_source": "not disclosed",
        },
        "claim": {
            "behavior": "math500_accuracy",
            "distribution": "MATH-500 test split (HuggingFaceH4/MATH-500), evaluate.py --protocol think35, "
                            "4 samples per problem, last \\boxed{} graded by math-verify",
            "direction": "increase",
            "threshold": 0.45,
            "scoring_metrics": ["math500_accuracy"],
        },
        "falsifier": {
            "command": "python3 records/falsify.py records/MIR-R1.json",
            "returns": "boolean",
        },
        "invariants": [
            {
                "property": "cut_share",
                "measurement": "share of MATH-500 answers cut at the token limit; the bound is on the "
                               "increase over the base run, so a positive bound is a permitted rise",
                "metric": "cut_share",
                "direction": "delta",
                "bound": 0.05,
            },
            {
                "property": "gsm8k_accuracy",
                "measurement": "GSM8K exact match, absolute floor",
                "metric": "gsm8k_accuracy",
                "direction": "floor",
                "bound": 0.60,
            },
            {
                "property": "ifeval_accuracy",
                "measurement": "IFEval prompt-level strict accuracy, absolute floor",
                "metric": "ifeval_accuracy",
                "direction": "floor",
                "bound": 0.40,
            },
        ],
        "harness": {"hash": harness_hash, "location": CODE_REPO + "/tree/" + COMMIT},
        "runs": runs,
        "lineage": [],
        "supersedes": None,
        "status": "submitted",
    }

    record_id = put_json(body)
    record = {"id": record_id}
    record.update(body)
    with open(RECORD, "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    print("manifest  %s" % manifest_hash)
    print("harness   %s" % harness_hash)
    print("base      %s  (locator)" % base_hash)
    print("edit      %s  (locator)" % edited_hash)
    print("record    %s" % record_id)
    print("runs      %d" % len(runs))


if __name__ == "__main__":
    main()
