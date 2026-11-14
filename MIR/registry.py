#!/usr/bin/env python3
"""Export, import, and verify a MIR-1 registry.

A registry is a directory holding a manifest, a records directory, and the
artifact store those records resolve against. MIR-1-09 requires that a registry
be exportable in full, by one command, in a format a third party can re-import
and verify. This is that command.

    python3 registry.py export REGISTRY OUT.tar.gz
    python3 registry.py import ARCHIVE DEST
    python3 registry.py verify REGISTRY
    python3 registry.py --selftest

The archive is deterministic: fixed member metadata, sorted names, no timestamps
and no user names, so exporting the same registry twice produces the same bytes.

Verification checks more than the record-level suite does. The suite hashes the
bytes of every artifact it resolves; this tool also checks that each record's id
is the content address of its body, and that every record names the manifest the
registry actually holds. A store whose entries do not match their names is not
content-addressed, whatever the filenames say.
"""

from __future__ import annotations

import argparse
import contextlib
import gzip
import hashlib
import io
import json
import os
import sys
import tarfile
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from validate import SUITE_VERSION, Store, canonical_bytes, norm_hash, run_checks  # noqa: E402

# Built by concatenation so that this file does not itself contain the strings
# it refuses: the export guard reads the bytes of every member, including this
# one, and a literal here would make the tool refuse to export itself.
FORBIDDEN = [
    os.path.expanduser("~").encode(),
    b"/" + b"Users/",
    b"/" + b"home/",
    b"/" + b"private/" + b"var/",
]

MAX_MEMBER_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024


def locate(root):
    """Find the manifest, the records, and the store.

    Three layouts are accepted: a clean registry (manifest.json + records/ +
    artifacts/), a records directory that is itself the registry (manifest.json
    beside the records and artifacts/), and a repository root that holds such a
    directory under records/.
    """
    descriptor = os.path.join(root, "registry.json")
    if os.path.isfile(descriptor):
        with open(descriptor, "r", encoding="utf-8") as handle:
            spec = json.load(handle)
        return (os.path.join(root, spec["manifest"]),
                os.path.join(root, spec["records"]),
                os.path.join(root, spec["artifacts"]))
    if (os.path.isfile(os.path.join(root, "manifest.json"))
            and os.path.isdir(os.path.join(root, "records"))):
        return (os.path.join(root, "manifest.json"),
                os.path.join(root, "records"),
                os.path.join(root, "artifacts"))
    if (os.path.isfile(os.path.join(root, "manifest.json"))
            and os.path.isdir(os.path.join(root, "artifacts"))):
        return (os.path.join(root, "manifest.json"), root, os.path.join(root, "artifacts"))
    if os.path.isfile(os.path.join(root, "records", "manifest.json")):
        return (os.path.join(root, "records", "manifest.json"),
                os.path.join(root, "records"),
                os.path.join(root, "records", "artifacts"))
    raise SystemExit("no manifest found under %s" % root)


def looks_like_record(document):
    return (isinstance(document, dict)
            and "mir_version" in document
            and "claim" in document
            and "runs" in document)


def records_in(directory):
    found = []
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(directory, name)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                document = json.load(handle)
        except (OSError, ValueError):
            continue
        if looks_like_record(document):
            found.append((name, path, document))
    return found


def file_digest(path):
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            hasher.update(block)
    return hasher.hexdigest()


def add(tar, name, data, mode=0o644):
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mtime = 0
    info.mode = mode
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    tar.addfile(info, io.BytesIO(data))


def export(root, out_path):
    manifest_path, records_dir, artifacts_dir = locate(root)
    with open(manifest_path, "rb") as handle:
        manifest_bytes = handle.read()
    manifest_hash = "sha256:" + hashlib.sha256(manifest_bytes).hexdigest()

    records = records_in(records_dir)
    if not records:
        raise SystemExit("no records under %s" % records_dir)
    artifacts = sorted(n for n in os.listdir(artifacts_dir)
                       if os.path.isfile(os.path.join(artifacts_dir, n)))

    index = {
        "format": "mir-registry-export",
        "suite": SUITE_VERSION,
        "manifest_hash": manifest_hash,
        "records": [{"file": name, "id": document.get("id")} for name, _p, document in records],
        "artifacts": len(artifacts),
    }

    payload = [(name, path) for name, path, _d in records]
    payload += [(os.path.join("artifacts", name), os.path.join(artifacts_dir, name))
                for name in artifacts]

    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w", format=tarfile.USTAR_FORMAT) as tar:
            add(tar, "index.json", canonical_bytes(index))
            add(tar, "manifest.json", manifest_bytes)
            for name, path in payload:
                with open(path, "rb") as handle:
                    data = handle.read()
                for forbidden in FORBIDDEN:
                    if forbidden in data:
                        raise SystemExit("refusing to export %s: it contains %r" % (name, forbidden))
                add(tar, name.replace(os.sep, "/"), data)

    with open(out_path, "wb") as handle:
        handle.write(buffer.getvalue())
    print("exported %d record(s), %d artifact(s)" % (len(records), len(artifacts)))
    print("manifest %s" % manifest_hash)
    print("archive  %s  %d bytes  sha256:%s"
          % (out_path, len(buffer.getvalue()), hashlib.sha256(buffer.getvalue()).hexdigest()))
    return 0


def safe_members(tar):
    for member in tar.getmembers():
        name = member.name
        if name.startswith("/") or ".." in name.split("/"):
            raise SystemExit("refusing to extract %r" % name)
        if not name.strip(" \t\r\n./") or name.endswith("/"):
            raise SystemExit("refusing to extract member with no file name %r" % name)
        if not member.isfile():
            raise SystemExit("refusing to extract non-regular member %r" % name)
        yield member


