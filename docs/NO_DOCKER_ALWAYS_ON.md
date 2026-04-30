# Run the Zoho assistant always-on without Docker

Use this when you want the Telegram bot to run all the time without typing commands. The app runs as a normal Python service managed by `systemd`.

## What this gives you

After setup, the server starts the backend automatically on boot and restarts it if it crashes. You use Telegram day to day:

```text
/help
/status
/remind tomorrow 11 call customer
/draft ZOHO_TICKET_ID
```

## Requirements

- Ubuntu/Debian server or PC that stays on
- Python 3.11+
- PostgreSQL 15+ running locally or remotely
- Your `.env` secrets configured

If you do not already have PostgreSQL installed:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip postgresql postgresql-contrib git
```

## 1. Create a service user

```bash
sudo useradd --system --create-home --shell /usr/sbin/nologin zohoassistant
```

## 2. Put the repo on the machine

Recommended path:

```bash
sudo mkdir -p /opt/zoho-desk-analytics
sudo chown -R "$USER":"$USER" /opt/zoho-desk-analytics
git clone <YOUR_REPO_URL> /opt/zoho-desk-analytics
cd /opt/zoho-desk-analytics
```

If the repo is already there, just `cd` into it and pull the latest branch.

## 3. Create the Python virtualenv

```bash
cd /opt/zoho-desk-analytics
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r backend/requirements.txt
```

## 4. Create PostgreSQL database

For local PostgreSQL:

```bash
sudo -u postgres psql
```

Inside `psql`:

```sql
CREATE USER zoho_analytics WITH PASSWORD 'choose-a-strong-password';
CREATE DATABASE zoho_analytics OWNER zoho_analytics;
\q
```

Your `DATABASE_URL` will look like:

```env
DATABASE_URL=postgresql://zoho_analytics:choose-a-strong-password@localhost:5432/zoho_analytics
```

## 5. Create `.env`

```bash
cd /opt/zoho-desk-analytics
cp .env.example .env
nano .env
```

Fill at least:

```env
DATABASE_URL=postgresql://zoho_analytics:choose-a-strong-password@localhost:5432/zoho_analytics
ZOHO_CLIENT_ID=...
ZOHO_CLIENT_SECRET=...
ZOHO_REFRESH_TOKEN=...
ZOHO_ORG_ID=...
AI_API_KEY=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=156127941
TELEGRAM_BOT_POLLING_ENABLED=1
ASSISTANT_REQUIRE_ALLOWED_ASSIGNEE=1
ASSISTANT_ALLOWED_ASSIGNEE_NAMES=Kasra
```

Keep `.env` private:

```bash
chmod 600 .env
```

## 6. Install the systemd service

```bash
sudo cp deploy/systemd/zoho-assistant.service /etc/systemd/system/zoho-assistant.service
sudo chown -R zohoassistant:zohoassistant /opt/zoho-desk-analytics
sudo systemctl daemon-reload
sudo systemctl enable zoho-assistant
sudo systemctl start zoho-assistant
```

## 7. Check it

```bash
sudo systemctl status zoho-assistant --no-pager
curl http://localhost:8000/health
curl http://localhost:8000/api/assistant/status
```

Logs:

```bash
sudo journalctl -u zoho-assistant -f
```

## 8. Use Telegram

In Telegram, message `@roomvuhelp_bot`:

```text
/help
/status
/remind tomorrow 11 call customer
```

For drafts:

```text
/draft ZOHO_TICKET_ID
```

Drafts stay Kasra-only by default.

## Updating later

```bash
cd /opt/zoho-desk-analytics
sudo systemctl stop zoho-assistant
git pull
.venv/bin/pip install -r backend/requirements.txt
sudo chown -R zohoassistant:zohoassistant /opt/zoho-desk-analytics
sudo systemctl start zoho-assistant
```

## If you do not want to expose the backend publicly

You do not need to expose port 8000 to the internet for Telegram polling. The backend calls Telegram outbound, so it can stay private behind your firewall.
