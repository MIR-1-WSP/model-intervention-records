#!/usr/bin/env python3
"""Evaluate the claim of a synthetic MIR-1 example against its own run result.

This is a fixture falsifier, not a measurement of a model. It reads the record
named on the command line, takes the first run's result for the claim's
behavior, and prints `true` when the claim holds and `false` when it does not.
A constant `print(True)` cannot refute anything; this script can.

    python3 examples/falsify_example.py examples/conforming.json
"""

from __future__ import annotations

import json
import sys


def main(argv):
    if len(argv) != 2:
        print("usage: falsify_example.py RECORD.json", file=sys.stderr)
        return 2
    with open(argv[1], "r", encoding="utf-8") as handle:
        record = json.load(handle)
    claim = record["claim"]
    value = record["runs"][0]["result"][claim["behavior"]]
    threshold = claim["threshold"]
    if claim["direction"] == "increase":
        held = value > threshold
    elif claim["direction"] == "decrease":
        held = value < threshold
    else:
        raise SystemExit("unknown direction: %r" % (claim["direction"],))
    print("true" if held else "false")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
