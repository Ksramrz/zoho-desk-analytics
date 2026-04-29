# Telegram-first Zoho assistant workflow

This is the lower-friction path: keep the backend running once, then use Telegram commands. You do not need to run `curl` every time.

## What you do day to day

Message your bot:

```text
/draft 123456789
```

The bot will:

1. fetch the Zoho ticket by id
2. block if the assignee is not Kasra
3. draft a reply using `backend/knowledge/zoho_support.md`
4. send the draft back to Telegram

Create reminders from Telegram:

```text
/remind tomorrow 11 call customer about onboarding
/remind today 3:30pm follow up on Instagram connection
/remind 2026-04-30 11:00 call customer
```

Other commands:

```text
/status
/help
```

## One-time setup

1. Put secrets in `.env`:

```env
AI_API_KEY=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
TELEGRAM_BOT_POLLING_ENABLED=1
ASSISTANT_REQUIRE_ALLOWED_ASSIGNEE=1
ASSISTANT_ALLOWED_ASSIGNEE_NAMES=Kasra
```

2. Keep the backend running on a server or your computer.

With Docker:

```bash
docker compose up -d --build
```

Without Docker, use the systemd setup in `docs/NO_DOCKER_ALWAYS_ON.md`.

After that, use Telegram. You do not need manual API commands for normal drafts/reminders.

## Best always-on options

- Existing Oracle Cloud box from this repo's deployment docs
- A small VPS
- Your work computer if it stays awake

For a demo, your computer is enough. For daily use, a small always-on server is better.

## Where OpenClaw fits now

OpenClaw is optional for the Telegram-first flow.

Use OpenClaw when you want browser magic, like:

- read the currently open Zoho ticket without copying ticket id
- summarize the visible browser ticket
- paste a draft into Zoho's reply box and stop before Send

Use Telegram when you want speed:

- `/draft <ticket_id>`
- `/remind <time> <message>`
