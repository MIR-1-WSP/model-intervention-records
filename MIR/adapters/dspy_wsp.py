#!/usr/bin/env python3
"""Turn a dspy-wsp run directory into a MIR-1.1 record with a Weight Patch.

The tool this adapter targets edits a model's weights without gradients and
publishes two artifacts per run: a `manifest.json` and an `edit.npz` holding the
edit as tensors. This script reads those, converts the edit to a Weight Patch,
fills the record from a run description, and captures `cost` and `wall_time_s`
at the point where the run is written rather than leaving them for an author to
remember.

    python3 adapters/dspy_wsp.py --run DIR --out record.json [--store DIR]
    python3 adapters/dspy_wsp.py --selftest

Input contract (all paths relative to --run):

    manifest.json   the tool's manifest; hashed as the harness, and copied
    edit.npz        tensor name -> float32/float64 array of the edit
    run.json        the record fields the tool does not carry:
                      base            {"file": "..."} or {"hash": ..., "location": ..., "license": ...}
                      manifest        {"file": "..."} registry parameters, optional
                      claim, invariants, falsifier, claimant, status
                      lineage         optional, default []
                      runs            list of {operator, funding_source, started_at,
                                      n_units, samples_per_unit, cost, wall_time_s, results}

`edit.npz` is read with the standard library alone: an npz file is a zip of npy
files, and both formats are small enough to parse directly. No numpy is needed
to run the adapter; `testdata/make_npz.py` uses numpy once, to cut the fixture.

Two conversions are explicit because the tool's own semantics decide them:

    --mode add   the arrays are deltas (default, and what the tool publishes)
    --mode set   the arrays are absolute values for the tensors they name

An additive edit can be inverted algebraically by negating the deltas, which is
not bit-identical; when the base is a `wpp-array-0.1` container the adapter
captures the prior values instead and emits an exact inverse, so P-05 executes.
"""

from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import io
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from validate import (  # noqa: E402
    PATCH_CONTEXT, Store, canonical_bytes, parse_record, run_checks,
)
import patchcheck  # noqa: E402
from patchcheck import parse_container  # noqa: E402

DTYPES = {
    "<f4": ("f", 4),
    "<f8": ("d", 8),
    "|f4": ("f", 4),
}


# ------------------------------------------------------------------- npy/npz

def read_npy(payload):
    """Parse one .npy file. Returns (shape, values) with values as floats."""
    if not payload.startswith(b"\x93NUMPY"):
        raise ValueError("not an npy file")
    major = payload[6]
    if major == 1:
        header_len = struct.unpack("<H", payload[8:10])[0]
        start = 10
    elif major in (2, 3):
        header_len = struct.unpack("<I", payload[8:12])[0]
        start = 12
    else:
        raise ValueError("unsupported npy version %d" % major)
    header = payload[start:start + header_len].decode("latin-1")
    body = payload[start + header_len:]
    try:
        description = ast.literal_eval(header.strip())
    except (ValueError, SyntaxError):
        raise ValueError("the npy header is not a Python literal")
    if not isinstance(description, dict):
        raise ValueError("the npy header is not a dict")
    if description.get("fortran_order"):
        raise ValueError("a Fortran-ordered array is not supported")
    descriptor = description.get("descr")
    shape = tuple(description.get("shape") or ())
    if descriptor not in DTYPES:
        raise ValueError("dtype %r is not float32 or float64" % descriptor)
    code, width = DTYPES[descriptor]
    count = 1
    for dimension in shape:
        count *= dimension
    if len(body) < count * width:
        raise ValueError("array data is shorter than its shape")
    values = struct.unpack("<%d%s" % (count, code), body[:count * width])
    return shape, list(values)


def read_npz(path):
    """Return {tensor name: (shape, values)} for the arrays in an npz file."""
    out = {}
    with zipfile.ZipFile(path) as archive:
        for name in sorted(archive.namelist()):
            if not name.endswith(".npy"):
                continue
            key = os.path.basename(name)[:-4]
            shape, values = read_npy(archive.read(name))
            out[key] = (shape, values)
    if not out:
        raise ValueError("the npz file carries no arrays")
    return out


