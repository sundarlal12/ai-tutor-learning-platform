#!/usr/bin/env python3
"""One-off: send each sample lesson's steps through the local voice service (POST /lesson) so
they carry real Sarvam audio_url + alignment, then write the result everywhere a copy of the
sample bundles lives (gateway seed, gateway's live data dir, Android assets)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
VOICE_URL = "http://127.0.0.1:8103/lesson"
TARGETS = [
    ROOT / "sample" / "bundles",
    ROOT / ".run" / "data" / "bundles",
    ROOT / "android" / "app" / "src" / "main" / "assets" / "bundles",
]


def main() -> None:
    src = ROOT / "sample" / "bundles"
    for f in sorted(src.glob("*.json")):
        bundle = json.loads(f.read_text(encoding="utf-8"))
        print(f"{f.name}: {len(bundle['lessons'])} lesson(s)")
        for lesson in bundle["lessons"]:
            r = httpx.post(VOICE_URL, json=lesson, timeout=120)
            r.raise_for_status()
            enriched = r.json()
            lesson["steps"] = enriched["steps"]
            n_audio = sum(1 for s in lesson["steps"] if s.get("audio_url"))
            print(f"  {lesson['title']}: {n_audio}/{len(lesson['steps'])} steps got real audio")
        text = json.dumps(bundle, ensure_ascii=False, indent=2)
        for target_dir in TARGETS:
            target_dir.mkdir(parents=True, exist_ok=True)
            (target_dir / f.name).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
