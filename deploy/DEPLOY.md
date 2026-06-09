# DAGents-InsightFlow 部署指南

> **推荐 Docker Compose 部署** — 无需手动安装 Python/Node.js/PostgreSQL，一条命令启动。

---

## 服务器要求

- Ubuntu 20.04+（或其他支持 Docker 的 Linux 发行版）
- 2 核 4GB 以上（`npm build` 需要内存）
- 以下 API 密钥：
  - `LLM_API_KEY` — 火山方舟 API 密钥
  - `TAVILY_API_KEY` — Tavily 搜索 API 密钥
  - `LANGSMITH_API_KEY` — 可选，调用链追踪

---

## 一、Docker Compose 部署（推荐）

### 1. 安装 Docker

Ubuntu 20.04 上没有 Docker，需要手动安装：

```bash
# 官方安装脚本（推荐）
curl -fsSL https://get.docker.com | sudo bash

# 将当前用户加入 docker 组（免 sudo）
sudo usermod -aG docker $USER
# 重新登录使生效
```

### 2. 上传项目

```bash
# 从 Git 克隆
git clone https://github.com/your-org/DAGents-InsightFlow.git
cd DAGents-InsightFlow

# 或从本地上传
# rsync -avz ./ user@server:~/DAGents-InsightFlow/
```

### 3. 配置环境变量

```bash
cp .env.docker .env
```

编辑 `.env`，填入真实密钥：

```bash
PG_PASSWORD=你的数据库密码
JWT_SECRET_KEY=$(openssl rand -hex 32)   # 随机生成
LLM_API_KEY=你的火山方舟密钥
LLM_BASE_URL=https://ark.cn-beijing.volces.com/api/v3/
LLM_MODEL=模型名称
TAVILY_API_KEY=你的Tavily密钥
ALLOWED_ORIGINS=http://你的域名,http://你的服务器IP
```

### 4. 构建并启动

```bash
docker compose up -d --build
```

首次构建约 3-5 分钟（主要是 `npm build`）。启动后四个容器运行：

| 容器 | 端口 | 说明 |
|------|------|------|
| `dagents-postgres` | (内部) | PostgreSQL 16 |
| `dagents-backend` | (内部) | FastAPI，uvicorn |
| `dagents-frontend` | (内部) | Next.js |
| `dagents-nginx` | **80** | 反向代理，统一入口 |

### 5. 验证

```bash
# 检查容器状态
docker compose ps

# 测试 API
curl http://localhost/api/v1/auth/login

# 注册用户
curl -X POST http://localhost/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username": "demo", "email": "demo@test.com", "password": "demo123456"}'
```

浏览器访问 `http://你的服务器IP` 即可。

---

## 二、日常运维 (Docker)

### 查看日志

```bash
docker compose logs -f              # 所有服务
docker compose logs -f backend      # 仅后端
docker compose logs -f frontend     # 仅前端
docker compose logs --tail=50 backend
```

### 更新应用

```bash
git pull
docker compose build --no-cache
docker compose up -d
# 清理旧镜像
docker image prune -f
```

### 重启服务

```bash
docker compose restart backend     # 单服务
docker compose restart             # 全部
docker compose down && docker compose up -d  # 完全重建
```

### 备份数据库

```bash
# 导出
docker exec dagents-postgres pg_dump -U dagents dagents > backup-$(date +%Y%m%d).sql

# 恢复
docker exec -i dagents-postgres psql -U dagents dagents < backup-20260609.sql
```

### 设置自动备份 (cron)

```bash
crontab -e
# 添加（每天凌晨 3 点）:
0 3 * * * docker exec dagents-postgres pg_dump -U dagents dagents > ~/backups/dagents-$(date +\%Y\%m\%d).sql && find ~/backups -name '*.sql' -mtime +7 -delete
```

---

## 三、HTTPS 配置

### 方式一：云厂商 SSL 证书（推荐）

在阿里云/腾讯云控制台申请免费 SSL 证书，下载 nginx 格式，然后：

1. 将证书文件放到 `./certs/` 目录
2. 修改 `docker-compose.yml`，取消 nginx 443 端口和证书挂载的注释
3. 修改 `deploy/nginx-docker.conf`，添加 SSL 配置

### 方式二：Let's Encrypt

