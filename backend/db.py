import os
import re
import time
from contextlib import contextmanager
from typing import Any

import psycopg2
import psycopg2.extras


DATABASE_URL = os.getenv("DATABASE_URL", "").strip()


def _report_timezone_sql() -> str:
    """IANA zone for Metabase/reporting (default US Pacific; handles DST)."""
    tz = os.getenv("ANALYTICS_REPORT_TIMEZONE", "America/Los_Angeles").strip() or "America/Los_Angeles"
    if not re.match(r"^[A-Za-z0-9_/+-]+$", tz) or len(tz) > 80:
        tz = "America/Los_Angeles"
    return tz.replace("'", "''")


def _analytics_excluded_where() -> str:
    """
    SQL AND-clauses to drop shared/team mailboxes from analytics (not from raw storage).
    Override via .env: ANALYTICS_EXCLUDED_AGENT_NAMES, ANALYTICS_EXCLUDED_AGENT_IDS (comma-separated).
    """
    names = []
    raw = os.getenv("ANALYTICS_EXCLUDED_AGENT_NAMES", "TechProduct Team")
    for n in raw.split(","):
        n = n.strip()
        if n:
            names.append(n.replace("'", "''"))
    ids = []
    raw_i = os.getenv("ANALYTICS_EXCLUDED_AGENT_IDS", "7296000004702077")
    for i in raw_i.split(","):
        i = i.strip()
        if i:
            ids.append(i.replace("'", "''"))
    parts: list[str] = []
    for n in names:
        parts.append(f"COALESCE(agent_name, '') <> '{n}'")
    for i in ids:
        parts.append(f"COALESCE(agent_id, '') <> '{i}'")
    if not parts:
        return ""
    return " AND " + " AND ".join(parts)


def _drop_reporting_views_for_migration() -> None:
    """Committed immediately so a failed CREATE does not roll back DROPs."""
    adc = _conn()
    adc.autocommit = True
    try:
        dcur = adc.cursor()
        for stmt in (
            "DROP VIEW IF EXISTS v_manager_agent_performance_monthly CASCADE",
            "DROP VIEW IF EXISTS v_manager_agent_performance_weekly CASCADE",
            "DROP VIEW IF EXISTS v_manager_agent_performance_daily CASCADE",
            "DROP VIEW IF EXISTS v_reporting_agents_actions_daily_pt CASCADE",
            "DROP VIEW IF EXISTS v_reporting_agents_monthly_pt CASCADE",
            "DROP VIEW IF EXISTS v_reporting_agents_weekly_pt CASCADE",
            "DROP VIEW IF EXISTS v_reporting_agents_daily_pt CASCADE",
        ):
            dcur.execute(stmt + ";")
        dcur.close()
    finally:
        adc.close()


