# MIR-1.1 — Composable Weight Interventions

## Weight Patches for the `weights` Intervention Type

**Status:** Version 1.1. Companion to MIR-1, version 1.0.
**Date:** 2026-11-18
**Patch format:** `wpp_version` 0.1
**Test suite:** 1.7.0
**License:** Text CC BY 4.0. Test suite Apache-2.0.
**Keywords:** weight-space programming; weight patches; model intervention records; composition; reproducibility; conformance testing

**Abstract.** MIR-1 defines a conformance test for claims about interventions. This companion extends the intervention type `weights` so that a claim may carry an executable, content-addressed, composable, and reversible payload: a **Weight Patch**. It specifies form, not desirability or method quality. Every valid MIR-1 record remains valid; only records that carry a structured Weight Patch can be measured by the five additional checks P-01 to P-05, and only those records can be reported with the patch qualifiers.

---

## 1. Scope

MIR-1 specifies the record. This document specifies one payload the record may name: a patch that transforms the weights of a base checkpoint without shipping the whole modified checkpoint.

In scope: the patch object, its canonical bytes and identifier, its operations, dependency and application order, inverse forms, five additional checks, and three derived qualifiers.

Out of scope, unchanged from MIR-1: whether the change is desirable, model safety beyond declared invariants, governance of any registry, and the correct unit of behavioral change. Further out of scope and stated here: rebasing a patch onto a different base, merging patches with automatic conflict resolution, and any tensor serialization other than the one named in section 5.7.

This document adds no requirement to MIR-1. A record that fails every check here may still be a conforming MIR-1 record. The five checks and the three qualifiers are additional measurements of the payload, not conditions on the record.

## 2. Motivation

A MIR-1 record can already declare a weight intervention and its invariants. In practice most interventions are distributed as full modified checkpoints. That forces every consumer to download large artifacts, makes successive edits difficult to track, and turns undo into a manual reconstruction problem.

This document makes the intervention payload itself the primary artifact: a compact, hash-pinned patch that can be applied to a verified base, stacked with other conforming patches, and reversed. The fields MIR-1 requires — base hash, invariant set, executable falsifier, lineage — remain mandatory. The patch is a structured and executable form of the `weights` intervention, not a replacement for the record.

## 3. Terms

**3.1 Weight Patch.** A content-addressed payload that describes a precise transformation of a base checkpoint's weights. A Weight Patch MUST be applicable to any copy of the named base whose bytes match the named hash, without requiring the full modified checkpoint.

**3.2 Patch Identifier.** The SHA-256 of the canonical form of the patch, computed after removal of the `id` member (section 5.5). Written as `wpp:sha256:<digest>` or as the bare lowercase hexadecimal digest. The two spellings name the same patch.

**3.3 Payload Hash.** The SHA-256 of the bytes actually stored under `intervention.payload_hash`. A patch is stored in canonical form (section 5.5), so the payload hash is a function of the patch and the patch identifier is a function of the patch without its `id`. When the stored artifact omits `id`, the two are equal. When it carries `id`, the payload hash covers the bytes including it, and the two differ by construction, not by drift. Both are checkable; neither is a claim about the other.

**3.4 Composition.** The ordered application of one or more Weight Patches to a base checkpoint. The resulting state is fully determined by the base hash, the ordered list of patch identifiers, and the patches themselves.

**3.5 Dependency.** A declared prior patch that MUST be present in the record's patch lineage before the current patch may be applied. A dependency is satisfied only by a patch identifier reachable through the record's lineage (section 6.2), or by an identifier declared in `external_dependencies`, which states that the patch exists but is not carried in this lineage.

**3.6 Exact inverse.** A stored snapshot of the weight values that existed before the patch was applied, sufficient to restore them by assignment. Assignment of a stored float32 value is bit-identical by construction.

**3.7 Algebraic inverse.** An inverse computed from the forward operations — negation of an additive delta, reciprocal of a scale. It restores the mathematical value, not necessarily the bits: adding a float32 delta and then subtracting it can differ in the last bit. An algebraic inverse is informative and is not executed by the suite.

**3.8 Array container.** The only tensor serialization this document defines for execution: `wpp-array-0.1` (section 5.7). It exists so that P-05 can run on real bytes. It is not a proposal for how checkpoints should be stored.

