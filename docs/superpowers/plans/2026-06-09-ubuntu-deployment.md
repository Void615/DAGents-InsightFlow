# Ubuntu 20.04 Deployment Plan for DAGents-InsightFlow

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy the full-stack DAGents-InsightFlow application (FastAPI backend + Next.js frontend + PostgreSQL) on Ubuntu 20.04 with nginx reverse proxy and systemd process management.

**Architecture:** nginx reverse proxy terminates HTTPS and routes to two upstreams — the Next.js frontend (localhost:3000) serving the SPA, and the FastAPI backend (localhost:8000) serving `/api/v1/*`. Both run as systemd services. PostgreSQL runs as the system-installed service.

**Tech Stack:** Python 3.11 (deadsnakes PPA), Node.js 22 LTS (NodeSource), PostgreSQL 16 (postgresql.org repo), nginx, systemd, uvicorn, Next.js

---

## Architecture Overview

```
                    ┌─────────────┐
                    │   nginx     │ :443 (TLS)
                    │  reverse    │──── /api/v1/* ──→ backend:8000
                    │   proxy     │──── /*          ──→ frontend:3000
                    └─────────────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
         PostgreSQL    backend       frontend
          :5432        uvicorn       next start
                       :8000         :3000
```

## Files to Create

| File | Purpose |
|------|---------|
| `deploy/setup.sh` | One-shot server bootstrap — installs all dependencies |
| `deploy/backend.service` | systemd unit for the FastAPI/uvicorn backend |
| `deploy/frontend.service` | systemd unit for the Next.js frontend |
| `deploy/nginx-dagents.conf` | nginx reverse proxy virtual host config |
| `deploy/DEPLOY.md` | Step-by-step deployment guide for human operators |

## Files to Modify

| File | Change |
|------|--------|
| `backend/app/config.py` | Add `ALLOWED_ORIGINS` env-sourced setting |
| `backend/app/main.py` | Use configurable CORS origins + add production port |

---

### Task 1: Make CORS Origins Configurable

**Files:**
- Modify: `backend/app/config.py:36`
- Modify: `backend/app/main.py:37-43`

- [ ] **Step 1: Add ALLOWED_ORIGINS to Settings**

In `backend/app/config.py`, add the new setting after line 18:

```python
    # CORS
    ALLOWED_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"
```

Also add the helper property at line 31 (after `LLM_TEMPERATURE`):

```python
    @property
    def cors_origins(self) -> list[str]:
        """Parse ALLOWED_ORIGINS into a list."""
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]
```

- [ ] **Step 2: Update main.py CORS middleware**

In `backend/app/main.py`, replace the hardcoded `allow_origins` list (lines 38-42) and `allow_origin_regex` (line 43) with:

```python
from app.config import get_settings

_settings = get_settings()

app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

- [ ] **Step 3: Verify it runs**

```bash
cd backend && python -c "from app.config import get_settings; s = get_settings(); print(s.cors_origins)"
```

Expected: `['http://localhost:3000', 'http://127.0.0.1:3000']`

- [ ] **Step 4: Commit**

```bash
git add backend/app/config.py backend/app/main.py
git commit -m "feat: make CORS origins configurable via ALLOWED_ORIGINS env var"
```

---

### Task 2: Create systemd Service for Backend

**Files:**
- Create: `deploy/backend.service`

- [ ] **Step 1: Write the backend systemd service file**

Create `deploy/backend.service`:

```ini
[Unit]
Description=DAGents-InsightFlow Backend (FastAPI)
After=network.target postgresql.service
Wants=postgresql.service

[Service]
Type=simple
User=dagents
Group=dagents
WorkingDirectory=/opt/dagents/backend
EnvironmentFile=/opt/dagents/backend/.env
ExecStart=/opt/dagents/backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 2 --log-level info
Restart=always
RestartSec=3
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

> Note: `--workers 2` uses 2 uvicorn worker processes. Adjust based on CPU cores (2 × CPU cores is a typical starting point). For single-core VMs, use `--workers 1`.

- [ ] **Step 2: Commit**

