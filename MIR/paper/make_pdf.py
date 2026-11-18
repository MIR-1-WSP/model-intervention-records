#!/usr/bin/env python3
"""Build the paper and its addendum deterministically, with pdflatex.

    python3 paper/make_pdf.py

arXiv compiles the source archive with pdflatex, so the PDF shipped beside it has
to come from the same engine. xelatex defaults to Latin Modern where pdflatex
defaults to Computer Modern: one .tex, two visibly different papers.

Each build is pinned to the date printed on the document's own title page and to
UTC. Left alone, pdfTeX writes the machine's local offset into /CreationDate ---
a timezone fingerprint in an anonymous release --- and the current clock, which
makes the PDF unreproducible. Two builds must produce identical bytes, and the
result must carry no path, no address and no local offset, or nothing is written.

The date is the document's, not the release's: rebuilding a document for a later
release must not restamp it, or ``metadata-only'' stops being a claim a reader
can check by diffing two files.
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
from make_release import audit_pdf  # noqa: E402

# source, output, the date printed on the title page
DOCUMENTS = [
    ("mir-1.tex", "mir-1.pdf", "2026-11-14T03:00:00+00:00"),
    ("mir-1-addendum.tex", "mir-1-addendum.pdf", "2026-11-18T03:00:00+00:00"),
]


def epoch_seconds(stamp):
    return calendar.timegm(time.strptime(stamp[:19], "%Y-%m-%dT%H:%M:%S"))


def compile_once(work, env, tex, pdf):
    for _ in (1, 2):
        proc = subprocess.run(["pdflatex", "-interaction=nonstopmode",
                               "-halt-on-error", tex],
                              cwd=work, env=env, capture_output=True, text=True)
        if proc.returncode != 0:
            raise SystemExit("pdflatex failed:\n%s" % proc.stdout[-4000:])
    with open(os.path.join(work, pdf), "rb") as handle:
        payload = handle.read()
    pages = re.search(r"Output written on .*?\((\d+) pages?", proc.stdout)
    return payload, int(pages.group(1)) if pages else 0


def build(tex, pdf, stamp):
    env = dict(os.environ, TZ="UTC", LC_ALL="C",
               SOURCE_DATE_EPOCH=str(epoch_seconds(stamp)))
    builds = []
    for _ in (1, 2):
        work = tempfile.mkdtemp(prefix="mir-pdf-")
        try:
            shutil.copyfile(os.path.join(HERE, tex), os.path.join(work, tex))
            builds.append(compile_once(work, env, tex, pdf))
        finally:
            shutil.rmtree(work, ignore_errors=True)
    payload, pages = builds[0]
    if payload != builds[1][0]:
        raise SystemExit("refusing to write %s: two builds produced different bytes" % pdf)
    problems = audit_pdf(payload)
    if problems:
        raise SystemExit("refusing to write %s:\n  %s" % (pdf, "\n  ".join(problems)))
    with open(os.path.join(HERE, pdf), "wb") as handle:
        handle.write(payload)
    print("%-22s %7d bytes  %2d pages  %s" % (pdf, len(payload), pages, stamp))
    print("%-22s sha256 %s" % ("", hashlib.sha256(payload).hexdigest()))
    return pages


def main():
    if shutil.which("pdflatex") is None:
        raise SystemExit("pdflatex is not on PATH; install TeX Live first")
    for tex, pdf, stamp in DOCUMENTS:
        build(tex, pdf, stamp)
    print("\ntwo builds of each document are byte-identical; no path, address or local offset")
    return 0


if __name__ == "__main__":
    sys.exit(main())
