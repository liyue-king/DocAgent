# ============================================================
# DocAgent 前端镜像（node 构建 → nginx 静态托管 + API 反代）
# 构建（上下文为仓库根目录，nginx.conf 与 Dockerfile 同放 deploy/）：
#   docker build -t docagent-frontend -f deploy/frontend.Dockerfile .
# ============================================================

FROM node:20-alpine AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80 443
