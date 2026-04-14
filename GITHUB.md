# GitHub vs Oracle (or any VPS)

## What GitHub is good for here

| Use | Works? |
|-----|--------|
| **Store your code** (private repo) | **Yes** — recommended. |
| **Deploy to a server** (SSH to Oracle/VPS, `docker compose pull && up`) | **Yes** — use **GitHub Actions** on push or schedule. |
| **Replace a 24/7 VM** for Postgres + Metabase + backend + web UI | **No** — GitHub does not run your Docker stack as a always-on server. |

## Why not “GitHub only” for this stack?

This project expects **long-running** services:

- **Postgres** (data)
- **Backend** (API + scheduled Zoho sync)
- **Metabase** (dashboards)
- **Frontend** (optional nginx)

**GitHub Actions** runs **short jobs** (minutes) on **temporary** runners. When the job ends, everything is gone. You cannot leave Metabase and Postgres “up” on GitHub the way you do on Oracle or any VPS.

So: **GitHub complements a server; it does not replace one** for this architecture.

## What you can do with GitHub Actions (optional)

1. **CI only** — run tests / lint on every push (if you add tests).
2. **Deploy** — on merge to `main`, SSH into your **Oracle/VPS** and run `git pull && docker compose up -d --build`.
3. **Sync-only job** (would require **redesign**): a scheduled Action runs `run_sync` against a **hosted** database (e.g. Neon, Supabase Postgres). You would **not** run Metabase inside Actions; you’d use Metabase Cloud, hosted Metabase elsewhere, or skip Metabase and use something else.

Option 3 is a **different** deployment model (external DB + no containerized Metabase on GitHub).

## Practical recommendation

- **Code:** **GitHub** (or GitLab, etc.).
- **24/7 runtime:** **Oracle Always Free**, another **VPS**, or a **home PC** with Docker — same as today.
- **Optional:** add a **deploy workflow** so pushing to `main` updates the server without manual SSH.

If you want, we can add a minimal **`.github/workflows/deploy.yml`** example that only deploys when *you* already have a server — it does not host the stack by itself.
