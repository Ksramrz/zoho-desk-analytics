# OpenClaw + Zoho Desk assistant setup

This repo now includes a backend assistant layer for:

- generating human-reviewed Zoho Desk draft replies
- storing reminders for promised calls or meeting requests
- sending due reminders to Telegram
- giving OpenClaw a skill/runbook for using your open Zoho Desk browser tab

The assistant does **not** auto-send customer replies. It creates drafts for a support agent to review.

## 1. Configure environment

Copy `.env.example` to `.env` and fill the existing Zoho values. Then add AI and Telegram values:

```bash
AI_API_KEY=your_openai_or_compatible_key
AI_MODEL=gpt-4o-mini
TELEGRAM_BOT_TOKEN=your_botfather_token
TELEGRAM_CHAT_ID=your_telegram_chat_id
ASSISTANT_REMINDER_TIMEZONE=America/Vancouver
```

The draft endpoint can work from browser-provided context with only `AI_API_KEY`. To fetch tickets directly by Zoho ticket id, your Zoho OAuth token must also be valid.

## 2. Put your documents/tutorials into the knowledge file

Edit:

```text
backend/knowledge/zoho_support.md
```

Paste approved support docs, FAQ answers, and tutorial links there. The AI draft endpoint uses this file as grounding context.

## 3. Start the backend

```bash
docker compose up --build
```

Check the assistant status:

```bash
curl http://localhost:8000/api/assistant/status
```

## 4. Telegram bot setup

1. In Telegram, message `@BotFather`.
2. Run `/newbot` and copy the bot token into `TELEGRAM_BOT_TOKEN`.
3. Send a message to your new bot.
4. Get your chat id by opening this URL in a browser, replacing the token:

```text
https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/getUpdates
```

5. Copy the numeric `chat.id` into `TELEGRAM_CHAT_ID`.
6. Restart the backend.

Due reminders are checked every `TELEGRAM_REMINDER_INTERVAL_MINUTES` minutes, default 5.

## 5. OpenClaw setup

Install/run OpenClaw using its own documentation, then enable browser access. The important browser config is:

```json5
{
  plugins: {
    allow: ["telegram", "browser"]
  },
  browser: {
    enabled: true,
    defaultProfile: "user"
  },
  tools: {
    profile: "coding",
    alsoAllow: ["browser"]
  }
}
```

Use the `user` browser profile when you want OpenClaw to read your already signed-in Zoho Desk browser session. You may need to approve Chrome/Chromium remote-debugging attach prompts.

## 6. Install the OpenClaw skill

Copy or symlink this repo folder into your OpenClaw skills location:

```text
openclaw/skills/zoho-desk-assistant
```

The skill tells OpenClaw to:

- read the currently open Zoho ticket from the browser
- call `POST /api/assistant/drafts` for a draft response
- call reminder endpoints when someone asks for a meeting or you promised a call
- stop before sending any customer reply

## 7. Manual API examples

Create a draft from copied text:

```bash
curl -s http://localhost:8000/api/assistant/drafts   -H 'Content-Type: application/json'   -d '{"customer_message":"Customer says they need help connecting Instagram.","agent_name":"Kasra"}'
```

Create a Telegram reminder:

```bash
curl -s http://localhost:8000/api/assistant/reminders   -H 'Content-Type: application/json'   -d '{"message":"Call customer at 11 about their onboarding question.","remind_at":"2026-04-30T11:00:00-07:00"}'
```

Extract reminders from conversation text:

```bash
curl -s http://localhost:8000/api/assistant/reminders/extract   -H 'Content-Type: application/json'   -d '{"text":"I promised the client I would call at 11 tomorrow.","timezone":"America/Vancouver"}'
```
