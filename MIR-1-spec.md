# MIR-1 — Model Intervention Records

## Conformance Requirements and Test Suite

**Status:** Version 1.0.
**Date:** 2026-11-14
**Test suite:** 1.5.0
**License:** Text CC BY 4.0. Test suite Apache-2.0.
**Keywords:** weight-space programming; model intervention records; weight editing; conformance testing; reproducibility; evaluation validity

**Abstract.** This document specifies a record format and a mechanical conformance test for one class of claim: that an intervention applied to a base model produces a stated behavior change on a stated distribution without degrading stated invariants beyond stated bounds. The class is the one recent work calls weight-space programming: a model's weights read and edited directly, without gradient descent or a training loop. It defines what such a claim must carry in order to be comparable, and defines a test that anyone may run without permission. It does not define what a claim is worth.

---

## 1. Scope

This document specifies fields, statuses, and conformance procedures for a single claim form:

> Intervention *I*, applied to base artifact *B*, produces behavior *X* on distribution *D*, without degrading property *P* beyond bound *b*.

In scope: record format, required fields, conformance procedures, status transitions, export requirements.

Out of scope: whether *X* is desirable, whether *B* is safe, who may publish, how a registry is governed, which evaluation is good, and the unresolved question of what the correct unit of behavioral change is.

The out-of-scope list is fixed, not provisional. A document that takes a position on desirability becomes a political object, and political objects are cited selectively and abandoned when the politics shifts. A document that takes a position only on form can be adopted by parties who disagree about everything else. That is the only reason this one is expected to survive contact with them.

## 2. Motivation

On 2026-11-08 a public run reported an intervention that reduced response length. The scoring function measured length and correctness on the target set. The accepted intervention reduced mathematical accuracy from 80% to between 23% and 54%, and reduced GSM8K accuracy from 46% to 0%. At least one run began every mathematical response with a stray period.

Source: Beaker, public run `3230a4ea`, reported by Reza Nayebi, "Adventures in Weight-Space Programming with Beaker", 8 November 2026, https://www.withbeaker.ai/blog/weight-space-programming. The figures above are quoted from that report. The run is public at https://app.withbeaker.ai/public/runs/3230a4ea-512b-4a9f-b42a-4d271cca03fd.

Every statement in the published record was true. The measurement was accurate. The system was damaged.

The record format provided no field in which the author could state what must not change. This is a property of the format rather than of the author: when the scoring function defines what is observed, the record will describe exactly what was scored, and nothing else. The defect is reproducible by anyone who uses the same format, which is why adding a field is sufficient and exhortation is not.

The authors of the concept have since stated its scope more narrowly than it is often read. In a response added on 12 November 2026 they write that weight-space programming "is not a method" but "the name of an emerging concept", and that their experiments are "evidence for that statement, not a proposed method for editing or training networks". They also report "more than a hundred" replications, extensions, benchmarks, and applications known to them. That is the condition this document is written for. A concept with many independent reports and no shared record produces many claims that cannot be compared. What is missing is not a method specification but the record: the fields that let one report be checked against another without asking either author what they meant.

Source: Rikiya Takehi, Jayden Teoh, Alex Zhang, and Omar Khattab, "Sparks of Weight-Space Programming", 2 November 2026, "Response to Comments" added 12 November 2026, https://rikiyat.github.io/blog/weight-space-programming/.

## 3. Conventions

The key words MUST, MUST NOT, SHOULD, SHOULD NOT, and MAY are to be interpreted as described in RFC 2119.

"Content-addressed" means identified by a cryptographic hash of the exact bytes, in a stated serialization, with the hash algorithm named.

## 4. Terms

**4.1 Base artifact.** A model checkpoint, identified by the SHA-256 of its weight files in a stated serialization, with the retrieval location and the license under which it is available.

**4.2 Intervention.** A typed payload applied to a base artifact. Types in v1:

| Type | Payload |
|---|---|
| `weights` | Tensor deltas with indices, or a full modified checkpoint |
| `vector` | A steering vector with its application points and scaling |
| `harness` | A prompt, decoding configuration, or tool set, with no weight change |
| `other` | A description plus an executable reproduction command |

