"""
绝大多数大模型服务商都对外提供兼容 OpenAI 标准格式的接口地址，
因此我们可以直接复用官方 openai SDK 完成调用。
仅需修改环境变量 OPENAI_BASE_URL（接口地址）与 OPENAI_API_KEY（密钥），
即可无缝切换不同模型服务商，无需改动业务代码。

针对不兼容 OpenAI 接口规范的服务商（AWS Bedrock、Google Vertex AI 等），
统一使用 LiteLLM 后端适配：LiteLLM 通过一套标准化接口封装了上百种大模型服务。
只需配置环境变量 CORECODER_PROVIDER=litellm 即可启用该适配模式。
"""

import json
import time
from dataclasses import dataclass, field

from openai import OpenAI, APIError, BadRequestError, RateLimitError, APITimeoutError, APIConnectionError


@dataclass
class ToolCall:
    """一次工具（函数）调用的结构化表示。"""
    id: str            # 工具调用唯一标识，由模型生成，回传结果时需要带上
    name: str          # 要调用的函数名
    arguments: dict    # 函数参数（已从 JSON 字符串解析为字典）


@dataclass
class LLMResponse:
    """大模型单次回复的统一封装。"""
    content: str = ""                              # 模型返回的文本内容
    tool_calls: list[ToolCall] = field(default_factory=list)  # 模型请求的工具调用列表
    prompt_tokens: int = 0       # 本次输入消耗的 token 数
    completion_tokens: int = 0   # 本次输出消耗的 token 数

    @property
    def message(self) -> dict:
        """转换为 OpenAI 消息格式，便于追加到对话历史。"""
        # self.content or None：空字符串转成 None（OpenAI 格式要求空内容用 None）
        msg: dict = {"role": "assistant", "content": self.content or None}
        if self.tool_calls:
            # 把 ToolCall 转成 OpenAI 的嵌套格式
            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        # json.dumps 把 dict 转成 JSON 字符串（OpenAI 要求 arguments 是字符串）
                        "arguments": json.dumps(tc.arguments),
                    },
                }
                for tc in self.tool_calls
            ]
        return msg


# pricing per million tokens: (input, output)
# 计费标准：单价单位为每百万Token，格式(输入单价, 输出单价)
# 官方价格来源
_PRICING = {
    # OpenAI - current flagships
    "gpt-5.5": (5, 30),
    "gpt-5.4": (2.5, 15),
    "gpt-5.4-mini": (0.75, 4.5),
    "gpt-5.4-nano": (0.2, 1.25),
    "o4-mini": (1.1, 4.4),
    # OpenAI - previous gen (still widely used)
    "gpt-4.1": (2, 8),
    "gpt-4.1-mini": (0.4, 1.6),
    "gpt-4.1-nano": (0.1, 0.4),
    "gpt-4o": (2.5, 10),
    "gpt-4o-mini": (0.15, 0.6),
    # DeepSeek
    "deepseek-chat": (0.27, 1.10),
    "deepseek-reasoner": (0.55, 2.19),
    # Anthropic Claude
    "claude-opus-4-6": (5, 25),
    "claude-sonnet-4-6": (3, 15),
    "claude-haiku-4-5": (1, 5),
    # Alibaba Qwen
    "qwen3-max": (0.78, 3.9),
    "qwen3-plus": (0.26, 0.78),
    "qwen-max": (0.78, 3.9),
    # Moonshot Kimi
    "kimi-k2.5": (0.6, 3),
}


