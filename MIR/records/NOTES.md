# The worked example, and what it found

`MIR-R1.json` re-records a published weight edit under MIR-1. This file records
what each run measured, where every artifact came from, and the defects the
exercise exposed. The record is the normative object; this file is the audit
trail behind it.

## The intervention

On 2026-11-02 a group at MIT CSAIL reported that an LLM, working in a Python
session over the weights with a budget of 50 forward passes and no gradients,
traced a reasoning loop in Qwen3.5-0.8B to one direction written by the MLPs of
layers 15 and 19, and subtracted it from 64 output columns of `down_proj` in
each. 131,072 weights change, 0.016% of the model. A second operator rebuilt the
checkpoint from the published bit-exact diff and re-ran the evaluation.

Nothing in this record was produced by the authors of this specification. Every
number is read from a file the operators published, copied byte for byte into
`raw/`.

## Runs

| # | Operator | Checkpoint | Problems | Samples | MATH-500 | Cut at limit | Wall time | Cost |
|---|---|---|---|---|---|---|---|---|
| 0 | Hugging Face (rebuild) | base | 25 | 4 | 0.050 | 0.950 | not disclosed | not disclosed |
| 1 | MIT CSAIL | base | 500 | 4 | 0.079 | 0.930 | not disclosed | not disclosed |
| 2 | MIT CSAIL | edited | 500 | 4 | 0.481 | 0.331 | not disclosed | not disclosed |
| 3 | Hugging Face (rebuild) | edited | 500 | 4 | 0.510 | 0.316 | 3059 s | not disclosed |

Run 3 is the only run that publishes per-problem observations, so it is the only
one the falsifier can recompute. It recomputes to 0.5100 from 2,000 correct/incorrect
flags, which is what the record states.

The three invariants declared in the record are satisfied by run 2: cut-at-limit
falls rather than rises, GSM8K goes from 0.138 to 0.671, and IFEval from 0.210 to
0.623. The edit removed a loop, and removing the loop helped every measurement in
the bundle. This record therefore demonstrates conformance, not refutation. The
example in `examples/terse-run.json` is the one that fails.

## Provenance

All files were retrieved on 2026-11-12 and are stored in `raw/` unchanged. The
digest of each is its entry in `artifacts/`.

| File | sha256 | Source |
|---|---|---|
| `README-model.md` | `cc464ae3…4dd5a3` | model card, `RikiyaT/Qwen3.5-0.8B-weight-space-programming` |
| `scores_edited_math500.json` | `17c14674…dfdc0c` | same repository, `eval/` |
| `scores_base_math500.json` | `205171ff…ee2cf` | same repository, `eval/` |
| `README-exp8.md` | `473e386a…edcbbd` | `RikiyaT/lm_understand-logs`, `exp8_math/`, commit `4d09ba6` |
| `RESULTS_excerpt.md` | `5f4e24a4…a4881` | same repository, `exp8_math/eval/` |
| `log_unedited_merged.json` | `5c313704…10221` | same repository, `exp8_math/eval/unedited/merged.json` |
| `log_p50c_merged.json` | `c93d3db3…0471` | same repository, `exp8_math/eval/p50c/merged.json` |
| `evaluate.py` | `c93f477c…2035d` | same repository, `exp8_math/code/` |
| `build_ckpt.py` | `da0759bd…217db` | same repository, `exp8_math/code/` |
| `apply_edit.py` | `d2b627a6…1b1c5d` | same repository, `exp8_math/code/` |

The two checkpoints are held as locators, not as bytes: 1,746,942,600 and
1,746,943,032 bytes.

The model repository also publishes `samples_base_math500.jsonl` and
`samples_edited_math500.jsonl`: 9.4 MB of generated text, 20 samples each, across
the same 5 problems. No field in the record cites them, so they are neither
stored here nor hashed, and they remain reachable at the source above. They are
a sample of a sample: 20 records for a measurement the run reports as 2,000. `validate.py --verify-remote` confirms both against the host
in one request each.

## Defects found

