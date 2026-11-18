#!/usr/bin/env python3
"""Build the two archives an arXiv submission needs, deterministically.

    python3 paper/make_arxiv.py

Produces, in paper/dist/:

    mir-1-source.tar.gz     mir-1.tex, nothing else. arXiv compiles this.
    mir-1-ancillary.tar.gz  the specification and the test, so that the paper
                            carries its own checker instead of pointing at a
                            repository that would have to be hosted somewhere.

Both archives are built with fixed metadata (mtime 0, uid/gid 0, no user or
group names) so that rebuilding on another day produces the same bytes and the
same digest. The script refuses to write an archive that contains a path or a
string that could identify the author or the machine.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import os
import re
import sys
import tarfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)            # MIR/
PARENT = os.path.dirname(ROOT)          # the directory holding MIR-1-spec.md
DIST = os.path.join(HERE, "dist")

SOURCE_FILES = ["mir-1.tex"]

# Every ancillary file is addressed from PARENT, so the specification and the
# implementation sit in one archive under the names the documentation uses.
ANCILLARY = [
    "kernel.md",
    "schema.json",
    "patch-schema.json",
    "validate.py",
    "patchcheck.py",
    "adapter.py",
    "adapters/dspy_wsp.py",
    "adapters/README.md",
    "adapters/testdata/edit.npz",
    "adapters/testdata/make_npz.py",
    "registry.py",
    "ci/check.py",
    "ci/verify.yml",
    "crosscheck.py",
    "fuzzgen.py",
    "README.md",
    "examples/build_examples.py",
    "examples/build_patch_example.py",
    "examples/patch/base.wpp-array.json",
    "examples/patch/record-a.json",
    "examples/patch/record-b.json",
    "examples/patch/patch_selfcheck.py",
    "examples/falsify_example.py",
    "examples/conforming.json",
    "examples/parent.json",
    "examples/terse-run.json",
    "impl2/patch.go",
    "impl2/qualifiers.go",
    "impl2/canonical.go",
    "impl2/checks.go",
    "impl2/schema.go",
    "impl2/store.go",
    "impl2/main.go",
    "impl2/pyformat.go",
    "impl2/casefold.go",
    "impl2/printability.go",
    "impl2/reference.go",
    "impl2/unicode_tables.go",
    "impl2/canonical_test.go",
    "impl2/schema_test.go",
    "impl2/casefold_test.go",
    "impl2/pyformat_test.go",
    "impl2/pystr_test.go",
    "impl2/reference_test.go",
    "impl2/go.mod",
    "impl2/README.md",
    "impl2/testdata/canonical_vectors.json",
    "impl2/testdata/make_vectors.py",
    "impl2/testdata/casefold_vectors.json",
    "impl2/testdata/make_casefold.py",
    "impl2/testdata/repr_vectors.json",
    "impl2/testdata/make_repr.py",
    "impl2/testdata/unicode_vectors.json",
    "impl2/testdata/make_unicode.py",
    "impl2/testdata/pystr_vectors.json",
    "impl2/testdata/make_pystr.py",
    "records/MIR-R1.json",
    "records/NOTES.md",
    "records/build_record.py",
    "records/falsify.py",
    "records/selfcheck.py",
    "records/qualifier_selfcheck.py",
    "records/manifest.json",
    "records/harness.json",
    "space/app.py",
    "space/selftest.py",
    "space/sync.py",
    "space/Dockerfile",
    "space/README.md",
    "space/validate.py",
    "space/schema.json",
    "space/patch-schema.json",
    "space/patchcheck.py",
    "space/kernel.md",
    "space/MIR-1-spec.md",
    "space/records/MIR-R1.json",
    "space/examples/patch/record-a.json",
]

ANCILLARY_DIRS = [
    "examples/patch/artifacts",
    "records/artifacts",
    "artifacts",
    "space/records/artifacts",
    "space/artifacts",
    "space/examples/patch/artifacts",
]

# Strings that must not appear in anything uploaded. The home directory is
# computed rather than written down, because a literal here would put the
# machine's account name into a published file that exists to prevent exactly
# that.
FORBIDDEN = [
    os.path.expanduser("~").encode(),
    b"/Users/",
    b"/home/",
    b"/private/var/",
]

README = """# Ancillary files for MIR-1

`MIR-1-spec.md` is the specification the paper describes. `validate.py` is the
reference implementation of its conformance test; `impl2/` is a second
implementation in Go, written from the specification and sharing no code.

Nothing here needs to be installed. The validator uses the Python standard
library only, and the Go implementation uses the standard library only.

```
python3 validate.py records/MIR-R1.json --verify-remote
python3 records/selfcheck.py
python3 crosscheck.py --fuzz 400
```

`MIR-1.1-Patch.md` extends the `weights` intervention type with composable
Weight Patches and five additional checks, P-01 to P-05. They are reported
beside the eleven rather than merged into them, and `examples/patch/record-a.json`
exercises all five.

