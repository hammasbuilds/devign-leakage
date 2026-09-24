"""Show what devign-leakage found, in one command.

    python demo.py

Devign is a standard vulnerability-detection benchmark: 27,318 C functions
labelled vulnerable or not. This measures how many of its test rows also appear
in its training set, which decides whether a score on it means anything.

Two readings, and the gap between them is the point:

  exact        byte-identical functions
  structural   identical after normalising whitespace, comments and identifier
               names - the same function, renamed

A model does not care that a variable was called `len` in one copy and `n` in
the other. The exact figure is the one a casual check produces and the
structural figure is the one that describes the benchmark.

Runs against the real dataset if it is present, and falls back to the committed
results if it is not, so this works on a fresh clone with no download.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results" / "leakage.json"


def from_committed_results() -> int:
    if not RESULTS.exists():
        print("No dataset and no committed results. Fetch the dataset, then:", flush=True)
        print("    python src/leakage.py train test", flush=True)
        return 1
    data = json.loads(RESULTS.read_text(encoding="utf-8"))
    print("Dataset not present - reading the committed measurement instead.", flush=True)
    print(f"  {RESULTS.relative_to(ROOT)}", flush=True)
    print(flush=True)
    print(json.dumps(data, indent=2)[:1600], flush=True)
    return 0


def main() -> int:
    print(
        "devign-leakage: how much of Devign's test set is already in its training set?", flush=True
    )
    print(flush=True)

    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    try:
        result = subprocess.run(
            [sys.executable, "src/leakage.py", "train", "test"],
            cwd=ROOT,
            env=env,
            check=False,
            timeout=1800,
        )
    except (OSError, subprocess.TimeoutExpired):
        return from_committed_results()

    if result.returncode != 0:
        return from_committed_results()

    print(flush=True)
    print("The exact figure is what a byte-comparison finds. The structural figure", flush=True)
    print("counts the same function written with different identifier names, which", flush=True)
    print("is what a model actually sees - and it is an order of magnitude larger.", flush=True)
    print(flush=True)
    print("Rows whose duplicate carries the OPPOSITE label are worse than leakage:", flush=True)
    print("they are unlearnable, and they cap the accuracy anything can reach here.", flush=True)
    print(flush=True)
    print("Full write-up: docs/RESULTS.md, docs/METHOD.md, docs/LIMITATIONS.md", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
