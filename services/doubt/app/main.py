"""Raise-hand service: streams a spoken + drawn answer to a student's doubt over a WebSocket.

Flow per doubt:  Claude streams NDJSON steps -> each step is math-checked by the verifier (if it
carries a check) -> voice service adds audio + timings -> step is sent to the phone. Steps are
sent in order, and speech synthesis of step n overlaps with Claude writing step n+1, which is what
keeps time-to-first-word low.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import AsyncIterator

import httpx
from anthropic import AsyncAnthropic
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from lessonkit import Action, LessonStep

from .prompts import DOUBT_SYSTEM

log = logging.getLogger("doubt")
app = FastAPI(title="ExamTricks doubt", version="0.1.0")

FAST_MODEL = os.getenv("DOUBT_FAST_MODEL", "claude-haiku-5-5")
STRONG_MODEL = os.getenv("DOUBT_STRONG_MODEL", "claude-sonnet-5-5")
VERIFIER_URL = os.getenv("VERIFIER_URL", "http://verifier:8002")
VOICE_URL = os.getenv("VOICE_URL", "http://voice:8003")
MAX_STEPS = 6
MAX_DOUBT_CHARS = 500

_client = AsyncAnthropic() if os.getenv("ANTHROPIC_API_KEY") else None


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "doubt", "mock": _client is None}


def pick_model(doubt: str) -> str:
    """Short, simple doubts go to the fast model; long or multi-part ones to the strong model."""
    return FAST_MODEL if len(doubt) < 120 and doubt.count("?") <= 1 else STRONG_MODEL


def build_context(msg: dict) -> str:
    q = msg.get("question", {})
    lesson = msg.get("lesson", {})
    shown = "\n".join(f"- {s}" for s in msg.get("steps_so_far", [])[-12:])
    return (
        f"QUESTION: {q.get('text', '')}\nOPTIONS: {'; '.join(q.get('options', []))}\n"
        f"CURRENT TRICK: {lesson.get('title', '')} (answer: {lesson.get('answer', '')})\n"
        f"WHAT THE TEACHER HAS SAID/WRITTEN SO FAR:\n{shown}\n"
        f"The student paused at step {msg.get('step_index', 0) + 1}.\n"
        f"STUDENT'S DOUBT: {msg.get('doubt', '')[:MAX_DOUBT_CHARS]}"
    )


async def claude_steps(msg: dict, feedback: str = "") -> AsyncIterator[dict]:
    """Yield complete JSON step objects as soon as each NDJSON line is finished."""
    language = msg.get("language", "hinglish")
    user = build_context(msg) + (f"\n\nYour previous attempt failed a math check ({feedback}). Fix it." if feedback else "")
    if _client is None:  # mock mode so the app works end to end without an API key
        for say in ["Achha doubt hai! Pehle dekhte hain aapne kahan tak samjha.",
                    "Is step mein hum sirf identity laga rahe hain, koi naya concept nahi.",
                    "Ab clear hua? Agar nahi, to dobara poochh sakte ho."]:
            yield {"say": say, "actions": []}
        return
    buffer = ""
    async with _client.messages.stream(
        model=pick_model(msg.get("doubt", "")), max_tokens=1500,
        system=DOUBT_SYSTEM.format(language=language), messages=[{"role": "user", "content": user}],
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
                        log.warning("bad NDJSON line skipped")
        tail = buffer.strip()
        if tail.startswith("{"):
            try:
                yield json.loads(tail)
            except json.JSONDecodeError:
                pass


async def check_step(http: httpx.AsyncClient, raw: dict) -> tuple[bool, str]:
    check = raw.get("check")
    if not check or not isinstance(check, dict):
        return True, ""  # no check, or the model sent something that isn't even an object (seen: a bare "identity")
    try:
        r = await http.post(f"{VERIFIER_URL}/verify", json={"checks": [check]}, timeout=15)
        if r.status_code != 200:
            return True, ""  # the verifier rejected the request shape itself: unverifiable, not wrong
        res = r.json()["results"][0]
        detail = res.get("detail", "")
        if not res["ok"] and (detail.startswith("missing field") or detail.startswith("unknown check kind")):
            # The doubt model (fast/Haiku) sometimes sends a check with the wrong field names for its
            # chosen kind — that's a schema slip, not proof the maths is wrong. Failing (and retrying,
            # then erroring out to the student) over a formatting mistake is worse than just not
            # verifying this one step, so treat it the same as "no check was given".
            return True, ""
        return bool(res["ok"]), detail
    except Exception:  # noqa: BLE001 - verifier down: fail closed, the teacher re-checks instead of guessing
        return False, "verifier unavailable"


async def voice_step(http: httpx.AsyncClient, step: LessonStep) -> LessonStep:
    try:
        r = await http.post(f"{VOICE_URL}/tts", json={"text": step.say}, timeout=60)
        if r.status_code == 200:
            data = r.json()
            step.audio_url, step.alignment = data["audio_url"], data["alignment"]
    except Exception:  # noqa: BLE001 - the app falls back to on-device speech
        log.warning("voice unavailable for doubt step")
    return step


async def answer_doubt(ws: WebSocket, msg: dict) -> None:
    async with httpx.AsyncClient() as http:
        feedback = ""
        for attempt in (1, 2):  # one retry if a step fails verification
            queue: asyncio.Queue[asyncio.Task | None] = asyncio.Queue()
            failed = {"reason": ""}

            async def produce() -> None:
                n = 0
                try:
                    async for raw in claude_steps(msg, feedback):
                        if not raw.get("say"):
                            continue
                        ok, detail = await check_step(http, raw)
                        if not ok:
                            failed["reason"] = detail
                            return
                        n += 1
                        step = LessonStep(
                            id=f"d{n}", say=str(raw["say"])[:400], pause_ms=int(raw.get("pause_ms", 300)),
                            actions=[a for a in _actions(raw.get("actions", []))])
                        await queue.put(asyncio.create_task(voice_step(http, step)))
                        if n >= MAX_STEPS:
                            return
                finally:
                    await queue.put(None)

            producer = asyncio.create_task(produce())
            sent = 0
            while (task := await queue.get()) is not None:
                step = await task
                await ws.send_json({"type": "step", "step": step.model_dump(mode="json", exclude_none=True)})
                sent += 1
            await producer
            if not failed["reason"]:
                await ws.send_json({"type": "done", "steps": sent})
                return
            feedback = failed["reason"]
            if attempt == 1:
                await ws.send_json({"type": "notice", "message": "rechecking"})
        await ws.send_json({"type": "error", "message": "Could not verify the answer. Please ask again."})


def _actions(raw: list) -> list[Action]:
    out = []
    for a in raw or []:
        try:
            for k in ("x", "y", "x2", "y2"):
                if k in a:
                    a[k] = min(1.0, max(0.0, float(a[k])))
            out.append(Action(**a))
        except Exception:  # noqa: BLE001
            continue
    return out


@app.websocket("/ws/doubt")
async def ws_doubt(ws: WebSocket) -> None:
    await ws.accept()
    try:
        while True:
            msg = await ws.receive_json()
            if msg.get("type") != "doubt" or not str(msg.get("doubt", "")).strip():
                await ws.send_json({"type": "error", "message": "send {type:'doubt', doubt:'...'}"})
                continue
            await answer_doubt(ws, msg)
    except WebSocketDisconnect:
        return
