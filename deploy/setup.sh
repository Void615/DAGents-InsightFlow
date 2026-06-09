#!/usr/bin/env bash
# ============================================================================
# DAGents-InsightFlow — Ubuntu 20.04 服务器一键部署脚本
# ============================================================================
# 用法（在 root 下执行）:
#   sudo bash setup.sh
#
# 执行前请设置以下环境变量（或运行时会提示输入）:
#   PG_PASSWORD       - PostgreSQL 数据库密码
#   LLM_API_KEY       - LLM API 密钥（火山方舟）
#   LLM_BASE_URL      - LLM API 地址
#   LLM_MODEL         - LLM 模型名称
#   TAVILY_API_KEY    - Tavily 搜索 API 密钥
#   DOMAIN_NAME       - 服务器域名或 IP（如 dagents.example.com）
#   GIT_REPO          - 项目 Git 仓库地址
#   GIT_BRANCH        - Git 分支（默认 main）
#
# 可选:
#   LANGSMITH_API_KEY - LangSmith 追踪 API 密钥
# ============================================================================
set -euo pipefail

# ── 可配置项（通过环境变量覆盖）─────────────────────────────────
GIT_REPO="${GIT_REPO:-}"
GIT_BRANCH="${GIT_BRANCH:-main}"
APP_DIR="${APP_DIR:-/opt/dagents}"

# 生成随机值作为默认值
if [ -z "${JWT_SECRET_KEY:-}" ]; then
    JWT_SECRET_KEY="$(openssl rand -hex 32 2>/dev/null || python3 -c 'import secrets;print(secrets.token_hex(32))')"
fi

echo "=============================================="
echo " DAGents-InsightFlow Server Setup"
echo " Ubuntu 20.04"
echo "=============================================="
echo ""

# ── 0. 交互式收集必要信息 ──────────────────────────────────────
if [ -z "${DOMAIN_NAME:-}" ]; then
    read -rp "请输入服务器域名或公网 IP: " DOMAIN_NAME
fi

if [ -z "${PG_PASSWORD:-}" ]; then
    read -rsp "请输入 PostgreSQL 数据库密码（或回车自动生成）: " PG_PASSWORD
    echo ""
    if [ -z "$PG_PASSWORD" ]; then
        PG_PASSWORD="$(openssl rand -hex 16 2>/dev/null || python3 -c 'import secrets;print(secrets.token_hex(16))')"
        echo "  自动生成密码: $PG_PASSWORD"
    fi
fi

echo ""
echo "部署配置:"
echo "  域名/IP:       $DOMAIN_NAME"
echo "  应用目录:      $APP_DIR"
echo "  Git 分支:      $GIT_BRANCH"
echo ""
if [ -n "$GIT_REPO" ]; then
    echo "  Git 仓库:      $GIT_REPO"
fi

# ── 1. 安装系统依赖 ────────────────────────────────────────────
echo "[1/8] 安装系统依赖..."

export DEBIAN_FRONTEND=noninteractive

# Python 3.11（deadsnakes PPA）
if ! command -v python3.11 &> /dev/null; then
    echo "  安装 Python 3.11..."
    apt-get update -qq
    apt-get install -y -qq software-properties-common
    add-apt-repository -y ppa:deadsnakes/ppa
    apt-get update -qq
    apt-get install -y -qq python3.11 python3.11-venv python3.11-dev
fi

# Node.js 22 LTS（NodeSource）
if ! command -v node &> /dev/null || [ "$(node -v | cut -d'.' -f1 | tr -d 'v')" -lt 20 ]; then
    echo "  安装 Node.js 22..."
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
    apt-get install -y -qq nodejs
fi

# PostgreSQL 16（官方仓库）
if ! command -v psql &> /dev/null; then
    echo "  安装 PostgreSQL 16..."
    sh -c 'echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list'
    curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /etc/apt/trusted.gpg.d/postgresql.gpg
    apt-get update -qq
    apt-get install -y -qq postgresql-16 postgresql-client-16 libpq-dev
fi

# nginx
if ! command -v nginx &> /dev/null; then
    echo "  安装 nginx..."
    apt-get install -y -qq nginx
fi

# 基础构建工具
apt-get install -y -qq build-essential git curl openssl

echo "  系统依赖安装完成。"
echo ""

# ── 2. 创建系统用户 ────────────────────────────────────────────
echo "[2/8] 创建 dagents 系统用户..."

if ! id -u dagents &>/dev/null; then
    useradd --system --shell /bin/bash --create-home dagents
    echo "  用户 'dagents' 已创建。"
else
    echo "  用户 'dagents' 已存在，跳过。"
fi

echo ""

# ── 3. 获取项目代码 ────────────────────────────────────────────
echo "[3/8] 部署项目代码..."

if [ -n "$GIT_REPO" ]; then
    if [ -d "$APP_DIR/.git" ]; then
        echo "  仓库已存在，拉取最新代码..."
        cd "$APP_DIR"
        git fetch origin
        git reset --hard "origin/$GIT_BRANCH"
    else
        echo "  克隆仓库..."
        mkdir -p "$APP_DIR"
        git clone --branch "$GIT_BRANCH" "$GIT_REPO" "$APP_DIR"
    fi
    echo "  项目代码已部署到 $APP_DIR"
else
    echo "  GIT_REPO 未设置，假设代码已存在于 $APP_DIR"
    if [ ! -d "$APP_DIR" ]; then
        echo "  [错误] $APP_DIR 不存在且 GIT_REPO 未设置。"
        echo "  请在执行前将代码上传至服务器，或设置 GIT_REPO 环境变量。"
        exit 1
    fi