## 4. Requirements on the `weights` Intervention Type

When an intervention has `"type": "weights"`:

- The payload named by `intervention.payload_hash` MUST be a Weight Patch conforming to section 5, **or** a full modified checkpoint. The second form remains valid MIR-1 and is not measured by this document.
- A payload is a Weight Patch when the stored bytes parse as a JSON object carrying `wpp_version`. Detection is by the payload's own declaration, not by a record field: a patch that does not declare itself is read as a full checkpoint and cannot be measured here.
- The patch MUST name the exact base checkpoint by content hash, and that hash MUST equal `base.hash` (normalized). A patch whose `base.checkpoint_hash` names different bytes than the record's `base.hash` is not applicable to the record's base.
- The patch MUST carry or reference the same invariant set and executable falsifier that MIR-1 requires of the record (P-04).
- A payload held as a locator is not a Weight Patch for the purposes of P-02 to P-05: its bytes are not held, so its canonical form cannot be computed. C-03 still resolves it as an artifact.

## 5. Weight Patch Canonical Format

### 5.1 Members

A conforming Weight Patch is a UTF-8 JSON object with at least these members. Additional members are permitted at the top level and inside an operation, and MUST be preserved during round-trips.

| Member | Type | Requirement |
|---|---|---|
| `wpp_version` | string | `"0.1"` |
| `base` | object | `checkpoint_hash` (hash); optional `model_id`, `format` (strings) |
| `id` | string | patch identifier (3.2), matching 5.5 |
| `dependencies` | array of strings | patch identifiers that must precede this patch; MAY be empty |
| `external_dependencies` | array of strings | optional; identifiers declared but not carried in this lineage |
| `edit` | object | `type`, `ops`, `num_changed`; optional `sparsity` |
| `inverse` | object | optional; `kind` is `exact` or `algebraic` (6.4) |
| `invariants` | array | the MIR-1 invariant set; required unless `invariants_hash` is given (5.6) |
| `falsifier` | object | the MIR-1 executable falsifier; required unless `falsifier_hash` is given (5.6) |
| `invariants_hash` | string | optional; a hash of the canonical bytes of the record's `invariants` (5.6) |
| `falsifier_hash` | string | optional; a hash of the canonical bytes of the record's `falsifier` (5.6) |
| `metadata` | object | optional; title, author, created, description, license, tags |

`edit.type` is one of:

| Type | Permitted operations |
|---|---|
| `sparse_delta` | `set`, `add`, `scale` |
| `operator` | `add_vector` |
| `mixed` | any combination, containing at least one of each family |

`edit.num_changed` is a non-negative integer: the number of scalar weight locations the patch addresses, counting each location once. `edit.sparsity`, when present, is a number in [0, 1].

### 5.2 Operations

An operation addresses one named tensor. Locations are flattened zero-based indices in row-major order, or rows along the first axis for `add_vector`. `indices` and `rows` MUST be arrays of non-negative integers in strictly ascending order, so that two implementations agree on what the patch touches without applying it.

| `op` | Members | Effect |
|---|---|---|
| `set` | `tensor`, `indices`, `values` | `x[i] = values[j]` |
| `add` | `tensor`, `indices`, `deltas` | `x[i] += deltas[j]` |
| `scale` | `tensor`, `indices`, `factor` | `x[i] *= factor`, `factor != 0` |
| `add_vector` | `tensor`, `rows`, `vector`, optional `scale` | for each row `r`: `x[r, j] += scale * vector[j]` over the flattened trailing dimensions |

For `set`, `add`, and `scale`, the length of `values`, `deltas`, or `indices` respectively MUST equal the length of `indices`. For `add_vector`, `vector` MUST be non-empty and MUST have length equal to the product of the tensor's dimensions after the first; `scale` defaults to 1. All numbers MUST be finite JSON numbers. A tensor name is a non-empty string.

A patch whose operations are structurally invalid cannot be applied by any implementation, so it fails P-02 rather than being reported as merely unstackable.

### 5.3 Numbers

Numbers are JSON numbers as MIR-1 defines them. Weight values in an array container are IEEE-754 binary32, little-endian, so the file stores a bit pattern and the patch stores a number. An operation's number is read as binary64, the operation is computed in binary64, and the result is rounded once to binary32 when stored. That rule makes the last bit a property of this document rather than of a compiler, and it is the reason an algebraic inverse is not bit-identical (3.7).