**D-1. Two populations under one distribution name.** The model repository's
`eval/` holds `scores_base_math500.json`, measured over 25 problems, next to
`scores_edited_math500.json`, measured over 500. The model card states that the
first is a smoke test; the file name does not, and neither file carries a
population. A reader who takes the obvious path computes 5.0% against 51.0%. The
full baseline is in the log repository under a different commit, and the two
repositories are not linked by any field.

`n_units` and `samples_per_unit` were added to the run record because of this.
They make the difference visible inside the record. They do not prevent the
comparison, and version 1 checks only that every run states its population, not
that two runs share one. Recorded in the paper, section 5.

**D-2. The harness hash does not cover the data.** `evaluate.py` calls
`load_dataset("HuggingFaceH4/MATH-500", split="test")` without a revision. The
harness manifest states this, and the hash covers the code and not the data. A
record can conform and still be tied to a distribution that has since changed.

**D-3. Invariant bounds are declared, not evaluated.** A `floor`, `ceiling`, or
`delta` says how to read the number; nothing computes whether the number held.
The suite checks that a bound exists, that it is numeric, that its direction is
one of the three, and that at least one invariant's metric lies outside the
declared scoring function. Satisfaction is a claim the record makes, and a
reader who wants it must run the harness the record names. A direction field was
added before first publication; it fixed how a bound is read, not whether it is
checked.

**D-4. No run states a cost.** This is the one that fails C-07. The model card
gives the hardware and the wall time of one run, from which a reader can compute
a machine-hour price. The record does not contain it, and MIR-1-04 asks the
record, not the reader. Under the specification an undisclosed run counts toward
no requirement, so the record is `submitted` and cannot be `replicated`, even
though the replication happened and is documented.

**D-5. The canonical form did not match the serializer.** The id of a record is
a hash of its canonical bytes, and the first implementation produced those bytes
with a general-purpose JSON serializer. That serializer writes exponent
notation for values at or above 10^16 and below 10^-4, while a conforming record
may write the same value without an exponent. The specification says the
exponent form does not conform, so the implementation was wrong and the rule was
under-described: it said what canonical bytes are not, not how a fractional
value is written. Found by writing the second implementation in Go from the
text, fixed in suite 1.2.0 in both implementations, and the record's id did not
change because none of its numbers is large or small enough to be affected. The
general lesson is in the paper, section 4: a format whose identity depends on a
serializer cannot be implemented twice.

**D-6. Lineage is declared, not computed.** The suite asks whether every hash
resolves. It does not ask whether the payload was derived from the base, or even
whether the payload differs from it. `selfcheck.py` now carries the case: set
`intervention.payload_hash` equal to `base.hash` and keep the claim, and the
record fails exactly the same check as the honest one, C-07 and nothing else. A
record can therefore assert that it edited a checkpoint into something else while
the "something else" is the checkpoint. Found by asking what the newest published
intervention class would look like as a record, and not by any failing test,
because no test can fail on it. This is not fixed in v1: deciding whether a
payload is an edit of a base requires the base bytes and a statement of what
counts as derived, which is a different and much larger requirement than
resolving a hash. It is listed here because a record format whose central edge
is unverified should say so where its users can read it.

**D-7. A construction cannot be typed.** MIR-1 assumes an intervention on a base
artifact: `base.hash` is required, and C-06 requires it to resolve. A published
line of work now builds a model by writing its weights directly in code, with no
parent checkpoint at all (`Interpretable Weight-Space Programming`, November
2026). Such a run has everything else the format wants, including, in
`metadata.json`, the two numbers C-07 demands: `cost_usd` and `seconds`, per
session, published for every run in the repository. What it does not have is a
base, so it cannot be written as a record without inventing one. The honest
consequence is a scope statement rather than a patch: v1 records edits, and a
construction is not an edit. Whether v2 should add an `origin: constructed` root
with the generating program as its content address is an open question, and the
answer depends on whether that class of artifact stays.

