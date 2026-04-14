# Running 24/7 (fully automated sync)

**Running only on your own computer for now (Mac/Windows):** see **`LOCAL_PC.md`**.

The app syncs Zoho on a **schedule** (default **every 30 minutes**, configurable via `ZOHO_SYNC_INTERVAL_MINUTES` in `.env`) while the **backend** process is running. Your laptop is only “always on” if the lid is open and it does not sleep—so for **true** automation without your PC, run the same Docker stack on a **small cloud server** that stays up.

**Step-by-step (Oracle Cloud Always Free ARM):** see **`ORACLE_CLOUD.md`**.

**Using GitHub for code / deploy automation (not as a replacement for a server):** see **`GITHUB.md`**.

## What you need

1. A **VPS** (virtual server) from any provider—examples: Oracle Always Free ARM, DigitalOcean Droplet, Linode, Vultr, AWS Lightsail, Hetzner. A **1 GB RAM** Ubuntu machine is tight; **2 GB+** is more comfortable with Metabase.
2. Your **`.env`** file (Zoho credentials and `DATABASE_URL`)—copy it to the server **securely**; never commit it to git.

## One-time server setup (high level)

1. Create an Ubuntu 22.04 (or similar) VM and note its **public IP**.
2. Install Docker using the official docs: [https://docs.docker.com/engine/install/ubuntu/](https://docs.docker.com/engine/install/ubuntu/)
3. Install Docker Compose plugin (often bundled as `docker compose`).
4. Copy this project folder to the server (`git clone` or `scp`).
5. Copy `.env` to the project root on the server.
6. **On the server only**, set a strong Postgres password in `docker-compose.yml` (`POSTGRES_PASSWORD`) and the same password inside `DATABASE_URL` in `.env`.
7. From the project folder run:

```bash
docker compose up -d --build
```

8. Open **only** the ports you need in the cloud firewall (e.g. **80** for the dashboard, **3000** for Metabase if you use it, **8000** only if you need the API directly). **Do not** expose Postgres (5432) to the whole internet.

Containers use `restart: unless-stopped`, so they come back after the VM reboots.

## Local development (optional)

Postgres is **not** published to your Mac by default (safer). To use a desktop SQL client on **localhost:5432**:

```bash
cp docker-compose.override.example.yml docker-compose.override.yml
docker compose up -d
```

(`docker-compose.override.yml` is gitignored.)

## After deployment

- **Dashboard:** `http://YOUR_SERVER_IP` (port 80)
- **Metabase:** `http://YOUR_SERVER_IP:3000` (if you open that port)
- Sync runs automatically; check **`GET /api/sync/status`** on port 8000 if needed.

For HTTPS and a domain name, put **Caddy** or **nginx** in front with a free Let’s Encrypt certificate—your host’s docs usually walk through that.
