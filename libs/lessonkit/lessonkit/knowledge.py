"""Loads the YAML trick library and retrieves the tricks relevant to a question.

The library is how the AI "does not miss a trick": every generation request gets the
matching tricks injected into the prompt, and the validator proves formula tricks
with SymPy so wrong tricks cannot enter the library.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field


FAMILIES = {"formula", "identity", "substitution", "plug_values", "digital_sum", "option_elimination",
            "guess", "estimation", "pattern", "diagram"}

_GENERIC = {"value", "values", "standard", "angles", "angle", "options", "back", "substitution",
            "quick", "calculation", "pair", "number", "numbers", "sums", "ratio", "total", "area"}


class TrickExample(BaseModel):
    question: str
    answer: str
    seconds: int = 0


class Trick(BaseModel):
    id: str
    name: str
    subject: str
    topic: str
    # What kind of trick this is, so the AI can check every family was considered for a question.
    family: str = "formula"
    exams: list[str] = Field(default_factory=list)
    triggers: list[str] = Field(default_factory=list)  # keywords/regex seen in questions
    when: str
    idea: str
    steps: list[str]
    example: TrickExample
    caution: str = ""
    speed_seconds: int = 30
    proof: Optional[dict[str, Any]] = None  # machine-checkable proof for formula tricks

    def to_prompt(self) -> str:
        steps = "\n".join(f"    {i + 1}. {s}" for i, s in enumerate(self.steps))
        caution = f"\n  works only when: {self.caution}" if self.caution else ""
        return (
            f"- id: {self.id}\n  family: {self.family}\n  name: {self.name}\n  use when: {self.when}\n"
            f"  idea: {self.idea}\n  steps:\n{steps}{caution}\n"
            f"  example: {self.example.question} => {self.example.answer}"
        )


class KnowledgeBase:
    def __init__(self, tricks: list[Trick]):
        self.tricks = tricks
        self.by_id = {t.id: t for t in tricks}

    @classmethod
    def load(cls, directory: str | Path) -> "KnowledgeBase":
        tricks: list[Trick] = []
        for path in sorted(Path(directory).glob("*.yaml")):
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            for raw in data.get("tricks", []):
                tricks.append(Trick(**raw))
        return cls(tricks)

    def subjects(self) -> list[str]:
        return sorted({t.subject for t in self.tricks})

    def retrieve(self, question: str, subject: Optional[str] = None, k: int = 8) -> list[Trick]:
        """Keyword + regex scoring. Cheap, deterministic, and explainable."""
        text = question.lower()
        scored: list[tuple[float, Trick]] = []
        for t in self.tricks:
            if subject and t.subject != subject:
                continue
            score = 0.0
            for trig in t.triggers:
                trig_l = trig.lower()
                try:
                    if re.search(trig_l, text):
                        score += 2.0
                        continue
                except re.error:
                    pass
                if trig_l in text:
                    score += 2.0
            for word in re.findall(r"[a-z]{4,}", t.topic.lower() + " " + t.name.lower()):
                if word not in _GENERIC and word in text:
                    score += 0.5
            if score > 0:
                scored.append((score, t))
        scored.sort(key=lambda x: (-x[0], x[1].speed_seconds))
        picked = [t for _, t in scored[:k]]
        # Every question also gets the option-check trick of its most likely subject.
        primary = subject or (picked[0].subject if picked else None)
        for t in self.tricks:
            if t.id.endswith("option-backsolve") and t.subject == primary and t not in picked:
                picked.append(t)
        return picked
