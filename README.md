# MIR-1 — Model Intervention Records

A conformance test for weight-space claims.

A claim that an intervention changed a model's behavior is currently not
comparable with another claim of the same kind: two reports can both be accurate
and still disagree about what happened, because neither record states what was
required not to change. MIR-1 specifies the fields such a claim must carry, and
a mechanical test that anyone may run on them without permission.

The format requires three things a report usually lacks: an executable
falsifier; an invariant set containing at least one metric the claim's own
scoring function does not observe; and content-addressed lineage to a base
checkpoint. The test checks those and eight other conditions, reports eleven
individual verdicts, and emits no aggregate score.

## What is here

| Path | |
|---|---|
| `MIR-1-spec.md` | The normative specification: fields, statuses, conformance procedures. |
| `MIR/` | The reference implementation, the worked example, and the paper. |
| `MIR/paper/mir-1.pdf` | Why the record is missing, what the test measures, and what it cannot. |

## Verify it

The validator runs on Python 3.8 or later. The full gate and the differential
test pin the toolchain the tables were cut with: Python 3.14 and Go 1.27.

```sh
cd MIR
python3 ci/check.py
```

The gate runs the validator against a conforming record, a record that must
fail, and the invariant fixture; runs both implementations on the same inputs;
runs the Go tests, the adapter, and the registry round trip; and asserts the
expected answer for each step.

One step is expected to fail. The worked example, `records/MIR-R1.json`, fails
exactly one check, on cost disclosure, because no run in the published bundle
states a cost. That failure is the paper's subject, not a defect in the example.

To check a single record:

```sh
cd MIR
python3 validate.py RECORD.json --verify-remote
```

## What it does not do

The suite does not report importance, novelty, evaluation quality, operator
reputation, model safety, or desirability. It does not verify that a claim is
true; it verifies that the claim is stated in a form another party can check.
Invariant bounds are declared, not evaluated. Section 10 of the specification
states the residual threats, including the ones left unmitigated.

## Status and license

Version 1.0, 14 November 2026. There is no certification authority and no mark
to license. Text CC BY 4.0; code Apache-2.0.