**D-8. C-05 compares one declaration against another.** The suite decides whether
an invariant is outside the scoring function by comparing `invariant.metric`
against `claim.scoring_metrics`. It never sees the harness, so it cannot know
which metrics the scoring function actually uses. The degenerate case is closed:
an invariant whose metric is `claim.behavior` is inside by construction, and no
field can place it outside; `records/selfcheck.py` carries that case under the
label "name the claim's own metric as an invariant". The general false
declaration stays open: a record that scores a metric and omits it from
`scoring_metrics` passes C-05. The honest failure in Section 2 is still caught,
because a record whose only metrics are length and correctness has no outside
metric to declare. The specification states the remaining limit in §4.5 and §10.
C-11 narrows the gap from the other side: the claim's metric must be reported by
every run, so a record can no longer assert an improvement in a quantity no run
measured. What remains is the declaration of which metrics the scoring function
used, and no record-level check can see the harness. An earlier draft of this
release used a boolean, `outside_scoring`, which a probe could set freely; the
metric comparison replaced it before first publication, when no record existed
outside the release (§14).

**D-9. The status vocabulary is now closed, not loosened.** C-10 determines the
status from the record: a record whose lineage does not resolve must be `orphan`
and one whose lineage resolves must not be; `submitted` and `replicated` require
resolving lineage; `replicated` additionally requires a disclosed claimant and
the manifest's independent-run count by other operators with disclosed,
differing sources. The probe that set `status: "replicated"` on the worked
example fails C-10, and the probe that set `orphan` on a record with resolving
lineage fails it too; both are cases in `records/selfcheck.py`.

What remains is not a status hole but the limit §4.10 already states: the
mechanism of distinctness between operators is out of scope, so a record can
satisfy C-10 by asserting two funding sources that are not distinct in fact.
`challenged`, `refuted`, and `expired` were removed from the vocabulary rather
than left unchecked: each needs an object the format does not define, and §11
says so.

**D-10. C-07 checks disclosure, not accuracy.** Zero cost passes, because
hardware that is already owned costs nothing per run. Zero duration does not:
a run that produced a result took time, and a record that declares zero for both
has disclosed nothing while appearing to satisfy a disclosure check. That pair
is rejected, and `records/selfcheck.py` carries the case against the positive
fixture. A false non-zero cost still passes; the check establishes that a number
was stated, not that it is true, and §10 carries the row.

**D-11. The differential test agreed about nothing.** `crosscheck.py --fuzz 200`
passed for months, and the corpus it passed on produced eleven distinct detail
messages in total: one per check, every one of them the same "field missing"
branch. Nine of the eleven checks had never been seen to pass. An arbitrary JSON
shape fails C-02 and everything downstream short-circuits, so the generator was
measuring the two implementations' agreement about malformed input while the
repository claimed agreement about records.

The generator now emits two kinds of document, half arbitrary shapes and half
mutations of a conforming record, and the run prints a coverage table. Over 400
documents the corpus reaches 190 distinct messages, and every check except C-09
has been seen to fail. C-09 is an invariant that should hold, so its never failing
is the expected result rather than a gap. Two of the defects below were found by
the rebuilt corpus; neither was reachable by the old one.

**D-12. Go's text functions are not Python's, and the difference is a verdict.**
C-10 decides independence with `str.strip()` and `str.casefold()`. Go's
`strings.TrimSpace` does not remove U+001C..U+001F, `strings.ToLower` ignores
SpecialCasing and Final_Sigma, and `strings.EqualFold` does simple folding, so
`strasse` and `straße` were two funding sources. Go also ships a newer Unicode
table than the reference runs on, which changes `repr()`'s printability test and
therefore the text of report details. The operations are now pinned to Unicode
16.0.0 with tables generated from Python and checked across every code point, so
an upgrade on either side fails a test instead of silently moving a verdict.

**D-13. C-05 coerced a value of the wrong type into the right one.** The Go
implementation read `claim.behavior` with a type assertion that discarded its
success flag, so a null behavior became the empty string. When
`claim.scoring_metrics` contained the empty string, the null behavior looked
scored and C-05 passed where the reference failed. C-02 rejects that record, but
C-05's own verdict was wrong, and the report is per check. A non-string behavior
is now not among the metrics, whatever the set contains; the detail quotes the
value as Python would print it.

