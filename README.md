# DAGents-InsightFlow

AI 驱动的竞品分析多 Agent 协作系统。通过 LangGraph 编排多个专业 Agent，自动完成信息采集、多维分析、报告撰写和质量审查的完整竞品分析流程。

## 技术栈
- 后端：FastAPI + LangGraph + 异步 PostgreSQL
- 前端：Next.js + Tailwind CSS（未开始）
- LLM：火山方舟（字节豆包）
- 搜索：Tavily API

## 已实现功能

- [x] 用户注册 / 登录 / JWT 认证
- [x] 工作流 CRUD（创建、列表、详情、删除）
- [x] InterviewAgent 多轮 SSE 流式对话，自动提取 WorkflowConfig
- [x] Tavily 搜索自动推荐竞品
- [x] LangGraph StateGraph DAG 编排（4 节点 + 条件路由）
- [x] BackgroundTasks 异步工作流执行
- [x] 事件日志系统（EventLogger，每事件独立 commit，单调序列号）
- [x] 并发事件写入保护（共享 seq 计数器 + asyncio.Lock，避免并发采集时事件主键/事务冲突）
- [x] SSE 实时推送（asyncio.Queue 广播）
- [x] 节点状态快照持久化（WorkflowNodeState）
- [x] 产物存储与下载（Artifact，支持 JSON 详情 / Markdown 导出）
- [x] Markdown 报告下载文件名兼容中文（Content-Disposition 使用 UTF-8 filename*）
- [x] 溯源链接数据模型（TraceLink）
- [x] 节点指数退避重试（最多 3 次，5 分钟超时）
- [x] Review 条件路由（通过/未通过/超限 → 结束或回退）
- [x] CollectionAgent 真实信息采集：按目标产品/竞品/品类/关注维度生成 Tavily 查询，并发采集与去重
- [x] AnalysisAgent 真实结构化分析：基于搜索来源生成 FeatureMatrix、PricingComparison、UserSentimentAnalysis、SWOT
- [x] ReportAgent 真实报告撰写：生成完整 Markdown 竞品分析报告、章节结构与引用列表
- [x] ReviewAgent 真实质量审查：检查完整性、证据来源、分析结构和一致性，不通过时路由回目标节点
- [x] LLM/Tavily 配置兜底：本地占位 key 下仍可生成可诊断草稿，真实 key 下调用外部服务
- [x] 全部 18 个 API 端点
- [x] 端到端流程验证通过（注册 → 访谈 → 启动 → DAG 完成 → 事件/产物查询）
- [ ] LangGraph checkpointer 崩溃恢复
- [ ] 前端界面

## 近期修复

- 修复 `information_collection` 并发搜索时多个异步任务共用同一 DB session 写事件导致的事务冲突；`EventLogger` 现在通过共享锁串行化事件写入，并保证同一 workflow 内 `seq` 单调递增。
- 修复 Markdown 报告下载时中文标题写入 `Content-Disposition` 导致的 `latin-1` 编码错误；下载接口现在同时提供 ASCII fallback 和 UTF-8 文件名。
- 强化 Review 逻辑：缺少真实采集来源或引用时不会误判通过，会生成 `review_fail` / `review_reroute` 事件并打回采集节点。

## 核心业务流程

### 工作流生命周期

```
创建工作流 → 访谈配置 → 确认配置 → 启动 DAG → 后台执行 → 完成/失败
  created    configuring              running                completed/failed
```

1. **创建**：用户创建工作流，状态为 `configuring`
2. **访谈配置**：InterviewAgent 通过多轮 SSE 流式对话，引导用户确定目标产品、竞品范围、分析维度等，自动提取 `WorkflowConfig`
3. **确认启动**：用户确认配置后调用 `/start`，状态转为 `running`，通过 `BackgroundTasks` 启动异步 DAG 执行
4. **DAG 执行**：四个 Agent 按 DAG 顺序协作，支持质量审查驱动的迭代修订
5. **完成**：所有节点执行完毕且审查通过，状态转为 `completed`

