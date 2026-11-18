#!/usr/bin/env python3
"""Generate the repr vectors that keep impl2's message formatting honest.

Report details quote arbitrary text with Python's repr(): the falsifier's output
in C-06 and the host's etag in C-07. Two implementations that quote differently
look like they disagree about the record, so impl2 reproduces repr() rather than
using Go's %q.

repr() escapes every rune that is not printable by Unicode category. Go's
unicode.IsPrint applies the same rule to a newer Unicode table, so the two differ
on runes added since. The vectors record Python's non-printable ranges in full;
the Go test derives the pin table from them and fails if it drifts.

    python3 impl2/testdata/make_repr.py
"""

import json
import os
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))

NONPRINTABLE = ("Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp", "Zs")

PROBES = [
    "",
    "plain",
    "it's",
    'a"b',
    'it\'s a "test"',
    '"',
    "'",
    "\\",
    "a\nb",
    "a\tb",
    "a\rb",
    "a\x00b",
    "a\x1fb",
    "a\x7fb",
    "a\x80b",
    "a\x9fb",
    "a\xa0b",
    "\u00e9",
    "caf\u00e9",
    "\u200b",
    "\u2028",
    "\u202e",
    "\ufeff",
    "\U0001f642",
    "\U00010000",
    "\U0010ffff",
    "\u0301",
    "a\u0301",
    "\u16ea0",
    "\ua7ce",
    "operator-a said 'no'",
    'etag: "weak"',
    "sha256:" + "0" * 64,
    "line1\nline2\ttab\rreturn",
    "\x1b[31mred\x1b[0m",
]


def printable(point):
    if point == 0x20:
        return True
    return unicodedata.category(chr(point)) not in NONPRINTABLE


def ranges(points):
    out = []
    for point in points:
        if out and point == out[-1][1] + 1:
            out[-1][1] = point
        else:
            out.append([point, point])
    return out


def main():
    nonprintable = [p for p in range(0x110000)
                    if not (0xD800 <= p <= 0xDFFF) and not printable(p)]
    document = {
        "unicode_version": unicodedata.unidata_version,
        "nonprintable": ranges(nonprintable),
        "probes": [{"input": text, "repr": repr(text)} for text in PROBES],
    }
    path = os.path.join(HERE, "repr_vectors.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(document, handle, indent=2)
        handle.write("\n")
    print("wrote %d non-printable ranges and %d probes to %s"
          % (len(document["nonprintable"]), len(PROBES), path))


if __name__ == "__main__":
    main()