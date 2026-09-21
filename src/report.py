"""Write the overlap numbers for a split pair to results/, so they are committed evidence.

`leakage.py` prints. This records, with the row counts and the normalisation level attached,
because a leakage figure means nothing without knowing which two splits produced it - the
first version of this repo reported `validation -> test` under a heading about training data,
and the two differ by a factor of seven.

    python src/report.py train test
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from leakage import (
    compare,
    internal_duplicates,
    load,
    normalise_exact,
    normalise_structural,
)

HERE = Path(__file__).resolve().parent.parent


def run(a: str, b: str) -> dict:
    left, right = load(a), load(b)
    out: dict = {
        "pair": f"{a}->{b}",
        "rows": {a: len(left), b: len(right)},
        "label_dist": {
            a: {str(k): int(v) for k, v in left["target"].value_counts().items()},
            b: {str(k): int(v) for k, v in right["target"].value_counts().items()},
        },
        "cross": {},
        "internal": {},
    }
    for fn in (normalise_exact, normalise_structural):
        o = compare(left, right, fn)
        out["cross"][o.level] = {
            "matched": o.matched_test_rows,
            "share": o.matched_share,
            "same_label": o.same_label,
            "conflicting": o.conflicting_label,
        }
        dup, conf = internal_duplicates(right, fn)
        out["internal"][o.level] = {b: {"duplicate_rows": dup, "conflicting_rows": conf}}
    return out


def main() -> int:
    a, b = (sys.argv[1], sys.argv[2]) if len(sys.argv) > 2 else ("train", "test")
    data = run(a, b)
    dest = HERE / "results" / f"leakage_{a}_{b}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(data, indent=2), encoding="utf-8", newline="\n")
    print(json.dumps(data, indent=2))
    print(f"\nwrote {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
