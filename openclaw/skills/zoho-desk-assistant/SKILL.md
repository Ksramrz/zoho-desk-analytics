---
name: zoho-desk-assistant
description: Draft Zoho Desk ticket replies from the current browser ticket and create Telegram follow-up reminders through the local Desk Analytics backend.
---

# Zoho Desk Assistant

Use this skill when the user is looking at a Zoho Desk ticket in the browser and asks for a draft reply or a follow-up reminder.

## Safety rules

- Never send a Zoho Desk reply automatically.
- Only prepare draft text and ask the human to review/paste/send it.
- Do not click Send, Submit, Reply, or similar final-action buttons in Zoho.
- If the browser cannot read the ticket clearly, ask the user to open the ticket and try again.

## Backend

The local backend is expected at `http://localhost:8000` unless the user provides another URL.

Useful endpoints:

- `GET /api/assistant/status`
- `POST /api/assistant/drafts`
- `POST /api/assistant/reminders`
- `POST /api/assistant/reminders/extract`
- `GET /api/assistant/reminders`

## Draft workflow from an open Zoho Desk browser tab

1. Use the browser tool with the `user` profile when the user wants to reuse their signed-in Zoho session.
2. Read the active Zoho Desk ticket page. Capture:
   - ticket id or number, if visible
   - subject
   - latest customer message
   - recent conversation context
   - customer name, if visible
3. Call the backend draft endpoint with browser-captured context:

```bash
curl -s http://localhost:8000/api/assistant/drafts   -H 'Content-Type: application/json'   -d '{
    "ticket_context": {
      "ticket": {"number": "VISIBLE_TICKET_NUMBER", "subject": "VISIBLE_SUBJECT"},
      "messages": [
        {"kind": "browser", "direction": "customer", "text": "LATEST_CUSTOMER_MESSAGE"}
      ]
    },
    "customer_message": "LATEST_CUSTOMER_MESSAGE",
    "agent_name": "Kasra"
  }'
```

4. Return the draft to the user clearly marked as a draft.
5. If the user wants it inserted into Zoho, paste it into the reply editor only. Stop before sending.

## Draft workflow by ticket id

If the user gives a Zoho ticket id and the backend has Zoho OAuth configured, call:

```bash
curl -s http://localhost:8000/api/assistant/drafts   -H 'Content-Type: application/json'   -d '{"ticket_id":"ZOHO_TICKET_ID","agent_name":"Kasra"}'
```

## Reminder workflow

If the conversation includes a meeting request or promised call time, create a reminder:

```bash
curl -s http://localhost:8000/api/assistant/reminders   -H 'Content-Type: application/json'   -d '{
    "message": "Call customer about ticket 12345 at 11:00 AM.",
    "remind_at": "2026-04-30T11:00:00-07:00",
    "ticket_id": "12345"
  }'
```

For natural-language extraction from a copied conversation:

```bash
curl -s http://localhost:8000/api/assistant/reminders/extract   -H 'Content-Type: application/json'   -d '{"text":"CUSTOMER_CONVERSATION_TEXT","timezone":"America/Vancouver"}'
```

The backend scheduler sends pending Telegram reminders when they become due.