### DAG 工作流编排

系统使用 LangGraph StateGraph 构建有向无环图，包含 4 个核心节点和 1 个条件路由：

```
information_collection → analysis → report_writing → review
                                                       │
                                            ┌──────────┴──────────┐
                                          通过                  未通过
                                            │                     │
                                          结束           revision_count < max?
                                                          │            │
                                                         是           否
                                                          │            │
                                                    路由至目标节点     结束
                                                  (collection/analysis/report)
```

**条件路由逻辑**（`_review_router`）：
- 审查通过 → 结束
- 审查未通过且未超过最大修订次数 → 路由到 `review_result.target_node` 指定的节点重新执行
- 超过最大修订次数（默认 3 次）→ 强制结束

### Agent 职责

| Agent | 节点名 | 输入 | 输出 |
|-------|--------|------|------|
| **CollectionAgent** | `information_collection` | WorkflowConfig | 各竞品原始搜索数据 `raw_data` |
| **AnalysisAgent** | `analysis` | raw_data | 功能矩阵、定价对比、用户情感、SWOT 分析 |
| **ReportAgent** | `report_writing` | 四项分析结果 | 完整 Markdown 竞品分析报告 |
| **ReviewAgent** | `review` | 报告内容 | 审查结果（通过/未通过 + 修订目标节点） |

> 当前 4 个业务 Agent 已替换 Stub：配置真实 API key 后会调用 Tavily 和火山方舟兼容 LLM；缺少真实 key 或外部服务失败时会保留可诊断的 fallback 结果，避免静默返回空结构。

### 工作流状态（WorkflowState）

贯穿 DAG 所有节点的共享状态：

```python
WorkflowState = {
    "config":              WorkflowConfig,          # 用户配置
    "competitors":         list[CompetitorInfo],     # 竞品列表
    "raw_data":            dict[str, list],          # 原始采集数据（按竞品分组）
    "collection_errors":   dict[str, str],           # 采集失败记录
    "feature_matrix":      FeatureMatrix | None,     # 功能对比矩阵
    "pricing_comparison":  PricingComparison | None, # 定价对比
    "user_sentiment":      UserSentimentAnalysis | None, # 用户情感分析
    "swot":                SWOTAnalysis | None,      # SWOT 分析
    "report":              ReportOutput | None,      # 最终报告
    "review_result":       ReviewOutput | None,      # 审查结果
    "revision_count":      int,                      # 当前修订轮次
    "max_revisions":       int,                      # 最大修订次数
    "current_phase":       str,                      # 当前阶段
    "workflow_status":     str,                      # 工作流状态
    "errors":              list[ErrorRecord],        # 错误历史
}
```

### 事件与可观测性

- **EventLogger**：每个事件独立写入 `workflow_event` 表并立即 commit（崩溃安全），使用单调递增序列号 `seq`
- **SSE 实时推送**：`SSEManager` 模块级单例，基于 `asyncio.Queue` 向所有订阅客户端广播节点执行进度
- **节点状态快照**：每次节点执行完成后保存完整 state 到 `workflow_node_state` 表，记录耗时、token 用量等指标
- **产物存储**：分析结果和报告作为 `Artifact` 持久化，支持 JSON 详情查看和 Markdown 下载

### 节点重试机制

`execute_with_retry` 提供指数退避重试：
- 最多 3 次重试，每次超时 5 分钟
- 退避间隔：`2^attempt` 秒
- 每次失败记录 `NODE_ERROR` 事件
- 全部失败后抛出 `NodeFatalError`，工作流标记为 `failed`

## API 接口

### Auth 认证
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/auth/register` | 用户注册 |
| POST | `/api/v1/auth/login` | 用户登录（返回 JWT） |
| GET | `/api/v1/auth/me` | 获取当前用户信息 |

### Workflow 工作流管理
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/workflows` | 创建工作流 |
| GET | `/api/v1/workflows` | 工作流列表 |
| GET | `/api/v1/workflows/{id}` | 工作流详情（含 config、phase、revision 等） |
| POST | `/api/v1/workflows/{id}/start` | 确认配置并启动 DAG 执行 |
| POST | `/api/v1/workflows/{id}/retry/{node}` | 重试失败的工作流 |
| DELETE | `/api/v1/workflows/{id}` | 删除工作流（级联删除所有关联数据） |

