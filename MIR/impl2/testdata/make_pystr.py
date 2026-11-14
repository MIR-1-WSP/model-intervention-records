#!/usr/bin/env python3
"""Generate the str() vectors that keep impl2's C-05 detail honest.

C-05 names claim.behavior in its failure detail. The reference writes it with
%s, which is str(), so a behavior that is not a string still has to be spelled
the way Python spells it: None, True, 100.0, [1, 'a'], {'b': 1, 'a': 2}. A Go
type assertion that fails yields "", which both misspells the value and -- when
scoring_metrics contains an empty string -- turns a failing check into a passing
one.

repr() for a float switches to exponent notation at a different threshold than
Go's 'g' format: Python uses an exponent when the decimal point falls outside
-4..16, so 1e15 is 1000000000000000.0 and 1e16 is 1e+16. The vectors pin that
boundary and a spread of bit patterns.

Object member order matters. str(dict) walks insertion order, so the probes are
written with unsorted keys and the JSON text is emitted unsorted too.

    python3 impl2/testdata/make_pystr.py
"""

import json
import os
import random
import struct

HERE = os.path.dirname(os.path.abspath(__file__))

FLOAT_PROBES = [
    0.0, -0.0, 1.0, -1.0, 100.0, 0.1, 1 / 3,
    1e-5, 1e-4, 1e-3, 1e15, 1e16, 1e17, 1e21, 1e22,
    9.999999999999999e15, 1.0000000000000002e16,
    5e-324, 2.2250738585072014e-308, 1.7976931348623157e308,
    1e-7, 1e-320, 1234567890123456.0, 12345678901234567.0,
    0.0001, 0.00001, 1e100, 1e-100, 1e-999, -1e-999, 1e999, -1e999,
    float("nan"), float("inf"), float("-inf"),
    0.30000000000000004, 2.0 ** 53, 2.0 ** 63, 1.5e-9, 9007199254740993.0,
]

NUMBER_LITERALS = [
    "0", "-0", "7", "-7", "1.5", "-1.5", "100.0", "1e2", "1E2", "1e+2",
    "1e-7", "1e15", "1e16", "0.1", "1e999", "-1e999", "1e-999", "-1e-999",
    "123456789012345678901234567890", "-1000000000000000000000",
    "9007199254740993", "4", "4.0", "0.30000000000000004", "1e-5", "1e-4",
]

# Non-finite floats are absent here: json.dumps writes them as Infinity, which
# is not JSON and both implementations reject it. They are covered as bit
# patterns and as the literal 1e999, which is JSON and parses to an infinity.
VALUE_PROBES = [
    None, True, False, 0, 7, -7, 1.5, 100.0, 1e16, 1e15, "", "x", "it's",
    'say "hi"', "é\u2028中", [], [1, "a", None, True], [1, [2, [3]]],
    {}, {"b": 1, "a": 2}, {"a": {"z": 1, "b": [1, "x"]}},
    {"metric": "mean_tokens", "bound": 0.1, "ok": False},
    ["é", "\u2028", "\\", "\n"], {"key'quote": 'value"double'},
    {"z": None, "y": [1e16, 1e15, -0.0], "x": {"n": 1, "m": "s"}},
    [None, True, False, 1e308, 1e-308, -0.0],
]


def bits(value):
    return "%016x" % struct.unpack("<Q", struct.pack("<d", value))[0]


def main():
    rng = random.Random(20261113)
    floats = [{"bits": bits(v), "str": str(v)} for v in FLOAT_PROBES]
    seen = {item["bits"] for item in floats}
    while len(floats) < 2000:
        raw = rng.getrandbits(64)
        key = "%016x" % raw
        if key in seen:
            continue
        seen.add(key)
        value = struct.unpack("<d", struct.pack("<Q", raw))[0]
        floats.append({"bits": key, "str": str(value)})

    document = {
        "floats": floats,
        "numbers": [{"literal": text, "str": str(json.loads(text))}
                    for text in NUMBER_LITERALS],
        "values": [{"json": json.dumps(value, ensure_ascii=False), "str": str(value)}
                   for value in VALUE_PROBES],
    }
    path = os.path.join(HERE, "pystr_vectors.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(document, handle, indent=2)
        handle.write("\n")
    print("wrote %d floats, %d number literals and %d values to %s"
          % (len(floats), len(document["numbers"]), len(document["values"]), path))


if __name__ == "__main__":
    main()