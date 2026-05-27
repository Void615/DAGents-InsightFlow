import json
from typing import AsyncGenerator, List
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, BaseMessage
from app.config import get_settings
from app.schemas.workflow import WorkflowConfig, ProductCategory


# 不同产品类别的搜索模板，供前端展示或后续集成搜索 API 时使用。
# 当前 interview 阶段不执行实际搜索，仅收集配置。
SEARCH_TEMPLATES = {
    ProductCategory.SAAS: {
        "general": "{competitor} 功能对比 定价 用户评价 site:zhihu.com OR site:sspai.com",
        "pricing": "{competitor} 订阅价格 收费模式 版本对比",
        "reviews": "{competitor} 差评 吐槽 使用体验"
    },
    ProductCategory.MOBILE_APP: {
        "general": "{competitor} 功能 评分 用户评价 site:apps.apple.com OR site:coolapk.com",
        "pricing": "{competitor} 内购 会员 价格",
        "reviews": "{competitor} 用户吐槽 体验问题 优缺点"
    },
    ProductCategory.HARDWARE: {
        "general": "{competitor} 参数 价格 评测 site:zhihu.com OR site:smzdm.com",
        "pricing": "{competitor} 售价 首发价 历史价格",
        "reviews": "{competitor} 测评 拆机 优缺点"
    }
}


SYSTEM_PROMPT = """你是一个专业的竞品分析访谈助手，负责在正式启动多Agent分析之前，通过自然的多轮对话，引导用户明确以下信息：
1. 要做竞品分析的目标产品是什么
2. 产品属于哪一类（SaaS / 协作工具、移动应用、硬件产品）
3. 你希望重点关注哪些分析维度
4. 最多需要对比多少个竞品
5. 你有没有其他额外的分析要求

规则：
- 不要一次把所有问题全部抛给用户，用非常自然的对话引导用户逐步说明
- 当信息收集完整后，用清晰的结构化卡片形式展示你理解到的配置，请求用户确认
- 确认后输出完整的WorkflowConfig JSON，格式必须符合规范
- 所有输出语言保持中文
- 不要做任何无关闲聊，始终围绕竞品分析需求展开
- 输出的JSON必须严格是以下Schema，不要额外字段：
{
  "target_product": "字符串，目标产品名称",
  "product_category": "字符串，必须是三个选项之一：SaaS / 协作工具、移动应用、硬件产品",
  "focus_dimensions": "字符串数组，用户指定的关注维度",
  "competitor_count": "整数，1-10之间",
  "competitors": "字符串数组，确定的竞品名称列表",
  "language": "zh",
  "extra_requirements": "字符串"
}

当配置确认完全无误后，在回复末尾单独一行输出 ---CONFIG_COMPLETE---"""


class InterviewAgent:
    """访谈 Agent：多轮对话引导用户明确竞品分析配置。

    独立于 DAG 工作流之外，在工作流创建前运行。
    通过 SSE 流式输出对话内容，最终解析 WorkflowConfig 用于创建正式工作流。

    与 DAG 内 agent 的区别：
    - 不继承 BaseAgent（不参与 LangGraph 编排，无 node_name）
    - 直接管理自己的 ChatOpenAI 实例（streaming=True，用于对话场景）
    - 使用 ---CONFIG_COMPLETE--- 哨兵标记对话结束，而非结构化输出解析
    """

    def __init__(self):
        settings = get_settings()
        self.llm = ChatOpenAI(
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_BASE_URL,
            model=settings.LLM_MODEL,
            temperature=settings.LLM_TEMPERATURE,
            streaming=True
        )
        self.system_message = SystemMessage(content=SYSTEM_PROMPT)

    async def stream_response(self, history_messages: List[BaseMessage]) -> AsyncGenerator[str, None]:
        """流式生成访谈回复，逐 token yield 供 SSE 推向前端。"""
        full_content = ""
        async for chunk in self.llm.astream([self.system_message] + history_messages):
            content = chunk.content
            if isinstance(content, list):
                content = "".join(b.get("text", "") for b in content if isinstance(b, dict))
            if content:
                full_content += content
                yield content

    def try_extract_config(self, full_text: str) -> WorkflowConfig | None:
        """从 LLM 累积回复中提取 WorkflowConfig。

        采用宽松匹配（取第一个 { 到最后一个 }），而非要求 JSON 是唯一内容，
        因为 LLM 可能在对话文本中嵌入 JSON 而非单独输出。
        """
        try:
            start = full_text.find("{")
            end = full_text.rfind("}")
            if start != -1 and end != -1:
                json_str = full_text[start:end+1]
                data = json.loads(json_str)
                return WorkflowConfig(**data)
        except Exception:
            return None
        return None

    def is_complete_signal(self, full_text: str) -> bool:
        """检测 LLM 是否输出了配置完成哨兵。

        哨兵机制比 try_extract_config 更可靠：LLM 可能提前输出类似 JSON 的文本
        但实际尚未完成信息收集，哨兵保证配置是 LLM 确认后的最终版本。
        """
        return "---CONFIG_COMPLETE---" in full_text
