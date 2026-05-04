from fastapi import APIRouter, BackgroundTasks, HTTPException

from db import list_telegram_subscribers
from zoho_automation import zoho_automation_disabled
from telegram_alerts import (
    TGClient,
    agent_id,
    agent_name,
    is_enabled,
    poll_telegram_updates,
    scan_and_alert,
)


router = APIRouter(prefix="/api/telegram", tags=["telegram"])


@router.get("/status")
def telegram_status():
    info = {"enabled": is_enabled(), "agent_id": agent_id(), "agent_name": agent_name()}
    if is_enabled():
        try:
            me = TGClient().get_me()
            if me.get("ok"):
                r = me.get("result", {})
                info["bot_username"] = r.get("username")
                info["bot_id"] = r.get("id")
        except Exception as exc:
            info["bot_error"] = str(exc)
        info["subscribers"] = len(list_telegram_subscribers())
    return info


@router.post("/scan")
def trigger_scan(background_tasks: BackgroundTasks):
    if not is_enabled():
        raise HTTPException(status_code=400, detail="TELEGRAM_BOT_TOKEN not configured")
    if zoho_automation_disabled():
        raise HTTPException(
            status_code=503,
            detail="Zoho automation disabled (DISABLE_ZOHO_AUTOMATION=1). Scan not queued.",
        )
    background_tasks.add_task(scan_and_alert)
    return {"queued": True}


@router.post("/poll")
def trigger_poll(background_tasks: BackgroundTasks):
    if not is_enabled():
        raise HTTPException(status_code=400, detail="TELEGRAM_BOT_TOKEN not configured")
    background_tasks.add_task(poll_telegram_updates)
    return {"queued": True}


@router.post("/test")
def telegram_test(text: str = "Roomvu Desk bot — test ping. If you see this, the wiring works."):
    if not is_enabled():
        raise HTTPException(status_code=400, detail="TELEGRAM_BOT_TOKEN not configured")
    tg = TGClient()
    sent = 0
    for chat_id in list_telegram_subscribers():
        r = tg.send_message(chat_id, text)
        if r.get("ok"):
            sent += 1
    return {"sent": sent, "subscribers": len(list_telegram_subscribers())}
