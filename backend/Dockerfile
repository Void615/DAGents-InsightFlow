# ============================================================================
# DAGents-InsightFlow Backend Dockerfile
# ============================================================================
# Build:  docker build -t dagents-backend ./backend
# Run:    docker run -p 8000:8000 --env-file backend/.env dagents-backend
# ============================================================================
FROM python:3.11-slim

# 防止 .pyc 文件生成，日志直接输出到 stdout
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# ── 安装系统依赖 ───────────────────────────────────────────────
# psycopg 编译需要 libpq-dev + gcc
RUN apt-get update -qq \
    && apt-get install -y -qq --no-install-recommends \
        libpq-dev \
        gcc \
        curl \
    && rm -rf /var/lib/apt/lists/*

# ── 安装 Python 依赖 ───────────────────────────────────────────
COPY pyproject.toml .
RUN pip install --upgrade pip -q \
    && pip install -e . -q \
    && pip cache purge

# ── 复制应用代码 ───────────────────────────────────────────────
COPY . .

# ── 创建非 root 用户 ───────────────────────────────────────────
RUN useradd --system --create-home appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--log-level", "info"]