def write_npy(values, shape):
    """Write one .npy payload. Used by --selftest, kept here so it is tested."""
    header = "{'descr': '<f4', 'fortran_order': False, 'shape': %r, }" % (tuple(shape),)
    header = header.encode("latin-1")
    padding = 64 - (10 + len(header) + 1) % 64
    header = header + b" " * padding + b"\n"
    payload = b"\x93NUMPY\x01\x00" + struct.pack("<H", len(header)) + header
    return payload + struct.pack("<%df" % len(values), *values)


# -------------------------------------------------------------------- patch

def build_patch(arrays, mode, base_tensors, dependencies):
    """Convert the edit arrays to a conforming Weight Patch."""
    ops = []
    prior = []
    changed = 0
    total = 0
    for name in sorted(arrays):
        shape, values = arrays[name]
        total += len(values)
        if mode == "add":
            indices = []
            for index, value in enumerate(values):
                try:
                    narrowed = struct.unpack("<f", struct.pack("<f", value))[0]
                except (OverflowError, struct.error):
                    raise ValueError("tensor %r carries a value outside the binary32 range"
                                     % name)
                if narrowed != 0.0:
                    indices.append(index)
            numbers = [values[index] for index in indices]
            if not indices:
                continue
            op = {"op": "add", "tensor": name, "indices": indices, "deltas": numbers}
        else:
            indices = list(range(len(values)))
            op = {"op": "set", "tensor": name, "indices": indices,
                  "values": list(values)}
        ops.append(op)
        changed += len(indices)
        tensor = base_tensors.get(name) if base_tensors else None
        if tensor is not None:
            data = tensor[1]
            if indices and indices[-1] >= len(data) // 4:
                raise ValueError("tensor %r is larger than its base" % name)
            prior.append({
                "tensor": name,
                "indices": indices,
                "values": [patchcheck_float(data, index) for index in indices],
            })
    if not ops:
        raise ValueError("the edit changes no weights")
    patch = {
        "wpp_version": "0.1",
        "base": {"checkpoint_hash": None},
        "dependencies": list(dependencies),
        "edit": {
            "type": "sparse_delta",
            "ops": ops,
            "num_changed": changed,
            "sparsity": round(changed / total, 6) if total else 0.0,
        },
    }
    if prior and len(prior) == len(ops):
        # Both modes can be inverted exactly when the base was readable; a set
        # edit has no algebraic inverse at all, because it discards the prior.
        patch["inverse"] = {"kind": "exact", "prior": prior}
    elif mode == "add":
        patch["inverse"] = {"kind": "algebraic", "ops": [
                {"op": "add", "tensor": op["tensor"], "indices": op["indices"],
             "deltas": [-value for value in op["deltas"]]}
            for op in ops
        ]}
    return patch


def patchcheck_float(data, index):
    return struct.unpack_from("<f", data, 4 * index)[0]


# ------------------------------------------------------------------- record

def sha256_hex(payload):
    return hashlib.sha256(payload).hexdigest()


def put(store, payload):
    digest = sha256_hex(payload)
    os.makedirs(store, exist_ok=True)
    with open(os.path.join(store, digest), "wb") as handle:
        handle.write(payload)
    return "sha256:" + digest


def resolve(value, store):
    """Turn {"file": path} into a hash, keeping the bytes in the store."""
    if isinstance(value, dict) and "file" in value:
        path = value["file"]
        with open(path, "rb") as handle:
            payload = handle.read()
        digest = put(store, payload)
        return digest
    if isinstance(value, dict) and isinstance(value.get("hash"), str):
        return value["hash"]
    raise ValueError("an artifact must be {\"file\": ...} or {\"hash\": ...}")


def build_record(spec, run_dir, store, args):
    base = spec.get("base")
    if not isinstance(base, dict):
        raise ValueError("run.json needs a base artifact")
    record = {
        "mir_version": "1",
        "manifest_hash": resolve(spec.get("manifest"), store),
        "base": {
            "hash": resolve(base, store),
            "location": base.get("location", "dspy-wsp/base"),
            "license": base.get("license", "not stated"),
        },
        "intervention": {"type": "weights"},
        "claimant": spec["claimant"],
        "claim": spec["claim"],
        "falsifier": spec["falsifier"],
        "invariants": spec["invariants"],
        "harness": {
            "hash": resolve(spec.get("harness") or {"file": os.path.join(run_dir, "manifest.json")},
                            store),
            "location": spec.get("harness_location", "dspy-wsp/manifest.json"),
        },
        "lineage": list(spec.get("lineage") or []),
        "supersedes": spec.get("supersedes"),
        "status": spec.get("status", "submitted"),
        "runs": [],
    }
    return record


