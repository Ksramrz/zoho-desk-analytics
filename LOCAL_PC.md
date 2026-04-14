# Run on your own PC (Mac or Windows)

This is the **simplest** way to use the stack: everything stays on your machine. No Oracle or paid VPS.

## What you accept

- **Sync and dashboards only run while the PC is on** and **Docker is running**.
- If the computer **sleeps**, **shuts down**, or Docker stops, syncing pauses until you start again.

That is fine for “for now”; you can move the same project to a cloud VM later.

---

## 1) Install Docker

- **Mac / Windows:** install **[Docker Desktop](https://www.docker.com/products/docker-desktop/)** and open it. Wait until it says Docker is running (whale icon in the menu bar / system tray).
- **Linux:** install Docker Engine + Compose plugin from Docker’s docs.

---

## 2) Configure `.env`

From the `zoho-desk-analytics` folder:

```bash
cp .env.example .env
```

Edit `.env` and fill in Zoho keys and `ZOHO_ORG_ID` (see **`README.md`**). The default `DATABASE_URL` is correct for Docker Compose.

---

## 3) Start the stack

In a terminal, from the **`zoho-desk-analytics`** folder:

```bash
docker compose up -d --build
```

`-d` runs containers in the background so you can close the terminal.

---

## 4) Open in the browser

| What            | URL |
|-----------------|-----|
| Dashboard       | [http://localhost](http://localhost) |
| API docs        | [http://localhost:8000/docs](http://localhost:8000/docs) |
| Metabase        | [http://localhost:3000](http://localhost:3000) |

The backend **syncs Zoho on a timer** (default every **30** minutes). Check logs:

```bash
docker compose logs -f backend
```

You should see a line like: `Scheduled Zoho sync every 30 minute(s)`.

---

## 5) Optional: Postgres on `localhost:5432` (TablePlus, DBeaver, etc.)

By default the database is **not** exposed on the host (safer). To connect a desktop SQL client:

```bash
cp docker-compose.override.example.yml docker-compose.override.yml
docker compose up -d
```

---

## 6) Make it less annoying day to day

- **Docker Desktop → Settings → General:** enable **“Start Docker Desktop when you log in”** (wording may vary).
- **Mac:** **System Settings → Battery / Energy** — if on power adapter, consider **preventing sleep** when you want overnight syncs (optional).
- **Fewer Zoho API calls** while the PC runs long hours: in `.env` set e.g. `ZOHO_SYNC_INTERVAL_MINUTES=60` or `120`, then:

  ```bash
  docker compose up -d --build
  ```

---

## 7) Stop or restart

```bash
cd /path/to/zoho-desk-analytics
docker compose down          # stop everything
docker compose up -d         # start again (after reboot, run this if Docker doesn’t auto-start containers)
```

Data is kept in Docker **volumes** (`postgres_data`, `metabase_data`) until you run `docker compose down -v` (that **deletes** DB data—avoid unless you mean it).

---

## 8) When you’re ready for 24/7 in the cloud

Use **`DEPLOYMENT.md`** — same `docker compose` commands on a small Ubuntu server; copy your `.env` there securely.
