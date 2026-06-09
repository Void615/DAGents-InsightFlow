# DAGents-InsightFlow 部署指南 (Ubuntu 20.04)

## 前置准备

- Ubuntu 20.04 服务器，具备 root SSH 访问权限
- 指向服务器 IP 的域名（可选，用于 HTTPS）
- 以下 API 密钥：
  - **LLM_API_KEY** — 火山方舟 API 密钥
  - **LLM_BASE_URL** — API 地址（默认 `https://ark.cn-beijing.volces.com/api/v3/`）
  - **LLM_MODEL** — 模型名称
  - **TAVILY_API_KEY** — Tavily 搜索 API 密钥
  - **LANGSMITH_API_KEY**（可选）— LangSmith 调用链追踪

---

## 快速部署（一键脚本）

### 1. SSH 登录服务器

```bash
ssh root@your-server-ip
```

### 2. 将项目上传至服务器并执行部署

**方式 A：从 Git 仓库部署**

```bash
export GIT_REPO="https://github.com/your-org/DAGents-InsightFlow.git"
export GIT_BRANCH="main"
export DOMAIN_NAME="your-domain.com"    # 或服务器 IP
export PG_PASSWORD="your-strong-pg-password"
export LLM_API_KEY="your-llm-api-key"
export TAVILY_API_KEY="your-tavily-api-key"
# 可选:
export LANGSMITH_API_KEY="your-langsmith-key"
export LANGSMITH_TRACING_V2="true"

# 下载脚本并执行（或手动 scp 上传整个项目后执行 deploy/setup.sh）
git clone "$GIT_REPO" /tmp/dagents-repo
cd /tmp/dagents-repo
sudo bash deploy/setup.sh
```

**方式 B：从本地上传项目**

```bash
# 在本地机器上
rsync -avz --exclude 'node_modules' --exclude '.venv' --exclude '.next' \
  ./ user@your-server:/opt/dagents/

# SSH 到服务器
ssh root@your-server-ip
cd /opt/dagents
sudo bash deploy/setup.sh
```

> 运行时会交互式询问未通过环境变量设置的必填项（域名、数据库密码等）。

### 3. 验证

```bash
# 检查服务状态
systemctl status dagents-backend dagents-frontend nginx postgresql

# 测试 API
curl http://localhost:8000/docs
curl http://your-domain/api/v1/auth/login
```

---

## 手动部署（逐步）

### 第一步：安装系统依赖

#### Python 3.11

Ubuntu 20.04 内置 Python 3.8，需要额外安装 3.11+：

```bash
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt-get update
sudo apt-get install -y python3.11 python3.11-venv python3.11-dev
```

#### Node.js 22 LTS

```bash
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo bash -
sudo apt-get install -y nodejs

# 验证
node -v  # 应输出 v22.x.x
```

#### PostgreSQL 16

Ubuntu 20.04 内置 PostgreSQL 12，项目需要 14+：

```bash
sudo sh -c 'echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list'
curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | sudo gpg --dearmor -o /etc/apt/trusted.gpg.d/postgresql.gpg
sudo apt-get update
sudo apt-get install -y postgresql-16 postgresql-client-16 libpq-dev
```

#### nginx + 其他工具

```bash
sudo apt-get install -y nginx build-essential git curl openssl
```

### 第二步：配置 PostgreSQL

```bash
# 启动并设为开机自启
sudo systemctl enable postgresql
sudo systemctl start postgresql

# 创建用户和数据库
sudo -u postgres psql << EOF
CREATE USER dagents WITH PASSWORD 'your-strong-password';
ALTER USER dagents CREATEDB;
CREATE DATABASE dagents OWNER dagents;
EOF
```

### 第三步：部署后端

```bash
# 创建应用目录
sudo mkdir -p /opt/dagents
sudo chown -R $USER:$USER /opt/dagents

# 克隆或上传项目代码
cd /opt/dagents
# git clone ... 或手动上传

# 创建虚拟环境
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .

# 创建 .env 配置文件
cat > .env << EOF
DATABASE_URL=postgresql+asyncpg://dagents:YOUR_PASSWORD@127.0.0.1:5432/dagents
DATABASE_URL_SYNC=postgresql://dagents:YOUR_PASSWORD@127.0.0.1:5432/dagents
JWT_SECRET_KEY=$(python3 -c 'import secrets;print(secrets.token_hex(32))')
LLM_API_KEY=your-llm-api-key
LLM_BASE_URL=https://ark.cn-beijing.volces.com/api/v3/
LLM_MODEL=your-model-name
TAVILY_API_KEY=your-tavily-api-key
ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,http://YOUR_DOMAIN,https://YOUR_DOMAIN
LANGSMITH_TRACING_V2=false
LANGSMITH_API_KEY=
LANGSMITH_PROJECT=dagents-insightflow
EOF

chmod 600 .env
```

