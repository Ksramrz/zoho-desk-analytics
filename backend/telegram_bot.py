import datetime as dt
import json
import os
import re
from typing import Any
from zoneinfo import ZoneInfo

import requests

from assistant_service import generate_draft
from db import get_app_state, insert_telegram_reminder, set_app_state
from telegram_reminders import send_telegram_message, telegram_configured


HELP_TEXT = """Zoho assistant commands:

/draft <ticket_id>
Draft a reply for a Zoho ticket assigned to Kasra.

/remind <when> <what>
Example: /remind tomorrow 11 call customer about onboarding
Example: /remind 2026-04-30 11:00 call customer

/status
Check bot/backend configuration.

/help
Show this message."""


def _config(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _bot_token() -> str:
    return _config("TELEGRAM_BOT_TOKEN")


def _allowed_chat_id() -> str:
    return _config("TELEGRAM_CHAT_ID")


def _api_url(method: str) -> str:
    return f"https://api.telegram.org/bot{_bot_token()}/{method}"


def _bot_enabled() -> bool:
    return _config("TELEGRAM_BOT_POLLING_ENABLED", "1").lower() not in {"0", "false", "no", "off"}


def _timezone() -> ZoneInfo:
    name = _config("ASSISTANT_REMINDER_TIMEZONE", "America/Vancouver")
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo("America/Vancouver")


def _parse_reminder_text(raw: str) -> tuple[str, str]:
    text = raw.strip()
    if not text:
        raise ValueError("Use /remind <when> <what>. Example: /remind tomorrow 11 call customer")

    tz = _timezone()
    now = dt.datetime.now(tz)
    lowered = text.lower()

    date_value = now.date()
    rest = text
    if lowered.startswith("tomorrow "):
        date_value = now.date() + dt.timedelta(days=1)
        rest = text.split(" ", 1)[1].strip()
    elif lowered.startswith("today "):
        rest = text.split(" ", 1)[1].strip()
    else:
        match = re.match(r"^(\d{4}-\d{2}-\d{2})\s+(.+)$", text)
        if match:
            date_value = dt.date.fromisoformat(match.group(1))
            rest = match.group(2).strip()

    match = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b\s*(.*)$", rest, flags=re.I)
    if not match:
        raise ValueError("Could not find a time. Example: /remind tomorrow 11 call customer")

    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    ampm = (match.group(3) or "").lower()
    message = match.group(4).strip()
    if ampm == "pm" and hour < 12:
        hour += 12
    if ampm == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        raise ValueError("Invalid reminder time.")
    if not message:
        raise ValueError("Add what you want to be reminded about after the time.")

    remind_at = dt.datetime.combine(date_value, dt.time(hour, minute), tzinfo=tz)
    if remind_at < now and not lowered.startswith(("today ", "tomorrow ")):
        remind_at = remind_at + dt.timedelta(days=1)
    return remind_at.isoformat(), message


def _send_to_chat(chat_id: str, text: str) -> None:
    token = _bot_token()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")
    resp = requests.post(
        _api_url("sendMessage"),
        json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
        timeout=30,
    )
    resp.raise_for_status()


def _handle_draft(chat_id: str, text: str) -> None:
    ticket_id = text.strip()
    if not ticket_id:
        _send_to_chat(chat_id, "Use /draft <zoho_ticket_id>")
        return
    _send_to_chat(chat_id, f"Working on draft for ticket {ticket_id}. I will only draft if it is assigned to Kasra.")
    try:
        result = generate_draft(ticket_id=ticket_id, agent_name="Kasra")
    except Exception as exc:
        _send_to_chat(chat_id, f"Could not create draft: {exc}")
        return
    _send_to_chat(chat_id, "Draft reply:\n\n" + result["draft"])


def _handle_remind(chat_id: str, text: str) -> None:
    try:
        remind_at, message = _parse_reminder_text(text)
        row = insert_telegram_reminder(ticket_id=None, message=message, remind_at=remind_at)
    except Exception as exc:
        _send_to_chat(chat_id, f"Could not create reminder: {exc}")
        return
    _send_to_chat(chat_id, f"Reminder saved for {row['remind_at']}:\n{row['message']}")


def _handle_status(chat_id: str) -> None:
    status = {
        "telegram_configured": telegram_configured(),
        "bot_polling_enabled": _bot_enabled(),
        "allowed_chat_id_set": bool(_allowed_chat_id()),
        "ai_configured": bool(_config("AI_API_KEY") or _config("OPENAI_API_KEY")),
        "kasra_only": _config("ASSISTANT_REQUIRE_ALLOWED_ASSIGNEE", "1"),
    }
    _send_to_chat(chat_id, json.dumps(status, indent=2))


def _handle_message(message: dict[str, Any]) -> None:
    chat = message.get("chat") or {}
    chat_id = str(chat.get("id", ""))
    allowed = _allowed_chat_id()
    if allowed and chat_id != allowed:
        if chat_id:
            _send_to_chat(chat_id, "This bot is restricted to the configured support chat.")
        return

    text = str(message.get("text") or "").strip()
    if not text:
        return
    command, _, rest = text.partition(" ")
    command = command.split("@", 1)[0].lower()

    if command in {"/help", "/start"}:
        _send_to_chat(chat_id, HELP_TEXT)
    elif command == "/draft":
        _handle_draft(chat_id, rest)
    elif command == "/remind":
        _handle_remind(chat_id, rest)
    elif command == "/status":
        _handle_status(chat_id)
    else:
        _send_to_chat(chat_id, "Unknown command. Send /help.")


def poll_telegram_bot_once(limit: int = 20) -> dict[str, Any]:
    if not telegram_configured() or not _bot_enabled():
        return {"configured": telegram_configured(), "enabled": _bot_enabled(), "processed": 0}

    offset_raw = get_app_state("telegram_bot_update_offset", "0") or "0"
    try:
        offset = int(offset_raw)
    except ValueError:
        offset = 0

    resp = requests.get(
        _api_url("getUpdates"),
        params={"offset": offset, "limit": limit, "timeout": 1, "allowed_updates": json.dumps(["message"])},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    processed = 0
    max_update_id = offset - 1
    for update in data.get("result", []):
        update_id = int(update.get("update_id", 0))
        max_update_id = max(max_update_id, update_id)
        message = update.get("message")
        if isinstance(message, dict):
            try:
                _handle_message(message)
            except Exception as exc:
                chat = message.get("chat") or {}
                chat_id = str(chat.get("id", ""))
                if chat_id:
                    _send_to_chat(chat_id, f"Bot error: {exc}")
            processed += 1
    if max_update_id >= offset:
        set_app_state("telegram_bot_update_offset", str(max_update_id + 1))
    return {"configured": True, "enabled": True, "processed": processed}
