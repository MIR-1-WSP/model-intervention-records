# Distribution

This repository is distributed as a single git bundle. The bundle is the unit:
it carries the full history, the specification, both implementations, the worked
example, and the paper. A clone from the bundle is the release.

## Verify

```
shasum -a 256 mir-1.bundle
git clone mir-1.bundle mir-1
cd mir-1
git bundle verify ../mir-1.bundle
git log -1 --format='%H %an <%ae> %ad'
```

`git bundle verify` comes after the clone because it needs a repository to check
the bundle's prerequisites against. Run first, in the directory where the bundle
was downloaded, it fails with `need a repository to verify a bundle` — which
reads as a damaged release rather than as a command in the wrong order.

The SHA-256 of the bundle is published next to it as `mir-1.bundle.sha256`.
If the digest you compute is not the one published, the file is not the
release, whatever its name says.

## What is inside

- `README.md` — what the release is, how to verify it, and what it does not do.
- `MIR-1-spec.md` — the specification.
- `MIR/` — the reference validator, the second implementation in Go, the
  worked example, the mutation suite, the differential test, and the Space
  source.
- `MIR/paper/mir-1.pdf` — the paper.
- `MIR/paper/mir-1.tex` — its source.

Not inside: private working notes, and `MIR/paper/dist/`. The arXiv archives are
rebuilt deterministically by `python3 MIR/paper/make_arxiv.py`.

## Run the test

```
cd MIR
python3 ci/check.py
python3 validate.py records/MIR-R1.json --verify-remote
python3 registry.py export records /tmp/registry.tar.gz
```

`ci/check.py` ends in `RESULT: PASS (14 of 14)`: it asserts the answer each
step must produce, including the ones that must fail. The next command ends in
`RESULT: FAIL (1 of 11)` — the worked example failing cost disclosure, which is
the paper's subject. The third exports the registry so a third party can import
and verify it. The differential test and every mutation are already inside the
first command.

## Rebuild

Four commands reproduce the whole release, in this order:

```
python3 MIR/space/sync.py          # after any edit to the spec or the records
python3 MIR/paper/make_pdf.py      # needs pdflatex on PATH
python3 MIR/paper/make_arxiv.py
python3 MIR/make_release.py --remote
```

`space/sync.py` must run before either archive is built. The Space serves copies
of the specification and the records, and an archive built from stale copies
fails the gate inside the ancillary. The failure surfaces as a crosscheck
disagreement, because `crosscheck.py` reports Space drift as one of its rows.

`make_pdf.py` needs `pdflatex` on PATH. It compiles the paper twice at a fixed
epoch under `TZ=UTC`, refuses to write unless the two builds are byte-identical,
and refuses a PDF that carries a path, an address, a local timezone offset, or a
producer other than pdfTeX. The engine is not a detail: arXiv compiles with
pdflatex, which defaults to Computer Modern, while xelatex defaults to Latin
Modern — one source, two different papers.

`make_release.py` builds the bundle from a clean copy outside the repository, at
a fixed epoch, under the identity `mir <mir@localhost>`. It builds the bundle
twice and refuses to write it unless the two digests match, refuses if any staged
file names the author or the machine, refuses if the paper's PDF is older than
its `.tex` source, and refuses a PDF that would leak identity. It writes
`mir-1.bundle` and `mir-1.bundle.sha256` into `release/`, beside the repository's
`MIR/` directory; an `--out` inside `MIR/` is refused, because that is the
directory it stages and a bundle written there would be tracked by the next
build. `--remote` adds the locator check against the hosts.

## Mirrors

The same bundle digest should appear in more than one place. A single copy is not
a distribution; it is a file.

This section cannot hold the list. A URL written into this file changes the
bundle's bytes, and therefore the digest the mirror is supposed to match: the
list would invalidate the artifact it describes, once per edit. The live list,
with the date each copy was verified, is kept beside the release in
`release/MANIFEST.md`, which is not part of the bundle.

## If it is published to a code host

The bundle is a git repository, so a host that can serve it is the shortest
route from a file to something a search engine can index. Two fields decide
whether anyone arrives without being sent:

- **Description.** `Model Intervention Records: a conformance test for
  weight-space claims.`
- **Topics.** `weight-space-programming`, `model-intervention-records`,
  `model-editing`, `reproducibility`, `conformance-testing`,
  `evaluation-validity`.

The topics are the host's own index. A repository that omits them is reachable
only through its description, and a reader who has not been told the name has
nothing to search for. The first topic is the term current work uses for the
subject; the rest name what this document adds to it. No keyword is added to a
normative sentence to serve the index.

## If it does not verify

Do not use the copy. Record the digest you computed and where you got the file.
A distribution that cannot be checked is not a distribution.

Text CC BY 4.0, code Apache-2.0.
