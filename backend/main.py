import os
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from db import init_db
from routers import assistant as assistant_router
from routers import analytics as analytics_router
from routers import sync as sync_router
from sync import run_sync
from telegram_reminders import send_due_telegram_reminders


scheduler = BackgroundScheduler(timezone="UTC")


def _sync_interval_minutes() -> int:
    raw = os.getenv("ZOHO_SYNC_INTERVAL_MINUTES", "30").strip()
    try:
        m = int(raw)
    except ValueError:
        m = 30
    return max(15, min(m, 24 * 60))


def _reminder_interval_minutes() -> int:
    raw = os.getenv("TELEGRAM_REMINDER_INTERVAL_MINUTES", "5").strip()
    try:
        m = int(raw)
    except ValueError:
        m = 5
    return max(1, min(m, 60))


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if not scheduler.running:
        interval = _sync_interval_minutes()
        print(f"[startup] Scheduled Zoho sync every {interval} minute(s) (ZOHO_SYNC_INTERVAL_MINUTES)")
        scheduler.add_job(run_sync, "interval", minutes=interval, id="zoho_sync", replace_existing=True)
        reminder_interval = _reminder_interval_minutes()
        print(f"[startup] Scheduled Telegram reminder check every {reminder_interval} minute(s)")
        scheduler.add_job(
            send_due_telegram_reminders,
            "interval",
            minutes=reminder_interval,
            id="telegram_reminders",
            replace_existing=True,
        )
        scheduler.start()
    try:
        yield
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)


app = FastAPI(title="Desk Analytics API", lifespan=lifespan)

allowed = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[x.strip() for x in allowed if x.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(analytics_router.router)
app.include_router(sync_router.router)
app.include_router(assistant_router.router)


@app.get("/health")
def health():
    return {"ok": True}
