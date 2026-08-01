# DocAgent 完整需求与系统设计说明书（优化版 v5.1）

> 本文档为项目唯一蓝图（Single Source of Truth），AI 结对编程（Vibe Coding）时请严格按此实现。

| 文档信息     | 内容                                                         |
| :----------- | :----------------------------------------------------------- |
| **项目名称** | DocAgent - 基于多智能体协作的智能文档处理平台                |
| **文档版本** | v5.1（基于 v5.0 优化：统一口径、补全状态映射 / 错误码 / 里程碑）|
| **开发模式** | Vibe Coding（AI 结对编程）                                   |
| **交付周期** | 7 个自然日（一次性全量交付）                                 |
| **核心架构** | FastAPI + Celery + LangGraph(Multi-Agent) + RAG(ChromaDB) + MySQL + Redis + MinIO + Vue3 |

**修订历史**

| 版本 | 日期       | 变更说明                                                     |
| :--- | :--------- | :----------------------------------------------------------- |
| v5.0 | 初版       | 整合战略 / 功能 / 数据 / 状态机 / API / 前端 / 部署全部章节  |
| v5.1 | 2026-08-01 | 统一「样式覆盖率」「相似度阈值」「状态枚举」「进度区间」口径；新增错误码、三端状态映射、术语表、非功能性需求、目录结构、里程碑 |

---

## 目录