### Interview 访谈配置
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/workflows/{id}/interview/stream` | SSE 流式访谈对话 |
| GET | `/api/v1/workflows/{id}/interview/history` | 访谈历史记录 |
| POST | `/api/v1/workflows/{id}/interview/confirm` | 确认配置（校验完整性） |

### Event 事件与监控
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/workflows/{id}/events` | 事件列表（分页，支持 node_name/event_type 筛选） |
| GET | `/api/v1/workflows/{id}/stream` | SSE 实时事件流 |
| GET | `/api/v1/workflows/{id}/states` | 节点状态快照历史 |

### Artifact 产物
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/workflows/{id}/artifacts` | 产物列表 |
| GET | `/api/v1/artifacts/{id}` | 产物详情（含 content JSON） |
| GET | `/api/v1/artifacts/{id}/download` | 下载 Markdown 报告 |

### Trace 溯源
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/workflows/{id}/trace` | 溯源链接列表 |

## 项目目录结构

```
backend/
├── app/
│   ├── main.py                    # FastAPI 应用入口
│   ├── config.py                  # 配置管理（pydantic-settings）
│   ├── dependencies.py            # 依赖注入（JWT 认证）
│   ├── api/v1/
│   │   ├── router.py              # 路由聚合
│   │   ├── auth.py                # 认证接口
│   │   ├── workflow.py            # 工作流管理接口
│   │   ├── interview.py           # 访谈配置接口
│   │   ├── event.py               # 事件查询与 SSE 流
│   │   ├── artifact.py            # 产物查询与下载
│   │   └── trace.py               # 溯源链接
│   ├── core/
│   │   ├── orchestrator.py        # LangGraph DAG 编译与条件路由
│   │   ├── graph_nodes.py         # 节点工厂函数（闭包注入 db/logger）
│   │   ├── workflow_executor.py   # BackgroundTasks 工作流执行入口
│   │   └── node_executor.py       # 节点重试与超时控制
│   ├── agents/
│   │   ├── base_agent.py          # Agent 基类（事件记录 + SSE 广播）
│   │   ├── interview_agent.py     # 访谈 Agent（LangChain + Tavily）
│   │   ├── agent_utils.py         # Agent 通用工具（LLM JSON 调用、配置检测、上下文压缩）
│   │   ├── collection_agent.py    # 信息采集 Agent（Tavily 并发搜索 + 来源去重）
│   │   ├── analysis_agent.py      # 多维分析 Agent（功能/定价/情感/SWOT）
│   │   ├── report_agent.py        # 报告撰写 Agent（Markdown 报告 + 引用）
│   │   └── review_agent.py        # 质量审查 Agent（规则/LLM 审查 + 条件回退）
│   ├── schemas/
│   │   ├── workflow_state.py      # LangGraph WorkflowState TypedDict
│   │   ├── workflow.py            # WorkflowConfig / WorkflowStatus
│   │   ├── event.py               # EventType 枚举与 payload 类型
│   │   ├── competitor.py          # CompetitorInfo / SearchResult
│   │   ├── feature.py             # FeatureMatrix
│   │   ├── pricing.py             # PricingComparison
│   │   ├── sentiment.py           # UserSentimentAnalysis
│   │   ├── swot.py                # SWOTAnalysis
│   │   ├── report.py              # ReportOutput / ReportSection
│   │   ├── review.py              # ReviewOutput / ReviewCheck
│   │   ├── interview.py           # 访谈消息与配置提取
│   │   ├── auth.py                # 认证相关
│   │   └── common.py              # SourceRef / ErrorRecord 等公共类型
│   ├── services/
│   │   ├── workflow_service.py    # 工作流 CRUD 与生命周期管理
│   │   ├── interview_service.py   # 访谈流式处理与配置提取
│   │   ├── event_service.py       # EventLogger 与事件查询
│   │   ├── sse_service.py         # SSE 广播管理器
│   │   └── auth_service.py        # 用户认证与 JWT
│   └── db/
│       ├── base.py                # SQLAlchemy Base
│       ├── session.py             # 异步会话工厂
│       └── models/
│           ├── user.py            # User
│           ├── workflow.py        # Workflow / InterviewMessage
│           ├── workflow_event.py  # 事件日志
│           ├── workflow_node_state.py # 节点状态快照
│           ├── artifact.py        # 分析产物
│           ├── trace_link.py      # 溯源链接
│           └── search_template.py # 搜索模板
├── tests/
│   ├── conftest.py                # 测试夹具（SQLite 内存 DB）
│   └── test_api/
│       ├── test_auth.py
│       ├── test_workflow.py
│       └── test_interview.py
└── .env                           # 环境变量配置
```

