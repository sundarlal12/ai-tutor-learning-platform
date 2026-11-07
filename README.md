# ai-tutor — ExamTricks backend (FastAPI microservices)

Backend-only split of the ExamTricks project: the five FastAPI services that solve exam
questions with Claude, verify every trick with SymPy, voice it with Sarvam, and stream both the
live solve and "raise hand" doubts to the Android app over WebSocket.

This repo is public; `knowledge/tricks/*.yaml` — the actual trick content the generator teaches
from — is deliberately gitignored and deployed straight to Railway from local instead, so the
product's teaching logic isn't sitting in a public repo. `generator`'s `KNOWLEDGE_DIR` just needs
that folder present wherever it runs; see `knowledge/tricks/` in this repo's working copy if
you're setting up a new deploy target.

## Layout
| Path | What |
|---|---|
| `knowledge/tricks/*.yaml` | Trick recipes (identity, substitution, option-elimination, ...) with a machine-checkable `proof` — **not in this public repo**, see note above |
| `libs/lessonkit` | Shared models, YAML knowledge base + retrieval, SymPy proof checker |
| `services/gateway` :8100 | App-facing REST API — question list / bundle / solve, file-backed cache |
| `services/generator` :8101 | Claude → verified lesson scripts. `/generate` (batch) and `/ws/generate` (live NDJSON stream — fastest trick first) |
| `services/verifier` :8102 | Sandboxed math verification (4 check kinds: identity, numeric, solve_target, option_check) |
| `services/voice` :8103 | Sarvam TTS with per-step audio + cache (mock mode without a key) |
| `services/doubt` :8104 | WebSocket: student doubt → streamed, verified, voiced answer |
| `db/init.sql` | PostgreSQL schema for a production store (the dev gateway uses local JSON files) |

## Run locally
```bash
cp .env.example .env        # add ANTHROPIC_API_KEY and SARVAM_API_KEY for real generation/voice
docker compose up --build   # or run each service with uvicorn app.main:app --port <port>
python3 tools/validate_tricks.py          # checks YAML + runs every proof
```
Without keys the services run in **mock mode** (sample lessons from `sample/bundles`, no Claude/Sarvam calls).

## ⚠️ Why this is NOT a Vercel deploy as-is
Two of these five services only work over a **persistent WebSocket** (`doubt` and `generator`'s
`/ws/generate` — this is what makes the live solve + raise-hand-doubt features in the Android app
work at all). Vercel's functions are request/response serverless functions with no WebSocket
support, so those two services cannot run there in their current form. The `gateway` and `voice`
services also write to local disk (cached bundles, cached audio files) — Vercel's filesystem is
ephemeral per invocation, so that caching would silently stop working too.

**What this means in practice:**
- `verifier` (pure stateless HTTP, no WS, no disk writes) would run on Vercel fine.
- `generator`'s plain `/generate` HTTP endpoint *could* run there, but a full multi-trick solve
  took ~45–50s in testing — past Vercel's Hobby-tier 10s limit and close to the Pro-tier default.
- `doubt` and `generator`'s `/ws/generate` need a host that keeps a process alive and speaks
  WebSocket: Railway, Render, Fly.io, or a plain VPS (e.g. a Docker Compose deploy using the
  `docker-compose.yml` already in this repo — no rewrite needed) all do this natively.
- `gateway`'s file cache and `voice`'s audio cache need persistent disk or a real database/object
  store (S3, R2, or the Postgres schema in `db/init.sql`) wherever this ends up running.

Happy to wire up whichever of those you pick — flagging this now so we don't spend effort
building Vercel-specific serverless wrappers for endpoints that can't actually serve the live
features once deployed.
