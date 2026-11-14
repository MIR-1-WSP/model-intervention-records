#!/usr/bin/env python3
"""Build a MIR-1 record from a run description.

A run description is the record's own fields, except that an artifact may be
given as {"file": "path"} where a hash is expected. The adapter hashes the file,
copies the bytes into the store under the digest, and fills the hash. It then
computes the record id and runs the suite, so the record is written with its
verdict attached rather than discovered to fail later.

    python3 adapter.py --spec run.json --out record.json [--store DIR] [--strict]
    python3 adapter.py --selftest

The description is checked by the suite, not by this script. The adapter does
not restate the requirements: a second copy of the rules is a second place for
them to drift, which is the defect the repository has spent the most time on.

Three artifacts accept a file: base, intervention, harness. Everything else must
already be a hash, because the adapter cannot know which file a run's result
refers to.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from validate import (  # noqa: E402
    SUITE_VERSION, Store, canonical_bytes, run_checks,
)

ARTIFACTS = (("base", "hash"), ("intervention", "payload_hash"), ("harness", "hash"))


def absorb(container, key, store_dir):
    """Replace {"file": path} with the digest of those bytes, and keep the bytes."""
    if not isinstance(container, dict) or "file" not in container:
        return
    path = container.pop("file")
    with open(path, "rb") as handle:
        data = handle.read()
    digest = hashlib.sha256(data).hexdigest()
    os.makedirs(store_dir, exist_ok=True)
    with open(os.path.join(store_dir, digest), "wb") as handle:
        handle.write(data)
    container[key] = "sha256:" + digest


def build(spec, store_dir):
    record = json.loads(json.dumps(spec))
    record.setdefault("mir_version", "1")
    record.setdefault("lineage", [])
    record.setdefault("supersedes", None)
    record.setdefault("status", "draft")
    for name, key in ARTIFACTS:
        absorb(record.get(name), key, store_dir)
    body = {k: v for k, v in record.items() if k != "id"}
    record["id"] = "sha256:" + hashlib.sha256(canonical_bytes(body)).hexdigest()
    return record


def check(record, store_dir):
    store = Store([store_dir, HERE, os.path.join(HERE, "artifacts")])
    return run_checks(record, store)


def main(argv):
    parser = argparse.ArgumentParser(description="Build a MIR-1 record from a run description.")
    parser.add_argument("--spec", help="the run description, as JSON")
    parser.add_argument("--out", help="where to write the record")
    parser.add_argument("--store", help="artifact store (default: artifacts beside --out)")
    parser.add_argument("--strict", action="store_true",
                        help="do not write a record that does not conform")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest()
    if not args.spec or not args.out:
        parser.error("--spec and --out are required unless --selftest is given")

    with open(args.spec, "r", encoding="utf-8") as handle:
        spec = json.load(handle)
    store_dir = args.store or os.path.join(os.path.dirname(os.path.abspath(args.out)), "artifacts")
    record = build(spec, store_dir)
    results = check(record, store_dir)
    failed = [cid for cid, (ok, _) in results if not ok]

    if failed and args.strict:
        print("not written: %d check(s) fail: %s" % (len(failed), ", ".join(failed)))
        for cid, (ok, detail) in results:
            if not ok:
                print("%s FAIL  %s" % (cid, detail))
        return 1

    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, ensure_ascii=False)
        handle.write("\n")

    print("wrote %s" % args.out)
    print("id    %s" % record["id"])
    print("suite %s" % SUITE_VERSION)
    for cid, (ok, detail) in results:
        print("%s %s  %s" % (cid, "PASS" if ok else "FAIL", detail))
    return 0 if not failed else 1


def selftest():
    """Build a record from a file, then prove the adapter refused to restate the rules."""
    failures = 0

    def check_case(label, condition, detail=""):
        nonlocal failures
        if condition:
            print("%-52s ok" % label)
        else:
            failures += 1
            print("%-52s FAILED %s" % (label, detail))

    temp = tempfile.mkdtemp(prefix="mir-adapter-")
    payload = os.path.join(temp, "payload.bin")
    with open(payload, "wb") as handle:
        handle.write(b"an intervention\n")
    store = os.path.join(temp, "artifacts")

    spec = {
        "manifest_hash": "sha256:" + "00" * 32,
        "base": {"file": payload, "location": "test", "license": "test"},
        "intervention": {"type": "weights", "file": payload},
        "claimant": {"operator": "operator-a", "funding_source": "fund-a"},
        "claim": {"behavior": "acc", "distribution": "d", "direction": "increase",
                  "threshold": 0.5, "scoring_metrics": ["acc"]},
        "falsifier": {"command": "true", "returns": "boolean"},
        "invariants": [{"property": "other", "measurement": "m", "metric": "other",
                        "direction": "floor", "bound": 0.5}],
        "harness": {"file": payload, "location": "test"},
        "runs": [{"operator": "operator-a", "funding_source": "fund-a", "cost": 1.0,
                  "wall_time_s": 10.0, "started_at": "2026-01-01",
                  "harness_hash": "sha256:" + "00" * 32,
                  "base_hash": "sha256:" + "00" * 32, "intervention_hash": None,
                  "result": {"n_units": 1, "samples_per_unit": 1, "acc": 0.9}}],
        "lineage": [],
        "status": "draft",
    }
    record = build(spec, store)
    check_case("a file becomes a hash in the store",
               record["base"]["hash"].startswith("sha256:")
               and os.path.isfile(os.path.join(store, record["base"]["hash"][7:])))
    body = {k: v for k, v in record.items() if k != "id"}
    check_case("the id is the content address of the body",
               record["id"] == "sha256:" + hashlib.sha256(canonical_bytes(body)).hexdigest())
    results = dict((cid, ok) for cid, (ok, _) in check(record, store))
    check_case("C-01 accepts the record the adapter built", results.get("C-01") is True)
    check_case("the adapter does not invent conformance",
               results.get("C-03") is False, "an unresolved manifest should fail C-03")

    os.remove(payload)
    broken = json.loads(json.dumps(spec))
    try:
        build(broken, store)
        raised = False
    except OSError:
        raised = True
    check_case("a missing artifact file is an error, not a silent pass", raised)

    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
