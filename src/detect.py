"""Can a coder model beat "always say safe" on Devign?

Devign is a standard vulnerability-detection benchmark and published accuracies cluster
around 62%. The number that is almost never printed next to them is the majority baseline:
the test split is 1477 safe to 1255 vulnerable, so a classifier that answers **SAFE** every
time and reads no code at all scores **54.1%**.

That makes the interesting question not "what does the model score" but "does it beat a
constant". Eight points of headroom is a narrow target, and a model that lands inside it
has demonstrated nothing about reading C.

The leakage audit in this repo found a second thing worth carrying forward: the test set
contains duplicate functions with *conflicting* labels - the same C function marked
vulnerable in one row and safe in another. Those rows are unwinnable, so the same
predictions are scored twice:

- **full**  - every row, as everyone reports it
- **clean** - with rows in a conflicting-label duplicate group removed

There are only 12 such rows in 2732, so this is a ceiling check rather than a headline: it
establishes that the label noise is real but far too rare to explain anyone's number, which
is worth knowing precisely because "the dataset is noisy" is the easy excuse.

    python src/detect.py --limit 400
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from leakage import digest, load, normalise_exact, normalise_structural  # noqa: E402

OLLAMA = "http://localhost:11434"
OUT = Path(__file__).resolve().parent.parent / "results"

PROMPT = """You are auditing C code for security vulnerabilities.

```c
{code}
```

Does this function contain a security vulnerability?

Answer with exactly one word: VULNERABLE or SAFE.
"""

_WORD = re.compile(r"\b(VULNERABLE|SAFE)\b", re.IGNORECASE)


def classify(code: str, model: str, max_chars: int = 6000) -> bool | None:
    payload = {
        "model": model,
        "prompt": PROMPT.format(code=code[:max_chars]),
        "stream": False,
        # Deterministic. A security audit whose verdict moves with a seed is not a
        # measurement, and this number gets compared against a published one.
        "options": {"temperature": 0.0, "num_predict": 8},
    }
    req = urllib.request.Request(
        f"{OLLAMA}/api/generate",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as fh:
            text = json.loads(fh.read()).get("response", "")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None
    m = _WORD.search(text or "")
    if not m:
        return None
    return m.group(1).upper() == "VULNERABLE"


def conflicting_rows(frame, normalise) -> set[int]:
    """Row positions belonging to a duplicate group with more than one label."""
    groups: dict[str, list[int]] = defaultdict(list)
    for i, code in enumerate(frame["func"]):
        groups[digest(normalise(code))].append(i)
    bad: set[int] = set()
    for idxs in groups.values():
        if len(idxs) > 1 and len({bool(frame["target"].iloc[i]) for i in idxs}) > 1:
            bad.update(idxs)
    return bad


def score(pairs) -> dict:
    """pairs: (predicted, actual). Accuracy plus the confusion matrix."""
    tp = sum(1 for p, a in pairs if p and a)
    tn = sum(1 for p, a in pairs if not p and not a)
    fp = sum(1 for p, a in pairs if p and not a)
    fn = sum(1 for p, a in pairs if not p and a)
    n = len(pairs)
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    majority = max(sum(1 for _, a in pairs if a), sum(1 for _, a in pairs if not a)) / n
    return {
        "n": n,
        "accuracy": (tp + tn) / n,
        "majority_baseline": majority,
        "precision": prec,
        "recall": rec,
        "f1": 2 * prec * rec / (prec + rec) if prec + rec else 0.0,
        "tp": tp, "tn": tn, "fp": fp, "fn": fn,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=400)
    ap.add_argument("--model", default="qwen2.5-coder:14b")
    args = ap.parse_args()

    frame = load("test")
    if frame is None:
        print("Devign test split not in the local Hugging Face cache")
        return 1

    conflict = conflicting_rows(frame, normalise_exact) | conflicting_rows(
        frame, normalise_structural
    )
    print(f"test rows                 : {len(frame)}")
    print(f"rows in conflicting groups: {len(conflict)}  ({len(conflict) / len(frame):.2%})")

    take = min(args.limit, len(frame))
    # Take the first N rows rather than a random sample: the row order is the dataset's,
    # so this is reproducible without carrying a seed, and the conflicting rows are not
    # concentrated anywhere in particular.
    idxs = list(range(take))
    print(f"classifying               : {take} rows with {args.model}\n")

    preds: dict[int, bool] = {}
    unparsed = 0
    t0 = time.time()
    for n, i in enumerate(idxs, 1):
        p = classify(frame["func"].iloc[i], args.model)
        if p is None:
            unparsed += 1
        else:
            preds[i] = p
        if n % 50 == 0 or n == take:
            rate = (time.time() - t0) / n
            print(f"  {n}/{take}  {rate:.1f}s each  eta {rate * (take - n) / 60:.0f} min", flush=True)

    full = [(preds[i], bool(frame["target"].iloc[i])) for i in idxs if i in preds]
    clean = [
        (preds[i], bool(frame["target"].iloc[i]))
        for i in idxs
        if i in preds and i not in conflict
    ]
    if not full:
        print("no parsable predictions")
        return 1

    fs, cs = score(full), score(clean)
    removed = len(full) - len(clean)

    print("\n" + "=" * 68)
    print(f"DEVIGN - the same predictions, scored twice ({args.model})")
    print("=" * 68)
    print(f"  unparsable answers: {unparsed}")
    print(f"  rows removed as conflicting duplicates: {removed}\n")
    print(f"  {'':22} {'full':>10} {'clean':>10} {'delta':>10}")
    for key in ("n", "accuracy", "majority_baseline", "precision", "recall", "f1"):
        a, b = fs[key], cs[key]
        if key == "n":
            print(f"  {key:22} {a:10} {b:10} {b - a:10}")
        else:
            print(f"  {key:22} {a:10.1%} {b:10.1%} {b - a:+10.1%}")

    print(f"\n  confusion (full) : tp {fs['tp']} tn {fs['tn']} fp {fs['fp']} fn {fs['fn']}")
    print(
        f"\n  The model beats the majority baseline by "
        f"{fs['accuracy'] - fs['majority_baseline']:+.1%} on the full set."
    )
    if abs(cs["accuracy"] - fs["accuracy"]) < 0.01:
        print(
            "  Removing the conflicting rows moves accuracy by less than a point: on a\n"
            "  sample this size the label noise is real but too rare to change a verdict."
        )
    else:
        print(
            f"  Removing them moves accuracy {cs['accuracy'] - fs['accuracy']:+.1%}, which is\n"
            "  the part of any published Devign number that is a dataset artefact."
        )

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "detect.json").write_text(
        json.dumps(
            {
                "model": args.model,
                "rows_classified": take,
                "unparsable": unparsed,
                "conflicting_rows_in_test": len(conflict),
                "full": fs,
                "clean": cs,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nwrote {OUT / 'detect.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
