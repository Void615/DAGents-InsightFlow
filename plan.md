# DAGents-InsightFlow 详细设计方案 v2

# 目录

1. [系统架构总览](#1-系统架构总览)
2. [Agent 协作模式](#2-agent-协作模式)
3. [子 Agent 功能与 Skill 设计](#3-子-agent-功能与-skill-设计)
4. [State 设计：Schema 与流转策略](#4-state-设计schema-与流转策略)
5. [Event 设计：Schema 与流转策略](#5-event-设计schema-与流转策略)
6. [数据库设计](#6-数据库设计)
7. [错误处理与回滚策略](#7-错误处理与回滚策略)
8. [上下文管理策略](#8-上下文管理策略)
9. [可观测性与溯源设计](#9-可观测性与溯源设计)
10. [API 设计](#10-api-设计)
11. [安全与配置](#11-安全与配置)
12. [实现路线图](#12-实现路线图)

---

## 1. 系统架构总览

### 1.1 整体架构

```
┌─────────────┐     HTTP/SSE      ┌──────────────────────────────────┐
│  Next.js     │ ◄──────────────► │  FastAPI 后端                     │
│  Frontend    │                   │                                  │
└─────────────┘                   │  ┌────────────────────────────┐  │
                                  │  │  LangGraph Workflow Engine │  │
                                  │  │  ┌──────┐  ┌──────┐       │  │
                                  │  │  │Collect│─►│Analyze│       │  │
                                  │  │  └──┬───┘  └──┬───┘       │  │
                                  │  │     │         │            │  │
                                  │  │  ┌──┴─────────┴──┐        │  │
                                  │  │  │    Report      │        │  │
                                  │  │  └──────┬────────┘        │  │
                                  │  │     ▲   │   ▼             │  │
                                  │  │     │ ┌─┴──────┐         │  │
                                  │  │     └─┤ Review │         │  │
                                  │  │       └────────┘         │  │
                                  │  └────────────────────────────┘  │
                                  │          │                       │
                                  │  ┌───────┴───────────────────┐   │
                                  │  │  Celery Worker             │   │
                                  │  │  (异步执行工作流)          │   │
                                  │  └───────────────────────────┘   │
                                  │          │                       │
                                  │  ┌───────┴──────┐  ┌──────────┐ │
                                  │  │ PostgreSQL   │  │ LangSmith │ │
                                  │  │ (业务DB+     │  │ (LLM追踪) │ │
                                  │  │  LangGraph   │  └──────────┘ │
                                  │  │  Checkpoint) │               │
                                  │  └──────────────┘               │
                                  └──────────────────────────────────┘
```

### 1.2 核心设计原则

| 原则 | 说明 |
|------|------|
| **双轨持久化** | LangGraph PostgresSaver 负责运行时 checkpoint；自定义表负责结构化快照与事件日志 |
| **Event 独立行** | 每个事件一行，不追加 JSONB 数组，支持高效查询与分页 |
| **反馈闭环** | Review 不通过时带结构化反馈打回至指定节点，最多 3 次迭代 |
| **全链路溯源** | 每个分析结论可通过 `trace_link` 追溯到原始 URL |
| **失败可恢复** | 节点级重试 + 工作流级 checkpoint 恢复 |

---

## 2. Agent 协作模式

### 2.1 模式选择：结构化 DAG + 条件路由

不使用完全动态的 Supervisor 模式（过于不确定且不可调试），也不使用完全硬编码的顺序链（无法支持反馈闭环）。采用 **LangGraph StateGraph + 条件边** 实现结构化 DAG：

```
                      ┌──────────────┐
                      │  用户访谈      │  ← 前置步骤（多轮对话，完成后锁定 config）
                      │ (pre-workflow)│
                      └──────┬───────┘
                             │ 用户确认后触发 workflow
                             ▼
                      ┌──────────────┐
                      │ 信息采集      │  ← 可并行采集多个竞品
                      └──────┬───────┘
                             │
                             ▼
                      ┌──────────────┐
                      │ 分析          │  ← 功能对比 + 定价分析 + 用户情感 + SWOT
                      └──────┬───────┘
                             │
                             ▼
                      ┌──────────────┐
                      │ 报告撰写      │  ← 结构化报告 + 内联引用
                      └──────┬───────┘
                             │
                             ▼
                      ┌──────────────┐
                 ┌───►│ 审查          ├─── pass ──► [完成]
                 │    └──────┬───────┘
                 │           │ fail + target_node
                 │           ▼
                 └── 打回至 【信息采集】或【分析】
                         (revision_count < max_revisions)
```

### 2.2 用户访谈为何是前置步骤

| 放在 DAG 内 | 放在前置 | 选择 |
|:---|:---|:---:|
| 需要 LangGraph interrupt 机制暂停等待 | 普通 FastAPI 路由 + 多轮对话 | **前置** |
| DAG 运行中无法自由多轮交互 | 不受 DAG 约束，体验更自然 | |
| 人不在时阻塞整个 DAG 执行 | 确认后 DAG 一次性跑完 | |

用户访谈阶段产出 `WorkflowConfig`（目标产品、品类、关注维度、竞品数量上限等），确认后固化为不可变配置传入 DAG。

### 2.3 信息采集的并行策略

采集阶段对每个竞品并发发起搜索，**在单个节点内使用 `asyncio.gather` 并行调用**，而非 LangGraph 的 `Send` fan-out：

| 方式 | 优点 | 缺点 |
|------|------|------|
| `Send` fan-out | 每个竞品独立 checkpoint | 实现复杂，3 周项目性价比低 |
| `asyncio.gather` 节点内并行 | 实现简单，单个 checkpoint | checkpoint 粒度较粗 |

`asyncio.gather` 内部每个竞品的搜索失败不阻断其他竞品，节点完成后汇总结果写入 state。

---

## 3. 子 Agent 功能与 Skill 设计

每个 Agent 是一个 LangGraph 节点函数，内部使用 LangChain tool-calling 模式。

### 3.1 用户访谈 Agent (pre-workflow)

**定位**：多轮对话，不进入 DAG。

**输入**：

```python
class InterviewInput(BaseModel):
    user_message: str  # 用户当前轮的消息
```

**输出**：

```python
class InterviewOutput(BaseModel):
    response: str                          # 本轮回复
    is_complete: bool                      # 访谈是否结束
    extracted_config: Optional[WorkflowConfig]  # 完成后提取的配置

class WorkflowConfig(BaseModel):
    target_product: str                    # "Notion"
    product_category: str                  # "SaaS / 协作工具"
    focus_dimensions: list[str]            # ["功能", "定价", "用户评价", "市场定位"]
    competitor_count: int                  # 最多分析 5 个竞品
    language: str = "zh"                   # 报告语言
    extra_requirements: str = ""           # 用户额外要求
```

**Skill（工具）**：

| 工具名 | 功能 |
|--------|------|
| `ask_clarification` | 针对模糊回答生成追问 |
| `confirm_config` | 汇总理解，生成确认卡片 |
| `suggest_competitors` | 根据目标产品建议可能竞品（Tavily 快速搜索） |

**Prompt 要点**：结构化引导用户明确"要分析什么产品、关注什么维度、需要多少竞品"，避免开放式闲聊。

---

### 3.2 信息采集 Agent

**定位**：DAG 第一个节点，并发搜索收集所有竞品信息。

**输入（state 子集）**：

```python
class CollectionInput(BaseModel):
    target_product: str
    product_category: str
    competitors: list[str]          # 竞品名列表
    focus_dimensions: list[str]
    language: str
```

**输出（写入 state）**：

```python
class CollectionOutput(BaseModel):
    raw_data: dict[str, list[SearchResult]]  # {竞品名: [搜索结果]}
    collection_errors: dict[str, str]         # {竞品名: 错误信息}

class SearchResult(BaseModel):
    url: str
    title: str
    snippet: str                        # Tavily 摘要
    content_summary: Optional[str]      # 全文提取后的摘要
    relevance_score: float              # 0-1
    retrieved_at: datetime
```

**Skill（工具）**：

| 工具名 | 功能 | 底层 |
|--------|------|------|
| `search_competitive_info` | 定向搜索竞品信息 | Tavily `search` |
| `extract_page_content` | 抓取+摘要页面正文 | Tavily `extract` + LLM 摘要 |
| `search_user_reviews` | 搜索用户评价（特定站点/关键词） | Tavily + 站点过滤 |
| `search_pricing` | 搜索定价信息 | Tavily + 关键词模板 |
| `deduplicate_sources` | 合并重复/相似来源 | LLM 去重 |

**搜索模板预设**：

根据 `product_category` 加载不同的搜索查询模板：

```
SaaS:        "{competitor} 功能对比 定价 用户评价 site:zhihu.com OR site:sspai.com"
移动应用:    "{competitor} 功能 评分 用户评价 site:app Store"
硬件产品:    "{competitor} 参数 价格 评测 site:zhihu.com OR site:smzdm.com"
```

---

### 3.3 分析 Agent

**定位**：将采集到的结构化+非结构化数据转化为对比分析。

**输入（state 子集）**：

```python
class AnalysisInput(BaseModel):
    target_product: str
    competitors: list[str]
    raw_data: dict[str, list[SearchResult]]       # 采集结果
    context_summaries: dict[str, str]              # 上下文管理器压缩后的摘要
    focus_dimensions: list[str]
```

**输出（写入 state）**：

```python
class AnalysisOutput(BaseModel):
    feature_matrix: FeatureMatrix
    pricing_comparison: PricingComparison
    user_sentiment: UserSentimentAnalysis
    swot: SWOTAnalysis
    analysis_sources: list[SourceRef]  # 分析段落的溯源引用

class FeatureMatrix(BaseModel):
    dimensions: list[str]               # ["协作", "AI能力", "集成"]
    matrix: list[dict]                  # [{feature, products: {A: "支持", B: "不支持"}}]

class PricingComparison(BaseModel):
    plans: list[PricingPlan]
    summary: str                        # 定价策略总结

class PricingPlan(BaseModel):
    product: str
    tiers: list[dict]                   # [{name: "免费版", price: 0, highlights: [...]}]

class UserSentimentAnalysis(BaseModel):
    per_product: dict[str, Sentiment]   # {产品: {正面, 负面, 中性}}
    common_praises: list[str]
    common_complaints: list[str]

class SWOTAnalysis(BaseModel):
    product: str
    strengths: list[str]
    weaknesses: list[str]
    opportunities: list[str]
    threats: list[str]
    source_refs: dict[str, list[str]]   # {"strengths[0]": ["url1", "url2"]}
```

**Skill（工具）**：

| 工具名 | 功能 |
|--------|------|
| `build_feature_matrix` | 从原始数据中提取功能对比 |
| `analyze_pricing` | 提取并对比定价方案 |
| `analyze_sentiment` | 聚合用户评价情绪 |
| `generate_swot` | 为每个竞品生成 SWOT |
| `validate_with_context` | 将分析断言与原文对照校验 |

---

### 3.4 报告撰写 Agent

**定位**：生成结构化报告，内联 `[1]` / `[2]` 风格的来源引用。

**输出（写入 state）**：

```python
class ReportOutput(BaseModel):
    title: str
    executive_summary: str              # 执行摘要 (~300 字)
    sections: list[ReportSection]       # 各章节
    citations: list[Citation]           # 引用列表
    full_markdown: str                  # 完整 Markdown 报告
    generated_at: datetime

class ReportSection(BaseModel):
    heading: str
    level: int                          # 1=一级标题, 2=二级标题
    content: str                        # Markdown 内容（含内联引用标记）
    source_refs: list[str]              # 关联的 trace_link id

class Citation(BaseModel):
    index: int                          # 对应 [1]
    url: str
    title: str
    access_date: date
```

**Skill（工具）**：

| 工具名 | 功能 |
|--------|------|
| `format_section` | 将分析数据格式化为报告章节 |
| `generate_citations` | 按引用顺序生成参考文献列表 |
| `inline_citations` | 在文本中插入 `[n]` 标记 |

**报告模板**（Markdown 结构）：

```markdown
# {{target_product}} 竞品分析报告

## 1. 执行摘要
...

## 2. 竞品概览
| 产品 | 定位 | 核心优势 | 目标用户 |
...

## 3. 功能对比
...

## 4. 定价分析
...

## 5. 用户评价
...

## 6. SWOT 分析
### 6.1 {{competitor_1}}
...

## 7. 结论与建议
...

## 参考文献
[1] ... [2] ...
```

---

### 3.5 审查 Agent

**定位**：质量保障，输出通过/不通过 + 结构化反馈。

**输入（state 子集）**：

```python
class ReviewInput(BaseModel):
    report: ReportOutput
    analysis: AnalysisOutput
    config: WorkflowConfig
    revision_count: int
```

**输出**：

```python
class ReviewOutput(BaseModel):
    passed: bool
    score: float                        # 0-100
    checks: list[ReviewCheck]           # 逐项检查结果
    feedback: str                       # 人类可读的反馈
    target_node: Optional[str]          # 打回目标节点
    # 'information_collection' | 'analysis' | 'report_writing'
    specific_issues: list[str]          # 具体问题列表

class ReviewCheck(BaseModel):
    dimension: str                      # 'completeness' | 'accuracy' | 'consistency' | 'credibility'
    passed: bool
    detail: str                         # 评价
```

**审查维度**：

| 维度 | 检查内容 | 通过标准 |
|------|---------|---------|
| `completeness` | 所有关注维度是否覆盖；每个竞品信息是否充足 | 无重大缺失 |
| `accuracy` | 关键断言能否在原始来源中找到支撑 | 关键断言可溯源 |
| `consistency` | 不同章节间的数据/结论是否矛盾 | 无矛盾 |
| `credibility` | 信息来源的质量（官方 > 媒体 > 个人博客） | 至少 50% 来源可靠 |

**Skill（工具）**：

| 工具名 | 功能 |
|--------|------|
| `verify_claim` | 从 trace_link 查找某断言的原始来源 |
| `check_coverage` | 检查 focus_dimensions 是否全部覆盖 |
| `check_contradictions` | LLM 对比不同章节查找矛盾 |
| `score_sources` | 评估所有引用来源的可信度 |

**评分逻辑**：

```
score = completeness * 0.35 + accuracy * 0.35 + consistency * 0.15 + credibility * 0.15
passed = score >= 70 AND all critical checks pass
target_node 决策逻辑:
  - 信息缺失 (completeness < 50) → target_node = 'information_collection'
  - 分析质量差 (accuracy < 50)   → target_node = 'analysis'
  - 报告格式/表述问题             → target_node = 'report_writing'
```

---

### 3.6 上下文管理器（工具组件，非 Agent）

不属于 DAG 的一个节点，而是被其他 Agent 调用的公共工具。

```python
class ContextManager:
    """管理 LLM 上下文窗口，在需要时压缩/摘要大段文本。"""

    def summarize_search_results(self, raw: list[SearchResult]) -> str:
        """将一批搜索结果压缩为结构化摘要，保留关键数据和 source URL。"""

    def extract_for_analysis(self, summaries: dict[str, str]) -> dict:
        """从多个竞品摘要中提取对比所需数据，丢弃冗余原文。"""

    def should_summarize(self, content: str, max_tokens: int) -> bool:
        """判断是否需要触发摘要。"""
```

上下文窗口预算分配（以 GPT-4o 128K 为例）：

| 环节 | 预算 | 说明 |
|------|------|------|
| 系统提示词 | 2K tokens | 角色定义 + 输出格式要求 |
| 工具定义 | 2K tokens | function calling schema |
| 竞品摘要 | 80K tokens | 每个竞品 ~16K（5 竞品） |
| 中间产物 | 20K tokens | feature_matrix 等结构化数据 |
| 输出保留 | 24K tokens | 报告生成空间 |

当采集内容超过 80K 时由 `ContextManager` 触发压缩。

---

## 4. State 设计：Schema 与流转策略

### 4.1 LangGraph StateSchema

```python
from typing import TypedDict, Annotated, Optional
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage


class WorkflowState(TypedDict, total=False):
    # ===== LangGraph 约定字段 =====
    messages: Annotated[list[BaseMessage], add_messages]

    # ===== 配置（用户访谈后锁定，DAG 内只读）=====
    config: WorkflowConfig

    # ===== 信息采集阶段 =====
    competitors: list[CompetitorInfo]
    # [{name: "飞书", website: "feishu.cn", category: "协作工具", description: "..."}]
    raw_data: dict[str, list[SearchResult]]
    # {"飞书": [SearchResult, ...], "钉钉": [...]}
    collection_errors: dict[str, str]
    # {"某竞品": "搜索超时"}
    context_summaries: dict[str, str]
    # 压缩后的竞品摘要 {"飞书": "飞书是字节跳动的...关键功能包括...定价..."}

    # ===== 分析阶段 =====
    feature_matrix: Optional[FeatureMatrix]
    pricing_comparison: Optional[PricingComparison]
    user_sentiment: Optional[UserSentimentAnalysis]
    swot: Optional[SWOTAnalysis]

    # ===== 报告阶段 =====
    report: Optional[ReportOutput]

    # ===== 审查与迭代 =====
    review_result: Optional[ReviewOutput]
    revision_count: int
    max_revisions: int

    # ===== 控制字段 =====
    current_phase: str
    # 'collecting' | 'analyzing' | 'writing' | 'reviewing' | 'done'
    workflow_status: str
    # 'running' | 'completed' | 'failed' | 'cancelled'
    errors: list[ErrorRecord]
```

### 4.2 流转时序

```
时间 ──────────────────────────────────────────────────────►

Phase:   [用户访谈]  [采集]      [分析]      [撰写]      [审查]      [done]
                        │           │           │           │
State:  config◄──►  raw_data   analysis   report    review_result
                          │    results      │           │
                          │ (context_       │           │
                          │  summaries)     │           │
                          │                 │           │
Event:  interview_   collect_   analysis_  report_    review_    workflow_
        **           **         **         **         **          complete
                          │                         │
DB:     ──snapshot──► ──snapshot──► ──snapshot──► ──snapshot──►
        ──events────► ──events────► ──events────► ──events────►
        ──artifact──► ──artifact──► ──artifact──► ──artifact──►
                                   ──trace──────► ──trace──────►
```

### 4.3 持久化策略：双轨制

```
┌──────────────────────────────────────────────────┐
│              LangGraph PostgresSaver              │
│  (自动，每节点前后 checkpoint，支持回滚和恢复)    │
│  表: langgraph_checkpoints (LangGraph 内部管理)   │
└────────────────────┬─────────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────────┐
│         workflow_node_state (自定义表)            │
│  每个节点成功后写入一行，记录该节点的完整 state    │
│  用途：前端展示进度、历史状态回溯、调试            │
│  策略：追加（不覆写），保留每个 iteration          │
└──────────────────────────────────────────────────┘
```

LangGraph 的 `PostgresSaver` checkpoint 是真正的"运行时恢复"机制——系统崩溃后可以从上一个 checkpoint 继续。`workflow_node_state` 则是业务层的"状态快照"——方便前端查询和人工审查，不参与自动恢复逻辑。

---

## 5. Event 设计：Schema 与流转策略

### 5.1 Event 类型定义

```python
class EventType(str, Enum):
    # 节点生命周期
    NODE_START = "node_start"
    NODE_COMPLETE = "node_complete"
    NODE_ERROR = "node_error"

    # 审查
    REVIEW_PASS = "review_pass"
    REVIEW_FAIL = "review_fail"
    REVIEW_REROUTE = "review_reroute"   # 打回至某节点

    # 工具调用（可观测性细节）
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"

    # LLM 调用
    LLM_REQUEST = "llm_request"         # 记录 prompt hash，不存完整 prompt
    LLM_RESPONSE = "llm_response"       # 记录 token 用量、延迟

    # 工作流
    WORKFLOW_START = "workflow_start"
    WORKFLOW_COMPLETE = "workflow_complete"
    WORKFLOW_FAILED = "workflow_failed"
    WORKFLOW_PAUSED = "workflow_paused" # 等待用户介入

    # 上下文管理
    CONTEXT_COMPRESSED = "context_compressed"
```

### 5.2 数据库表结构

```sql
CREATE TABLE workflow_event (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id     UUID NOT NULL,
    node_name       VARCHAR(64) NOT NULL,
    iteration       INTEGER NOT NULL DEFAULT 0,
    -- iteration 配合 node_name 定位是哪一次经过该节点（首次=0，第一次打回重跑=1）
    event_type      VARCHAR(32) NOT NULL,  -- EventType 枚举值
    seq             INTEGER NOT NULL,      -- 工作流内单调递增序号
    payload         JSONB NOT NULL DEFAULT '{}',
    -- 事件特有数据，见下方 Event Payload Schema
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT fk_event_workflow FOREIGN KEY (workflow_id)
        REFERENCES workflow(id) ON DELETE CASCADE
);

-- 索引
CREATE INDEX idx_event_wf_seq     ON workflow_event(workflow_id, seq);
CREATE INDEX idx_event_wf_node    ON workflow_event(workflow_id, node_name, iteration);
CREATE INDEX idx_event_type       ON workflow_event(workflow_id, event_type);
CREATE INDEX idx_event_created    ON workflow_event(workflow_id, created_at);
```

### 5.3 Event Payload Schema（JSONB 内结构）

```python
# node_start
{
    "input_summary": {
        "competitors_count": 5,
        "phase": "collecting",
        "revision_count": 0,
    },
    "node_config": {},            # 节点特定配置
}

# node_complete
{
    "output_summary": {
        "collected_competitors": 5,
        "total_sources": 42,
        "failed_competitors": 0,
    },
    "artifact_ids": ["uuid1", "uuid2"],
    "duration_ms": 12450,
    "tokens_input": 3200,
    "tokens_output": 1500,
    "model_name": "gpt-4o",
}

# node_error
{
    "error_code": "TAVILY_TIMEOUT",
    "error_message": "Tavily search timed out after 30s",
    "retry_count": 2,
    "max_retries": 3,
    "failed_at": "search_competitive_info(competitor='飞书')",
}

# tool_call / tool_result
{
    "tool_name": "search_competitive_info",
    "tool_input": {"query": "飞书 功能对比", "max_results": 5},
    # tool_result additionally:
    "tool_output": {"results_count": 5, "top_urls": ["..."]},
    "duration_ms": 2300,
}

# llm_request
{
    "prompt_hash": "sha256_of_prompt",  # 不存全文，用 hash 去 LangSmith 查
    "model": "gpt-4o",
    "temperature": 0.3,
    "max_tokens": 4096,
}

# llm_response
{
    "tokens_input": 3200,
    "tokens_output": 1500,
    "duration_ms": 4800,
    "finish_reason": "stop",
}

# review_pass / review_fail
{
    "score": 85,
    "checks": [
        {"dimension": "completeness", "passed": True, "detail": "..."},
    ],
    "feedback": "报告质量良好",
    # review_fail additionally:
    "target_node": "information_collection",
    "specific_issues": ["竞品B缺少定价信息", "SWOT分析中威胁部分过于简略"],
}

# context_compressed
{
    "before_tokens": 45000,
    "after_tokens": 12000,
    "compression_ratio": 0.27,
    "strategy": "extractive_summary",  # 或 "hierarchical_summary"
}
```

### 5.4 事件的写入时机与职责

```
graph TD
    subgraph "LangGraph 节点内 (Agent 代码)"
        A[node_start event] --> B[LLM call → llm_request/response events]
        B --> C[tool calls → tool_call/tool_result events]
        C --> D{成功?}
        D -->|是| E[node_complete event + state snapshot]
        D -->|否| F[node_error event]
    end

    subgraph "Orchestrator (节点间路由)"
        G[review_fail event] --> H[review_reroute event]
        H --> I[revision_count++]
    end
```

关键规则：
- 每个 event 写入后立即 commit（独立事务），保证崩溃时已写入的日志不丢失
- `seq` 在 workflow 生命周期内单调递增，由 application 层生成
- `node_start` 总是和 `node_complete` 或 `node_error` 配对出现

---

## 6. 数据库设计

### 6.1 完整 ER 关系

```
user 1──────N workflow 1──────N workflow_node_state
                    │
                    │ 1──────N workflow_event
                    │
                    │ 1──────N artifact 1──────N trace_link
```

### 6.2 建表语句

```sql
-- =============================================
-- 用户表
-- =============================================
CREATE TABLE user (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username        VARCHAR(64) UNIQUE NOT NULL,
    email           VARCHAR(255) UNIQUE NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    display_name    VARCHAR(128),
    is_active       BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);


-- =============================================
-- 工作流表（每次竞品分析任务）
-- =============================================
CREATE TABLE workflow (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id        UUID NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
    title           VARCHAR(255) NOT NULL,
    status          VARCHAR(32) NOT NULL DEFAULT 'created',
    -- 'created' | 'configuring' | 'running' | 'completed' | 'failed' | 'cancelled'
    current_phase   VARCHAR(32),
    -- 'collecting' | 'analyzing' | 'writing' | 'reviewing'
    config          JSONB NOT NULL DEFAULT '{}',
    -- WorkflowConfig 序列化（用户访谈后锁定）
    revision_count  INTEGER NOT NULL DEFAULT 0,
    max_revisions   INTEGER NOT NULL DEFAULT 3,
    total_tokens    INTEGER NOT NULL DEFAULT 0,
    -- 累计 token 用量
    langgraph_checkpoint_id VARCHAR(128),
    -- 关联 LangGraph checkpoint，用于恢复
    error_message   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ
);

CREATE INDEX idx_workflow_owner  ON workflow(owner_id, created_at DESC);
CREATE INDEX idx_workflow_status ON workflow(status, created_at);


-- =============================================
-- 节点状态快照表（每个节点执行完后的完整 state）
-- =============================================
CREATE TABLE workflow_node_state (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id     UUID NOT NULL REFERENCES workflow(id) ON DELETE CASCADE,
    node_name       VARCHAR(64) NOT NULL,
    -- 'information_collection' | 'analysis' | 'report_writing' | 'review'
    iteration       INTEGER NOT NULL DEFAULT 0,
    -- 第几次执行该节点（打回重跑时递增）
    state_snapshot  JSONB NOT NULL,
    -- WorkflowState 的完整序列化
    artifact_ids    UUID[] DEFAULT '{}',
    -- 该节点产出的 artifact ID 列表
    tokens_input    INTEGER DEFAULT 0,
    tokens_output   INTEGER DEFAULT 0,
    duration_ms     INTEGER DEFAULT 0,
    model_name      VARCHAR(64),
    is_error        BOOLEAN NOT NULL DEFAULT false,
    error_message   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_node_state_wf    ON workflow_node_state(workflow_id, node_name, iteration);
CREATE INDEX idx_node_state_error ON workflow_node_state(workflow_id, is_error)
    WHERE is_error = true;


-- =============================================
-- 工作流事件表（审计日志，独立行）
-- =============================================
CREATE TABLE workflow_event (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id     UUID NOT NULL REFERENCES workflow(id) ON DELETE CASCADE,
    node_name       VARCHAR(64) NOT NULL,
    iteration       INTEGER NOT NULL DEFAULT 0,
    event_type      VARCHAR(32) NOT NULL,
    seq             INTEGER NOT NULL,
    payload         JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_event_wf_seq    ON workflow_event(workflow_id, seq);
CREATE INDEX idx_event_wf_node   ON workflow_event(workflow_id, node_name, iteration);
CREATE INDEX idx_event_type      ON workflow_event(workflow_id, event_type);
CREATE INDEX idx_event_created   ON workflow_event(workflow_id, created_at);


-- =============================================
-- 知识产物表
-- =============================================
CREATE TABLE artifact (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id     UUID NOT NULL REFERENCES workflow(id) ON DELETE CASCADE,
    artifact_type   VARCHAR(32) NOT NULL,
    -- 'feature_matrix' | 'pricing_comparison' | 'swot_analysis'
    -- | 'user_sentiment' | 'report' | 'collection_raw' | 'interview_config'
    title           VARCHAR(255) NOT NULL,
    content         JSONB NOT NULL,
    -- 结构化数据：FeatureMatrix / ReportOutput 等序列化
    content_text    TEXT,
    -- 人类可读版本（Markdown）
    format_version  VARCHAR(16) NOT NULL DEFAULT '1.0',
    created_by_node VARCHAR(64),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_artifact_wf   ON artifact(workflow_id, created_at);
CREATE INDEX idx_artifact_type ON artifact(workflow_id, artifact_type);


-- =============================================
-- 溯源链接表（每条分析结论 → 原始 URL）
-- =============================================
CREATE TABLE trace_link (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    artifact_id     UUID NOT NULL REFERENCES artifact(id) ON DELETE CASCADE,
    -- 属于哪个 artifact 的引用
    section_path    VARCHAR(255),
    -- JSON 路径定位，如 "swot.strengths[0]" 或 "report.sections[2].content"
    claim_text      TEXT,
    -- 具体的分析断言文本（截取前 512 字符）
    source_url      TEXT NOT NULL,
    source_title    VARCHAR(512),
    source_snippet  TEXT,
    source_type     VARCHAR(32) DEFAULT 'web',
    -- 'web' | 'official' | 'review_platform' | 'social_media'
    retrieved_at    TIMESTAMPTZ NOT NULL,
    confidence      FLOAT CHECK (confidence >= 0 AND confidence <= 1),
    -- 来源可信度
    is_verified     BOOLEAN DEFAULT false,
    -- 是否通过审查 Agent 验证
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_trace_artifact ON trace_link(artifact_id);
CREATE INDEX idx_trace_url      ON trace_link(source_url);


-- =============================================
-- 搜索模板预设表（可选，用于不同品类的搜索策略）
-- =============================================
CREATE TABLE search_template (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    category        VARCHAR(64) UNIQUE NOT NULL,
    -- 'SaaS' | '移动应用' | '硬件产品' | '内容平台' | ...
    templates       JSONB NOT NULL,
    -- {"general": "...{competitor}...", "pricing": "...", "reviews": "..."}
    description     VARCHAR(255),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### 6.3 数据流转关系

```
1. 用户创建 workflow → INSERT workflow (status='configuring')
2. 用户访谈完成 → UPDATE workflow.config, status='running'
3. DAG 开始执行 → INSERT workflow_event (workflow_start)
4. 每节点:
   a. INSERT workflow_event (node_start)
   b. 采集/分析/撰稿 → INSERT artifact (产物)
   c. 每引用一个来源 → INSERT trace_link
   d. INSERT workflow_event (node_complete)
   e. INSERT workflow_node_state (快照)
5. 审查通过 → INSERT workflow_event (review_pass + workflow_complete)
   → UPDATE workflow.status='completed'
6. 审查不通过 → INSERT workflow_event (review_fail + review_reroute)
   → UPDATE workflow.revision_count += 1 → 路由回目标节点（步骤4 重复）
```

---

## 7. 错误处理与回滚策略

### 7.1 错误分类矩阵

| 错误类型 | 示例 | 处理策略 | 恢复方式 |
|----------|------|---------|---------|
| **瞬时故障** | Tavily 超时、LLM 429 | 指数退避重试 (3 次) | 自动 |
| **不可恢复故障** | API Key 无效、模型不存在 | 节点标记 failed，暂停工作流 | 人工介入 |
| **业务不通过** | 审查 score < 70 | 打回至指定节点重跑 | 自动（有限次） |
| **部分失败** | 5 个竞品中 1 个采集失败 | 标记该竞品为"数据不足"，继续 | 自动降级 |
| **上下文溢出** | 采集内容超 128K tokens | ContextManager 触发压缩 | 自动 |
| **系统崩溃** | 进程 kill、服务器重启 | LangGraph PostgresSaver 恢复 | 自动（重启） |

### 7.2 节点级重试实现

```python
from tenacity import retry, stop_after_attempt, wait_exponential

class NodeExecutor:
    MAX_RETRIES = 3

    async def execute_with_retry(self, state, node_fn, node_name, event_logger):
        last_error = None
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                result = await asyncio.wait_for(
                    node_fn(state),
                    timeout=NODE_TIMEOUT  # 每个节点 5 分钟超时
                )
                return result
            except Exception as e:
                last_error = e
                await event_logger.log(
                    event_type=EventType.NODE_ERROR,
                    payload={
                        "error_code": type(e).__name__,
                        "error_message": str(e),
                        "retry_count": attempt,
                        "max_retries": self.MAX_RETRIES,
                    }
                )
                if attempt < self.MAX_RETRIES and self._is_retryable(e):
                    await asyncio.sleep(2 ** attempt)  # 指数退避
                    continue
                break

        raise NodeFatalError(
            node=node_name,
            attempts=self.MAX_RETRIES,
            last_error=last_error,
        )
```

### 7.3 审查不通过的回滚流程

```
                         NodeState ID=10
                         (report_writing 完成)
                              │
                              ▼
                     ┌─────────────────┐
                     │  review 节点     │
                     │  score=55, FAIL  │
                     └────────┬────────┘
                              │
                    INSERT workflow_event
                    (review_fail, target_node='analysis')
                              │
                    UPDATE workflow.revision_count += 1
                              │
                    revision_count < 3? ──Yes──► 路由到 'analysis'
                              │
                              ▼
                         NodeState ID=11
                         (analysis, iteration=1)
                         基于上一轮 review 的 feedback
                         重新分析 → 生成新的 analysis artifact
                              │
                              ▼
                         NodeState ID=12
                         (report_writing, iteration=1)
                         基于新的 analysis 重写报告
                              │
                              ▼
                         NodeState ID=13
                         (review, iteration=1)
                              │
                         再次检查...
```

关键设计：
- **不回退/删除旧数据**：上一轮的 state_snapshot、artifact、event 全部保留
- `iteration` 字段区分同一节点的不同轮次，前端可按 iteration 展示历史版本
- 打回时 review Agent 指定 `target_node`，Orchestrator 只重新执行 target_node 及其下游节点

### 7.4 系统崩溃恢复

```
场景：分析节点执行到一半，进程 crash

恢复步骤：
1. Celery Worker 重启触发 workflow 状态检查
2. 查询 LangGraph PostgresSaver: 最后一个 checkpoint 在哪？
   → checkpoint 在 'information_collection' 节点完成后
3. LangGraph 自动从该 checkpoint 恢复，重新执行 analysis 节点
4. workflow_node_state 中 analysis 的旧记录（如果有）标记为 incomplete
5. 新增一轮执行的事件和快照
```

### 7.5 状态一致性保障

为防止崩溃导致的脏数据：

```
workflow_node_state 采用"先写后认"模式：
  1. INSERT state_snapshot (status='pending')
  2. 关联 artifact 写入
  3. 关联 trace_link 写入
  4. 全部成功后 → UPDATE state_snapshot (status='committed')

崩溃恢复时，status='pending' 的快照视为无效，可被覆盖。
```

---

## 8. 上下文管理策略

### 8.1 压缩触发条件

```python
CONTEXT_BUDGET = 100_000  # tokens，为 128K 留 28K 余量

def should_compress(state: WorkflowState) -> bool:
    estimated = estimate_tokens(state["raw_data"])  # 原始搜索结果
    estimated += estimate_tokens(state["context_summaries"]) if state.get("context_summaries") else 0
    estimated += estimate_tokens(state["messages"])
    return estimated > CONTEXT_BUDGET
```

### 8.2 分层压缩策略

```
Level 0（原始）: 完整网页内容
  │  仅用于信息采集 Agent 内部 LLM 调用
  ▼
Level 1（竞品摘要）: ~2000 tokens/竞品
  │  关键信息提炼：功能清单、定价方案、用户评价要点、source URLs
  │  存入 state.context_summaries
  ▼
Level 2（分析摘要）: ~500 tokens/竞品
  │  仅保留分析所需的核心数据（数字、对比维度）
  │  用于 analysis Agent 的 prompt
  ▼
Level 3（报告摘要）: ~100 tokens/竞品（一句话定位）
    用于报告撰写阶段快速引用
```

### 8.3 压缩时的溯源保留

压缩不丢失溯源信息：

```python
class CompressedSummary(BaseModel):
    product_name: str
    summary: str                        # 压缩后文本
    key_claims: list[CompressedClaim]   # 关键断言
    source_urls: list[str]              # 所有原始来源 URL

class CompressedClaim(BaseModel):
    claim: str                          # "飞书支持 5000 人同时在线协作"
    source_indices: list[int]           # [0, 3] → source_urls[0] 和 source_urls[3]
```

压缩后，`source_urls` 仍然完整保留，后续生成 `trace_link` 时仍可定位到原始 URL。

---

## 9. 可观测性与溯源设计

### 9.1 三层可观测性

```
┌─────────────────────────────────────────────────────────┐
│ L1: LangSmith (LLM 级别)                                 │
│   - 每次 LLM 调用的完整 prompt/response                 │
│   - Token 用量、延迟 Trace                              │
│   - 工具调用的输入输出                                   │
│   用途：调试/prompt engineering/成本分析                 │
├─────────────────────────────────────────────────────────┤
│ L2: workflow_event 表 (Agent 级别)                       │
│   - 每个节点的开始/完成/错误                             │
│   - 工具调用的输入/输出摘要                              │
│   - 审查决策 (通过/不通过/打回)                          │
│   用途：前端时间线、审计追溯、运行监控                   │
├─────────────────────────────────────────────────────────┤
│ L3: trace_link 表 (结论级别)                             │
│   - 每条分析断言的来源 URL                               │
│   - 置信度评分                                           │
│   - 是否通过审查验证                                     │
│   用途：报告溯源、信源可信度评估                         │
└─────────────────────────────────────────────────────────┘
```

### 9.2 前端可观测性视图

**工作流时间线**

```
┌────────────────────────────────────────────────────────┐
│ 竞品分析时间线: "Notion 竞品分析"                       │
│                                                        │
│ 14:00  ● 信息采集开始                                  │
│ 14:02  │  ├ tavily.search("Notion 功能对比") → 8 结果  │
│ 14:03  │  ├ tavily.extract(url) → 摘要 1200 tokens     │
│ 14:04  │  ├ ... (5 竞品 × 4 次搜索 = 20 次调用)        │
│ 14:35  ● 信息采集完成 (42 sources, 15K tokens)         │
│ 14:35  ● 分析开始                                      │
│ 14:36  │  ├ 功能矩阵构建                                │
│ 14:37  │  ├ 定价对比分析                                │
│ 14:38  │  ├ SWOT 生成                                   │
│ 14:40  ● 分析完成                                      │
│ 14:40  ● 报告撰写开始                                  │
│ 14:42  ● 报告完成 (引用 42 来源)                       │
│ 14:42  ● 审查开始                                      │
│ 14:43  │  ├ completeness: ✓ (85%)                      │
│ 14:43  │  ├ accuracy: ✓ (78%)                          │
│ 14:43  │  ├ consistency: ✓ (92%)                       │
│ 14:43  │  └ credibility: ✓ (70%)                       │
│ 14:43  ● 审查通过 (score: 81)                          │
│ 14:43  ● 工作流完成                                    │
└────────────────────────────────────────────────────────┘
```

**溯源视图**

```
报告章节: 3. 功能对比 → "飞书在实时协作方面领先，支持 500+ 人同时编辑"
  ├ [1] 飞书官方文档 - 协作功能说明    ✓ 已验证  c=0.95
  ├ [3] 少数派评测 - 飞书 vs 钉钉      ✓ 已验证  c=0.80
  └ [7] 知乎用户反馈                    ✗ 未验证  c=0.50
```

### 9.3 LangSmith 集成

```python
# 在 LangGraph workflow 编译时启用
from langgraph.checkpoint.postgres import PostgresSaver

graph = workflow.compile(
    checkpointer=PostgresSaver.from_conn_string(DATABASE_URL),
)

# 所有 LLM 调用自动 trace
# 可在 LangSmith UI 中查看:
# - 每个 Agent 节点的 prompt → response 完整链路
# - Token 用量图表
# - 工具调用时间线
```

---

## 10. API 设计

### 10.1 端点列表

```
Auth
  POST   /api/v1/auth/register              # 注册
  POST   /api/v1/auth/login                 # 登录 → JWT

Workflow
  POST   /api/v1/workflows                  # 创建新工作流 → workflow_id
  GET    /api/v1/workflows                  # 用户的工作流列表（分页）
  GET    /api/v1/workflows/{id}             # 工作流详情（含当前状态、进度）
  DELETE /api/v1/workflows/{id}             # 取消/删除工作流
  POST   /api/v1/workflows/{id}/start       # 用户确认访谈配置后，启动 DAG

Interview (用户访谈前置步骤)
  POST   /api/v1/workflows/{id}/interview   # 发送用户访谈消息
  GET    /api/v1/workflows/{id}/interview   # 获取访谈历史
  POST   /api/v1/workflows/{id}/interview/confirm  # 确认配置，准备启动

Events & Trace (可观测性)
  GET    /api/v1/workflows/{id}/events      # 事件列表（分页，可按 node/type 筛选）
  GET    /api/v1/workflows/{id}/trace       # 溯源链接列表
  GET    /api/v1/workflows/{id}/states      # 历史 state 快照列表

Artifact
  GET    /api/v1/workflows/{id}/artifacts   # 产物列表
  GET    /api/v1/artifacts/{id}             # 单个产物详情
  GET    /api/v1/artifacts/{id}/download    # 下载报告 Markdown

Error Recovery
  POST   /api/v1/workflows/{id}/retry/{node_name}  # 手动重试失败节点
```

### 10.2 实时进度推送（SSE）

用户访谈阶段和 DAG 执行阶段，前端通过 SSE 获取实时事件：

```
GET /api/v1/workflows/{id}/stream
  → Content-Type: text/event-stream

  data: {"event_type": "node_start", "node_name": "information_collection", "seq": 1}
  data: {"event_type": "tool_call", "tool_name": "search_competitive_info", "seq": 2}
  data: {"event_type": "node_complete", "node_name": "information_collection", "duration_ms": 32000, "seq": 40}
  data: {"event_type": "node_start", "node_name": "analysis", "seq": 41}
  ...
  data: {"event_type": "workflow_complete", "seq": 100}
```

实现方式：FastAPI `StreamingResponse` + Redis pub/sub（或直接用 PostgreSQL LISTEN/NOTIFY）。

### 10.3 API 响应示例

```json
// GET /api/v1/workflows/{id}
{
  "id": "uuid",
  "title": "Notion 竞品分析",
  "status": "running",
  "current_phase": "analyzing",
  "config": {
    "target_product": "Notion",
    "product_category": "SaaS / 协作工具",
    "competitors": ["飞书", "Confluence", "Coda", "ClickUp", "Obsidian"],
    "focus_dimensions": ["功能", "定价", "用户评价"],
    "language": "zh"
  },
  "revision_count": 0,
  "progress": {
    "phases": {
      "collecting": {"status": "completed", "duration_ms": 32000},
      "analyzing": {"status": "running", "started_at": "2025-..."},
      "writing": {"status": "pending"},
      "reviewing": {"status": "pending"}
    },
    "total_tokens": 45000
  },
  "created_at": "2025-...",
  "updated_at": "2025-..."
}
```

---

## 11. 安全与配置

### 11.1 环境变量

```bash
# .env.example
# === Database ===
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/dagents
DATABASE_URL_SYNC=postgresql://user:pass@localhost:5432/dagents

# === LLM ===
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o
OPENAI_TEMPERATURE=0.3

# === Search ===
TAVILY_API_KEY=tvly-...

# === Auth ===
JWT_SECRET_KEY=your-secret-key
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=1440

# === LangSmith (可选，开发时可关闭) ===
LANGSMITH_API_KEY=lsv2_...
LANGSMITH_PROJECT=dagents-insightflow
LANGSMITH_TRACING_V2=true

# === Celery ===
CELERY_BROKER_URL=sqla+postgresql://...

# === Rate Limits ===
LLM_RATE_LIMIT_PER_MINUTE=50
TAVILY_RATE_LIMIT_PER_MINUTE=10
```

### 11.2 安全措施

| 措施 | 说明 |
|------|------|
| JWT 认证 | access_token + 可选 refresh_token |
| 密码哈希 | bcrypt |
| SQL 注入 | SQLAlchemy 参数化查询 |
| LLM Prompt 注入 | 用户输入在进入 prompt 前做 sanitize |
| Rate Limit | FastAPI + slowapi 中间件 |
| 用户隔离 | 所有查询加 `WHERE owner_id = current_user.id` |
| Secrets | 环境变量，不入代码、不存 DB |

---

## 12. 实现路线图

### 第 1 周：基础设施 + Schema + 单个 Agent

```
Day 1-2:  项目脚手架
  - FastAPI 项目结构、config、DB 连接
  - SQLAlchemy 模型 (user, workflow, workflow_node_state,
    workflow_event, artifact, trace_link)
  - Alembic migration
  - JWT auth 模块
  - Pydantic Schema 定义（所有 schema 类）

Day 3-4:  LangGraph 骨架 + 采集 Agent
  - LangGraph StateGraph 搭建（空节点 + 条件路由）
  - PostgresSaver checkpoint 配置
  - 信息采集 Agent 实现（Tavily 集成 + 搜索模板）
  - ContextManager 基础实现
  - Event 记录工具

Day 5:    用户访谈 Agent + 单节点联调
  - 用户访谈多轮对话实现
  - 访谈 → workflow config 提取
  - 从 interview 到 workflow start 的完整流程
```

### 第 2 周：DAG 联调 + 反馈闭环

```
Day 6-7:  分析 Agent + 报告 Agent
  - Analysis Agent 实现（feature_matrix, pricing, sentiment, SWOT）
  - Report Agent 实现（模板渲染 + 内联引用）
  - trace_link 自动生成
  - Artifact 写入逻辑

Day 8:    审查 Agent + 反馈闭环
  - Review Agent 实现（四维检查 + 评分逻辑）
  - 打回路由逻辑（conditional edge）
  - iteration 管理

Day 9-10: 全流程联调
  - 端到端测试: interview → collection → analysis → report → review
  - 审查不通过打回 → 重跑通过
  - 错误注入测试（搜索超时、LLM 失败）
  - 崩溃恢复测试
```

### 第 3 周：前端 + 可观测性 + 答辩准备

```
Day 11-12: 前端核心页面
  - 登录/注册
  - 用户访谈界面（聊天式）
  - 工作流列表页
  - 工作流详情页（时间线 + 进度）
  - 报告展示页

Day 13:    可观测性 + SSE
  - 实时进度 SSE 推送
  - 溯源视图（点击引用跳转到原始来源）
  - LangSmith 集成确认
  - 错误日志面板

Day 14:    答辩准备
  - Demo 录制/演示流程
  - 边界情况测试
  - README / 答辩 PPT
```

---

## 附录 A：与原设计的差异对照

| 维度 | 原设计 (notice.md) | v2 设计 | 原因 |
|------|-------------------|---------|------|
| State 持久化 | JSONB 覆写 | LangGraph checkpoint + 快照追加 | 保留历史，支持回滚 |
| Event 存储 | JSONB 数组追加 | 每事件独立行 | 可查询、可分页、不膨胀 |
| 用户访谈 | DAG 内节点 | 前置步骤 | 多轮交互不适合 DAG 内 |
| 上下文管理 | "可能需要摘要 agent" | ContextManager 工具 + 分层压缩 | 上下文控制是多 Agent 核心需求 |
| 审查维度 | 未定义 | 四维检查 + 评分公式 | 可量化、可重复 |
| 溯源 | 概念提及 | trace_link 表 + section_path 精确定位 | 从"有引用"升级为"可验证" |
| 错误处理 | "节点级恢复" 一句带过 | 分类矩阵 + 退避重试 + 崩溃恢复 | 覆盖所有异常场景 |
| 并行采集 | 未提及 | asyncio.gather 节点内并行 | 显著缩短采集时间 |
| 搜索模板 | "预置查询途径" 未展开 | search_template 表 + category 匹配 | 可配置、可扩展 |

---

## 附录 B：关键数据结构速查

```python
# WorkflowState 在 LangGraph 中的流转
{
    "config": WorkflowConfig,
    "competitors": [CompetitorInfo, ...],
    "raw_data": {"竞品A": [SearchResult, ...], ...},
    "context_summaries": {"竞品A": "...", ...},
    "feature_matrix": FeatureMatrix | None,
    "pricing_comparison": PricingComparison | None,
    "user_sentiment": UserSentimentAnalysis | None,
    "swot": SWOTAnalysis | None,
    "report": ReportOutput | None,
    "review_result": ReviewOutput | None,
    "revision_count": 0,
    "max_revisions": 3,
    "current_phase": "collecting",
    "workflow_status": "running",
    "errors": [],
}
```

---

## 附录 C：完整项目结构

```
DAGents-InsightFlow/
│
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                         # FastAPI 入口，注册路由 + CORS
│   │   ├── config.py                       # pydantic-settings 全局配置
│   │   ├── dependencies.py                 # 全局依赖（DB session、current_user）
│   │   │
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   └── v1/
│   │   │       ├── __init__.py
│   │   │       ├── router.py               # v1 路由聚合
│   │   │       ├── auth.py                 # POST register / login
│   │   │       ├── workflow.py             # CRUD + start + retry
│   │   │       ├── interview.py            # POST interview / confirm
│   │   │       ├── event.py                # GET events（分页+筛选）
│   │   │       ├── artifact.py             # GET artifacts / download
│   │   │       └── trace.py                # GET trace links
│   │   │
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   ├── orchestrator.py             # LangGraph StateGraph 编译 + 路由逻辑
│   │   │   ├── graph_nodes.py              # DAG 节点函数定义
│   │   │   ├── workflow_executor.py        # Celery 异步任务（启动 DAG）
│   │   │   ├── memory_manager.py           # ContextManager 工具
│   │   │   └── node_executor.py            # 节点级重试 + 超时包装
│   │   │
│   │   ├── agents/
│   │   │   ├── __init__.py
│   │   │   ├── base_agent.py               # Agent 基类（event logging 工具等）
│   │   │   ├── interview_agent.py          # pre-workflow 多轮对话
│   │   │   ├── collection_agent.py         # Tavily 搜索 + 页面提取
│   │   │   ├── analysis_agent.py           # 功能矩阵/定价/情感/SWOT
│   │   │   ├── report_agent.py             # 报告模板渲染 + 内联引用
│   │   │   └── review_agent.py             # 四维审查 + 评分公式
│   │   │
│   │   ├── schemas/
│   │   │   ├── __init__.py
│   │   │   ├── workflow_state.py           # WorkflowState TypedDict
│   │   │   ├── config.py                   # WorkflowConfig、InterviewInput/Output
│   │   │   ├── competitor.py               # CompetitorInfo、SearchResult
│   │   │   ├── feature.py                  # FeatureMatrix、FeatureItem
│   │   │   ├── pricing.py                  # PricingComparison、PricingPlan
│   │   │   ├── sentiment.py                # UserSentimentAnalysis、Sentiment
│   │   │   ├── swot.py                     # SWOTAnalysis、SWOTItem
│   │   │   ├── report.py                   # ReportOutput、ReportSection、Citation
│   │   │   ├── review.py                   # ReviewOutput、ReviewCheck
│   │   │   ├── event.py                    # EventType、EventPayload 各结构
│   │   │   └── common.py                   # SourceRef、ErrorRecord、CompressedSummary
│   │   │
│   │   ├── db/
│   │   │   ├── __init__.py
│   │   │   ├── base.py                     # SQLAlchemy declarative base
│   │   │   ├── session.py                  # 同步/异步 session 管理
│   │   │   ├── models/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── user.py
│   │   │   │   ├── workflow.py
│   │   │   │   ├── workflow_node_state.py
│   │   │   │   ├── workflow_event.py
│   │   │   │   ├── artifact.py
│   │   │   │   ├── trace_link.py
│   │   │   │   └── search_template.py
│   │   │   └── repositories/
│   │   │       ├── __init__.py
│   │   │       ├── user_repo.py
│   │   │       ├── workflow_repo.py
│   │   │       ├── event_repo.py
│   │   │       ├── artifact_repo.py
│   │   │       └── trace_repo.py
│   │   │
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── auth_service.py             # JWT 签发/验证
│   │   │   ├── interview_service.py        # 多轮对话维护 + config 提取
│   │   │   ├── search_service.py           # Tavily 搜索封装 + 模板匹配
│   │   │   └── sse_service.py              # SSE 事件推送
│   │   │
│   │   └── tasks/                          # Celery 任务
│   │       ├── __init__.py
│   │       ├── celery_app.py               # Celery 实例
│   │       └── workflow_tasks.py           # run_workflow.delay()
│   │
│   ├── tests/
│   │   ├── __init__.py
│   │   ├── conftest.py
│   │   ├── test_agents/
│   │   │   ├── test_collection_agent.py
│   │   │   ├── test_analysis_agent.py
│   │   │   ├── test_report_agent.py
│   │   │   └── test_review_agent.py
│   │   ├── test_api/
│   │   │   ├── test_auth.py
│   │   │   ├── test_workflow.py
│   │   │   └── test_interview.py
│   │   ├── test_db/
│   │   │   └── test_repositories.py
│   │   └── test_e2e/
│   │       └── test_full_workflow.py
│   │
│   ├── alembic/
│   │   ├── versions/
│   │   └── env.py
│   ├── alembic.ini
│   ├── pyproject.toml
│   └── .env.example
│
├── frontend/
│   ├── app/
│   │   ├── layout.tsx                      # 根布局（Provider 包裹）
│   │   ├── page.tsx                        # / → redirect to /dashboard
│   │   │
│   │   ├── auth/
│   │   │   ├── login/page.tsx
│   │   │   └── register/page.tsx
│   │   │
│   │   ├── dashboard/
│   │   │   ├── page.tsx                    # 工作流列表（卡片+搜索+分页）
│   │   │   └── loading.tsx
│   │   │
│   │   └── workflows/
│   │       └── [id]/
│   │           ├── page.tsx                # 工作流详情主页（Tabs 容器）
│   │           ├── interview/page.tsx      # 用户访谈聊天页
│   │           ├── report/page.tsx         # 报告展示页
│   │           ├── trace/page.tsx          # 溯源视图页
│   │           └── events/page.tsx         # 事件日志页
│   │
│   ├── components/
│   │   ├── ui/                             # 通用 UI 组件（shadcn/ui 风格）
│   │   │   ├── button.tsx
│   │   │   ├── card.tsx
│   │   │   ├── badge.tsx
│   │   │   ├── tabs.tsx
│   │   │   ├── modal.tsx
│   │   │   ├── input.tsx
│   │   │   ├── select.tsx
│   │   │   ├── spinner.tsx
│   │   │   └── toast.tsx
│   │   │
│   │   ├── auth/
│   │   │   ├── login-form.tsx
│   │   │   ├── register-form.tsx
│   │   │   └── auth-guard.tsx              # 未登录重定向
│   │   │
│   │   ├── dashboard/
│   │   │   ├── workflow-card.tsx           # 列表卡片
│   │   │   ├── workflow-list.tsx
│   │   │   ├── create-workflow-button.tsx
│   │   │   └── filter-bar.tsx              # 按状态/日期筛选
│   │   │
│   │   ├── interview/
│   │   │   ├── chat-message.tsx            # 气泡消息
│   │   │   ├── message-input.tsx
│   │   │   ├── config-preview.tsx          # 确认卡片
│   │   │   └── chat-history.tsx
│   │   │
│   │   ├── workflow/
│   │   │   ├── progress-timeline.tsx       # 时间线组件
│   │   │   ├── phase-badge.tsx             # 阶段标签（状态色）
│   │   │   ├── phase-progress.tsx          # 四阶段进度条
│   │   │   ├── iteration-badge.tsx         # 打回次数标记
│   │   │   └── workflow-header.tsx         # 标题+状态+操作按钮
│   │   │
│   │   ├── report/
│   │   │   ├── report-viewer.tsx           # Markdown 渲染
│   │   │   ├── report-section.tsx          # 单个章节
│   │   │   ├── citation-list.tsx           # 参考文献列表
│   │   │   ├── feature-matrix-table.tsx    # 功能对比表格
│   │   │   ├── pricing-table.tsx           # 定价对比
│   │   │   ├── swot-card.tsx               # SWOT 四象限卡片
│   │   │   └── executive-summary.tsx
│   │   │
│   │   ├── trace/
│   │   │   ├── trace-list.tsx              # 溯源条目列表
│   │   │   ├── trace-item.tsx              # 单条：断言 → source
│   │   │   ├── source-link.tsx             # 外部链接（置信度标记）
│   │   │   └── claim-verification-badge.tsx
│   │   │
│   │   ├── events/
│   │   │   ├── event-log.tsx               # 事件日志表格
│   │   │   ├── event-item.tsx              # 单行事件
│   │   │   ├── event-filter.tsx            # 按类型/节点筛选
│   │   │   └── event-detail-drawer.tsx     # 展开 payload
│   │   │
│   │   └── shared/
│   │       ├── error-boundary.tsx
│   │       ├── empty-state.tsx
│   │       ├── pagination.tsx
│   │       ├── page-header.tsx
│   │       ├── sse-listener.tsx            # SSE 连接管理 hook
│   │       └── theme-toggle.tsx
│   │
│   ├── lib/
│   │   ├── api.ts                          # axios 实例 + 拦截器（JWT）
│   │   ├── auth-context.tsx                # React Context: user + token
│   │   ├── use-workflow.ts                 # React Query hooks
│   │   ├── use-events.ts
│   │   ├── use-artifacts.ts
│   │   ├── use-interview.ts
│   │   ├── use-sse.ts                      # SSE 连接 hook
│   │   └── utils.ts                        # 格式化日期、状态颜色映射等
│   │
│   ├── types/
│   │   ├── workflow.ts                     # Workflow, WorkflowConfig, PhaseStatus
│   │   ├── artifact.ts                     # Artifact, ReportOutput, FeatureMatrix etc.
│   │   ├── event.ts                        # WorkflowEvent, EventType
│   │   ├── trace.ts                        # TraceLink, Source
│   │   ├── interview.ts                    # InterviewMessage, InterviewConfig
│   │   └── api.ts                          # ApiResponse<T>, PaginatedResponse<T>
│   │
│   ├── public/
│   │   └── favicon.ico
│   │
│   ├── styles/
│   │   ├── globals.css                     # Tailwind 指令 + 自定义变量
│   │   └── markdown.css                    # report Markdown 渲染样式
│   │
│   ├── .env.local.example
│   ├── next.config.js
│   ├── tailwind.config.ts
│   ├── tsconfig.json
│   └── package.json
│
├── docker-compose.yml                      # PostgreSQL
├── .gitignore
├── CLAUDE.md
├── plan.md
├── notice.md
└── README.md
```

### C.1 结构设计要点

| 维度 | 说明 |
|------|------|
| **前后端分离** | Next.js 前端只做展示和用户交互，所有业务逻辑在 FastAPI 后端 |
| **前端路由** | `workflows/[id]` 为主入口，Tabs 切换 interview / report / trace / events 四个子页 |
| **组件域分离** | `components/` 按业务域分目录，每个组件职责单一 |
| **React Query** | `lib/use-*.ts` 封装所有 API 调用 + 缓存 + 自动刷新，配合 SSE 实现实时进度 |
| **后端 service 层** | 复杂业务逻辑（多轮对话、搜索模板匹配、SSE 推送）从 API handler 抽离到 services/ |
| **测试分层** | agent 单元测试 → API 集成测试 → 端到端测试，对应第 2 周联调计划 |
