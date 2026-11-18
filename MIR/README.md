# MIR-1 reference implementation

Validator and schema for MIR-1 (Model Intervention Records): a record format
for weight-space programming, in which a model's weights are read and edited
directly, without gradient descent or a training loop. A record states the
intervention, the behavior change, and the properties required not to change.
The validator runs on Python 3.8 or later with no third-party dependencies. The
full gate (`ci/check.py`) and the differential test need the toolchain the
pinned tables were cut with: Python 3.14 and Go 1.27.

The specification is in `../MIR-1-spec.md`. This repository is the reference
implementation of its section 7. There are two implementations, written from the
text in different languages: `validate.py` here, and `impl2/` in Go. A single
implementation is a project; two are the first evidence that the text, rather
than its author, specifies the format.

## Use

```
python3 validate.py examples/conforming.json
python3 validate.py examples/terse-run.json
python3 validate.py records/MIR-R1.json --verify-remote
python3 validate.py RECORD.json --json
```

Exit code is 0 when every check passes and 1 otherwise. The store a record uses
is found next to the record, at `artifacts/`, so a record travels with what it
cites.

## Structure

```
validate.py       checks C-01 through C-11
patchcheck.py     checks P-01 through P-05 for a Weight Patch (MIR-1.1)
patch-schema.json JSON Schema for the patch payload
adapter.py        builds a record from a run description, hashing local artifacts
adapters/         dspy-wsp run directory -> MIR-1.1 record + Weight Patch
registry.py       export, import, and verify a registry (MIR-1-09)
ci/               the whole verification, with the expected answer for each step
make_release.py   builds the release bundle from a clean, audited staging copy
schema.json       JSON Schema for the record
kernel.md         normative kernel, standalone (Appendix D), under 250 words
examples/         three synthetic records: a lineage root, one conforming,
                  one that fails C-05; falsify_example.py evaluates a claim
  patch/          two records on a tiny array container, and the two patches
                  they name; patch_selfcheck.py fails each P check in turn
records/          the worked example: a published intervention, re-recorded
  qualifier_selfcheck.py  each MIR-1.2 qualifier, present and absent
  MIR-R1.json     the record
  manifest.json   registry parameters, hashed as declared, byte for byte
  harness.json    the harness manifest, hashed as declared, byte for byte
  raw/            every source file the record cites, as published
  artifacts/      the store: digests, and two locators for the checkpoints
  NOTES.md        what each run measured, and the defects found
artifacts/        content-addressed store for the synthetic examples
impl2/            second implementation, in Go, from the same text
crosscheck.py     runs both implementations and diffs their reports
fuzzgen.py        random documents for the differential test
space/            the conformance test as a page and a JSON endpoint
paper/            the paper: markdown, LaTeX source, compiled PDF
  make_pdf.py     builds the PDF with pdflatex, reproducibly and in UTC
  make_arxiv.py   builds the two archives an arXiv submission needs
  SUBMISSION.md   the arXiv metadata and the one field that blocks it
```

## Checks

| ID | Meaning |
|---|---|
| C-01 | Parses; declared `id` matches the SHA-256 of its canonical bytes (§4.13) |
| C-02 | The record matches `schema.json`: required fields, types, enumerations, no undeclared fields |
| C-03 | Every hash resolves, as stored bytes or as a locator confirmed against its host |
| C-04 | Falsifier declared and returns a boolean |
| C-05 | At least one invariant `metric` outside `claim.scoring_metrics`; `behavior` declared inside it; valid `direction`; numeric bound |
| C-06 | Lineage resolves to a base artifact |
| C-07 | Cost and wall time disclosed as numbers on every run |
| C-08 | Manifest hash declared and resolves |
| C-09 | Export round-trips byte-identically and reproduces its results |
| C-10 | Status coherence: `replicated` carries the manifest's independent-run count by other operators with disclosed, differing funding sources; `submitted` and `replicated` carry lineage that resolves, `orphan` carries lineage that does not |
| C-11 | Every run reports `claim.behavior` as a number in its `result` |

When the `weights` payload declares `wpp_version`, the report carries a second
block, measured by MIR-1.1 (`../MIR-1.1-Patch.md`). It is reported beside the
eleven and never merged into them, so a record without a patch is unchanged.

| ID | Meaning |
|---|---|
| P-01 | `base.checkpoint_hash` resolves and equals the record's `base.hash` |
| P-02 | The patch conforms to the patch schema, `num_changed` is consistent where computable, and `id` matches its canonical form |
| P-03 | Every dependency is a conforming patch that appears earlier in the patch lineage, or is declared external |
| P-04 | The patch carries or references the record's invariant set and falsifier |
| P-05 | On a `wpp-array-0.1` base, applying the lineage and then the exact inverse restores bit-identical tensors, and the patch changes at least one weight |

`P-05` can be `NOT RUN`, which is not a pass: the base may be a real checkpoint
rather than an array container, the patch may carry no exact inverse, or an
ancestor may not apply. Three qualifiers — `patch-executable`, `stackable`,
`reversible` — are derived from the checks and are never declared by the record.

MIR-1.2 adds four record-level qualifiers, reported on one line and in one JSON
array, never stored in the record: `baseline-present`, `single-population`,
`unpriced-reproduction`, and `invariants-replicated`. None of them changes a
check, a status, or an `id`; `../MIR-1.2-Qualifiers.md` defines each one and
states what it does not mean.

```
python3 validate.py examples/patch/record-b.json
python3 examples/patch/patch_selfcheck.py
```

C-04 does not execute the falsifier unless `--execute-falsifier` is passed. A
record is untrusted input, and a validator that executes commands by default
cannot be run on untrusted input.