The type field is mandatory. The question of which unit is correct is unresolved, and a record that cannot state what it changed cannot be compared with another record. A record declaring `harness` is as valid as one declaring `weights`; the declaration is a measurement, not a ranking.

**4.3 Claim.** A tuple `{behavior, distribution, direction, threshold, scoring_metrics}`. The behavior MUST be defined operationally by the harness, and every run MUST report it as a number in its `result` (C-11). A behavior defined only in prose does not conform; neither does a behavior that no run reports.

**4.4 Falsifier.** An executable observation that would refute the claim. It MUST be a command, or a fully specified measurement, returning a boolean verdict. A falsifier expressed only in prose does not conform, regardless of its precision.

**4.5 Invariant set.** A list of `{property, measurement, metric, direction, bound}`. `metric` names the quantity the bound applies to. `direction` is one of `floor`, meaning the measured value MUST be at least the bound; `ceiling`, meaning it MUST be at most the bound; or `delta`, meaning the bound applies to the signed change from the base run: a positive bound permits a rise of at most that much, a negative bound permits a fall of at most its magnitude, and zero permits no change. The claim declares `scoring_metrics`, the set of metrics its scoring function observes, and `claim.behavior` MUST be one of them. The invariant set MUST contain at least one `metric` that is not in `scoring_metrics`. A record whose invariant set is a subset of its scoring function reproduces the failure described in section 2 while presenting all required fields as complete.

Conformance is checked on the declaration. The suite compares each invariant's `metric` against the declared `scoring_metrics`; it does not reconstruct the scoring function from the harness. A record that declares a metric outside the scoring function while scoring it is a false record, not a non-conforming one. What the comparison does prevent is the degenerate case: an invariant whose metric is the claim's own behavior is inside by construction, and no flag can place it outside. Section 10 states the limit that remains.

**4.6 Harness.** Code, data, seeds, environment, and versions, content-addressed as a single manifest hash.

**4.7 Run.** One execution. A run record carries `harness_hash`, `base_hash`, `intervention_hash`, `operator`, `funding_source`, `cost`, `wall_time_s`, `started_at`, and a `result` that declares `n_units` and `samples_per_unit`.

Within a run, three fields MAY be `null`, and only these three. `intervention_hash` is `null` in a **baseline run**, which measures the base artifact with no intervention applied; a record that claims a change without a baseline cannot state the change. `cost` and `wall_time_s` are `null` when the operator did not disclose them.

A `null` is a declaration and not an omission. The field is kept in the record so that a reader sees the author state the absence, rather than find the field missing and assume it was forgotten. It does not satisfy MIR-1-04.

`cost` MAY be zero: hardware already owned costs nothing per run. `wall_time_s` MUST be greater than zero, because a run that produced a result took time; a record that declares zero for both has disclosed nothing while appearing to satisfy a disclosure check.

`n_units` is the number of evaluation units measured, at least one, and `samples_per_unit` is the number of generations per unit, at least one. Two runs are comparable only when both agree. Comparability is not checked in v1: the suite confirms that every run states its population, not that two runs share one. A record may carry a smoke test next to a full run, and a reader can see which is which.

`result` is open. It MUST declare `n_units` and `samples_per_unit`, and it MUST report the claim's behavior as a number (C-11), but it MAY carry any other measurement. A run reports what it measured, and closing this object would require enumerating every metric a harness could produce. The consequence is stated rather than left to be discovered: the suite does not inspect the remaining fields, so a record can carry arbitrary content there. Every byte of it is content-addressed and visible to a reader, and no verdict depends on it.

**4.8 Record.** The bundle of 4.2 through 4.7 plus lineage, content-addressed. Immutable once its status leaves `draft`.

**4.9 Lineage.** A directed edge from a record to the record or records it was applied on top of, and from each of those to their parents, terminating at a base artifact.

A record applied directly to a base artifact has no parent records, and its `lineage` is the empty list. That is the root case and not a missing field: C-06 accepts an empty lineage when the record's own `base.hash` resolves, and fails it when it does not. An empty lineage whose base does not resolve is `orphan`.

A lineage entry MAY be written as `sha256:<digest>` or as the bare hexadecimal digest. Both spellings name the same content, and both are verified against it. The suite normalizes the bare form before resolving it, so the choice of spelling cannot be used to name a file whose bytes were never checked against their name.

