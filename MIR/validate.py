#!/usr/bin/env python3
"""MIR-1 conformance validator.

Implements checks C-01 through C-11 of MIR-1 (Model Intervention Records), and
the five checks P-01 through P-05 of MIR-1.1 when the `weights` payload declares
itself a Weight Patch. The patch block is reported beside the eleven and never
merged into them.
Python 3.8 or later. No third-party dependencies.

Usage:
    python3 validate.py RECORD.json [--artifacts DIR] [--execute-falsifier] [--json]

Exit code 0 when every check passes, 1 otherwise.

Note on C-04: by default the falsifier is checked for declaration only, not
executed. Running arbitrary commands from a record is a code-execution vector,
and a validator that does it by default cannot be run on untrusted input.
Pass --execute-falsifier to run it in a subprocess with a timeout.
"""

from __future__ import annotations

import argparse
import decimal
import hashlib
import http.client
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.parse

import patchcheck

SUITE_VERSION = "1.7.0"
MIR_VERSION = "1"
FALSIFIER_TIMEOUT_S = 30

HEX64 = re.compile(r"^[0-9a-f]{64}$")


# ---------------------------------------------------------------- primitives

def canonical_bytes(obj):
    """Canonical bytes as defined by MIR-1 section 4.13.

    Not json.dumps: that emits exponent notation for values below 1e-4 or at
    1e16 and above, and a record may write the same value without an exponent
    and still conform. The canonical form of a value must not depend on which
    spelling the record happened to use, so the expansion is done here.
    """
    out = []
    _emit(obj, out)
    return "".join(out).encode("utf-8")


_ESCAPES = {
    '"': '\\"',
    "\\": "\\\\",
    "\b": "\\b",
    "\f": "\\f",
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
}


def _canonical_string(value):
    out = ['"']
    for ch in value:
        esc = _ESCAPES.get(ch)
        if esc is not None:
            out.append(esc)
        elif ord(ch) < 0x20:
            out.append("\\u%04x" % ord(ch))
        elif 0xD800 <= ord(ch) <= 0xDFFF:
            raise ValueError("lone surrogate in string")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _canonical_number(value):
    if isinstance(value, int):
        return str(value)
    if value != value or value in (float("inf"), float("-inf")):
        raise ValueError("non-finite number")
    text = repr(value)  # shortest decimal that round-trips to the same float
    if "e" in text or "E" in text:
        text = format(decimal.Decimal(text), "f")
    if "." not in text:
        text += ".0"
    return text


def _emit(node, out):
    if node is None:
        out.append("null")
    elif node is True:
        out.append("true")
    elif node is False:
        out.append("false")
    elif isinstance(node, str):
        out.append(_canonical_string(node))
    elif isinstance(node, int):
        out.append(_canonical_number(node))
    elif isinstance(node, float):
        out.append(_canonical_number(node))
    elif isinstance(node, list):
        out.append("[")
        for i, item in enumerate(node):
            if i:
                out.append(",")
            _emit(item, out)
        out.append("]")
    elif isinstance(node, dict):
        out.append("{")
        for i, key in enumerate(sorted(node)):
            if not isinstance(key, str):
                raise ValueError("object key is not a string")
            if i:
                out.append(",")
            out.append(_canonical_string(key))
            out.append(":")
            _emit(node[key], out)
        out.append("}")
    else:
        raise ValueError("cannot canonicalize %r" % (type(node).__name__,))


def _reject_constant(name):
    # json.loads accepts NaN and Infinity. No other JSON parser does, and they
    # have no canonical spelling, so a record that contains them is not JSON.
    raise ValueError("non-JSON numeric constant %s" % name)


MAX_NESTING = 256


def _hex_unit(text, start):
    chunk = text[start:start + 4]
    if len(chunk) != 4:
        return None
    try:
        return int(chunk, 16)
    except ValueError:
        return None


def _scan_text(text):
    """Reject what the canonical form cannot represent, before parsing.

    Both implementations scan identically so a malformed record fails with the
    same detail in either. Without this, json.loads recurses until it crashes on
    deep input, and Go's decoder silently replaces a lone surrogate with U+FFFD.
    """
    depth = 0
    in_string = False
    i = 0
    while i < len(text):
        char = text[i]
        if not in_string:
            if char == '"':
                in_string = True
            elif char in "[{":
                depth += 1
                if depth > MAX_NESTING:
                    raise ValueError("record is nested too deeply")
            elif char in "]}":
                depth -= 1
        elif char == '"':
            in_string = False
        elif char == "\\":
            i += 1
            if i >= len(text):
                return
            if text[i] == "u":
                unit = _hex_unit(text, i + 1)
                if unit is None:
                    return
                i += 4
                if 0xDC00 <= unit <= 0xDFFF:
                    raise ValueError("record contains a lone surrogate")
                if 0xD800 <= unit <= 0xDBFF:
                    low = _hex_unit(text, i + 3) if text[i + 1:i + 3] == "\\u" else None
                    if low is None or not 0xDC00 <= low <= 0xDFFF:
                        raise ValueError("record contains a lone surrogate")
                    i += 6
        i += 1


