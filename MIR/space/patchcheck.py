#!/usr/bin/env python3
"""MIR-1.1 checks P-01 through P-05 for a Weight Patch payload.

A record is measured here only when its `weights` payload declares itself a
patch with `wpp_version`. The record's eleven MIR-1 checks are unaffected, and
the patch block is reported beside them rather than merged into them, so a
record without a patch is still eleven checks and a plain MIR-1 record cannot
become non-conforming by this companion.

The module receives the canonical serializer, parser, hash normalizer, and
schema walker from the caller. That keeps one implementation of each primitive
and no import cycle between the two files.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import struct

ARRAY_VERSION = "0.1"
PATCH_SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "patch-schema.json")
SPARSE_OPS = ("set", "add", "scale")
VECTOR_OPS = ("add_vector",)
MAX_PATCH_LINEAGE = 32


HEX64 = re.compile(r"^[0-9a-f]{64}$")


class Context:
    """The primitives the patch checks share with the record validator."""

    def __init__(self, canonical_bytes, parse_bytes, norm_hash, schema_problem):
        self.canonical_bytes = canonical_bytes
        self.parse_bytes = parse_bytes
        self.norm_hash = norm_hash
        self.schema_problem = schema_problem


def digest(value):
    """A patch identifier or checkpoint hash, normalized to bare lowercase hex.

    Accepts `wpp:sha256:`, `sha256:`, or nothing. The record's own hash fields
    keep MIR-1's narrower rule; this function is only used inside a patch.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.startswith("wpp:"):
        text = text[4:]
    if text.startswith("sha256:"):
        text = text[7:]
    text = text.lower()
    return text if HEX64.match(text) else None


def is_patch(document):
    return isinstance(document, dict) and "wpp_version" in document


def short(text):
    return text[:12]


def patch_id(patch, ctx):
    """The SHA-256 of the canonical bytes of the patch without its id."""
    body = {k: v for k, v in patch.items() if k != "id"}
    try:
        return hashlib.sha256(ctx.canonical_bytes(body)).hexdigest()
    except (ValueError, TypeError):
        return None


def load_schema():
    with open(PATCH_SCHEMA_PATH, "r", encoding="utf-8") as handle:
        return json.load(handle)


# ------------------------------------------------------------- operations

def _op_kind(op):
    return op.get("op") if isinstance(op, dict) else None


def _ascending(values):
    if not isinstance(values, list):
        return False
    previous = -1
    for value in values:
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            return False
        if value <= previous:
            return False
        previous = value
    return True


def _known_op(op):
    return _op_kind(op) in SPARSE_OPS + VECTOR_OPS


def _family(op):
    return "sparse" if _op_kind(op) in SPARSE_OPS else "vector"


def structural_problem(patch):
    """The first structural defect the schema cannot express, or ''.

    Order is fixed so that two implementations report the same first defect.
    """
    edit = patch.get("edit")
    if not isinstance(edit, dict):
        return ""  # the schema already failed
    kind = edit.get("type")
    ops = edit.get("ops")
    if not isinstance(ops, list) or not ops:
        return ""
    families = []
    for index, op in enumerate(ops):
        if not _known_op(op):
            continue
        families.append(_family(op))
        if kind in ("sparse_delta", "operator"):
            allowed = SPARSE_OPS if kind == "sparse_delta" else VECTOR_OPS
            if _op_kind(op) not in allowed:
                return ("edit.type '%s' permits %s operations only; op[%d] is '%s'"
                        % (kind, "|".join(allowed), index, _op_kind(op)))
        name = _op_kind(op)
        if name in SPARSE_OPS or name == "add_vector":
            field = "rows" if name == "add_vector" else "indices"
            locations = op.get(field)
            if not _ascending(locations):
                return "op[%d] %s are not strictly ascending" % (index, field)
        if name in ("set", "add"):
            data = op.get("values") if name == "set" else op.get("deltas")
            if not isinstance(data, list) or len(data) != len(op.get("indices") or []):
                return ("op[%d] has %d indices and %d %s"
                        % (index, len(op.get("indices") or []),
                           len(data) if isinstance(data, list) else 0,
                           "values" if name == "set" else "deltas"))
        if name == "scale":
            factor = op.get("factor")
            if not isinstance(factor, (int, float)) or isinstance(factor, bool):
                return ""  # the schema already failed
            if factor == 0:
                return "op[%d] factor is zero" % index
        if name == "add_vector":
            vector = op.get("vector")
            if isinstance(vector, list) and not vector:
                return "op[%d] vector is empty" % index
    if kind == "mixed":
        if "sparse" not in families or "vector" not in families:
            return "edit.type 'mixed' needs at least one sparse and one operator operation"
    return ""


