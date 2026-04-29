# Virtuals Whale Radar Deployment Guide

## 0. Current Aliyun Server Type

The current production server for `virtuals.club` is **Alibaba Cloud Simple Application Server** (`swas-open`), not ECS.

Use the project helper CLI first:

```bash
scripts/ops/aliyun_swas_server.sh instance
scripts/ops/aliyun_swas_server.sh services
scripts/ops/aliyun_swas_server.sh ssh-check
```

Default production target:

- Product line: `aliyun swas-open`
- Region: `cn-hongkong`
- Domain: `virtuals.club`
- Public IP: `47.243.172.165`
- App dir: `/opt/virtuals-whale-radar`
- Current production systemd prefix: `vwr`
- Current public frontend/API domain: `https://virtuals.club`

Production status checks:

```bash
ssh -i /Users/myandong/.ssh/id_ed25519 root@47.243.172.165
systemctl is-active vwr@writer vwr@realtime vwr@backfill vwr-signalhub nginx
curl -fsS http://127.0.0.1:8080/health
curl -fsS http://127.0.0.1:8000/healthz
```

Do **not** start production lookup with ECS commands such as:

```bash
aliyun ecs DescribeInstances ...
```

Those commands query the wrong Aliyun product line for this project.

This guide covers two production patterns:

1. Split-domain (recommended):
   - Frontend: `https://app.example.com`
   - API: `https://api.example.com`
2. Same-domain with API prefix:
   - Frontend: `https://app.example.com`
   - API via reverse proxy path: `https://app.example.com/api/*`

The project now supports:
- Configurable frontend API base (meta tag `vpulse-api-base` in `dashboard.html`)
- Configurable backend CORS allowlist (`CORS_ALLOW_ORIGINS` in `config.json`)

## 0. One-click installer (Ubuntu 22.04, same-domain mode)

For domain `launch.licheng.website` style deployment:

```bash
cd /opt/virtuals-whale-radar
chmod +x deploy/install_ubuntu22_oneclick.sh
DOMAIN=launch.licheng.website \
LETSENCRYPT_EMAIL=you@example.com \
WS_RPC_URL=wss://... \
HTTP_RPC_URL=https://... \
BACKFILL_HTTP_RPC_URL=https://... \
bash deploy/install_ubuntu22_oneclick.sh
```

The script will:
- install system packages and Python deps
- generate/update `config.json`
- set frontend API base to `/api`
- install `systemd` services (`writer/realtime/backfill`)
- install Nginx same-domain reverse proxy
- try HTTPS via Certbot (if `LETSENCRYPT_EMAIL` provided)

## 1. Server prerequisites

Example target: Ubuntu 22.04+

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nginx
```

Open firewall ports (if enabled):
- `22` (SSH)
- `80`, `443` (HTTP/HTTPS)

## 2. Project layout on server

Recommended paths:
- App code: `/opt/virtuals-whale-radar`
- Frontend static files: `/var/www/virtuals-whale-radar`

```bash
sudo mkdir -p /opt/virtuals-whale-radar /var/www/virtuals-whale-radar
sudo chown -R $USER:$USER /opt/virtuals-whale-radar /var/www/virtuals-whale-radar
```

Upload or clone this repository into `/opt/virtuals-whale-radar`.
If you already use legacy paths (`/opt/vpulse`, `/var/www/vpulse`), you can keep them.

## 3. Python environment

```bash
cd /opt/virtuals-whale-radar
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## 4. Backend config (`/opt/virtuals-whale-radar/config.json`)

Start from template:

```bash
cp /opt/virtuals-whale-radar/config.example.json /opt/virtuals-whale-radar/config.json
```

Edit required RPC/project values first, then set deployment-related fields:

- Split-domain:
  - `API_HOST`: `"127.0.0.1"`
  - `API_PORT`: `8080`
  - `CORS_ALLOW_ORIGINS`: `["https://app.example.com"]`
- Same-domain with `/api` reverse proxy:
  - `CORS_ALLOW_ORIGINS`: `[]` (same-origin, no CORS needed)

## 5. Backend services (systemd)

Use the template unit:
- `deploy/systemd/vpulse@.service`

Install:

```bash
SERVICE_PREFIX=virtuals-whale-radar
sudo cp /opt/virtuals-whale-radar/deploy/systemd/vpulse@.service /etc/systemd/system/${SERVICE_PREFIX}@.service
sudo systemctl daemon-reload
sudo systemctl enable --now ${SERVICE_PREFIX}@writer ${SERVICE_PREFIX}@realtime ${SERVICE_PREFIX}@backfill
```

Check status/logs:

```bash
SERVICE_PREFIX=virtuals-whale-radar
sudo systemctl status ${SERVICE_PREFIX}@writer
sudo systemctl status ${SERVICE_PREFIX}@realtime
sudo systemctl status ${SERVICE_PREFIX}@backfill
sudo journalctl -u ${SERVICE_PREFIX}@writer -f
```

## 6. Frontend files

Copy frontend assets:

```bash
cp /opt/virtuals-whale-radar/dashboard.html /var/www/virtuals-whale-radar/dashboard.html
cp /opt/virtuals-whale-radar/favicon-vpulse.svg /var/www/virtuals-whale-radar/favicon-vpulse.svg
mkdir -p /var/www/virtuals-whale-radar/favicon
cp -r /opt/virtuals-whale-radar/favicon/. /var/www/virtuals-whale-radar/favicon/
cp /opt/virtuals-whale-radar/favicon/favicon.ico /var/www/virtuals-whale-radar/favicon.ico
```

Set API base in `dashboard.html` by editing:

