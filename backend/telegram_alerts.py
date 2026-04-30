"""
Telegram alerts for tickets assigned to a single agent (default: Kasra).

What it does:
- Polls Zoho Desk for open tickets where assigneeId = TELEGRAM_AGENT_ID
- Classifies each ticket: critical, stale, due-callback, new-assignment
- Parses recent customer messages for callback promises like
  "call me at 3pm" / "talk tomorrow at 10:30" / "in 30 minutes"
- Sends a clean, deduplicated Telegram message to every subscribed chat
- Handles /start, /today, /critical, /promises, /stop via getUpdates polling

All state is in Postgres (telegram_subscribers, alerts_sent, callback_promises).
The bot does not block analytics sync; failures are logged and skipped.
"""
from __future__ import annotations

import datetime as dt
import html
import os
import re
import threading
from typing import Any
from zoneinfo import ZoneInfo

import requests

from db import (
    add_callback_promise,
    add_telegram_subscriber,
    due_callback_promises,
    list_telegram_subscribers,
    mark_alert_sent,
    mark_callback_sent,
    record_telegram_update_offset,
    remove_telegram_subscriber,
    seen_alert_recently,
    telegram_update_offset,
)
from zoho_client import ZohoDeskClient


# ---------- Config ----------

DEFAULT_AGENT_ID = "7296000000961828"  # Kas M (Kasra)
DEFAULT_AGENT_NAME = "Kas M"
DEFAULT_TZ = "America/Los_Angeles"

# Priority strings Zoho uses; "High" and "Urgent" trigger immediate alerts.
CRITICAL_PRIORITIES = {"high", "urgent", "critical"}

# Stale = open >= this many hours since last customer activity.
STALE_HOURS = int(os.getenv("TELEGRAM_STALE_HOURS", "8"))

# Suppress duplicate alerts for the same (type, ticket) within this window.
ALERT_DEDUP_HOURS = int(os.getenv("TELEGRAM_ALERT_DEDUP_HOURS", "12"))


def agent_id() -> str:
    return os.getenv("TELEGRAM_AGENT_ID", DEFAULT_AGENT_ID).strip() or DEFAULT_AGENT_ID


def agent_name() -> str:
    return os.getenv("TELEGRAM_AGENT_NAME", DEFAULT_AGENT_NAME).strip() or DEFAULT_AGENT_NAME


def tz() -> ZoneInfo:
    name = os.getenv("TELEGRAM_TIMEZONE", DEFAULT_TZ).strip() or DEFAULT_TZ
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo(DEFAULT_TZ)


def bot_token() -> str:
    return os.getenv("TELEGRAM_BOT_TOKEN", "").strip()


def is_enabled() -> bool:
    return bool(bot_token())


# ---------- Telegram HTTP client ----------


class TGClient:
    """Minimal Telegram Bot API client (sendMessage + getUpdates)."""

    def __init__(self, token: str | None = None) -> None:
        self.token = (token or bot_token()).strip()
        self.base = f"https://api.telegram.org/bot{self.token}"
        self._lock = threading.Lock()

    def _post(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.token:
            return {"ok": False, "error": "no_token"}
        r = requests.post(f"{self.base}/{method}", json=payload, timeout=20)
        try:
            return r.json()
        except ValueError:
            return {"ok": False, "error": f"bad_json status={r.status_code}"}

    def send_message(self, chat_id: int | str, text: str, *, disable_preview: bool = True) -> dict[str, Any]:
        return self._post(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": disable_preview,
            },
        )

    def get_updates(self, offset: int | None = None, timeout: int = 0) -> list[dict[str, Any]]:
        payload = {"timeout": timeout, "allowed_updates": ["message"]}
        if offset:
            payload["offset"] = offset
        data = self._post("getUpdates", payload)
        if not data.get("ok"):
            return []
        return data.get("result", [])

    def get_me(self) -> dict[str, Any]:
        return self._post("getMe", {})