**4.10 Operator and claimant.** An operator is the entity that executed a run. A claimant is the entity asserting the claim, recorded once at the record level as `{operator, funding_source}`. Operators MUST be distinguishable for the independence requirement of MIR-1-05, and the claimant is what a replication is measured against: without it, the strongest status would be available to any record that added a run. The mechanism of distinction is out of scope in v1; funding disclosure is the minimum.

A funding source is **disclosed** when it names something. The suite trims leading and trailing whitespace, applies Unicode full case folding, and compares the result against a fixed list of non-answers: the empty string, `not disclosed`, `undisclosed`, `not stated`, `unknown`, `none`, `n/a`, `na`, `null`, `anonymous`, `withheld`, `unattributed`. A value on that list is not a source, and neither is a value that is not a string. Two operators, or two funding sources, name the same entity when their trimmed and folded forms are equal. Case and surrounding whitespace are not identity: a claimant that signs an added run with its own name re-spelled has not produced an independent run.

The list is exact, and folding is not compatibility normalization. Fullwidth `Ｎｏｎｅ` folds to fullwidth `ｎｏｎｅ`, which is not on the list, and is therefore read as a disclosed source. The suite reports what the record declares. Deciding which spellings are evasions of the list is not a mechanical operation, and a rule that attempted it would be a rating; section 10 states the limit that remains.

Full case folding, the whitespace test, and the printability test used in report details are those of **Unicode 16.0.0**. The version is part of the rule, not an implementation detail: a later Unicode assigns code points an earlier one leaves unassigned, and two implementations folding under different versions decide independence differently for the same record. An implementation MUST pin these tables rather than inherit its language's current Unicode version, and SHOULD derive them from the reference implementation so that an upgrade on either side is a visible test failure rather than a silent divergence.

**4.11 Challenge.** A bonded assertion, with evidence, that a record's claim does not replicate. A bond is an amount, in a unit named by the registry manifest, posted by the challenger and forfeited to the record's operator if the challenge does not produce a refutation. The bond makes a challenge cost something; it does not make the challenge true.

**4.12 Locator.** A declared substitute for bytes too large to store, holding `{kind, sha256, size, url}` at the path `<sha256>.locator.json` in the artifact store. It resolves a hash only when its declared digest matches the name it is stored under, its size is stated, and its URL is retrievable. A validator MAY confirm the digest against the host without downloading the bytes.

A locator is not the artifact. It is the strongest claim about the artifact that can be checked without holding it, and a check that uses one MUST report whether it confirmed the claim against the host or accepted it.

**4.13 Canonical form.** The `id` of a record is the SHA-256 of its canonical bytes, where the record has been copied without the `id` member. Canonical bytes are UTF-8 JSON with the following properties:

