import os
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, Field

from assistant_service import allowed_assignee_names, extract_reminders, generate_draft, load_knowledge_base
from db import insert_ai_draft, insert_telegram_reminder, query_telegram_reminders
from telegram_reminders import send_due_telegram_reminders, telegram_configured


router = APIRouter(prefix="/api/assistant", tags=["assistant"])


class DraftRequest(BaseModel):
    ticket_id: str | None = None
    customer_message: str | None = None
    ticket_context: dict[str, Any] | None = None
    agent_name: str | None = None
    tone: str = "friendly and concise"


class ReminderRequest(BaseModel):
    message: str = Field(..., min_length=1)
    remind_at: str = Field(..., description="ISO-8601 datetime, e.g. 2026-04-29T11:00:00-07:00")
    ticket_id: str | None = None


class ReminderExtractRequest(BaseModel):
    text: str = Field(..., min_length=1)
    ticket_id: str | None = None
    now_iso: str | None = None
    timezone: str | None = None


def _ai_configured() -> bool:
    return bool(os.getenv("AI_API_KEY", "").strip() or os.getenv("OPENAI_API_KEY", "").strip())


@router.get("/status")
def get_assistant_status():
    return {
        "ai_configured": _ai_configured(),
        "telegram_configured": telegram_configured(),
        "knowledge_base_loaded": bool(load_knowledge_base()),
        "knowledge_path": os.getenv("ASSISTANT_KNOWLEDGE_PATH", "knowledge/zoho_support.md"),
        "require_allowed_assignee": os.getenv("ASSISTANT_REQUIRE_ALLOWED_ASSIGNEE", "1").strip().lower()
        not in {"0", "false", "no", "off"},
        "allowed_assignee_names": allowed_assignee_names(),
    }


@router.post("/drafts")
def create_draft(payload: DraftRequest):
    try:
        result = generate_draft(
            ticket_id=payload.ticket_id,
            customer_message=payload.customer_message,
            ticket_context=payload.ticket_context,
            agent_name=payload.agent_name,
            tone=payload.tone,
        )
        row = insert_ai_draft(
            ticket_id=payload.ticket_id,
            customer_message=payload.customer_message,
            ticket_context=result.get("ticket_context"),
            draft=result["draft"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {**result, "stored_draft": row}


@router.post("/reminders")
def create_reminder(payload: ReminderRequest):
    try:
        return {"reminder": insert_telegram_reminder(ticket_id=payload.ticket_id, message=payload.message, remind_at=payload.remind_at)}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/reminders/extract")
def extract_and_create_reminders(payload: ReminderExtractRequest):
    try:
        extracted = extract_reminders(payload.text, now_iso=payload.now_iso, timezone=payload.timezone)
        rows = []
        for reminder in extracted:
            ticket_id = reminder.get("ticket_id") or payload.ticket_id
            rows.append(
                insert_telegram_reminder(
                    ticket_id=ticket_id or None,
                    message=reminder["message"],
                    remind_at=reminder["remind_at"],
                )
            )
        return {"extracted": extracted, "created": rows}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/reminders")
def list_reminders(limit: int = Query(50, ge=1, le=200)):
    return {"reminders": query_telegram_reminders(limit=limit)}


@router.post("/reminders/send-due")
def send_due_reminders(background_tasks: BackgroundTasks):
    background_tasks.add_task(send_due_telegram_reminders)
    return {"message": "Due reminder send job submitted"}