def _create_reporting_views_pt(cur) -> None:
    """Pacific-calendar aggregates for people (excludes team mailboxes)."""
    _drop_reporting_views_for_migration()
    tz = _report_timezone_sql()
    ex = _analytics_excluded_where()
    metrics = """
                COUNT(*) AS total_actions,
                COUNT(DISTINCT ticket_id) AS tickets_touched,
                SUM(CASE WHEN action_type='reply' THEN 1 ELSE 0 END) AS replies,
                SUM(CASE WHEN action_type='internal_note' THEN 1 ELSE 0 END) AS internal_notes,
                SUM(CASE WHEN action_type='comment' THEN 1 ELSE 0 END) AS comments,
                SUM(CASE WHEN action_type='handover' THEN 1 ELSE 0 END) AS handovers,
                SUM(CASE WHEN action_type='status_change' THEN 1 ELSE 0 END) AS status_changes,
                SUM(CASE WHEN action_type IN ('reply','comment') THEN 1 ELSE 0 END) AS customer_responses
    """
    cur.execute(
        f"""
        CREATE OR REPLACE VIEW v_reporting_agents_daily_pt AS
        SELECT
            (action_timestamp AT TIME ZONE '{tz}')::date AS report_date_pt,
            '{tz}'::text AS report_timezone,
            COALESCE(NULLIF(agent_name, ''), 'Unknown') AS agent_name,
            {metrics}
        FROM agent_actions
        WHERE 1=1 {ex}
        GROUP BY 1, 2, 3;
        """
    )
    cur.execute(
        f"""
        CREATE OR REPLACE VIEW v_reporting_agents_weekly_pt AS
        SELECT
            date_trunc('week', action_timestamp AT TIME ZONE '{tz}')::date AS week_start_pt,
            '{tz}'::text AS report_timezone,
            COALESCE(NULLIF(agent_name, ''), 'Unknown') AS agent_name,
            {metrics}
        FROM agent_actions
        WHERE 1=1 {ex}
        GROUP BY 1, 2, 3;
        """
    )
    cur.execute(
        f"""
        CREATE OR REPLACE VIEW v_reporting_agents_monthly_pt AS
        SELECT
            date_trunc('month', action_timestamp AT TIME ZONE '{tz}')::date AS month_start_pt,
            '{tz}'::text AS report_timezone,
            COALESCE(NULLIF(agent_name, ''), 'Unknown') AS agent_name,
            {metrics}
        FROM agent_actions
        WHERE 1=1 {ex}
        GROUP BY 1, 2, 3;
        """
    )
    cur.execute(
        f"""
        CREATE OR REPLACE VIEW v_reporting_agents_actions_daily_pt AS
        SELECT
            (action_timestamp AT TIME ZONE '{tz}')::date AS report_date_pt,
            '{tz}'::text AS report_timezone,
            COALESCE(NULLIF(agent_name, ''), 'Unknown') AS agent_name,
            action_type,
            COUNT(*) AS action_count,
            COUNT(DISTINCT ticket_id) AS tickets_touched
        FROM agent_actions
        WHERE 1=1 {ex}
        GROUP BY 1, 2, 3, 4;
        """
    )
    # Legacy Metabase names: `bucket_start` stays timestamptz (Pacific midnight for that calendar bucket).
    cur.execute(
        f"""
        CREATE OR REPLACE VIEW v_manager_agent_performance_daily AS
        SELECT
            (report_date_pt::timestamp AT TIME ZONE '{tz}') AS bucket_start,
            report_timezone,
            agent_name,
            total_actions,
            tickets_touched,
            replies,
            comments,
            handovers,
            status_changes,
            internal_notes,
            customer_responses
        FROM v_reporting_agents_daily_pt;
        """
    )
    cur.execute(
        f"""
        CREATE OR REPLACE VIEW v_manager_agent_performance_weekly AS
        SELECT
            (week_start_pt::timestamp AT TIME ZONE '{tz}') AS bucket_start,
            report_timezone,
            agent_name,
            total_actions,
            tickets_touched,
            replies,
            comments,
            handovers,
            status_changes,
            internal_notes,
            customer_responses
        FROM v_reporting_agents_weekly_pt;
        """
    )
    cur.execute(
        f"""
        CREATE OR REPLACE VIEW v_manager_agent_performance_monthly AS
        SELECT
            (month_start_pt::timestamp AT TIME ZONE '{tz}') AS bucket_start,
            report_timezone,
            agent_name,
            total_actions,
            tickets_touched,
            replies,
            comments,
            handovers,
            status_changes,
            internal_notes,
            customer_responses
        FROM v_reporting_agents_monthly_pt;
        """
    )


def _conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set")
    last_err = None
    for attempt in range(12):
        try:
            return psycopg2.connect(DATABASE_URL)
        except psycopg2.OperationalError as exc:
            last_err = exc
            # Startup race: db container can be up before Postgres is ready.
            time.sleep(min(1 + attempt, 5))
    raise last_err


@contextmanager
def get_cursor(dict_cursor: bool = False):
    conn = _conn()
    try:
        cur_factory = psycopg2.extras.RealDictCursor if dict_cursor else None
        cur = conn.cursor(cursor_factory=cur_factory)
        try:
            yield conn, cur
            conn.commit()
        finally:
            cur.close()
    finally:
        conn.close()