```html
<meta name="vpulse-api-base" content="" />
```

Use:
- Split-domain: `content="https://api.example.com"`
- Same-domain `/api`: `content="/api"`
- Full same-origin direct API: keep empty `content=""`

## 7. Nginx configuration

Choose one pattern.

### Option A: Split-domain

Use:
- `deploy/nginx/vpulse-split-app.conf`
- `deploy/nginx/vpulse-split-api.conf`

Install:

```bash
sudo cp /opt/virtuals-whale-radar/deploy/nginx/vpulse-split-app.conf /etc/nginx/sites-available/vpulse-split-app.conf
sudo cp /opt/virtuals-whale-radar/deploy/nginx/vpulse-split-api.conf /etc/nginx/sites-available/vpulse-split-api.conf
sudo ln -s /etc/nginx/sites-available/vpulse-split-app.conf /etc/nginx/sites-enabled/
sudo ln -s /etc/nginx/sites-available/vpulse-split-api.conf /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### Option B: Same-domain with `/api`

Use:
- `deploy/nginx/vpulse-same-domain.conf`

Install:

```bash
sudo cp /opt/virtuals-whale-radar/deploy/nginx/vpulse-same-domain.conf /etc/nginx/sites-available/vpulse-same-domain.conf
sudo ln -s /etc/nginx/sites-available/vpulse-same-domain.conf /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### Option C: `launch.licheng.website` with dedicated `launch` site file

Use:
- `deploy/nginx/launch-http-bootstrap.conf` (first-time cert issuance)
- `deploy/nginx/launch.conf`

Install (replace existing `v-pulse` or `vpulse` enabled site if present):

```bash
sudo cp /opt/virtuals-whale-radar/deploy/nginx/launch-http-bootstrap.conf /etc/nginx/sites-available/launch
sudo rm -f /etc/nginx/sites-enabled/v-pulse /etc/nginx/sites-enabled/v-pulse.conf
sudo rm -f /etc/nginx/sites-enabled/vpulse /etc/nginx/sites-enabled/vpulse.conf
sudo rm -f /etc/nginx/sites-enabled/vpulse-same-domain.conf
sudo ln -sfn /etc/nginx/sites-available/launch /etc/nginx/sites-enabled/launch
sudo nginx -t
sudo systemctl reload nginx
sudo certbot --nginx -d launch.licheng.website
sudo cp /opt/virtuals-whale-radar/deploy/nginx/launch.conf /etc/nginx/sites-available/launch
sudo nginx -t
sudo systemctl reload nginx
```

## 8. HTTPS (recommended)

With Certbot (example):

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d app.example.com
sudo certbot --nginx -d api.example.com
```

For same-domain, only request the single domain certificate.

## 9. Validation checklist

1. API health:
   - Split-domain: `curl https://api.example.com/health`
   - Same-domain: `curl https://app.example.com/api/health`
2. UI opens:
   - `https://app.example.com/`
3. `writer/realtime/backfill` all active in systemd.
4. UI can load `/meta`, `/minutes`, `/leaderboard`, `/project-tax`.

## 10. Upgrade process

### 10.1 One-click update script (recommended)

Use:

```bash
cd /opt/virtuals-whale-radar
chmod +x deploy/update_server_oneclick.sh
bash deploy/update_server_oneclick.sh
```

Common options:

```bash
# Pull from a specific branch
BRANCH=main bash deploy/update_server_oneclick.sh

# Override service prefix for existing old installations
SERVICE_PREFIX=vpulse bash deploy/update_server_oneclick.sh

# Keep same-domain /api in dashboard meta after each pull
FRONTEND_API_BASE=/api bash deploy/update_server_oneclick.sh

# Skip pip install when Python deps did not change
SKIP_PIP=1 bash deploy/update_server_oneclick.sh
```

Default actions:
1. `git pull --rebase --autostash`
2. update Python deps from `requirements.txt`
3. publish `dashboard.html` and `favicon-vpulse.svg` to the detected web root
4. restart `${SERVICE_PREFIX}@writer`, `${SERVICE_PREFIX}@realtime`, `${SERVICE_PREFIX}@backfill`
5. `nginx -t` and reload nginx

### 10.2 Migrate systemd service names (legacy `vpulse` -> new prefix)

```bash
cd /opt/virtuals-whale-radar
chmod +x deploy/migrate_service_prefix.sh
OLD_PREFIX=vpulse NEW_PREFIX=virtuals-whale-radar bash deploy/migrate_service_prefix.sh
```

Verify:

```bash
systemctl is-active virtuals-whale-radar@writer virtuals-whale-radar@realtime virtuals-whale-radar@backfill
systemctl is-enabled virtuals-whale-radar@writer virtuals-whale-radar@realtime virtuals-whale-radar@backfill
```

### 10.3 Manual fallback

```bash
cd /opt/virtuals-whale-radar
SERVICE_PREFIX=virtuals-whale-radar   # legacy deployments may still use: vpulse
WEB_DIR=/var/www/virtuals-whale-radar # legacy deployments may still use: /var/www/vpulse
git pull
source .venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart ${SERVICE_PREFIX}@writer ${SERVICE_PREFIX}@realtime ${SERVICE_PREFIX}@backfill
cp /opt/virtuals-whale-radar/dashboard.html ${WEB_DIR}/dashboard.html
mkdir -p ${WEB_DIR}/favicon
cp -r /opt/virtuals-whale-radar/favicon/. ${WEB_DIR}/favicon/
cp /opt/virtuals-whale-radar/favicon/favicon.ico ${WEB_DIR}/favicon.ico
sudo systemctl reload nginx
```