def import_archive(archive, dest):
    os.makedirs(dest, exist_ok=True)
    with tarfile.open(archive, "r:gz") as tar:
        members = list(safe_members(tar))
        total = 0
        for member in members:
            if member.size > MAX_MEMBER_BYTES:
                raise SystemExit("refusing to extract %r: %d bytes is over the %d-byte member limit"
                                 % (member.name, member.size, MAX_MEMBER_BYTES))
            total += member.size
        if total > MAX_ARCHIVE_BYTES:
            raise SystemExit("refusing to extract %s: %d bytes is over the %d-byte archive limit"
                             % (archive, total, MAX_ARCHIVE_BYTES))
        for member in members:
            target = os.path.join(dest, member.name)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            source = tar.extractfile(member)
            with open(target, "wb") as handle:
                for block in iter(lambda: source.read(1 << 20), b""):
                    handle.write(block)
    print("imported into %s" % dest)
    return verify(dest)


def verify(root):
    """Check that the registry is intact, and report what conforms.

    Two different things are measured. Integrity is a property of the export:
    every artifact hashes to its name, every record id is the content address of
    its body, and every record points at the manifest the registry holds. A
    registry that fails integrity is not the registry that was exported.

    Conformance is a property of the records. A registry may hold records that
    fail checks — the worked example fails one on purpose — and an export that
    refused them would be an export of a curated subset, which is the opposite
    of what MIR-1-09 asks for.
    """
    manifest_path, records_dir, artifacts_dir = locate(root)
    problems = []
    with open(manifest_path, "rb") as handle:
        manifest_bytes = handle.read()
    manifest_hash = "sha256:" + hashlib.sha256(manifest_bytes).hexdigest()

    artifacts = sorted(n for n in os.listdir(artifacts_dir)
                       if os.path.isfile(os.path.join(artifacts_dir, n)))
    checked = 0
    matched = 0
    for name in artifacts:
        if name.endswith(".locator.json"):
            continue
        checked += 1
        if file_digest(os.path.join(artifacts_dir, name)) == name:
            matched += 1
        else:
            problems.append("artifact %s does not hash to its name" % name)

    records = records_in(records_dir)
    store = Store([artifacts_dir, records_dir])
    conforming = 0
    failing = []
    for name, path, document in records:
        body = {k: v for k, v in document.items() if k != "id"}
        expected = "sha256:" + hashlib.sha256(canonical_bytes(body)).hexdigest()
        if document.get("id") != expected:
            problems.append("%s: id is not the content address of its body" % name)
            continue
        if norm_hash(document.get("manifest_hash")) != manifest_hash[7:]:
            problems.append("%s: declares a manifest this registry does not hold" % name)
        results = run_checks(document, store)
        failed = [cid for cid, (ok, _) in results if not ok]
        if failed:
            failing.append((name, failed))
        else:
            conforming += 1

    print("%-40s %s" % ("manifest", manifest_hash))
    print("%-40s %d checked, %d match their name" % ("artifacts", checked, matched))
    print("%-40s %d, %d conform, %d do not" % ("records", len(records), conforming, len(failing)))
    for name, failed in failing:
        print("  %s fails %s" % (name, ", ".join(failed)))
    for problem in problems:
        print("  %s" % problem)
    if problems:
        print("RESULT: FAIL (%d integrity problem(s))" % len(problems))
        return 1
    print("RESULT: PASS (integrity)")
    return 0


def selftest():
    failures = 0

    def check_case(label, condition, detail=""):
        nonlocal failures
        if condition:
            print("%-52s ok" % label)
        else:
            failures += 1
            print("%-52s FAILED %s" % (label, detail))

    registry = os.path.join(HERE, "records")
    temp = tempfile.mkdtemp(prefix="mir-registry-")
    archive = os.path.join(temp, "export.tar.gz")
    export(registry, archive)
    with open(archive, "rb") as handle:
        first = hashlib.sha256(handle.read()).hexdigest()
    export(registry, archive + ".2")
    with open(archive + ".2", "rb") as handle:
        second = hashlib.sha256(handle.read()).hexdigest()
    check_case("two exports of one registry are identical", first == second)

    with tarfile.open(archive, "r:gz") as tar:
        names = tar.getnames()
    check_case("no absolute paths in the archive",
               all(not name.startswith("/") and ".." not in name.split("/") for name in names))
    check_case("the archive carries the manifest and the store",
               "manifest.json" in names and any(n.startswith("artifacts/") for n in names))

    dest = os.path.join(temp, "imported")
    report = io.StringIO()
    with contextlib.redirect_stdout(report):
        code = import_archive(archive, dest)
    text = report.getvalue()
    check_case("a fresh import verifies", code == 0)
    check_case("a non-conforming record is reported, not treated as damage",
               "fails C-07" in text and "PASS (integrity)" in text)

    artifacts = os.path.join(dest, "artifacts")
    victim = sorted(n for n in os.listdir(artifacts) if not n.endswith(".locator.json"))[0]
    with open(os.path.join(artifacts, victim), "ab") as handle:
        handle.write(b"X")
    check_case("one changed byte fails verification", verify(dest) == 1)

    return 0 if failures == 0 else 1


def main(argv):
    parser = argparse.ArgumentParser(description="Export, import, and verify a MIR-1 registry.")
    parser.add_argument("command", nargs="?", choices=["export", "import", "verify"])
    parser.add_argument("first", nargs="?")
    parser.add_argument("second", nargs="?")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest()
    if args.command == "export" and args.first and args.second:
        return export(args.first, args.second)
    if args.command == "import" and args.first and args.second:
        return import_archive(args.first, args.second)
    if args.command == "verify" and args.first:
        return verify(args.first)
    parser.error("usage: registry.py export DIR OUT | import ARCHIVE DEST | verify DIR | --selftest")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
