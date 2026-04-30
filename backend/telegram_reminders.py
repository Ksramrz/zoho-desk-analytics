import os
from typing import Any

import requests

from db import query_due_telegram_reminders, update_telegram_reminder_status


def _config(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def telegram_configured() -> bool:
    return bool(_config("TELEGRAM_BOT_TOKEN") and _config("TELEGRAM_CHAT_ID"))


def send_telegram_message(text: str) -> dict[str, Any]:
    token = _config("TELEGRAM_BOT_TOKEN")
    chat_id = _config("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set")

    resp = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def send_due_telegram_reminders(limit: int = 25) -> dict[str, Any]:
    if not telegram_configured():
        return {"configured": False, "sent": 0, "failed": 0, "message": "Telegram env vars are not set"}

    sent = 0
    failed = 0
    reminders = query_due_telegram_reminders(limit=limit)
    for reminder in reminders:
        text = reminder["message"]
        if reminder.get("ticket_id"):
            text = f"{text}\n\nZoho ticket: {reminder['ticket_id']}"
        try:
            send_telegram_message(text)
            update_telegram_reminder_status(reminder["id"], "sent")
            sent += 1
        except Exception as exc:
            update_telegram_reminder_status(reminder["id"], "failed", str(exc)[:1000])
            failed += 1
    return {"configured": True, "sent": sent, "failed": failed, "checked": len(reminders)}
