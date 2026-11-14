#!/usr/bin/env python3
"""Build the release bundle in a clean staging directory, reproducibly.

    python3 make_release.py [--remote] [--out DIR]

The bundle is the unit of distribution, so it is built from a copy rather than
from the working tree: the working tree carries private notes, backups, build
artifacts and extended attributes that must not be published. The copy is made
outside this repository, given a local identity, and committed at a fixed epoch
in the past.

The bundle is built twice and the two digests must match. A release whose digest
cannot be reproduced is a release nobody can verify they hold.

Refuses to build when the paper's PDF is older than its source, because a bundle
carrying a PDF that does not match the .tex beside it publishes two papers.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(HERE)
# Outside MIR/, which is what gets staged. A bundle written inside MIR/ would be
# copied into the next build's staging tree and tracked there, so each release
# would contain the previous one and the digest would never settle.
RELEASE = os.path.join(PARENT, "release")

# Fixed, and in the past relative to the real clock. A future date in an
# anonymous release is a forensic anomaly, not a harmless constant.
BUILD_EPOCH = "2026-11-14T03:00:00+00:00"
COMMIT_MESSAGE = ("MIR-1: specification, two implementations, adapter, registry, "
                  "worked example, paper")

EXCLUDE_NAMES = {".DS_Store", "__pycache__", ".git", "mir-validate"}
EXCLUDE_SUFFIXES = (".pyc",)
EXCLUDE_RELATIVE = {"paper/dist", "paper/draft.md"}

FORBIDDEN = [
    os.path.expanduser("~").encode(),
    b"/Users/",
    b"/home/",
    b"/private/var/",
]

# The builders carry the generic prefixes above as detection patterns. A guard
# quoting the string it looks for is not a leak, so those literals are removed
# before scanning. The home directory is computed rather than written down, so a
# real one is still caught wherever it appears.
GUARD_LITERALS = [b'b"/Users/"', b'b"/home/"', b'b"/private/var/"']

UTC_OFFSETS = ("Z", "+00'00'", "-00'00'")


def run(command, cwd=None, env=None):
    proc = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit("command failed: %s\n%s%s"
                         % (" ".join(command), proc.stdout, proc.stderr))
    return proc.stdout


def digest(payload):
    return hashlib.sha256(payload).hexdigest()


def copy_tree(source, target):
    """Copy MIR/ into the staging repository, leaving the private parts behind."""
    for root, dirs, files in os.walk(source):
        dirs[:] = sorted(d for d in dirs
                         if d not in EXCLUDE_NAMES
                         and not d.startswith(".backup-pre-")
                         and os.path.relpath(os.path.join(root, d), source) not in EXCLUDE_RELATIVE)
        relative_dir = os.path.relpath(root, source)
        for name in sorted(files):
            if name in EXCLUDE_NAMES or name.endswith(EXCLUDE_SUFFIXES):
                continue
            relative = os.path.normpath(os.path.join(relative_dir, name))
            if relative in EXCLUDE_RELATIVE or relative.startswith("paper/dist/"):
                continue
            destination = os.path.join(target, relative)
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            shutil.copyfile(os.path.join(root, name), destination)


def stage(root):
    repo = os.path.join(root, "mir-1")
    os.makedirs(os.path.join(repo, "MIR"))
    copy_tree(HERE, os.path.join(repo, "MIR"))
    shutil.copyfile(os.path.join(PARENT, "MIR-1-spec.md"),
                    os.path.join(repo, "MIR-1-spec.md"))
    shutil.copyfile(os.path.join(PARENT, "README.md"),
                    os.path.join(repo, "README.md"))
    workflows = os.path.join(repo, ".github", "workflows")
    os.makedirs(workflows, exist_ok=True)
    shutil.copyfile(os.path.join(HERE, "ci", "verify.yml"),
                    os.path.join(workflows, "verify.yml"))
    for path, dirs, files in os.walk(repo):
        for name in files:
            if name == ".DS_Store":
                os.remove(os.path.join(path, name))
        dirs[:] = [d for d in dirs if d != "__pycache__"]
    subprocess.run(["xattr", "-rc", repo], capture_output=True)
    return repo


def commit(repo):
    run(["git", "init", "-q", "-b", "main"], cwd=repo)
    # Local to this repository. The global configuration is never touched.
    for key, value in (("user.name", "mir"), ("user.email", "mir@localhost"),
                       ("commit.gpgsign", "false")):
        run(["git", "config", "--local", key, value], cwd=repo)
    run(["git", "add", "-A"], cwd=repo)
    env = dict(os.environ, GIT_AUTHOR_DATE=BUILD_EPOCH, GIT_COMMITTER_DATE=BUILD_EPOCH)
    run(["git", "commit", "-q", "-m", COMMIT_MESSAGE], cwd=repo, env=env)
    return run(["git", "rev-parse", "HEAD"], cwd=repo).strip()


def audit(repo):
    """Nothing published may name the author or the machine."""
    problems = []
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d != ".git"]
        for name in sorted(files):
            path = os.path.join(root, name)
            with open(path, "rb") as handle:
                payload = handle.read()
            for literal in GUARD_LITERALS:
                payload = payload.replace(literal, b"")
            label = os.path.relpath(path, repo)
            for needle in FORBIDDEN:
                if needle in payload:
                    problems.append("%s contains %r" % (label, needle.decode()))
            if re.search(rb"[\w.+-]+@[\w-]+\.[\w.]+", payload):
                problems.append("%s contains an email address" % label)
    return problems


def inflate_streams(payload):
    """A PDF hides its metadata in compressed object streams; scan those too."""
    out = [payload]
    for match in re.finditer(rb"stream\r?\n", payload):
        start = match.end()
        end = payload.find(b"endstream", start)
        if end < 0:
            continue
        try:
            out.append(zlib.decompress(payload[start:end]))
        except zlib.error:
            pass
    return b"\n".join(out)


def audit_pdf(payload):
    """The PDF is the one published file the byte scan cannot read.

    pdfTeX writes the machine's local offset into /CreationDate unless the build
    is pinned to UTC, and a timezone in an anonymous release is a fingerprint.
    It also names its engine: arXiv compiles with pdflatex, so a PDF produced by
    xelatex is a different paper from the one arXiv will serve.
    """
    problems = []
    blob = inflate_streams(payload)
    for needle in FORBIDDEN:
        if needle in blob:
            problems.append("the PDF contains %r" % needle.decode(errors="replace"))
    for address in re.findall(rb"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", blob):
        problems.append("the PDF contains an address: %s" % address.decode())
    for stamp in re.findall(rb"/(?:CreationDate|ModDate)\s*\((D:\d{14})([^)]*)\)", blob):
        if stamp[1].decode() not in UTC_OFFSETS:
            problems.append("the PDF carries a local timezone offset: %s%s"
                            % (stamp[0].decode(), stamp[1].decode()))
    producer = re.findall(rb"/Producer\s*\(([^)]*)\)", blob)
    if producer and not any(p.startswith(b"pdfTeX") for p in producer):
        problems.append("the PDF was not built by pdfTeX: %s"
                        % producer[0].decode(errors="replace"))
    return problems


def audit_identity(repo):
    """The commit must carry the release identity and nothing else."""
    problems = []
    author = run(["git", "log", "-1", "--format=%an <%ae>"], cwd=repo).strip()
    committer = run(["git", "log", "-1", "--format=%cn <%ce>"], cwd=repo).strip()
    for label, value in (("author", author), ("committer", committer)):
        if value != "mir <mir@localhost>":
            problems.append("%s is %s" % (label, value))
    return problems


def gate(repo, remote):
    """Run the publication gate inside the staging copy, not the working tree.

    Each command is held to its expected answer, including the one that must
    fail: the worked example fails C-07, and a build where it passes everything
    is a build whose record stopped being the paper's subject.
    """
    mir = os.path.join(repo, "MIR")
    results = []
    for label, command in (
        ("ci/check.py", [sys.executable, "ci/check.py"]),
        ("crosscheck.py --fuzz 400", [sys.executable, "crosscheck.py", "--fuzz", "400"]),
        ("space/selftest.py", [sys.executable, "space/selftest.py"]),
        ("records/selfcheck.py", [sys.executable, "records/selfcheck.py"]),
    ):
        proc = subprocess.run(command, cwd=mir, capture_output=True, text=True)
        lines = [line for line in proc.stdout.splitlines() if line.strip()]
        results.append((label, proc.returncode == 0, lines[-1] if lines else ""))
    command = [sys.executable, "validate.py", "records/MIR-R1.json", "--json"]
    if remote:
        command.append("--verify-remote")
    proc = subprocess.run(command, cwd=mir, capture_output=True, text=True)
    report = json.loads(proc.stdout)
    failing = sorted(c["id"] for c in report["checks"] if not c["ok"])
    label = "validate.py MIR-R1" + (" --verify-remote" if remote else "")
    results.append((label, proc.returncode == 1 and failing == ["C-07"],
                    "fails %s" % (",".join(failing) or "nothing")))
    return results


def main(argv):
    remote = "--remote" in argv
    out = RELEASE
    if "--out" in argv:
        out = os.path.abspath(argv[argv.index("--out") + 1])
    if os.path.commonpath([out, HERE]) == HERE:
        print("refusing to build: --out is inside MIR/, which is staged")
        print("  the bundle would be tracked by the next build")
        return 1

    pdf = os.path.join(HERE, "paper", "mir-1.pdf")
    tex = os.path.join(HERE, "paper", "mir-1.tex")
    if os.path.isfile(pdf) and os.path.getmtime(pdf) < os.path.getmtime(tex):
        print("refusing to build: paper/mir-1.pdf is older than paper/mir-1.tex")
        print("  the bundle would carry a PDF that does not match its source")
        print("  rebuild the PDF, then run this again")
        return 1
    if os.path.isfile(pdf):
        with open(pdf, "rb") as handle:
            problems = audit_pdf(handle.read())
        if problems:
            print("refusing to build: paper/mir-1.pdf would leak identity")
            for line in problems:
                print("  " + line)
            print("  rebuild it with python3 MIR/paper/make_pdf.py")
            return 1
    if time.time() < time.mktime(time.strptime(BUILD_EPOCH[:19], "%Y-%m-%dT%H:%M:%S")):
        print("refusing to build: BUILD_EPOCH is in the future")
        return 1

    root = tempfile.mkdtemp(prefix="mir-release-")
    if os.path.commonpath([root, PARENT]) == PARENT:
        raise SystemExit("staging must be outside the repository")
    try:
        repo = stage(root)
        problems = audit(repo)
        if problems:
            print("refusing to build:")
            for line in problems:
                print("  " + line)
            return 1
        head = commit(repo)
        problems = audit_identity(repo)
        if problems:
            print("refusing to build:")
            for line in problems:
                print("  " + line)
            return 1
        tracked = run(["git", "ls-files"], cwd=repo).splitlines()

        print("staging      %s" % repo)
        print("commit       %s" % head)
        print("identity     %s" % run(["git", "log", "-1", "--format=%an <%ae>"],
                                      cwd=repo).strip())
        print("tracked      %d files" % len(tracked))

        print("\ngate, run inside the staging copy")
        failed = 0
        for label, ok, summary in gate(repo, remote):
            print("  %-34s %-4s %s" % (label, "ok" if ok else "FAIL", summary[:70]))
            failed += not ok

        bundles = []
        for attempt in (1, 2):
            path = os.path.join(root, "mir-1-%d.bundle" % attempt)
            run(["git", "bundle", "create", path, "--all"], cwd=repo)
            with open(path, "rb") as handle:
                bundles.append(handle.read())
        same = bundles[0] == bundles[1]
        print("\nbundle       %d bytes  %s" % (len(bundles[0]), digest(bundles[0])))
        print("reproducible %s" % ("yes" if same else "NO"))
        if not same:
            return 1

        if failed:
            print("\nrefusing to publish: %d gate command(s) failed" % failed)
            return 1
        os.makedirs(out, exist_ok=True)
        target = os.path.join(out, "mir-1.bundle")
        with open(target, "wb") as handle:
            handle.write(bundles[0])
        with open(target + ".sha256", "w", encoding="utf-8") as handle:
            handle.write("%s  mir-1.bundle\n" % digest(bundles[0]))
        print("wrote        %s" % target)
        return 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))