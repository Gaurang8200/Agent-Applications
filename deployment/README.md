# Deployment

Target architecture (not yet live):

| Component | Where | Notes |
|---|---|---|
| `frontend/` | Vercel | Next.js 16; set `NEXT_PUBLIC_API_URL` to the API's public URL |
| `backend/`  | Railway or Fly.io | Container built from `backend/Dockerfile` |
| Postgres    | Managed (Neon / Railway) | Needs the `vector` extension |
| Redis       | Managed (Upstash / Railway) | Job queue |
| Object storage | S3 or Cloudflare R2 | Replaces local MinIO; same S3 env vars |

## Environment

All configuration is env-var driven — see `.env.example` at the repo root.
Production requirements:

- `JWT_SECRET`: generate fresh (`openssl rand -hex 32`), never reuse dev values
- `ENVIRONMENT=production`
- `CORS_ORIGINS`: the frontend's exact origin, no wildcards
- `DATABASE_URL`: must use the `postgresql+psycopg://` driver prefix

## Build images locally

```sh
docker build -t agentapp-api backend/
docker build -t agentapp-web frontend/
```

CI/CD (GitHub Actions) to be added once the first deploy target is chosen.

## Running it (local, indefinitely)

The agent runs on this machine. Nothing is exposed publicly and no hosting is
involved, so there is nothing to pay for and no tunnel to maintain.

```sh
./deployment/run-local.sh
```

That brings up Postgres, Redis, and MinIO, applies migrations, and starts the
API and web app. Open <http://localhost:3000>.

With `AUTOPILOT_ENABLED=true` the API runs the pipeline on its own interval:
discover new German postings, score them, and prepare tailored documents for
the best matches. Every application stops at `ready_for_review`; submitting is
a human action, always.

Documents land in `~/AgentApplications/<Company>/` as both `.docx` and `.pdf`.

### Keeping it alive around the clock

The loop only runs while the machine is awake, so stop it sleeping:

```sh
caffeinate -dimsu
```

Leave that running in its own terminal. Closing the lid still suspends the
machine unless it is on power with an external display, so keep the lid open
for an unattended overnight run.

### Tuning the loop

| Setting | Effect |
|---|---|
| `AUTOPILOT_INTERVAL_MINUTES` | How often a cycle runs. 180 is a reasonable default; postings do not appear faster than that. |
| `AUTOPILOT_MIN_SCORE` | Minimum judged fit before documents are prepared. Lower it for more applications, raise it for better ones. |
| `AUTOPILOT_PREPARE_LIMIT` | Applications prepared per cycle. Each one costs a tailoring call, so this is the main cost control. |
| `AUTOPILOT_SCORE_LIMIT` | Postings scored per cycle. |

`GET /api/v1/autopilot/status` reports what recent cycles did, including
failures. `POST /api/v1/autopilot/run` triggers one immediately.

## Why not serverless

The API needs LibreOffice to render the tailored `.docx` into PDF, and the loop
needs a process that stays alive between requests. Neither fits a serverless
platform's size limits or execution model. If this is ever hosted, it needs a
container host rather than a functions platform.
