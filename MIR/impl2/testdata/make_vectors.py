#!/usr/bin/env python3
"""Generate the canonical-form test vectors shared by both implementations.

The expected bytes are produced by the reference implementation (validate.py),
and the Go test in this directory asserts that impl2 produces the same bytes.
A vector is a JSON document as text, not a Python value, because the literal
spelling is part of what section 4.13 has to normalize.

    python3 impl2/testdata/make_vectors.py
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

from validate import canonical_bytes  # noqa: E402

CASES = [
    ("member order", '{"b":1,"a":2}'),
    ("nested member order", '{"z":{"b":1,"a":2},"a":[{"d":4,"c":3}]}'),
    ("empty containers", '{"a":[],"b":{}}'),
    ("literals", '[true,false,null]'),
    ("integer and float are different values", '[4,4.0]'),
    ("trailing zero removed", '[0.050,1.500]'),
    ("exponent becomes plain decimal", '[1e2,1E+2]'),
    ("negative zero", '[-0.0,-0]'),
    ("small exponent expanded", '[1e-7,1.234e-5]'),
    ("large exponent expanded", '[1e16,1e21]'),
    ("largest finite double", '[1.7976931348623157e308]'),
    ("smallest positive double", '[5e-324]'),
    ("large integer", '[123456789012345678901234567890]'),
    ("negative large integer", '[-123456789012345678901234567890]'),
    ("shortest round-trip digits", '[0.1,0.30000000000000004,0.6709628506444276]'),
    ("escapes", r'["quote\" backslash\\ newline\n tab\t return\r"]'),
    ("control characters", r'["\u0000\u0001\u001f\u007f"]'),
    ("slash is not escaped", r'["a\/b"]'),
    ("non-ascii stays utf-8", '{"ي":"عربي","中":"文","emoji":"🙂"}'),
    ("line separator stays utf-8", '["a\\u2028b\\u2029c"]'),
    ("keys sort by code point", '{"😀":5,"z":1,"é":2,"Z":4,"a":3}'),
    ("empty key", '{"":1}'),
    ("empty string", '[""]'),
]


def main():
    vectors = []
    for name, document in CASES:
        value = json.loads(document)
        vectors.append({
            "name": name,
            "input": document,
            "canonical": canonical_bytes(value).decode("utf-8"),
        })
    path = os.path.join(HERE, "canonical_vectors.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(vectors, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print("wrote %d vectors to %s" % (len(vectors), path))


if __name__ == "__main__":
    main()