## 环境要求
- Python 3.11+
- PostgreSQL 14+

## 后端启动步骤

1. 进入 backend 目录
```bash
cd backend
```

2. 创建虚拟环境并激活
```bash
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/Mac
```

3. 安装依赖
```bash
pip install -e .
```

4. 确认配置文件 `.env` 已正确填写：
```
DATABASE_URL=postgresql+asyncpg://postgres:xxx@127.0.0.1:5432/dagents
LLM_API_KEY=你的火山方舟APIKey
LLM_BASE_URL=https://ark.cn-beijing.volces.com/api/v3/
LLM_MODEL=你的模型接入点ID
TAVILY_API_KEY=你的Tavily APIKey
```

5. 在 PostgreSQL 中提前创建好 dagents 数据库：
```sql
CREATE DATABASE dagents;
```

6. 启动后端服务（首次启动自动建表）
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

7. 访问自动生成的 API 文档：
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## 运行测试
```bash
cd backend
pip install pytest pytest-asyncio httpx aiosqlite
python -m pytest -v
```

## 数据库表结构

### user — 用户账户

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | UUID | PK | 用户唯一标识 |
| `username` | VARCHAR(64) | UNIQUE, NOT NULL | 用户名 |
| `email` | VARCHAR(255) | UNIQUE, NOT NULL | 邮箱 |
| `hashed_password` | VARCHAR(255) | NOT NULL | bcrypt 哈希密码 |
| `display_name` | VARCHAR(128) | NULL | 显示名称 |
| `is_active` | BOOLEAN | NOT NULL, DEFAULT TRUE | 账户是否启用 |
| `created_at` | TIMESTAMPTZ | NOT NULL | 创建时间 |
| `updated_at` | TIMESTAMPTZ | NOT NULL | 更新时间（自动更新） |

### workflow — 工作流聚合根

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | UUID | PK | 工作流唯一标识 |
| `owner_id` | UUID | FK → user.id CASCADE, NOT NULL | 创建者 |
| `title` | VARCHAR(255) | NOT NULL | 工作流标题 |
| `status` | VARCHAR(32) | NOT NULL, DEFAULT 'created' | 状态：created / configuring / running / paused / completed / failed / cancelled |
| `current_phase` | VARCHAR(32) | NULL | 当前 DAG 阶段：collecting / analyzing / reporting / reviewing / done |
| `config` | JSON | NOT NULL, DEFAULT '{}' | 工作流配置（目标产品、竞品列表、分析维度等） |
| `revision_count` | INTEGER | NOT NULL, DEFAULT 0 | 当前修订轮次 |
| `max_revisions` | INTEGER | NOT NULL, DEFAULT 3 | 最大修订次数 |
| `total_tokens` | INTEGER | NOT NULL, DEFAULT 0 | 累计 LLM token 消耗 |
| `langgraph_checkpoint_id` | VARCHAR(128) | NULL | LangGraph checkpoint 引用 |
| `error_message` | TEXT | NULL | 失败时的错误信息 |
| `pause_state` | JSON | NULL | 暂停元数据（reason / options / paused_by_node / paused_at），checkpoint 负责 DAG state |
| `execution_attempt` | INTEGER | NOT NULL, DEFAULT 1 | 执行批次号，每次 retry 递增 |
| `created_at` | TIMESTAMPTZ | NOT NULL | 创建时间 |
| `updated_at` | TIMESTAMPTZ | NOT NULL | 更新时间（自动更新） |
| `completed_at` | TIMESTAMPTZ | NULL | 完成时间 |