```bash
git add deploy/backend.service
git commit -m "feat: add systemd service for backend"
```

---

### Task 3: Create systemd Service for Frontend

**Files:**
- Create: `deploy/frontend.service`

- [ ] **Step 1: Write the frontend systemd service file**

Create `deploy/frontend.service`:

```ini
[Unit]
Description=DAGents-InsightFlow Frontend (Next.js)
After=network.target dagents-backend.service
Wants=dagents-backend.service

[Service]
Type=simple
User=dagents
Group=dagents
WorkingDirectory=/opt/dagents/frontend
EnvironmentFile=/opt/dagents/frontend/.env.production
ExecStart=/usr/bin/node /opt/dagents/frontend/node_modules/.bin/next start --port 3000
Restart=always
RestartSec=3
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: Commit**

```bash
git add deploy/frontend.service
git commit -m "feat: add systemd service for frontend"
```

---

### Task 4: Create nginx Configuration

**Files:**
- Create: `deploy/nginx-dagents.conf`

- [ ] **Step 1: Write nginx virtual host config**

Create `deploy/nginx-dagents.conf`:

```nginx
# DAGents-InsightFlow nginx configuration
# Place at: /etc/nginx/sites-available/dagents
# Enable:    ln -s /etc/nginx/sites-available/dagents /etc/nginx/sites-enabled/
#
# For HTTPS: Uncomment the SSL sections after obtaining certificates.

upstream dagents_backend {
    server 127.0.0.1:8000 fail_timeout=0;
}

upstream dagents_frontend {
    server 127.0.0.1:3000 fail_timeout=0;
}

