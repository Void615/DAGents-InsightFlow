# Changelog

## 2026-05-25

### 1. 增加全局异常处理架构

引入 Java Spring `@ExceptionHandler` 风格的全局异常处理机制，替换原有的 `return None` + 手动 `HTTPException` 模式。

#### 修复方案

定义 `AppException` 基类（携带 `error_code` / `message` / `status_code` / `details`）及 7 个子类。在 `main.py` 注册全局异常 handler：`AppException` → 结构化 JSON 响应；`Exception` → 500 兜底。所有 service / dependency / API 路由中的 `return None` 和 `raise HTTPException` 替换为对应的业务异常。

#### 新增文件

- `backend/app/exceptions.py` — 业务异常层级：`AppException` 基类 + 7 个子类（`WorkflowNotFoundError`、`InvalidStateTransitionError`、`ConfigIncompleteError`、`InvalidCredentialsError`、`InvalidTokenError`、`DuplicateResourceError`、`ArtifactNotFoundError`）

#### 修改的文件

- `backend/app/main.py` — 注册全局 handler
- `backend/app/services/workflow_service.py` — `return None` → `raise` 对应异常
- `backend/app/services/auth_service.py` — `authenticate_user` 返回 None → `raise InvalidCredentialsError`
- `backend/app/dependencies.py` — 4 处 `raise HTTPException(401)` → `raise InvalidTokenError`
- `backend/app/api/v1/*.py` — 移除 `HTTPException` 导入，手动 `raise HTTPException` → 业务异常

---

### 2. 结构化错误记录与节点状态修复

#### 修复方案

新增 `_extract_error_info()` 解包 `NodeFatalError.last_error` 获取 `AppException` 的结构化字段。抽取 `_execute_node()` 公共 helper，统一在 `NodeFatalError` 时保存 `WorkflowNodeState` 并标记 `is_error=True`，修复 `is_error` 列从未被使用的死字段。

#### 修改的文件

- `backend/app/core/workflow_executor.py` — 新增 `_extract_error_info()`，`WORKFLOW_FAILED` payload 包含结构化错误信息
- `backend/app/core/node_executor.py` — `NODE_ERROR` payload 使用业务 `error_code`
- `backend/app/core/graph_nodes.py` — 抽取 `_execute_node()`，统一错误快照保存

---

### 3. 查询层重构

将分散在各 service 和 API 路由中的 15 处 SQLAlchemy 内联查询抽取到 `backend/app/db/queries/` 目录，按业务域分文件。

#### 新增文件

- `backend/app/db/queries/user_queries.py` — `get_user_by_email`、`get_user_by_username`、`get_user_by_id`
- `backend/app/db/queries/workflow_queries.py` — `get_workflow_by_id`、`get_workflow_by_uuid`、`get_user_workflows`、`get_message_history`
- `backend/app/db/queries/event_queries.py` — `get_events`、`count_events`、`get_node_states`
- `backend/app/db/queries/artifact_queries.py` — `get_workflow_artifacts`、`get_artifact_by_id`、`get_artifact_ids_by_workflow`、`get_trace_links`

---

### 4. 安全与代码质量修复

修复 5 个安全及代码质量问题。

#### 修复方案

- **模块级副作用改为懒初始化**：`tavily_client` 和 `interview_agent` 从模块导入时实例化改为首次调用时懒初始化，避免 API key 为空或 LLM 配置错误时静默失败
- **JWT 密钥强制显式配置**：`JWT_SECRET_KEY` 移除不安全默认值 `"change-me-in-production"`，未配置时启动即报错
- **创建 Workflow 改用 JSON body**：`POST /workflows` 的 `title` 参数从 query string 改为 JSON 请求体 `WorkflowCreate` schema
- **密码与用户名添加长度校验**：`UserRegister.password` 要求 `min_length=8`，`username` 要求 `min_length=3`
- **认证接口添加频率限制**：新增 `RateLimiter` 内存固定窗口实现，登录 10 次/60s，注册 5 次/60s，超限返回 429

#### 新增文件

- `backend/app/services/rate_limiter.py` — 内存固定窗口频率限制器

