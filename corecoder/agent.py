"""
这是 CoreCoder（代码核心智能体）的核心运行机制。整体执行流程非常简洁：

用户消息 → 大模型（搭载工具调用能力）
    ↓ 分支判断
    1. 若输出工具调用指令 → 执行对应工具 → 回到循环头部重复流程
    2. 若输出纯文本回复 → 直接返回结果给用户

循环会持续迭代运行，直到大模型仅返回纯文本内容（不再附带任何工具调用指令），此时代表任务处理完毕，可以向用户输出最终结果。
"""

import concurrent.futures
import inspect
from .llm import LLM
from .tools import ALL_TOOLS
from .tools.base import Tool
from .tools.agent import AgentTool
from .prompt import system_prompt
from .context import ContextManager


class Agent:
    """代码核心智能体：协调大模型与工具，循环执行直到产出最终回复。"""

    def __init__(
        self,
        llm: LLM,
        tools: list[Tool] | None = None,
        max_context_tokens: int = 128_000,
        max_rounds: int = 50,
    ):
        self.llm = llm                              # 底层大模型（LLM / LiteLLM 实例）
        self.tools = tools if tools is not None else ALL_TOOLS  # 可用工具列表，默认注册全部工具
        self._tool_by_name = {t.name: t for t in self.tools}    # 工具名 → 工具对象 的查找表
        self.messages: list[dict] = []              # 对话历史（OpenAI 消息格式）
        self.context = ContextManager(max_tokens=max_context_tokens)  # 上下文管理器（负责压缩/裁剪）
        self.max_rounds = max_rounds                # 工具调用最大轮数，防止死循环
        self._system = system_prompt(self.tools)    # 根据工具列表生成的系统提示词

        # wire up sub-agent capability
        # 把子智能体能力接线进来：找到 AgentTool，设置其父智能体为当前 self
        for t in self.tools:
            if isinstance(t, AgentTool):
                t._parent_agent = self

    def _full_messages(self) -> list[dict]:
        """拼装完整消息列表：系统提示词 + 历史消息。"""
        return [{"role": "system", "content": self._system}] + self.messages

    def _tool_schemas(self) -> list[dict]:
        """获取所有工具的 JSON Schema 定义（传给模型的 tools 参数）。"""
        return [t.schema() for t in self.tools]

    def chat(self, user_input: str, on_token=None, on_tool=None) -> str:
        """Process one user message. May involve multiple LLM/tool rounds."""
        # 处理一条用户消息，可能包含多轮 LLM/工具调用
        self.messages.append({"role": "user", "content": user_input})  # 追加用户消息
        self.context.maybe_compress(self.messages, self.llm)           # 必要时压缩上下文

        for _ in range(self.max_rounds):
            # 调用大模型，传入完整消息 + 工具 schema，流式返回
            resp = self.llm.chat(
                messages=self._full_messages(),
                tools=self._tool_schemas(),
                on_token=on_token,
            )

            # no tool calls -> LLM is done, return text
            # 没有工具调用 → 模型已完成，直接返回文本
            if not resp.tool_calls:
                self.messages.append(resp.message)  # 记录助手回复
                return resp.content

            # tool calls -> execute (parallel when multiple, like Claude Code's
            # StreamingToolExecutor which runs independent tools concurrently)
            # 有工具调用 → 执行工具（多个时并行执行，类似 Claude Code 的 StreamingToolExecutor）
            self.messages.append(resp.message)      # 先记录含 tool_calls 的助手消息

            try:
                if len(resp.tool_calls) == 1:
                    # 单个工具调用：直接执行
                    tc = resp.tool_calls[0]
                    if on_tool:
                        on_tool(tc.name, tc.arguments)   # 触发工具回调
                    result = self._exec_tool(tc)
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,    # 必须对应到上面的 tool_calls id
                        "content": result,        # 工具返回结果
                    })
                else:
                    # parallel execution for multiple tool calls
                    # 多个工具调用：并行执行
                    results = self._exec_tools_parallel(resp.tool_calls, on_tool)
                    for tc, result in zip(resp.tool_calls, results):
                        self.messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": result,
                        })
            except KeyboardInterrupt:
                # Ctrl+C mid-execution would leave the assistant tool_calls
                # message without replies, poisoning the next request; backfill
                # 执行中 Ctrl+C 会导致助手消息的 tool_calls 没有对应回复，
                # 这会污染下一次请求（OpenAI 要求每个 tool_calls id 都有回复），因此回填占位
                self._answer_pending_tool_calls(resp.tool_calls)
                raise

            # compress if tool outputs are big
            # 工具输出可能很大，按需压缩上下文
            self.context.maybe_compress(self.messages, self.llm)

        # 达到最大轮数仍未结束，返回提示
        return "(reached maximum tool-call rounds)"

    def _exec_tool(self, tc) -> str:
        """Execute a single tool call, returning the result string."""
        # 执行单个工具调用，返回结果字符串
        tool = self._tool_by_name.get(tc.name)
        if tool is None:
            return f"Error: unknown tool '{tc.name}'"   # 未知工具
        # validate arguments first so a TypeError raised *inside* the tool isn't
        # mislabelled as a bad-arguments error from the caller
        # 先校验参数签名：避免把工具内部抛出的 TypeError 误判成调用方传参错误
        try:
            inspect.signature(tool.execute).bind(**tc.arguments)
        except TypeError as e:
            return f"Error: bad arguments for {tc.name}: {e}"   # 参数不匹配
        try:
            return tool.execute(**tc.arguments)
        except Exception as e:
            return f"Error executing {tc.name}: {e}"   # 工具执行异常，转成错误字符串返回

    def _exec_tools_parallel(self, tool_calls, on_tool=None) -> list[str]:
        """Run multiple tool calls concurrently using threads.

        This is inspired by Claude Code's StreamingToolExecutor which starts
        executing tools while the model is still generating.  We simplify to:
        when the model returns N tool calls at once, run them in parallel.
        """
        # 用线程池并发执行多个工具调用。
        # 灵感来自 Claude Code 的 StreamingToolExecutor（边生成边执行），
        # 这里简化为：模型一次返回 N 个工具调用时，并行执行。
        for tc in tool_calls:
            if on_tool:
                on_tool(tc.name, tc.arguments)   # 触发每个工具的回调

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            # 提交所有任务，最多 8 个工作线程
            futures = [pool.submit(self._exec_tool, tc) for tc in tool_calls]
            # 按提交顺序收集结果
            return [f.result() for f in futures]

    def _answer_pending_tool_calls(self, tool_calls):
        """Backfill a tool reply for every call that didn't get one.

        OpenAI-compatible APIs reject a request where an assistant message has
        tool_calls without a matching tool reply for each id, so this keeps the
        history valid when execution is interrupted partway through.
        """
        # 为每个尚未回复的工具调用补一条占位回复。
        # OpenAI 兼容接口要求：助手消息里的每个 tool_calls id 都必须有对应的 tool 回复，
        # 否则下一次请求会被拒绝。本方法用于执行被中途打断时，保持历史消息合法。
        answered = {m.get("tool_call_id") for m in self.messages if m.get("role") == "tool"}
        for tc in tool_calls:
            if tc.id not in answered:
                self.messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": "[interrupted]",   # 占位内容，表示被中断
                })

    def reset(self):
        """Clear conversation history."""
        # 清空对话历史（开始新会话）
        self.messages.clear()