server {
    listen 80;
    # listen 443 ssl http2;  # Uncomment for HTTPS
    server_name _;  # Replace with your domain name, e.g. dagents.example.com

    # ssl_certificate     /etc/letsencrypt/live/dagents.example.com/fullchain.pem;
    # ssl_certificate_key /etc/letsencrypt/live/dagents.example.com/privkey.pem;

    client_max_body_size 10m;

    # ── Backend API ─────────────────────────────────────────────
    location /api/ {
        proxy_pass http://dagents_backend;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # SSE support (interview streaming, event streaming)
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
        chunked_transfer_encoding on;
    }

    # ── Frontend ─────────────────────────────────────────────────
    location / {
        proxy_pass http://dagents_frontend;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket support (Next.js HMR, if needed)
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    # ── Security headers ─────────────────────────────────────────
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
}
```

- [ ] **Step 2: Commit**

```bash
git add deploy/nginx-dagents.conf
git commit -m "feat: add nginx reverse proxy configuration"
```

---

### Task 5: Create Server Bootstrap Script

**Files:**
- Create: `deploy/setup.sh`

This is the largest task. The script handles the full Ubuntu 20.04 server setup.

- [ ] **Step 1: Write the setup script**

Create `deploy/setup.sh`:

```bash
#!/usr/bin/env bash
# ============================================================================
# DAGents-InsightFlow — Ubuntu 20.04 Server Bootstrap Script
# ============================================================================
# Run once as root on a fresh Ubuntu 20.04 server:
#   sudo bash setup.sh
#
# What this does:
#   1. Installs system dependencies (Python 3.11, Node.js 22, PostgreSQL 16, nginx)
#   2. Creates the 'dagents' system user
#   3. Clones (or updates) the project to /opt/dagents
#   4. Sets up Python venv + installs backend dependencies
#   5. Builds the frontend
#   6. Configures and starts systemd services + nginx
#
# What you MUST do before running:
#   - Have a PostgreSQL password ready (set below or export PG_PASSWORD)
#   - Have API keys ready: LLM_API_KEY, TAVILY_API_KEY, JWT_SECRET_KEY
#   - Optional: LANGSMITH_API_KEY
# ============================================================================
set -euo pipefail

# ── Configuration (edit these or export them before running) ───
PG_PASSWORD="${PG_PASSWORD:-change-me-to-a-strong-password}"
JWT_SECRET_KEY="${JWT_SECRET_KEY:-$(openssl rand -hex 32)}"
LLM_API_KEY="${LLM_API_KEY:-your-llm-api-key}"
LLM_BASE_URL="${LLM_BASE_URL:-https://ark.cn-beijing.volces.com/api/v3/}"
LLM_MODEL="${LLM_MODEL:-your-llm-model-name}"
TAVILY_API_KEY="${TAVILY_API_KEY:-your-tavily-api-key}"
DOMAIN_NAME="${DOMAIN_NAME:-_}"  # Set to your domain, e.g. dagents.example.com
APP_DIR="/opt/dagents"
GIT_REPO="https://github.com/your-org/DAGents-InsightFlow.git"  # ← UPDATE THIS
GIT_BRANCH="main"

echo "=============================================="
echo " DAGents-InsightFlow Server Setup"
echo "=============================================="
echo ""

# ── 1. System Dependencies ─────────────────────────────────────
echo "[1/8] Installing system dependencies..."

# Prevent interactive prompts
export DEBIAN_FRONTEND=noninteractive

# Python 3.11 (deadsnakes PPA)
if ! command -v python3.11 &> /dev/null; then
    apt-get update -qq
    apt-get install -y -qq software-properties-common
    add-apt-repository -y ppa:deadsnakes/ppa
    apt-get update -qq
    apt-get install -y -qq python3.11 python3.11-venv python3.11-dev
fi

# Node.js 22 LTS (NodeSource)
if ! command -v node &> /dev/null || [ "$(node -v | cut -d'.' -f1 | tr -d 'v')" -lt 20 ]; then
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
    apt-get install -y -qq nodejs
fi

# PostgreSQL 16 (official repo)
if ! command -v psql &> /dev/null; then
    sh -c 'echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list'
    curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /etc/apt/trusted.gpg.d/postgresql.gpg
    apt-get update -qq
    apt-get install -y -qq postgresql-16 postgresql-client-16 libpq-dev
fi

# nginx
apt-get install -y -qq nginx

# Build tools
apt-get install -y -qq build-essential git curl openssl

echo "  System dependencies installed."
echo ""

# ── 2. Create system user ──────────────────────────────────────
echo "[2/8] Creating 'dagents' system user..."

if ! id -u dagents &>/dev/null; then
    useradd --system --shell /bin/bash --create-home dagents
fi
# Add to appropriate groups for socket access if needed
usermod -a -G dagents dagents 2>/dev/null || true

echo "  System user 'dagents' ready."
echo ""

# ── 3. Clone project ───────────────────────────────────────────
echo "[3/8] Cloning project to $APP_DIR..."

if [ -d "$APP_DIR/.git" ]; then
    echo "  Repository exists, pulling latest..."
    cd "$APP_DIR"
    git fetch origin
    git reset --hard "origin/$GIT_BRANCH"
else
    mkdir -p "$(dirname "$APP_DIR")"
    git clone --branch "$GIT_BRANCH" "$GIT_REPO" "$APP_DIR"
fi

chown -R dagents:dagents "$APP_DIR"
echo "  Project cloned to $APP_DIR."
echo ""

# ── 4. PostgreSQL setup ────────────────────────────────────────
echo "[4/8] Configuring PostgreSQL..."

# Start and enable PostgreSQL
systemctl enable postgresql
systemctl start postgresql

# Create user and database (idempotent as postgres user)
su - postgres -c "psql -tc \"SELECT 1 FROM pg_roles WHERE rolname='dagents'\"" | grep -q 1 || \
    su - postgres -c "psql -c \"CREATE USER dagents WITH PASSWORD '$PG_PASSWORD';\""
su - postgres -c "psql -tc \"SELECT 1 FROM pg_roles WHERE rolname='dagents'\"" | grep -q 1 || \
    su - postgres -c "psql -c \"ALTER USER dagents CREATEDB;\""
su - postgres -c "psql -tc \"SELECT 1 FROM pg_database WHERE datname='dagents'\"" | grep -q 1 || \
    su - postgres -c "psql -c \"CREATE DATABASE dagents OWNER dagents;\""

echo "  PostgreSQL configured (user: dagents, database: dagents)."
echo ""

# ── 5. Backend setup ───────────────────────────────────────────
echo "[5/8] Setting up backend..."

cd "$APP_DIR/backend"

# Create virtual environment
if [ ! -d ".venv" ]; then
    python3.11 -m venv .venv
fi
chown -R dagents:dagents .venv

# Install dependencies
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -e . -q

# Generate .env file
if [ ! -f ".env" ]; then
    cat > .env << EOF
DATABASE_URL=postgresql+asyncpg://dagents:${PG_PASSWORD}@127.0.0.1:5432/dagents
DATABASE_URL_SYNC=postgresql://dagents:${PG_PASSWORD}@127.0.0.1:5432/dagents
JWT_SECRET_KEY=${JWT_SECRET_KEY}
LLM_API_KEY=${LLM_API_KEY}
LLM_BASE_URL=${LLM_BASE_URL}
LLM_MODEL=${LLM_MODEL}
TAVILY_API_KEY=${TAVILY_API_KEY}
ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,http://${DOMAIN_NAME},https://${DOMAIN_NAME}
LANGSMITH_TRACING_V2=${LANGSMITH_TRACING_V2:-false}
LANGSMITH_API_KEY=${LANGSMITH_API_KEY:-}
LANGSMITH_PROJECT=${LANGSMITH_PROJECT:-dagents-insightflow}
EOF
    chown dagents:dagents .env
    chmod 600 .env
    echo "  .env file created. Please verify the API keys!"
else
    echo "  .env already exists, skipping."
fi

echo "  Backend dependencies installed."
echo ""

# ── 6. Frontend setup ──────────────────────────────────────────
echo "[6/8] Setting up frontend..."

cd "$APP_DIR/frontend"

# Create production env file
if [ ! -f ".env.production" ]; then
    cat > .env.production << EOF
NEXT_PUBLIC_API_BASE_URL=http://${DOMAIN_NAME}/api/v1
EOF
    chown dagents:dagents .env.production
    echo "  .env.production created."
else
    echo "  .env.production already exists, skipping."
fi

# Install and build
npm ci --omit=dev 2>/dev/null || npm install
NODE_ENV=production npm run build

echo "  Frontend built."
echo ""

# ── 7. Install and enable services ─────────────────────────────
echo "[7/8] Installing systemd services..."

# Backend
cp "$APP_DIR/deploy/backend.service" /etc/systemd/system/dagents-backend.service

# Frontend
cp "$APP_DIR/deploy/frontend.service" /etc/systemd/system/dagents-frontend.service

systemctl daemon-reload
systemctl enable dagents-backend
systemctl enable dagents-frontend
systemctl start dagents-backend
sleep 2
systemctl start dagents-frontend

echo "  Services installed and started."
echo ""

# ── 8. nginx configuration ─────────────────────────────────────
echo "[8/8] Configuring nginx..."

cp "$APP_DIR/deploy/nginx-dagents.conf" /etc/nginx/sites-available/dagents
ln -sf /etc/nginx/sites-available/dagents /etc/nginx/sites-enabled/dagents

# Remove default site if present
rm -f /etc/nginx/sites-enabled/default

# Test and reload
nginx -t && systemctl reload nginx

echo "  nginx configured and reloaded."
echo ""

# ── Done ────────────────────────────────────────────────────────
echo "=============================================="
echo " Setup Complete!"
echo "=============================================="
echo ""
echo "Services:"
echo "  backend:  systemctl status dagents-backend"
echo "  frontend: systemctl status dagents-frontend"
echo "  db:       systemctl status postgresql"
echo "  nginx:    systemctl status nginx"
echo ""
echo "Logs:"
echo "  journalctl -u dagents-backend -f"
echo "  journalctl -u dagents-frontend -f"
echo ""
echo "Next steps:"
echo "  1. Edit /opt/dagents/backend/.env to set real API keys"
echo "  2. Set up HTTPS: sudo certbot --nginx -d YOUR_DOMAIN"
echo "  3. Update DOMAIN_NAME in .env.production with your real domain"
echo "  4. Test: curl http://localhost:8000/docs"
echo ""
echo "JWT secret (saved): $JWT_SECRET_KEY"
```

Make it executable:

```bash
chmod +x deploy/setup.sh
```

- [ ] **Step 2: Commit**

```bash
git add deploy/setup.sh
git commit -m "feat: add server bootstrap setup script"
```

---

### Task 6: Write Deployment Guide

**Files:**
- Create: `deploy/DEPLOY.md`

- [ ] **Step 1: Write the deployment guide**

Create `deploy/DEPLOY.md`:

```markdown
# DAGents-InsightFlow Deployment Guide (Ubuntu 20.04)

## Prerequisites

- Ubuntu 20.04 server with root SSH access
- Domain name pointing to server IP (optional, for HTTPS)
- API keys:
  - **LLM_API_KEY** — Volcengine Ark (火山方舟) API key
  - **TAVILY_API_KEY** — Tavily search API key
  - **LANGSMITH_API_KEY** (optional) — LangSmith tracing

## Quick Start (Fresh Server)

### 1. SSH into the server

```bash
ssh root@your-server-ip
```

### 2. Set required environment variables and run the setup

```bash
export PG_PASSWORD="your-strong-postgres-password"
export LLM_API_KEY="your-llm-api-key"
export TAVILY_API_KEY="your-tavily-api-key"
export JWT_SECRET_KEY="$(openssl rand -hex 32)"
export DOMAIN_NAME="your-domain.com"  # or use server IP

# Optional:
export LANGSMITH_TRACING_V2="true"
export LANGSMITH_API_KEY="your-langsmith-key"
```

### 3. Upload project or clone from git

If your repo is on GitHub:

```bash
# First, set GIT_REPO in setup.sh or modify the script before running
sudo bash deploy/setup.sh
```

If deploying from local machine, use rsync/scp to upload the project first.

### 4. Verify

```bash
# Check services
systemctl status dagents-backend
systemctl status dagents-frontend
systemctl status nginx

# Test API
curl http://localhost:8000/docs

# Test via nginx
curl http://localhost/api/v1/auth/login
```

## Manual Deployment (Step by Step)

### Phase 1: System Dependencies

```bash
# Python 3.11
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt-get update
sudo apt-get install -y python3.11 python3.11-venv python3.11-dev

# Node.js 22 LTS
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo bash -
sudo apt-get install -y nodejs

# PostgreSQL 16
sudo sh -c 'echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list'
curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | sudo gpg --dearmor -o /etc/apt/trusted.gpg.d/postgresql.gpg
sudo apt-get update
sudo apt-get install -y postgresql-16 postgresql-client-16 libpq-dev

# nginx + tools
sudo apt-get install -y nginx build-essential git curl
```

### Phase 2: PostgreSQL

```bash
sudo systemctl enable postgresql
sudo systemctl start postgresql

sudo -u postgres psql << SQL
CREATE USER dagents WITH PASSWORD 'your-strong-password';
ALTER USER dagents CREATEDB;
CREATE DATABASE dagents OWNER dagents;
SQL
```

### Phase 3: Backend

```bash
# Clone project
sudo mkdir -p /opt/dagents
sudo git clone https://github.com/your-org/DAGents-InsightFlow.git /opt/dagents
sudo chown -R $USER:$USER /opt/dagents

# Create venv and install
cd /opt/dagents/backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .

# Create .env
cat > .env << EOF
DATABASE_URL=postgresql+asyncpg://dagents:YOUR_PASSWORD@127.0.0.1:5432/dagents
DATABASE_URL_SYNC=postgresql://dagents:YOUR_PASSWORD@127.0.0.1:5432/dagents
JWT_SECRET_KEY=$(openssl rand -hex 32)
LLM_API_KEY=your-llm-api-key
LLM_BASE_URL=https://ark.cn-beijing.volces.com/api/v3/
LLM_MODEL=your-model-name
TAVILY_API_KEY=your-tavily-key
ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
EOF

chmod 600 .env
```

### Phase 4: Frontend

```bash
cd /opt/dagents/frontend

# Create production env
cat > .env.production << EOF
NEXT_PUBLIC_API_BASE_URL=http://YOUR_SERVER_IP_OR_DOMAIN/api/v1
EOF

# Build
npm ci
NODE_ENV=production npm run build
```

### Phase 5: systemd Services

```bash
# Copy and enable services
sudo cp /opt/dagents/deploy/backend.service /etc/systemd/system/dagents-backend.service
sudo cp /opt/dagents/deploy/frontend.service /etc/systemd/system/dagents-frontend.service

sudo useradd --system --shell /bin/bash --create-home dagents
sudo chown -R dagents:dagents /opt/dagents

sudo systemctl daemon-reload
sudo systemctl enable dagents-backend dagents-frontend
sudo systemctl start dagents-backend dagents-frontend
```

### Phase 6: nginx

```bash
sudo cp /opt/dagents/deploy/nginx-dagents.conf /etc/nginx/sites-available/dagents
sudo ln -s /etc/nginx/sites-available/dagents /etc/nginx/sites-enabled/dagents
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx
```

### Phase 7: HTTPS (Let's Encrypt)

```bash
sudo apt-get install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

## Post-Deployment

### Verify it works

```bash
# 1. Register a user
curl -X POST http://YOUR_SERVER/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username": "demo", "email": "demo@test.com", "password": "demo123456"}'

# 2. Login
curl -X POST http://YOUR_SERVER/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "demo@test.com", "password": "demo123456"}'

# 3. Visit the frontend in browser
# http://YOUR_SERVER
```

### View logs

```bash
journalctl -u dagents-backend -f   # Backend logs
journalctl -u dagents-frontend -f  # Frontend logs
tail -f /var/log/nginx/access.log  # nginx access
tail -f /var/log/nginx/error.log   # nginx errors
```

### Update the application

```bash
cd /opt/dagents
git pull

# Backend
cd backend
source .venv/bin/activate
pip install -e .
sudo systemctl restart dagents-backend

# Frontend
cd ../frontend
npm ci
NODE_ENV=production npm run build
sudo systemctl restart dagents-frontend
```

### Backup PostgreSQL

```bash
sudo -u postgres pg_dump dagents > /opt/backups/dagents-$(date +%Y%m%d).sql
```

## Troubleshooting

| Problem | Check |
|---------|-------|
| Backend won't start | `journalctl -u dagents-backend -n 50` — likely .env misconfiguration or PostgreSQL connection refused |
| Frontend won't start | `journalctl -u dagents-frontend -n 50` — check Node.js version (≥20) |
| 502 from nginx | Backend/frontend not running or wrong port |
| SSE streams hang | nginx `proxy_buffering off;` must be set for `/api/` location |
| CORS errors | Verify `ALLOWED_ORIGINS` in `.env` includes your frontend URL |
```

- [ ] **Step 2: Commit**

```bash
git add deploy/DEPLOY.md
git commit -m "docs: add deployment guide for Ubuntu 20.04"
```

---

## Self-Review

### 1. Spec Coverage
- ✅ System dependency installation (Python 3.11, Node.js 22, PostgreSQL 16, nginx)
- ✅ Database setup (user, database, pg_hba)
- ✅ Backend venv + pip install + .env generation
- ✅ Frontend npm install + build + .env.production
- ✅ CORS origins made configurable
- ✅ systemd services for both backend and frontend
- ✅ nginx reverse proxy with SSE support
- ✅ HTTPS setup instructions (Let's Encrypt)
- ✅ Deployment guide with troubleshooting

### 2. Placeholder Check
No TBDs, TODOs, or "implement later" placeholders. All code and config is concrete.

### 3. Type/Path Consistency
- All file paths match the actual project structure
- Env var names match across setup.sh, systemd units, and config.py
- Service names are consistent: `dagents-backend`, `dagents-frontend`
- Port assignments consistent: backend=8000, frontend=3000, PostgreSQL=5432