#### 修改的文件

- `backend/app/services/interview_service.py` — 懒初始化 `tavily_client` / `interview_agent`；`import json` 移至顶部
- `backend/app/config.py` — `JWT_SECRET_KEY` 移除默认值，强制配置
- `backend/app/schemas/workflow.py` — 新增 `WorkflowCreate` 请求体 schema
- `backend/app/api/v1/workflow.py` — `create_new_workflow` 从 query param 改为 Body
- `backend/app/schemas/auth.py` — `password` / `username` 添加 `min_length` 校验
- `backend/app/api/v1/auth.py` — `login` / `register` 添加 `Depends(rate_limit)`
- `backend/tests/conftest.py` — 添加 `JWT_SECRET_KEY` 测试默认值；覆盖 rate limiter 为 no-op
- `backend/tests/test_api/*.py` — 更新密码长度和 JSON body 调用方式
- `backend/tests/test_exceptions.py` — 同步更新

---

### 5. 引入 execution_attempt 执行批次隔离机制

节点级操作（event 写入、node_state 快照、artifact 产出）各自独立 `db.commit()`，导致外层 `db.rollback()` 是死代码——失败时所有已持久化的数据无法回滚。同时 retry 端点重跑 DAG 时，新旧两次执行的 events/node_states/artifacts 混在同一 `workflow_id` 下，无法按执行批次区分。

#### 修复方案

在 `Workflow`、`WorkflowEvent`、`WorkflowNodeState`、`Artifact` 四张表各新增 `execution_attempt` 整数列（DEFAULT 1）。每次 `run_workflow` 调用从 `workflow.execution_attempt` 读取当前批次号，全链路透传至所有写入点。retry 端点将 `workflow.execution_attempt += 1`，后续执行的所有行自动带上新批次号。移除 `workflow_executor.py` 中的死代码 `db.rollback()`，替换为注释说明节点级 commit 的设计意图。查询函数增加可选 `execution_attempt` 过滤参数。

#### 新增文件

- `backend/migrations/001_add_execution_attempt.sql` — 4 张表加列的数据库迁移脚本

#### 修改的文件

- `backend/app/db/models/workflow.py` — `Workflow` 新增 `execution_attempt` 列
- `backend/app/db/models/workflow_event.py` — `WorkflowEvent` 新增 `execution_attempt` 列
- `backend/app/db/models/workflow_node_state.py` — `WorkflowNodeState` 新增 `execution_attempt` 列
- `backend/app/db/models/artifact.py` — `Artifact` 新增 `execution_attempt` 列
- `backend/app/services/event_service.py` — `EventLogger` 构造函数接收并透传 `execution_attempt`；`log()` 写入；`with_node()` 传播
- `backend/app/core/graph_nodes.py` — `_save_node_state`、`_save_artifact`、`_execute_node`、4 个工厂函数全链路透传 `execution_attempt`
- `backend/app/core/orchestrator.py` — `compile_workflow_graph` 接收 `execution_attempt` 并传入 4 个工厂
- `backend/app/core/workflow_executor.py` — 从 `workflow.execution_attempt` 读取并传入下游；删除无意义的 `db.rollback()`，替换为注释说明
- `backend/app/api/v1/workflow.py` — retry 端点 `workflow.execution_attempt += 1`，返回值附带新批次号
- `backend/app/db/queries/event_queries.py` — `get_events`、`count_events`、`get_node_states` 新增可选 `execution_attempt` 过滤参数
- `backend/app/db/queries/artifact_queries.py` — `get_workflow_artifacts`、`get_artifact_ids_by_workflow` 新增可选 `execution_attempt` 过滤参数

#### 可能的潜在问题

- **部分 attempt 数据不完整**：DAG 跑到中途崩溃时，已执行节点的事件/产物已持久化（该 attempt 内部不完整），但查询时可通过 `execution_attempt` 过滤。不影响后续 attempt
- **老 attempt 数据堆积**：无自动清理机制，失败的 attempt 数据永久保留。后续可按需增加 TTL 清理或手动归档

---

## 2026-05-26

### 6. Agent 层 LLM 流式输出与调用模式工程化

