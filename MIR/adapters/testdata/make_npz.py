#!/usr/bin/env python3
"""Cut the dspy-wsp fixture with numpy, so the reader is tested on real bytes.

The adapter itself uses the standard library only. numpy is used here once, to
produce `edit.npz`, which is then committed; the gate reads the committed file.

    python3 adapters/testdata/make_npz.py
"""

from __future__ import annotations

import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    edit = np.zeros((2, 3), dtype=np.float32)
    edit[0, 0] = 0.5
    edit[1, 1] = -1.0
    path = os.path.join(HERE, "edit.npz")
    np.savez(path, w=edit)
    print("wrote %s" % path)


if __name__ == "__main__":
    main()
