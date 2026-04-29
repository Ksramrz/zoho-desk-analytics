import datetime as dt
import json
import os
import re
from html import unescape
from pathlib import Path
from typing import Any

import requests

from zoho_client import ZohoDeskClient


DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_SYSTEM_PROMPT = """You are a roomvu Zoho Desk support assistant.
Write helpful draft replies for support agents. Use only the provided ticket
context and knowledge base. If the answer is not supported by the context,
say what needs to be checked instead of inventing facts.

Style:
- friendly, concise, and professional
- clear next steps
- no markdown tables
- do not claim that anything was already done unless the ticket context says so
- never send the message yourself; this is a draft for a human agent to review
"""


def _config(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _knowledge_path() -> Path:
    raw = _config("ASSISTANT_KNOWLEDGE_PATH", "knowledge/zoho_support.md")
    return Path(raw)


def load_knowledge_base() -> str:
    path = _knowledge_path()
    if not path.is_absolute():
        path = Path(__file__).resolve().parent / path
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")[: int(_config("ASSISTANT_KNOWLEDGE_MAX_CHARS", "24000") or "24000")]


def _strip_html(value: Any) -> str:
    text = "" if value is None else str(value)
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
    text = re.sub(r"(?s)<br\s*/?>", "\n", text)
    text = re.sub(r"(?s)</p\s*>", "\n", text)
    text = re.sub(r"(?s)<.*?>", " ", text)
    text = unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s+", "\n", text)
    return text.strip()


def _first_text(row: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = row.get(key)
        if value:
            return _strip_html(value)
    return ""


def build_ticket_context(ticket_id: str) -> dict[str, Any]:
    client = ZohoDeskClient()
    ticket = client.get_ticket(ticket_id)
    threads, comments, _history = client.fetch_ticket_activity(ticket_id)

    messages: list[dict[str, Any]] = []
    for row in threads:
        messages.append(
            {
                "kind": "thread",
                "created_time": row.get("createdTime") or row.get("modifiedTime"),
                "direction": row.get("direction") or row.get("channel"),
                "from": row.get("fromEmailAddress") or row.get("author") or row.get("createdBy"),
                "text": _first_text(row, ("summary", "content", "plainText", "description")),
            }
        )
    for row in comments:
        messages.append(
            {
                "kind": "comment",
                "created_time": row.get("createdTime") or row.get("modifiedTime"),
                "direction": "internal" if row.get("isPublic") is False else "public",
                "from": row.get("commenter") or row.get("createdBy"),
                "text": _first_text(row, ("content", "plainText", "summary")),
            }
        )

    messages = [m for m in messages if m["text"]]
    messages.sort(key=lambda m: str(m.get("created_time") or ""))
    max_messages = int(_config("ASSISTANT_MAX_TICKET_MESSAGES", "12") or "12")

    return {
        "ticket": {
            "id": ticket.get("id") or ticket_id,
            "number": ticket.get("ticketNumber"),
            "subject": ticket.get("subject"),
            "status": ticket.get("status"),
            "priority": ticket.get("priority"),
            "description": _strip_html(ticket.get("description")),
        },
        "messages": messages[-max_messages:],
    }


def _chat_completion(messages: list[dict[str, str]], temperature: float = 0.2) -> str:
    api_key = _config("AI_API_KEY") or _config("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("AI_API_KEY or OPENAI_API_KEY is not set")

    base_url = _config("AI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = _config("AI_MODEL", DEFAULT_MODEL)
    resp = requests.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": model, "messages": messages, "temperature": temperature},
        timeout=90,
    )
    resp.raise_for_status()
    data = resp.json()
    try:
        return str(data["choices"][0]["message"]["content"]).strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Unexpected AI response shape: {data}") from exc


def generate_draft(
    *,
    ticket_id: str | None = None,
    customer_message: str | None = None,
    ticket_context: dict[str, Any] | None = None,
    agent_name: str | None = None,
    tone: str = "friendly and concise",
) -> dict[str, Any]:
    context = ticket_context or {}
    if ticket_id and not context:
        context = build_ticket_context(ticket_id)

    if not context and not customer_message:
        raise ValueError("Provide ticket_id, ticket_context, or customer_message")

    knowledge = load_knowledge_base()
    prompt = {
        "customer_message": customer_message,
        "ticket_context": context,
        "agent_name": agent_name,
        "tone": tone,
        "knowledge_base": knowledge,
    }
    content = _chat_completion(
        [
            {"role": "system", "content": DEFAULT_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": "Draft a Zoho Desk reply using this JSON context:\n"
                + json.dumps(prompt, ensure_ascii=False, indent=2),
            },
        ]
    )
    return {
        "draft": content,
        "ticket_context": context,
        "used_knowledge_base": bool(knowledge),
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


def extract_reminders(text: str, *, now_iso: str | None = None, timezone: str | None = None) -> list[dict[str, str]]:
    if not text.strip():
        return []

    now = now_iso or dt.datetime.now(dt.timezone.utc).isoformat()
    tz = timezone or _config("ASSISTANT_REMINDER_TIMEZONE", "America/Vancouver")
    knowledge = load_knowledge_base()
    prompt = f"""Current time: {now}
Default timezone: {tz}

Extract only real follow-up reminders from this support conversation.
Examples: a promised call, a customer asking for a meeting, an agreed demo time,
or a follow-up the agent committed to do.

Return strict JSON only:
{{"reminders":[{{"remind_at":"ISO-8601 datetime with timezone","message":"short Telegram reminder","ticket_id":"optional"}}]}}

If there is no reminder, return {{"reminders":[]}}.

Knowledge base context, if helpful:
{knowledge[:4000]}

Conversation:
{text}
"""
    raw = _chat_completion(
        [
            {"role": "system", "content": "You extract support reminders and return valid JSON only."},
            {"role": "user", "content": prompt},
        ],
        temperature=0,
    )
    data = json.loads(raw)
    reminders = data.get("reminders", [])
    if not isinstance(reminders, list):
        return []
    out: list[dict[str, str]] = []
    for item in reminders:
        if not isinstance(item, dict):
            continue
        remind_at = str(item.get("remind_at", "")).strip()
        message = str(item.get("message", "")).strip()
        if remind_at and message:
            out.append(
                {
                    "remind_at": remind_at,
                    "message": message,
                    "ticket_id": str(item.get("ticket_id", "")).strip(),
                }
            )
    return out
