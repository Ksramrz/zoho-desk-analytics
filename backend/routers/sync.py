from functools import partial

from fastapi import APIRouter, BackgroundTasks, Query

from db import query_sync_status
from sync import run_sync


router = APIRouter(prefix="/api/sync", tags=["sync"])


@router.get("/status")
def get_sync_status():
    return {"logs": query_sync_status(limit=5)}


@router.post("/trigger")
def trigger_sync(
    background_tasks: BackgroundTasks,
    force_full_lookback: bool = Query(
        False,
        description="Ignore incremental cursor; sync a full rolling window ending now (pair with lookback_days).",
    ),
    lookback_days: int | None = Query(
        None,
        ge=1,
        le=365,
        description="Override SYNC_LOOKBACK_DAYS for this run (e.g. 7 for last week).",
    ),
):
    kwargs: dict = {}
    if force_full_lookback:
        kwargs["force_full_lookback"] = True
    if lookback_days is not None:
        kwargs["lookback_days_override"] = lookback_days
    background_tasks.add_task(partial(run_sync, **kwargs))
    return {
        "message": "Sync job submitted",
        "force_full_lookback": force_full_lookback,
        "lookback_days": lookback_days,
    }
