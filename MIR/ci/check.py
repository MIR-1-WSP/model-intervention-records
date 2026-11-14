#!/usr/bin/env python3
"""The whole verification, with the expected answer for each step.

A conformance suite cannot be checked by exit code: the worked example is
supposed to fail one check, and a run that turned that into a pass would be the
worst possible outcome. Each step below asserts the result it is supposed to
produce, so a change that makes the suite more permissive fails here.

    python3 ci/check.py

No network. `--verify-remote` is exercised by hand, not in CI, because a
flaky host should not look like a broken format.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable


def run(command, cwd=ROOT):
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True)


def main():
    cases = []
    outputs = {}

    def expect(label, command, wanted, cwd=ROOT):
        result = run(command, cwd)
        output = (result.stdout or "") + (result.stderr or "")
        missing = [text for text in wanted if text not in output]
        ok = not missing and result.returncode == 0
        outputs[label] = output
        cases.append((label, ok, "" if ok else "missing %r (exit %d)" % (missing, result.returncode)))
        return result

    def expect_failure(label, command, wanted, cwd=ROOT):
        """A step that is supposed to exit non-zero, with a stated reason."""
        result = run(command, cwd)
        output = (result.stdout or "") + (result.stderr or "")
        missing = [text for text in wanted if text not in output]
        ok = not missing and result.returncode != 0
        outputs[label] = output
        cases.append((label, ok, "" if ok else "missing %r (exit %d)" % (missing, result.returncode)))

    mir = ROOT  # ci/ lives inside MIR/

    expect_failure("the worked example fails exactly one check",
                   [PY, "validate.py", "records/MIR-R1.json"], ["RESULT: FAIL (1 of 11)"], mir)
    expect("the positive fixture passes every check",
           [PY, "validate.py", "examples/conforming.json"], ["RESULT: PASS (11 of 11)"], mir)
    expect("the lineage root passes every check",
           [PY, "validate.py", "examples/parent.json"], ["RESULT: PASS (11 of 11)"], mir)
    expect_failure("the invariant fixture fails on invariants",
                   [PY, "validate.py", "examples/terse-run.json"], ["C-05 FAIL", "RESULT: FAIL (1 of 11)"], mir)
    expect("every check has been seen to fail",
           [PY, "records/selfcheck.py"], ["schema agreement"], mir)
    expect("the two implementations agree",
           [PY, "crosscheck.py", "--fuzz", "20"], ["both implementations agree"], mir)
    expect("the Go tests pass", ["go", "test", "./..."], ["ok"], os.path.join(mir, "impl2"))
    expect("the adapter builds a record",
           [PY, "adapter.py", "--selftest"], ["C-01 accepts the record the adapter built"], mir)
    expect("a registry exports, imports, and detects damage",
           [PY, "registry.py", "--selftest"], ["one changed byte fails verification"], mir)

    skipped = []

    # §7.5 requires the normative kernel, the text a model reads, to be a
    # standalone file under 250 words. It is one sentence from that limit, and
    # nothing enforced it. A document that demands gates but leaves its own
    # rules as prose is the failure the format exists to prevent.
    kernel_path = os.path.join(mir, "kernel.md")
    if os.path.isfile(kernel_path):
        with open(kernel_path, "r", encoding="utf-8") as handle:
            kernel_text = handle.read()
        words = len(kernel_text.split())
        cases.append(("the normative kernel stays under 250 words",
                      words < 250, "%d words" % words))

        # Both copies are normative. The spec is published beside MIR/ in the
        # repository and at the root of the arXiv archive, so look in both.
        spec_path = next(
            (p for p in (os.path.join(mir, "MIR-1-spec.md"),
                         os.path.join(os.path.dirname(mir), "MIR-1-spec.md"))
             if os.path.isfile(p)), None)
        if spec_path:
            with open(spec_path, "r", encoding="utf-8") as handle:
                document = handle.read()
            marker = "> A claim that an intervention changes"
            quoted = []
            if marker in document:
                for line in document[document.index(marker):].splitlines():
                    if not line.startswith(">"):
                        break
                    quoted.append(line[1:].lstrip(" "))
            appendix = "\n".join(quoted).strip()
            standalone = kernel_text.split("---", 1)[1].strip()
            cases.append(("the kernel and Appendix D carry the same words",
                          appendix == standalone,
                          "" if appendix == standalone else "the two copies differ"))

    # The arXiv ancillary archive is the artifact a reviewer actually receives.
    # It is built from an explicit file list, so it can be incomplete while the
    # working tree passes every other check. Build it here, extract it into an
    # empty directory, and run this same verification inside it.
    builder = os.path.join(mir, "paper", "make_arxiv.py")
    if os.path.isfile(builder):
        built = run([PY, "paper/make_arxiv.py"], mir)
        archive = os.path.join(mir, "paper", "dist", "mir-1-ancillary.tar.gz")
        why = "" if built.returncode == 0 else "builder failed: %s" % (built.stdout or built.stderr)[-200:]
        temp = tempfile.mkdtemp(prefix="mir-ancillary-")
        try:
            unpacked = run(["tar", "-xzf", archive, "-C", temp])
            if unpacked.returncode != 0:
                why = why or "could not extract the archive"
                inner = None
            else:
                inner = run([PY, "ci/check.py"], temp)
                text = (inner.stdout or "") + (inner.stderr or "")
                if inner.returncode != 0 or "RESULT: PASS" not in text or "FAILED" in text:
                    why = why or "the extracted archive does not verify: %s" % text.strip().splitlines()[-1]
            ok = not why
            cases.append(("the arXiv ancillary verifies on its own", ok, why))
        finally:
            shutil.rmtree(temp, ignore_errors=True)
    else:
        skipped.append("the arXiv ancillary (builder not in this package)")

    if os.path.isfile(os.path.join(mir, "space", "sync.py")):
        expect("the Space answers correctly",
               [PY, "space/selftest.py"], ["9 checks, all pass"], mir)
        expect("the Space serves current copies",
               [PY, "space/sync.py", "--check"], ["in sync"], mir)
    else:
        skipped.append("the Space (source not in this package)")

    for label in skipped:
        print("%-*s  skipped" % (max(len(x) for x in [c[0] for c in cases] + [label]), label))
    width = max(len(label) for label, _ok, _why in cases)
    for label, ok, why in cases:
        print("%-*s  %s%s" % (width, label, "ok" if ok else "FAILED", ("  " + why) if why else ""))
    failed = [label for label, ok, _why in cases if not ok]

    # A failing check that reports only "missing" leaves the operator to
    # reproduce it by hand, which is how a stale pin stayed unexplained behind
    # a green-looking message. The tail of the step's own output is printed
    # under the table, indented, so the reason is in the same run.
    for label, ok, _why in cases:
        if ok:
            continue
        rows = [line for line in outputs.get(label, "").splitlines() if line.strip()]
        if rows:
            print()
            print(label)
            for line in rows[-12:]:
                print("  " + line)

    print()
    if failed:
        print("RESULT: FAIL (%d of %d)" % (len(failed), len(cases)))
        return 1
    if skipped:
        print("RESULT: PASS (%d of %d, %d skipped)" % (len(cases), len(cases), len(skipped)))
    else:
        print("RESULT: PASS (%d of %d)" % (len(cases), len(cases)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
