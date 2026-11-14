#!/usr/bin/env python3
"""Run both MIR-1 implementations on the same input and require the same answer.

This is the test a specification has to pass: two programs, written from the
text and sharing no code, must agree on which records conform. It is not a test
of the authors; it is a test of whether the text is complete enough to be
implemented twice.

    python3 crosscheck.py [--remote]

Compares, byte for byte, the --json report and the exit code of validate.py and
impl2/mir-validate for:
  * the records and examples in this repository,
  * every mutation records/selfcheck.py defines, applied to the real record and
    to the positive fixture,
  * three damaged stores (bytes changed, locator broken, entry removed),
  * the canonical-form vectors in impl2/testdata,
  * every pinned Unicode and formatting table, regenerated from the reference
    implementation and compared byte for byte with the committed copy.

--remote additionally checks the locator resolution path against the hosts,
which costs one HEAD request per locator. --fuzz N adds N random documents, half
arbitrary JSON shapes (canonical form) and half mutations of a conforming record
(the other ten checks), and prints which branches the corpus reached.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "impl2")
GO_BINARY = os.path.join(ROOT, "mir-validate")
STORE = os.path.join(HERE, "records", "artifacts")
CORPUS = [
    os.path.join(HERE, "records", "MIR-R1.json"),
    os.path.join(HERE, "examples", "conforming.json"),
    os.path.join(HERE, "examples", "terse-run.json"),
    os.path.join(HERE, "examples", "parent.json"),
    os.path.join(HERE, "records", "manifest.json"),
    os.path.join(HERE, "records", "harness.json"),
]


def build():
    if shutil.which("go") is None:
        print("go is not installed; the second implementation cannot be built")
        return False
    proc = subprocess.run(["go", "build", "-o", GO_BINARY, "."], cwd=ROOT)
    return proc.returncode == 0


def compare(label, record, extra, cwd=None, sink=None):
    python_command = [sys.executable, os.path.join(HERE, "validate.py")]
    python = subprocess.run(python_command + [record] + extra, capture_output=True,
                            text=True, cwd=cwd)
    golang = subprocess.run([GO_BINARY, record] + extra, capture_output=True,
                            text=True, cwd=cwd)
    if sink is not None:
        sink.append(json.loads(python.stdout))
    if python.stdout != golang.stdout or python.returncode != golang.returncode:
        print("%-58s MISMATCH" % label)
        if python.returncode != golang.returncode:
            print("  exit: python %d, go %d" % (python.returncode, golang.returncode))
        for line in unified(python.stdout, golang.stdout):
            print("  " + line)
        return False
    print("%-58s identical (exit %d)" % (label, python.returncode))
    return True


def unified(left, right):
    import difflib
    return list(difflib.unified_diff(left.splitlines(), right.splitlines(),
                                     "python", "go", lineterm=""))[:20]


def mutations():
    sys.path.insert(0, os.path.join(HERE, "records"))
    import selfcheck
    with open(os.path.join(HERE, "records", "MIR-R1.json"), encoding="utf-8") as handle:
        original = json.load(handle)
    cases = []
    for label, mutate, _expected, reid in selfcheck.CASES:
        record = json.loads(json.dumps(original))
        mutate(record)
        if reid:
            selfcheck.reidentify(record)
        cases.append((label, record))
    return cases


def positive_mutations():
    """The same, on the only record that passes every check.

    A mutation of a failing record can agree because both implementations fail
    for some unrelated reason. The positive fixture starts from eleven passes,
    so a rule present in one implementation and absent from the other shows up
    as a disagreement about exactly one check.
    """
    sys.path.insert(0, os.path.join(HERE, "records"))
    import selfcheck
    with open(os.path.join(HERE, "examples", "conforming.json"), encoding="utf-8") as handle:
        original = json.load(handle)
    cases = []
    for label, mutate, _expected in selfcheck.POSITIVE_CASES:
        record = json.loads(json.dumps(original))
        mutate(record)
        selfcheck.reidentify(record)
        cases.append((label, record))
    return cases


def damaged_stores():
    """Stores whose bytes no longer match their names.

    The record is the same in every case; only the store is damaged. A
    content-addressed store that is checked by filename alone would pass all of
    these, so the cases exist to keep both implementations honest about the
    bytes.
    """
    base = os.path.join(HERE, "records", "artifacts")
    entries = sorted(os.listdir(base))
    payloads = [n for n in entries if not n.endswith(".locator.json")]
    locators = [n for n in entries if n.endswith(".locator.json")]
    cases = []
    for label, victim, damage in (
        ("store: bytes changed under a digest", payloads[0], b"X"),
        ("store: locator is not valid JSON", locators[0], b"X"),
        ("store: entry removed", payloads[1], None),
    ):
        temp = tempfile.mkdtemp(prefix="mir-store-")
        store = os.path.join(temp, "artifacts")
        shutil.copytree(base, store)
        target = os.path.join(store, victim)
        if damage is None:
            os.remove(target)
        else:
            with open(target, "ab") as handle:
                handle.write(damage)
        cases.append((label, store, temp))
    return cases


def reference_vectors():
    """Regenerate every pinned table and require the committed copy to match.

    The Go tests assert that impl2 matches these vectors, so a stale vector is
    invisible to them: both sides agree with each other and disagree with the
    reference. Regenerating into a temporary directory and comparing bytes makes
    a Python or Unicode upgrade a failure here rather than a silent drift.
    """
    source = os.path.join(HERE, "impl2", "testdata")
    temp = tempfile.mkdtemp(prefix="mir-vectors-")
    ok = True
    try:
        work = os.path.join(temp, "testdata")
        os.makedirs(work)
        generators = sorted(n for n in os.listdir(source) if n.startswith("make_"))
        for name in generators:
            shutil.copyfile(os.path.join(source, name), os.path.join(work, name))
        for name in generators:
            proc = subprocess.run([sys.executable, os.path.join(work, name)],
                                  capture_output=True, text=True,
                                  env=dict(os.environ, PYTHONPATH=HERE))
            if proc.returncode != 0:
                print("%-58s FAILED" % ("regenerate " + name))
                print("  " + proc.stderr.strip().splitlines()[-1][:200])
                ok = False
        produced = set()
        for root, _dirs, files in os.walk(temp):
            for name in sorted(files):
                if name.startswith("make_"):
                    continue
                relative = os.path.relpath(os.path.join(root, name), temp)
                produced.add(relative)
                committed = os.path.join(HERE, "impl2", relative)
                label = "pin: %s" % relative
                if not os.path.isfile(committed):
                    print("%-58s MISSING" % label)
                    ok = False
                elif read_bytes(os.path.join(root, name)) != read_bytes(committed):
                    print("%-58s STALE (regenerate after the upgrade)" % label)
                    ok = False
                else:
                    print("%-58s current" % label)
        for name in sorted(os.listdir(source)):
            if name.endswith("_vectors.json") and os.path.join("testdata", name) not in produced:
                print("%-58s ORPHAN (no generator produces it)" % ("pin: testdata/" + name))
                ok = False
    finally:
        shutil.rmtree(temp, ignore_errors=True)
    return ok


def read_bytes(path):
    with open(path, "rb") as handle:
        return handle.read()


def coverage(reports):
    """Which branches the random documents actually reached.

    Agreement between two implementations on a corpus that only ever produces
    one message per check is agreement about nothing. The record-shaped half of
    the corpus exists to reach the branches an arbitrary JSON shape cannot.
    """
    tally = {}
    for report in reports:
        for check in report.get("checks", []):
            entry = tally.setdefault(check["id"], {"pass": 0, "fail": 0, "details": set()})
            entry["pass" if check["ok"] else "fail"] += 1
            entry["details"].add(check["detail"])
    print("\ncheck coverage over %d documents" % len(reports))
    print("  %-6s %6s %6s %9s" % ("check", "pass", "fail", "messages"))
    for cid in sorted(tally):
        entry = tally[cid]
        print("  %-6s %6d %6d %9d" % (cid, entry["pass"], entry["fail"], len(entry["details"])))
    quiet = [cid for cid in sorted(tally) if not tally[cid]["fail"]]
    if quiet:
        print("  never seen to fail: %s" % ", ".join(quiet))


def main(argv):
    remote = "--remote" in argv
    fuzz_count = 0
    if "--fuzz" in argv:
        fuzz_count = int(argv[argv.index("--fuzz") + 1])
    if not build():
        return 2

    ok = True
    print("records and examples")
    for path in CORPUS:
        ok = compare(os.path.relpath(path, HERE), path, ["--json"]) and ok

    print("\nmutations of the real record")
    for label, record in mutations():
        handle, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(record, stream)
        try:
            ok = compare(label, path, ["--artifacts", STORE, "--json"]) and ok
        finally:
            os.unlink(path)

    print("\nmutations of the positive fixture")
    for label, record in positive_mutations():
        handle, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(record, stream)
        try:
            ok = compare(label, path, ["--json"], cwd=HERE) and ok
        finally:
            os.unlink(path)

    print("\ndamaged stores")
    damaged = damaged_stores()
    try:
        for label, store, _temp in damaged:
            ok = compare(label, os.path.join(HERE, "records", "MIR-R1.json"),
                         ["--artifacts", store, "--json"]) and ok
    finally:
        for _label, _store, temp in damaged:
            shutil.rmtree(temp, ignore_errors=True)

    print("\nfalsifier execution")
    ok = compare("records/MIR-R1.json --execute-falsifier",
                 os.path.join(HERE, "records", "MIR-R1.json"),
                 ["--execute-falsifier", "--json"], cwd=HERE) and ok

    if remote:
        print("\nlocators, checked against the hosts")
        ok = compare("records/MIR-R1.json --verify-remote",
                     os.path.join(HERE, "records", "MIR-R1.json"),
                     ["--verify-remote", "--json"]) and ok

    print("\ncanonical form vectors")
    vectors = os.path.join(HERE, "impl2", "testdata", "canonical_vectors.json")
    with open(vectors, encoding="utf-8") as handle:
        loaded = json.load(handle)
    sys.path.insert(0, HERE)
    from validate import canonical_bytes
    bad = 0
    for item in loaded:
        actual = canonical_bytes(json.loads(item["input"])).decode("utf-8")
        if actual != item["canonical"]:
            bad += 1
            print("  %s: %r != %r" % (item["name"], actual, item["canonical"]))
    print("%-58s %s" % ("%d vectors" % len(loaded), "ok" if not bad else "MISMATCH"))
    ok = ok and not bad

    print("\nreference pins")
    ok = reference_vectors() and ok

    go_test = subprocess.run(["go", "test", "./..."], cwd=ROOT,
                             capture_output=True, text=True)
    print("%-58s %s" % ("go test ./...", "ok" if go_test.returncode == 0 else "FAILED"))
    if go_test.returncode != 0:
        print(go_test.stdout, go_test.stderr)
    ok = ok and go_test.returncode == 0

    sync_path = os.path.join(HERE, "space", "sync.py")
    if os.path.isfile(sync_path):
        sync = subprocess.run([sys.executable, sync_path, "--check"],
                              capture_output=True, text=True)
        print("%-58s %s" % ("space copies", "in sync" if sync.returncode == 0 else "DRIFTED"))
        if sync.returncode != 0:
            print(sync.stdout)
        ok = ok and sync.returncode == 0
    else:
        print("%-58s %s" % ("space copies", "skipped (not in this package)"))

    if fuzz_count:
        print("\nrandom documents (%d)" % fuzz_count)
        sys.path.insert(0, HERE)
        from validate import canonical_bytes
        from fuzzgen import prepare_record, random_document, reidentify
        reports = []
        bad = 0
        shapes = fuzz_count // 2
        for index in range(fuzz_count):
            if index < shapes:
                label = "shape %d" % index
                document = reidentify(random_document(index), canonical_bytes)
            else:
                names, document = prepare_record(index, canonical_bytes)
                label = "record %d (%s)" % (index, ", ".join(names))
            handle, path = tempfile.mkstemp(suffix=".json")
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(document, stream, ensure_ascii=False)
            try:
                if not compare(label, path, ["--artifacts", STORE, "--json"],
                               sink=reports):
                    bad += 1
            finally:
                os.unlink(path)
        ok = ok and not bad
        coverage(reports)

    print("\nRESULT: %s" % ("both implementations agree" if ok else "DISAGREEMENT"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
