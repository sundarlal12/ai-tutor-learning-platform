"""Question -> verified lesson bundle.

retrieve tricks (YAML) -> Claude writes lessons via a forced tool call -> verifier proves every
lesson -> failed tricks are dropped -> (optional) voice service adds audio + timings.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, AsyncIterator

import httpx
from anthropic import AsyncAnthropic

from lessonkit import (
    Action, KnowledgeBase, LANGUAGE_TO_SARVAM, LessonBundle, LessonScript, LessonStep, Question, Teacher,
)

from .prompts import STREAM_SYSTEM_PROMPT, SUBMIT_TOOL, SYSTEM_PROMPT

log = logging.getLogger("generator")

MODEL = os.getenv("GENERATOR_MODEL", "claude-sonnet-5-5")
VERIFIER_URL = os.getenv("VERIFIER_URL", "http://verifier:8002")
VOICE_URL = os.getenv("VOICE_URL", "http://voice:8003")
GATEWAY_URL = os.getenv("GATEWAY_URL", "http://gateway:8000")  # for resolving teacher_id -> voice settings
KNOWLEDGE_DIR = os.getenv("KNOWLEDGE_DIR", "/knowledge/tricks")
SAMPLE_DIR = Path(os.getenv("SAMPLE_DIR", "/sample/bundles"))
GATEWAY_DATA_DIR = os.getenv("GATEWAY_DATA_DIR", "")  # when set, cache finished live-solved bundles here too

kb = KnowledgeBase.load(KNOWLEDGE_DIR) if Path(KNOWLEDGE_DIR).exists() else KnowledgeBase([])
_client: AsyncAnthropic | None = None
_teacher_cache: dict[str, tuple[float, Teacher | None]] = {}
_TEACHER_CACHE_TTL = 60.0


def anthropic_client() -> AsyncAnthropic | None:
    global _client
    if _client is None and os.getenv("ANTHROPIC_API_KEY"):
        _client = AsyncAnthropic()
    return _client


async def _resolve_teacher(teacher_id: str | None) -> Teacher | None:
    """Looks up a teacher's voice (gateway's /v1/teachers) so speaker/language/pace come from
    per-teacher config instead of this service's own env vars. None (lookup skipped or failed)
    just means the voice service falls back to its SARVAM_* env defaults, same as before teachers
    existed at all."""
    if not teacher_id:
        return None
    now = time.monotonic()
    cached = _teacher_cache.get(teacher_id)
    if cached and now - cached[0] < _TEACHER_CACHE_TTL:
        return cached[1]
    teacher: Teacher | None = None
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            r = await http.get(f"{GATEWAY_URL}/v1/teachers/{teacher_id}")
            if r.status_code == 200:
                teacher = Teacher(**r.json())
    except Exception:  # noqa: BLE001 - unresolved teacher: fall back to env defaults, don't fail the lesson
        log.warning("could not resolve teacher_id=%s from gateway", teacher_id)
    _teacher_cache[teacher_id] = (now, teacher)
    return teacher


def _voice_payload(lesson: LessonScript, teacher: Teacher | None) -> dict:
    # voice_* names (not speaker/language/pace): LessonScript already has its own `language`
    # field (narration style), so reusing that name on the wire would shadow it on the voice
    # service's side — see the matching comment in services/voice/app/main.py.
    # voice_language always comes from the LESSON's own language (the student's choice), not the
    # teacher's stored default — the same teacher persona can narrate in whichever language the
    # student picked. Only speaker/pace (voice identity/speed) come from the teacher.
    payload = lesson.model_dump(mode="json")
    payload["voice_language"] = LANGUAGE_TO_SARVAM.get(lesson.language, "hi-IN")
    if teacher:
        payload["voice_speaker"] = teacher.sarvam_speaker
        payload["voice_pace"] = teacher.sarvam_pace
    return payload


def question_id(text: str) -> str:
    return "q-" + hashlib.sha1(text.strip().encode()).hexdigest()[:10]


def _clean_actions(raw: list[dict]) -> list[Action]:
    out: list[Action] = []
    for a in raw or []:
        try:
            for k in ("x", "y", "x2", "y2"):
                if k in a:
                    a[k] = min(1.0, max(0.0, float(a[k])))
            out.append(Action(**a))
        except Exception:  # noqa: BLE001 - drop one bad action, keep the lesson
            log.warning("dropped invalid action: %s", a)
    return out


async def _verify(checks: list[dict]) -> list[dict]:
    async with httpx.AsyncClient(timeout=30) as http:
        r = await http.post(f"{VERIFIER_URL}/verify", json={"checks": checks})
        r.raise_for_status()
        return r.json()["results"]


def _norm(ans: str) -> str:
    return "".join(str(ans).lower().split()).rstrip(".")


async def _sample_fallback(text: str) -> LessonBundle | None:
    """Mock mode (no ANTHROPIC_API_KEY): serve a hand-written sample for known questions."""
    if not SAMPLE_DIR.exists():
        return None
    for path in SAMPLE_DIR.glob("*.json"):
        bundle = LessonBundle(**json.loads(path.read_text(encoding="utf-8")))
        if _norm(bundle.question.text)[:40] == _norm(text)[:40]:
            return bundle
    return None


async def generate(text: str, options: list[str], exam: str, subject: str | None, language: str,
                   with_voice: bool, teacher_id: str | None = None) -> tuple[LessonBundle, list[dict]]:
    client = anthropic_client()
    if client is None:
        sample = await _sample_fallback(text)
        if sample:
            return sample, [{"note": "mock mode: served sample bundle"}]
        raise RuntimeError("ANTHROPIC_API_KEY is not set and no sample matches this question")

    tricks = kb.retrieve(text, subject, k=8)
    system = SYSTEM_PROMPT.format(language=language, knowledge="\n".join(t.to_prompt() for t in tricks) or "(none matched)")
    user = f"Exam: {exam or 'general'}\nQuestion: {text}\nOptions: {'; '.join(options) if options else '(none)'}"
    msg = await client.messages.create(
        model=MODEL, max_tokens=8000, system=system,
        messages=[{"role": "user", "content": user}],
        tools=[SUBMIT_TOOL], tool_choice={"type": "tool", "name": "submit_lessons"},
    )
    payload: dict[str, Any] | None = next((b.input for b in msg.content if b.type == "tool_use"), None)
    if not payload:
        raise RuntimeError("model did not return lessons")

    truth = payload["ground_truth"]
    lessons_raw: list[dict] = payload.get("lessons", [])
    report: list[dict] = []

    # 1) prove the ground truth, 2) prove each lesson, 3) require every lesson to agree with the truth
    checks = [truth["check"]] + [l.get("check", {}) for l in lessons_raw]
    results = await _verify(checks)
    if not results[0]["ok"]:
        raise RuntimeError(f"ground-truth answer failed verification: {results[0]['detail']}")
    lessons: list[LessonScript] = []
    qid = question_id(text)
    for raw, res in zip(lessons_raw, results[1:]):
        tid = raw.get("trick_id", "unknown")
        if not res["ok"]:
            report.append({"trick_id": tid, "dropped": True, "reason": res["detail"]})
            continue
        if _norm(raw.get("final_answer", "")) != _norm(truth["final_answer"]):
            report.append({"trick_id": tid, "dropped": True, "reason": "answer differs from ground truth"})
            continue
        steps = [LessonStep(id=f"s{i + 1}", say=s["say"], pause_ms=int(s.get("pause_ms", 350)),
                            actions=_clean_actions(s.get("actions", [])))
                 for i, s in enumerate(raw.get("steps", [])) if s.get("say")]
        if not steps:
            continue
        lessons.append(LessonScript(
            question_id=qid, title=raw.get("title", tid), trick_id=tid, language=language,
            estimated_seconds=int(raw.get("estimated_seconds", 0)), works_when=raw.get("works_when", ""),
            answer=truth["final_answer"], steps=steps))
        report.append({"trick_id": tid, "dropped": False, "detail": res["detail"]})
    if not lessons:
        raise RuntimeError("no trick survived verification")
    lessons.sort(key=lambda l: l.estimated_seconds or 999)

    if with_voice:
        teacher = await _resolve_teacher(teacher_id)
        async with httpx.AsyncClient(timeout=120) as http:
            voiced = await asyncio.gather(
                *[http.post(f"{VOICE_URL}/lesson", json=_voice_payload(l, teacher)) for l in lessons],
                return_exceptions=True)
        for i, v in enumerate(voiced):
            if isinstance(v, httpx.Response) and v.status_code == 200:
                lessons[i] = LessonScript(**v.json())
            else:
                log.warning("voice failed for lesson %s", lessons[i].trick_id)

    q = Question(id=qid, exam=exam, subject=payload.get("subject") or subject or "", text=text, options=options,
                 correct_option=truth.get("correct_option", ""))
    return LessonBundle(question=q, lessons=lessons), report


async def _claude_ndjson_lines(system: str, user: str) -> AsyncIterator[dict]:
    """Yield complete JSON objects as soon as each NDJSON line finishes streaming."""
    buffer = ""
    async with _client.messages.stream(  # type: ignore[union-attr]  # callers only reach here with a real client
        model=MODEL, max_tokens=8000, system=system, messages=[{"role": "user", "content": user}],
    ) as stream:
        async for chunk in stream.text_stream:
            buffer += chunk
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip().strip("`")
                if line.startswith("{"):
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        log.warning("bad NDJSON line skipped (generate stream)")
        tail = buffer.strip()
        if tail.startswith("{"):
            try:
                yield json.loads(tail)
            except json.JSONDecodeError:
                pass


async def generate_stream(text: str, options: list[str], exam: str, subject: str | None,
                          language: str, teacher_id: str | None = None) -> AsyncIterator[dict]:
    """Same pipeline as generate(), but yields a {"type":"question"} event as soon as the ground
    truth is verified, then one {"type":"lesson"} event per trick as it finishes generation +
    verification + voice — so the fastest trick can start playing while slower ones are still
    being written, instead of the student waiting for every trick to be ready at once."""
    qid = question_id(text)
    client = anthropic_client()
    if client is None:
        sample = await _sample_fallback(text)
        if sample is None:
            yield {"type": "error", "message": "ANTHROPIC_API_KEY is not set and no sample matches this question"}
            return
        yield {"type": "question", "question": sample.question.model_dump(mode="json")}
        for lesson in sample.lessons:
            yield {"type": "lesson", "lesson": lesson.model_dump(mode="json")}
        yield {"type": "done"}
        return

    tricks = kb.retrieve(text, subject, k=8)
    system = STREAM_SYSTEM_PROMPT.format(language=language, knowledge="\n".join(t.to_prompt() for t in tricks) or "(none matched)")
    user = f"Exam: {exam or 'general'}\nQuestion: {text}\nOptions: {'; '.join(options) if options else '(none)'}"

    teacher = await _resolve_teacher(teacher_id)
    truth: dict[str, Any] | None = None
    lessons: list[LessonScript] = []
    async with httpx.AsyncClient(timeout=30) as http:
        async for obj in _claude_ndjson_lines(system, user):
            if truth is None and isinstance(obj.get("ground_truth"), dict):
                truth = obj["ground_truth"]
                res = (await _verify([truth.get("check", {})]))[0]
                if not res["ok"]:
                    yield {"type": "error", "message": f"ground-truth answer failed verification: {res['detail']}"}
                    return
                q = Question(id=qid, exam=exam, subject=subject or "", text=text, options=options,
                             correct_option=truth.get("correct_option", ""))
                yield {"type": "question", "question": q.model_dump(mode="json")}
            elif truth is not None and isinstance(obj.get("lesson"), dict):
                raw = obj["lesson"]
                tid = raw.get("trick_id", "unknown")
                res = (await _verify([raw.get("check", {})]))[0]
                if not res["ok"]:
                    yield {"type": "dropped", "trick_id": tid, "reason": res["detail"]}
                    continue
                if _norm(raw.get("final_answer", "")) != _norm(truth["final_answer"]):
                    yield {"type": "dropped", "trick_id": tid, "reason": "answer differs from ground truth"}
                    continue
                steps = [LessonStep(id=f"s{i + 1}", say=s["say"], pause_ms=int(s.get("pause_ms", 350)),
                                    actions=_clean_actions(s.get("actions", [])))
                         for i, s in enumerate(raw.get("steps", [])) if s.get("say")]
                if not steps:
                    continue
                lesson = LessonScript(question_id=qid, title=raw.get("title", tid), trick_id=tid, language=language,
                                      estimated_seconds=int(raw.get("estimated_seconds", 0)),
                                      works_when=raw.get("works_when", ""), answer=truth["final_answer"], steps=steps)
                try:
                    r = await http.post(f"{VOICE_URL}/lesson", json=_voice_payload(lesson, teacher), timeout=120)
                    if r.status_code == 200:
                        lesson = LessonScript(**r.json())
                    else:
                        log.warning("voice failed for lesson %s", tid)
                except Exception:  # noqa: BLE001 - ship the trick silently, speak it with on-device TTS instead
                    log.warning("voice unavailable for lesson %s", tid)
                lessons.append(lesson)
                yield {"type": "lesson", "lesson": lesson.model_dump(mode="json")}

    if truth is None:
        yield {"type": "error", "message": "model did not return a ground truth"}
        return
    if not lessons:
        yield {"type": "error", "message": "no trick survived verification"}
        return
    if GATEWAY_DATA_DIR:
        try:
            q = Question(id=qid, exam=exam, subject=subject or "", text=text, options=options,
                        correct_option=truth.get("correct_option", ""))
            bundle = LessonBundle(question=q, lessons=lessons)
            (Path(GATEWAY_DATA_DIR) / f"{qid}.json").write_text(bundle.model_dump_json(exclude_none=True), encoding="utf-8")
        except Exception:  # noqa: BLE001 - caching is a nice-to-have, never block the live answer on it
            log.warning("could not cache live-solved bundle for %s", qid)
    yield {"type": "done"}
