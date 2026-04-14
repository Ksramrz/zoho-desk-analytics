import datetime as dt
import hashlib
import os
import threading
from typing import Any

from db import get_last_sync_end, insert_sync_log, is_first_run, upsert_action, upsert_ticket_snapshot
from zoho_client import ZohoDeskClient


_sync_lock = threading.Lock()


def _as_iso(value: str | None) -> str:
    if not value:
        return ""
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(dt.timezone.utc).isoformat()


def _history_changes(item: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("events", "history", "changes", "fieldChanges"):
        val = item.get(key)
        if isinstance(val, list):
            return val
    # Some payloads represent one change directly on the history record.
    if any(k in item for k in ("field", "fieldName", "from", "to", "oldValue", "newValue", "fromValue", "toValue")):
        return [item]
    return []


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        for k in ("name", "displayName", "label", "value", "id"):
            if k in value and value[k] not in (None, ""):
                return str(value[k])
        return str(value)
    if isinstance(value, list):
        parts = [_to_text(v) for v in value]
        parts = [p for p in parts if p]
        return ", ".join(parts)
    return str(value)


def _extract_actor(source: dict[str, Any], fallback: dict[str, Any]) -> tuple[str, str]:
    # Zoho history can expose actor in multiple shapes:
    # - modifiedBy/performedBy/updatedBy object
    # - top-level agentId/agentName fields
    if source.get("agentId") or source.get("agentName"):
        return str(source.get("agentId", "")), str(source.get("agentName", ""))
    actor = source.get("modifiedBy") or source.get("performedBy") or source.get("updatedBy") or fallback
    if not isinstance(actor, dict):
        actor = {}
    return str(actor.get("id", "")), str(actor.get("name", ""))


def _make_action(
    ticket: dict[str, Any],
    action_type: str,
    action_timestamp: str,
    agent_id: str,
    agent_name: str,
    source_event_id: str | None = None,
    source_event_type: str | None = None,
    from_value: str | None = None,
    to_value: str | None = None,
) -> dict[str, Any]:
    return {
        "ticket_id": str(ticket.get("id", "")),
        "ticket_number": str(ticket.get("ticketNumber", "")),
        "ticket_subject": str(ticket.get("subject", "")),
        "agent_id": agent_id or "",
        "agent_name": agent_name or "",
        "action_type": action_type,
        "action_timestamp": action_timestamp,
        "source_event_id": source_event_id or "",
        "source_event_type": source_event_type or "",
        "from_value": from_value,
        "to_value": to_value,
        "department_id": str(ticket.get("departmentId", "")) if ticket.get("departmentId") else None,
    }


def _event_id(prefix: str, *parts: Any) -> str:
    payload = "|".join(str(p) for p in parts)
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()
    return f"{prefix}:{digest}"


def run_sync() -> dict[str, Any]:
    if not _sync_lock.acquire(blocking=False):
        return {"started": False, "message": "Sync already running"}

    start_dt = dt.datetime.now(dt.timezone.utc)
    tickets_processed = 0
    actions_inserted = 0
    failed_tickets = 0

    try:
        client = ZohoDeskClient()
        lookback_days = int(os.getenv("SYNC_LOOKBACK_DAYS", "31"))
        overlap_hours = int(os.getenv("SYNC_OVERLAP_HOURS", "24"))
        if is_first_run():
            window_start = start_dt - dt.timedelta(days=max(90, lookback_days))
        else:
            # Incremental sync for faster, reliable recurring runs.
            # Keep an overlap window to catch late Zoho updates.
            last_success = get_last_sync_end()
            if last_success:
                last_dt = dt.datetime.fromisoformat(last_success.replace("Z", "+00:00")).astimezone(dt.timezone.utc)
                window_start = min(
                    start_dt - dt.timedelta(days=lookback_days),
                    last_dt - dt.timedelta(hours=overlap_hours),
                )
            else:
                window_start = start_dt - dt.timedelta(days=lookback_days)
        window_end = start_dt

        tickets = client.list_modified_tickets(window_start.isoformat(), window_end.isoformat())
        tickets_processed = len(tickets)

        for ticket in tickets:
            ticket_id = str(ticket.get("id", ""))
            if not ticket_id:
                continue
            try:
                upsert_ticket_snapshot(ticket)

                threads, comments, history = client.fetch_ticket_activity(ticket_id)
                for th in threads:
                    author = th.get("author") or {}
                    if str(author.get("type", "")).upper() != "AGENT":
                        continue
                    visibility = str(th.get("visibility", "")).lower()
                    if visibility == "public":
                        action_type = "reply"
                    elif visibility == "private":
                        action_type = "internal_note"
                    else:
                        continue
                    ts = _as_iso(th.get("createdTime") or th.get("lastModifiedTime") or "")
                    if not ts:
                        continue
                    action = _make_action(
                        ticket=ticket,
                        action_type=action_type,
                        action_timestamp=ts,
                        agent_id=str(author.get("id", "")),
                        agent_name=str(author.get("name", "")),
                        source_event_id=f"thread:{th.get('id', '')}",
                        source_event_type="thread",
                    )
                    if upsert_action(action):
                        actions_inserted += 1

                for cm in comments:
                    author = cm.get("commenter") or cm.get("author") or cm.get("createdBy") or {}
                    author_type = str(author.get("type", "AGENT")).upper()
                    if author_type != "AGENT":
                        continue
                    ts = _as_iso(
                        cm.get("commentedTime")
                        or cm.get("modifiedTime")
                        or cm.get("createdTime")
                        or cm.get("lastModifiedTime")
                        or ""
                    )
                    if not ts:
                        continue
                    action = _make_action(
                        ticket=ticket,
                        action_type="comment",
                        action_timestamp=ts,
                        agent_id=str(author.get("id", "")),
                        agent_name=str(author.get("name", "")),
                        source_event_id=f"comment:{cm.get('id', '')}",
                        source_event_type="comment",
                    )
                    if upsert_action(action):
                        actions_inserted += 1

                for h in history:
                    base_agent_id, base_agent_name = _extract_actor(h, {})
                    modified_by = {"id": base_agent_id, "name": base_agent_name}
                    agent_id = base_agent_id
                    agent_name = base_agent_name
                    when = h.get("modifiedTime") or h.get("eventTime") or h.get("createdTime") or ""
                    when_iso = _as_iso(when)
                    if not when_iso:
                        continue
                    for ch in _history_changes(h):
                        if not isinstance(ch, dict):
                            continue
                        field = str(ch.get("field") or ch.get("fieldName") or "").strip().lower().replace(" ", "")
                        from_v = _to_text(ch.get("from") or ch.get("oldValue") or ch.get("fromValue"))
                        to_v = _to_text(ch.get("to") or ch.get("newValue") or ch.get("toValue"))
                        ch_agent_id, ch_agent_name = _extract_actor(ch, modified_by)
                        use_agent_id = ch_agent_id or agent_id
                        use_agent_name = ch_agent_name or agent_name
                        is_handover_field = ("assignee" in field) or ("owner" in field)
                        is_status_field = ("status" in field)
                        if is_handover_field:
                            action = _make_action(
                                ticket,
                                "handover",
                                when_iso,
                                use_agent_id,
                                use_agent_name,
                                source_event_id=_event_id(
                                    "history",
                                    h.get("id", ""),
                                    h.get("eventTime", ""),
                                    "handover",
                                    field,
                                    from_v,
                                    to_v,
                                ),
                                source_event_type="history",
                                from_value=from_v,
                                to_value=to_v,
                            )
                            if upsert_action(action):
                                actions_inserted += 1
                        elif is_status_field:
                            action = _make_action(
                                ticket,
                                "status_change",
                                when_iso,
                                use_agent_id,
                                use_agent_name,
                                source_event_id=_event_id(
                                    "history",
                                    h.get("id", ""),
                                    h.get("eventTime", ""),
                                    "status_change",
                                    field,
                                    from_v,
                                    to_v,
                                ),
                                source_event_type="history",
                                from_value=from_v,
                                to_value=to_v,
                            )
                            if upsert_action(action):
                                actions_inserted += 1
            except Exception as ticket_exc:
                failed_tickets += 1
                print(f"[sync] ticket {ticket_id} failed: {ticket_exc}")
                continue

        end_dt = dt.datetime.now(dt.timezone.utc)
        status = "success" if failed_tickets == 0 else "partial_success"
        error_message = None if failed_tickets == 0 else f"Failed tickets: {failed_tickets}"
        insert_sync_log(
            sync_start=start_dt.isoformat(),
            sync_end=end_dt.isoformat(),
            tickets_processed=tickets_processed,
            actions_inserted=actions_inserted,
            status=status,
            error_message=error_message,
        )
        return {
            "started": True,
            "status": status,
            "tickets_processed": tickets_processed,
            "actions_inserted": actions_inserted,
            "failed_tickets": failed_tickets,
            "sync_start": start_dt.isoformat(),
            "sync_end": end_dt.isoformat(),
        }
    except Exception as exc:
        end_dt = dt.datetime.now(dt.timezone.utc)
        insert_sync_log(
            sync_start=start_dt.isoformat(),
            sync_end=end_dt.isoformat(),
            tickets_processed=tickets_processed,
            actions_inserted=actions_inserted,
            status="error",
            error_message=str(exc),
        )
        raise
    finally:
        _sync_lock.release()