def touched_counts(edit):
    """(computable, count) for the locations the edit addresses.

    Sparse operations are computable from the indices. Vector operations are
    computable when no (tensor, row) pair repeats across operations, because
    each row addresses `len(vector)` trailing weights. A mixed edit is not
    computable without the base's shapes.
    """
    ops = edit["ops"]
    families = {_family(op) for op in ops}
    if families == {"sparse"}:
        seen = set()
        for op in ops:
            for index in op["indices"]:
                seen.add((op["tensor"], index))
        return True, len(seen)
    if families == {"vector"}:
        seen = set()
        for op in ops:
            for row in op["rows"]:
                if (op["tensor"], row) in seen:
                    return False, 0
                seen.add((op["tensor"], row))
        total = 0
        for op in ops:
            total += len(op["rows"]) * len(op["vector"])
        return True, total
    return False, 0


def exact_inverse_problem(patch):
    """'' when an exact inverse is structurally complete, else the reason.

    An exact inverse is a snapshot of prior values, restored by assignment.
    Coverage against the forward operations is verified here only when the
    forward locations are computable without the base; P-05 verifies it by
    execution where they are not.
    """
    inverse = patch.get("inverse")
    if not isinstance(inverse, dict) or inverse.get("kind") != "exact":
        return "no exact inverse is supplied"
    edit = patch.get("edit")
    if not isinstance(edit, dict) or not isinstance(edit.get("ops"), list) or not edit["ops"]:
        return "the patch has no operations"
    prior = inverse.get("prior")
    if not isinstance(prior, list) or not prior:
        return "the exact inverse carries no prior values"
    covered = set()
    for index, entry in enumerate(prior):
        if not isinstance(entry, dict):
            return "prior[%d] is not an object" % index
        tensor = entry.get("tensor")
        if not isinstance(tensor, str) or not tensor:
            return "prior[%d] has no tensor" % index
        locations = entry.get("indices")
        if not _ascending(locations):
            return "prior[%d] indices are not strictly ascending" % index
        values = entry.get("values")
        if not isinstance(values, list) or len(values) != len(locations):
            return "prior[%d] has %d indices and %d values" % (
                index, len(locations), len(values) if isinstance(values, list) else 0)
        for location in locations:
            covered.add((tensor, location))
    computable, _ = touched_counts(edit)
    if computable and {_family(op) for op in edit["ops"]} == {"sparse"}:
        wanted = set()
        for op in edit["ops"]:
            for location in op["indices"]:
                wanted.add((op["tensor"], location))
        missing = sorted(wanted - covered)
        if missing:
            return ("the exact inverse does not cover %d location(s); the first is "
                    "%s[%d]" % (len(missing), missing[0][0], missing[0][1]))
    return ""


# -------------------------------------------------------------- containers

def parse_container(raw, ctx):
    """(tensors, error). tensors maps name -> [shape, bytearray]."""
    try:
        document = ctx.parse_bytes(raw)
    except ValueError:
        return None, "base is not a wpp-array-0.1 container"
    if not isinstance(document, dict) or document.get("wpp_array_version") != ARRAY_VERSION:
        return None, "base is not a wpp-array-0.1 container"
    tensors = document.get("tensors")
    if not isinstance(tensors, dict):
        return None, "container has no tensors object"
    out = {}
    for name in sorted(tensors):
        entry = tensors[name]
        if not isinstance(entry, dict):
            return None, "tensor '%s' is not an object" % name
        if entry.get("dtype") != "float32":
            return None, "tensor '%s' is not float32" % name
        shape = entry.get("shape")
        if not isinstance(shape, list) or not shape:
            return None, "tensor '%s' has no shape" % name
        size = 1
        for dimension in shape:
            if not isinstance(dimension, int) or isinstance(dimension, bool) or dimension < 1:
                return None, "tensor '%s' has a non-positive dimension" % name
            size *= dimension
        text = entry.get("data_b64")
        if not isinstance(text, str):
            return None, "tensor '%s' has no data_b64" % name
        try:
            payload = base64.b64decode(text.encode("ascii"), validate=True)
        except (binascii.Error, UnicodeEncodeError):
            return None, "tensor '%s' data is not valid base64" % name
        if len(payload) != 4 * size:
            return None, "tensor '%s' data does not match its shape" % name
        out[name] = [list(shape), bytearray(payload)]
    return out, ""


