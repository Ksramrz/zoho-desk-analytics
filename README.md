# Zoho Desk Agent Activity Analytics

Self-hosted analytics system for Zoho Desk using FastAPI + PostgreSQL + React, all run via Docker Compose.

## 1) Prerequisites

- Docker
- Docker Compose (`docker compose` command)

## 2) Zoho OAuth setup (step-by-step)

1. Open the Zoho API Console and create a **Server-based** client.
2. Save the generated:
   - `client_id`
   - `client_secret`
3. Generate a grant code with scopes:
   - `Desk.tickets.READ`
   - `Desk.contacts.READ`
   - `Desk.basic.READ`
4. Exchange the grant code for access + refresh token:
   - `POST https://accounts.zohocloud.ca/oauth/v2/token`
   - Include `grant_type=authorization_code`, `client_id`, `client_secret`, `code`, `redirect_uri`
5. Copy the **refresh token**.
6. In Zoho Desk, get your organization ID (`ZOHO_ORG_ID`).

## 3) Configure environment

1. Copy `.env.example` to `.env`:

   ```bash
   cp .env.example .env
   ```

2. Fill values:

   - `ZOHO_CLIENT_ID`
   - `ZOHO_CLIENT_SECRET`
   - `ZOHO_REFRESH_TOKEN`
   - `ZOHO_ORG_ID`
   - `DATABASE_URL` (default in example works with docker compose)

## 4) Run everything

**Own PC only (simplest):** see **`LOCAL_PC.md`** for Docker Desktop, sleep, and tips.

```bash
docker compose up --build
```

Or in the background: `docker compose up -d --build`

Services:

- Frontend dashboard: [http://localhost](http://localhost)
- Backend API docs: [http://localhost:8000/docs](http://localhost:8000/docs)

## Metabase (managers)

See **`METABASE.md`** — Pacific-time views per agent (TechProduct Team excluded), day/week/month tables, and comparison charts.

## 5) Manual backfill / sync trigger

- First run automatically backfills last 90 days if `sync_log` is empty.
- You can trigger sync manually at any time:

```bash
curl -X POST http://localhost:8000/api/sync/trigger
```

## 6) Scheduler behavior

- APScheduler runs inside backend every 30 minutes.
- Each run:
  - refreshes OAuth token
  - pulls modified tickets in time window
  - fetches ticket threads/comments/history
  - writes normalized agent actions to PostgreSQL
  - writes status row in `sync_log`

## API overview

- `GET /api/summary?date_from=...&date_to=...`
- `GET /api/timeline?date_from=...&date_to=...&granularity=day|week`
- `GET /api/actions?date_from=...&date_to=...&page=1&page_size=50&agent_id=&action_type=`
- `GET /api/agents`
- `GET /api/sync/status`
- `POST /api/sync/trigger`

## Optional AI draft + Telegram reminders

See **`docs/OPENCLAW_ZOHO_ASSISTANT.md`** for the optional assistant setup.
It adds `/api/assistant/*` endpoints for AI-generated draft replies, Telegram
follow-up reminders, and an OpenClaw skill/runbook for working from an open
Zoho Desk browser tab.
