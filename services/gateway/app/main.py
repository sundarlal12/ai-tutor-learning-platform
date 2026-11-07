"""Public REST API used by the Android app.

Storage is file-based (one JSON bundle per question) so it runs with zero setup. db/init.sql holds
the PostgreSQL schema for production; swap `Store` for a SQL-backed class when you move there.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from lessonkit import LessonBundle

API_KEY = os.getenv("API_KEY", "")  # empty = open (development only)
GENERATOR_URL = os.getenv("GENERATOR_URL", "http://generator:8001")
DATA_DIR = Path(os.getenv("DATA_DIR", "./data/bundles"))
SEED_DIR = Path(os.getenv("SEED_DIR", "/sample/bundles"))

DATA_DIR.mkdir(parents=True, exist_ok=True)
app = FastAPI(title="ExamTricks gateway", version="0.1.0")
# Browser-based teacher templates (web/) fetch this cross-origin; the Android app doesn't need
# this (CORS is a browser-only mechanism), but without it every fetch() from a page fails.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_ID = re.compile(r"^[A-Za-z0-9_-]{3,64}$")  # ids become file names: never trust them


def auth(x_api_key: str | None = Header(default=None)) -> None:
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(401, "invalid API key")


class Store:
    def __init__(self, root: Path, seed: Path):
        self.root = root
        if seed.exists():
            for f in seed.glob("*.json"):
                target = root / f.name
                if not target.exists():
                    target.write_text(f.read_text(encoding="utf-8"), encoding="utf-8")

    def get(self, qid: str) -> LessonBundle | None:
        if not _ID.match(qid):
            return None
        path = self.root / f"{qid}.json"
        return LessonBundle(**json.loads(path.read_text(encoding="utf-8"))) if path.exists() else None

    def put(self, bundle: LessonBundle) -> None:
        (self.root / f"{bundle.question.id}.json").write_text(bundle.model_dump_json(exclude_none=True), encoding="utf-8")

    def list(self) -> list[dict]:
        out = []
        for f in sorted(self.root.glob("*.json")):
            q = json.loads(f.read_text(encoding="utf-8"))["question"]
            out.append({k: q.get(k, "") for k in ("id", "exam", "subject", "text")})
        return out


store = Store(DATA_DIR, SEED_DIR)


class SolveRequest(BaseModel):
    text: str = Field(..., min_length=5, max_length=2000)
    options: list[str] = Field(default_factory=list)
    exam: str = ""
    subject: str | None = None
    language: str = "hinglish"


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "gateway", "questions": len(store.list())}


@app.get("/v1/questions", dependencies=[Depends(auth)])
def list_questions(response: Response, subject: str | None = None) -> list[dict]:
    response.headers["Cache-Control"] = "no-store"
    return [q for q in store.list() if not subject or q["subject"] == subject]


@app.get("/v1/questions/{qid}/bundle", response_model=LessonBundle, dependencies=[Depends(auth)])
def get_bundle(qid: str, response: Response) -> LessonBundle:
    response.headers["Cache-Control"] = "no-store"
    bundle = store.get(qid)
    if bundle is None:
        raise HTTPException(404, "question not found")
    return bundle


@app.post("/v1/questions/solve", response_model=LessonBundle, dependencies=[Depends(auth)])
async def solve(req: SolveRequest) -> LessonBundle:
    """Photo-snap / typed question: generate (or reuse) verified lessons."""
    async with httpx.AsyncClient(timeout=180) as http:
        try:
            r = await http.post(f"{GENERATOR_URL}/generate", json=req.model_dump())
        except httpx.HTTPError as exc:
            raise HTTPException(503, "generator unavailable") from exc
    if r.status_code != 200:
        raise HTTPException(r.status_code, r.json().get("detail", "generation failed"))
    bundle = LessonBundle(**r.json()["bundle"])
    store.put(bundle)  # cache: the next student gets it instantly with no AI cost
    return bundle


@app.get("/v1/tricks", dependencies=[Depends(auth)])
async def tricks(subject: str | None = None) -> list[dict]:
    async with httpx.AsyncClient(timeout=15) as http:
        r = await http.get(f"{GENERATOR_URL}/tricks", params={"subject": subject} if subject else None)
    return r.json()
