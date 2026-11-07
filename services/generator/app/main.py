from __future__ import annotations

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from lessonkit import LessonBundle

from . import pipeline

app = FastAPI(title="ExamTricks generator", version="0.1.0")


class GenerateRequest(BaseModel):
    text: str = Field(..., min_length=5, max_length=2000)
    options: list[str] = Field(default_factory=list)
    exam: str = ""
    subject: str | None = None
    language: str = "hinglish"
    with_voice: bool = True


class GenerateResponse(BaseModel):
    bundle: LessonBundle
    report: list[dict]


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "generator", "tricks_loaded": len(pipeline.kb.tricks),
            "mock": pipeline.anthropic_client() is None}


@app.get("/tricks")
def tricks(subject: str | None = None) -> list[dict]:
    items = [t for t in pipeline.kb.tricks if not subject or t.subject == subject]
    return [{"id": t.id, "name": t.name, "subject": t.subject, "topic": t.topic, "when": t.when,
             "idea": t.idea, "steps": t.steps, "example": t.example.model_dump(),
             "speed_seconds": t.speed_seconds, "caution": t.caution} for t in items]


@app.post("/generate", response_model=GenerateResponse)
async def generate(req: GenerateRequest) -> GenerateResponse:
    try:
        bundle, report = await pipeline.generate(
            req.text, req.options, req.exam, req.subject, req.language, req.with_voice)
    except RuntimeError as exc:
        raise HTTPException(422, str(exc)) from exc
    return GenerateResponse(bundle=bundle, report=report)


@app.websocket("/ws/generate")
async def ws_generate(ws: WebSocket) -> None:
    """Live variant of /generate: streams a {"type":"question"} event once the ground truth is
    verified, then one {"type":"lesson"} event per trick as each is generated, verified and
    voiced — the fastest trick can start playing on the student's board immediately instead of
    waiting for every trick in the bundle to finish."""
    await ws.accept()
    try:
        while True:
            msg = await ws.receive_json()
            if msg.get("type") != "solve" or not str(msg.get("text", "")).strip():
                await ws.send_json({"type": "error", "message": "send {type:'solve', text:'...'}"})
                continue
            async for event in pipeline.generate_stream(
                msg["text"], msg.get("options", []), msg.get("exam", ""), msg.get("subject"),
                msg.get("language", "hinglish"),
            ):
                await ws.send_json(event)
    except WebSocketDisconnect:
        return
