# MIR-1.2 — Record Qualifiers

## Report-Only Refinements of MIR-1

**Status:** Version 1.2. Companion to MIR-1, version 1.0.
**Date:** 2026-11-18
**Test suite:** 1.7.0
**License:** Text CC BY 4.0. Test suite Apache-2.0.
**Keywords:** model intervention records; conformance testing; replication; evaluation validity; reproducibility

**Abstract.** MIR-1 reports four statuses and eleven checks, and neither vocabulary is allowed to grow a word a check cannot test. Some evidence a record carries is nevertheless worth naming: whether a baseline run exists, whether every run measured one population, whether another operator reproduced the claim without disclosing a cost, and whether the invariants were re-measured rather than only the target metric. This companion defines four **qualifiers** that a report derives from that evidence. A qualifier never changes a check, a status, or an identifier. It states what the record carries, so that a reader does not have to recompute it and does not have to infer it from a status that is deliberately narrower.

---

## 1. Scope

In scope: four derived qualifiers, their mechanical definitions, and their report form.

Out of scope, unchanged from MIR-1: whether a claim is true, whether a change is desirable, and whether a record is important. Also out of scope: any qualifier that requires evaluating a bound, grading a replication, or judging an author.

This document adds no member to a record and no condition to conformance. A record that carries no qualifier is as conforming as one that carries four. The record's canonical bytes and its `id` are unaffected.

## 2. Why qualifiers and not checks

MIR-1 §6 states the rule: a status is a function of the evidence the record carries, and a status no check can test is a word. The four properties here are testable, so the rule does not forbid making them checks. Two other requirements do.

First, §14: a change that makes an existing record fail produces MIR-2. Requiring every record to carry a baseline, or every replication to re-measure every invariant, would retroactively invalidate records that were conforming when they were made, including the worked example. Second, §7.3 and §6: a suite that grades a record becomes a rating, and a rating is a body with an interest. "This record measured two populations" is a measurement. "This record is worse because it measured two populations" is a rating, and MIR-1 does not do that.

A qualifier therefore refines what a reader sees without moving the verdict. It is the pressure-release valve between the format's promise that statuses mean something and the fact that more evidence can always be named.

## 3. Definitions

**3.1 Counted run.** A run that counts toward independence under MIR-1-05: it is not a baseline (`intervention_hash` is not `null`), it discloses cost and wall time as numbers (MIR-1-04), its operator differs from the claimant's after trimming and Unicode full case folding, and its funding source is disclosed and differs from the claimant's by the same comparison. This is the set C-10 counts. It is restated here because two qualifiers are defined over it.

**3.2 `baseline-present`.** Emitted when at least one run carries `intervention_hash: null`.

**3.3 `single-population`.** Emitted when the record has at least one run, every run reports `n_units` and `samples_per_unit` as integers, and every run reports the same pair.

**3.4 `unpriced-reproduction`.** Emitted when the claimant's `operator` is a string that names something, and at least one run is not a baseline, has an operator that differs from the claimant's after trimming and full case folding, does not disclose cost or wall time as numbers, and reports `claim.behavior` as a number in its `result`.

**3.5 `invariants-replicated`.** Emitted when at least one counted run reports a number in its `result` for every `metric` named by the record's invariant set.

## 4. What each qualifier does not mean

| Qualifier | It does not mean |
|---|---|
| `baseline-present` | That the baseline matches the intervention in population or harness. It means a baseline run is declared. |
| `single-population` | That a smoke test beside a full run is forbidden, or that a record without the qualifier compared two populations. MIR-1 §4.7 permits a smoke test next to a full run; the qualifier only says the record does not have one. |
| `unpriced-reproduction` | That the claim was replicated. The run is exactly the one MIR-1-04 excludes from counting. The qualifier makes the rebuild visible; it does not promote it. |
| `invariants-replicated` | That the bounds were satisfied. The suite reads presence of a number, not its value; MIR-1 declares bounds and does not evaluate them. |

A qualifier is a measurement of the record, not of the claim, and none of the four is evidence that the claim is true.

## 5. Report form

A report carries one array, `qualifiers`, naming each qualifier the record earns, in the order this document defines them. The array is omitted when empty. The text report prints the same names on one line:

```
record qualifiers   baseline-present, unpriced-reproduction
```

The JSON form is:

```json
"qualifiers": ["baseline-present", "unpriced-reproduction"]
```

The order is fixed so that two implementations produce the same bytes, and so that a diff between two reports is a diff of content rather than of iteration order. A suite version that adds a qualifier adds it at the end of the list.

## 6. Backward Compatibility

Every valid MIR-1 record remains valid. A report produced by an earlier suite version is a report under that version; nothing here changes a verdict, an exit code, or a canonical byte. A record's `id` is unchanged by the presence or absence of a qualifier, because the qualifier is derived from the record and never stored in it.

## 7. Residual Limits

- **Presence is not truth.** A run that declares `cost: 4.0` without measuring it earns `invariants-replicated` if its `result` carries the numbers. MIR-1's false-declaration limit is unchanged.
- **The set is not a score.** Four qualifiers are not better than one. Counting them, ranking records by them, or aggregating them into a number is the practice MIR-1 §7.3 excludes, and this document does not license it.
- **`single-population` is coarse.** Two runs of 500 units can sample different questions. The qualifier compares declared populations, which is what the format records; it does not compare their contents.
- **`invariants-replicated` is not a per-invariant verdict.** One counted run that reports all the numbers earns it, even if a different run reported some of them and a third reported none.

---

*End of MIR-1.2, version 1.*