def finite32(value):
    """False when the value has no finite binary32 representation.

    A weight stored as an infinity is not a weight, and an implementation that
    silently saturated would report a round-trip it did not perform.
    """
    try:
        struct.pack("<f", value)
        return True
    except (OverflowError, struct.error):
        return False


def _read(tensors, tensor, index):
    return struct.unpack_from("<f", tensors[tensor][1], 4 * index)[0]


def _write(tensors, tensor, index, value):
    struct.pack_into("<f", tensors[tensor][1], 4 * index, value)


def apply_ops(tensors, ops, ctx):
    """Apply operations in order. Returns (changed, error).

    Arithmetic is binary64 rounded once to binary32 (MIR-1.1 5.3), which both
    implementations can reproduce and which keeps an inverse's last-bit
    behaviour a property of the statement rather than of a compiler.
    """
    changed = 0
    for index, op in enumerate(ops):
        name = _op_kind(op)
        tensor = op.get("tensor")
        if tensor not in tensors:
            return changed, "op[%d] names unknown tensor '%s'" % (index, tensor)
        shape, data = tensors[tensor]
        total = len(data) // 4
        if name in SPARSE_OPS:
            locations = op.get("indices")
            if name == "set":
                values = op.get("values")
            elif name == "add":
                values = op.get("deltas")
            else:
                values = None
            for offset, location in enumerate(locations):
                if location >= total:
                    return changed, ("op[%d] index %d is outside tensor '%s' (%d values)"
                                     % (index, location, tensor, total))
                before = _read(tensors, tensor, location)
                if name == "set":
                    operand = float(values[offset])
                    if not finite32(operand):
                        return changed, "op[%d] carries a value outside the binary32 range" % index
                    after = operand
                elif name == "add":
                    operand = float(values[offset])
                    if not finite32(operand):
                        return changed, "op[%d] carries a value outside the binary32 range" % index
                    after = before + operand
                else:
                    operand = float(op["factor"])
                    if not finite32(operand):
                        return changed, "op[%d] carries a value outside the binary32 range" % index
                    after = before * operand
                _write(tensors, tensor, location, after)
                if _read(tensors, tensor, location) != before:
                    changed += 1
        elif name == "add_vector":
            if len(shape) < 2:
                return changed, "op[%d] add_vector needs a tensor of rank 2 or more" % index
            trailing = 1
            for dimension in shape[1:]:
                trailing *= dimension
            vector = op.get("vector")
            if len(vector) != trailing:
                return changed, ("op[%d] vector has %d values; tensor '%s' has %d "
                                 "trailing dimensions" % (index, len(vector), tensor, trailing))
            factor = op.get("scale", 1)
            if not isinstance(factor, (int, float)) or isinstance(factor, bool):
                return changed, "op[%d] scale is not a number" % index
            if not finite32(float(factor)):
                return changed, "op[%d] carries a value outside the binary32 range" % index
            for row in op.get("rows"):
                if row >= shape[0]:
                    return changed, ("op[%d] row %d is outside tensor '%s' (%d rows)"
                                     % (index, row, tensor, shape[0]))
                base = row * trailing
                for column in range(trailing):
                    location = base + column
                    component = float(vector[column])
                    if not finite32(component):
                        return changed, "op[%d] carries a value outside the binary32 range" % index
                    before = _read(tensors, tensor, location)
                    _write(tensors, tensor, location, before + factor * component)
                    if _read(tensors, tensor, location) != before:
                        changed += 1
        else:
            return changed, "op[%d] has unknown kind" % index
    return changed, ""


