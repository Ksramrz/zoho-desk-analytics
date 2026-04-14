from fastapi import APIRouter, BackgroundTasks

from db import query_sync_status
from sync import run_sync


router = APIRouter(prefix="/api/sync", tags=["sync"])


@router.get("/status")
def get_sync_status():
    return {"logs": query_sync_status(limit=5)}


@router.post("/trigger")
def trigger_sync(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_sync)
    return {"message": "Sync job submitted"}