### interview_message — 访谈消息历史

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | UUID | PK | 消息唯一标识 |
| `workflow_id` | UUID | FK → workflow.id CASCADE, NOT NULL | 所属工作流 |
| `role` | VARCHAR(16) | NOT NULL | 角色：user / assistant |
| `content` | TEXT | NOT NULL | 消息内容 |
| `created_at` | TIMESTAMPTZ | NOT NULL | 创建时间 |

### workflow_event — 事件日志

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | UUID | PK | 事件唯一标识 |
| `workflow_id` | UUID | FK → workflow.id CASCADE, NOT NULL | 所属工作流 |
| `node_name` | VARCHAR(64) | NOT NULL | 产生事件的节点名 |
| `iteration` | INTEGER | NOT NULL, DEFAULT 0 | 节点迭代轮次 |
| `event_type` | VARCHAR(32) | NOT NULL | 事件类型（见 EventType 枚举） |
| `seq` | INTEGER | NOT NULL | 工作流内单调递增序列号 |
| `execution_attempt` | INTEGER | NOT NULL, DEFAULT 1 | 执行批次号 |
| `payload` | JSON | NOT NULL, DEFAULT '{}' | 事件负载数据 |
| `created_at` | TIMESTAMPTZ | NOT NULL | 创建时间 |

### workflow_node_state — 节点执行快照

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | UUID | PK | 快照唯一标识 |
| `workflow_id` | UUID | FK → workflow.id CASCADE, NOT NULL | 所属工作流 |
| `node_name` | VARCHAR(64) | NOT NULL | 节点名 |
| `iteration` | INTEGER | NOT NULL, DEFAULT 0 | 节点迭代轮次 |
| `state_snapshot` | JSON | NOT NULL, DEFAULT '{}' | 执行后完整 WorkflowState 快照 |
| `artifact_ids` | JSON | NOT NULL, DEFAULT '[]' | 本次产生的产物 ID 列表 |
| `tokens_input` | INTEGER | NOT NULL, DEFAULT 0 | LLM 输入 token 数 |
| `tokens_output` | INTEGER | NOT NULL, DEFAULT 0 | LLM 输出 token 数 |
| `duration_ms` | INTEGER | NOT NULL, DEFAULT 0 | 执行耗时（毫秒） |
| `model_name` | VARCHAR(64) | NULL | 使用的 LLM 模型名 |
| `is_error` | BOOLEAN | NOT NULL, DEFAULT FALSE | 是否为错误快照 |
| `error_message` | TEXT | NULL | 错误信息 |
| `execution_attempt` | INTEGER | NOT NULL, DEFAULT 1 | 执行批次号 |
| `created_at` | TIMESTAMPTZ | NOT NULL | 创建时间 |

### artifact — 工作流产物

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | UUID | PK | 产物唯一标识 |
| `workflow_id` | UUID | FK → workflow.id CASCADE, NOT NULL | 所属工作流 |
| `artifact_type` | VARCHAR(32) | NOT NULL | 产物类型：collection_raw / feature_matrix / pricing_comparison / user_sentiment / swot_analysis / report |
| `title` | VARCHAR(255) | NOT NULL | 产物标题 |
| `content` | JSON | NOT NULL, DEFAULT '{}' | 结构化产物内容 |
| `content_text` | TEXT | NULL | 纯文本 / Markdown 内容（用于全文检索和下载） |
| `format_version` | VARCHAR(16) | NOT NULL, DEFAULT '1.0' | 内容格式版本 |
| `created_by_node` | VARCHAR(64) | NULL | 创建该产物的节点名 |
| `execution_attempt` | INTEGER | NOT NULL, DEFAULT 1 | 执行批次号 |
| `created_at` | TIMESTAMPTZ | NOT NULL | 创建时间 |
| `updated_at` | TIMESTAMPTZ | NOT NULL | 更新时间（自动更新） |

