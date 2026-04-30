import os
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from db import init_db
from routers import analytics as analytics_router
from routers import sync as sync_router
from routers import telegram as telegram_router
from sync import run_sync
from telegram_alerts import is_enabled as telegram_enabled
from telegram_alerts import poll_telegram_updates, scan_and_alert


scheduler = BackgroundScheduler(timezone="UTC")


def _sync_interval_minutes() -> int:
    raw = os.getenv("ZOHO_SYNC_INTERVAL_MINUTES", "30").strip()
    try:
        m = int(raw)
    except ValueError:
        m = 30
    return max(15, min(m, 24 * 60))


def _telegram_scan_minutes() -> int:
    raw = os.getenv("TELEGRAM_SCAN_INTERVAL_MINUTES", "5").strip()
    try:
        m = int(raw)
    except ValueError:
        m = 5
    return max(1, min(m, 60))


def _telegram_poll_seconds() -> int:
    raw = os.getenv("TELEGRAM_POLL_INTERVAL_SECONDS", "10").strip()
    try:
        s = int(raw)
    except ValueError:
        s = 10
    return max(3, min(s, 120))


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if not scheduler.running:
        interval = _sync_interval_minutes()
        print(f"[startup] Scheduled Zoho sync every {interval} minute(s) (ZOHO_SYNC_INTERVAL_MINUTES)")
        scheduler.add_job(run_sync, "interval", minutes=interval, id="zoho_sync", replace_existing=True)

        if telegram_enabled():
            scan_min = _telegram_scan_minutes()
            poll_sec = _telegram_poll_seconds()
            print(
                f"[startup] Telegram bot enabled: scanning Zoho every {scan_min} min, "
                f"polling getUpdates every {poll_sec} s"
            )
            scheduler.add_job(
                scan_and_alert, "interval", minutes=scan_min, id="telegram_scan", replace_existing=True
            )
            scheduler.add_job(
                poll_telegram_updates, "interval", seconds=poll_sec, id="telegram_poll", replace_existing=True
            )
        else:
            print("[startup] Telegram bot disabled (TELEGRAM_BOT_TOKEN not set)")

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
app.include_router(telegram_router.router)


@app.get("/health")
def health():
    return {"ok": True}