1. [项目概述](#1-项目概述)
2. [总体架构](#2-总体架构)
3. [功能需求（FR）](#3-功能需求fr)
4. [非功能性需求（NFR）](#4-非功能性需求nfr)
5. [数据设计：四库联动](#5-数据设计四库联动)
6. [智能体编排设计（LangGraph）](#6-智能体编排设计langgraph)
7. [API 接口契约](#7-api-接口契约)
8. [前端 UI 设计（Vue3）](#8-前端-ui-设计vue3)
9. [异常处理与容错矩阵](#9-异常处理与容错矩阵)
10. [部署与环境配置](#10-部署与环境配置)
11. [交付计划与里程碑](#11-交付计划与里程碑)
12. [附录](#12-附录)

---

## 1. 项目概述

### 1.1 产品使命

打造一款"会思考的文档机器人"。用户上传任意 `.docx` 文件并输入自然语言需求，系统通过**多智能体协作**自动完成：模板检索（RAG）→ 排版规划（Planner）→ 执行修改（Executor）→ 自我校验（Validator）的全链路闭环。

### 1.2 SMART 目标

| 维度 | 目标 |
| :--- | :--- |
| **范围** | 覆盖学术论文、商务标书、合同、报告四大类文档排版，支持 10 种预设模板 |
| **质量** | 样式覆盖率验收线 **≥ 98%**（Validator 强制校验，详见 3.3 口径说明）；系统崩溃率 **≤ 1%** |
| **成本** | 单文档 LLM API 费用 **≤ ￥0.05**（默认 DeepSeek，备选 GPT-4o-mini） |
| **性能** | 20 页以内文档全流程处理 **≤ 3 分钟** |
| **时限** | 7 个自然日全量交付（见第 11 章里程碑） |

> **口径说明（v5.1 统一）**：Validator 以覆盖率 100% 为**重试触发线**（未到 100% 即触发重规划，最多 3 次）；重试耗尽后，覆盖率 **≥ 98% 判成功**，**< 98% 判失败**。三档口径：`100%` = 重试触发线，`≥98%` = 成功验收线，`<98%` = 失败线。

### 1.3 明确不做（Anti-Goals）

- ❌ 不支持 `.doc`（老格式）——用户需自行另存为 `.docx`。
- ❌ 不支持在线编辑器（WYSIWYG）。
- ❌ P0 版本不做用户登录/注册——所有任务挂载匿名游客账户（`users.id=1`），字段预留。
- ❌ 不支持表格内单元格独立样式修改（表格整体样式暂不处理）。

### 1.4 术语表

| 术语 | 含义 |
| :--- | :--- |
| RAG | 检索增强生成，用向量库召回最匹配的模板配置 |
| BM25 | 经典关键词相关性排序算法（配合 `rank_bm25` 库） |
| RRF | 倒数排名融合（Reciprocal Rank Fusion），多路召回结果融合排序 |
| DOM 树 | python-docx 解析出的文档结构树：`{"paragraphs":[{"id":0,"style":"Heading1",...}]}` |
| Supervisor | LangGraph 主调度节点，负责任务拆解与子 Agent 路由 |
| 原子操作 | Executor 执行的最小修改指令，如 `{"action":"set_font","para_ids":[0,1,2],"font":"黑体"}` |
| 预签名 URL | MinIO 生成的限时访问链接（本设计 5 分钟有效） |
| ILM | 对象存储生命周期策略（本设计 24 小时后自动删除） |
| Vibe Coding | 以自然语言蓝图驱动 AI 生成代码的开发模式 |

---

## 2. 总体架构

### 2.1 五层架构图

```text
┌─────────────────────────────────────────────────────────────────────┐
│                   1. 前端展示层 (Vue3 + Element-Plus)              │
│           拖拽上传 / 实时进度条 / 滚动日志终端 / 下载              │
└─────────────────────────────────────────────────────────────────────┘
                                    │ HTTP (RESTful)
┌─────────────────────────────────────────────────────────────────────┐
│                  2. 网关与异步调度层 (FastAPI + Celery)            │
│         RESTful API / 文件校验 / 投递 Celery 任务 / 状态查询       │
└─────────────────────────────────────────────────────────────────────┘
                                    │ 任务投递 / 结果回传
┌─────────────────────────────────────────────────────────────────────┐
│             3. 核心智能编排层 (LangGraph + Multi-Agent)            │
│  ┌────────────────────── Supervisor (主调度器) ──────────────────┐ │
│  │        ↓               ↓               ↓               ↓      │ │
│  │  RAG_Agent        Planner_Agent  Executor_Agent  Validator_Agent│
│  └────────── (ReAct 模式：规划 → 执行 → 校验 → 重规划) ──────────┘ │
└─────────────────────────────────────────────────────────────────────┘
                                    │ 工具调用
┌─────────────────────────────────────────────────────────────────────┐
│                   4. 工具与数据接入层 (Tools)                      │
│    docx 解析器(DOM树) / 样式修改器(原子操作) / 混合检索器(BM25+向量) │
└─────────────────────────────────────────────────────────────────────┘
                                    │ 读写
┌─────────────────────────────────────────────────────────────────────┐
│               5. 基础设施层 (四库联动)                              │
│  MySQL(业务) │ Redis(队列/缓存) │ MinIO(文件) │ ChromaDB(向量)    │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 技术选型

| 层次 | 选型 | 版本要求 | 职责 |
| :--- | :--- | :--- | :--- |
| 前端 | Vue3 + Element-Plus + Vite | Node ≥ 20 | 上传 / 轮询 / 日志终端 / 下载 |
| 网关 | FastAPI | ≥ 0.141（当前工程已装） | REST API、文件校验、任务投递 |
| 异步 | Celery + Redis | Celery ≥ 5 | 耗时 Agent 任务异步执行 |
| 编排 | LangGraph | 最新稳定版 | 多智能体状态机与重试闭环 |
| 检索 | ChromaDB + rank_bm25 | chroma ≥ 0.5 | 向量 + 关键词混合召回 |
| 文档 | python-docx | 最新稳定版 | 解析 DOM 树与样式原子操作 |
| 存储 | MySQL 8.0 / Redis 7 / MinIO | 见 docker-compose | 业务主数据 / 队列缓存 / 对象存储 |

### 2.3 核心处理流程（时序概览）

```text
用户上传 .docx + prompt
      │
      ▼
[FastAPI] 文件校验 → 存 MinIO → 写 MySQL(tasks, pending) → 投递 Celery
      │
      ▼
[Celery Worker] 执行 LangGraph 状态机:
   RAG_Agent(选模板) → Planner(生成原子指令) → Executor(逐条修改)
      → Validator(扫描覆盖率) ──未达标且重试<3──▶ 回退 Planner 重规划
      │                         └──达标──▶ 输出文件 → MinIO → 更新 MySQL(success)
      │
      ▼
[前端] 轮询 /api/v1/task/{id} → 进度条 + 日志 → 成功页下载
```

---

## 3. 功能需求（FR）

### 模块 A：文件与异步任务管理（FastAPI + Celery）

| 需求ID | 需求描述 | 验收标准 |
| :----- | :--- | :--- |
| FR-A01 | 后端提供 `POST /api/v1/process`，接收 `.docx` 文件和用户自然语言 `prompt` | 返回 `{"code":0,"task_id":"uuid"}`，文件存入 MinIO |
| FR-A02 | 后端用 **Celery + Redis** 执行耗时 Agent 任务，前端通过 `GET /api/v1/task/{id}` 轮询状态 | 响应包含 `status`、`progress`(0-100)、`step`、`logs` |
| FR-A03 | 任务完成后通过 `GET /api/v1/download/{id}` 下载修改后的 docx（5 分钟预签名 URL） | 文件下载成功；24 小时后 MinIO 按 ILM 自动删除 |

### 模块 B：RAG 增强模板检索（ChromaDB + 混合召回）

| 需求ID | 需求描述 | 验收标准 |
| :----- | :--- | :--- |
| FR-B01 | 内置 10 种预设模板（学术/商务/政府/个人），含样式配置 JSON 和语义描述向量 | 初始化脚本一次性灌入 ChromaDB |
| FR-B02 | **RAG Agent** 执行混合检索：① 向量语义 Top-3；② BM25 关键词 Top-3；③ RRF 融合排序，返回最佳模板 | 输入"我要严谨的论文格式"命中"学术论文"模板，相似度 ≥ 0.7 |
| FR-B03 | 相似度不足时按档位降级，不报错 | 系统稳定运行，日志可追踪 |

> **相似度档位（v5.1 统一）**：
> - `≥ 0.7`：高置信命中，直接采用 Top-1 模板；
> - `0.5 ~ 0.7`：中置信，采用 Top-1 并写入 WARNING 日志（提示"匹配度一般"）；
> - `< 0.5`：自动降级为"通用模板"（`default_template.json`），记录 INFO 日志，**不报错**。

### 模块 C：核心智能体编排（LangGraph 状态机）

| 需求ID | 需求描述 | 验收标准 |
| :----- | :--- | :--- |
| FR-C01 | **Supervisor 节点**：解析用户 Prompt，拆解任务，调度 Sub-Agent | LangGraph 编译通过，状态流转正常 |
| FR-C02 | **Planner 节点**：结合模板配置与文档 DOM 树，生成原子操作任务队列（JSON） | 示例输出 `[{"action":"set_font","para_ids":[0,1,2],"font":"黑体"}]` |
| FR-C03 | **Executor 节点**：调用 `python-docx` 工具集逐条执行任务队列 | 文档被实际修改，进度条同步更新 |
| FR-C04 | **Validator 节点**（闭环核心）：修改后二次扫描计算样式覆盖率；未达 100% 生成差异报告并触发 `retry`（最多 3 次） | 失败重试时状态变为 `retrying`，前端黄色闪烁提示 |

> **覆盖率三档口径见 [1.2](#12-smart-目标)**：重试触发线 100%、成功验收线 ≥98%、失败线 <98%。

### 模块 D：精准文档操作（python-docx）

| 需求ID | 需求描述 | 验收标准 |
| :----- | :--- | :--- |
| FR-D01 | 支持修改段落样式：字体/字号/加粗/斜体/行距（单倍/1.5 倍/固定值）/段前段后距 | Word 打开后样式面板同步变化 |
| FR-D02 | 支持识别 `Heading 1` ~ `Heading 3` 并分别应用不同配置 | 大纲视图层级不乱 |
| FR-D03 | 执行前**自动备份**原始文件至 MinIO 临时目录，修改失败则回滚 | 损坏文件绝不覆盖原文件 |

### 模块 E：前端交互（Vue3 + Element-Plus）

| 需求ID | 需求描述 | 验收标准 |
| :----- | :--- | :--- |
| FR-E01 | 页面：上传区（拖拽）+ Prompt 文本框（占位符示例）+ "开始魔法处理"按钮 | 按钮仅在"文件 + 文本非空"时点亮 |
| FR-E02 | **6 种状态视图**：空闲/上传中/处理中(进度条+日志终端)/重试中(黄色闪烁)/成功/失败 | 日志终端黑底绿字，滚动显示 Agent 步骤 |
| FR-E03 | 成功页：大号下载按钮 + "再来一单"重置按钮；失败页：红色错误卡片 + 复制日志按钮 | 交互闭环 |

### 3.1 需求优先级总览

| 优先级 | 需求 | 说明 |
| :--- | :--- | :--- |
| **P0（本期必须）** | 模块 A/B/C/D/E 全部 | 7 天内交付可用的最小闭环 |
| **P1（预留扩展）** | Redis db=3 LangGraph Checkpointer、用户登录、表格样式、在线编辑器 | 字段与接口已预留，本期不实现 |

---

## 4. 非功能性需求（NFR）

| 类别 | 需求 | 指标 |
| :--- | :--- | :--- |
| **性能** | 20 页以内文档端到端处理 | ≤ 3 分钟 |
| | 前端状态轮询 | 每 2 秒 1 次，Redis 命中 |
| | 预签名 URL 有效期 | 5 分钟 |
| **成本** | 单文档 LLM API 费用 | ≤ ￥0.05（DeepSeek 优先） |
| **可靠性** | 系统崩溃率 | ≤ 1% |
| | 文档损坏兜底 | 修改前备份，失败自动回滚，原文件绝不丢失 |
| | 任务超时保护 | Worker `soft_time_limit=240`，超时置 `failed` |
| **安全** | 文件访问 | MinIO 桶 Private + 预签名 URL，防盗链 |
| | 文件生命周期 | 输入/输出文件 24 小时自动删除 |
| | 限流 | 按 IP 限流 `10 次/分钟`（Redis 计数） |
| **可维护性** | 日志 | 统一 `loguru` 输出；Agent 步骤入库 `agent_logs` |
| | 配置 | 全部经环境变量注入（`.env`），容器化部署 |

---

## 5. 数据设计：四库联动

### 5.1 MySQL：业务主数据（Source of Truth）

**完整 DDL（MySQL 8.0+）**：

```sql
-- 创建数据库
CREATE DATABASE IF NOT EXISTS `docagent`
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE `docagent`;

-- 1. 用户表（P0 默认匿名游客 ID=1）
CREATE TABLE `users` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `phone` VARCHAR(20) NULL DEFAULT NULL,
  `email` VARCHAR(100) NULL DEFAULT NULL,
  `password_hash` VARCHAR(255) NOT NULL DEFAULT '',
  `credits_balance` INT NOT NULL DEFAULT 10 COMMENT '免费额度10次',
  `is_active` TINYINT(1) NOT NULL DEFAULT 1,
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_phone` (`phone`),
  UNIQUE KEY `uk_email` (`email`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 插入匿名游客（P0 所有任务挂载到该账户）
INSERT INTO `users` (`id`, `credits_balance`) VALUES (1, 999);

-- 2. 模板配置表
CREATE TABLE `templates` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `name` VARCHAR(50) NOT NULL,
  `description` TEXT NOT NULL,
  `config` JSON NOT NULL COMMENT '样式配置JSON',
  `vector_id` VARCHAR(64) NULL DEFAULT NULL COMMENT 'ChromaDB向量ID',
  `is_system` TINYINT(1) NOT NULL DEFAULT 0,
  `usage_count` INT NOT NULL DEFAULT 0,
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`id`),
  KEY `idx_is_system` (`is_system`),
  KEY `idx_usage_count` (`usage_count` DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 3. 任务核心表（含 Agent 全状态）
CREATE TABLE `tasks` (
  `id` CHAR(36) NOT NULL COMMENT 'UUID (与Celery task_id一致)',
  `user_id` BIGINT UNSIGNED NOT NULL DEFAULT 1,
  `template_id` INT UNSIGNED NULL DEFAULT NULL,

  `prompt_text` TEXT NOT NULL,
  `input_file_name` VARCHAR(255) NOT NULL,
  `input_file_hash` VARCHAR(64) NOT NULL,
  `input_file_path` VARCHAR(500) NOT NULL,
  `output_file_path` VARCHAR(500) NULL DEFAULT NULL,

  `status` ENUM(
    'pending', 'retrieving', 'planning', 'executing',
    'validating', 'retrying', 'success', 'failed', 'expired'
  ) NOT NULL DEFAULT 'pending',
  `progress` TINYINT UNSIGNED NOT NULL DEFAULT 0,
  `current_step` VARCHAR(50) NULL DEFAULT NULL,
  `retry_count` TINYINT UNSIGNED NOT NULL DEFAULT 0,

  `agent_state_snapshot` JSON NULL DEFAULT NULL COMMENT 'LangGraph全量状态快照',
  `llm_total_tokens` INT UNSIGNED NOT NULL DEFAULT 0,
  `cost_usd` DECIMAL(10,6) UNSIGNED NOT NULL DEFAULT 0.000000,
  `processing_time_ms` INT UNSIGNED NULL DEFAULT NULL,

  `started_at` DATETIME(3) NULL DEFAULT NULL,
  `completed_at` DATETIME(3) NULL DEFAULT NULL,
  `expires_at` DATETIME(3) NOT NULL COMMENT 'created_at + 24小时',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),

  PRIMARY KEY (`id`),
  KEY `idx_user_status` (`user_id`, `status`),
  KEY `idx_status_created` (`status`, `created_at` DESC),
  KEY `idx_expires_at` (`expires_at`),
  CONSTRAINT `fk_tasks_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`),
  CONSTRAINT `fk_tasks_template` FOREIGN KEY (`template_id`) REFERENCES `templates` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 4. Agent 执行日志表
CREATE TABLE `agent_logs` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `task_id` CHAR(36) NOT NULL,
  `agent_node` VARCHAR(30) NOT NULL,
  `log_level` ENUM('INFO','WARNING','ERROR') NOT NULL DEFAULT 'INFO',
  `log_message` TEXT NOT NULL,
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`id`),
  KEY `idx_task_id_created` (`task_id`, `created_at` DESC),
  CONSTRAINT `fk_logs_task` FOREIGN KEY (`task_id`) REFERENCES `tasks` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

**模板 `config` JSON 结构范例**：

```json
{
  "version": "1.0",
  "paragraph_styles": {
    "heading_1": {"font_name": "黑体", "font_size_pt": 16, "bold": true, "space_before_pt": 24, "space_after_pt": 12, "line_spacing_rule": "MULTIPLE", "line_spacing_value": 1.5},
    "heading_2": {"font_name": "黑体", "font_size_pt": 14, "bold": true, "space_before_pt": 18, "space_after_pt": 6, "line_spacing_rule": "MULTIPLE", "line_spacing_value": 1.5},
    "normal": {"font_name": "宋体", "font_size_pt": 12, "bold": false, "space_before_pt": 0, "space_after_pt": 0, "line_spacing_rule": "MULTIPLE", "line_spacing_value": 1.5}
  }
}
```

### 5.2 Redis：运行时缓存与队列（db 分区隔离）

| Redis DB | 用途 | 关键 Key 模式 | TTL |
| :--- | :--- | :--- | :--- |
| `db=0` | Celery Broker（自动） | `celery` 前缀 | 自动 |
| `db=1` | Celery Result Backend（自动） | `celery-task-meta-{id}` | 自动 |
| `db=2` | **应用级缓存** | | |
| | - 任务进度 | `docagent:task:{id}:progress` | 3600s |
| | - 任务状态 | `docagent:task:{id}:status` | 3600s |
| | - 当前步骤 | `docagent:task:{id}:step` | 3600s |
| | - 最近日志(20条) | `docagent:task:{id}:logs` (List) | 3600s |
| | - 模板配置缓存 | `docagent:template:{id}:config` (Hash) | 86400s |
| | - IP 限流 | `docagent:ratelimit:{ip}` | 60s |
| `db=3` | LangGraph Checkpointer（P1 启用） | 自动管理 | 持久 |

**读写策略**：前端轮询**优先读 Redis**，Key 不存在则降级查 MySQL 并回填 Redis。

### 5.3 MinIO：对象存储（文件资产）

| 桶名 | 访问策略 | 用途 | ILM 生命周期 |
| :--- | :--- | :--- | :--- |
| `docagent-input` | Private | 存储用户上传的原始文件 | 24 小时后自动删除 |
| `docagent-output` | Private | 存储处理后的输出文件 | 24 小时后自动删除 |

**对象 Key 规范**：

```
docagent-input/{year}/{month}/{day}/{task_id}/{original_filename}.docx
docagent-output/{year}/{month}/{day}/{task_id}/modified_{original_filename}.docx
```

**预签名 URL 下载**：有效期 5 分钟，防止盗链。

### 5.4 ChromaDB：向量知识库（RAG 检索）

| 配置项 | 值 |
| :--- | :--- |
| **Collection 名称** | `doc_templates` |
| **Embedding 模型** | `BAAI/bge-m3`（CPU 可跑，免费） |
| **距离度量** | `cosine` |
| **持久化路径** | `./chroma_data` |

**存储数据模型（每个 Document）**：

| 字段 | 类型 | 示例 |
| :--- | :--- | :--- |
| `id` | String | `tmpl_001`（与 MySQL `template_id` 对齐） |
| `document` | String | `"适用于本科毕业论文，正文宋体小四，标题黑体三号，1.5倍行距"` |
| `metadata.template_id` | Int | `1` |
| `metadata.template_name` | String | `"学术论文"` |
| `metadata.category` | String | `"academic"` |

**查询逻辑（多路召回）**：

1. 向量检索：`collection.query(query_texts=[prompt], n_results=5)`
2. 关键词检索：BM25（`rank_bm25` 库）对同一批文档计分
3. 融合排序：RRF（Reciprocal Rank Fusion）取 Top-1

---

## 6. 智能体编排设计（LangGraph）

### 6.1 State Schema

> 原样写入 `app/agents/state.py`：

```python
from typing import TypedDict, List, Dict, Any, Literal

class DocAgentState(TypedDict):
    # 输入
    user_prompt: str
    task_id: str

    # RAG 结果
    retrieved_templates: List[Dict[str, Any]]
    selected_template_id: int
    selected_template_config: Dict[str, Any]  # 模板 JSON

    # 文档解析
    doc_dom_tree: Dict[str, Any]  # {"paragraphs": [{"id":0, "style":"Heading1"}, ...]}

    # 规划与执行
    task_queue: List[Dict[str, Any]]  # 原子指令列表
    current_task_index: int
    executed_count: int

    # 校验闭环
    validation_report: Dict[str, Any]  # {"coverage": 0.95, "missed": [...], "passed": False}
    retry_count: int

    # 控制
    status: Literal["idle", "retrieving", "planning", "executing", "validating", "done", "failed"]
    error_message: str
    agent_logs: List[str]
    llm_total_tokens: int
```

### 6.2 节点与流转逻辑

```text
supervisor_node ──► rag_searcher ──► planner ──► executor ──► validator
                                                              │
            ┌─────────────────────────────────────────────────┤
            │  passed=False 且 retry_count < 3               │  passed=True
            ▼                                                 ▼
        planner（重规划，retry_count+1）                success_node
                                                              │
        validator 输出 passed=False 且 retry_count >= 3 ──► error_node（强制失败）
```

- `supervisor_node`：条件路由 → `rag_searcher` / `planner` / `executor` / `validator`
- `validator` 输出 `passed=False` 且 `retry_count < 3` → 跳回 `planner`（重规划）
- `validator` 输出 `passed=True` → 跳转 `success_node`
- `retry_count >= 3` → 跳转 `error_node`（强制失败）

### 6.3 三端状态映射（v5.1 补全）

> LangGraph 内部状态、MySQL 持久化状态、前端 UI 视图三者必须一一对应。

| LangGraph 状态 | MySQL `tasks.status` | 前端 UI 视图 | 进度区间 |
| :--- | :--- | :--- | :--- |
| `idle` | `pending` | 上传中（提交后）→ 处理中 | 0 |
| `retrieving` | `retrieving` | 处理中 | 0 ~ 30 |
| `planning` | `planning` | 处理中 | 30 ~ 60 |
| `executing` | `executing` | 处理中 | 60 ~ 90 |
| `validating` | `validating` | 处理中 | 90 ~ 100 |
| 回跳 `planning`（重试） | `retrying` | **重试中**（黄色闪烁） | 回退至 30 重新推进 |
| `done` | `success` | 成功 | 100 |
| `failed` | `failed` | 失败 | 定格 |
| - | `expired`（24h 后清理） | - | - |

---

## 7. API 接口契约

### 7.1 接口列表

| 方法 | 端点 | 请求体 | 响应体示例 |
| :--- | :--- | :--- | :--- |
| **POST** | `/api/v1/process` | `multipart/form-data`：`file` + `prompt`(string) | `{"code":0,"task_id":"abc-123","msg":"任务已提交"}` |
| **GET** | `/api/v1/task/{task_id}` | - | `{"code":0,"status":"executing","progress":65,"step":"正在修改第3章标题","logs":["[10:00:01] 检索完成"],"download_url":null}` |
| **GET** | `/api/v1/download/{task_id}` | - | `302 Redirect` 到 MinIO 预签名 URL，或直接返回文件流 |
| **GET** | `/api/v1/health` | - | `{"status":"ok","services":{"mysql":true,"redis":true,"minio":true,"chroma":true}}` |

### 7.2 统一错误码（v5.1 补全）

| code | 含义 | 触发场景 |
| :--- | :--- | :--- |
| `0` | 成功 | - |
| `1001` | 参数错误 | 未传文件 / prompt 为空 |
| `1002` | 文件大小超限 | 超过 `MAX_FILE_SIZE_MB`（20MB） |
| `1003` | 文件格式不支持 | 非 `.docx` |
| `2001` | 任务不存在或已过期 | task_id 无效 |
| `2002` | 状态不允许该操作 | 任务未完成时请求下载 |
| `3001` | 文件已过期删除 | 超过 24h 生命周期 |
| `4001` | 内部错误 / LLM 服务异常 | LLM 返回 429/400/超时 |
| `4002` | 文档处理失败 | 重试 3 次后覆盖率仍 < 98% |
| `429` | 触发限流 | 超过 `API_RATE_LIMIT`（10 次/分钟/IP） |

### 7.3 轮询协议约定

- 前端每 **2 秒**轮询一次 `GET /api/v1/task/{task_id}`。
- 后端优先读 Redis（`db=2`），未命中降级查 MySQL 并回填。
- `status` 为 `success` 时响应携带 `download_url`（5 分钟预签名 URL）。
- `status` 为 `failed` / `expired` 时前端停止轮询并渲染失败视图。

---

## 8. 前端 UI 设计（Vue3）

### 8.1 UI 状态机

| 界面状态 | 显示元素 | 用户可操作 |
| :--- | :--- | :--- |
| **空闲** | 大号拖拽区 + Prompt 文本框（占位符示例）+ 灰色"开始魔法"按钮 | 上传文件、输入文字 |
| **上传中** | 进度条（文件上传 %）+ 取消按钮 | 取消 |
| **处理中** | 三段进度条（检索 0-30 / 规划 30-60 / 执行 60-90 / 校验 90-100）+ **黑底绿字滚动日志终端** | **无操作（防抖）** |
| **重试中** | 进度条**黄色闪烁** + 日志打印"校验未通过，AI 重规划中(第2次)" | 仅观看 |
| **成功** | 绿色对勾动画 + "下载文件"大按钮 + "再来一单" | 下载、重置 |
| **失败** | 红色卡片 + 错误详情 + "复制错误日志"按钮 | 重试、复制 |

### 8.2 组件结构建议

```text
frontend/src/
├── App.vue                 # 根组件：持有 task_id / status 状态机
├── components/
│   ├── UploadZone.vue      # 拖拽上传 + 文件校验
│   ├── PromptInput.vue     # 自然语言需求输入
│   ├── ProgressBar.vue     # 分段进度条（含黄色闪烁态）
│   ├── LogTerminal.vue     # 黑底绿字滚动日志终端
│   ├── SuccessPanel.vue    # 下载 + 再来一单
│   └── ErrorPanel.vue      # 错误卡片 + 复制日志
└── api/client.js           # axios 封装：process / poll / download
```

---

## 9. 异常处理与容错矩阵（强制兜底）

| 异常场景 | 触发条件 | **系统强制响应（硬逻辑）** | 用户提示 |
| :--- | :--- | :--- | :--- |
| RAG 检索空 | ChromaDB 最高分 < 0.5 | 自动加载 `default_template.json`（通用宋体黑体） | "未找到高度匹配模板，已应用通用标准" |
| LLM JSON 解析失败 | Planner 返回非有效 JSON | 重试 1 次（temperature=0），仍失败则执行硬编码（全部改宋体） | "AI 规划走神，已启用备用方案" |
| python-docx 损坏 | 修改后 `Document()` 加载报错 | **立即回滚**：将 MinIO 备份复制到输出路径 | "文档结构特殊，已安全返回原文件" |
| Celery Worker 宕机 | 任务 Pending 超 5 分钟 | `soft_time_limit=240`，超时置为 `failed` | "任务超时，请稍后重试" |
| API 配额耗尽 | 返回 429/400 | 捕获后直接置 `failed`，记录 `cost_usd` | "LLM 服务配额不足，请联系管理员" |
| 校验重试耗尽 | 3 次重试后覆盖率 < 98% | 置 `failed`，保留最后一次修改结果供下载 | "排版校验未通过，可下载当前结果" |

---

## 10. 部署与环境配置

### 10.1 Docker Compose（一键启动全部基础设施）

```yaml
# 定义网络，让所有容器在同一个局域网内互访
networks:
  docagent-net:
    driver: bridge

services:
  # ---------- 1. MySQL 业务数据库 ----------
  mysql:
    image: mysql:8.0
    container_name: docagent-mysql
    restart: always
    environment:
      MYSQL_ROOT_PASSWORD: docagent123
      MYSQL_DATABASE: docagent
      # 解决 Windows 下中文乱码问题
      MYSQL_CHARACTER_SET_SERVER: utf8mb4
      MYSQL_COLLATION_SERVER: utf8mb4_unicode_ci
    ports:
      - "3306:3306"
    volumes:
      # 数据卷基址可用环境变量覆盖：VOLUME_BASE=/path/to/data docker compose up -d
      - ${VOLUME_BASE:-./data}/mysql:/var/lib/mysql
    networks:
      - docagent-net
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost"]
      interval: 10s
      timeout: 5s
      retries: 5

  # ---------- 2. Redis 缓存与队列 ----------
  redis:
    image: redis:7.0-alpine
    container_name: docagent-redis
    restart: always
    ports:
      - "6379:6379"
    volumes:
      - ${VOLUME_BASE:-./data}/redis:/data
    # 开启持久化，防止重启丢数据
    command: redis-server --appendonly yes --appendfsync everysec
    networks:
      - docagent-net
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

  # ---------- 3. MinIO 文件存储（对象存储） ----------
  minio:
    image: minio/minio:RELEASE.2024-01-16T16-07-38Z
    container_name: docagent-minio
    restart: always
    ports:
      - "9000:9000"   # API 端口（代码连接用）
      - "9001:9001"   # 管理后台 Web 界面
    environment:
      MINIO_ROOT_USER: docagent
      MINIO_ROOT_PASSWORD: docagent123
    volumes:
      - ${VOLUME_BASE:-./data}/minio:/data
    command: server /data --console-address ":9001"
    networks:
      - docagent-net
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
      interval: 30s
      timeout: 10s
      retries: 3

  # ---------- 4. ChromaDB 向量数据库（RAG 核心） ----------
  chromadb:
    image: chromadb/chroma:0.5.0
    container_name: docagent-chroma
    restart: always
    ports:
      - "8000:8000"
    volumes:
      - ${VOLUME_BASE:-./data}/chroma:/chroma/chroma
    environment:
      ANONYMIZED_TELEMETRY: FALSE   # 关闭匿名统计，提升隐私
      IS_PERSISTENT: TRUE           # 开启持久化
      CHROMA_SERVER_CORS_ALLOW_ORIGINS: "*"  # 允许跨域（前端调试方便）
    networks:
      - docagent-net
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/v1/heartbeat"]
      interval: 30s
      timeout: 10s
      retries: 3
```

> **v5.1 变更说明**：数据卷挂载由写死的 `D:/DocAgent/data/...` 改为 `${VOLUME_BASE:-./data}/...`，默认落盘到 compose 文件所在目录的 `./data`，同时保留通过环境变量 `VOLUME_BASE` 指定绝对路径的能力（如 Windows 下 `VOLUME_BASE=D:/DocAgent/data`）。

### 10.2 环境变量（`.env.example`）

```env
# MySQL
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=docagent123
MYSQL_DATABASE=docagent

# Redis
REDIS_URL=redis://localhost:6379/0
REDIS_CACHE_URL=redis://localhost:6379/2

# MinIO
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=docagent
MINIO_SECRET_KEY=docagent123
MINIO_SECURE=false
MINIO_INPUT_BUCKET=docagent-input
MINIO_OUTPUT_BUCKET=docagent-output

# ChromaDB
CHROMA_HOST=localhost
CHROMA_PORT=8000

# LLM (DeepSeek 或 OpenAI)
LLM_PROVIDER=deepseek  # 或 openai
DEEPSEEK_API_KEY=sk-xxx
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
OPENAI_API_KEY=sk-xxx
OPENAI_BASE_URL=https://api.openai.com/v1
LLM_MODEL=deepseek-chat  # 或 gpt-4o-mini

# Celery
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1

# 应用
MAX_FILE_SIZE_MB=20
TASK_EXPIRE_HOURS=24
MAX_RETRY_COUNT=3
API_RATE_LIMIT=10  # 每分钟请求数
```

### 10.3 项目目录结构（建议）

```text
DocAgent/
├── app/
│   ├── main.py                  # FastAPI 入口（当前工程已存在脚手架）
│   ├── config.py                # pydantic-settings 读取 .env
│   ├── api/
│   │   └── routes.py            # /process /task/{id} /download/{id} /health
│   ├── agents/
│   │   ├── state.py             # DocAgentState（见 6.1）
│   │   ├── graph.py             # LangGraph 状态机（含重试闭环）
│   │   └── nodes/               # supervisor / rag / planner / executor / validator
│   ├── services/
│   │   ├── storage.py           # MinIO 上传/备份/预签名
│   │   ├── rag.py               # ChromaDB + BM25 + RRF
│   │   ├── docx_tools.py        # python-docx 解析与原子操作
│   │   └── llm.py               # DeepSeek / OpenAI 客户端
│   └── models/                  # SQLAlchemy 模型（users/templates/tasks/agent_logs）
├── frontend/                    # Vue3 + Element-Plus + Vite
│   └── src/
│       ├── App.vue
│       ├── components/          # UploadZone / ProgressBar / LogTerminal / ...
│       └── api/client.js
├── scripts/
│   ├── init_db.py               # 建表 + 插入默认模板和匿名游客
│   ├── init_minio.py            # 创建两个桶并设置 ILM 策略
│   ├── init_chroma.py           # 初始化 Collection 并灌入 10 条模板向量
│   └── seed_templates.json      # 10 种预设模板（config + 语义描述）
├── data/                        # Docker 数据卷（默认 ./data）
├── docker-compose.yml
├── .env.example
├── pyproject.toml               # 当前工程使用 uv 管理
└── README.md
```

> **现状说明（v5.1 补充）**：当前工程为 `uv` + Python 3.13 + FastAPI 空脚手架（仅 `main.py` 的 HelloWorld），本蓝图涉及的新依赖（celery、langgraph、chromadb、rank_bm25、python-docx、minio、sqlalchemy、loguru、pydantic-settings 等）按第 11 章里程碑逐步加入 `pyproject.toml`。

---

## 11. 交付计划与里程碑

| 天 | 里程碑 | 交付物 | 验收点 |
| :--- | :--- | :--- | :--- |
| **Day 1** | 基础设施初始化 | `docker-compose.yml` + `.env.example` + 4 个 init 脚本 + 目录骨架 | 四库容器健康检查通过；`scripts/init_*.py` 可执行且幂等 |
| **Day 2** | 后端网关与异步链路 | `app/api/routes.py` + MinIO 存储服务 + Celery 任务 + MySQL 落库 | 上传→入队→状态查询全链路通；文件入库 MinIO |
| **Day 3** | RAG 检索 | `app/services/rag.py` + ChromaDB 灌库 | 10 模板就绪；"我要严谨的论文格式"命中学术模板 ≥0.7 |
| **Day 4** | 智能体编排 | `state.py` + `graph.py` + 5 个节点 | 状态机编译通过；Validator 重试闭环可触发 |
| **Day 5** | 文档操作 | `docx_tools.py` 原子操作 + 备份回滚 | 样式修改生效；损坏注入时自动回滚不丢原文件 |
| **Day 6** | 前端 | Vue3 6 状态视图 + 轮询 + 日志终端 + 下载 | 全流程 UI 演示通过；重试黄色闪烁可见 |
| **Day 7** | 联调与验收 | 全链路测试 + 异常注入用例 + README | 20 页文档 ≤3 分钟；覆盖率 ≥98%；成本 ≤￥0.05 |

---

## 12. 附录：Vibe Coding 启动指令（直接喂给 Cursor/Cline）

> 本项目已提供完整蓝图 `PROJECT_BLUEPRINT.md`（即本文档）。向 AI 发送以下指令：

> "我已提供完整的 `PROJECT_BLUEPRINT.md`，请严格按照此蓝图执行：
> 1. 先生成 `requirements.txt`（或更新 `pyproject.toml`）和项目目录结构（`app/`、`frontend/`、`scripts/`）。
> 2. 生成 `scripts/init_db.py`，执行建表语句并插入默认模板和匿名游客。
> 3. 生成 `scripts/init_minio.py`，创建两个桶并设置 ILM 策略。
> 4. 生成 `scripts/init_chroma.py`，初始化 Collection 并灌入 10 条内置模板向量。
> 5. 生成 `app/agents/graph.py`，完整实现 LangGraph 状态机（含 Validator 重试闭环）。
> 6. 生成 `app/api/routes.py`，实现四个接口（上传/状态/下载/健康检查）。
> 7. 生成前端 `frontend/src/App.vue`，包含 6 种状态视图和滚动日志组件。
> 8. 确保所有代码包含中文注释，且日志使用 `loguru` 统一输出。
> 9. 最后生成 `README.md`，包含 `docker-compose up -d` 启动命令。"