# ---------- Time / formatting helpers ----------


def _parse_iso(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(dt.timezone.utc)
    except Exception:
        return None


def _ago(value: dt.datetime | None) -> str:
    if not value:
        return "?"
    now = dt.datetime.now(dt.timezone.utc)
    delta = now - value
    secs = int(delta.total_seconds())
    if secs < 60:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


def _local(value: dt.datetime | None) -> str:
    if not value:
        return "?"
    return value.astimezone(tz()).strftime("%a %b %d, %I:%M %p %Z")


def _ticket_link(ticket: dict[str, Any]) -> str:
    tid = ticket.get("id", "")
    portal = os.getenv("ZOHO_PORTAL_URL", "https://desk.zoho.com").rstrip("/")
    return f"{portal}/agent/roomvu/customer-support/tickets/details/{tid}"


def _esc(value: Any) -> str:
    return html.escape(str(value or ""))


# ---------- Callback promise parsing ----------

# Captures relative ("in 30 minutes", "in 2 hours") and absolute ("at 3pm",
# "at 14:30", "tomorrow at 10am") promises in the latest inbound message.
_REL_PATTERN = re.compile(
    r"\b(?:call|callback|ring|talk|reach\s*out|get\s*back)\b[^.!?\n]{0,40}?\bin\s+(\d{1,3})\s*(minutes?|mins?|hours?|hrs?|h|m)\b",
    re.IGNORECASE,
)
_ABS_PATTERN = re.compile(
    r"\b(?:call|callback|ring|talk|reach\s*out|get\s*back)\b[^.!?\n]{0,60}?"
    r"(?:\b(today|tomorrow|tonight|tmrw)\b[^.!?\n]{0,10})?"
    r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b",
    re.IGNORECASE,
)


def parse_callback_promise(text: str, *, now: dt.datetime | None = None) -> dt.datetime | None:
    """
    Heuristic: find a future call-time promise inside `text` (latest inbound).
    Returns a UTC datetime in the future, or None.
    """
    if not text:
        return None
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(tz())
    sample = text[:1500]

    rel = _REL_PATTERN.search(sample)
    if rel:
        n = int(rel.group(1))
        unit = rel.group(2).lower()
        delta = dt.timedelta(minutes=n if unit.startswith("m") else n * 60)
        candidate = now + delta
        if dt.timedelta(minutes=2) <= candidate - now <= dt.timedelta(days=1):
            return candidate.astimezone(dt.timezone.utc)

    abs_m = _ABS_PATTERN.search(sample)
    if abs_m:
        when_word = (abs_m.group(1) or "").lower()
        hour = int(abs_m.group(2))
        minute = int(abs_m.group(3) or 0)
        ampm = (abs_m.group(4) or "").lower()
        if ampm == "pm" and hour < 12:
            hour += 12
        if ampm == "am" and hour == 12:
            hour = 0
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            return None
        base_date = now.date()
        if when_word in ("tomorrow", "tmrw"):
            base_date = base_date + dt.timedelta(days=1)
        candidate_local = dt.datetime.combine(base_date, dt.time(hour, minute, 0), tz())
        # If only "at 3pm" with no day word and the time has already passed today,
        # assume they meant tomorrow rather than the past.
        if not when_word and candidate_local <= now + dt.timedelta(minutes=2):
            candidate_local = candidate_local + dt.timedelta(days=1)
        if candidate_local - now > dt.timedelta(days=2):
            return None
        return candidate_local.astimezone(dt.timezone.utc)

    return None


# ---------- Zoho fetch helpers ----------


def fetch_open_tickets_for_agent(client: ZohoDeskClient, assignee_id: str) -> list[dict[str, Any]]:
    """Open tickets assigned to a single agent. Uses /tickets/search (paged)."""
    out: list[dict[str, Any]] = []
    limit = 50
    for offset in range(0, 500, limit):
        params = {
            "limit": limit,
            "from": offset,
            "assigneeId": assignee_id,
            "statusType": "Open",
            "sortBy": "-modifiedTime",
        }
        try:
            data = client._request("GET", "/tickets/search", params=params)
        except Exception as exc:
            print(f"[telegram] search assignee failed offset={offset}: {exc}")
            break
        rows = data.get("data", []) if isinstance(data, dict) else data
        if not rows:
            break
        out.extend(rows)
        if len(rows) < limit:
            break
    return out


def latest_inbound_text(client: ZohoDeskClient, ticket_id: str) -> str:
    """Pull the most recent customer-direction thread/comment text for callback parsing."""
    try:
        threads = client.list_threads(ticket_id) or []
    except Exception:
        threads = []
    threads.sort(key=lambda t: str(t.get("createdTime") or t.get("lastModifiedTime") or ""), reverse=True)
    for th in threads[:5]:
        author = th.get("author") or {}
        if str(author.get("type", "")).upper() == "AGENT":
            continue
        for key in ("plainText", "summary", "content"):
            text = th.get(key)
            if text:
                # strip basic HTML
                return re.sub(r"<[^>]+>", " ", str(text))
    return ""


# ---------- Alert classification ----------


def _is_critical(ticket: dict[str, Any]) -> bool:
    pr = str(ticket.get("priority") or "").strip().lower()
    if pr in CRITICAL_PRIORITIES:
        return True
    sentiment = str(ticket.get("sentiment") or "").lower()
    if sentiment in ("negative", "angry"):
        return True
    return False


def _is_stale(ticket: dict[str, Any]) -> bool:
    last = _parse_iso(ticket.get("customerResponseTime") or ticket.get("modifiedTime"))
    if not last:
        return False
    age = dt.datetime.now(dt.timezone.utc) - last
    return age >= dt.timedelta(hours=STALE_HOURS)


def _format_ticket_block(ticket: dict[str, Any], reason: str) -> str:
    num = _esc(ticket.get("ticketNumber") or ticket.get("id"))
    subject = _esc((ticket.get("subject") or "(no subject)")[:120])
    priority = _esc(ticket.get("priority") or "—")
    status = _esc(ticket.get("status") or "—")
    last = _parse_iso(ticket.get("customerResponseTime") or ticket.get("modifiedTime"))
    link = _ticket_link(ticket)
    return (
        f"<b>#{num}</b> · {subject}\n"
        f"   <i>{reason}</i>\n"
        f"   priority {priority} · {status} · last activity {_esc(_ago(last))}\n"
        f"   <a href=\"{link}\">open in Desk</a>"
    )


# ---------- Sender ----------


def _send_to_subscribers(tg: TGClient, text: str) -> None:
    for chat_id in list_telegram_subscribers():
        try:
            r = tg.send_message(chat_id, text)
            if not r.get("ok"):
                # Drop subscribers Telegram says are blocked / chat-not-found.
                desc = (r.get("description") or "").lower()
                if "blocked" in desc or "chat not found" in desc:
                    remove_telegram_subscriber(chat_id)
        except Exception as exc:
            print(f"[telegram] send to {chat_id} failed: {exc}")


# ---------- Scan job (called by APScheduler) ----------


def scan_and_alert() -> dict[str, Any]:
    """Single sweep: classify Kasra's open tickets and fire alerts."""
    if not is_enabled():
        return {"enabled": False}
    subs = list_telegram_subscribers()
    if not subs:
        return {"enabled": True, "subscribers": 0}

    tg = TGClient()
    client = ZohoDeskClient()

    summary = {"critical": 0, "stale": 0, "callback_due": 0, "new_callback_promises": 0}

    # 1) Due callback promises (cheap, no Zoho calls)
    for promise in due_callback_promises():
        ticket_label = promise["ticket_number"] or promise["ticket_id"]
        text = (
            "<b>📞 Reminder:</b> you promised to call now\n"
            f"<b>#{_esc(ticket_label)}</b> · {_esc(promise['subject'][:120])}\n"
            f"   promised at {_esc(_local(promise['promised_at']))}"
        )
        _send_to_subscribers(tg, text)
        mark_callback_sent(promise["id"])
        summary["callback_due"] += 1

    # 2) Open tickets sweep
    try:
        tickets = fetch_open_tickets_for_agent(client, agent_id())
    except Exception as exc:
        print(f"[telegram] fetch tickets failed: {exc}")
        return {"enabled": True, "error": str(exc), **summary}

    critical_blocks: list[str] = []
    stale_blocks: list[str] = []

    for t in tickets:
        ticket_id = str(t.get("id", ""))
        if not ticket_id:
            continue

        if _is_critical(t):
            key = f"critical:{ticket_id}"
            if not seen_alert_recently(key, ALERT_DEDUP_HOURS):
                critical_blocks.append(_format_ticket_block(t, "Critical / high priority"))
                mark_alert_sent(key)
                summary["critical"] += 1

        elif _is_stale(t):
            key = f"stale:{ticket_id}"
            if not seen_alert_recently(key, ALERT_DEDUP_HOURS):
                stale_blocks.append(_format_ticket_block(t, f"No reply for {STALE_HOURS}+ hours"))
                mark_alert_sent(key)
                summary["stale"] += 1

        # Callback promise scan (only inspect first 30 tickets per run for cost)
        if summary["new_callback_promises"] + summary["critical"] + summary["stale"] < 30:
            try:
                text = latest_inbound_text(client, ticket_id)
            except Exception:
                text = ""
            promised = parse_callback_promise(text)
            if promised:
                added = add_callback_promise(
                    ticket_id=ticket_id,
                    ticket_number=str(t.get("ticketNumber", "")),
                    subject=str(t.get("subject", "")),
                    promised_at=promised,
                )
                if added:
                    summary["new_callback_promises"] += 1
                    block = (
                        "<b>🗓 New callback promise detected</b>\n"
                        f"<b>#{_esc(t.get('ticketNumber') or ticket_id)}</b> · {_esc((t.get('subject') or '')[:120])}\n"
                        f"   I'll remind you at <b>{_esc(_local(promised))}</b>"
                    )
                    _send_to_subscribers(tg, block)

    if critical_blocks:
        header = f"🔴 <b>{len(critical_blocks)} critical ticket(s) for {_esc(agent_name())}</b>"
        _send_to_subscribers(tg, header + "\n\n" + "\n\n".join(critical_blocks))
    if stale_blocks:
        header = f"⏰ <b>{len(stale_blocks)} ticket(s) waiting for you</b>"
        _send_to_subscribers(tg, header + "\n\n" + "\n\n".join(stale_blocks))

    return {"enabled": True, "subscribers": len(subs), "tickets_scanned": len(tickets), **summary}


# ---------- /commands handler (called by APScheduler) ----------


HELP_TEXT = (
    "<b>Roomvu Desk assistant</b>\n"
    "I watch tickets assigned to you and ping you when something needs attention.\n\n"
    "<b>Commands</b>\n"
    "/start — subscribe this chat\n"
    "/today — quick snapshot of your open tickets\n"
    "/critical — list everything urgent right now\n"
    "/promises — list outstanding callback promises\n"
    "/stop — unsubscribe"
)


def _cmd_today(tg: TGClient, chat_id: int) -> None:
    try:
        client = ZohoDeskClient()
        tickets = fetch_open_tickets_for_agent(client, agent_id())
    except Exception as exc:
        tg.send_message(chat_id, f"Couldn't reach Zoho right now: {_esc(exc)}")
        return
    total = len(tickets)
    crit = sum(1 for t in tickets if _is_critical(t))
    stale = sum(1 for t in tickets if _is_stale(t))
    fresh = total - stale
    sample = tickets[:5]
    lines = [
        f"<b>Today, {_esc(agent_name())}</b>",
        f"open: <b>{total}</b> · critical: <b>{crit}</b> · waiting &gt; {STALE_HOURS}h: <b>{stale}</b> · fresh: <b>{fresh}</b>",
        "",
    ]
    for t in sample:
        lines.append(_format_ticket_block(t, "open"))
    if total > len(sample):
        lines.append(f"\n…and {total - len(sample)} more.")
    tg.send_message(chat_id, "\n\n".join(lines))


def _cmd_critical(tg: TGClient, chat_id: int) -> None:
    try:
        client = ZohoDeskClient()
        tickets = [t for t in fetch_open_tickets_for_agent(client, agent_id()) if _is_critical(t)]
    except Exception as exc:
        tg.send_message(chat_id, f"Couldn't reach Zoho right now: {_esc(exc)}")
        return
    if not tickets:
        tg.send_message(chat_id, "✅ Nothing critical right now.")
        return
    blocks = [_format_ticket_block(t, "Critical / high priority") for t in tickets[:15]]
    header = f"🔴 <b>{len(tickets)} critical ticket(s)</b>"
    tg.send_message(chat_id, header + "\n\n" + "\n\n".join(blocks))


def _cmd_promises(tg: TGClient, chat_id: int) -> None:
    promises = due_callback_promises(window_minutes=24 * 60, include_future=True)
    if not promises:
        tg.send_message(chat_id, "No callback promises on the books.")
        return
    lines = ["<b>Upcoming callback promises</b>"]
    for p in promises:
        lines.append(
            f"• <b>#{_esc(p['ticket_number'] or p['ticket_id'])}</b> at "
            f"<b>{_esc(_local(p['promised_at']))}</b> — {_esc(p['subject'][:80])}"
        )
    tg.send_message(chat_id, "\n".join(lines))


def poll_telegram_updates() -> dict[str, Any]:
    """Drain new Telegram updates and respond to commands. Safe to call frequently."""
    if not is_enabled():
        return {"enabled": False}
    tg = TGClient()
    offset = telegram_update_offset() or 0
    next_offset = offset
    try:
        updates = tg.get_updates(offset=offset + 1 if offset else None, timeout=0)
    except Exception as exc:
        return {"enabled": True, "error": str(exc)}

    handled = 0
    for upd in updates:
        next_offset = max(next_offset, int(upd.get("update_id", 0)))
        msg = upd.get("message") or {}
        chat = msg.get("chat") or {}
        chat_id = chat.get("id")
        text = (msg.get("text") or "").strip()
        if not chat_id or not text:
            continue
        cmd = text.split()[0].lower().split("@")[0]
        if cmd == "/start":
            add_telegram_subscriber(
                chat_id=chat_id,
                username=str(chat.get("username") or ""),
                first_name=str(chat.get("first_name") or ""),
            )
            tg.send_message(
                chat_id,
                "✅ Subscribed. I'll ping you about urgent / stale tickets and "
                f"any callback promises I detect for <b>{_esc(agent_name())}</b>.\n\n" + HELP_TEXT,
            )
        elif cmd == "/stop":
            remove_telegram_subscriber(chat_id)
            tg.send_message(chat_id, "Unsubscribed. Send /start anytime to come back.")
        elif cmd == "/today":
            _cmd_today(tg, chat_id)
        elif cmd == "/critical":
            _cmd_critical(tg, chat_id)
        elif cmd == "/promises":
            _cmd_promises(tg, chat_id)
        elif cmd in ("/help", "/start@"):
            tg.send_message(chat_id, HELP_TEXT)
        else:
            tg.send_message(chat_id, HELP_TEXT)
        handled += 1

    if next_offset and next_offset != offset:
        record_telegram_update_offset(next_offset)

    return {"enabled": True, "handled": handled, "offset": next_offset}
