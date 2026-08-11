# DocAgent —— 多智能体文档智能排版平台

上传 Word 文档 + 自然语言需求，AI 自动完成格式排版（字体/字号/加粗/行距/段间距），支持模板推荐、样式覆盖率校验、失败自动重规划，全程进度实时推送。

## 功能特性

- **多智能体编排**（LangGraph）：Supervisor → RAG 模板检索 → Planner → EntryGuard → Executor → Validator 闭环，校验不达标自动重规划重试（最多 3 轮）
- **RAG 模板推荐**：BGE-M3 向量化 + BM25 混合检索，按行业/文档内容推荐最匹配排版模板
- **原子指令执行**：每条排版指令独立执行、逐条错误记录，单条失败不中断流程；修改前 MinIO + 内存双层备份，失败可回滚
- **样式覆盖率校验**：字体/字号/加粗/行距/段间距五维扫描，生成 missed 段落明细报告
- **实时进度**：SSE 实时推送 + Redis 快照降级轮询
- **账户体系**：邮箱验证码注册/登录、JWT、积分扣费、支付宝沙箱支付、管理员后台
- **个人知识库**：上传文档（支持 MinerU 解析，含图片提取）→ 切块向量化 → 隔离检索
- **MCP 暴露**：全部 API 以 MCP 工具形式暴露（`/mcp`），前端/AI 客户端可直接调用

## 技术栈

| 层 | 技术 |
|---|---|
| 网关 | FastAPI + Uvicorn（端口 8001） |
| 异步任务 | Celery + Redis（broker db0 / backend db1 / 缓存 db2） |
| 编排 | LangGraph（Checkpointer 断点恢复） |
| 向量库 | ChromaDB（端口 8000） |
| 存储 | MySQL 8（3307）/ Redis 7 / MinIO（9000） |
| 文档处理 | python-docx + BGE-M3（sentence-transformers） |
| 前端 | Vue3 + Vite + Element Plus（5173 dev / 80 生产） |
| 文档解析（可选） | MinerU（OpenXLab API，含图片提取） |

## 架构总览

```
浏览器 ── Vue3 (5173) ──┬── /api/v1/* ──┐
                        │                │
                        └── /mcp (MCP) ──┤
                       FastAPI 网关 (8001) ── MySQL / Redis / MinIO
                              │ 投递任务
                        Celery Worker ── LangGraph 编排图
                              │              │
                        RAG 检索 ── ChromaDB / BGE-M3
```

任务链路：`上传 → 存 MinIO → 写 MySQL(pending) → Celery 执行 LangGraph 图 → 校验 → 成功/失败 → 下载`

## 快速开始（本地开发）

开发环境运行方案（推荐 A）：**基础设施（MySQL/Redis/MinIO/ChromaDB）用 Docker 容器，应用（uvicorn/Celery/前端）在本机跑**——代码热重载秒级生效、日志/断点调试最方便。全栈容器化（`docker compose up -d --build`）适合演示或干净环境；生产部署见下文。

### 1. 启动基础设施（Docker）

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/dev_up.ps1   # 一键启动 + 等待健康
```

或手动执行 `docker compose up -d mysql redis minio chromadb`（只起 4 个基础设施容器）。

启动 MySQL(3307) / Redis(6379) / MinIO(9000) / ChromaDB(8000)，全部带健康检查。

### 2. 配置环境变量

```bash
cp .env.example .env   # 填入 LLM API Key / SMTP / 支付宝等
```

必填：`QWEN_API_KEY`（或 DEEPSEEK/OPENAI，并对应改 `LLM_PROVIDER` / `LLM_MODEL`）。

### 3. 安装依赖并初始化

```bash
uv sync                              # 安装 Python 依赖（Python >= 3.13）
PYTHONPATH=. uv run python scripts/init_db.py      # 建表 + 游客账号 + 管理员
PYTHONPATH=. uv run python scripts/init_chroma.py  # 内置模板向量灌库
```

### 4. 启动后端

```bash
uv run uvicorn app.main:app --port 8001          # API 网关
uv run celery -A app.celery_app worker -P solo --loglevel=info   # Worker（Windows 需 -P solo）
uv run celery -A app.celery_app beat --loglevel=info             # Beat（过期任务清扫）
```

### 5. 启动前端

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```

