#!/usr/bin/env python3
"""Generate the case-folding vectors that keep impl2's fold table honest.

validate.py decides funding independence with str.casefold(), which is Unicode
*full* folding. strings.EqualFold alone does *simple* folding, so impl2 carries a
table of the runes whose full fold expands to several runes. A table like that is
transcribed data, and transcribed data drifts: a decomposed sequence can be
replaced by a precomposed rune that looks identical in an editor and folds to
itself.

The expected folds here come from Python, not from the table. Only runes whose
fold differs from the rune itself are listed; every other rune folds to itself.
Folds are written as code points so that decomposed and precomposed spellings
cannot be confused. The Go test walks the whole code point space and asserts that
impl2's folding induces exactly the same partition as Python's.

    python3 impl2/testdata/make_casefold.py
"""

import json
import os
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    folds = {}
    for point in range(0x110000):
        if 0xD800 <= point <= 0xDFFF:
            continue
        character = chr(point)
        folded = character.casefold()
        if folded != character:
            folds["%04X" % point] = " ".join("%04X" % ord(c) for c in folded)
    document = {
        "unicode_version": unicodedata.unidata_version,
        "folds": folds,
    }
    path = os.path.join(HERE, "casefold_vectors.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(document, handle, indent=2, sort_keys=True)
        handle.write("\n")
    expanding = sum(1 for value in folds.values() if " " in value)
    print("wrote %d folds (%d expanding) to %s" % (len(folds), expanding, path))


if __name__ == "__main__":
    main()