原有 `invoke_json_model` 在三个分析 agent（analysis / report / review）中使用 `ainvoke` 一次性获取完整响应，SSE 层只能广播粗粒度的生命周期事件（NODE_START / NODE_COMPLETE / LLM_RESPONSE），前端看不到 LLM 逐 token 生成的实时进度。同时三个 agent 各自重复相同的调用样板代码（LLM_REQUEST 日志 → on_token 闭包 → invoke_json_model）。

#### 修复方案

**流式输出**：`invoke_json_model` 新增可选 `stream_callback` 参数。当传入回调时走 `astream` 逐 chunk 推送 token，否则回退到 `ainvoke`；两种路径最终都经过 `extract_json_object` → Pydantic 校验链。`BaseAgent` 新增 `stream_llm_token` 方法，将 token 以 `LLM_STREAM` 事件类型通过 SSE 广播（不写 DB，避免 token 粒度写入撑爆数据库）。`EventType` 枚举新增 `LLM_STREAM = "llm_stream"`。

**模式提取**：在 `BaseAgent` 中新增泛型方法 `invoke_llm(system_prompt, user_payload, schema, event_logger, workflow_id, model_task, ...)`，封装完整调用链：记录 LLM_REQUEST → 创建内部 `_on_token` 回调（调用 `stream_llm_token`）→ 传入 `invoke_json_model` → 返回 Pydantic 结构化对象。三个 agent 不再直接导入 `invoke_json_model`。

**可读性**：7 个 agent 文件全面补充注释，说明每处非显而易见的 WHY：JSON 提取两阶段策略、AnalysisBundle 单次调用设计、引用构建与 LLM 分离的原因、哨兵 vs 宽松 JSON 匹配的可靠性差异、asyncio.gather 的异常隔离策略、搜索模板按产品类别的差异化设计等。

#### 新增文件

（无）

#### 修改的文件

- `backend/app/schemas/event.py` — `EventType` 新增 `LLM_STREAM = "llm_stream"`
- `backend/app/agents/agent_utils.py` — `invoke_json_model` 新增可选 `stream_callback` 参数；新增 `StreamCallback` 类型别名；补充核心函数文档注释
- `backend/app/agents/base_agent.py` — 新增 `stream_llm_token`（SSE 广播 token，不写 DB）和 `invoke_llm`（泛型 LLM 调用封装）两个方法；补充三段式方法分组注释
- `backend/app/agents/analysis_agent.py` — 移除 `invoke_json_model` 直接导入；LLM 调用改为 `self.invoke_llm(...)`；补充注释
- `backend/app/agents/report_agent.py` — 同上；补充引用构建与 LLM 分离的设计注释
- `backend/app/agents/review_agent.py` — 同上；补充规则审查四维度及硬性门槛注释
- `backend/app/agents/collection_agent.py` — 补充搜索模板设计、并发隔离策略、URL 去重注释
- `backend/app/agents/interview_agent.py` — 补充架构差异说明（独立于 DAG、哨兵机制）、清理未使用的 `HumanMessage` 导入

#### 可能的潜在问题

- **JSON 提取仍依赖 prompt engineering**：当前 LLM 通过系统提示中的手写 JSON schema 文本输出自由格式 JSON，再由 regex 提取、Pydantic 校验。schema 变更需同时修改系统提示和 Pydantic model，容易不同步。代码中已标注迁移路径：后续替换为 `with_structured_output()` / function calling，届时 `extract_json_object` 和系统提示中的手写 schema 即可删除

---

### 7. 人在回路 (Human-in-the-Loop) 机制

引入泛化的人在回路暂停/恢复机制，使任意 agent 可在需要人工决策时暂停 DAG 执行，并通过 SSE 推送决策选项到前端，待用户决策后从断点恢复。

#### 核心设计

