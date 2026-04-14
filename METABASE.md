# Metabase: people reports (Pacific time, no TechProduct Team)

## Where to locate Metabase and your reports

| What | Where |
|------|--------|
| **Metabase in the browser** | **`http://localhost:3000`** while Docker Compose is running (`metabase` service in `docker-compose.yml`). On a server, use **`http://YOUR_SERVER_IP:3000`** if port 3000 is open in the firewall. |
| **Postgres data (views)** | Not inside Metabase’s UI as files — metrics come from the **`zoho_analytics`** database on the **`db`** container. Metabase only **reads** those views after you add the connection (below). |
| **Saved questions & dashboards you create** | **Inside Metabase only:** **Home** → **Browse all items** (or your **Collections**), or **Dashboards** in the left sidebar. This repo does **not** contain Metabase JSON exports; you build questions once in the UI and they persist in Metabase’s own database (Docker volume **`metabase_data`**). |
| **The SQL definitions of the metrics** | In **this repo:** `backend/db.py` → function **`_create_reporting_views_pt`** (views named `v_reporting_agents_*_pt`). Restart the **backend** after changing reporting timezone or exclusions so views refresh. |

**Quick path to the data in Metabase:** **+ New** → **Question** → **Pick a database** → choose **`zoho_analytics`** → **Pick a table** → select **`v_reporting_agents_daily_pt`** (or another `v_reporting_*` view below).

---

## What changed in Postgres

After restarting the **backend** once, these views exist:

| View | Use |
|------|-----|
| **`v_reporting_agents_daily_pt`** | One row per **calendar day (US Pacific)** × **agent** — replies, comments, handovers, etc. |
| **`v_reporting_agents_weekly_pt`** | Same metrics, **week** buckets (Monday-start ISO weeks). |
| **`v_reporting_agents_monthly_pt`** | Same metrics, **month** buckets. |
| **`v_reporting_agents_actions_daily_pt`** | **Bar / comparison charts**: `action_type` × agent × day. |

**TechProduct Team** (and any IDs in `ANALYTICS_EXCLUDED_AGENT_IDS`) are **not** in these views. Raw data is unchanged; only reporting filters them out.

Older names **`v_manager_agent_performance_*`** still work: they are aliases with column **`bucket_start`** = Pacific date (same as `report_date_pt` / week / month starts).

Legacy views like `v_agent_performance_daily` (UTC, no exclusions) are **deprecated** — ignore or delete old Metabase questions that used them.

---

## Connect Metabase to Postgres

1. Open Metabase (e.g. `http://localhost:3000`).
2. **Admin → Databases → Add database → PostgreSQL.**
3. **Host:** `db` (from Metabase container on the same Docker network).  
   **Not** `localhost` from inside the Metabase container.
4. **Port:** `5432`  
5. **Database name:** `zoho_analytics`  
6. **User / password:** match `docker-compose.yml` (`postgres` / `postgres` unless you changed them).
7. Save, then **Sync database schema** (Metabase may do this automatically).

---

## Clean up old questions / dashboards

Metabase stores saved questions **inside Metabase**, not in this repo—we cannot delete them from code.

1. **Browse data → your database** and open **Our analytics** or **Browse all items**.
2. Delete or archive questions that point to deprecated views (`v_agent_performance_*` UTC duplicates, etc.).
3. Build new questions from **`v_reporting_agents_*_pt`** only.

---

## Suggested questions (per person / compare)

### Table — last 30 days by agent (day grain)

1. **New → Question → Pick `v_reporting_agents_daily_pt`.**
2. **Filter:** `report_date_pt` → **Previous 30 days** (or a custom range).
3. **Visualization:** **Table**.  
4. Columns: `agent_name`, `report_date_pt`, `replies`, `comments`, `customer_responses`, `handovers`, `status_changes`, `total_actions`.
5. **Optional:** add **agent_name** filter on the dashboard so you pick one person.

Repeat for **`v_reporting_agents_weekly_pt`** (`week_start_pt`) and **`v_reporting_agents_monthly_pt`** (`month_start_pt`).

### Chart — compare agents (actions per day)

1. **New question → `v_reporting_agents_actions_daily_pt`.**
2. **Filter** date range on `report_date_pt`.
3. **Visualization:** **Bar** or **Line**.
4. **X-axis:** `report_date_pt`  
5. **Y-axis:** Sum of `action_count`  
6. **Series / Breakout:** `agent_name` (or `action_type` for a breakdown by type).

### Dashboard

1. **New dashboard** → add the three table questions + one chart.
2. Add a **single date filter** and wire it to each card (Metabase “Click behavior” / dashboard filters).

---

## Timezone note

`ANALYTICS_REPORT_TIMEZONE` (default `America/Los_Angeles`) is **Pacific Time** (PST in winter, PDT in summer). Weeks use PostgreSQL **ISO weeks** (Monday week start).

Restart the backend after changing `.env` so views and the API use the new zone and exclusions:

```bash
docker compose up -d --build backend
```