A number whose nearest binary32 value is infinite has no weight to round to. An implementation MUST refuse such an operand and report why, rather than saturate the stored weight to an infinity; the suite reports that refusal as P-05 failing to apply.

### 5.4 Base

`base.checkpoint_hash` is the SHA-256 of the base checkpoint in the serialization named by `base.format`. For an array container the hash is of the file's exact bytes. `base.model_id` and `base.format` are free strings; neither is checked against the artifact, because a string that describes a checkpoint is a description and not a measurement.

### 5.5 Canonical bytes and identifier

The canonical bytes of a patch follow MIR-1 §4.13 exactly: UTF-8, object members sorted by code point, no insignificant whitespace, the same string escaping, the same number spelling, nesting bounded at 256.

The patch identifier is the SHA-256 of the canonical bytes of the patch **with the `id` member removed**. The stored artifact SHOULD be the canonical form, and the suite reports whether it is (P-02), because a patch that is not stored canonically cannot be reproduced byte for byte from its identifier.

### 5.6 Invariants and falsifier references

P-04 accepts two forms for each of `invariants` and `falsifier`:

- the member itself, canonically equal to the record's member; or
- a reference member `invariants_hash` / `falsifier_hash` that resolves in the store to bytes canonically equal to the record's member.

The second form exists because a patch is often produced before the record is assembled, and copying a declaration into two artifacts is a way for them to diverge.

### 5.7 The `wpp-array-0.1` container

An array container is a UTF-8 JSON object:

```json
{
  "wpp_array_version": "0.1",
  "tensors": {
    "name": {"shape": [2, 3], "dtype": "float32", "data_b64": "..."}
  }
}
```

`shape` is a non-empty array of positive integers. `dtype` is `float32`. `data_b64` is standard base64 with padding; the decoded length MUST equal four times the product of `shape`. Values are row-major, little-endian.

The container is defined so that composition and inversion can be executed rather than described. P-05 runs on it and reports `not run` on any other base. It is not a checkpoint format and this document does not propose it as one.

## 6. Composition, Lineage, and Reversibility

**6.1 Patch lineage.** A record's patch lineage is derived, not declared: walk the record's MIR-1 lineage, load each parent record, take the parent's `intervention.payload_hash`, and read the patch it names. The patch lineage of a record is the patch lineage of each parent followed by the parent's own patch, if any, and then the record's own patch.

**6.2 Application order.** The order is the depth-first post-order of that walk, visiting each record's `lineage` entries in document order. A patch MUST be applied after every patch it depends on. A patch whose dependency is not earlier in that order fails P-03, whether the dependency is absent or merely out of order.

**6.3 Conflicts.** Two patches conflict when they address the same tensor location and their operations on it do not commute. The suite reports overlaps it can compute: sparse against sparse by index, vector against vector by row. An overlap between a sparse operation and a vector operation cannot be decided from the two patches alone: an index is a row only once the tensor's trailing dimensions are known. The suite reports that case as undetermined rather than resolving it, even when the base happens to be an array container. A reported conflict is advisory: it never fails a check, because MIR-1.1 requires detectability and not resolution.

**6.4 Undo and redo.** An exact inverse (3.6) restores the touched locations by assignment and is bit-identical. An algebraic inverse (3.7) is a computation and is not. When a patch carries neither, undo is lineage replay from the base: recomputing the surviving chain produces the same bytes, because application is deterministic. Replay is the fallback and not a lesser one; it is the only form that is exact for an additive edit whose exact inverse was not captured.

A patch is reported `reversible` when it carries an exact inverse that is structurally complete: every prior entry names a tensor and ascending indices, and every forward location is covered when coverage is computable without the base. P-05 is the executed test of the same property.

## 7. Checks

In addition to C-01 to C-11, a record whose payload is a Weight Patch carries five checks. They are reported in a separate patch block. The eleven checks of MIR-1 are not renumbered, and a record without a patch is still reported as eleven checks and nothing else. No aggregate score is produced.