def apply_prior(tensors, prior, ctx):
    for index, entry in enumerate(prior):
        tensor = entry.get("tensor")
        if tensor not in tensors:
            return "prior[%d] names unknown tensor '%s'" % (index, tensor)
        total = len(tensors[tensor][1]) // 4
        for offset, location in enumerate(entry.get("indices") or []):
            if location >= total:
                return ("prior[%d] index %d is outside tensor '%s' (%d values)"
                        % (index, location, tensor, total))
            value = float(entry["values"][offset])
            if not finite32(value):
                return "prior[%d] carries a value outside the binary32 range" % index
            _write(tensors, tensor, location, value)
    return ""


def snapshot(tensors):
    return {name: bytes(data) for name, (_shape, data) in tensors.items()}


# ------------------------------------------------------ record patch access

def payload_bytes(record, store, ctx):
    """(digest, raw) for the record's intervention payload, or (None, None)."""
    intervention = record.get("intervention")
    if not isinstance(intervention, dict) or intervention.get("type") != "weights":
        return None, None
    digest_value = ctx.norm_hash(intervention.get("payload_hash"))
    if digest_value is None:
        return None, None
    kind, path = store.find(digest_value)
    if kind != "bytes":
        return None, None
    try:
        with open(path, "rb") as handle:
            return digest_value, handle.read()
    except OSError:
        return None, None


def load_patch(raw, ctx):
    """(patch, error). A payload that is not a patch is not an error."""
    try:
        document = ctx.parse_bytes(raw)
    except ValueError:
        return None, ""
    if not is_patch(document):
        return None, ""
    return document, ""


def _record_from_path(path, ctx):
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError:
        return None
    try:
        document = ctx.parse_bytes(raw)
    except ValueError:
        return None
    return document if isinstance(document, dict) else None


def patch_lineage(record, store, ctx):
    """Ancestor patches in application order, then this record's patch.

    Order is the depth-first post-order of the MIR-1 lineage, visiting declared
    entries in document order (MIR-1.1 6.2). Returns (entries, error) where an
    entry is (record, patch, patch_digest).
    """
    entries = []

    def walk(node, seen, depth):
        if depth > MAX_PATCH_LINEAGE:
            return "patch lineage is deeper than %d records" % MAX_PATCH_LINEAGE
        lineage = node.get("lineage") if isinstance(node.get("lineage"), list) else []
        for value in lineage:
            parent_digest = ctx.norm_hash(value)
            if parent_digest is None:
                return "malformed lineage entry"
            if parent_digest in seen:
                return "lineage contains a cycle"
            path = store.resolve(parent_digest)
            if not path:
                return "lineage entry %s is not readable bytes" % short(parent_digest)
            parent = _record_from_path(path, ctx)
            if parent is None:
                return "lineage entry %s is not JSON" % short(parent_digest)
            problem = walk(parent, seen | {parent_digest}, depth + 1)
            if problem:
                return problem
            _digest, raw = payload_bytes(parent, store, ctx)
            if raw is None:
                continue
            patch, _error = load_patch(raw, ctx)
            if patch is not None:
                entries.append((parent, patch, patch_id(patch, ctx)))
        return ""

    problem = walk(record, frozenset(), 0)
    return entries, problem


# ------------------------------------------------------------------ checks

def check_p01(record, patch, store, ctx):
    base = patch.get("base")
    if not isinstance(base, dict):
        return "fail", "patch.base is missing or malformed"
    declared = digest(base.get("checkpoint_hash"))
    if declared is None:
        return "fail", "base.checkpoint_hash is missing or malformed"
    record_base = record.get("base") if isinstance(record.get("base"), dict) else {}
    actual = ctx.norm_hash(record_base.get("hash"))
    if actual is None:
        return "fail", "the record's base.hash is missing or malformed"
    if declared != actual:
        return "fail", "base.checkpoint_hash does not match the record's base.hash"
    if store.find(declared)[0] is None:
        return "fail", "base checkpoint does not resolve"
    return "pass", "base checkpoint resolves and matches the record's base.hash"