class LLM:
    """基于 OpenAI 兼容接口的大模型统一封装。"""

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str | None = None,
        **kwargs,
    ):
        self.model = model                                  # 模型名称，如 "gpt-4o"、"deepseek-chat"
        self.client = OpenAI(api_key=api_key, base_url=base_url)  # OpenAI 客户端（兼容各服务商）
        self.extra = kwargs  # 额外参数：temperature、max_tokens 等，调用时展开传入
        self.total_prompt_tokens = 0        # 累计输入 token（用于成本估算）
        self.total_completion_tokens = 0    # 累计输出 token（用于成本估算）

    @property
    def estimated_cost(self) -> float | None:
        """粗略估算累计花费（美元）。模型不在价格表中时返回 None。"""
        pricing = _PRICING.get(self.model)
        if not pricing:
            return None
        input_rate, output_rate = pricing   # 解包出输入、输出单价（每百万 token）
        # 花费 = 输入token × 输入单价 / 1_000_000 + 输出token × 输出单价 / 1_000_000
        return (
            self.total_prompt_tokens * input_rate / 1_000_000
            + self.total_completion_tokens * output_rate / 1_000_000
        )

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        on_token=None,
    ) -> LLMResponse:
        """Send messages, stream back response, handle tool calls."""
        # 组装请求参数
        params: dict = {
            "model": self.model,
            "messages": messages,
            "stream": True,        # 流式返回，边生成边接收
            **self.extra,          # 展开额外参数（temperature 等）
        }
        if tools:
            params["tools"] = tools   # 可选：函数工具定义

        # stream_options 是 OpenAI 接口扩展参数；
        # 仅当模型服务商直接拒绝该参数（返回400错误请求）时，才降级舍弃该参数
        # 若只是临时波动类报错（已通过 _call_with_retry 耗尽重试次数），则不做降级处理；
        # 否则会造成双重重试逻辑，大幅拉高调用次数
        params["stream_options"] = {"include_usage": True}  # 让最后一块返回本次用量
        try:
            stream = self._call_with_retry(params)
        except BadRequestError:
            # 服务商不支持 stream_options 时，移除后重试一次
            params.pop("stream_options", None)
            stream = self._call_with_retry(params)

        content_parts: list[str] = []          # 累积文本片段
        # index -> {id, name, arguments_str}，按工具调用下标聚合分片
        tc_map: dict[int, dict] = {}
        prompt_tok = 0          # 本次输入 token 数
        completion_tok = 0      # 本次输出 token 数

        for chunk in stream:
            # usage info comes in the final chunk
            if chunk.usage:
                # 部分模型服务商返回的用量数据中会存在空字段（null）；需要强制转换为数字0，
                # 防止下方累加统计总消耗时，出现「整数 + 空值」的运算报错导致程序崩溃
                prompt_tok = chunk.usage.prompt_tokens or 0
                completion_tok = chunk.usage.completion_tokens or 0

            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta

            # accumulate text
            if delta.content:
                content_parts.append(delta.content)   # 拼接文本片段
                if on_token:
                    on_token(delta.content)            # 触发回调：实时输出

            # accumulate tool calls across chunks
            # 工具调用也是流式的：同一个调用的 id/name/arguments 会分散到多个 chunk
            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index   # 用 index 作为 key 聚合同一个调用的分片
                    if idx not in tc_map:
                        tc_map[idx] = {"id": "", "name": "", "args": ""}
                    if tc_delta.id:
                        tc_map[idx]["id"] = tc_delta.id
                    if tc_delta.function:
                        if tc_delta.function.name:
                            tc_map[idx]["name"] = tc_delta.function.name
                        # arguments 是 JSON 字符串片段，需要 += 拼接（中途无法解析）
                        if tc_delta.function.arguments:
                            tc_map[idx]["args"] += tc_delta.function.arguments

        # parse accumulated tool calls
        # 解析拼接好的工具调用
        parsed: list[ToolCall] = []
        for idx in sorted(tc_map):    # 按 index 排序，保证顺序正确
            raw = tc_map[idx]
            try:
                args = json.loads(raw["args"])   # 把 JSON 字符串解析为 dict
            except (json.JSONDecodeError, KeyError):
                args = {}    # 解析失败兜底为空 dict，避免崩溃
            parsed.append(ToolCall(id=raw["id"], name=raw["name"], arguments=args))

        # 累加本次 token 到总量（用于成本估算）
        self.total_prompt_tokens += prompt_tok
        self.total_completion_tokens += completion_tok

        return LLMResponse(
            content="".join(content_parts),   # 拼接成完整文本
            tool_calls=parsed,
            prompt_tokens=prompt_tok,
            completion_tokens=completion_tok,
        )

    def _call_with_retry(self, params: dict, max_retries: int = 3):
        """遇到临时性错误时按指数退避重试。"""
        for attempt in range(max_retries):
            try:
                return self.client.chat.completions.create(**params)
            except (RateLimitError, APITimeoutError, APIConnectionError):
                # 限流 / 超时 / 网络错误：可重试
                if attempt == max_retries - 1:
                    raise   # 最后一次仍失败，直接抛出
                wait = 2 ** attempt     # 指数退避：1s、2s、4s
                time.sleep(wait)
            except APIError as e:
                # retry 5xx server errors but not 4xx
                # 重试 5xx 服务端错误，但不重试 4xx 客户端错误
                # 基类 APIError 没有 status_code 属性，需防御性读取
                status_code = getattr(e, "status_code", None)
                if status_code and status_code >= 500 and attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    raise


