# Architecture

## Principle: human approval gate

Agents may advance an application only as far as `ready_for_review`. The
transition to `submitted` requires an explicit user action, recorded on the
`applications` row as `approved_by_user_at` and in the append-only
`application_events` table with `actor = "user"`. Auto-submission is
deliberately not built: it violates most job boards' terms of service and gets
accounts banned.

## Pipeline stages

Each stage lives in `backend/app/agents/` as an independent module.

1. **Ingest** (`resume_parser.py`, done) — PDF/DOCX/TXT → raw text → structured
   `ParsedResume` via Claude structured outputs (`claude-opus-4-8`, adaptive
   thinking). Regex fallback when no API key: contact + skills only, never
   invented work history. User reviews before the draft becomes the profile.
2. **Discover** — job-board APIs only (Adzuna, USAJobs, Greenhouse/Lever public
   boards). No scraping of sites that forbid it.
3. **Match** — pgvector cosine similarity for recall, Claude scoring with
   reasoning for precision. Both scores kept on the `matches` row.
4. **Tailor** — resume rewrite + cover letter grounded strictly in the verified
   profile; the model may rephrase real experience, never invent it.
5. **Prefill** — Playwright fills the ATS form, screenshots it, sets
   `ready_for_review`, stops.
6. **Track** — status board, reminders, event history.

## Data model

`users → profiles → {resumes, work_experience, education, skills}`
`job_postings ← matches → profiles`
`applications` (profile × posting) with `application_events` as its audit log.

Embeddings: `Vector(1024)` on `profiles.embedding` and
`job_postings.embedding` (dimension set in `backend/app/models/profile.py`).

## Local infrastructure

`infra/docker/docker-compose.yml`: Postgres 16 + pgvector (host port 5433),
Redis 7, MinIO (9000/9001) with an init job that creates the `resumes` bucket.
