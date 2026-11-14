#!/usr/bin/env python3
"""Build paper/mir-1.pdf deterministically, with pdflatex.

    python3 paper/make_pdf.py

arXiv compiles the source archive with pdflatex, so the PDF shipped beside it has
to come from the same engine. xelatex defaults to Latin Modern where pdflatex
defaults to Computer Modern: one .tex, two visibly different papers.

The build is pinned to the release epoch and to UTC. Left alone, pdfTeX writes
the machine's local offset into /CreationDate --- a timezone fingerprint in an
anonymous release --- and the current clock, which makes the PDF unreproducible.
Two builds must produce identical bytes, and the result must carry no path, no
address and no local offset, or nothing is written.
"""

from __future__ import annotations

import calendar
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)            # MIR/
sys.path.insert(0, ROOT)
from make_release import BUILD_EPOCH, audit_pdf  # noqa: E402

TEX = "mir-1.tex"
PDF = "mir-1.pdf"


def epoch_seconds():
    return calendar.timegm(time.strptime(BUILD_EPOCH[:19], "%Y-%m-%dT%H:%M:%S"))


def compile_once(work, env):
    for _ in (1, 2):
        proc = subprocess.run(["pdflatex", "-interaction=nonstopmode",
                               "-halt-on-error", TEX],
                              cwd=work, env=env, capture_output=True, text=True)
        if proc.returncode != 0:
            raise SystemExit("pdflatex failed:\n%s" % proc.stdout[-4000:])
    with open(os.path.join(work, PDF), "rb") as handle:
        payload = handle.read()
    pages = re.search(r"Output written on .*?\((\d+) pages?", proc.stdout)
    return payload, int(pages.group(1)) if pages else 0


def main():
    if shutil.which("pdflatex") is None:
        raise SystemExit("pdflatex is not on PATH; install TeX Live first")
    env = dict(os.environ, TZ="UTC", LC_ALL="C",
               SOURCE_DATE_EPOCH=str(epoch_seconds()))
    builds = []
    try:
        for _ in (1, 2):
            work = tempfile.mkdtemp(prefix="mir-pdf-")
            try:
                shutil.copyfile(os.path.join(HERE, TEX), os.path.join(work, TEX))
                builds.append(compile_once(work, env))
            finally:
                shutil.rmtree(work, ignore_errors=True)
    except SystemExit:
        raise
    payload, pages = builds[0]
    if payload != builds[1][0]:
        raise SystemExit("refusing to write: two builds produced different bytes")
    problems = audit_pdf(payload)
    if problems:
        print("refusing to write:")
        for line in problems:
            print("  " + line)
        return 1
    target = os.path.join(HERE, PDF)
    with open(target, "wb") as handle:
        handle.write(payload)
    print("%s  %d bytes  %d pages" % (PDF, len(payload), pages))
    print("sha256  %s" % hashlib.sha256(payload).hexdigest())
    print("epoch   %s (UTC, fixed)" % BUILD_EPOCH)
    print("two builds identical; no path, address or local offset")
    return 0


if __name__ == "__main__":
    sys.exit(main())