- **暂停信号**：agent 通过返回值约定 `{"__pause__": True, "pause_reason": "...", "pause_options": [...], ...}` 表达需要人工输入，不抛业务异常
- **LangGraph 原生中断**：`_execute_node` 检测到 `__pause__` 后调用 LangGraph `interrupt()` 暂停图执行，checkpoint 自动保存
- **恢复机制**：`POST /{id}/decide` 端点接收人工决策（resume/jump/approve/abort），通过 `Command(resume=..., update=...)` 从 checkpoint 恢复，`human_decision` 注入 state 避免无限循环
- **PostgreSQL checkpointer**：引入 `langgraph-checkpoint-postgres`，替代手动 JSON 序列化 state，支持进程重启后恢复
- **`run_workflow` 三态处理**：completed / paused / failed，暂停时 `finally` 跳过 `close_workflow()` 保持 SSE 连接
- **review agent 适配**：不再自动递增 `revision_count` 并重试，而是返回 `__pause__` 暂停信号

#### 新建文件

- `backend/app/schemas/decision.py` — `DecisionAction` 枚举（resume/jump/approve/abort）、`DecisionRequest` schema
- `backend/app/core/checkpointer.py` — PostgreSQL `PostgresSaver` 单例管理，懒初始化 + `setup()`

#### 修改的文件

- `backend/app/schemas/event.py` — `EventType` 新增 `WORKFLOW_RESUMED`；已有 `WORKFLOW_PAUSED` 开始使用
- `backend/app/schemas/workflow.py` — `WorkflowStatus` 新增 `PAUSED`
- `backend/app/schemas/workflow_state.py` — `WorkflowState` 新增 `human_decision: dict` 可选字段
- `backend/app/db/models/workflow.py` — `Workflow` 新增 `pause_state` JSON 列（存暂停元数据，checkpoint 负责 DAG state）
- `backend/app/core/node_executor.py` — `execute_with_retry` 新增 `except GraphInterrupt: raise`，暂停信号不被重试
- `backend/app/core/graph_nodes.py` — `_execute_node` 检测 `__pause__` 并调用 `interrupt()`；恢复路径合并 `human_decision` 并递增 `revision_count`
- `backend/app/core/orchestrator.py` — `compile_workflow_graph` 新增 `checkpointer` 参数；`_review_router` 优先使用 `human_decision` 中的 `target_node`
- `backend/app/core/workflow_executor.py` — `run_workflow` 新增 `except GraphInterrupt` 三态处理；新增 `resume_workflow` 函数；`finally` 中 `status != "paused"` 才关闭 SSE
- `backend/app/agents/review_agent.py` — `passed=False` 时返回 `__pause__` 信号，包含 pause_options 和 pause_context；达重试上限时正常返回
- `backend/app/api/v1/workflow.py` — 新增 `POST /{id}/decide`（resume 走后台恢复，approve/abort 同步完成）；修改 `POST /{id}/retry/{node_name}` 支持 `paused` 状态；详情接口新增 `pause_state` 字段
- `backend/app/main.py` — `lifespan` 启动事件中预热 checkpointer
- `backend/pyproject.toml` — 新增 `langgraph-checkpoint-postgres` 依赖

#### 可能的潜在问题

- **interrupt() 后节点重新执行**：LangGraph 从 checkpoint 恢复时会重新执行整个节点函数。通过 `human_decision` 注入 state 并检查 `state.get("human_decision")` 来跳过二次暂停，但 agent 的 LLM 调用也会重新执行，带来额外的 token 开销。后续可考虑通过 `_execute_node` 的快速路径优化，在有 `human_decision` 时跳过 agent 调用直接返回缓存结果。
- **checkpointer 表与业务表不在同一事务**：`checkpoints`/`checkpoint_blobs`/`checkpoint_writes` 三张表由 LangGraph checkpointer 独立管理（通过 psycopg 连接池），与 SQLAlchemy 管理的业务表不在同一事务边界。极端情况下可能出现业务表标记为 paused 但 checkpoint 未保存（或反之），导致 resume 时状态不一致。当前通过先保存 checkpoint（interrupt 内部），再提交业务事务来降低风险，但无法完全消除。
- **并发恢复风险**：当前未对 `workflow.status` 加乐观锁或分布式锁，理论上可能有两个并发 `POST /decide` 同时触发 resume。后续可增加 `status` 字段的 CAS 检查或引入 Redis 分布式锁。
