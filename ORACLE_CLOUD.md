# Oracle Cloud Always Free (ARM) — run this stack 24/7

Oracle offers **Always Free** ARM VMs (Ampere). If your account is approved, you can run Docker **without a monthly VPS bill**. Rules and availability can change—check [Oracle’s Always Free page](https://www.oracle.com/cloud/free/) for current terms.

This guide assumes you can open a terminal (SSH) and paste commands. Total time: **about 30–60 minutes** the first time.

---

## 1. Create an Oracle Cloud account

1. Go to [https://www.oracle.com/cloud/free/](https://www.oracle.com/cloud/free/) and sign up.
2. Complete verification (email, phone, payment method—many regions require a card for identity; **Always Free** resources should not incur charges if you stay within free limits; read Oracle’s terms).
3. Pick a **home region** (closest to you). You cannot move regions later without recreating resources.

---

## 2. Create a network (VCN)

1. In the Oracle Console: **Networking → Virtual cloud networks**.
2. **Create VCN** → use the **“Create VCN with Internet Connectivity”** wizard (or equivalent) so you get:
   - a VCN
   - public subnets
   - an Internet Gateway
3. Note the **public subnet** you will use for the VM.

---

## 3. Security rules (firewall)

So you can SSH and use the web UI:

1. **Networking → Virtual cloud networks** → your VCN → **Security Lists** → default security list → **Ingress Rules**.
2. Add rules (source `0.0.0.0/0` unless you lock to your IP):

| Source | IP protocol | Destination port | Description        |
|--------|-------------|------------------|--------------------|
| 0.0.0.0/0 | TCP      | 22               | SSH                |
| 0.0.0.0/0 | TCP      | 80               | HTTP (dashboard)   |
| 0.0.0.0/0 | TCP      | 3000             | Metabase (optional)|
| 0.0.0.0/0 | TCP      | 8000             | API (optional)     |

For production, restrict **22** to **your home IP** only.

---

## 4. Create an SSH key (on your Mac)

```bash
ssh-keygen -t ed25519 -f ~/.ssh/oracle_desk_analytics -N ""
cat ~/.ssh/oracle_desk_analytics.pub
```

Copy the **`.pub`** line—you will paste it into Oracle when creating the instance.

---

## 5. Create the ARM instance

1. **Compute → Instances → Create instance**.
2. **Image:** Ubuntu 22.04 (or 24.04) **aarch64**.
3. **Shape:** Ampere **VM.Standard.A1.Flex** (Always Free allows up to **4 OCPUs / 24 GB RAM** total across A1 instances in the tenancy—often people use **1 OCPU, 6 GB RAM** for one small VM).
4. **Networking:** your VCN + **public subnet**, assign a **public IPv4**.
5. **SSH keys:** paste your **public** key.
6. Create. Wait until state is **Running** and copy the **public IP**.

---

## 6. Connect by SSH

```bash
ssh -i ~/.ssh/oracle_desk_analytics ubuntu@YOUR_PUBLIC_IP
```

(Username may be `ubuntu` or `opc` depending on image—Oracle shows it on the instance page.)

---

## 7. Install Docker (on the VM)

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "${VERSION_CODENAME:-jammy}") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo usermod -aG docker "$USER"
```

Log out and SSH back in so `docker` works without `sudo`.

Test:

```bash
docker run --rm hello-world
```

---

## 8. Copy the project and `.env`

On your **Mac** (from the folder that contains `zoho-desk-analytics`):

```bash
scp -i ~/.ssh/oracle_desk_analytics -r zoho-desk-analytics ubuntu@YOUR_PUBLIC_IP:~/
scp -i ~/.ssh/oracle_desk_analytics zoho-desk-analytics/.env ubuntu@YOUR_PUBLIC_IP:~/zoho-desk-analytics/
```

Never commit `.env` to git.

---

## 9. Start the stack

On the **VM**:

```bash
cd ~/zoho-desk-analytics
docker compose up -d --build
```

Check:

```bash
docker compose ps
curl -s http://127.0.0.1:8000/health
```

Open in a browser: `http://YOUR_PUBLIC_IP` (port 80) and Metabase on `:3000` if you opened that port.

---

## 10. HTTPS and domain (optional)

Use **Caddy** or **nginx** with Let’s Encrypt in front of ports 80/443, or Oracle’s load balancer + certificate manager. This is optional for internal use.

---

## 11. Not “burning” Zoho API calls

Calls scale with **how often** sync runs and **how many tickets** fall in each sync window. On the **server**, set in `.env`:

| Variable | Effect |
|----------|--------|
| `ZOHO_SYNC_INTERVAL_MINUTES` | **Main dial.** Default `30`. Try `60` or `120` to **cut scheduled sync count** roughly in half or quarter. Minimum allowed: **15**. |
| `SYNC_OVERLAP_HOURS` | Default `24` is safe. Lower (e.g. `12`) can reduce duplicate work slightly; **too low** risks missing late-updated tickets—increase only if you understand the tradeoff. |
| `SYNC_LOOKBACK_DAYS` | How far back the window can reach; usually leave at `31` unless you know you need less. |

Avoid running **`rebuild_all_actions.py`** unless you need a full history reload—it walks **many** tickets and generates **many** API calls.

The backend logs `[startup] Scheduled Zoho sync every N minute(s)` so you can confirm the interval after a restart:

```bash
docker compose logs backend | head -20
```

---

## Troubleshooting

- **Cannot SSH:** check security list allows TCP 22, correct key, correct user (`ubuntu` vs `opc`).
- **502 / connection refused:** `docker compose ps`, `docker compose logs backend`.
- **Out of memory:** reduce Metabase or run fewer services; A1 1 OCPU / 1 GB is tight—**6 GB** is more comfortable for Postgres + Metabase + backend.