def parse_record(raw):
    """Parse a record, failing in the classes both implementations report alike.

    The detail is language-independent so the two reports stay byte-identical on
    malformed input; the parser's own message is kept as the exception context.
    """
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("record is not valid UTF-8")
    _scan_text(text)
    try:
        return json.loads(text, parse_constant=_reject_constant)
    except ValueError:
        raise ValueError("record does not parse")


def norm_hash(value):
    if not isinstance(value, str):
        return None
    v = value.strip()
    if v.startswith("sha256:"):
        v = v[7:]
    v = v.lower()
    return v if HEX64.match(v) else None


class Store:
    """Content-addressed store: files are named by their lowercase hex digest.

    A digest resolves in one of two ways. Either the store holds the bytes under
    the digest, or it holds a locator named `<digest>.locator.json` that declares
    where the bytes are and what they should hash to. Locators exist because a
    checkpoint can be larger than anything a reviewer will download to check a
    record; they are verified over the network on request, not by trust.
    """

    LOCATOR_SUFFIX = ".locator.json"

    def __init__(self, roots):
        self.roots = [r for r in roots if r and os.path.isdir(r)]
        self.by_locator = 0
        self.verified = 0
        self.unverified = []

    def find(self, digest):
        if not digest:
            return None, None
        for root in self.roots:
            path = os.path.join(root, digest)
            if os.path.isfile(path):
                return "bytes", path
            path = os.path.join(root, digest + self.LOCATOR_SUFFIX)
            if os.path.isfile(path):
                return "locator", path
        return None, None

    def resolve(self, digest):
        kind, path = self.find(digest)
        return path if kind == "bytes" else None