def build_runs(spec, record, patch_hash, args):
    runs = spec.get("runs")
    if not isinstance(runs, list) or not runs:
        raise ValueError("run.json needs at least one run")
    out = []
    for index, run in enumerate(runs):
        if not isinstance(run, dict):
            raise ValueError("runs[%d] is not an object" % index)
        cost = args.cost if args.cost is not None else run.get("cost")
        wall = args.wall_time if args.wall_time is not None else run.get("wall_time_s")
        if cost is None or wall is None:
            if not args.allow_undisclosed:
                raise ValueError(
                    "runs[%d] does not state cost and wall time; pass --cost/--wall-time, "
                    "or --allow-undisclosed to write a record that fails C-07" % index)
            cost = None if cost is None else cost
            wall = None if wall is None else wall
        result = dict(run.get("results") or {})
        result["n_units"] = run["n_units"]
        result["samples_per_unit"] = run["samples_per_unit"]
        out.append({
            "operator": run["operator"],
            "funding_source": run["funding_source"],
            "cost": cost,
            "wall_time_s": wall,
            "started_at": run["started_at"],
            "harness_hash": record["harness"]["hash"],
            "base_hash": record["base"]["hash"],
            "intervention_hash": patch_hash,
            "result": result,
        })
    return out


# --------------------------------------------------------------------- main

def convert(run_dir, args):
    store = args.store or os.path.join(os.path.dirname(os.path.abspath(args.out)), "artifacts")
    with open(os.path.join(run_dir, "run.json"), encoding="utf-8") as handle:
        spec = json.load(handle)
    arrays = read_npz(os.path.join(run_dir, "edit.npz"))

    base_tensors = None
    base = spec.get("base") or {}
    if isinstance(base, dict) and base.get("file"):
        try:
            with open(base["file"], "rb") as handle:
                base_tensors, _why = parse_container(handle.read(), PATCH_CONTEXT)
        except OSError:
            base_tensors = None

    patch = build_patch(arrays, args.mode, base_tensors,
                        spec.get("patch_dependencies") or [])
    patch["base"]["checkpoint_hash"] = resolve(base, store)
    patch["base"]["model_id"] = spec.get("model_id", base.get("model_id", "unknown"))
    patch["base"]["format"] = base.get(
        "format", "wpp-array-0.1" if base_tensors else "unspecified")
    # The date comes from the run, never from the clock: a converter that dates
    # a record by when it was converted makes two conversions of one run differ.
    created = args.created or spec.get("created")
    if not created:
        runs = spec.get("runs") or [{}]
        started = runs[0].get("started_at") if isinstance(runs[0], dict) else None
        created = started[:10] if isinstance(started, str) and len(started) >= 10 else "unspecified"
    patch["metadata"] = {
        "title": spec.get("title", "dspy-wsp edit"),
        "generator": "mir adapters/dspy_wsp.py",
        "source": os.path.basename(run_dir.rstrip(os.sep)),
        "created": created,
    }

    record = build_record(spec, run_dir, store, args)
    # P-04 requires the payload to carry the same declaration the record does.
    patch["invariants"] = record["invariants"]
    patch["falsifier"] = record["falsifier"]
    patch_id = sha256_hex(canonical_bytes(
        {key: value for key, value in patch.items() if key != "id"}))
    patch["id"] = "wpp:sha256:" + patch_id
    patch_hash = put(store, canonical_bytes(patch))
    record["intervention"]["payload_hash"] = patch_hash
    record["runs"] = build_runs(spec, record, patch_hash, args)
    body = {key: value for key, value in record.items() if key != "id"}
    record["id"] = "sha256:" + sha256_hex(canonical_bytes(body))

    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
    return record, store


def verdict(record, store_dir):
    store = Store([store_dir, ROOT, os.path.join(ROOT, "artifacts")])
    return run_checks(record, store)


