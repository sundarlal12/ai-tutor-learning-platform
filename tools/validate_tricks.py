#!/usr/bin/env python3
"""Validates the YAML trick library.

Checks: schema, unique ids, subject matches file, every trick has >= 2 steps, and every `proof`
passes the same SymPy checker the verifier service uses. Exit code 1 if anything fails, so it can
run in CI before a new trick reaches the generator prompt.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "libs" / "lessonkit"))

from lessonkit import FAMILIES, Trick  # noqa: E402
from lessonkit.proofs import run_check  # noqa: E402


def main() -> int:
    errors: list[str] = []
    tricks: list[Trick] = []
    per_subject: Counter[str] = Counter()
    proofs_ok = proofs_total = 0
    for path in sorted((ROOT / "knowledge" / "tricks").glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        for raw in data.get("tricks", []):
            try:
                t = Trick(**raw)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{path.name}: {raw.get('id', '?')}: schema error: {exc}")
                continue
            if t.subject != data.get("subject"):
                errors.append(f"{path.name}: {t.id}: subject {t.subject!r} != file subject {data.get('subject')!r}")
            if t.family not in FAMILIES:
                errors.append(f"{path.name}: {t.id}: unknown family {t.family!r}")
            if len(t.steps) < 2:
                errors.append(f"{path.name}: {t.id}: needs at least 2 steps")
            if not t.triggers:
                errors.append(f"{path.name}: {t.id}: needs triggers so retrieval can find it")
            tricks.append(t)
            per_subject[t.subject] += 1
            if t.proof:
                proofs_total += 1
                res = run_check(t.proof)
                if res.ok:
                    proofs_ok += 1
                else:
                    errors.append(f"{path.name}: {t.id}: PROOF FAILED: {res.detail}")
    dupes = [i for i, c in Counter(t.id for t in tricks).items() if c > 1]
    errors += [f"duplicate trick id: {d}" for d in dupes]
    print(f"{len(tricks)} tricks in {len(per_subject)} subjects: {dict(per_subject)}")
    print(f"proofs: {proofs_ok}/{proofs_total} passed")
    for e in errors:
        print("ERROR:", e)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
