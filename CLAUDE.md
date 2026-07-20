# Agent Applications

Job application autopilot. The agent finds, matches, tailors, and pre-fills.
The user submits. Agents never advance an application past `ready_for_review`.

## Output style — most important rule

**Keep chat output minimal.** Long summaries burn the user's context window,
which is the scarcest resource in this project.

- No recap of what you just did — the tool calls already showed it.
- No "what works" tables, no restating file contents back.
- Report only: what broke, what decision needs the user, what's next. One or
  two lines each.
- Prefer a short fragment over a full sentence. Skip preamble and sign-off.
- Never re-explain context from earlier in the session.
- Code, commit messages, and security warnings are written normally — this rule
  is about chat prose only.

Target: under ~10 lines per turn unless the user asks for detail.

## Stack

- `apps/api` — FastAPI, SQLAlchemy, Alembic, Python 3.11 (venv at `apps/api/.venv`)
- `apps/web` — Next.js 16, React 19, Tailwind 4. Read `apps/web/AGENTS.md` first;
  Next 16 has breaking changes from v15.
- `infra/docker-compose.yml` — Postgres 16 + pgvector, Redis 7, MinIO

## Local setup

```sh
cp .env.example .env                                     # then fill ANTHROPIC_API_KEY
docker compose --env-file .env -f infra/docker-compose.yml up -d
cd apps/api && .venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --reload                  # :8000
cd apps/web && npm run dev                               # :3000
```

## Gotchas

- **Postgres is on host port 5433**, not 5432 — a native Homebrew Postgres
  commonly owns 5432 and silently shadows the container on `localhost`.
- **Repo lives in iCloud Drive.** If git reports `object file ... is empty`,
  that's iCloud eviction — re-clone from GitHub. Do not move the folder.
- **No `ANTHROPIC_API_KEY`** means resume parsing falls back to regex, which
  extracts contact details and skills but deliberately no work history.
- Use `bcrypt` directly, not `passlib` — passlib is unmaintained and breaks
  against bcrypt 4.x.
- pgvector's Alembic autogenerate omits its own import; the migration template
  in `apps/api/alembic/script.py.mako` adds it back.