class LiteLLM(LLM):
    """
    基于 LiteLLM 实现大模型后端，支持百余种模型服务商。

    当目标模型服务商不兼容 OpenAI 接口规范（AWS Bedrock、Google Vertex、Cohere 等），
    或是你希望通过仅修改模型标识字符串、用统一接口无缝切换所有服务商时，请使用该模式。

    配置环境变量 CORECODER_PROVIDER=litellm，同时采用 LiteLLM 标准模型标识格式，例如：
    anthropic/claude-3-haiku、bedrock/anthropic.claude-v2、vertex_ai/gemini-pro 等。
    """

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        **kwargs,
    ):
        # skip LLM.__init__ which creates an OpenAI client
        # 跳过父类 LLM.__init__（它会创建 OpenAI 客户端），改用 litellm 适配
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.extra = kwargs
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        on_token=None,
    ) -> LLMResponse:
        """Send messages via litellm, stream back response, handle tool calls."""
        # 通过 litellm 发送消息、流式接收回复、处理工具调用
        params: dict = {
            "model": self.model,
            "messages": messages,
            "stream": True,        # 流式返回
            **self.extra,
        }
        if tools:
            params["tools"] = tools

        # ask for usage stats in the final chunk; litellm drops this for providers
        # that don't support it (drop_params), so it's safe to always request
        # 请求最后一块返回用量；litellm 对不支持该参数的服务商会自动丢弃，所以总是请求是安全的
        params["stream_options"] = {"include_usage": True}
        stream = self._call_with_retry(params)

        content_parts: list[str] = []
        tc_map: dict[int, dict] = {}  # 按工具调用下标聚合分片
        prompt_tok = 0
        completion_tok = 0

        for chunk in stream:
            # 不同服务商返回结构有差异，用 getattr 防御性读取
            usage = getattr(chunk, "usage", None)
            if usage:
                prompt_tok = getattr(usage, "prompt_tokens", 0) or 0
                completion_tok = getattr(usage, "completion_tokens", 0) or 0

            if not getattr(chunk, "choices", None):
                continue
            delta = chunk.choices[0].delta

            if getattr(delta, "content", None):
                content_parts.append(delta.content)
                if on_token:
                    on_token(delta.content)

            if getattr(delta, "tool_calls", None):
                # 工具调用流式分片，按 index 聚合
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in tc_map:
                        tc_map[idx] = {"id": "", "name": "", "args": ""}
                    if tc_delta.id:
                        tc_map[idx]["id"] = tc_delta.id
                    if tc_delta.function:
                        if tc_delta.function.name:
                            tc_map[idx]["name"] = tc_delta.function.name
                        # arguments 是 JSON 字符串片段，需要 += 拼接
                        if tc_delta.function.arguments:
                            tc_map[idx]["args"] += tc_delta.function.arguments

        # 解析拼接好的工具调用
        parsed: list[ToolCall] = []
        for idx in sorted(tc_map):    # 按 index 排序，保证顺序正确
            raw = tc_map[idx]
            try:
                args = json.loads(raw["args"])   # 解析为 dict
            except (json.JSONDecodeError, KeyError):
                args = {}    # 解析失败兜底为空 dict
            parsed.append(ToolCall(id=raw["id"], name=raw["name"], arguments=args))

        # 累加本次 token 到总量
        self.total_prompt_tokens += prompt_tok
        self.total_completion_tokens += completion_tok

        return LLMResponse(
            content="".join(content_parts),   # 拼接成完整文本
            tool_calls=parsed,
            prompt_tokens=prompt_tok,
            completion_tokens=completion_tok,
        )

    def _call_with_retry(self, params: dict, max_retries: int = 3):
        """Retry on transient errors with exponential backoff via litellm."""
        # 通过 litellm 调用，遇到临时性错误时按指数退避重试
        import litellm

        params["drop_params"] = True   # 自动丢弃服务商不支持的参数
        if self.api_key:
            params["api_key"] = self.api_key
        if self.base_url:
            params["api_base"] = self.base_url

        for attempt in range(max_retries):
            try:
                return litellm.completion(**params)
            except Exception as e:
                # 通过错误信息关键词判断错误类型
                err = str(e).lower()
                # 临时性错误：限流、超时、连接、服务端波动
                is_transient = any(
                    kw in err
                    for kw in ["rate_limit", "timeout", "connection", "502", "503", "529"]
                )
                # 5xx 服务端错误
                is_server = any(kw in err for kw in ["500", "502", "503", "504"])
                if (is_transient or is_server) and attempt < max_retries - 1:
                    time.sleep(2 ** attempt)    # 指数退避
                else:
                    raise   # 非临时错误或重试耗尽，直接抛出
