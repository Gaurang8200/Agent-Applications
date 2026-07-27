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


## Running it for real (free)

The agent runs on your own machine and is reached through a Cloudflare Quick
Tunnel. Nothing here costs money, and the only tradeoff is that the agent is
reachable while the machine is awake.

```sh
./deployment/start-agent.sh
```

That brings up Postgres, Redis, and MinIO, applies migrations, starts the API
and the web app, and opens a tunnel to each. It prints two URLs; the web one is
what you open, and what you put behind the button on the portfolio site
(`VITE_AGENT_APP_URL` in that project).

Two things worth understanding:

**The hostnames change every run.** A Quick Tunnel mints a throwaway
`*.trycloudflare.com` name each time. For a stable address you need a named
tunnel, which requires a domain on Cloudflare — the same domain that serves the
portfolio site would do.

**A tunnel URL is public.** Anyone holding the link reaches the app, so access
control is what keeps it yours: `ALLOWED_EMAILS` in `.env` must list your
address before you share the link. Registration and sign-in both refuse
everything else.

The autonomous loop is off by default because it spends API budget. Turn it on
with `AUTOPILOT_ENABLED=true`; it will discover, score, and prepare documents
on an interval, and stop at `ready_for_review` every time.

## Why not serverless

The API needs LibreOffice to render the tailored `.docx` into PDF, and the
autonomous loop needs a process that stays alive between requests. Neither fits
a serverless platform's size limits or execution model, which is why the
frontend can live on Vercel but the backend cannot.