def selftest():
    """Convert a real npz, then hold the record to both implementations."""
    temp = tempfile.mkdtemp(prefix="mir-dspy-")
    checks = []
    try:
        run_dir = os.path.join(temp, "run")
        os.makedirs(run_dir)
        shutil.copyfile(os.path.join(HERE, "testdata", "edit.npz"),
                        os.path.join(run_dir, "edit.npz"))
        with open(os.path.join(run_dir, "manifest.json"), "w", encoding="utf-8") as handle:
            handle.write('{"tool": "dspy-wsp", "version": "fixture"}\n')

        base = {
            "wpp_array_version": "0.1",
            "tensors": {"w": {
                "shape": [2, 3],
                "dtype": "float32",
                "data_b64": base64.b64encode(
                    struct.pack("<6f", 1.0, 2.0, 3.0, 4.0, 5.0, 6.0)).decode("ascii"),
            }},
        }
        base_path = os.path.join(run_dir, "base.wpp-array.json")
        with open(base_path, "w", encoding="utf-8") as handle:
            handle.write(canonical_bytes(base).decode("utf-8"))

        registry = {
            "mir_version": "1",
            "name": "adapters-selftest",
            "parameters": {
                "challenge_window_days": 30,
                "bond_size": 1000,
                "min_independent_replications": 2,
                "benchmark_rotation_days": 180,
            },
        }
        manifest_path = os.path.join(run_dir, "registry.json")
        with open(manifest_path, "w", encoding="utf-8") as handle:
            handle.write(canonical_bytes(registry).decode("utf-8"))

        spec = {
            "base": {"file": base_path, "location": "selftest/base", "license": "example-only"},
            "manifest": {"file": manifest_path},
            "claimant": {"operator": "operator-a", "funding_source": "example-fund-a"},
            "claim": {"behavior": "mean_tokens", "distribution": "instruct-set",
                      "direction": "decrease", "threshold": 0.9,
                      "scoring_metrics": ["mean_tokens"]},
            "falsifier": {"command": "python3 -c \"print(True)\"", "returns": "boolean"},
            "invariants": [
                {"property": "math_accuracy", "measurement": "math500/exact",
                 "metric": "math_accuracy", "direction": "floor", "bound": 0.5},
            ],
            "status": "replicated",
            "runs": [
                {"operator": "operator-b", "funding_source": "example-fund-b",
                 "started_at": "2026-11-18T00:00:00Z", "n_units": 500,
                 "samples_per_unit": 4, "cost": 4.0, "wall_time_s": 14400.0,
                 "results": {"mean_tokens": 0.62, "math_accuracy": 0.78}},
                {"operator": "operator-c", "funding_source": "example-fund-c",
                 "started_at": "2026-11-19T00:00:00Z", "n_units": 500,
                 "samples_per_unit": 4, "cost": 3.0, "wall_time_s": 12600.0,
                 "results": {"mean_tokens": 0.63, "math_accuracy": 0.79}},
            ],
        }
        spec_path = os.path.join(run_dir, "run.json")
        with open(spec_path, "w", encoding="utf-8") as handle:
            json.dump(spec, handle)

        args = argparse.Namespace(store=None, out=os.path.join(temp, "record.json"),
                                  mode="add", cost=None, wall_time=None,
                                  allow_undisclosed=False, created="2026-11-18")
        record, store = convert(run_dir, args)
        with open(args.out, "rb") as handle:
            reloaded = parse_record(handle.read())
        results = verdict(reloaded, store)
        failed = [cid for cid, (ok, _detail) in results if not ok]
        block = patchcheck.evaluate(reloaded, Store([store]), PATCH_CONTEXT)
        states = {item["id"]: item["result"] for item in (block or {}).get("checks", [])}
        with open(os.path.join(store, reloaded["intervention"]["payload_hash"][7:]), "rb") as handle:
            stored = json.loads(handle.read())

        checks.append(("the committed numpy fixture reads as two deltas",
                       read_npz(os.path.join(HERE, "testdata", "edit.npz"))
                       == {"w": ((2, 3), [0.5, 0.0, 0.0, 0.0, -1.0, 0.0])}))
        checks.append(("the adapter writes a record that parses", reloaded.get("id") is not None))
        checks.append(("every MIR-1 check passes", not failed))
        checks.append(("every MIR-1.1 check passes",
                       len(states) == 5 and all(state == "pass" for state in states.values())))
        checks.append(("the patch declares an exact inverse",
                       stored.get("inverse", {}).get("kind") == "exact"))
        checks.append(("num_changed counts the non-zero deltas",
                       stored["edit"]["num_changed"] == 2))

        # The two implementations must agree on the record the adapter wrote.
        binary = os.path.join(ROOT, "impl2", "mir-validate")
        if not os.path.isfile(binary):
            subprocess.run(["go", "build", "-o", "mir-validate", "."],
                           cwd=os.path.join(ROOT, "impl2"), check=True)
        outputs = []
        for command in ([sys.executable, os.path.join(ROOT, "validate.py")],
                        [os.path.join(ROOT, "impl2", "mir-validate")]):
            proc = subprocess.run(command + [args.out, "--artifacts", store, "--json"],
                                  capture_output=True, text=True)
            outputs.append((proc.stdout, proc.returncode))
        checks.append(("both implementations agree on the generated record",
                       outputs[0] == outputs[1]))

        # The other conversion is documented, so it is exercised: absolute values
        # instead of deltas, with the prior values captured the same way.
        set_args = argparse.Namespace(store=None, out=os.path.join(temp, "set-record.json"),
                                      mode="set", cost=None, wall_time=None,
                                      allow_undisclosed=False, created=None)
        set_record, set_store = convert(run_dir, set_args)
        with open(set_args.out, "rb") as handle:
            set_reloaded = parse_record(handle.read())
        set_block = patchcheck.evaluate(set_reloaded, Store([set_store]), PATCH_CONTEXT)
        set_states = {item["id"]: item["result"] for item in (set_block or {}).get("checks", [])}
        with open(os.path.join(set_store, set_reloaded["intervention"]["payload_hash"][7:]),
                  "rb") as handle:
            set_stored = json.loads(handle.read())
        checks.append(("a set edit converts and passes every check",
                       len(set_states) == 5 and all(state == "pass" for state in set_states.values())
                       and set_stored["edit"]["num_changed"] == 6))

        # A run that discloses no cost is refused rather than written silently.
        with open(spec_path, encoding="utf-8") as handle:
            unpriced = json.load(handle)
        unpriced["runs"][0]["cost"] = None
        with open(spec_path, "w", encoding="utf-8") as handle:
            json.dump(unpriced, handle)
        try:
            convert(run_dir, argparse.Namespace(
                store=None, out=os.path.join(temp, "unpriced.json"), mode="add",
                cost=None, wall_time=None, allow_undisclosed=False, created="2026-11-18"))
            refused = False
        except ValueError:
            refused = True
        checks.append(("a run with no disclosed cost is refused", refused))

        ok = all(result for _label, result in checks)
        for label, result in checks:
            print("%-56s %s" % (label, "ok" if result else "FAILED"))
        if not ok and failed:
            print("  failed checks: %s" % ", ".join(failed))
        print()
        print("%d checks, %s" % (len(checks), "all pass" if ok else "FAILED"))
        return 0 if ok else 1
    finally:
        shutil.rmtree(temp, ignore_errors=True)