```bash
# 先用 HTTP 启动
docker compose up -d

# 安装 certbot
sudo apt-get install -y certbot

# 获取证书（standalone 模式，需临时停 nginx）
docker compose stop nginx
sudo certbot certonly --standalone -d your-domain.com
docker compose start nginx

# 证书在 /etc/letsencrypt/live/your-domain.com/
# 挂载到 nginx 容器并修改 nginx 配置启用 SSL
```

---

## 四、Docker 架构说明

```
docker compose up -d
        │
        ├── postgres:16-alpine      ← 数据持久化: pgdata volume
        │     └── healthcheck: pg_isready
        │
        ├── backend (built)          ← Python 3.11 + FastAPI
        │     └── env 由 .env 注入
        │
        ├── frontend (built)         ← Next.js standalone
        │     └── NEXT_PUBLIC_API_BASE_URL=/api/v1 (相对路径)
        │
        └── nginx:alpine             ← 端口映射 80:80
              └── proxy: /api/* → backend, /* → frontend
```

**关键设计点：**

- **前端使用相对 API 路径**：`/api/v1` 相对路径，由 nginx 统一代理。同一套构建产物可用于任何域名。
- **PostgreSQL 健康检查**：backend 等待 postgres 就绪后才启动，避免冷启动竞态。
- **数据持久化**：`pgdata` volume 保存数据库文件，`docker compose down` 不会丢失数据。
- **容器间通信**：通过 `dagents` bridge 网络，容器名即为 hostname（如 `postgres:5432`）。

---

## 五、故障排查

| 问题 | 检查方向 |
|------|---------|
| 容器启动失败 | `docker compose logs backend` 查看具体错误 |
| 502 Bad Gateway | `docker compose ps` 确认 backend/frontend 都是 Up 状态 |
| 数据库连接拒绝 | backend 日志中 `postgres` hostname 是否可达，密码是否正确 |
| CORS 错误 | `.env` 中 `ALLOWED_ORIGINS` 需包含浏览器访问地址（含 `http://` 或 `https://`） |
| SSE 流中断 | `deploy/nginx-docker.conf` 中 `/api/` 的 `proxy_buffering off` 是否生效 |
| 构建时内存不足 | `docker compose build --build-arg NODE_OPTIONS="--max-old-space-size=4096"` |
| npm build 失败 | 检查 `frontend/next.config.ts` 中 `output: "standalone"` 是否配置 |

---

## 六、裸机部署（备选）

如需不使用 Docker 部署，参见下方步骤。Docker 方案不需要以下任何操作。

<details>
<summary>展开裸机部署步骤</summary>

### 安装系统依赖

```bash
# Python 3.11
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt-get update && sudo apt-get install -y python3.11 python3.11-venv python3.11-dev

# Node.js 22
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo bash -
sudo apt-get install -y nodejs

# PostgreSQL 16
sudo sh -c 'echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list'
curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | sudo gpg --dearmor -o /etc/apt/trusted.gpg.d/postgresql.gpg
sudo apt-get update && sudo apt-get install -y postgresql-16 postgresql-client-16 libpq-dev

# nginx
sudo apt-get install -y nginx build-essential git curl openssl
```

### 配置 PostgreSQL

```bash
sudo systemctl enable postgresql && sudo systemctl start postgresql
sudo -u postgres psql << EOF
CREATE USER dagents WITH PASSWORD 'your-password';
ALTER USER dagents CREATEDB;
CREATE DATABASE dagents OWNER dagents;
EOF
```

### 部署后端

```bash
cd backend
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env  # 编辑填入真实配置
```

### 部署前端

```bash
cd frontend
cat > .env.production << EOF
NEXT_PUBLIC_API_BASE_URL=http://YOUR_DOMAIN/api/v1
EOF
npm ci && NODE_ENV=production npm run build
```

### 安装 systemd 服务

```bash
sudo cp deploy/backend.service /etc/systemd/system/dagents-backend.service
sudo cp deploy/frontend.service /etc/systemd/system/dagents-frontend.service
sudo systemctl daemon-reload
sudo systemctl enable --now dagents-backend dagents-frontend
```

### 配置 nginx

```bash
sudo cp deploy/nginx-dagents.conf /etc/nginx/sites-available/dagents
sudo ln -s /etc/nginx/sites-available/dagents /etc/nginx/sites-enabled/dagents
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

</details>
