"""
Central flag for anything that calls Zoho Desk / OAuth on a schedule or via API trigger.

Set DISABLE_ZOHO_AUTOMATION=1 (or true/yes/on) in the environment to stop:
- APScheduler Zoho sync on the backend
- Telegram jobs that poll Zoho (they share the same API quota)
- POST /api/sync/trigger (manual / CI / deploy hooks)

Read-only analytics endpoints still work against Postgres.
"""
import os


def zoho_automation_disabled() -> bool:
    raw = os.getenv("DISABLE_ZOHO_AUTOMATION", "").strip().lower()
    return raw in ("1", "true", "yes", "on")
