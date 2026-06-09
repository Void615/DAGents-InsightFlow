# ============================================================================
# DAGents-InsightFlow Frontend Dockerfile (multi-stage)
# ============================================================================
# Build:  docker build -t dagents-frontend ./frontend \
#           --build-arg NEXT_PUBLIC_API_BASE_URL=/api/v1
# ============================================================================

# ── Stage 1: Build ──────────────────────────────────────────────
FROM node:22-alpine AS builder

WORKDIR /app

# 构建时注入 API 地址（默认为相对路径，由 nginx 统一代理）
ARG NEXT_PUBLIC_API_BASE_URL=/api/v1
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL

COPY package.json package-lock.json* ./
RUN npm ci

COPY . .
RUN npm run build

# ── Stage 2: Runtime ────────────────────────────────────────────
FROM node:22-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

# 创建非 root 用户
RUN addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 nextjs

# 仅复制运行时需要的文件
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs

EXPOSE 3000

ENV PORT=3000
ENV HOSTNAME=0.0.0.0

CMD ["node", "server.js"]