def init_db() -> None:
    with get_cursor() as (_, cur):
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_actions (
                id SERIAL PRIMARY KEY,
                ticket_id VARCHAR NOT NULL,
                ticket_number VARCHAR,
                ticket_subject VARCHAR,
                agent_id VARCHAR,
                agent_name VARCHAR,
                action_type VARCHAR NOT NULL,
                action_timestamp TIMESTAMPTZ NOT NULL,
                source_event_id VARCHAR NULL,
                source_event_type VARCHAR NULL,
                from_value VARCHAR NULL,
                to_value VARCHAR NULL,
                department_id VARCHAR NULL,
                synced_at TIMESTAMPTZ DEFAULT now(),
                UNIQUE(ticket_id, action_type, action_timestamp, agent_id)
            );
            """
        )
        cur.execute("ALTER TABLE agent_actions ADD COLUMN IF NOT EXISTS source_event_id VARCHAR NULL;")
        cur.execute("ALTER TABLE agent_actions ADD COLUMN IF NOT EXISTS source_event_type VARCHAR NULL;")
        cur.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ux_agent_actions_source_event_id
            ON agent_actions(source_event_id);
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS sync_log (
                id SERIAL PRIMARY KEY,
                sync_start TIMESTAMPTZ NOT NULL,
                sync_end TIMESTAMPTZ NOT NULL,
                tickets_processed INT NOT NULL DEFAULT 0,
                actions_inserted INT NOT NULL DEFAULT 0,
                status VARCHAR NOT NULL,
                error_message TEXT NULL
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS tickets_snapshot (
                ticket_id VARCHAR PRIMARY KEY,
                ticket_number VARCHAR,
                ticket_subject VARCHAR,
                department_id VARCHAR NULL,
                status VARCHAR NULL,
                assignee_id VARCHAR NULL,
                assignee_name VARCHAR NULL,
                created_time TIMESTAMPTZ NULL,
                modified_time TIMESTAMPTZ NULL,
                synced_at TIMESTAMPTZ DEFAULT now()
            );
            """
        )
        # Analytics-friendly views for Metabase dashboards.
        cur.execute(
            """
            CREATE OR REPLACE VIEW v_agent_performance_daily AS
            SELECT
                date_trunc('day', action_timestamp) AS bucket_start,
                COALESCE(NULLIF(agent_name, ''), 'Unknown') AS agent_name,
                COUNT(*) AS total_actions,
                COUNT(DISTINCT ticket_id) AS tickets_touched,
                SUM(CASE WHEN action_type='reply' THEN 1 ELSE 0 END) AS replies,
                SUM(CASE WHEN action_type='internal_note' THEN 1 ELSE 0 END) AS internal_notes,
                SUM(CASE WHEN action_type='comment' THEN 1 ELSE 0 END) AS comments,
                SUM(CASE WHEN action_type='handover' THEN 1 ELSE 0 END) AS handovers,
                SUM(CASE WHEN action_type='status_change' THEN 1 ELSE 0 END) AS status_changes
            FROM agent_actions
            GROUP BY 1, 2;
            """
        )
        cur.execute(
            """
            CREATE OR REPLACE VIEW v_agent_performance_weekly AS
            SELECT
                date_trunc('week', action_timestamp) AS bucket_start,
                COALESCE(NULLIF(agent_name, ''), 'Unknown') AS agent_name,
                COUNT(*) AS total_actions,
                COUNT(DISTINCT ticket_id) AS tickets_touched,
                SUM(CASE WHEN action_type='reply' THEN 1 ELSE 0 END) AS replies,
                SUM(CASE WHEN action_type='internal_note' THEN 1 ELSE 0 END) AS internal_notes,
                SUM(CASE WHEN action_type='comment' THEN 1 ELSE 0 END) AS comments,
                SUM(CASE WHEN action_type='handover' THEN 1 ELSE 0 END) AS handovers,
                SUM(CASE WHEN action_type='status_change' THEN 1 ELSE 0 END) AS status_changes
            FROM agent_actions
            GROUP BY 1, 2;
            """
        )
        cur.execute(
            """
            CREATE OR REPLACE VIEW v_agent_performance_monthly AS
            SELECT
                date_trunc('month', action_timestamp) AS bucket_start,
                COALESCE(NULLIF(agent_name, ''), 'Unknown') AS agent_name,
                COUNT(*) AS total_actions,
                COUNT(DISTINCT ticket_id) AS tickets_touched,
                SUM(CASE WHEN action_type='reply' THEN 1 ELSE 0 END) AS replies,
                SUM(CASE WHEN action_type='internal_note' THEN 1 ELSE 0 END) AS internal_notes,
                SUM(CASE WHEN action_type='comment' THEN 1 ELSE 0 END) AS comments,
                SUM(CASE WHEN action_type='handover' THEN 1 ELSE 0 END) AS handovers,
                SUM(CASE WHEN action_type='status_change' THEN 1 ELSE 0 END) AS status_changes
            FROM agent_actions
            GROUP BY 1, 2;
            """
        )
        cur.execute(
            """
            CREATE OR REPLACE VIEW v_agent_action_comparison_daily AS
            SELECT
                date_trunc('day', action_timestamp) AS bucket_start,
                COALESCE(NULLIF(agent_name, ''), 'Unknown') AS agent_name,
                action_type,
                COUNT(*) AS action_count,
                COUNT(DISTINCT ticket_id) AS tickets_touched
            FROM agent_actions
            GROUP BY 1, 2, 3;
            """
        )
        cur.execute(
            """
            CREATE OR REPLACE VIEW v_agent_action_comparison_weekly AS
            SELECT
                date_trunc('week', action_timestamp) AS bucket_start,
                COALESCE(NULLIF(agent_name, ''), 'Unknown') AS agent_name,
                action_type,
                COUNT(*) AS action_count,
                COUNT(DISTINCT ticket_id) AS tickets_touched
            FROM agent_actions
            GROUP BY 1, 2, 3;
            """
        )
        cur.execute(
            """
            CREATE OR REPLACE VIEW v_agent_action_comparison_monthly AS
            SELECT
                date_trunc('month', action_timestamp) AS bucket_start,
                COALESCE(NULLIF(agent_name, ''), 'Unknown') AS agent_name,
                action_type,
                COUNT(*) AS action_count,
                COUNT(DISTINCT ticket_id) AS tickets_touched
            FROM agent_actions
            GROUP BY 1, 2, 3;
            """
        )
        cur.execute(
            """
            CREATE OR REPLACE VIEW v_agent_performance_comparison_daily AS
            SELECT
                date_trunc('day', action_timestamp) AS bucket_start,
                COALESCE(NULLIF(agent_name, ''), 'Unknown') AS agent_name,
                COUNT(*) AS total_actions,
                COUNT(DISTINCT ticket_id) AS tickets_touched,
                SUM(CASE WHEN action_type='reply' THEN 1 ELSE 0 END) AS replies,
                SUM(CASE WHEN action_type='comment' THEN 1 ELSE 0 END) AS comments,
                SUM(CASE WHEN action_type='handover' THEN 1 ELSE 0 END) AS handovers,
                SUM(CASE WHEN action_type='status_change' THEN 1 ELSE 0 END) AS status_changes,
                SUM(CASE WHEN action_type IN ('reply','comment') THEN 1 ELSE 0 END) AS customer_responses
            FROM agent_actions
            GROUP BY 1, 2;
            """
        )
        cur.execute(
            """
            CREATE OR REPLACE VIEW v_agent_performance_comparison_weekly AS
            SELECT
                date_trunc('week', action_timestamp) AS bucket_start,
                COALESCE(NULLIF(agent_name, ''), 'Unknown') AS agent_name,
                COUNT(*) AS total_actions,
                COUNT(DISTINCT ticket_id) AS tickets_touched,
                SUM(CASE WHEN action_type='reply' THEN 1 ELSE 0 END) AS replies,
                SUM(CASE WHEN action_type='comment' THEN 1 ELSE 0 END) AS comments,
                SUM(CASE WHEN action_type='handover' THEN 1 ELSE 0 END) AS handovers,
                SUM(CASE WHEN action_type='status_change' THEN 1 ELSE 0 END) AS status_changes,
                SUM(CASE WHEN action_type IN ('reply','comment') THEN 1 ELSE 0 END) AS customer_responses
            FROM agent_actions
            GROUP BY 1, 2;
            """
        )
        cur.execute(
            """
            CREATE OR REPLACE VIEW v_agent_performance_comparison_monthly AS
            SELECT
                date_trunc('month', action_timestamp) AS bucket_start,
                COALESCE(NULLIF(agent_name, ''), 'Unknown') AS agent_name,
                COUNT(*) AS total_actions,
                COUNT(DISTINCT ticket_id) AS tickets_touched,
                SUM(CASE WHEN action_type='reply' THEN 1 ELSE 0 END) AS replies,
                SUM(CASE WHEN action_type='comment' THEN 1 ELSE 0 END) AS comments,
                SUM(CASE WHEN action_type='handover' THEN 1 ELSE 0 END) AS handovers,
                SUM(CASE WHEN action_type='status_change' THEN 1 ELSE 0 END) AS status_changes,
                SUM(CASE WHEN action_type IN ('reply','comment') THEN 1 ELSE 0 END) AS customer_responses
            FROM agent_actions
            GROUP BY 1, 2;
            """
        )
        cur.execute(
            """
            CREATE OR REPLACE VIEW v_ticket_incoming_daily AS
            SELECT
                date_trunc('day', created_time) AS bucket_start,
                COUNT(*) AS incoming_tickets
            FROM tickets_snapshot
            WHERE created_time IS NOT NULL
            GROUP BY 1;
            """
        )
        cur.execute(
            """
            CREATE OR REPLACE VIEW v_period_comparison AS
            SELECT
                'today'::text AS period,
                (SELECT COUNT(*) FROM tickets_snapshot WHERE created_time >= date_trunc('day', now())) AS incoming_tickets,
                (SELECT COUNT(*) FROM tickets_snapshot WHERE modified_time >= date_trunc('day', now())) AS modified_tickets,
                (SELECT COUNT(DISTINCT ticket_id) FROM agent_actions WHERE action_timestamp >= date_trunc('day', now())) AS touched_tickets,
                (SELECT COUNT(*) FROM agent_actions WHERE action_timestamp >= date_trunc('day', now())) AS total_actions
            UNION ALL
            SELECT
                'last_7_days'::text,
                (SELECT COUNT(*) FROM tickets_snapshot WHERE created_time >= now() - interval '7 days'),
                (SELECT COUNT(*) FROM tickets_snapshot WHERE modified_time >= now() - interval '7 days'),
                (SELECT COUNT(DISTINCT ticket_id) FROM agent_actions WHERE action_timestamp >= now() - interval '7 days'),
                (SELECT COUNT(*) FROM agent_actions WHERE action_timestamp >= now() - interval '7 days')
            UNION ALL
            SELECT
                'last_30_days'::text,
                (SELECT COUNT(*) FROM tickets_snapshot WHERE created_time >= now() - interval '30 days'),
                (SELECT COUNT(*) FROM tickets_snapshot WHERE modified_time >= now() - interval '30 days'),
                (SELECT COUNT(DISTINCT ticket_id) FROM agent_actions WHERE action_timestamp >= now() - interval '30 days'),
                (SELECT COUNT(*) FROM agent_actions WHERE action_timestamp >= now() - interval '30 days');
            """
        )
        cur.execute(
            """
            CREATE OR REPLACE VIEW v_data_quality_status AS
            WITH recent AS (
                SELECT *
                FROM agent_actions
                WHERE action_timestamp >= now() - interval '30 days'
            ),
            totals AS (
                SELECT
                    COUNT(*)::bigint AS total_actions_30d,
                    COUNT(*) FILTER (WHERE COALESCE(NULLIF(agent_name, ''), 'Unknown') = 'Unknown')::bigint AS unknown_actions_30d,
                    COUNT(*) FILTER (WHERE LOWER(COALESCE(agent_name, '')) LIKE '%team%')::bigint AS team_bucket_actions_30d
                FROM recent
            ),
            syncs AS (
                SELECT
                    MAX(sync_end) AS last_sync_end,
                    MAX(CASE WHEN status='success' THEN sync_end END) AS last_success_sync_end
                FROM sync_log
            ),
            snapshots AS (
                SELECT
                    COUNT(*)::bigint AS ticket_snapshot_rows,
                    MAX(synced_at) AS last_ticket_snapshot_sync
                FROM tickets_snapshot
            )
            SELECT
                total_actions_30d,
                unknown_actions_30d,
                team_bucket_actions_30d,
                CASE WHEN total_actions_30d = 0 THEN 0
                     ELSE ROUND((unknown_actions_30d::numeric / total_actions_30d::numeric) * 100, 2)
                END AS unknown_pct_30d,
                CASE WHEN total_actions_30d = 0 THEN 0
                     ELSE ROUND((team_bucket_actions_30d::numeric / total_actions_30d::numeric) * 100, 2)
                END AS team_bucket_pct_30d,
                last_sync_end,
                last_success_sync_end,
                ticket_snapshot_rows,
                last_ticket_snapshot_sync
            FROM totals, syncs, snapshots;
            """
        )
        cur.execute(
            """
            CREATE OR REPLACE VIEW v_agent_overview AS
            WITH base AS (
                SELECT
                    COALESCE(NULLIF(agent_id, ''), '') AS agent_id,
                    COALESCE(NULLIF(agent_name, ''), 'Unknown') AS agent_name,
                    ticket_id,
                    action_type,
                    action_timestamp,
                    COALESCE(NULLIF(from_value, ''), '') AS from_value,
                    COALESCE(NULLIF(to_value, ''), '') AS to_value
                FROM agent_actions
            )
            SELECT
                agent_name,
                COUNT(*) AS total_actions,
                COUNT(DISTINCT ticket_id) AS tickets_touched,
                SUM(CASE WHEN action_type='reply' THEN 1 ELSE 0 END) AS replies,
                SUM(CASE WHEN action_type='internal_note' THEN 1 ELSE 0 END) AS internal_notes,
                SUM(CASE WHEN action_type='comment' THEN 1 ELSE 0 END) AS comments,
                SUM(CASE WHEN action_type='handover' THEN 1 ELSE 0 END) AS handovers,
                SUM(CASE WHEN action_type='status_change' THEN 1 ELSE 0 END) AS status_changes,
                SUM(
                    CASE
                        WHEN action_type='handover'
                         AND (
                             LOWER(TRIM(to_value)) = LOWER(TRIM(agent_name))
                             OR TRIM(to_value) = TRIM(agent_id)
                         )
                        THEN 1 ELSE 0
                    END
                ) AS handovers_in,
                SUM(
                    CASE
                        WHEN action_type='handover'
                         AND (
                             LOWER(TRIM(from_value)) = LOWER(TRIM(agent_name))
                             OR TRIM(from_value) = TRIM(agent_id)
                         )
                        THEN 1 ELSE 0
                    END
                ) AS handovers_out,
                MIN(action_timestamp) AS first_seen_action,
                MAX(action_timestamp) AS latest_action
            FROM base
            GROUP BY agent_name;
            """
        )
        cur.execute(
            """
            CREATE OR REPLACE VIEW v_ticket_activity AS
            SELECT
                ticket_id,
                ticket_number,
                MAX(ticket_subject) AS ticket_subject,
                MIN(action_timestamp) AS first_action_at,
                MAX(action_timestamp) AS latest_action_at,
                COUNT(*) AS total_actions,
                COUNT(DISTINCT COALESCE(NULLIF(agent_name, ''), 'Unknown')) AS unique_agents_involved,
                SUM(CASE WHEN action_type='reply' THEN 1 ELSE 0 END) AS replies,
                SUM(CASE WHEN action_type='internal_note' THEN 1 ELSE 0 END) AS internal_notes,
                SUM(CASE WHEN action_type='comment' THEN 1 ELSE 0 END) AS comments,
                SUM(CASE WHEN action_type='handover' THEN 1 ELSE 0 END) AS handovers,
                SUM(CASE WHEN action_type='status_change' THEN 1 ELSE 0 END) AS status_changes
            FROM agent_actions
            GROUP BY ticket_id, ticket_number;
            """
        )
        _create_reporting_views_pt(cur)

        # Telegram bot tables (subscribers, alert dedup, callback promises).
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS telegram_subscribers (
                chat_id BIGINT PRIMARY KEY,
                username VARCHAR NULL,
                first_name VARCHAR NULL,
                subscribed_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS telegram_alerts_sent (
                alert_key VARCHAR PRIMARY KEY,
                last_sent_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS telegram_callback_promises (
                id SERIAL PRIMARY KEY,
                ticket_id VARCHAR NOT NULL,
                ticket_number VARCHAR NULL,
                subject VARCHAR NULL,
                promised_at TIMESTAMPTZ NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                sent_at TIMESTAMPTZ NULL,
                UNIQUE (ticket_id, promised_at)
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS telegram_state (
                key VARCHAR PRIMARY KEY,
                value VARCHAR NOT NULL
            );
            """
        )


def is_first_run() -> bool:
    with get_cursor() as (_, cur):
        cur.execute("SELECT COUNT(*) FROM sync_log;")
        return int(cur.fetchone()[0]) == 0


def upsert_action(action: dict[str, Any]) -> bool:
    with get_cursor() as (_, cur):
        cur.execute(
            """
            INSERT INTO agent_actions (
                ticket_id, ticket_number, ticket_subject, agent_id, agent_name,
                action_type, action_timestamp, source_event_id, source_event_type, from_value, to_value, department_id
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT DO NOTHING;
            """,
            (
                action.get("ticket_id"),
                action.get("ticket_number"),
                action.get("ticket_subject"),
                action.get("agent_id"),
                action.get("agent_name"),
                action.get("action_type"),
                action.get("action_timestamp"),
                action.get("source_event_id"),
                action.get("source_event_type"),
                action.get("from_value"),
                action.get("to_value"),
                action.get("department_id"),
            ),
        )
        return cur.rowcount > 0


def upsert_ticket_snapshot(ticket: dict[str, Any]) -> bool:
    ticket_id = str(ticket.get("id", ""))
    if not ticket_id:
        return False
    with get_cursor() as (_, cur):
        cur.execute(
            """
            INSERT INTO tickets_snapshot (
                ticket_id, ticket_number, ticket_subject, department_id, status,
                assignee_id, assignee_name, created_time, modified_time, synced_at
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s, now())
            ON CONFLICT (ticket_id) DO UPDATE SET
                ticket_number = EXCLUDED.ticket_number,
                ticket_subject = EXCLUDED.ticket_subject,
                department_id = EXCLUDED.department_id,
                status = EXCLUDED.status,
                assignee_id = EXCLUDED.assignee_id,
                assignee_name = EXCLUDED.assignee_name,
                created_time = EXCLUDED.created_time,
                modified_time = EXCLUDED.modified_time,
                synced_at = now();
            """,
            (
                ticket_id,
                str(ticket.get("ticketNumber", "")),
                str(ticket.get("subject", "")),
                str(ticket.get("departmentId", "")) if ticket.get("departmentId") else None,
                str(ticket.get("status", "")) if ticket.get("status") else None,
                str(ticket.get("assigneeId", "")) if ticket.get("assigneeId") else None,
                str(ticket.get("assigneeName", "")) if ticket.get("assigneeName") else None,
                ticket.get("createdTime"),
                ticket.get("modifiedTime") or ticket.get("createdTime"),
            ),
        )
        return cur.rowcount > 0


def insert_sync_log(
    sync_start: str,
    sync_end: str,
    tickets_processed: int,
    actions_inserted: int,
    status: str,
    error_message: str | None = None,
) -> None:
    with get_cursor() as (_, cur):
        cur.execute(
            """
            INSERT INTO sync_log (sync_start, sync_end, tickets_processed, actions_inserted, status, error_message)
            VALUES (%s,%s,%s,%s,%s,%s);
            """,
            (sync_start, sync_end, tickets_processed, actions_inserted, status, error_message),
        )


def get_last_sync_end() -> str | None:
    with get_cursor() as (_, cur):
        cur.execute("SELECT sync_end FROM sync_log WHERE status='success' ORDER BY id DESC LIMIT 1;")
        row = cur.fetchone()
        return row[0].isoformat() if row and row[0] else None


def query_summary(date_from: str, date_to: str):
    ex = _analytics_excluded_where()
    with get_cursor(dict_cursor=True) as (_, cur):
        cur.execute(
            f"""
            SELECT
                COALESCE(agent_name, 'Unknown') AS agent_name,
                SUM(CASE WHEN action_type='reply' THEN 1 ELSE 0 END) AS reply,
                SUM(CASE WHEN action_type='internal_note' THEN 1 ELSE 0 END) AS internal_note,
                SUM(CASE WHEN action_type='comment' THEN 1 ELSE 0 END) AS comment,
                SUM(CASE WHEN action_type='handover' THEN 1 ELSE 0 END) AS handover,
                SUM(CASE WHEN action_type='status_change' THEN 1 ELSE 0 END) AS status_change,
                COUNT(*) AS total
            FROM agent_actions
            WHERE action_timestamp >= %s::timestamptz
              AND action_timestamp < %s::timestamptz
              {ex}
            GROUP BY COALESCE(agent_name, 'Unknown')
            ORDER BY total DESC;
            """,
            (date_from, date_to),
        )
        return [dict(r) for r in cur.fetchall()]


def query_timeline(date_from: str, date_to: str, granularity: str):
    if granularity not in {"day", "week"}:
        raise ValueError("granularity must be 'day' or 'week'")
    trunc = "day" if granularity == "day" else "week"
    tz = _report_timezone_sql()
    ex = _analytics_excluded_where()
    with get_cursor(dict_cursor=True) as (_, cur):
        cur.execute(
            f"""
            SELECT
                date_trunc('{trunc}', action_timestamp AT TIME ZONE '{tz}') AS bucket_start,
                COALESCE(agent_name, 'Unknown') AS agent_name,
                COUNT(*) AS total_actions
            FROM agent_actions
            WHERE action_timestamp >= %s::timestamptz
              AND action_timestamp < %s::timestamptz
              {ex}
            GROUP BY bucket_start, COALESCE(agent_name, 'Unknown')
            ORDER BY bucket_start ASC, total_actions DESC;
            """,
            (date_from, date_to),
        )
        rows = []
        for r in cur.fetchall():
            rows.append(
                {
                    "bucket_start": r["bucket_start"].isoformat(),
                    "agent_name": r["agent_name"],
                    "total_actions": r["total_actions"],
                }
            )
        return rows


def query_actions(
    date_from: str,
    date_to: str,
    agent_id: str | None,
    action_type: str | None,
    page: int,
    page_size: int,
):
    offset = (page - 1) * page_size
    ex = _analytics_excluded_where()
    with get_cursor(dict_cursor=True) as (_, cur):
        where = [
            "action_timestamp >= %(date_from)s::timestamptz",
            "action_timestamp < %(date_to)s::timestamptz",
        ]
        params: dict[str, Any] = {
            "date_from": date_from,
            "date_to": date_to,
            "limit": page_size,
            "offset": offset,
        }
        if agent_id:
            where.append("agent_id = %(agent_id)s")
            params["agent_id"] = agent_id
        if action_type:
            where.append("action_type = %(action_type)s")
            params["action_type"] = action_type

        where_sql = " AND ".join(where) + (ex if ex else "")
        cur.execute(f"SELECT COUNT(*) AS total FROM agent_actions WHERE {where_sql};", params)
        total = int(cur.fetchone()["total"])
        cur.execute(
            f"""
            SELECT
                id, ticket_id, ticket_number, ticket_subject, agent_id, agent_name,
                action_type, action_timestamp, from_value, to_value, department_id
            FROM agent_actions
            WHERE {where_sql}
            ORDER BY action_timestamp DESC
            LIMIT %(limit)s OFFSET %(offset)s;
            """,
            params,
        )
        items = []
        for r in cur.fetchall():
            row = dict(r)
            row["action_timestamp"] = row["action_timestamp"].isoformat()
            items.append(row)
        return {"total": total, "page": page, "page_size": page_size, "items": items}


def query_agents():
    ex = _analytics_excluded_where()
    with get_cursor(dict_cursor=True) as (_, cur):
        cur.execute(
            f"""
            SELECT DISTINCT agent_id, COALESCE(agent_name, 'Unknown') AS agent_name
            FROM agent_actions
            WHERE 1=1 {ex}
            ORDER BY agent_name ASC;
            """
        )
        return [dict(r) for r in cur.fetchall()]


def query_kpis(date_from: str, date_to: str):
    ex = _analytics_excluded_where()
    with get_cursor(dict_cursor=True) as (_, cur):
        cur.execute(
            f"""
            SELECT
                (SELECT COUNT(*) FROM tickets_snapshot
                  WHERE created_time >= %(date_from)s::timestamptz
                    AND created_time < %(date_to)s::timestamptz) AS incoming_tickets,
                (SELECT COUNT(*) FROM tickets_snapshot
                  WHERE modified_time >= %(date_from)s::timestamptz
                    AND modified_time < %(date_to)s::timestamptz) AS modified_tickets,
                (SELECT COUNT(DISTINCT ticket_id) FROM agent_actions
                  WHERE action_timestamp >= %(date_from)s::timestamptz
                    AND action_timestamp < %(date_to)s::timestamptz {ex}) AS touched_tickets,
                (SELECT COUNT(*) FROM agent_actions
                  WHERE action_timestamp >= %(date_from)s::timestamptz
                    AND action_timestamp < %(date_to)s::timestamptz {ex}) AS total_actions;
            """,
            {"date_from": date_from, "date_to": date_to},
        )
        row = cur.fetchone() or {}
        return {
            "incoming_tickets": int(row.get("incoming_tickets") or 0),
            "modified_tickets": int(row.get("modified_tickets") or 0),
            "touched_tickets": int(row.get("touched_tickets") or 0),
            "total_actions": int(row.get("total_actions") or 0),
        }


def query_sync_status(limit: int = 5):
    with get_cursor(dict_cursor=True) as (_, cur):
        cur.execute(
            """
            SELECT id, sync_start, sync_end, tickets_processed, actions_inserted, status, error_message
            FROM sync_log
            ORDER BY id DESC
            LIMIT %s;
            """,
            (limit,),
        )
        rows = []
        for r in cur.fetchall():
            row = dict(r)
            row["sync_start"] = row["sync_start"].isoformat()
            row["sync_end"] = row["sync_end"].isoformat()
            rows.append(row)
        return rows


# ---------- Telegram subscriber + alert helpers ----------


def add_telegram_subscriber(*, chat_id: int, username: str = "", first_name: str = "") -> None:
    with get_cursor() as (_, cur):
        cur.execute(
            """
            INSERT INTO telegram_subscribers (chat_id, username, first_name)
            VALUES (%s, %s, %s)
            ON CONFLICT (chat_id) DO UPDATE SET
                username = EXCLUDED.username,
                first_name = EXCLUDED.first_name;
            """,
            (chat_id, username or None, first_name or None),
        )


def remove_telegram_subscriber(chat_id: int) -> None:
    with get_cursor() as (_, cur):
        cur.execute("DELETE FROM telegram_subscribers WHERE chat_id = %s;", (chat_id,))


def list_telegram_subscribers() -> list[int]:
    with get_cursor() as (_, cur):
        cur.execute("SELECT chat_id FROM telegram_subscribers ORDER BY subscribed_at;")
        return [int(r[0]) for r in cur.fetchall()]


def seen_alert_recently(alert_key: str, within_hours: int) -> bool:
    with get_cursor() as (_, cur):
        cur.execute(
            "SELECT last_sent_at FROM telegram_alerts_sent WHERE alert_key = %s;",
            (alert_key,),
        )
        row = cur.fetchone()
        if not row or not row[0]:
            return False
        import datetime as _dt
        delta = _dt.datetime.now(_dt.timezone.utc) - row[0]
        return delta.total_seconds() < within_hours * 3600


def mark_alert_sent(alert_key: str) -> None:
    with get_cursor() as (_, cur):
        cur.execute(
            """
            INSERT INTO telegram_alerts_sent (alert_key, last_sent_at)
            VALUES (%s, now())
            ON CONFLICT (alert_key) DO UPDATE SET last_sent_at = now();
            """,
            (alert_key,),
        )


def add_callback_promise(*, ticket_id: str, ticket_number: str, subject: str, promised_at) -> bool:
    """Returns True if a new promise was inserted (not a duplicate)."""
    with get_cursor() as (_, cur):
        cur.execute(
            """
            INSERT INTO telegram_callback_promises (ticket_id, ticket_number, subject, promised_at)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (ticket_id, promised_at) DO NOTHING;
            """,
            (ticket_id, ticket_number or None, subject or None, promised_at),
        )
        return cur.rowcount > 0


def due_callback_promises(*, window_minutes: int = 5, include_future: bool = False) -> list[dict]:
    """
    By default returns promises whose time is within `window_minutes` past or future
    AND not yet sent. Set include_future=True to list everything pending in the next 24h.
    """
    with get_cursor(dict_cursor=True) as (_, cur):
        if include_future:
            cur.execute(
                """
                SELECT id, ticket_id, ticket_number, subject, promised_at
                FROM telegram_callback_promises
                WHERE sent_at IS NULL
                  AND promised_at >= now() - make_interval(mins => %s)
                  AND promised_at <= now() + make_interval(mins => %s)
                ORDER BY promised_at;
                """,
                (window_minutes, window_minutes),
            )
        else:
            cur.execute(
                """
                SELECT id, ticket_id, ticket_number, subject, promised_at
                FROM telegram_callback_promises
                WHERE sent_at IS NULL
                  AND promised_at <= now() + make_interval(mins => %s)
                  AND promised_at >= now() - INTERVAL '60 minutes'
                ORDER BY promised_at;
                """,
                (window_minutes,),
            )
        return [dict(r) for r in cur.fetchall()]


def mark_callback_sent(promise_id: int) -> None:
    with get_cursor() as (_, cur):
        cur.execute(
            "UPDATE telegram_callback_promises SET sent_at = now() WHERE id = %s;",
            (promise_id,),
        )


def telegram_update_offset() -> int | None:
    with get_cursor() as (_, cur):
        cur.execute("SELECT value FROM telegram_state WHERE key = 'last_update_id';")
        row = cur.fetchone()
        if not row:
            return None
        try:
            return int(row[0])
        except (TypeError, ValueError):
            return None


def record_telegram_update_offset(offset: int) -> None:
    with get_cursor() as (_, cur):
        cur.execute(
            """
            INSERT INTO telegram_state (key, value)
            VALUES ('last_update_id', %s)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
            """,
            (str(offset),),
        )
