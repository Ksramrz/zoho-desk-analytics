import datetime as dt
import re
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query

from db import query_actions, query_agents, query_kpis, query_summary, query_timeline


router = APIRouter(prefix="/api", tags=["analytics"])

_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _parse_date(value: str, field_name: str) -> dt.datetime:
    try:
        return dt.datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}; expected ISO date/datetime")


def _validate_range_iso(date_from: str, date_to: str) -> tuple[str, str]:
    d_from = _parse_date(date_from, "date_from")
    d_to = _parse_date(date_to, "date_to")
    if d_from >= d_to:
        raise HTTPException(status_code=400, detail="date_from must be earlier than date_to")
    return d_from.isoformat(), d_to.isoformat()


def _resolve_report_range(
    date_from: str,
    date_to: str,
    report_timezone: str | None,
) -> tuple[str, str]:
    """
    If both bounds are calendar dates (YYYY-MM-DD), interpret start/end in `report_timezone`
    (default US Pacific). Otherwise use full ISO datetimes (legacy clients).
    """
    date_from = date_from.strip()
    date_to = date_to.strip()
    has_time = "T" in date_from or "T" in date_to
    if not has_time and _DATE_ONLY.match(date_from) and _DATE_ONLY.match(date_to):
        tzname = (report_timezone or "America/Los_Angeles").strip()
        try:
            tz = ZoneInfo(tzname)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid report_timezone (use an IANA name, e.g. America/Los_Angeles)")
        d0 = dt.date.fromisoformat(date_from)
        d1 = dt.date.fromisoformat(date_to)
        if d0 > d1:
            raise HTTPException(status_code=400, detail="date_from must be on or before date_to")
        start = dt.datetime.combine(d0, dt.time.min, tzinfo=tz)
        end = dt.datetime.combine(d1, dt.time(23, 59, 59, 999999), tzinfo=tz)
        if start >= end:
            raise HTTPException(status_code=400, detail="date_from must be earlier than date_to")
        return start.isoformat(), end.isoformat()
    return _validate_range_iso(date_from, date_to)


@router.get("/summary")
def get_summary(
    date_from: str = Query(..., description="YYYY-MM-DD (calendar in report_timezone) or ISO datetime"),
    date_to: str = Query(..., description="YYYY-MM-DD (calendar in report_timezone) or ISO datetime"),
    report_timezone: str | None = Query(
        "America/Los_Angeles",
        description="IANA zone when using YYYY-MM-DD bounds (e.g. US Pacific for PST/PDT days)",
    ),
):
    start, end = _resolve_report_range(date_from, date_to, report_timezone)
    return {"agents": query_summary(start, end)}


@router.get("/timeline")
def get_timeline(
    date_from: str = Query(..., description="YYYY-MM-DD or ISO datetime"),
    date_to: str = Query(..., description="YYYY-MM-DD or ISO datetime"),
    report_timezone: str | None = Query("America/Los_Angeles"),
    granularity: str = Query("day", pattern="^(day|week)$"),
):
    start, end = _resolve_report_range(date_from, date_to, report_timezone)
    try:
        rows = query_timeline(start, end, granularity)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"granularity": granularity, "rows": rows}


@router.get("/actions")
def get_actions(
    date_from: str = Query(...),
    date_to: str = Query(...),
    report_timezone: str | None = Query("America/Los_Angeles"),
    agent_id: str | None = Query(None),
    action_type: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    start, end = _resolve_report_range(date_from, date_to, report_timezone)
    return query_actions(start, end, agent_id, action_type, page, page_size)


@router.get("/agents")
def get_agents():
    return {"agents": query_agents()}


@router.get("/kpis")
def get_kpis(
    date_from: str = Query(..., description="YYYY-MM-DD or ISO datetime"),
    date_to: str = Query(..., description="YYYY-MM-DD or ISO datetime"),
    report_timezone: str | None = Query("America/Los_Angeles"),
):
    start, end = _resolve_report_range(date_from, date_to, report_timezone)
    return query_kpis(start, end)