def check_p02(patch, raw, ctx, schema):
    problem = ctx.schema_problem(patch, schema, schema, "/")
    if problem:
        return "fail", "not a conforming patch: %s" % problem
    problem = structural_problem(patch)
    if problem:
        return "fail", problem
    declared = digest(patch.get("id"))
    if declared is None:
        return "fail", "id is missing or malformed"
    actual = patch_id(patch, ctx)
    if actual is None:
        return "fail", "the patch contains a number that cannot be represented"
    if declared != actual:
        return "fail", "id does not match the content address"
    try:
        canonical = raw == ctx.canonical_bytes(patch)
    except (ValueError, TypeError):
        canonical = False
    computable, count = touched_counts(patch["edit"])
    if computable:
        declared_count = patch["edit"].get("num_changed")
        if not isinstance(declared_count, int) or isinstance(declared_count, bool):
            return "fail", "num_changed is not an integer"
        if declared_count != count:
            return "fail", "num_changed is %d; the operations address %d location(s)" % (
                declared_count, count)
    detail = "conforms; id matches; %s; num_changed %s" % (
        "stored canonically" if canonical else "stored bytes are not canonical",
        "recomputed (%d)" % count if computable else
        "declared (%s), not recomputable without the base" % patch["edit"].get("num_changed"))
    return "pass", detail


def _touched(patch):
    """Per tensor: ('sparse', set(indices)) and/or ('vector', set(rows))."""
    out = {}
    for op in patch.get("edit", {}).get("ops", []):
        tensor = op.get("tensor")
        entry = out.setdefault(tensor, {"sparse": set(), "vector": set()})
        if _op_kind(op) in SPARSE_OPS:
            entry["sparse"].update(op.get("indices") or [])
        elif _op_kind(op) == "add_vector":
            entry["vector"].update(op.get("rows") or [])
    return out


def _overlap(left, right):
    """(locations, undetermined) between two touched maps."""
    locations = 0
    undetermined = 0
    for tensor, one in left.items():
        two = right.get(tensor)
        if not two:
            continue
        locations += len(one["sparse"] & two["sparse"])
        locations += len(one["vector"] & two["vector"])
        if (one["sparse"] and two["vector"]) or (one["vector"] and two["sparse"]):
            undetermined += 1
    return locations, undetermined


def check_p03(patch, ancestors, store, ctx):
    dependencies = patch.get("dependencies")
    external = patch.get("external_dependencies")
    dependencies = dependencies if isinstance(dependencies, list) else []
    external = external if isinstance(external, list) else []
    reachable = {}
    for _parent, ancestor, ancestor_digest in ancestors:
        if ancestor_digest:
            reachable.setdefault(ancestor_digest, ancestor)
    external_digests = set()
    for value in external:
        normalized = digest(value)
        if normalized is None:
            return "fail", "external_dependencies contains a malformed identifier"
        external_digests.add(normalized)
    resolved = 0
    skipped = 0
    for value in dependencies:
        normalized = digest(value)
        if normalized is None:
            return "fail", "dependencies contains a malformed identifier"
        if normalized in external_digests:
            skipped += 1
            continue
        if normalized not in reachable:
            return "fail", "dependency %s is not in the patch lineage before this patch" % short(normalized)
        ancestor = reachable[normalized]
        problem = structural_problem(ancestor)
        if problem:
            return "fail", "dependency %s is not a conforming patch (%s)" % (
                short(normalized), problem)
        actual = patch_id(ancestor, ctx)
        if actual is None or actual != normalized:
            return "fail", "dependency %s does not match its content address" % short(normalized)
        resolved += 1
    locations = 0
    undetermined = 0
    own = _touched(patch)
    for _parent, ancestor, ancestor_digest in ancestors:
        if ancestor_digest in external_digests:
            continue
        found, unknown = _overlap(own, _touched(ancestor))
        locations += found
        undetermined += unknown
    if undetermined:
        conflict = "overlap with an earlier patch undetermined without base shapes"
    elif locations:
        conflict = "%d overlapping location(s) with earlier patches" % locations
    else:
        conflict = "no overlap with earlier patches"
    detail = "dependencies resolve in order: %d" % resolved
    if skipped:
        detail += "; declared external: %d" % skipped
    detail += "; %s" % conflict
    return "pass", detail