### trace_link — 溯源链接

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | UUID | PK | 溯源链接唯一标识 |
| `artifact_id` | UUID | FK → artifact.id CASCADE, NOT NULL | 所属产物 |
| `section_path` | VARCHAR(255) | NULL | 报告中的章节路径 |
| `claim_text` | TEXT | NULL | 被溯源的声明文本 |
| `source_url` | TEXT | NOT NULL | 来源 URL |
| `source_title` | VARCHAR(512) | NULL | 来源标题 |
| `source_snippet` | TEXT | NULL | 来源摘要片段 |
| `source_type` | VARCHAR(32) | NOT NULL, DEFAULT 'web' | 来源类型 |
| `retrieved_at` | TIMESTAMPTZ | NOT NULL | 来源检索时间 |
| `confidence` | FLOAT | NULL | 置信度评分 |
| `is_verified` | BOOLEAN | NOT NULL, DEFAULT FALSE | 是否人工验证 |
| `created_at` | TIMESTAMPTZ | NOT NULL | 创建时间 |

### search_template — 搜索模板

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | UUID | PK | 模板唯一标识 |
| `category` | VARCHAR(64) | UNIQUE, NOT NULL | 产品类别 |
| `templates` | JSON | NOT NULL, DEFAULT '{}' | 搜索模板配置 |
| `description` | VARCHAR(255) | NULL | 模板描述 |
| `created_at` | TIMESTAMPTZ | NOT NULL | 创建时间 |

## 一个跑通的工作流示例

### 用户访谈 Interview Agent

1. 登录后取得token

POST api/v1/auth/login

2. 创建工作流

POST api/v1/workflows

传入title: "分析英雄牌钢笔的竞品"

3. 进行访谈（多轮对话）

POST api/v1/workflows/{workflow_id}/interview/stream

user:
{
  "workflow_id": workflow_id,
  "user_message": "你好！帮我从价格、质量、产量和供应链三个方面分析英雄牌钢笔和其他知名厂商产品"
}

assistant:
好的，我先和你逐步确认本次竞品分析的相关信息：
首先我初步判断你要分析的目标产品是英雄牌钢笔，产品属于硬件产品分类，你想要重点关注的分析维度是价格、质量、产量与供应链这三个部分，请问这几点的理解是正确的吗？

除此之外还需要和你确认几个细节：你最多希望对比多少个竞品呢？有没有指定具体要对标分析的其他钢笔品牌，还是后续会自动为你筛选对应数量的主流知名钢笔竞品？另外你有没有其他额外的分析要求呀？

user:
{
  "workflow_id": workflow_id,
  "user_message": "最多对比6个，没有指定的品牌"
}

assistant:
📋 已收集到的竞品分析配置信息如下，请你确认：
| 配置项 | 详情 |
| ---- | ---- |
| 目标产品 | 英雄牌钢笔 |
| 产品类别 | 硬件产品 |
| 重点关注维度 | 价格、质量、产量与供应链 |
| 最大对比竞品数量 | 6个 |
| 指定竞品列表 | 无指定品牌，将自动筛选6个主流知名钢笔厂商作为对标对象 |
| 额外分析要求 | 无特殊额外要求 |

确认配置无误后，将按照以下规则启动分析流程：
```json
{
  "target_product": "英雄牌钢笔",
  "product_category": "硬件产品",
  "focus_dimensions": ["价格", "质量", "产量与供应链"],
  "competitor_count": 6,
  "competitors": [],
  "language": "zh",
  "extra_requirements": "无特殊额外分析要求"
}
```
---CONFIG_COMPLETE---

