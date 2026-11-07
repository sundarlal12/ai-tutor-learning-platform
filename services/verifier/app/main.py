"""Verifier service: proves a trick's answer is right before any student sees it."""
from __future__ import annotations

import asyncio

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from lessonkit.proofs import run_check

app = FastAPI(title="ExamTricks verifier", version="0.1.0")

MAX_CHECKS = 20
TIMEOUT_S = 10.0


class VerifyRequest(BaseModel):
    checks: list[dict] = Field(..., description="Check specs, see lessonkit.proofs for kinds")


class CheckOut(BaseModel):
    ok: bool
    detail: str
    info: dict = Field(default_factory=dict)


class VerifyResponse(BaseModel):
    all_ok: bool
    results: list[CheckOut]


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "verifier"}


async def _one(spec: dict) -> CheckOut:
    try:
        res = await asyncio.wait_for(asyncio.to_thread(run_check, spec), timeout=TIMEOUT_S)
        return CheckOut(ok=res.ok, detail=res.detail, info=res.info)
    except asyncio.TimeoutError:
        return CheckOut(ok=False, detail="verification timed out")
    except Exception as exc:  # noqa: BLE001 - never leak a stack trace to callers
        return CheckOut(ok=False, detail=f"verifier error: {type(exc).__name__}")


@app.post("/verify", response_model=VerifyResponse)
async def verify(req: VerifyRequest) -> VerifyResponse:
    if not req.checks:
        raise HTTPException(400, "no checks supplied")
    if len(req.checks) > MAX_CHECKS:
        raise HTTPException(400, f"at most {MAX_CHECKS} checks per request")
    results = await asyncio.gather(*[_one(c) for c in req.checks])
    return VerifyResponse(all_ok=all(r.ok for r in results), results=list(results))