def _member_matches(record, patch, member, store, ctx):
    reference = digest(patch.get(member + "_hash"))
    carried = patch.get(member) if member in patch else None
    record_value = record.get(member)
    expected = ctx.canonical_bytes(record_value)
    if carried is not None:
        try:
            if ctx.canonical_bytes(carried) != expected:
                return "the patch's %s differ from the record's" % member
        except (ValueError, TypeError):
            return "the patch's %s cannot be serialized" % member
    if reference is not None:
        path = store.resolve(reference)
        if not path:
            return "%s_hash does not resolve" % member
        try:
            with open(path, "rb") as handle:
                if handle.read() != expected:
                    return "%s_hash does not resolve to the record's %s" % (member, member)
        except OSError:
            return "%s_hash does not resolve" % member
    if carried is None and reference is None:
        return "the patch carries neither %s nor %s_hash" % (member, member)
    return ""


def check_p04(record, patch, store, ctx):
    for member in ("invariants", "falsifier"):
        problem = _member_matches(record, patch, member, store, ctx)
        if problem:
            return "fail", problem
    return "pass", "invariants and falsifier match the record"


def check_p05(record, patch, ancestors, store, ctx):
    inverse = patch.get("inverse")
    if not isinstance(inverse, dict) or inverse.get("kind") != "exact":
        return "not run", "no exact inverse is supplied; algebraic or absent"
    base = record.get("base") if isinstance(record.get("base"), dict) else {}
    base_digest = ctx.norm_hash(base.get("hash"))
    path = store.resolve(base_digest) if base_digest else None
    if not path:
        return "not run", "base bytes are not held in the store"
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError:
        return "not run", "base bytes are not readable"
    tensors, why = parse_container(raw, ctx)
    if tensors is None:
        return "not run", why
    for _parent, ancestor, ancestor_digest in ancestors:
        changed, why = apply_ops(tensors, ancestor.get("edit", {}).get("ops") or [], ctx)
        if why:
            return "not run", "ancestor patch %s does not apply to the base (%s)" % (
                short(ancestor_digest or ""), why)
    before = snapshot(tensors)
    changed, why = apply_ops(tensors, patch["edit"]["ops"], ctx)
    if why:
        return "fail", "the patch does not apply to its base (%s)" % why
    if changed == 0:
        return "fail", "the patch changes no weights"
    why = apply_prior(tensors, inverse.get("prior") or [], ctx)
    if why:
        return "fail", why
    after = snapshot(tensors)
    if after != before:
        differing = sorted(name for name in after if after[name] != before.get(name))
        return "fail", ("the exact inverse does not restore bit-identical weights "
                        "(tensor '%s')" % differing[0])
    return "pass", ("round-trip restores bit-identically; tensors: %d, values changed: %d"
                    % (len(after), changed))


# -------------------------------------------------------------- evaluation

def evaluate(record, store, ctx, schema=None):
    """The patch block for a record, or None when the payload is not a patch."""
    _digest, raw = payload_bytes(record, store, ctx)
    if raw is None:
        return None
    patch, _error = load_patch(raw, ctx)
    if patch is None:
        return None
    schema = schema if schema is not None else load_schema()
    ancestors, lineage_problem = patch_lineage(record, store, ctx)

    results = []
    results.append(("P-01", check_p01(record, patch, store, ctx)))
    results.append(("P-02", check_p02(patch, raw, ctx, schema)))
    if lineage_problem:
        results.append(("P-03", ("fail", lineage_problem)))
    else:
        results.append(("P-03", check_p03(patch, ancestors, store, ctx)))
    results.append(("P-04", check_p04(record, patch, store, ctx)))
    if lineage_problem:
        results.append(("P-05", ("not run", "the patch lineage does not resolve")))
    else:
        results.append(("P-05", check_p05(record, patch, ancestors, store, ctx)))

    by_id = {cid: (state, detail) for cid, (state, detail) in results}
    identifier = patch_id(patch, ctx)
    qualifiers = []
    if by_id["P-02"][0] == "pass":
        qualifiers.append("patch-executable")
        if by_id["P-03"][0] == "pass":
            qualifiers.append("stackable")
        if exact_inverse_problem(patch) == "" and by_id["P-05"][0] != "fail":
            qualifiers.append("reversible")

    return {
        "id": "wpp:sha256:%s" % identifier if identifier else "",
        "checks": [{"id": cid, "result": state, "detail": detail}
                   for cid, (state, detail) in results],
        "qualifiers": qualifiers,
        "failed": [cid for cid, (state, _detail) in results if state == "fail"],
        "not_run": [cid for cid, (state, _detail) in results if state == "not run"],
    }