**D-14. The report was not a function of the canonical bytes.** C-03 lists the
hashes it could not resolve. Some it finds structurally, and the rest it finds by
walking the record, and the walk emitted them in document order. Canonical form
sorts member names, so two documents with the same canonical bytes are the same
record — but re-serialising one changed the order of C-03's detail, and C-09
reported a round-trip that had not preserved the result. The suite was failing
records for a property the format says does not exist. Walk-discovered paths are
now sorted before reporting, in both implementations.

**D-15. Operators were compared case-sensitively while funding was folded.** A
claimant could sign an added run with its own name in a different case and count
it as independent, reaching `replicated` without a second entity. The funding
rule already prevented the same evasion on the other field. Both comparisons now
trim and full-case-fold, and `records/selfcheck.py` carries the case against the
positive fixture.

## A run that was not re-recorded

The `dspy-wsp` package (Cmpnd, 13 November 2026, MIT) publishes five Typed
Decisions runs, each with a real tensor delta, a patch manifest naming the base
model and revision, and per-case final-check scores. On the 400-case test split
the Strands Decider 2B edit gained 10.4 ± 1.1 points and the Clef-Flash edit 1.9
± 0.7. The results README also gives writer cost and wall time for both.

No record of either run is included. The cost and wall time are published in a
README table, not emitted as fields of the run, and the price table behind them
is not published with the artifact. A record could transcribe the two numbers and
pass C-07, but the pass would assert a disclosure the run does not carry: a
reader could not recompute the cost from the bytes the record cites. That is the
failure D-3 describes, in the one field the suite checks mechanically, and it is
worse than the honest failure of MIR-R1.

The run is cited in the paper for what it does carry. Its patch manifest and
per-case scores are most of a record's run-level content, and the two missing
numbers are ones the operator already publishes. When the report carries them,
anyone can write the record without asking the operator for anything.

## The 8 November run

The failure the specification answers was reported publicly on 8 November 2026
by Beaker: Reza Nayebi, "Adventures in Weight-Space Programming with Beaker",
https://www.withbeaker.ai/blog/weight-space-programming. The accepted terse run
is public at
https://app.withbeaker.ai/public/runs/3230a4ea-512b-4a9f-b42a-4d271cca03fd,
and the checkpoint is
https://huggingface.co/rilixai/Qwen3.5-0.8B-Beaker-terse-3230a4ea.

Quoted from the report: "Math answers right dropped from 80% to 23–54%."
"GSM8K accuracy fell from 46% to 0% in our pre-check." "one run starts every
math answer with a stray \".\""

The report also states that the average answer length fell from 345 to 183–234
tokens and that the terse score rose from 0.26 to 0.33–0.36. Those are the
numbers the scoring function measured; the correctness figures are what it did
not measure.

The page was retrieved on 13 November 2026. The retrieved HTML (681,098 bytes)
has SHA-256
`a56df9daf6fb877b5299f2c38e12371ff661e6db35449c8384e7ba0f412ade25`. The digest
identifies the copy that was read, not a permanent artifact: the page is served
by an application and its bytes change when the application is rebuilt.

`examples/terse-run.json` is not this run. It is a synthetic fixture built by
`examples/build_examples.py`, with placeholder hashes and an `example-only`
license, shaped after the reported failure so that the suite has a case whose
invariant set stays inside the scoring function. The record of the actual run
is the report and the public run page; this repository does not claim a MIR-1
record of it.

## What a reviewer can check without a GPU

```
python3 validate.py records/MIR-R1.json --verify-remote
python3 records/falsify.py records/MIR-R1.json
python3 records/selfcheck.py
python3 crosscheck.py --remote
```

The first resolves every hash, two of them against the host over the network.
The second recomputes the claim from per-sample observations. The third shows
each check failing when its condition is removed. The fourth runs the Python and
Go implementations on the same inputs and reports a disagreement if a single
byte differs.

What none of them does is check the checkpoint against the claim. That requires
downloading 1.7 GB, running `evaluate.py run` with the pinned harness, and
comparing. It is the falsifier that costs something, and the record states it in
the field a reviewer would look at.
