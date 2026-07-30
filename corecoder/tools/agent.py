# 子智能体派生工具（灵感来自 Claude Code 的 AgentTool，原版 1397 行）。
# 核心思路：对复杂子任务，派生一个独立的子智能体，拥有自己的对话历史和工具权限。
# 这样主智能体可以把「去研究代码库并汇报」之类的工作委派出去，
# 不会污染主智能体自身的上下文窗口。
# 子智能体会独立运行到完成，最后返回一段文本摘要。

from .base import Tool


class AgentTool(Tool):
    # 子智能体工具：让主智能体能派生独立子智能体处理复杂任务
    name = "agent"
    description = (
        "Spawn a sub-agent to handle a complex sub-task independently. "
        "The sub-agent has its own context and tool access. Use this for: "
        "researching a codebase, implementing a multi-step change in isolation, "
        "or any task that would benefit from a fresh context window."
    )
    parameters = {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "What the sub-agent should accomplish",
            },
        },
        "required": ["task"],
    }

    # 由 Agent.__init__ 在构造完成后注入：指向主（父）智能体
    _parent_agent = None

    def execute(self, task: str) -> str:
        if self._parent_agent is None:
            # 未注入父智能体，无法派生
            return "Error: agent tool not initialized (no parent agent)"

        # 在此导入，避免与 agent.py 产生循环依赖
        from ..agent import Agent

        parent = self._parent_agent
        # 创建子智能体：复用父智能体的 llm，但排除 agent 工具（禁止递归派生）
        sub = Agent(
            llm=parent.llm,
            tools=[t for t in parent.tools if t.name != "agent"],  # no recursive agents
            max_context_tokens=parent.context.max_tokens,
            max_rounds=20,
        )

        try:
            result = sub.chat(task)
            # 截断过长结果，避免撑爆父智能体的上下文
            if len(result) > 5000:
                result = result[:4500] + "\n... (sub-agent output truncated)"
            return f"[Sub-agent completed]\n{result}"
        except Exception as e:
            return f"Sub-agent error: {e}"