| ID | Check |
|---|---|
| P-01 | Base hash resolution: `base.checkpoint_hash` resolves, and equals the record's `base.hash` |
| P-02 | Patch conformance and integrity: the object matches section 5, `num_changed` is consistent where computable, and `id` matches the canonical form without it |
| P-03 | Dependency closure and order: every dependency is a conforming patch that appears earlier in the patch lineage, or is declared external |
| P-04 | Invariant and falsifier presence: the patch carries or references the record's invariant set and falsifier |
| P-05 | Executed round-trip: on a `wpp-array-0.1` base, applying the lineage and then the exact inverse restores bit-identical tensors, and the patch changes at least one weight |

Each check is reported PASS, FAIL, or NOT RUN. NOT RUN is not a pass: P-05 is NOT RUN when the base is not an array container, when the patch carries no exact inverse, or when an ancestor patch cannot be applied. The report states which condition applied.

P-01 fails when the hash does not resolve or names different bytes than the record's base. P-02 fails on a structural defect, a `num_changed` mismatch in a patch whose locations are computable, or an identifier mismatch. P-03 fails on a missing, malformed, later-ordered, or non-conforming dependency. P-04 fails when neither form is present or a reference does not resolve to the record's member. P-05 fails when the forward application cannot be performed on a base it claims to apply to, when it changes nothing, or when the exact inverse does not restore the bytes.

A payload that parses but does not carry `wpp_version` is a full checkpoint (section 4). It produces no patch block, so it cannot be reported with a patch qualifier and cannot be reported as failing one either.

## 8. Qualifiers

Three qualifiers are derived by the suite from the checks, never declared by the record. They refine a MIR-1 status and do not replace it. A record cannot assert a qualifier the payload does not support, for the same reason MIR-1 §6 gives for status: a qualifier is a measurement, not a story.

| Qualifier | Emitted when |
|---|---|
| `patch-executable` | P-02 passes: the payload is a conforming patch with a matching identifier |
| `stackable` | `patch-executable` and P-03 passes: dependencies resolve, precede it, and are themselves conforming |
| `reversible` | the patch is `patch-executable` and carries a structurally complete exact inverse (6.4), and P-05, when it runs, did not fail |

`reversible` is a statement about the inverse, not about P-05. The report carries both, and a reader sees whether the inverse was executed. A patch whose inverse is structurally complete is still not reported `reversible` if executing it changed the wrong bytes.

## 9. Backward Compatibility

Every valid MIR-1 record remains valid under MIR-1.1. Records that use a full modified checkpoint continue to conform to MIR-1 and are not measured by P-01 to P-05. Only records whose payload declares `wpp_version` carry a patch block and the qualifiers.

Suite 1.6.0 published this document; suite 1.7.0 adds MIR-1.2's record qualifiers and leaves P-01 to P-05, and the patch qualifiers they derive, unchanged.

The record schema is unchanged. This document adds no member to a MIR-1 record: the patch is the payload that `intervention.payload_hash` already names, and the qualifiers are in the report. A record's canonical bytes and identifier are therefore unaffected by this companion.

## 10. Residual Limits

All residual threats in MIR-1 §10 remain.

- **Bit identity is a property of the inverse form, not of arithmetic.** A negated delta restores the value the author intended, not necessarily the bits that were there. Only assignment of captured values, or a replay from the base, is bit-identical, and the report says which form was used.
- **Detectability is not semantic compatibility.** Two patches can commute on every index and still interact through the behavior they change. The invariant set is the instrument for that, not the conflict report.
- **A sparse conflict report is partial.** Sparse against vector overlap is not computed by the suite, and is reported as undetermined rather than as no conflict.
- **Rebase is outside this surface.** A patch names one base hash. Nothing here supports applying it to a newer checkpoint, and nothing here should be read as claiming that it does.
- **`num_changed` is declared.** It is recomputed only where the touched locations are computable without the base; elsewhere it is reported as declared.
- **A patch can name a base it was not derived from.** P-01 checks that the named hash matches the record and resolves. It does not check that the operations were computed from those weights. That is MIR-1's derivation limit, unchanged, and composition makes it more valuable to an attacker rather than less.
- **Execution covers one container.** P-05 is evidence about `wpp-array-0.1` bytes. It is not evidence about a real checkpoint in a framework serialization, and the report says NOT RUN there rather than implying otherwise.

---

*End of MIR-1.1, version 1.*