fi

chown -R dagents:dagents "$APP_DIR"
echo ""

# ── 4. PostgreSQL 配置 ──────────────────────────────────────────
echo "[4/8] 配置 PostgreSQL..."

systemctl enable postgresql
systemctl start postgresql

# 创建用户（幂等）
su - postgres -c "psql -tc \"SELECT 1 FROM pg_roles WHERE rolname='dagents'\"" 2>/dev/null | grep -q 1 || \
    su - postgres -c "psql -c \"CREATE USER dagents WITH PASSWORD '$PG_PASSWORD';\""
su - postgres -c "psql -c \"ALTER USER dagents CREATEDB;\"" 2>/dev/null || true

# 创建数据库（幂等）
su - postgres -c "psql -tc \"SELECT 1 FROM pg_database WHERE datname='dagents'\"" 2>/dev/null | grep -q 1 || \
    su - postgres -c "psql -c \"CREATE DATABASE dagents OWNER dagents;\""

echo "  PostgreSQL 配置完成（数据库: dagents, 用户: dagents）。"
echo ""

# ── 5. 后端设置 ─────────────────────────────────────────────────
echo "[5/8] 设置后端..."

cd "$APP_DIR/backend"

# 创建虚拟环境
if [ ! -d ".venv" ]; then
    python3.11 -m venv .venv
fi
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -e . -q

# 生成 .env 文件
cat > .env << ENVEOF
DATABASE_URL=postgresql+asyncpg://dagents:${PG_PASSWORD}@127.0.0.1:5432/dagents
DATABASE_URL_SYNC=postgresql://dagents:${PG_PASSWORD}@127.0.0.1:5432/dagents
JWT_SECRET_KEY=${JWT_SECRET_KEY}
LLM_API_KEY=${LLM_API_KEY:-your-llm-api-key}
LLM_BASE_URL=${LLM_BASE_URL:-https://ark.cn-beijing.volces.com/api/v3/}
LLM_MODEL=${LLM_MODEL:-your-llm-model-name}
TAVILY_API_KEY=${TAVILY_API_KEY:-your-tavily-api-key}
ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,http://${DOMAIN_NAME},https://${DOMAIN_NAME}
LANGSMITH_TRACING_V2=${LANGSMITH_TRACING_V2:-false}
LANGSMITH_API_KEY=${LANGSMITH_API_KEY:-}
LANGSMITH_PROJECT=${LANGSMITH_PROJECT:-dagents-insightflow}
LANGSMITH_ENDPOINT=${LANGSMITH_ENDPOINT:-}
ENVEOF

chown dagents:dagents .env
chmod 600 .env

echo "  后端依赖安装完成，.env 已生成。"
echo ""

# ── 6. 前端设置 ─────────────────────────────────────────────────
echo "[6/8] 设置前端..."

cd "$APP_DIR/frontend"

# 生成前端环境变量
cat > .env.production << ENVEOF
NEXT_PUBLIC_API_BASE_URL=http://${DOMAIN_NAME}/api/v1
ENVEOF
chown dagents:dagents .env.production

# 安装依赖并构建
echo "  安装 npm 依赖..."
npm ci --omit=dev 2>/dev/null || npm install
echo "  构建前端..."
NODE_ENV=production npm run build

echo "  前端构建完成。"
echo ""

# ── 7. 安装 systemd 服务 ───────────────────────────────────────
echo "[7/8] 安装 systemd 服务..."

cp "$APP_DIR/deploy/backend.service" /etc/systemd/system/dagents-backend.service
cp "$APP_DIR/deploy/frontend.service" /etc/systemd/system/dagents-frontend.service

systemctl daemon-reload
systemctl enable dagents-backend dagents-frontend
systemctl start dagents-backend
sleep 2
systemctl start dagents-frontend

echo "  systemd 服务已安装并启动。"
echo ""

# ── 8. nginx 配置 ───────────────────────────────────────────────
echo "[8/8] 配置 nginx..."

cp "$APP_DIR/deploy/nginx-dagents.conf" /etc/nginx/sites-available/dagents
ln -sf /etc/nginx/sites-available/dagents /etc/nginx/sites-enabled/dagents
rm -f /etc/nginx/sites-enabled/default

nginx -t && systemctl reload nginx

echo "  nginx 配置完成。"
echo ""

# ── 完成 ────────────────────────────────────────────────────────
echo "=============================================="
echo " 部署完成！"
echo "=============================================="
echo ""
echo "服务状态检查:"
echo "  backend:  systemctl status dagents-backend"
echo "  frontend: systemctl status dagents-frontend"
echo "  postgres: systemctl status postgresql"
echo "  nginx:    systemctl status nginx"
echo ""
echo "查看日志:"
echo "  journalctl -u dagents-backend -f"
echo "  journalctl -u dagents-frontend -f"
echo ""
echo "验证:"
echo "  curl http://localhost:8000/docs"
echo "  curl http://localhost/api/v1/auth/login"
echo ""
echo "数据库密码: $PG_PASSWORD"
echo "JWT 密钥:    $JWT_SECRET_KEY"
echo ""
echo "后续步骤:"
echo "  1. 编辑 $APP_DIR/backend/.env 填入真实的 API 密钥"
echo "  2. 配置 HTTPS: sudo certbot --nginx -d $DOMAIN_NAME"
echo "  3. 防火墙开放 80/443: sudo ufw allow 80/tcp && sudo ufw allow 443/tcp"