- Object members are ordered by the code point of their names.
- No whitespace between tokens.
- Strings escape only `"`, `\`, and the control characters, which are written `\b`, `\f`, `\n`, `\r`, `\t` or `\u00xx` in lowercase hexadecimal. Every other character is written as UTF-8, including non-ASCII.
- A number written without a fraction or exponent is written as digits. A number written with either is written in plain decimal, without an exponent, with at least one digit after the point.
- `true`, `false`, and `null` are written as such.
- Nesting is bounded at 256 levels of arrays and objects. A document deeper than that does not parse, and the record fails C-01.

The bound is part of the rule rather than a defensive limit in one implementation. A recursive parser without a shared bound exhausts its stack on a document another parser accepts, so the two would disagree about whether the record exists at all.

The one case this fixes is not style. Two implementations that serialize the same value differently produce different ids for the same record, and a format whose identity depends on the serializer cannot be implemented twice. Canonical bytes never contain exponent notation: the exponent form and the plain form of the same value are different bytes, and only one of them can be the canonical form.

## 5. Requirements

**MIR-1-01 (Falsifier).** A record MUST carry an executable falsifier as defined in 4.4.

**MIR-1-02 (Invariants).** A record MUST carry an invariant set as defined in 4.5, each invariant naming a `metric`, a `direction`, and a numeric bound, and the set MUST contain at least one `metric` outside the claim's declared `scoring_metrics`.

**MIR-1-03 (Resolution).** All hashes MUST resolve to retrievable artifacts, as bytes in an artifact store or as a locator (4.12). An unresolvable hash is a conformance failure, not a pending item.

**MIR-1-04 (Cost).** Every run MUST disclose cost and wall time as numbers. A field declared `null` does not satisfy this requirement and the run fails C-07. An undisclosed run counts toward no requirement.

**MIR-1-05 (Independence).** The status `replicated` requires at least one run executed by an operator other than the claimant's, whose declared funding source is disclosed (4.10) and differs from the claimant's. A funding source that is not disclosed is not a source: independence cannot be established against it, and a record that declares one cannot be `replicated`. Two kinds of run do not count toward this requirement: a baseline run, which never applies the intervention (4.7), and a run that discloses neither cost nor wall time, which counts toward no requirement (MIR-1-04). The number of independent runs required is the registry's `min_independent_replications` parameter (section 8); the floor is one.

**MIR-1-06 (Lineage).** Lineage MUST resolve to a base artifact. An empty lineage resolves when the record's own `base` resolves, which is the root case of 4.9. A record with unresolvable lineage has status `orphan` and MUST NOT be `replicated`, irrespective of the number of runs it carries.

**MIR-1-07 (Harness retrieval).** A harness hash whose content a third party cannot retrieve does not conform. The common failure of reproducibility is not an incorrect hash. It is a correct hash to content that was never retained.

**MIR-1-08 (Immutability).** A record MUST NOT be edited after leaving `draft`. Corrections are new records carrying a `supersedes` edge. History is append-only.

**MIR-1-09 (Export).** A registry MUST be exportable in full, by one command, in a format that a third party can re-import and verify. A registry that cannot be exported does not conform irrespective of its contents.

MIR-1-09 is the exit requirement. A registry that cannot be left is not a shared record. It is a silo with a public address, and the difference between the two is the only structural protection this document provides to the people whose records it holds. A party that satisfies section 5 but not MIR-1-09 has built a product.

**MIR-1-10 (Manifest binding).** Every record MUST declare the hash of the registry manifest (section 8) under which it was created, so that a record is always read against the parameters that existed when it was made.

## 6. Status

Four statuses exist in v1, and each is determined by evidence the record carries:

| Status | Meaning | Checked by |
|---|---|---|
| `draft` | Unfinished. No claim is made. | Nothing; the suite accepts any draft. |
| `submitted` | The claim is published and its lineage resolves. | C-10 |
| `replicated` | An operator other than the claimant ran it, with a disclosed funding source that differs, as defined in MIR-1-05. | C-10 |
| `orphan` | The lineage does not resolve. | C-10 |

The status is therefore not a story the record tells about itself; it is a function of what the record contains. A record whose lineage does not resolve MUST be `orphan`, and a record whose lineage resolves MUST NOT be.

`replicated` does not mean true. It means the claim survived an attempt to refute it, and the number of attempts required is a registry parameter (section 8), not a property of the record. The status name is not `verified` for this reason; readers who treat `replicated` as `true` have misread the document, and no wording prevents that.

Three statuses a registry would normally hold are not in v1: `challenged`, `refuted`, and `expired`. Each requires an object the format does not define — a bond in a registry's unit, a verdict, a clock — and a status no check can test is a word. Section 11 excludes them explicitly rather than carrying them as decoration.

## 7. The conformance test

**7.1 Implementability.** The suite MUST be implementable from this document alone, within one working day, by an implementer with no access to the authors and no communication with them. A requirement that fails this condition is not in v1. This condition is the specification's own quality gate and is checked by the first independent implementation.

Two implementations exist as of suite version 1.5.0: `validate.py` in Python and `impl2/` in Go, written from this document and sharing no code. They produce identical reports, byte for byte, on every record and mutation in the repository and on a corpus of random documents. That is evidence that the text is implementable. It is not evidence of implementer independence, because the same author wrote both. The condition in the previous paragraph remains unmet until an implementation exists by someone with no access to the authors; the text is written so that this is possible within one working day. Writing the second implementation is what made §4.13 normative: two serializers that spell the same value differently produce two ids for one record.

**7.2 Mechanical checks.**

| ID | Check |
|---|---|
| C-01 | Record parses; the declared `id`, if present, matches the SHA-256 of its canonical bytes (§4.13) |
| C-02 | The record matches the schema in section 4: required fields, types, enumerations, and no field the schema does not declare |
| C-03 | Every hash resolves, as stored bytes or as a locator confirmed against its host |
| C-04 | Falsifier declared and executable; returns a boolean |
| C-05 | At least one invariant's `metric` is absent from `claim.scoring_metrics`; `claim.behavior` is present in it; every `direction` is `floor`, `ceiling`, or `delta`; every bound numeric |
| C-06 | Lineage resolves to a base artifact |
| C-07 | Cost and wall time disclosed as numbers on every run; `null` fails |
| C-08 | Manifest hash declared and resolvable |
| C-09 | Canonical round-trip: re-serialise, re-parse, re-run the suite, identical result |
| C-10 | Status coherence: `replicated` carries at least the manifest's independent-run count, by operators other than the claimant with disclosed and differing funding sources; `submitted` and `replicated` carry lineage that resolves, and `orphan` carries lineage that does not |
| C-11 | Every run reports `claim.behavior` as a number in its `result` |

C-09 is a round-trip of the record's own bytes. MIR-1-09, the export requirement, is a property of a registry rather than of a record, and no record-level check can establish it: the release exercises it with `registry.py`, which exports a registry, re-imports it, and verifies every byte.

C-02 is the schema. The suite loads `schema.json` and checks the record against it rather than restating the shape in code, because a second copy of the rules is a second place for them to drift; when `claimant` became required, both implementations kept their own lists and both kept the old one. A schema keyword the suite does not implement is a defect in the suite, and the tests fail on one rather than ignoring it.

A detail message MUST NOT depend on the order in which the record's members were written. Canonical form sorts member names, so document order is not a property of the record: two documents with the same canonical bytes are the same record. C-09 re-runs the suite on the re-serialised bytes, so a check that lists the fields it discovered in document order reports a different result after a round-trip that preserved everything, and C-09 fails on a record that conforms. A check that discovers fields by walking the record MUST order them by their path before reporting them.

A value of the wrong type is not coerced into the right one. `claim.behavior` is compared against `claim.scoring_metrics` as a string, and a behavior that is not a string is not among them. Coercing it to the empty string made a null behavior look scored against a set containing the empty string. C-02 rejects that set, but C-05 reported a pass on it, and a per-check verdict that is wrong on a malformed record is still wrong: the report, not the aggregate, is what a reader consumes.

**7.3 Non-checks.** The suite MUST NOT check importance, novelty, evaluation quality, operator reputation, model safety, or desirability. These are not mechanical. A suite that reports on them becomes a rating, and a rating is a body with an interest.

**7.4 Output.** One PASS or FAIL per check, plus a machine-readable report naming the suite version and the manifest hash. No aggregate score, because an aggregate score is optimized rather than satisfied.

**7.5 Machine-readable form.** The suite MUST accept records as JSON and MUST emit results as JSON. A compact normative kernel MUST be extractable from this document without loss, and MUST be published as a standalone file of under 250 words (Appendix D). The standalone file and Appendix D MUST carry the same words; the suite enforces the length limit, and a divergence between the two copies is a defect. Automated review tooling, including model-based review, may include the kernel in a context window without parsing the full text. The kernel is normative: where kernel and body differ, the body governs and the difference is a defect.

## 8. Parameters

Four values are governance rather than measurement:

1. Challenge window duration
2. Bond size
3. Minimum independent replications for `replicated`
4. Benchmark rotation period

They MUST be declared in the registry manifest and are the only values in this document decided by anything other than measurement.

Changing any of them MUST be a fork, not an edit. A silent parameter change retroactively invalidates prior records while leaving them appearing valid. The fork requirement makes the change visible in the lineage, where a reader can see that a record was made under different rules.

The replication count is the only one of the four the suite reads: C-10 takes it from the manifest the record declares. A manifest that cannot be read as bytes does not lower the threshold; C-10 fails instead, because a threshold nobody can read is not a declared parameter.

Truth is not among the parameters. Nothing here is decided by vote except these four values, and none of them alters what happened.

## 9. Conformance is permissionless

There is no certification authority, no membership, no revocation, and no mark to license. Anyone MAY run the suite against any record and publish the result.

A claim of conformance is itself a falsifiable claim, and it is cheap to falsify: the suite runs in minutes and its output is mechanical. An organization that adopts the vocabulary and fails the test can be shown to fail it by a stranger on a laptop, without asking anyone.

Three things are absent on purpose. A trademark creates a licensor, and a licensor is an owner. A foundation is a legal person with a board, a bank account, and a jurisdiction. A membership tier converts conformance into access, and access is the resource this document exists to distribute. Each of the three is a point at which the format can be acquired, and each is cheaper to omit now than to remove later.

## 10. Threat model

| Threat | Mitigation in this document | Residual |
|---|---|---|
| Sybil replication: one operator, many keys | Funding disclosure (MIR-1-04, MIR-1-05) | High, not solved |
| A funding non-answer re-spelled to escape the list, in fullwidth characters or with added punctuation | The exact list of 4.10, after trimming and full case folding | Unmitigated: deciding which spellings are evasions is not mechanical |
| Evaluation capture: harness tuned to pass | Invariant set (MIR-1-02), rotation (section 8), challenge | Medium |
| Record spam | Cost of a run (MIR-1-04) | Low |
| Registry capture: one body becomes default | Export (MIR-1-09), fork right, multiple implementations | Medium |
| Silent parameter change | Fork rule (section 8) | Low |
| Harness decay: links rot, code disappears | MIR-1-07 | Medium |
| Two runs over different populations presented as a comparison | `n_units` and `samples_per_unit` on every run (4.7) | Medium: the difference is visible, not prevented |
| A record whose payload is its own base | None in v1 | Unmitigated (D-6) |
| A construction presented as an edit | None in v1 | Out of scope; not expressible (§11) |
| False declaration of a field (cost, operator, funding source, or the membership of a metric in the scoring function) | None | Unmitigated: the suite checks presence, type, and membership as declared, not truth |
| Arbitrary content carried in a run's `result` | The object is open by design (4.7), and every byte is content-addressed | Low: visible to a reader, and no verdict depends on it |
| A status declared without the evidence its definition requires | C-10 for all four statuses | None in v1: the statuses a check cannot test are excluded (section 11) |
| A well-funded actor holding the only credible evaluations | None | Unmitigated |

The final row is included because a threat model that lists only mitigated threats is a prospectus. A party with the resources to run the only credible evaluations can satisfy every requirement in this document while controlling what counts as evidence. The specification does not fix this. It requires that the evaluations be named, hashed, and retrievable, which makes the control observable without making it removable.

## 11. Out of scope, explicitly

Alignment. Safety certification. Desirability. Registry governance. The unit question. Enforcement. Liability.

Three further exclusions are stated here because they were found by testing the format against published artifacts rather than by design.

**Constructions.** A record describes an edit: `base.hash` is required and MUST resolve (C-06). An intervention that builds a model without a parent checkpoint — weights written directly, no training, no base to edit — has no value for that field, and inventing one would make the record assert a lineage that does not exist. Such work is out of scope in v1. It is not rejected; it is simply not expressible, and a reader who tries will find that out at `base`.

**Derivation.** The lineage edge is declared, not computed. Every hash must resolve, but no check asks whether the payload was derived from the base, or whether it differs from it. A record whose payload is the base itself, with an unchanged claim, fails nothing that an honest record passes (D-6 in `MIR/records/NOTES.md`, reproducible with `records/selfcheck.py`). Deciding derivation requires the base bytes and a definition of "derived", which is a larger requirement than resolving a hash, and it is not attempted in v1.

**Challenge, refutation, expiry.** v1 defines four statuses and no others. `challenged`, `refuted`, and `expired` would each require an object the format does not define: a bond denominated in a registry's unit, a verdict, a clock. A registry may hold those events outside the record; the record does not carry them. A status that no check can test is a word, and the vocabulary is restricted to what the evidence determines.

Adopting this format does not make a model safer. A document that implied otherwise would be making a claim its own test cannot check, and the format's function depends on its claims being checkable.

## 12. The falsifier of this specification

> **Window: eighteen months from the first public release of suite version 1.5.0.**
>
> If, at the end of that window, no venue, laboratory, or registry has adopted the format, then the record format is not the binding constraint. The effort SHOULD then move to interface attestation (compute, energy, laboratory, payment), where the constraint is physical rather than editorial.
>
> If an independent implementation --- one written by someone with no access to the authors --- exists at that point, the conclusion is about adoption. If none exists, the conclusion is about 7.1 instead: a text that nobody outside its authors has implemented in eighteen months has not shown that it is implementable from the text alone, and the two implementations in this repository are evidence about their author rather than about the document.

This condition is stated so that the document can fail on evidence rather than on attrition. A specification without a stated failure condition is maintained by whoever benefits from its existence. A window without a number is not a stated window, and a condition that waits on an event with no deadline of its own can be postponed forever by waiting for it. Both branches above therefore end at the same date, and neither can be deferred by the absence of the other.

## 13. Minimal viable implementation

| Deliverable | Where |
|---|---|
| JSON schema for the record (section 4) | `schema.json` |
| Validator implementing C-01 through C-11 | `validate.py`, `impl2/` |
| Adapter that wraps an existing run and emits a record | `adapter.py` |
| Export command and import command | `registry.py` |
| One worked example: a published intervention re-recorded | `records/MIR-R1.json` |
| A signed, append-only ledger file | Not in this release |

The ledger is the one deliverable this release does not carry, and it is left out rather than half-built. MIR-1-08 requires history to be append-only, and a registry of content-addressed records satisfies that without a separate ledger: a record cannot be edited without changing its id, and an export is a snapshot whose digest names it. What a ledger adds is a signed sequence --- who submitted what, in what order --- which is a registry-level decision, not a record-level one. A registry that keeps one does not violate this document; a release that shipped a ledger it had not tested would.

Constraints: one person, one week, one consumer GPU, no service dependencies. An implementation requiring a server is not v1.

## 14. Versioning

Append-only. A change that breaks existing records produces MIR-2. Records remain valid under the version they were created with, and a registry MUST retain the ability to validate every version it has ever accepted.

The document's version and the suite's version are independent. The document numbers its requirements; the suite numbers the code that checks them. A validator that reports `suite 1.5.0` conforms to this document, version 1.0.

This document was amended five times before its first publication, each time before any record existed outside this release, so the rule above was not engaged. First, `claim.scoring_metrics`, `invariant.metric`, and `invariant.direction` replaced a boolean field in the invariant record. Second, `claimant` became a required record-level field and C-10 was added. Third, C-11 was added, the status vocabulary was reduced to the four statuses a check can test, and `wall_time_s` acquired a lower bound. Each of those three alters the canonical bytes and therefore the `id` of every record. Fourth, the independence comparison was pinned to trimming and Unicode full case folding for operators as well as funding sources, the list of funding non-answers was fixed, the nesting bound of 4.13 was stated, and 7.2 required the report to be a function of the canonical bytes rather than of document order. The fourth changes which records conform and what a report says, but not the canonical bytes, so no `id` moves. Fifth, section 2 gained a paragraph recording the authors' 12 November 2026 statement that weight-space programming is a concept rather than a method. The fifth adds no requirement and changes no canonical byte. After first publication this rule applies without exception.

---

## Appendix A — the intervention of section 2, re-recorded

| Field | As published | Under MIR-1 |
|---|---|---|
| Intervention type | implied `weights` | declared `weights` |
| Claim | "shorter responses" | `{behavior: mean_tokens, distribution: D, direction: decrease, threshold: t, scoring_metrics: [mean_tokens]}` |
| Falsifier | none | re-run on held-out set; refuted if mean tokens ≥ t |
| Invariant set | absent | `{metric: math_accuracy, direction: delta, bound: -0.05}`, `{metric: gsm8k_accuracy, direction: delta, bound: -0.05}`, `{metric: format, direction: ceiling, bound: 0}` |
| Conformance | not applicable | FAIL at MIR-1-02 and C-05 |

The intervention was found, scored, accepted, and published correctly under the rules that existed. The rules did not contain the field that would have stopped it. No claim about anyone's intentions is required to reach that conclusion, and none is made here.

## Appendix B — adjacent work

| Format | Domain | Borrowed here |
|---|---|---|
| CONSORT | Clinical trials | Checklist as a gate, enforced by venues rather than an authority |
| MIQE | Quantitative PCR | Minimum information before a claim is reportable |
| SLSA | Software supply chain | Attestation of what went into an artifact |
| Model Cards, Datasheets | Models, datasets | Structured disclosure of a thing |

The difference from all four is the object. This format describes an intervention, which has a parent, rather than an artifact. A model card states what a model is. This states what someone did to it, what followed, and what was required not to follow.

## Appendix C — schema sketch

```json
{
  "mir_version": "1",
  "manifest_hash": "sha256:...",
  "id": "sha256:...",
  "base": {"hash": "sha256:...", "location": "...", "license": "..."},
  "intervention": {"type": "weights|vector|harness|other", "payload_hash": "sha256:..."},
  "claimant": {"operator": "...", "funding_source": "..."},
  "claim": {"behavior": "...", "distribution": "...", "direction": "increase|decrease", "threshold": 0, "scoring_metrics": ["..."]},
  "falsifier": {"command": "...", "returns": "boolean"},
  "invariants": [{"property": "...", "measurement": "...", "metric": "...", "direction": "floor|ceiling|delta", "bound": 0}],
  "harness": {"hash": "sha256:...", "location": "..."},
  "runs": [{"operator": "...", "funding_source": "...", "cost": null, "wall_time_s": 0,
            "started_at": "...", "harness_hash": "sha256:...", "base_hash": "sha256:...",
            "intervention_hash": null,
            "result": {"n_units": 500, "samples_per_unit": 4, "<behavior>": 0}}],
  "lineage": ["sha256:..."],
  "supersedes": null,
  "status": "draft|submitted|replicated|orphan"
}
```

## Appendix D — normative kernel

This section is intended for inclusion in automated review pipelines and in the context window of model-based review systems, as provided in 7.5.

> A claim that an intervention changes a model's behavior is, in current practice,
> unfalsifiable, because the record of the claim does not state what must not
> change. A conforming record carries three mandatory parts: a declared falsifier
> that returns a boolean; an invariant set with at least one metric outside the
> claim's own declared scoring function; and content-addressed lineage to a base
> artifact. Omitting any of the three does not conform, whatever result is reported.
>
> Every run reports the claim's metric as a number, and states its cost and
> duration or declares them undisclosed. The record names the claimant and carries
> a status its evidence supports: broken lineage is orphan; replicated requires
> independent runs by other operators, with disclosed funding differing from the
> claimant's.
>
> Conformance is mechanical and permissionless: anyone may run the suite against
> any record and publish the outcome, and no body may certify, license, or revoke
> it. Four parameters are declared in the registry manifest (challenge window,
> bond size, replication count, benchmark rotation) and may be changed only by
> forking it; the suite reads the replication count. Replication is an independent
> run, not truth.

---

## Appendix E — the reference record

`records/MIR-R1.json` re-records a published intervention: 131,072 weights of Qwen3.5-0.8B changed to remove a reasoning loop, reported 2026-11-02. It is the worked example required by section 13.

| Line | Result |
|---|---|
| C-01 to C-11 | 10 pass; C-07 fails |
| Runs | 4, by 2 operators declaring 2 funding sources |
| Claimant | MIT CSAIL; funding source not disclosed |
| Invariants | 3, all outside the declared scoring function, all satisfied |
| Status | `submitted` |

The failure is MIR-1-04. No run in the published bundle states a cost, so no run counts toward any requirement, and the record cannot be `replicated` although an independent operator rebuilt the checkpoint and re-ran the evaluation to a number inside the claim. This is the requirement behaving as written. It is also the reason cost disclosure is the first item a laboratory can adopt on its own: it is one number per run.

Two requirements now block the same status, and the second is the one this record cannot argue past. C-10 asks for a disclosed claimant funding source and a run by a different operator with a disclosed source that differs. The claimant's source is not disclosed, and the rebuild's source is the operator's employer rather than a separate fund, so no run counts as independent. The record would fail C-10 if it declared `replicated`; it declares `submitted`, which is what the evidence supports.

The record exposes a defect this version does not fix. Two files in the model repository are named for the same distribution and measure 25 and 500 problems. The model card states that the first is a smoke test; the file name does not, and neither file carries a population. `n_units` puts the difference inside the record. It does not stop a reader from comparing the two, and section 4.7 says why the suite cannot.

---

*End of MIR-1, version 1.*
