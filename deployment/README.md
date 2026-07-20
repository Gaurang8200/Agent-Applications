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