### 第四步：部署前端

```bash
cd /opt/dagents/frontend

# 创建生产环境变量
cat > .env.production << EOF
NEXT_PUBLIC_API_BASE_URL=http://YOUR_DOMAIN_OR_IP/api/v1
EOF

# 安装依赖并构建
npm ci
NODE_ENV=production npm run build
```

### 第五步：配置 systemd 服务

```bash
# 创建系统用户
sudo useradd --system --shell /bin/bash --create-home dagents
sudo chown -R dagents:dagents /opt/dagents

# 安装服务文件
sudo cp /opt/dagents/deploy/backend.service /etc/systemd/system/dagents-backend.service
sudo cp /opt/dagents/deploy/frontend.service /etc/systemd/system/dagents-frontend.service

# 启动服务
sudo systemctl daemon-reload
sudo systemctl enable dagents-backend dagents-frontend
sudo systemctl start dagents-backend dagents-frontend
```

### 第六步：配置 nginx

```bash
sudo cp /opt/dagents/deploy/nginx-dagents.conf /etc/nginx/sites-available/dagents
sudo ln -s /etc/nginx/sites-available/dagents /etc/nginx/sites-enabled/dagents
sudo rm -f /etc/nginx/sites-enabled/default

sudo nginx -t           # 测试配置
sudo systemctl reload nginx
```

### 第七步：配置 HTTPS（推荐）

```bash
sudo apt-get install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

certbot 会自动修改 nginx 配置，添加 SSL 证书并启用 HTTPS 重定向。

### 第八步：配置防火墙

```bash
sudo ufw allow 22/tcp      # SSH
sudo ufw allow 80/tcp      # HTTP
sudo ufw allow 443/tcp     # HTTPS
sudo ufw enable
```

---

## 部署后验证

```bash
# 1. 注册用户
curl -X POST http://YOUR_SERVER/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username": "demo", "email": "demo@test.com", "password": "demo123456"}'

# 2. 登录获取 token
curl -X POST http://YOUR_SERVER/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "demo@test.com", "password": "demo123456"}'

# 3. 浏览器访问
# http://YOUR_SERVER
```

---

## 日常运维

### 查看日志

```bash
# 后端日志
journalctl -u dagents-backend -f

# 前端日志
journalctl -u dagents-frontend -f

# 最近 50 行
journalctl -u dagents-backend -n 50

# nginx 日志
tail -f /var/log/nginx/access.log
tail -f /var/log/nginx/error.log
```

### 更新应用

```bash
cd /opt/dagents

# 拉取最新代码
git pull origin main

# 更新后端
cd backend
source .venv/bin/activate
pip install -e .
sudo systemctl restart dagents-backend

# 更新前端
cd ../frontend
npm ci
NODE_ENV=production npm run build
sudo systemctl restart dagents-frontend
```

### 重启服务

```bash
sudo systemctl restart dagents-backend
sudo systemctl restart dagents-frontend
```

### 备份数据库

```bash
# 创建备份目录
sudo mkdir -p /opt/backups

# 导出
sudo -u postgres pg_dump dagents > /opt/backups/dagents-$(date +%Y%m%d-%H%M).sql

# 恢复
# sudo -u postgres psql dagents < /opt/backups/dagents-20260609-1200.sql
```

### 设置自动备份 (cron)

```bash
# 每天凌晨 3 点备份，保留最近 7 天
sudo crontab -e
# 添加:
0 3 * * * pg_dump -U postgres dagents > /opt/backups/dagents-$(date +\%Y\%m\%d).sql && find /opt/backups -name '*.sql' -mtime +7 -delete
```

---

## 故障排查

| 问题 | 检查方向 |
|------|---------|
| 后端无法启动 | `journalctl -u dagents-backend -n 50` — 通常是 .env 配置错误或 PostgreSQL 连不上 |
| 前端无法启动 | `journalctl -u dagents-frontend -n 50` — 检查 Node.js 版本 ≥20 |
| nginx 返回 502 | 后端或前端未运行，或监听端口不正确 |
| SSE 流中断 | nginx 的 `proxy_buffering off` 必须对 `/api/` 路径生效 |
| CORS 错误 | 检查 `backend/.env` 中 `ALLOWED_ORIGINS` 是否包含前端访问地址 |
| 数据库连接拒绝 | 检查 PostgreSQL 是否运行、密码是否正确、pg_hba.conf 是否允许本地连接 |
| npm build 失败 | 内存不足可能导致 OOM — 尝试 `NODE_OPTIONS="--max-old-space-size=4096" npm run build` |