C-03 accepts two things under a digest: the bytes, or a locator named
`<digest>.locator.json` that declares the size and a URL. With `--verify-remote`
the validator asks the host for the digest in one request and transfers no
bytes, and the check line says whether it confirmed the locator or accepted it.
A validator that reports an unconfirmed locator as resolved is claiming more
than it measured.

## The worked example

`records/MIR-R1.json` re-records a published intervention: 131,072 weights of
Qwen3.5-0.8B changed to remove a reasoning loop, reported 2026-11-02. Four runs
by two operators, three invariants outside the declared scoring function, all satisfied,
and a falsifier that recomputes the claim from the per-sample observations the
operators published.

```
python3 validate.py records/MIR-R1.json
C-07 FAIL  4 of 4 runs declare cost or wall time as undisclosed
RESULT: FAIL (1 of 11)
```

The failure is the point. No run in the published bundle states a cost, so no
run counts toward any requirement, so the record cannot be `replicated` although
an independent operator rebuilt the checkpoint and reproduced the claim. The
requirement costs one number per run. C-10 gives a second, independent reason
the status cannot advance: the claimant's funding source is not disclosed, so no
run can be counted as independent of it.

`records/NOTES.md` records what each run measured, where every artifact came
from, and the defects the exercise found. `records/selfcheck.py` shows each
check failing when the condition it checks is removed.

## Two implementations

`impl2/` is a Go implementation written from the specification, sharing no code
with `validate.py`. Neither is the authority: the specification is. The test of
the text is that both programs reach the same verdict on the same bytes.

```
python3 crosscheck.py --fuzz 400
```

That builds the Go binary, runs both validators on every record, on seventeen
mutations of the worked example and three of the conforming fixture, and on
random documents, and diffs the reports byte for byte. It exits non-zero on a
single byte of disagreement. The random documents are half arbitrary JSON shapes
and half mutations of a conforming record, and the run ends with a coverage table
naming, per check, how many documents passed, how many failed, and how many
distinct messages it produced. Over 400 documents that is 190 messages; a corpus
of arbitrary shapes alone reaches one branch per check and measures agreement
about malformed input.

Writing it found a defect in this implementation. The canonical form in §4.13
allows a record to write a number without an exponent, but `validate.py` used a
general-purpose JSON encoder, which emits `1e+16` for a value whose canonical
form is `10000000000000000.0`. Two serializers that disagree produce two ids for
one record, and the id is the content address. Suite 1.5.0 writes the canonical
bytes itself, in both implementations. The worked example's id did not change,
because none of its numbers is affected. See `records/NOTES.md`, D-5.

The corpus itself was a defect, logged as D-11: it passed while reaching only one
branch per check. Four further defects are logged as D-12 through D-15 — text
handling that depended on the language's Unicode version, a check that coerced a
value of the wrong type into the right one, a report that depended on document
key order rather than on the canonical bytes, and an independence comparison that
folded funding sources but not operator names. Each now has a test that fails if
it returns.

The two implementations agree on every input in this repository. That is
evidence that the text is implementable. It is not evidence of implementer
independence: the same author wrote both.

## Build a record

`adapter.py` turns a run description into a record. An artifact may be given as
`{"file": "path"}` where a hash is expected; the adapter hashes the file, copies
the bytes into the store, and fills the digest.

```
python3 adapter.py --spec run.json --out records/NEW.json --store records/artifacts
```

It then runs the suite and prints the verdict. `--strict` refuses to write a
record that does not conform, which is the wrong default: a record that documents
a failure is still a record.

## Export a registry

MIR-1-09 requires that a registry be exportable in full, by one command, in a
format a third party can re-import and verify. `registry.py` is that command.

```
python3 registry.py export records registry.tar.gz
python3 registry.py import registry.tar.gz /tmp/registry
python3 registry.py verify /tmp/registry
```

The archive is deterministic: fixed member metadata, sorted names, no
timestamps. Verification hashes every artifact's bytes against the name it is
filed under, which the record-level suite does not do.

## Verify everything

```
python3 ci/check.py
```

Each step asserts the result it is supposed to produce, including the ones that
are supposed to fail. No network. The same command runs in CI.

## Run it as a service

`space/` serves the same validator as one page and one JSON endpoint, with no
dependencies beyond the standard library. It stores nothing.

```
python3 space/sync.py
PORT=7860 python3 space/app.py
curl -s -X POST --data-binary @records/MIR-R1.json \
  -H 'content-type: application/json' localhost:7860/api/validate
```

`space/sync.py --check` fails if the copies the Space serves have drifted from
this repository.

## Non-checks

The suite does not report on importance, novelty, evaluation quality, operator
reputation, model safety, or desirability. A suite that reports on them becomes
a rating, and a rating is a body with an interest. Aggregate scores are not
emitted for the same reason: an aggregate is optimized rather than satisfied.

## Conformance

There is no certification authority and no mark to license. Anyone may run the
suite against any record and publish the result. A claim of conformance is
itself a falsifiable claim and can be checked in minutes.

To check a conformance claim:

```
git clone <repo> && cd MIR
python3 validate.py <record.json> --verify-remote
```

If the claim is false, that command shows it.

## Rebuilding

```
python3 examples/build_examples.py     # synthetic examples
python3 records/build_record.py        # the worked example, from records/raw
python3 records/selfcheck.py           # each check, observed failing
python3 crosscheck.py                  # both implementations, same answer
python3 space/sync.py                  # refresh what the Space serves
```

All three generators are deterministic: running them again produces the same
bytes.

## License

Text CC BY 4.0. Code Apache-2.0. Forking is permitted and expected; a fork that
changes a requirement produces a new version identifier, not a modification of
this one.
