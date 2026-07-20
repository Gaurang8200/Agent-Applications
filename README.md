# Agent-Applications

Job application autopilot. The agent finds postings, matches them to your
profile, tailors your resume, and pre-fills the application. **You review and
submit** — the agent never sends an application on its own.

## Repository structure

```
├── frontend/          Next.js 16 web app (auth, dashboard, resume upload)
├── backend/           FastAPI service
│   ├── app/agents/    AI agent stages (ingest → discover → match → tailor → prefill → track)
│   ├── app/api/       HTTP routes
│   ├── app/models/    SQLAlchemy models
│   ├── app/services/  Storage, text extraction
│   └── alembic/       Database migrations
├── infra/
│   └── docker/        docker-compose for local Postgres+pgvector, Redis, MinIO
├── deployment/        Production deployment notes and configs
├── docs/              Architecture documentation
└── packages/          Shared code (reserved)
```

## Quick start

```sh
cp .env.example .env          # fill in ANTHROPIC_API_KEY and JWT_SECRET
docker compose --env-file .env -f infra/docker/docker-compose.yml up -d

cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --reload        # http://localhost:8000

cd ../frontend
npm install && npm run dev                     # http://localhost:3000
```

Note: Postgres is exposed on host port **5433** to avoid clashing with any
native Postgres on 5432.

## Agent pipeline

| Stage | Status | Does |
|---|---|---|
| Ingest | ✅ | Parse resume into a structured, user-verified profile |
| Discover | planned | Pull postings from job-board APIs |
| Match | planned | Rank postings vs profile (pgvector + Claude scoring) |
| Tailor | planned | Per-posting resume + cover letter, grounded in the real profile |
| Prefill | planned | Fill the application form, screenshot, stop for review |
| Track | planned | Status board and follow-ups |

## License

MIT
