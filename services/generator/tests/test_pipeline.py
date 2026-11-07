"""Tests the generate() pipeline with a fake Claude: a wrong trick must be dropped, a right one kept."""
import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("KNOWLEDGE_DIR", str(Path(__file__).resolve().parents[3] / "knowledge" / "tricks"))

from app import pipeline  # noqa: E402
from lessonkit.proofs import run_check  # noqa: E402

GIVENS = ["a**4 + b**4 + a**2*b**2 = 8", "a**2 + b**2 + a*b = 4"]


def _solve(claimed: str) -> dict:
    return {"kind": "solve_target", "vars": ["a", "b"], "givens": GIVENS, "target": "a*b", "claimed": claimed}


def _step(say: str) -> dict:
    return {"say": say, "actions": [{"type": "write", "text": "ab = 1", "x": 0.1, "y": 0.2, "color": "green"},
                                    {"type": "teleport", "x": 5}]}  # invalid action must be dropped, not crash


PAYLOAD = {
    "subject": "algebra",
    "ground_truth": {"final_answer": "1", "correct_option": "(d)", "check": _solve("1")},
    "lessons": [
        {"trick_id": "alg-sum-diff-substitution", "title": "Slow but right", "final_answer": "1",
         "estimated_seconds": 25, "check": _solve("1"), "steps": [_step("Pehla step")]},
        {"trick_id": "new-wrong-trick", "title": "Wrong trick", "final_answer": "2",
         "estimated_seconds": 5, "check": _solve("2"), "steps": [_step("Galat step")]},
        {"trick_id": "alg-identity-a4-a2b2-b4", "title": "Identity", "final_answer": "1",
         "estimated_seconds": 10, "check": _solve("1"), "steps": [_step("Identity lagao")]},
    ],
}


class FakeClient:
    class messages:  # noqa: N801
        @staticmethod
        async def create(**kwargs):
            assert kwargs["tool_choice"]["name"] == "submit_lessons"
            assert "alg-identity-a4-a2b2-b4" in kwargs["system"]  # knowledge base was injected
            return SimpleNamespace(content=[SimpleNamespace(type="tool_use", input=PAYLOAD)])


async def _local_verify(checks):
    return [{"ok": r.ok, "detail": r.detail} for r in map(run_check, checks)]


def test_wrong_trick_dropped_and_lessons_sorted(monkeypatch):
    monkeypatch.setattr(pipeline, "anthropic_client", lambda: FakeClient)
    monkeypatch.setattr(pipeline, "_verify", _local_verify)
    bundle, report = asyncio.run(pipeline.generate(
        "If a⁴ + b⁴ + a²b² = 8 and a² + b² + ab = 4, then the value of ab is:",
        ["(b) 0", "(c) 2", "(d) 1"], "SSC CGL", None, "hinglish", with_voice=False))
    ids = [l.trick_id for l in bundle.lessons]
    assert ids == ["alg-identity-a4-a2b2-b4", "alg-sum-diff-substitution"]  # fastest first, wrong one gone
    dropped = [r for r in report if r.get("dropped")]
    assert [d["trick_id"] for d in dropped] == ["new-wrong-trick"]
    assert all(len(s.actions) == 1 for l in bundle.lessons for s in l.steps)  # invalid action removed
    assert bundle.question.correct_option == "(d)"


def test_bad_ground_truth_aborts(monkeypatch):
    bad = {**PAYLOAD, "ground_truth": {"final_answer": "2", "check": _solve("2")}}

    class BadClient(FakeClient):
        class messages:  # noqa: N801
            @staticmethod
            async def create(**kwargs):
                return SimpleNamespace(content=[SimpleNamespace(type="tool_use", input=bad)])

    monkeypatch.setattr(pipeline, "anthropic_client", lambda: BadClient)
    monkeypatch.setattr(pipeline, "_verify", _local_verify)
    try:
        asyncio.run(pipeline.generate("question text here", [], "", None, "hinglish", False))
        raise AssertionError("should have raised")
    except RuntimeError as exc:
        assert "ground-truth" in str(exc)