The first command reports ten passes and one failure on the worked example:
the record does not state a cost for any run. That failure is the paper's
subject, not a defect in the archive. The second shows each check failing when
its condition is removed, across seventeen mutations of the worked example and
three of the conforming fixture; `examples/patch/patch_selfcheck.py` does the
same for the five patch checks. The third builds the Go binary and requires both
implementations to produce the same report, byte for byte, on every record, on
every mutation, and on random documents -- half arbitrary JSON shapes, half
mutations of a conforming record -- and prints which branches the corpus reached.

Text CC BY 4.0, code Apache-2.0.
"""


def digest(payload):
    return hashlib.sha256(payload).hexdigest()


def add(tar, name, payload, mode=0o644):
    info = tarfile.TarInfo(name)
    info.size = len(payload)
    info.mtime = 0
    info.mode = mode
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.type = tarfile.REGTYPE
    tar.addfile(info, io.BytesIO(payload))


def pack(members, prefix=""):
    """members: list of (archive name, bytes). Returns gzipped tar bytes."""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.GNU_FORMAT) as tar:
        for name, payload in members:
            add(tar, prefix + name, payload)
    compressed = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=compressed, mtime=0, compresslevel=9) as gz:
        gz.write(raw.getvalue())
    return compressed.getvalue()


def read(path):
    with open(path, "rb") as handle:
        return handle.read()


def check(payload, label):
    problems = []
    for needle in FORBIDDEN:
        if needle in payload:
            problems.append("%s contains %r" % (label, needle.decode()))
    if re.search(rb"[\w.+-]+@[\w-]+\.[\w.]+", payload):
        problems.append("%s contains an email address" % label)
    return problems


def main():
    missing = [name for name in ANCILLARY if not os.path.isfile(os.path.join(ROOT, name))]
    missing += [name for name in SOURCE_FILES if not os.path.isfile(os.path.join(HERE, name))]
    if not os.path.isfile(os.path.join(PARENT, "MIR-1-spec.md")):
        missing.append("../MIR-1-spec.md")

    # The list is explicit, so a new source file can be added to the tree and
    # silently left out of the archive. That happened once: impl2/schema.go was
    # added, the local suite and the release clone both passed, and the shipped
    # ancillary archive could not compile Go at all. Checking the reverse
    # direction turns "the files we listed exist" into "the archive is complete".
    # The vectors are checked too: a Go test whose golden file is missing fails
    # in the archive and nowhere else.
    listed = {os.path.normpath(name) for name in ANCILLARY}
    for directory in ("impl2", "impl2/testdata"):
        root = os.path.join(ROOT, directory)
        for name in sorted(os.listdir(root)):
            if not os.path.isfile(os.path.join(root, name)):
                continue
            if directory == "impl2" and not name.endswith(".go"):
                continue
            relative = os.path.normpath(os.path.join(directory, name))
            if relative not in listed:
                missing.append("%s (not listed in ANCILLARY)" % relative)
    if missing:
        print("missing files:")
        for name in missing:
            print("  " + name)
        return 1

    source_members = [(name, read(os.path.join(HERE, name))) for name in SOURCE_FILES]

    ancillary_members = [
        ("MIR-1-spec.md", read(os.path.join(PARENT, "MIR-1-spec.md"))),
        ("MIR-1.1-Patch.md", read(os.path.join(PARENT, "MIR-1.1-Patch.md"))),
        ("MIR-1.2-Qualifiers.md", read(os.path.join(PARENT, "MIR-1.2-Qualifiers.md"))),
        ("CITATION.cff", read(os.path.join(PARENT, "CITATION.cff"))),
    ]
    for name in ANCILLARY:
        ancillary_members.append((name, read(os.path.join(ROOT, name))))
    for source_dir in ANCILLARY_DIRS:
        directory = os.path.join(ROOT, source_dir)
        for name in sorted(os.listdir(directory)):
            path = os.path.join(directory, name)
            if os.path.isfile(path):
                ancillary_members.append((source_dir + "/" + name, read(path)))
    ancillary_members.append(("README-ANCILLARY.md", README.encode("utf-8")))

    problems = []
    for name, payload in source_members + ancillary_members:
        problems += check(payload, name)
    if problems:
        print("refusing to build:")
        for line in problems:
            print("  " + line)
        return 1

    os.makedirs(DIST, exist_ok=True)
    for label, members in (("source", source_members), ("ancillary", ancillary_members)):
        payload = pack(members)
        path = os.path.join(DIST, "mir-1-%s.tar.gz" % label)
        with open(path, "wb") as handle:
            handle.write(payload)
        print("%-28s %8d bytes  %s" % (os.path.basename(path), len(payload), digest(payload)))
        print("%-28s %8d files" % ("", len(members)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
