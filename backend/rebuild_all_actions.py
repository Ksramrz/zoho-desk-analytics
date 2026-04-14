import datetime as dt
import hashlib

from db import get_cursor, upsert_action, upsert_ticket_snapshot
from sync import _as_iso, _extract_actor, _history_changes, _to_text
from zoho_client import ZohoDeskClient


def _event_id(prefix: str, *parts: object) -> str:
    payload = "|".join(str(p) for p in parts)
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()
    return f"{prefix}:{digest}"


def _iter_all_tickets(client: ZohoDeskClient, limit: int = 100):
    offset = 0
    while True:
        try:
            data = client._request(
                "GET",
                "/tickets/search",
                params={"limit": limit, "from": offset, "sortBy": "-modifiedTime"},
            )
        except Exception as exc:
            if "422" in str(exc) and offset > 0:
                break
            raise
        rows = data.get("data", [])
        if not rows:
            break
        for row in rows:
            yield row
        if len(rows) < limit:
            break
        offset += limit


def _action(
    ticket: dict,
    action_type: str,
    action_timestamp: str,
    agent_id: str,
    agent_name: str,
    source_event_id: str,
    source_event_type: str,
    from_value: str | None = None,
    to_value: str | None = None,
) -> dict:
    return {
        "ticket_id": str(ticket.get("id", "")),
        "ticket_number": str(ticket.get("ticketNumber", "")),
        "ticket_subject": str(ticket.get("subject", "")),
        "agent_id": agent_id or "",
        "agent_name": agent_name or "",
        "action_type": action_type,
        "action_timestamp": action_timestamp,
        "source_event_id": source_event_id,
        "source_event_type": source_event_type,
        "from_value": from_value,
        "to_value": to_value,
        "department_id": str(ticket.get("departmentId", "")) if ticket.get("departmentId") else None,
    }


def main():
    client = ZohoDeskClient()
    tickets_seen = 0
    actions_inserted = 0
    failed_tickets = 0
    start = dt.datetime.now(dt.timezone.utc)

    for ticket in _iter_all_tickets(client):
        tickets_seen += 1
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
                if upsert_action(
                    _action(
                        ticket=ticket,
                        action_type=action_type,
                        action_timestamp=ts,
                        agent_id=str(author.get("id", "")),
                        agent_name=str(author.get("name", "")),
                        source_event_id=f"thread:{th.get('id', '')}",
                        source_event_type="thread",
                    )
                ):
                    actions_inserted += 1

            comments = client.list_comments(ticket_id)
            for cm in comments:
                author = cm.get("commenter") or cm.get("author") or cm.get("createdBy") or {}
                if str(author.get("type", "AGENT")).upper() != "AGENT":
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
                if upsert_action(
                    _action(
                        ticket=ticket,
                        action_type="comment",
                        action_timestamp=ts,
                        agent_id=str(author.get("id", "")),
                        agent_name=str(author.get("name", "")),
                        source_event_id=f"comment:{cm.get('id', '')}",
                        source_event_type="comment",
                    )
                ):
                    actions_inserted += 1

            for h in history:
                base_agent_id, base_agent_name = _extract_actor(h, {})
                modified_by = {"id": base_agent_id, "name": base_agent_name}
                when_iso = _as_iso(h.get("modifiedTime") or h.get("eventTime") or h.get("createdTime") or "")
                if not when_iso:
                    continue
                for ch in _history_changes(h):
                    field = str(ch.get("field") or ch.get("fieldName") or "").strip().lower().replace(" ", "")
                    from_v = _to_text(ch.get("from") or ch.get("oldValue") or ch.get("fromValue"))
                    to_v = _to_text(ch.get("to") or ch.get("newValue") or ch.get("toValue"))
                    ch_agent_id, ch_agent_name = _extract_actor(ch, modified_by)
                    use_agent_id = ch_agent_id or base_agent_id
                    use_agent_name = ch_agent_name or base_agent_name
                    if ("assignee" in field) or ("owner" in field):
                        if upsert_action(
                            _action(
                                ticket=ticket,
                                action_type="handover",
                                action_timestamp=when_iso,
                                agent_id=use_agent_id,
                                agent_name=use_agent_name,
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
                        ):
                            actions_inserted += 1
                    elif "status" in field:
                        if upsert_action(
                            _action(
                                ticket=ticket,
                                action_type="status_change",
                                action_timestamp=when_iso,
                                agent_id=use_agent_id,
                                agent_name=use_agent_name,
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
                        ):
                            actions_inserted += 1
        except Exception as exc:
            failed_tickets += 1
            print(f"[rebuild] ticket {ticket_id} failed: {exc}")
            continue

        if tickets_seen % 100 == 0:
            print(
                f"[rebuild] tickets={tickets_seen} inserted={actions_inserted} failed={failed_tickets} elapsed={(dt.datetime.now(dt.timezone.utc)-start)}"
            )

    print(
        f"[rebuild] complete tickets={tickets_seen} inserted={actions_inserted} failed={failed_tickets} elapsed={(dt.datetime.now(dt.timezone.utc)-start)}"
    )


if __name__ == "__main__":
    # Optional reset when user explicitly wants a full rebuild.
    with get_cursor() as (_, cur):
        cur.execute("DELETE FROM agent_actions;")
    main()
