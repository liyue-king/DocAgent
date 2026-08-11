# ============================================================
# DocAgent 后端镜像（uv 管理依赖，多入口：web / worker / beat）
# 构建：docker build -t docagent-backend .
# 入口：
#   web    默认（uvicorn，端口 8001）
#   worker  docker run docagent-backend uv run celery -A app.celery_app worker
#   beat    docker run docagent-backend uv run celery -A app.celery_app beat
# ============================================================

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

# 依赖缓存层：pyproject/uv.lock 不变则跳过 uv sync
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONPATH=/app \
    HF_HOME=/models \
    SENTENCE_TRANSFORMERS_HOME=/models \
    PYTHONUNBUFFERED=1

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# 代码与资源层
COPY app ./app
COPY scripts ./scripts
COPY keys ./keys
RUN mkdir -p /app/data/output /app/logs /app/checkpoints

EXPOSE 8001

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
