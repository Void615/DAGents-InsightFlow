"""
langgraph stategraph building and dynamic DAG routing.
"""

import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command
from app.schemas.workflow_state import WorkflowState
from app.services.event_service import EventLogger
from app.core.graph_nodes import (
    make_collection_node,
    make_analysis_node,
    make_report_node,
    make_review_node,
)


REROUTE_TARGETS = ("information_collection", "analysis", "report_writing")


def make_pause_router(default_next: str):
    """创建暂停恢复后的通用条件路由函数。

    每个 DAG 节点都通过此路由决定下一步：正常完成时走 default_next，
    有人工 jump 或 agent 建议则走 target_node。

    优先级：
      1. 人工 jump + 有效 target_node → 跳到该节点
      2. state 中有 agent 建议的 target_node → 跳到该节点（fallback）
      3. 都没有 → default_next（正常流程）
    """
    def _router(state: dict) -> str:
        # 1. 人工决策优先——消费时立即清除，防止后续节点 router 重复路由
        human_decision = state.get("human_decision") or {}
        if human_decision.get("action") == "jump":
            target = human_decision.get("target_node")
            if target in REROUTE_TARGETS:
                return Command(goto=target, update={"human_decision": None})

        # 2. agent 建议的 target_node 作为 fallback
        review = state.get("review_result")
        if isinstance(review, dict):
            target = review.get("target_node")
            if target in REROUTE_TARGETS:
                return target

        # 3. 正常流程
        return default_next

    return _router


def compile_workflow_graph(
    db: AsyncSession,
    workflow_id: uuid.UUID,
    event_logger: EventLogger,
    execution_attempt: int,
    checkpointer: PostgresSaver | None = None,
):
    """编译 LangGraph StateGraph。

    所有节点均通过条件边连接，支持任意节点暂停后跳转：

      ┌────────────────── reroute ──────────────────┐
      ↓                                             │
      information_collection → analysis → report_writing → review
                                  ↑          ↑              │
                                  └──────────┴── reroute ───┘
                                                          │
                                                        done → END

    正常执行时 make_pause_router 返回 default_next，行为等价于线性 add_edge。
    有人工 jump 或 agent 建议的 target_node 时才走 reroute。
    """
    graph = StateGraph(WorkflowState)

    graph.add_node("information_collection", make_collection_node(db, workflow_id, event_logger, execution_attempt))
    graph.add_node("analysis", make_analysis_node(db, workflow_id, event_logger, execution_attempt))
    graph.add_node("report_writing", make_report_node(db, workflow_id, event_logger, execution_attempt))
    graph.add_node("review", make_review_node(db, workflow_id, event_logger, execution_attempt))

    graph.set_entry_point("information_collection")

    node_edges = [
        ("information_collection", "analysis"),
        ("analysis", "report_writing"),
        ("report_writing", "review"),
        ("review", "done"),
    ]
    for node_name, default_next in node_edges:
        mapping = {t: t for t in REROUTE_TARGETS}
        if default_next == "done":
            mapping["done"] = END
        else:
            mapping[default_next] = default_next
        graph.add_conditional_edges(node_name, make_pause_router(default_next), mapping)

    return graph.compile(checkpointer=checkpointer)