def main(argv):
    parser = argparse.ArgumentParser(
        description="Convert a dspy-wsp run into a MIR-1.1 record and Weight Patch.")
    parser.add_argument("--run", help="directory holding manifest.json, edit.npz, run.json")
    parser.add_argument("--out", help="where to write the record")
    parser.add_argument("--store", help="artifact store (default: artifacts beside --out)")
    parser.add_argument("--mode", choices=("add", "set"), default="add",
                        help="add: the npz holds deltas (default); set: absolute values")
    parser.add_argument("--cost", type=float, help="override the cost on every run")
    parser.add_argument("--wall-time", type=float, dest="wall_time",
                        help="override wall_time_s on every run")
    parser.add_argument("--allow-undisclosed", action="store_true",
                        help="write a record whose runs state no cost (it will fail C-07)")
    parser.add_argument("--created", default=None,
                        help="patch metadata date (default: the run's started_at)")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest()
    if not args.run or not args.out:
        parser.error("--run and --out are required unless --selftest is given")
    record, store = convert(args.run, args)
    results = verdict(record, store)
    failed = [cid for cid, (ok, _detail) in results if not ok]
    print("record       %s" % args.out)
    print("patch        %s" % record["intervention"]["payload_hash"])
    if failed:
        print("RESULT: FAIL (%s)" % ", ".join(failed))
        return 1
    print("RESULT: PASS (11 of 11)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