def read_locator(path, digest):
    """Validate a locator file against the digest it is named for."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = fh.read()
    except OSError:
        return None, "locator unreadable"
    try:
        doc = json.loads(raw, parse_constant=_reject_constant)
    except ValueError:
        return None, "locator is not valid JSON"
    if not isinstance(doc, dict):
        return None, "locator is not an object"
    if doc.get("kind") != "mir-locator":
        return None, "not a mir-locator"
    if norm_hash(doc.get("sha256")) != digest:
        return None, "locator sha256 does not match its name"
    size = doc.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        return None, "locator size missing or invalid"
    url = doc.get("url")
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return None, "locator url missing or not http(s)"
    return doc, None


def remote_head(doc, digest, timeout=20):
    """Ask the host in a locator for the digest and the size, without downloading.

    A Hugging Face resolve URL answers a HEAD request with `x-linked-etag` on the
    redirect and the size on the final response, so this costs one request and no
    bytes. Any other host is accepted if it returns a matching ETag.
    """
    parts = urllib.parse.urlsplit(doc["url"])
    conn_cls = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
    path = parts.path + ("?" + parts.query if parts.query else "")
    conn = conn_cls(parts.netloc, timeout=timeout)
    try:
        conn.request("HEAD", path, headers={"User-Agent": "mir-1/1.1"})
        resp = conn.getresponse()
        etag = (resp.getheader("x-linked-etag") or resp.getheader("etag") or "")
        linked = resp.getheader("x-linked-size")
        length = resp.getheader("content-length")
        status = resp.status
    except (OSError, http.client.HTTPException) as exc:
        return False, "remote check failed (%s)" % exc
    finally:
        conn.close()

    etag = etag.strip().strip('"').lower()
    if etag.startswith("w/"):
        etag = etag[2:].strip('"')
    if etag != digest:
        return False, "host reports etag %r for %s" % (etag[:16] or None, digest[:16])

    declared = doc["size"]
    if linked is not None and linked.isdigit() and int(linked) != declared:
        return False, "host reports size %s, locator declares %d" % (linked, declared)
    if linked is None and status == 200 and length is not None and length.isdigit():
        if int(length) != declared:
            return False, "host reports size %s, locator declares %d" % (length, declared)
    return True, ""


# ------------------------------------------------------------------- checks

def check_c01(rec):
    if not isinstance(rec, dict):
        return False, "record is not a JSON object"
    declared = rec.get("id")
    if declared is None:
        return True, "parses; no id declared"
    body = {k: v for k, v in rec.items() if k != "id"}
    try:
        actual = hashlib.sha256(canonical_bytes(body)).hexdigest()
    except (ValueError, TypeError):
        return False, "record contains a number that cannot be represented"
    if norm_hash(declared) != actual:
        return False, "id does not match the content address"
    return True, "parses; id matches content address"


def check_c02(rec, schema=None):
    """The record matches the schema in section 4.

    The schema is the published shape, and this check runs it rather than
    restating it. A second copy of the rules in code is a second place for them
    to drift, which is what happened when `claimant` became required: both
    implementations kept their own list and both kept the old one.
    """
    schema = schema if schema is not None else load_schema()
    problem = _schema_problem(rec, schema, schema, "/")
    if problem:
        return False, problem
    return True, "matches the schema"


def _hash_fields(rec):
    """Every hash the record declares, by path.

    Two sources. The structural fields a record cannot omit: the base, the
    intervention payload, the harness, and the three inputs of each run. And any
    other string in the record written as `sha256:<digest>`, so a record cannot
    carry a hash outside the checked fields and be treated as if it had not.
    """
    out = {}
    base = rec.get("base") if isinstance(rec.get("base"), dict) else {}
    out["base.hash"] = base.get("hash")
    it = rec.get("intervention") if isinstance(rec.get("intervention"), dict) else {}
    out["intervention.payload_hash"] = it.get("payload_hash")
    h = rec.get("harness") if isinstance(rec.get("harness"), dict) else {}
    out["harness.hash"] = h.get("hash")
    if "supersedes" in rec:
        out["supersedes"] = rec.get("supersedes")
    runs = rec.get("runs") if isinstance(rec.get("runs"), list) else []
    for i, run in enumerate(runs):
        if not isinstance(run, dict):
            out["runs[%d]" % i] = None
            continue
        for field in ("harness_hash", "base_hash", "intervention_hash"):
            out["runs[%d].%s" % (i, field)] = run.get(field)

    # The schema accepts a lineage digest with or without the `sha256:` prefix.
    # Collecting only prefixed strings let a bare-hex entry name a file whose
    # bytes were never checked against it, so C-03 reported a resolved lineage
    # that did not resolve. Normalise here so both spellings are verified.
    lineage = rec.get("lineage") if isinstance(rec.get("lineage"), list) else []
    for i, entry in enumerate(lineage):
        digest = norm_hash(entry)
        if digest is not None:
            out["lineage[%d]" % i] = "sha256:" + digest

    extra = {}

    def walk(node, path):
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, path + "." + key if path else key)
        elif isinstance(node, list):
            for i, value in enumerate(node):
                walk(value, "%s[%d]" % (path, i))
        elif isinstance(node, str) and node.strip().lower().startswith("sha256:"):
            extra.setdefault(path, node)

    walk(rec, "")
    # Canonical form sorts keys, so document order is not a property of the
    # record. Sorting the discovered paths keeps the report a function of the
    # canonical bytes, which is what C-09 asserts when it re-imports.
    for path in sorted(extra):
        out.setdefault(path, extra[path])
    return out


def check_c03(rec, store, verify_remote=False):
    items = _hash_fields(rec)
    # The record's own id is a content address of itself, checked by C-01. It is
    # not required to be present in a store: a stranger's first copy of a record
    # is the file they were handed, not an entry in a registry.
    items.pop("id", None)
    bad = []
    located = 0
    verified = 0
    unverified = []
    for name, value in items.items():
        if value is None:
            # An explicit null is declared absence, not a malformed hash. The
            # schema decides where null is allowed; C-03 decides what resolves.
            if name.endswith("intervention_hash") or name == "supersedes":
                continue
            bad.append(name + " (null)")
            continue
        digest = norm_hash(value)
        if digest is None:
            bad.append(name + " (malformed)")
            continue
        kind, path = store.find(digest)
        if kind is None:
            bad.append(name + " (not in store)")
            continue
        if kind == "locator":
            doc, why = read_locator(path, digest)
            if doc is None:
                bad.append("%s (%s)" % (name, why))
                continue
            located += 1
            if verify_remote:
                ok, why = remote_head(doc, digest)
                if not ok:
                    bad.append("%s (%s)" % (name, why))
                    continue
                verified += 1
            else:
                unverified.append(name)
        elif kind == "bytes":
            if _file_digest(path) != digest:
                bad.append(name + " (bytes do not match the digest)")
    if bad:
        return False, "%d of %d do not resolve: %s" % (len(bad), len(items), ", ".join(bad[:6]))
    detail = "%d/%d hashes resolve" % (len(items), len(items))
    if located:
        if verify_remote:
            detail += "; %d by locator, %d verified against the host" % (located, verified)
        else:
            detail += "; %d by locator, not checked against the host (--verify-remote)" % located
    return True, detail


def check_c04(rec, execute=False):
    f = rec.get("falsifier")
    if not isinstance(f, dict):
        return False, "falsifier is not an object"
    cmd = f.get("command")
    if not isinstance(cmd, str) or not cmd.strip():
        return False, "falsifier.command missing or empty"
    if f.get("returns") != "boolean":
        return False, "falsifier.returns must be 'boolean'"
    if not execute:
        return True, "declared, returns boolean (not executed; pass --execute-falsifier)"
    try:
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                              timeout=FALSIFIER_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return False, "falsifier exceeded %ds" % FALSIFIER_TIMEOUT_S
    out = (proc.stdout or "").strip().lower()
    if out not in ("true", "false", "1", "0"):
        return False, "falsifier output %r is not boolean" % (out[:40],)
    return True, "executed; returned %s" % out


def check_c05(rec):
    inv = rec.get("invariants")
    if not isinstance(inv, list) or not inv:
        return False, "invariants missing or empty"
    claim = rec.get("claim") if isinstance(rec.get("claim"), dict) else {}
    scored = claim.get("scoring_metrics")
    if not isinstance(scored, list) or not scored:
        return False, "claim.scoring_metrics missing or empty"
    scored = set(m for m in scored if isinstance(m, str))
    behavior = claim.get("behavior")
    if behavior not in scored:
        return False, ('claim.behavior "%s" is not among claim.scoring_metrics'
                       % (behavior,))
    problems = []
    outside = 0
    for i, item in enumerate(inv):
        if not isinstance(item, dict):
            problems.append("[%d] not an object" % i)
            continue
        for key in ("property", "measurement", "metric", "direction", "bound"):
            if key not in item:
                problems.append("[%d] missing %s" % (i, key))
        metric = item.get("metric")
        direction = item.get("direction")
        if direction not in ("floor", "ceiling", "delta"):
            problems.append("[%d] direction not one of floor|ceiling|delta" % i)
        bound = item.get("bound")
        if not isinstance(bound, (int, float)) or isinstance(bound, bool):
            problems.append("[%d] bound not numeric" % i)
        if isinstance(metric, str) and metric != "" and metric not in scored:
            outside += 1
    if problems:
        return False, "; ".join(problems[:3])
    if outside == 0:
        return False, ("no invariant outside the scoring function "
                       "(%d declared, all inside)" % len(inv))
    return True, ("%d invariants, %d outside scoring "
                  "(scoring function declares %d)" % (len(inv), outside, len(scored)))


def _file_digest(path):
    """The SHA-256 of the bytes on disk.

    A store entry is content-addressed only if its bytes hash to the name it is
    filed under. Checking the name alone makes the store a list of filenames.
    """
    hasher = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            hasher.update(block)
    return hasher.hexdigest()


def _present(store, digest):
    return digest is not None and store.find(digest)[0] is not None


def looks_like_record(document):
    return (isinstance(document, dict)
            and "mir_version" in document
            and "claim" in document
            and "runs" in document)


def _lineage_walk(rec, store, seen, depth):
    """Every chain of parents must be records and must end at a base artifact."""
    lineage = rec.get("lineage")
    if not isinstance(lineage, list):
        return False, "lineage is not a list"
    if not lineage:
        base = rec.get("base") if isinstance(rec.get("base"), dict) else {}
        digest = norm_hash(base.get("hash"))
        if _present(store, digest):
            return True, 0
        return False, "a chain ends at a base that does not resolve"
    if depth > 32:
        return False, "lineage is deeper than 32 records"
    parents = 0
    for entry in lineage:
        digest = norm_hash(entry)
        if digest is None:
            return False, "malformed lineage entry"
        if digest in seen:
            return False, "lineage contains a cycle"
        kind, path = store.find(digest)
        if kind != "bytes":
            return False, ("lineage entry %s is not readable bytes"
                           % digest[:12])
        try:
            with open(path, "r", encoding="utf-8") as handle:
                parent = json.load(handle)
        except (OSError, ValueError):
            return False, "lineage entry %s is not JSON" % digest[:12]
        if not looks_like_record(parent):
            return False, "lineage entry %s is not a record" % digest[:12]
        ok, nested = _lineage_walk(parent, store, seen | {digest}, depth + 1)
        if not ok:
            return False, nested
        parents += 1 + nested
    return True, parents


def check_c06(rec, store):
    lin = rec.get("lineage")
    if not isinstance(lin, list):
        return False, "lineage is not a list"
    if not lin:
        base = rec.get("base") if isinstance(rec.get("base"), dict) else {}
        digest = norm_hash(base.get("hash"))
        if _present(store, digest):
            return True, "empty lineage; applies directly to base"
        return False, "empty lineage and base does not resolve"
    ok, detail = _lineage_walk(rec, store, frozenset(), 0)
    if not ok:
        return False, detail
    return True, "lineage resolves to a base (%d parent record(s))" % detail


def check_c07(rec):
    runs = rec.get("runs")
    if not isinstance(runs, list) or not runs:
        return False, "no runs"
    missing = []
    undisclosed = []
    invalid = []
    for i, run in enumerate(runs):
        if not isinstance(run, dict):
            return False, "runs[%d] is not an object" % i
        for key in ("cost", "wall_time_s"):
            if key not in run:
                missing.append("runs[%d].%s" % (i, key))
                continue
            value = run[key]
            if value is None:
                undisclosed.append("runs[%d].%s" % (i, key))
            elif not isinstance(value, (int, float)) or isinstance(value, bool):
                invalid.append("runs[%d].%s" % (i, key))
            elif value < 0 or (key == "wall_time_s" and value == 0):
                # A run that executed took time. Zero cost is real on owned
                # hardware; zero duration is not, and the pair is how a record
                # discloses nothing while satisfying a disclosure check.
                invalid.append("runs[%d].%s" % (i, key))
    if missing or invalid:
        return False, "missing: %s; non-numeric or out of range: %s" % (
            ", ".join(missing) or "none", ", ".join(invalid) or "none")
    if undisclosed:
        # MIR-1-04: an undisclosed run counts toward no requirement. The field is
        # present and null so that the omission is visible in the record rather
        # than absent from it; the check still fails.
        return False, "%d of %d runs declare cost or wall time as undisclosed: %s" % (
            len({p.split(".")[0] for p in undisclosed}), len(runs), ", ".join(undisclosed[:6]))
    return True, "cost and wall_time_s present on %d run(s)" % len(runs)


def check_c08(rec, store):
    digest = norm_hash(rec.get("manifest_hash"))
    if digest is None:
        return False, "manifest_hash missing or malformed"
    if not _present(store, digest):
        return False, "manifest hash does not resolve"
    return True, "manifest hash resolves"



# ------------------------------------------------------- schema conformance

SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.json")

# The keywords the walker implements. A schema that grows one outside this set
# is a schema this suite silently ignores, so the tests compare the two.
SCHEMA_KEYWORDS = frozenset([
    "$ref", "oneOf", "type", "const", "enum", "minLength", "pattern",
    "minimum", "exclusiveMinimum", "minItems", "uniqueItems", "items",
    "required", "properties",
    "additionalProperties",
])
SCHEMA_METADATA = frozenset(["$schema", "$id", "title", "description", "definitions"])
JSON_TYPES = ("object", "array", "string", "number", "integer", "boolean", "null")


def load_schema(path=None):
    with open(path or SCHEMA_PATH, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _actual_type(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "integer" if value.is_integer() else "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "unknown"


def _join(path, key):
    return ("" if path == "/" else path) + "/" + str(key)


def _resolves(ref, root):
    node = root
    for part in ref.lstrip("#/").split("/"):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _show(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _type_ok(value, wanted):
    actual = _actual_type(value)
    if wanted == "number":
        return actual in ("number", "integer")
    if wanted == "integer":
        return actual == "integer"
    return actual == wanted


def _schema_problem(value, schema, root, path="/"):
    """The first place the value does not match the schema, or an empty string.

    Only the keywords this schema uses are implemented: type, required,
    properties, additionalProperties, enum, const, minLength, pattern, minimum,
    minItems, uniqueItems, items, oneOf, and $ref. A schema that grows a keyword
    outside this list is a schema this suite cannot check, and the test that
    compares the two implementations is what notices.
    """
    if not isinstance(schema, dict):
        return ""
    if "$ref" in schema:
        target = _resolves(schema["$ref"], root)
        if target is None:
            return "%s: unresolvable reference %s" % (path, schema["$ref"])
        return _schema_problem(value, target, root, path)
    if "oneOf" in schema:
        matches = sum(1 for alternative in schema["oneOf"]
                      if not _schema_problem(value, alternative, root, path))
        if matches != 1:
            return ("%s: matches %d of %d alternatives"
                    % (path, matches, len(schema["oneOf"])))
    if "type" in schema:
        wanted = schema["type"]
        if isinstance(wanted, list):
            if not any(_type_ok(value, item) for item in wanted):
                return "%s: expected %s, got %s" % (path, " or ".join(wanted), _actual_type(value))
        elif not _type_ok(value, wanted):
            return "%s: expected %s, got %s" % (path, wanted, _actual_type(value))
    if "const" in schema and value != schema["const"]:
        return "%s: expected %s, got %s" % (path, _show(schema["const"]), _show(value))
    if "enum" in schema and value not in schema["enum"]:
        allowed = ", ".join(_show(item) for item in schema["enum"])
        return "%s: %s is not one of %s" % (path, _show(value), allowed)
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            return "%s: shorter than %d character(s)" % (path, schema["minLength"])
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            return "%s: does not match the pattern" % path
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            return "%s: less than %s" % (path, _show(schema["minimum"]))
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            return "%s: not greater than %s" % (path, _show(schema["exclusiveMinimum"]))
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            return "%s: fewer than %d item(s)" % (path, schema["minItems"])
        if schema.get("uniqueItems"):
            seen = []
            for item in value:
                shown = _show(item)
                if shown in seen:
                    return "%s: duplicate item %s" % (path, shown)
                seen.append(shown)
        if "items" in schema:
            for index, item in enumerate(value):
                problem = _schema_problem(item, schema["items"], root, _join(path, index))
                if problem:
                    return problem
    if isinstance(value, dict):
        for name in schema.get("required", []):
            if name not in value:
                return "%s: missing required field %s" % (path, _show(name))
        declared = schema.get("properties")
        if schema.get("additionalProperties") is False and isinstance(declared, dict):
            for name in sorted(value):
                if name not in declared:
                    return "%s: unexpected field %s" % (path, _show(name))
        if isinstance(declared, dict):
            for name in sorted(declared):
                if name in value:
                    problem = _schema_problem(value[name], declared[name], root, _join(path, name))
                    if problem:
                        return problem
    return ""


# -------------------------------------------------------------- aggregation

UNDISCLOSED = frozenset([
    "", "not disclosed", "undisclosed", "not stated", "unknown", "none",
    "n/a", "na", "null", "anonymous", "withheld", "unattributed",
])


def _disclosed_run(run):
    """MIR-1-04: a run that discloses neither cost nor wall time counts toward
    no requirement, so it cannot count toward independence either."""
    for key in ("cost", "wall_time_s"):
        value = run.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return False
    return run.get("cost") >= 0 and run.get("wall_time_s") > 0


def _fold(value):
    """Trim and full-case-fold: the comparison MIR-1-05 makes.

    An operator or a funding source that differs only in case or in surrounding
    whitespace names the same entity. Comparing operators case-sensitively let a
    claimant reach `replicated` by re-spelling its own name.
    """
    return value.strip().casefold()


def _disclosed(value):
    """A funding source counts only when it names something."""
    if not isinstance(value, str):
        return False
    return _fold(value) not in UNDISCLOSED


def _manifest_min_replications(rec, store):
    """The registry's replication threshold.

    Returns None when the manifest cannot be read, which is not the same as a
    threshold of one: a record could otherwise hold its manifest as a locator
    and be measured against a lower bar than the manifest states.
    """
    digest = norm_hash(rec.get("manifest_hash"))
    path = store.resolve(digest) if digest else None
    if not path:
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            manifest = json.load(fh)
        value = (manifest.get("parameters") or {}).get("min_independent_replications")
    except (OSError, ValueError, AttributeError):
        return None
    if isinstance(value, bool):
        return 1
    if isinstance(value, int):
        number = value
    elif isinstance(value, float) and value.is_integer():
        number = int(value)
    else:
        return None
    return number if number >= 1 else 1


def check_c10(rec, store):
    """Status coherence. C-06 says whether lineage resolves; this says what the
    status is allowed to be, given the runs the record carries."""
    status = rec.get("status")
    if not isinstance(status, str) or not status:
        return False, "status missing or empty"
    if status == "draft":
        return True, "status 'draft' makes no claim"
    lineage_ok, _ = check_c06(rec, store)
    if status == "orphan":
        if lineage_ok:
            return False, "status 'orphan' with lineage that resolves"
        return True, "status 'orphan'; lineage does not resolve"
    if not lineage_ok:
        return False, ("status '%s' requires lineage that resolves; MIR-1-06 "
                       "requires the status orphan" % status)
    if status == "submitted":
        return True, "status 'submitted'; lineage resolves"
    claimant = rec.get("claimant")
    if not isinstance(claimant, dict):
        return False, "claimant missing"
    operator = claimant.get("operator")
    funding = claimant.get("funding_source")
    if not isinstance(operator, str) or not operator.strip():
        return False, "claimant.operator missing or empty"
    if not isinstance(funding, str) or not funding.strip():
        return False, "claimant.funding_source missing or empty"
    if not _disclosed(funding):
        return False, ("claimant.funding_source is not a disclosed source, so "
                       "independence cannot be established against it")
    runs = rec.get("runs") if isinstance(rec.get("runs"), list) else []
    independent = 0
    undisclosed = 0
    for run in runs:
        if not isinstance(run, dict):
            continue
        if run.get("intervention_hash") is None:
            continue  # baseline: measures the base, never applies the claim
        if not _disclosed_run(run):
            undisclosed += 1
            continue
        other_operator = run.get("operator")
        other_funding = run.get("funding_source")
        if not isinstance(other_operator, str) or _fold(other_operator) == _fold(operator):
            continue
        if not _disclosed(other_funding):
            continue
        if _fold(other_funding) == _fold(funding):
            continue
        independent += 1
    required = _manifest_min_replications(rec, store)
    if required is None:
        return False, ("the manifest is not held as bytes, so the replication "
                       "threshold cannot be read")
    if independent < required:
        detail = ("status 'replicated' with %d independent run(s); the "
                  "declared manifest requires %d" % (independent, required))
        if undisclosed:
            detail += " (%d run(s) not counted: cost or wall time undisclosed)" % undisclosed
        return False, detail
    detail = ("status 'replicated'; %d independent run(s), %d required"
              % (independent, required))
    if undisclosed:
        detail += " (%d run(s) not counted: cost or wall time undisclosed)" % undisclosed
    return True, detail


def check_c11(rec):
    """The claim's metric is reported by the runs.

    A claim names a behavior and a threshold. Without this check the number the
    claim is about need not appear anywhere in the record, so a record could
    assert an improvement in a quantity no run measured."""
    claim = rec.get("claim") if isinstance(rec.get("claim"), dict) else {}
    behavior = claim.get("behavior")
    if not isinstance(behavior, str) or not behavior.strip():
        return False, "claim.behavior missing or empty"
    runs = rec.get("runs") if isinstance(rec.get("runs"), list) else []
    if not runs:
        return False, "runs missing or empty"
    missing = []
    for index, run in enumerate(runs):
        result = run.get("result") if isinstance(run, dict) else None
        if not isinstance(result, dict):
            missing.append(index)
            continue
        value = result.get(behavior)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            missing.append(index)
    if missing:
        return False, ("%d of %d run(s) do not report claim.behavior '%s': %s"
                       % (len(missing), len(runs), behavior,
                          ", ".join("runs[%d]" % i for i in missing[:3])))
    return True, "all %d run(s) report '%s'" % (len(runs), behavior)

PATCH_CONTEXT = patchcheck.Context(canonical_bytes, parse_record, norm_hash,
                                   _schema_problem)


def run_checks(rec, store, execute_falsifier=False, include_c09=True, verify_remote=False):
    results = [
        ("C-01", check_c01(rec)),
        ("C-02", check_c02(rec)),
        ("C-03", check_c03(rec, store, verify_remote)),
        ("C-04", check_c04(rec, execute_falsifier)),
        ("C-05", check_c05(rec)),
        ("C-06", check_c06(rec, store)),
        ("C-07", check_c07(rec)),
        ("C-08", check_c08(rec, store)),
    ]
    if include_c09:
        results.append(("C-09", check_c09(rec, store, execute_falsifier, verify_remote)))
    results.append(("C-10", check_c10(rec, store)))
    results.append(("C-11", check_c11(rec)))
    return results


def check_c09(rec, store, execute_falsifier=False, verify_remote=False):
    try:
        payload = canonical_bytes(rec)
    except (ValueError, TypeError):
        return False, "record contains a number that cannot be represented"
    handle, path = tempfile.mkstemp(suffix=".json")
    try:
        with os.fdopen(handle, "wb") as fh:
            fh.write(payload)
        with open(path, "rb") as fh:
            reloaded_bytes = fh.read()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass

    if reloaded_bytes != payload:
        return False, "export/import is not byte-identical"
    try:
        reloaded = json.loads(reloaded_bytes, parse_constant=_reject_constant)
    except Exception as exc:  # noqa: BLE001
        return False, "re-import failed: %s" % exc
    try:
        reimported = canonical_bytes(reloaded)
    except (ValueError, TypeError):
        return False, "re-import contains a number that cannot be represented"
    if reimported != payload:
        return False, "re-import is not canonical"

    before = run_checks(rec, store, execute_falsifier, include_c09=False, verify_remote=verify_remote)
    after = run_checks(reloaded, store, execute_falsifier, include_c09=False, verify_remote=verify_remote)
    if before != after:
        return False, "results differ after round-trip"

    # The patch block is part of the report, so a round-trip that reproduced
    # the eleven checks and changed the patch block would still have changed
    # the answer. Compare it on the same pair of documents.
    patch_before = patchcheck.evaluate(rec, store, PATCH_CONTEXT)
    patch_after = patchcheck.evaluate(reloaded, store, PATCH_CONTEXT)
    if patch_before != patch_after:
        return False, "patch results differ after round-trip"
    if record_qualifiers(rec) != record_qualifiers(reloaded):
        return False, "qualifiers differ after round-trip"
    return True, "byte-identical round-trip; results reproduce"


# --------------------------------------------------------- record qualifiers

def _reports_number(run, metric):
    result = run.get("result") if isinstance(run.get("result"), dict) else {}
    value = result.get(metric) if isinstance(metric, str) else None
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def record_qualifiers(rec):
    """Derived, report-only refinements of a MIR-1 record (MIR-1.2).

    None of these changes a check, a status, or an id. Each is a measurement the
    evidence already carries, named so that a reader does not have to recompute
    it: whether a baseline exists, whether every run measured one population,
    whether another operator reproduced the claim without a disclosed cost, and
    whether the invariants were re-measured rather than only the target metric.
    """
    runs = rec.get("runs") if isinstance(rec.get("runs"), list) else []
    runs = [run for run in runs if isinstance(run, dict)]
    if not runs:
        return []
    claim = rec.get("claim") if isinstance(rec.get("claim"), dict) else {}
    behavior = claim.get("behavior")
    claimant = rec.get("claimant") if isinstance(rec.get("claimant"), dict) else {}
    operator = claimant.get("operator")
    funding = claimant.get("funding_source")

    out = []
    if any(run.get("intervention_hash") is None for run in runs):
        out.append("baseline-present")

    populations = set()
    for run in runs:
        result = run.get("result") if isinstance(run.get("result"), dict) else {}
        units = result.get("n_units")
        samples = result.get("samples_per_unit")
        if not isinstance(units, int) or isinstance(units, bool):
            populations = None
            break
        if not isinstance(samples, int) or isinstance(samples, bool):
            populations = None
            break
        populations.add((units, samples))
    if populations and len(populations) == 1:
        out.append("single-population")

    # "Another operator" needs a named operator to differ from. With none, the
    # relation is undefined, and the same guard already governs invariants-replicated.
    other = []
    if isinstance(operator, str) and operator.strip():
        for run in runs:
            if run.get("intervention_hash") is None:
                continue
            value = run.get("operator")
            if not isinstance(value, str):
                continue
            if _fold(value) == _fold(operator):
                continue
            other.append(run)
    if any(not _disclosed_run(run) and _reports_number(run, behavior) for run in other):
        out.append("unpriced-reproduction")

    counted = []
    if isinstance(operator, str) and isinstance(funding, str) and _disclosed(funding):
        for run in other:
            if not _disclosed_run(run):
                continue
            run_funding = run.get("funding_source")
            if not _disclosed(run_funding):
                continue
            if _fold(run_funding) == _fold(funding):
                continue
            counted.append(run)
    metrics = []
    invariants = rec.get("invariants") if isinstance(rec.get("invariants"), list) else []
    for item in invariants:
        if isinstance(item, dict) and isinstance(item.get("metric"), str):
            metrics.append(item["metric"])
    if metrics and any(all(_reports_number(run, metric) for metric in metrics)
                       for run in counted):
        out.append("invariants-replicated")
    return out


# ---------------------------------------------------------------------- main

def main(argv=None):
    parser = argparse.ArgumentParser(description="MIR-1 conformance validator")
    parser.add_argument("record", help="path to a MIR-1 record (JSON)")
    parser.add_argument("--artifacts", action="append", default=[],
                        help="artifact store directory (repeatable)")
    parser.add_argument("--execute-falsifier", action="store_true",
                        help="run falsifier.command (arbitrary code; trusted input only)")
    parser.add_argument("--verify-remote", action="store_true",
                        help="for artifacts held as locators, ask the host for the digest (no download)")
    parser.add_argument("--json", action="store_true", help="emit a JSON report")
    args = parser.parse_args(argv)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    roots = list(args.artifacts) + [
        os.path.join(os.getcwd(), "artifacts"),
        os.path.join(script_dir, "artifacts"),
        os.path.join(os.path.dirname(os.path.abspath(args.record)), "artifacts"),
    ]
    store = Store(roots)

    try:
        with open(args.record, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        print("cannot read record: %s" % exc, file=sys.stderr)
        return 2

    try:
        rec = parse_record(raw)
    except ValueError as exc:
        if exc.__context__ is not None:
            print("parse error: %s" % exc.__context__, file=sys.stderr)
        report = {
            "suite": SUITE_VERSION,
            "record": args.record,
            "checks": [{"id": "C-01", "ok": False, "detail": "invalid JSON: %s" % exc}],
            "pass": False,
        }
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print("C-01 FAIL  invalid JSON: %s" % exc)
            print("RESULT: FAIL")
        return 1

    results = run_checks(rec, store, args.execute_falsifier, verify_remote=args.verify_remote)
    failed = [cid for cid, (ok, _) in results if not ok]
    qualifiers = record_qualifiers(rec)
    patch_block = patchcheck.evaluate(rec, store, PATCH_CONTEXT)
    report = {
        "suite": SUITE_VERSION,
        "mir_version": MIR_VERSION,
        "record": args.record,
        "manifest_hash": rec.get("manifest_hash"),
        "checks": [{"id": cid, "ok": ok, "detail": detail}
                   for cid, (ok, detail) in results],
    }
    if qualifiers:
        report["qualifiers"] = qualifiers
    if patch_block is not None:
        report["patch"] = patch_block
    report["pass"] = not failed and not (patch_block and patch_block["failed"])
    report["failed"] = failed

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("MIR-1 conformance   suite %s   record %s" % (SUITE_VERSION, args.record))
        for cid, (ok, detail) in results:
            print("%s %s  %s" % (cid, "PASS" if ok else "FAIL", detail))
        if qualifiers:
            print("record qualifiers   %s" % ", ".join(qualifiers))
        if patch_block is not None:
            print("MIR-1.1 patch   %s   qualifiers: %s" % (
                patch_block["id"] or "no id",
                ", ".join(patch_block["qualifiers"]) or "none"))
            for check in patch_block["checks"]:
                print("%s %s  %s" % (check["id"], check["result"].upper(),
                                      check["detail"]))
        verdict = "PASS" if not failed and not (patch_block and patch_block["failed"]) else "FAIL"
        # The first pair keeps MIR-1's reading: on FAIL it counts the failed
        # checks, on PASS it counts the total. The patch pair is labelled so
        # that the two numbers cannot be read as the same quantity.
        summary = "(%d of %d" % (len(results) if verdict == "PASS" else len(failed), len(results))
        if patch_block is not None:
            passed = sum(1 for check in patch_block["checks"] if check["result"] == "pass")
            summary += ", patch %d of %d passed" % (passed, len(patch_block["checks"]))
            if patch_block["not_run"]:
                summary += ", %d not run" % len(patch_block["not_run"])
        summary += ")"
        print("RESULT: %s %s" % (verdict, summary))

    if failed or (patch_block and patch_block["failed"]):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
