#!/usr/bin/env python3
"""Random documents for the differential test in crosscheck.py.

Two generators, because one shape cannot exercise both halves of the suite.

random_document builds arbitrary JSON: integers too large for a machine word,
doubles whose shortest form needs an exponent, control characters, lone quotes
and backslashes, non-ASCII, U+2028. None of it is a MIR-1 record. Measured over
200 seeds, every one of the eleven checks returned exactly one distinct detail
message -- the "field missing" branch -- and nine checks were never seen to
pass. It stresses canonical form (C-01, C-09) and nothing else.

random_record starts from examples/conforming.json, a record that passes all
eleven, and mutates it. The mutations aim at what arbitrary shapes never reach:
hashes that resolve or do not, lineage that walks or breaks, invariants inside
or outside the scoring function, runs that are independent or not, funding that
names something or does not.

crosscheck.py puts a correct id on each document, so a single byte of
disagreement about canonical form shows up as C-01 failing in one implementation
and passing in the other.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import struct

HERE = os.path.dirname(os.path.abspath(__file__))
SEED_PATH = os.path.join(HERE, "examples", "conforming.json")
STORE_DIR = os.path.join(HERE, "records", "artifacts")

ALPHABET = ["a", "Z", "0", "\u00e9", "\u064a", "\u4e2d", "\U0001f642",
            "\u2028", "\u007f", " ", '"', "\\", "\n", "\t"]
AWKWARD_NUMBERS = [
    1e-7, 1e-320, 1e16, 1e21, 5e-324, 2.2250738585072014e-308,
    1.7976931348623157e308, 0.1, 1 / 3, 0.0, -0.0, 100.0, 1e2,
]

# Funding values on both sides of the normalisation line. The first group names
# nothing once trimmed and folded: U+017F folds to s, and U+00A0 / U+001F are
# stripped by Python but not by Go's unicode.IsSpace. The second group must NOT
# be treated as undisclosed -- casefold is not compatibility normalisation, so
# fullwidth stays fullwidth, and U+0130 expands to i plus a combining dot.
FUNDING_TRAPS = [
    "not disclosed", "NOT DISCLOSED", "  unknown  ", "n/a", "anonymous",
    "not \u017ftated", "none\u00a0", "\u001fnot stated", "WITHHELD", "unattributed",
    "\uff2e\uff4f\uff4e\uff45", "und\u0130sclosed", "Acme Research Fund",
]


# ------------------------------------------------------- arbitrary JSON shapes

def random_string(rng):
    return "".join(rng.choice(ALPHABET) for _ in range(rng.randrange(0, 6)))


def random_number(rng):
    kind = rng.randrange(5)
    if kind == 0:
        return rng.randint(-1000, 1000)
    if kind == 1:
        return rng.randint(-10 ** 30, 10 ** 30)
    if kind == 2:
        return rng.uniform(-1e6, 1e6)
    if kind == 3:
        bits = rng.getrandbits(64)
        value = struct.unpack("<d", struct.pack("<Q", bits))[0]
        while not math.isfinite(value):
            bits = rng.getrandbits(64)
            value = struct.unpack("<d", struct.pack("<Q", bits))[0]
        return value
    return rng.choice(AWKWARD_NUMBERS)


def random_value(rng, depth):
    choices = ["null", "bool", "number", "string"]
    if depth > 0:
        choices += ["list", "object"]
    kind = rng.choice(choices)
    if kind == "null":
        return None
    if kind == "bool":
        return rng.choice([True, False])
    if kind == "number":
        return random_number(rng)
    if kind == "string":
        return random_string(rng)
    if kind == "list":
        return [random_value(rng, depth - 1) for _ in range(rng.randrange(0, 4))]
    return {random_string(rng): random_value(rng, depth - 1)
            for _ in range(rng.randrange(0, 4))}


def random_document(seed):
    rng = random.Random(seed)
    document = {random_string(rng): random_value(rng, 3) for _ in range(rng.randrange(1, 5))}
    if not document:
        document = {"a": 1}
    return document


def reidentify(document, canonical_bytes):
    body = {key: value for key, value in document.items() if key != "id"}
    digest = hashlib.sha256(canonical_bytes(body)).hexdigest()
    document["id"] = "sha256:" + digest
    return document


# ------------------------------------------------------------- mutated records

_SEED_TEXT = None
_LOCATORS = None


def seed_record():
    global _SEED_TEXT
    if _SEED_TEXT is None:
        with open(SEED_PATH, encoding="utf-8") as handle:
            _SEED_TEXT = handle.read()
    return json.loads(_SEED_TEXT)


def locator_digests():
    """Digests the store holds as locators rather than bytes."""
    global _LOCATORS
    if _LOCATORS is None:
        _LOCATORS = []
        suffix = ".locator.json"
        if os.path.isdir(STORE_DIR):
            for name in sorted(os.listdir(STORE_DIR)):
                if name.endswith(suffix):
                    _LOCATORS.append(name[:-len(suffix)])
    return _LOCATORS


def unknown_digest(rng):
    return "sha256:" + hashlib.sha256(str(rng.getrandbits(128)).encode()).hexdigest()


def assign(record, path, value):
    node = record
    for part in path[:-1]:
        if isinstance(part, int):
            if not isinstance(node, list) or not -len(node) <= part < len(node):
                return
            node = node[part]
        else:
            if not isinstance(node, dict):
                return
            node = node.get(part)
    last = path[-1]
    if isinstance(last, int):
        if isinstance(node, list) and -len(node) <= last < len(node):
            node[last] = value
    elif isinstance(node, dict):
        node[last] = value


def some_run(record, rng):
    runs = record.get("runs")
    if isinstance(runs, list):
        objects = [run for run in runs if isinstance(run, dict)]
        if objects:
            return rng.choice(objects)
    return None


def some_invariant(record, rng):
    items = record.get("invariants")
    if isinstance(items, list):
        objects = [item for item in items if isinstance(item, dict)]
        if objects:
            return rng.choice(objects)
    return None


def drop_id(record, rng):
    record.pop("id", None)


def wrong_id(record, rng):
    record["id"] = unknown_digest(rng)


def drop_required_field(record, rng):
    present = [key for key in ("mir_version", "manifest_hash", "base", "harness",
                               "lineage", "status", "falsifier", "intervention",
                               "claimant", "claim", "invariants", "runs") if key in record]
    if present:
        record.pop(rng.choice(present))


def wrong_field_type(record, rng):
    path, value = rng.choice([
        (("claim", "threshold"), "0.9"),
        (("claim", "behavior"), 7),
        (("status",), 5),
        (("base",), []),
        (("runs",), {}),
        (("mir_version",), 1),
        (("claimant", "operator"), None),
        (("invariants",), "none"),
        (("runs", 0, "cost"), "4.0"),
        (("runs", 0, "result", "n_units"), "500"),
        (("intervention", "type"), None),
    ])
    assign(record, path, value)


def bad_enum_value(record, rng):
    path, value = rng.choice([
        (("claim", "direction"), "sideways"),
        (("status",), "published"),
        (("intervention", "type"), "vibes"),
        (("falsifier", "returns"), "maybe"),
        (("invariants", 0, "direction"), "around"),
        (("mir_version",), "2"),
    ])
    assign(record, path, value)


def bad_hash_pattern(record, rng):
    path, value = rng.choice([
        (("base", "hash"), "sha256:xyz"),
        (("manifest_hash",), "md5:" + "a" * 32),
        (("harness", "hash"), "sha256:" + "g" * 64),
        (("intervention", "payload_hash"), ""),
        (("runs", 0, "base_hash"), "sha256:" + "a" * 63),
    ])
    assign(record, path, value)


def extra_property(record, rng):
    path, value = rng.choice([
        (("surprise",), 1),
        (("claim", "extra"), "x"),
        (("runs", 0, "result", "smuggled"), "x"),
        (("claimant", "nickname"), "x"),
        (("base", "note"), "x"),
    ])
    assign(record, path, value)


def duplicate_scoring_metrics(record, rng):
    claim = record.get("claim")
    if isinstance(claim, dict):
        claim["scoring_metrics"] = ["mean_tokens", "mean_tokens"]


def empty_scoring_metric(record, rng):
    # An empty string in the set is what makes a non-string behavior look scored
    # to an implementation that coerces it to "" instead of rejecting it.
    claim = record.get("claim")
    if isinstance(claim, dict):
        claim["scoring_metrics"] = rng.choice([[""], ["", "mean_tokens"]])


def negative_number(record, rng):
    path, value = rng.choice([
        (("claim", "threshold"), -0.5),
        (("runs", 0, "cost"), -1.0),
        (("runs", 0, "wall_time_s"), -3.0),
        (("invariants", 0, "bound"), -0.1),
        (("runs", 0, "result", "n_units"), -5),
    ])
    assign(record, path, value)


def empty_required_array(record, rng):
    assign(record, rng.choice([("invariants",), ("runs",),
                               ("claim", "scoring_metrics"), ("lineage",)]), [])


def hash_not_in_store(record, rng):
    assign(record, rng.choice([("base", "hash"), ("harness", "hash"),
                               ("intervention", "payload_hash"), ("manifest_hash",),
                               ("runs", 0, "harness_hash")]), unknown_digest(rng))


def hash_malformed(record, rng):
    assign(record, rng.choice([("base", "hash"), ("harness", "hash"),
                               ("manifest_hash",)]), "sha256:" + "q" * 64)


def hash_null(record, rng):
    assign(record, rng.choice([("base", "hash"), ("harness", "hash"),
                               ("intervention", "payload_hash"), ("supersedes",)]), None)


def hash_bare_hex(record, rng):
    record["lineage"] = [seed_record()["lineage"][0].split(":", 1)[1]]


def hash_uppercase(record, rng):
    base = record.get("base")
    if isinstance(base, dict) and isinstance(base.get("hash"), str):
        prefix, _, digest = base["hash"].partition(":")
        base["hash"] = prefix + ":" + digest.upper()


def hash_padded(record, rng):
    base = record.get("base")
    if isinstance(base, dict) and isinstance(base.get("hash"), str):
        base["hash"] = "  " + base["hash"] + "\t"


def hash_to_locator(record, rng):
    locators = locator_digests()
    if locators:
        assign(record, ("base", "hash"), "sha256:" + rng.choice(locators))


def falsifier_not_object(record, rng):
    record["falsifier"] = rng.choice(["python3 falsify.py", 7, None, []])


def falsifier_empty_command(record, rng):
    falsifier = record.get("falsifier")
    if isinstance(falsifier, dict):
        falsifier["command"] = rng.choice(["", "   ", "\t\n"])


def falsifier_wrong_returns(record, rng):
    falsifier = record.get("falsifier")
    if isinstance(falsifier, dict):
        falsifier["returns"] = rng.choice(["int", "boolean ", "exit-code", None])


def invariants_empty(record, rng):
    record["invariants"] = []


def invariant_missing_key(record, rng):
    item = some_invariant(record, rng)
    if item:
        item.pop(rng.choice(["property", "measurement", "metric", "direction", "bound"]), None)


def invariant_bad_direction(record, rng):
    item = some_invariant(record, rng)
    if item:
        item["direction"] = rng.choice(["around", "FLOOR", "", None])


def invariant_bound_not_numeric(record, rng):
    item = some_invariant(record, rng)
    if item:
        item["bound"] = rng.choice(["0.1", None, True, []])


def invariant_not_object(record, rng):
    items = record.get("invariants")
    if isinstance(items, list) and items:
        items[rng.randrange(len(items))] = rng.choice([7, "x", None])


def behavior_not_scored(record, rng):
    claim = record.get("claim")
    if isinstance(claim, dict):
        claim["behavior"] = rng.choice(["latency", "mean_token", ""])


def all_invariants_inside(record, rng):
    claim = record.get("claim")
    items = record.get("invariants")
    if isinstance(claim, dict) and isinstance(items, list):
        scored = claim.get("scoring_metrics")
        if isinstance(scored, list) and scored:
            for item in items:
                if isinstance(item, dict):
                    item["metric"] = scored[0]


def lineage_not_list(record, rng):
    record["lineage"] = rng.choice(["sha256:" + "a" * 64, None, 7])


def lineage_empty(record, rng):
    record["lineage"] = []


def lineage_malformed_entry(record, rng):
    record["lineage"] = [rng.choice(["nonsense", "", "sha256:xyz", 7])]


def lineage_not_in_store(record, rng):
    record["lineage"] = [unknown_digest(rng)]


def lineage_to_locator(record, rng):
    locators = locator_digests()
    if locators:
        record["lineage"] = ["sha256:" + rng.choice(locators)]


def lineage_to_non_record(record, rng):
    base = record.get("base")
    if isinstance(base, dict) and isinstance(base.get("hash"), str):
        record["lineage"] = [base["hash"]]


def runs_empty(record, rng):
    record["runs"] = []


def run_not_object(record, rng):
    runs = record.get("runs")
    if isinstance(runs, list) and runs:
        runs[rng.randrange(len(runs))] = rng.choice([3, "x", None])


def run_missing_cost(record, rng):
    run = some_run(record, rng)
    if run:
        run.pop("cost", None)


def run_missing_wall_time(record, rng):
    run = some_run(record, rng)
    if run:
        run.pop("wall_time_s", None)


def run_cost_undisclosed(record, rng):
    run = some_run(record, rng)
    if run:
        run["cost"] = None


def run_cost_not_numeric(record, rng):
    run = some_run(record, rng)
    if run:
        run["cost"] = rng.choice(["4.0", [], {}])


def run_cost_negative(record, rng):
    run = some_run(record, rng)
    if run:
        run["cost"] = -1.0


def run_zero_wall_time(record, rng):
    run = some_run(record, rng)
    if run:
        run["wall_time_s"] = 0.0


def run_cost_boolean(record, rng):
    run = some_run(record, rng)
    if run:
        run["cost"] = True


def manifest_missing(record, rng):
    record.pop("manifest_hash", None)


def manifest_malformed(record, rng):
    record["manifest_hash"] = rng.choice(["sha256:xyz", "", None, 7])


def manifest_not_in_store(record, rng):
    record["manifest_hash"] = unknown_digest(rng)


def status_draft(record, rng):
    record["status"] = "draft"


def status_orphan(record, rng):
    record["status"] = "orphan"


def status_submitted(record, rng):
    record["status"] = "submitted"


def status_unknown(record, rng):
    record["status"] = rng.choice(["published", "", None, 7])


def claimant_missing(record, rng):
    record.pop("claimant", None)


def claimant_operator_empty(record, rng):
    claimant = record.get("claimant")
    if isinstance(claimant, dict):
        claimant["operator"] = rng.choice(["", "   ", None])


def claimant_funding_undisclosed(record, rng):
    claimant = record.get("claimant")
    if isinstance(claimant, dict):
        claimant["funding_source"] = rng.choice(FUNDING_TRAPS)


def runs_same_operator(record, rng):
    claimant = record.get("claimant")
    runs = record.get("runs")
    if isinstance(claimant, dict) and isinstance(runs, list):
        for run in runs:
            if isinstance(run, dict):
                run["operator"] = claimant.get("operator")


def runs_same_funding(record, rng):
    claimant = record.get("claimant")
    runs = record.get("runs")
    if isinstance(claimant, dict) and isinstance(runs, list):
        funding = claimant.get("funding_source")
        for run in runs:
            if isinstance(run, dict):
                run["funding_source"] = rng.choice([funding, str(funding).upper()])


def run_is_baseline(record, rng):
    run = some_run(record, rng)
    if run:
        run["intervention_hash"] = None


def run_undisclosed_for_independence(record, rng):
    run = some_run(record, rng)
    if run:
        run["wall_time_s"] = None


def behavior_empty(record, rng):
    claim = record.get("claim")
    if isinstance(claim, dict):
        claim["behavior"] = rng.choice(["", "   ", None])


def run_result_missing(record, rng):
    run = some_run(record, rng)
    if run:
        run.pop("result", None)


def run_result_not_object(record, rng):
    run = some_run(record, rng)
    if run:
        run["result"] = rng.choice([5, "x", None, []])


def behavior_not_reported(record, rng):
    claim = record.get("claim")
    run = some_run(record, rng)
    if isinstance(claim, dict) and run:
        result = run.get("result")
        behavior = claim.get("behavior")
        if isinstance(result, dict) and isinstance(behavior, str):
            result.pop(behavior, None)


def behavior_not_numeric(record, rng):
    claim = record.get("claim")
    run = some_run(record, rng)
    if isinstance(claim, dict) and run:
        result = run.get("result")
        behavior = claim.get("behavior")
        if isinstance(result, dict) and isinstance(behavior, str):
            result[behavior] = rng.choice(["0.62", None, True])


def awkward_numbers(record, rng):
    assign(record, ("claim", "threshold"), rng.choice(AWKWARD_NUMBERS))
    assign(record, ("invariants", 0, "bound"), rng.choice(AWKWARD_NUMBERS))
    run = some_run(record, rng)
    if run:
        result = run.get("result")
        if isinstance(result, dict):
            result["mean_tokens"] = rng.choice(AWKWARD_NUMBERS)


def unicode_labels(record, rng):
    claim = record.get("claim")
    if isinstance(claim, dict):
        claim["distribution"] = random_string(rng)
    claimant = record.get("claimant")
    if isinstance(claimant, dict):
        claimant["operator"] = random_string(rng)
    run = some_run(record, rng)
    if run:
        run["funding_source"] = random_string(rng)


def huge_unit_count(record, rng):
    run = some_run(record, rng)
    if run:
        result = run.get("result")
        if isinstance(result, dict):
            result["n_units"] = rng.choice([10 ** 30, 2 ** 63, 10 ** 400])


MUTATIONS = [
    drop_id, wrong_id,
    drop_required_field, wrong_field_type, bad_enum_value, bad_hash_pattern,
    extra_property, duplicate_scoring_metrics, empty_scoring_metric,
    negative_number, empty_required_array,
    hash_not_in_store, hash_malformed, hash_null, hash_bare_hex, hash_uppercase,
    hash_padded, hash_to_locator,
    falsifier_not_object, falsifier_empty_command, falsifier_wrong_returns,
    invariants_empty, invariant_missing_key, invariant_bad_direction,
    invariant_bound_not_numeric, invariant_not_object, behavior_not_scored,
    all_invariants_inside,
    lineage_not_list, lineage_empty, lineage_malformed_entry, lineage_not_in_store,
    lineage_to_locator, lineage_to_non_record,
    runs_empty, run_not_object, run_missing_cost, run_missing_wall_time,
    run_cost_undisclosed, run_cost_not_numeric, run_cost_negative,
    run_zero_wall_time, run_cost_boolean,
    manifest_missing, manifest_malformed, manifest_not_in_store,
    status_draft, status_orphan, status_submitted, status_unknown,
    claimant_missing, claimant_operator_empty, claimant_funding_undisclosed,
    runs_same_operator, runs_same_funding, run_is_baseline,
    run_undisclosed_for_independence,
    behavior_empty, run_result_missing, run_result_not_object,
    behavior_not_reported, behavior_not_numeric,
    awkward_numbers, unicode_labels, huge_unit_count,
]

ID_MUTATIONS = frozenset(["drop_id", "wrong_id"])


def record_case(seed):
    """The mutation names and the mutated record for one seed."""
    rng = random.Random(seed)
    record = seed_record()
    chosen = rng.sample(MUTATIONS, rng.randint(1, 3))
    for mutate in chosen:
        mutate(record, rng)
    return [mutate.__name__ for mutate in chosen], record


def random_record(seed):
    return record_case(seed)[1]


def prepare_record(seed, canonical_bytes):
    """A mutated record with a correct id, unless the mutation targeted the id."""
    names, record = record_case(seed)
    if not ID_MUTATIONS.intersection(names):
        reidentify(record, canonical_bytes)
    return names, record