### 6. 验证

```bash
curl http://localhost:8001/api/v1/health   # {"status":"ok","services":{...}}
```

## 生产部署（Docker 一键）

```bash
docker compose -f docker-compose.prod.yml up --build
```

构建后端镜像（web/worker/beat 三进程）+ 前端 nginx（80/443 HTTPS，反代 /api、/mcp），
MinerU 模型缓存挂卷，MySQL 每日自动备份到 `./data/backup`。

## 环境变量配置表

完整清单见 `.env.example`（12 组配置）。核心项：

| 分组 | 变量 | 说明 |
|---|---|---|
| LLM | `LLM_PROVIDER` / `LLM_MODEL` | deepseek \| openai \| qwen |
| LLM | `QWEN_API_KEY` 等 | 对应供应商 Key |
| 认证 | `JWT_SECRET` | 生产必须更换为随机长字符串 |
| 认证 | `ADMIN_EMAILS` | 逗号分隔，自动授权管理员 |
| 邮件 | `SMTP_*` | QQ 邮箱 SMTP + 授权码 |
| 支付 | `ALIPAY_*` | 支付宝沙箱配置 |
| 解析 | `MINERU_API_KEY` | 可选，知识库上传文档解析 |
| 任务 | `TASK_EXPIRE_HOURS` / `API_RATE_LIMIT` | 生命周期 / 限流 |

## API 契约（模块 A 四接口）

统一前缀 `/api/v1`，业务错误返回 `HTTP 200 + {"code":N,"msg":...}`，限流返回 `429`。

| 接口 | 方法 | 说明 |
|---|---|---|
| `/process` | POST | 上传 .docx + prompt → 提交任务（限流 10 次/分） |
| `/task/{task_id}` | GET | 轮询状态/进度/步骤/日志（Redis 快照优先） |
| `/download/{task_id}` | GET | 302 重定向 MinIO 预签名 URL（5 分钟） |
| `/health` | GET | 四服务健康探测 |
| `/tasks` | GET | 我的任务列表（登录） |

其他模块：`/auth/*`（注册/登录/验证码/改密）、`/chat` + `/rag/*`、`/knowledge/*`、`/pay/*`、`/templates/*`。

**MCP**：`POST http://localhost:8001/mcp`（Streamable HTTP），JSON-RPC `initialize → tools/list → tools/call`；文件上传/下载类接口不走 MCP。

## 测试

```bash
uv run pytest               # 单元测试（无外部依赖，SQLite 内存库）
uv run ruff check app scripts tests   # 代码规范
# 全链路 e2e（需基础设施 + 网关 + worker 已启动）：
PYTHONPATH=. uv run python scripts/test_api.py
```

## 目录结构

```
app/
  api/           # 网关路由（routes/auth/chat/knowledge/pay/templates）
  agents/        # LangGraph 编排（graph + nodes/*）
  services/      # 领域服务（docx_editor/parser、storage、knowledge、mineru、embeddings、task_cache）
  crud/          # 数据层
  models/        # ORM 模型
  tasks.py       # Celery 任务
frontend/        # Vue3 前端（src/views/* 12 个页面）
scripts/         # 初始化/测试脚本（init_db/init_chroma/init_knowledge/test_api）
tests/           # pytest 单元测试
docker-compose.yml          # 基础设施 + 应用服务（本地）
docker-compose.prod.yml     # 生产一键部署
Dockerfile / frontend/Dockerfile
```

## 常见问题

- **端口冲突**：8000 被 Chroma 占用，网关固定 8001；本机 3306 被占用，MySQL 映射 3307
- **Windows Worker**：必须 `-P solo`（Windows 无 fork）
- **MinerU 未生效**：检查 `.env` 的 `MINERU_API_KEY`，未配置时自动降级本地正则提取
- **日志**：loguru 统一输出（控制台 + `logs/` 文件轮转），指标见 `GET /metrics`

## License

MIT
