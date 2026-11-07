"""Voice service: text -> speech audio plus per-character timings (for lip sync).

Two real providers, picked by VOICE_PROVIDER (default: first one with keys set, else mock):
  - elevenlabs: library voice, returns exact per-character timings ("with-timestamps").
  - sarvam: Indic-language voices (bulbul); no per-character timings, so we scale the same
    estimated-timing shape used in mock mode to the real audio's measured duration.
Mock mode (no provider configured): no audio file, only estimated timings, and the Android
app falls back to the phone's own text-to-speech.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import wave
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sarvamai import SarvamAI
from sarvamai.play import save as sarvam_save

from lessonkit import Alignment, LessonScript

API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "")  # pick a library voice id in the ElevenLabs dashboard
MODEL_ID = os.getenv("ELEVENLABS_MODEL", "eleven_multilingual_v2")

SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "")
SARVAM_MODEL = os.getenv("SARVAM_MODEL", "bulbul:v3")
SARVAM_SPEAKER = os.getenv("SARVAM_SPEAKER", "ritu")
SARVAM_LANGUAGE = os.getenv("SARVAM_LANGUAGE", "hi-IN")
SARVAM_PACE = float(os.getenv("SARVAM_PACE", "0.8"))  # 1.0 = normal; <1 slower, easier to follow on a board
_sarvam_client = SarvamAI(api_subscription_key=SARVAM_API_KEY) if SARVAM_API_KEY else None

VOICE_PROVIDER = os.getenv("VOICE_PROVIDER") or (
    "sarvam" if SARVAM_API_KEY else "elevenlabs" if (API_KEY and VOICE_ID) else "mock"
)

MEDIA_DIR = Path(os.getenv("MEDIA_DIR", "./media"))
PUBLIC_BASE = os.getenv("PUBLIC_BASE_URL", "http://localhost:8003").rstrip("/")
MOCK_SECONDS_PER_CHAR = 0.065

MEDIA_DIR.mkdir(parents=True, exist_ok=True)
app = FastAPI(title="ExamTricks voice", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/media", StaticFiles(directory=MEDIA_DIR), name="media")
_sem = asyncio.Semaphore(4)  # stay inside provider concurrency limits


@app.middleware("http")
async def fix_wav_content_type(request, call_next):
    # Python's mimetypes (which StaticFiles uses) maps .wav to the legacy "audio/x-wav" on
    # some systems (this Mac included) instead of the standard "audio/wav" — Android WebView's
    # <audio> element can refuse to play that, failing completely silently with no player error
    # a caller would normally catch, which looks exactly like "the voice never plays."
    response = await call_next(request)
    if request.url.path.endswith(".wav"):
        response.headers["content-type"] = "audio/wav"
    return response


class TtsRequest(BaseModel):
    text: str
    voice_id: str | None = None
    # Per-teacher voice override (resolved by the caller from gateway's /v1/teachers) — falls
    # back to the SARVAM_* env vars above when not given, so existing callers need no changes.
    speaker: str | None = None
    language: str | None = None
    pace: float | None = None


class TtsResponse(BaseModel):
    audio_url: str | None
    alignment: Alignment
    duration_ms: int
    mock: bool


def _mock_alignment(text: str) -> Alignment:
    chars = list(text)
    start = [round(i * MOCK_SECONDS_PER_CHAR, 3) for i in range(len(chars))]
    end = [round((i + 1) * MOCK_SECONDS_PER_CHAR, 3) for i in range(len(chars))]
    return Alignment(chars=chars, start=start, end=end)


def _scaled_alignment(text: str, duration_s: float) -> Alignment:
    """No per-character timing from the provider: spread chars evenly over the real audio
    duration so lip sync at least starts and ends in the right place, instead of drifting."""
    chars = list(text)
    n = len(chars)
    if n == 0 or duration_s <= 0:
        return Alignment(chars=chars, start=[0.0] * n, end=[0.0] * n)
    start = [round(i / n * duration_s, 3) for i in range(n)]
    end = [round((i + 1) / n * duration_s, 3) for i in range(n)]
    return Alignment(chars=chars, start=start, end=end)


def _wav_duration_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "voice", "provider": VOICE_PROVIDER, "mock": VOICE_PROVIDER == "mock"}


async def _synthesize_sarvam(text: str, speaker: str | None = None, language: str | None = None,
                             pace: float | None = None) -> TtsResponse:
    speaker, language = speaker or SARVAM_SPEAKER, language or SARVAM_LANGUAGE
    pace = SARVAM_PACE if pace is None else pace
    key = hashlib.sha256(f"sarvam|{SARVAM_MODEL}|{speaker}|{language}|{pace}|{text}".encode()).hexdigest()[:32]
    wav_path, meta = MEDIA_DIR / f"{key}.wav", MEDIA_DIR / f"{key}.json"
    if wav_path.exists() and meta.exists():  # cache hit: no provider cost, no latency
        al = Alignment(**json.loads(meta.read_text()))
    else:
        async with _sem:
            loop = asyncio.get_running_loop()
            try:
                response = await loop.run_in_executor(
                    None,
                    lambda: _sarvam_client.text_to_speech.convert(
                        text=text, language_code=language, model=SARVAM_MODEL, speaker=speaker, pace=pace,
                    ),
                )
            except Exception as e:  # noqa: BLE001 - surface the provider's own message
                raise HTTPException(502, f"sarvam tts error: {e}") from e
        sarvam_save(response, str(wav_path))
        al = _scaled_alignment(text, _wav_duration_seconds(wav_path))
        meta.write_text(al.model_dump_json())
    return TtsResponse(
        audio_url=f"{PUBLIC_BASE}/media/{key}.wav", alignment=al,
        duration_ms=int((al.end[-1] if al.end else 0) * 1000), mock=False,
    )


async def _synthesize_elevenlabs(text: str, voice_id: str | None = None) -> TtsResponse:
    voice = voice_id or VOICE_ID
    key = hashlib.sha256(f"{voice}|{MODEL_ID}|{text}".encode()).hexdigest()[:32]
    mp3, meta = MEDIA_DIR / f"{key}.mp3", MEDIA_DIR / f"{key}.json"
    if mp3.exists() and meta.exists():  # cache hit: no provider cost, no latency
        al = Alignment(**json.loads(meta.read_text()))
    else:
        async with _sem, httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice}/with-timestamps",
                headers={"xi-api-key": API_KEY},
                json={"text": text, "model_id": MODEL_ID},
            )
        if resp.status_code != 200:
            raise HTTPException(502, f"tts provider error {resp.status_code}")
        data = resp.json()
        mp3.write_bytes(base64.b64decode(data["audio_base64"]))
        a = data.get("alignment") or data.get("normalized_alignment") or {}
        al = Alignment(
            chars=a.get("characters", []),
            start=a.get("character_start_times_seconds", []),
            end=a.get("character_end_times_seconds", []),
        )
        meta.write_text(al.model_dump_json())
    return TtsResponse(
        audio_url=f"{PUBLIC_BASE}/media/{key}.mp3", alignment=al,
        duration_ms=int((al.end[-1] if al.end else 0) * 1000), mock=False,
    )


async def synthesize(text: str, voice_id: str | None = None, speaker: str | None = None,
                     language: str | None = None, pace: float | None = None) -> TtsResponse:
    text = text.strip()
    if not text:
        raise HTTPException(400, "empty text")
    if VOICE_PROVIDER == "sarvam":
        return await _synthesize_sarvam(text, speaker, language, pace)
    if VOICE_PROVIDER == "elevenlabs":
        return await _synthesize_elevenlabs(text, voice_id)
    al = _mock_alignment(text)
    return TtsResponse(audio_url=None, alignment=al, duration_ms=int((al.end[-1] if al.end else 0) * 1000), mock=True)


@app.post("/tts", response_model=TtsResponse)
async def tts(req: TtsRequest) -> TtsResponse:
    return await synthesize(req.text, req.voice_id, req.speaker, req.language, req.pace)


class VoiceLessonRequest(LessonScript):
    speaker: str | None = None
    language: str | None = None
    pace: float | None = None


@app.post("/lesson", response_model=LessonScript)
async def voice_lesson(req: VoiceLessonRequest) -> LessonScript:
    """Adds audio_url + alignment to every step of a lesson (steps are synthesised in parallel)."""
    results = await asyncio.gather(
        *[synthesize(s.say, speaker=req.speaker, language=req.language, pace=req.pace) for s in req.steps])
    lesson = LessonScript(**req.model_dump(exclude={"speaker", "language", "pace"}))
    for step, res in zip(lesson.steps, results):
        step.audio_url, step.alignment = res.audio_url, res.alignment
    return lesson
