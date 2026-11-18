# MIR-1 — Model Intervention Records

A conformance test for weight-space claims.

Claims that an intervention changed a model's behavior are not comparable. Two
reports can both be accurate and still disagree about what happened, because
neither record states what was required not to change. The paper documents a
public run on 2026-11-08 in which an accepted intervention cut response length,
and also cut mathematical accuracy from 80% to between 23% and 54% and GSM8K
accuracy from 46% to 0%, while every statement in the published record remained
true. MIR-1 specifies the fields such a claim must carry, and a mechanical test
anyone may run on them without permission.

Read the paper first:
[Model Intervention Records: A Conformance Test for Weight-Space Claims](MIR/paper/mir-1.pdf)
— PDF, 10 pages. What was added after it was published is in the
[addendum](MIR/paper/mir-1-addendum.pdf) — 3 pages.

## Start here

| Entry point | What it is |
|---|---|
| [The specification](MIR-1-spec.md) | The normative record format and the eleven checks. |
| [Weight patches](MIR-1.1-Patch.md) | The companion: a composable payload for `weights`, and five more checks. |
| [Record qualifiers](MIR-1.2-Qualifiers.md) | The companion: four report-only refinements of the evidence. |
| [The worked example](MIR/records/MIR-R1.json) | A published intervention re-recorded; one check fails. |
| [The implementation](MIR/README.md) | Both validators, the adapter, the registry, the service. |
| [The dspy-wsp adapter](MIR/adapters/README.md) | A run directory becomes a record and a patch, with cost captured. |
| [Citation metadata](CITATION.cff) | `CITATION.cff`, under the collective identity. |
| [The gate](MIR/ci/check.py) | Every expected answer, asserted in one command. |

## What a record carries

Three fields a report usually lacks:

- An executable falsifier: a program that recomputes the claim from the
  published observations and returns a boolean.
- An invariant set with at least one metric outside the claim's own scoring
  function, so a side effect the score cannot see has somewhere to appear.
- Content-addressed lineage to a base checkpoint, so the record names the
  weights it started from by their bytes.

Eight further checks cover identity, schema, hash resolution, cost disclosure,
the manifest hash, the export round-trip, status coherence, and the reported
behavior. The suite reports eleven individual verdicts and emits no aggregate
score.

A `weights` payload may also be a Weight Patch (MIR-1.1): a compact,
content-addressed edit that can be stacked and reversed. The payload is
measured by five further checks, P-01 to P-05, in a separate block; the eleven
are not renumbered, and a record without a patch is still eleven checks.

## Verify it

The validator runs on Python 3.8 or later, with no third-party dependencies.
The full gate and the differential test pin the toolchain the tables were cut
with: Python 3.14 and Go 1.27.

```sh
cd MIR
python3 ci/check.py
```

The gate runs the validator against a conforming record, a record that must
fail, and the invariant fixture; runs both implementations on the same inputs;
runs the Go tests, the adapter, and the registry round trip; and asserts the
expected answer for each step.

One step is expected to fail. The worked example, `MIR/records/MIR-R1.json`,
fails exactly one check, on cost disclosure, because no run in the published
bundle states a cost. That failure is the paper's subject, not a defect in the
example.

To check a single record:

```sh
cd MIR
python3 validate.py RECORD.json --verify-remote
```

## The worked example

`MIR/records/MIR-R1.json` re-records a published intervention from 2026-11-02:
131,072 weights of Qwen3.5-0.8B, 0.017% of the model, changed by subtracting one
direction from 64 output columns in two layers. Four runs by two operators,
three invariants outside the declared scoring function, all satisfied, and a
falsifier that recomputes the claim from the per-sample observations the
operators published.

No run states a cost, so no run counts toward any requirement, so the record
cannot be `replicated` — although an independent operator rebuilt the
checkpoint and reproduced the claim. The requirement costs one number per run.
`MIR/records/NOTES.md` records what each run measured, where every artifact came
from, and the defects the exercise found.

## What is here

| Path | What it is |
|---|---|
| `MIR-1-spec.md` | The normative specification: the format, the eleven checks, the threat model. |
| `MIR-1.1-Patch.md` | The companion: Weight Patches, composition, inverses, and P-01 to P-05. |
| `MIR-1.2-Qualifiers.md` | The companion: baseline, population, unpriced reproduction, and invariant re-measurement. |
| `MIR/` | The reference implementation, both validators, the worked example, the paper source. |
| `MIR/paper/mir-1.pdf` | The paper, 10 pages. |
| `MIR/records/MIR-R1.json` | The worked example, as a record. |
| `MIR/records/NOTES.md` | What each run measured, and the defects the exercise found. |
| `MIR/README.md` | The implementation in detail: each check, both languages, the adapter, the registry, the service. |

## What it does not do

The suite does not report importance, novelty, evaluation quality, operator
reputation, model safety, or desirability. It does not verify that a claim is
true; it verifies that the claim is stated in a form another party can check.
Invariant bounds are declared, not evaluated. Section 10 of the specification
states the residual threats, including the ones left unmitigated.

## Cite

`CITATION.cff` carries the citation metadata, under the collective identity the
release is published with. The paper is the citable description of the format:
*Model Intervention Records: A Conformance Test for Weight-Space Claims*,
version 1.0, 2026. The document version (1.0) and the test-suite version (1.7.0)
are independent; the validator prints the suite version on its first line.

## Status and license

Version 1.0, with companions 1.1 and 1.2, 18 November 2026. Test suite 1.7.0. There is no certification
authority and no mark to license; anyone may run the suite against any record
and publish the result.

The specification, the paper, and the records are CC BY 4.0
(`LICENSE-CC-BY-4.0`). The code is Apache-2.0 (`LICENSE`).
