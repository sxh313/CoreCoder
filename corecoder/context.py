"""Multi-layer context compression.

Claude Code uses a 4-layer strategy:
  1. HISTORY_SNIP   - trim old tool outputs to a one-line summary
  2. Microcompact   - LLM-powered summary of old turns (cached)
  3. CONTEXT_COLLAPSE - aggressive compression when nearing hard limit
  4. Autocompact    - periodic background compaction

CoreCoder implements the same idea in 3 layers:
  Layer 1 (tool_snip)   - replace verbose tool results with truncated versions
  Layer 2 (summarize)   - LLM-powered summary of old conversation
  Layer 3 (hard_collapse) - last resort: drop everything except summary + recent
"""
# 多层上下文压缩模块。
# Claude Code 采用 4 层策略：
#   1. HISTORY_SNIP     —— 把旧的工具输出裁剪成一行摘要
#   2. Microcompact     —— 用 LLM 对旧的对话轮次做摘要（带缓存）
#   3. CONTEXT_COLLAPSE —— 接近硬上限时进行激进压缩
#   4. Autocompact      —— 周期性后台压缩
#
# CoreCoder 实现了同样的思路，精简为 3 层：
#   第 1 层 (tool_snip)     —— 把冗长的工具结果替换为截断版本
#   第 2 层 (summarize)     —— 用 LLM 对旧对话做摘要
#   第 3 层 (hard_collapse) —— 最后手段：丢弃一切，只保留摘要 + 最近消息

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # 仅用于类型标注，避免运行时循环导入
    from .llm import LLM


def _approx_tokens(text: str) -> int:
    """Rough token count, roughly 3 chars per token for mixed en/zh content."""
    # 粗略估算 token 数：中英混合内容大约每 3 个字符算 1 个 token
    return len(text) // 3


def estimate_tokens(messages: list[dict]) -> int:
    # 估算整段消息列表占用的 token 数（content + tool_calls 都计入）
    total = 0
    for m in messages:
        if m.get("content"):
            total += _approx_tokens(m["content"])
        if m.get("tool_calls"):
            total += _approx_tokens(str(m["tool_calls"]))
    return total


class ContextManager:
    # 上下文管理器：根据 token 用量自动触发多层压缩
    def __init__(self, max_tokens: int = 128_000):
        self.max_tokens = max_tokens
        # layer thresholds (fraction of max_tokens)
        # 各层触发阈值（占 max_tokens 的比例）
        self._snip_at = int(max_tokens * 0.50)    # 50% -> 裁剪工具输出
        self._summarize_at = int(max_tokens * 0.70)  # 70% -> LLM 摘要
        self._collapse_at = int(max_tokens * 0.90)   # 90% -> 硬性折叠

    def maybe_compress(self, messages: list[dict], llm: LLM | None = None) -> bool:
        """Apply compression layers as needed. Returns True if any compression happened."""
        # 按需应用压缩层；若发生了任何压缩则返回 True
        current = estimate_tokens(messages)
        compressed = False

        # Layer 1: snip verbose tool outputs
        # 第 1 层：裁剪冗长的工具输出
        if current > self._snip_at:
            if self._snip_tool_outputs(messages):
                compressed = True
                current = estimate_tokens(messages)

        # Layer 2: LLM-powered summarization of old turns
        # 第 2 层：用 LLM 对旧轮次做摘要
        if current > self._summarize_at and len(messages) > 10:
            if self._summarize_old(messages, llm, keep_recent=8):
                compressed = True
                current = estimate_tokens(messages)

        # Layer 3: hard collapse - last resort
        # 第 3 层：硬性折叠 —— 最后手段
        if current > self._collapse_at and len(messages) > 4:
            self._hard_collapse(messages, llm)
            compressed = True

        return compressed

    @staticmethod
    def _snip_tool_outputs(messages: list[dict]) -> bool:
        """Layer 1: Truncate tool results over 1500 chars to their first/last lines.

        This mirrors Claude Code's HISTORY_SNIP which replaces old tool outputs
        with a one-line summary to reclaim context space.
        """
        # 第 1 层：把超过 1500 字符的工具结果截断为「前 3 行 + 后 3 行」。
        # 对应 Claude Code 的 HISTORY_SNIP：用一行摘要替换旧工具输出，腾出上下文空间。
        changed = False
        for m in messages:
            if m.get("role") != "tool":
                continue
            content = m.get("content", "")
            if len(content) <= 1500:
                continue
            lines = content.splitlines()
            if len(lines) <= 6:
                continue
            # keep first 3 + last 3 lines
            # 保留前 3 行 + 后 3 行
            snipped = (
                "\n".join(lines[:3])
                + f"\n... ({len(lines)} lines, snipped to save context) ...\n"
                + "\n".join(lines[-3:])
            )
            m["content"] = snipped
            changed = True
        return changed

    @staticmethod
    def _safe_split(messages: list[dict], keep_recent: int) -> int:
        """Index where the kept tail should start.

        Walk the boundary back so a 'tool' result is never separated from the
        assistant message whose tool_calls produced it - an orphaned tool
        message has no preceding tool_calls and OpenAI-compatible APIs reject it.
        """
        # 计算保留的尾部从哪个下标开始。
        # 把边界往回挪，确保不会把「tool 结果」与其对应的「assistant tool_calls」拆开：
        # 孤立的 tool 消息前面没有 tool_calls，OpenAI 兼容接口会拒绝这种请求。
        split = max(0, len(messages) - keep_recent)
        while split > 0 and messages[split].get("role") == "tool":
            split -= 1
        return split

    def _summarize_old(self, messages: list[dict], llm: LLM | None,
                       keep_recent: int = 8) -> bool:
        """Layer 2: Summarize old conversation, keep recent messages intact."""
        # 第 2 层：摘要旧对话，保留最近的消息不动
        if len(messages) <= keep_recent:
            return False

        split = self._safe_split(messages, keep_recent)
        old = messages[:split]      # 旧消息：用来做摘要
        tail = messages[split:]     # 最近消息：原样保留

        summary = self._get_summary(old, llm)

        # 用「摘要 + 一句应答」替换掉旧消息，再拼回最近消息
        messages.clear()
        messages.append({
            "role": "user",
            "content": f"[Context compressed - conversation summary]\n{summary}",
        })
        messages.append({
            "role": "assistant",
            "content": "Got it, I have the context from our earlier conversation.",
        })
        messages.extend(tail)
        return True

    def _hard_collapse(self, messages: list[dict], llm: LLM | None):
        """Layer 3: Emergency compression. Keep only last 4 messages + summary."""
        # 第 3 层：紧急压缩。只保留最后 4 条消息 + 摘要
        split = self._safe_split(messages, 4 if len(messages) > 4 else 2)
        tail = messages[split:]
        summary = self._get_summary(messages[:split], llm)

        messages.clear()
        messages.append({
            "role": "user",
            "content": f"[Hard context reset]\n{summary}",
        })
        messages.append({
            "role": "assistant",
            "content": "Context restored. Continuing from where we left off.",
        })
        messages.extend(tail)

    def _get_summary(self, messages: list[dict], llm: LLM | None) -> str:
        """Generate summary via LLM or fallback to extraction."""
        # 优先用 LLM 生成摘要；失败或无 llm 时回退到正则抽取
        flat = self._flatten(messages)

        if llm:
            try:
                resp = llm.chat(
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "Compress this conversation into a brief summary. "
                                "Preserve: file paths edited, key decisions made, "
                                "errors encountered, current task state. "
                                "Drop: verbose command output, code listings, "
                                "redundant back-and-forth."
                            ),
                        },
                        {"role": "user", "content": flat[:15000]},
                    ],
                )
                return resp.content
            except Exception:
                pass   # LLM 摘要失败，走兜底逻辑

        # fallback: extract key lines
        # 兜底：抽取关键信息
        return self._extract_key_info(messages)

    @staticmethod
    def _flatten(messages: list[dict]) -> str:
        # 把消息列表拍平成纯文本，每条限 400 字符，供摘要使用
        parts = []
        for m in messages:
            role = m.get("role", "?")
            text = m.get("content", "") or ""
            if text:
                parts.append(f"[{role}] {text[:400]}")
        return "\n".join(parts)

    @staticmethod
    def _extract_key_info(messages: list[dict]) -> str:
        """Fallback: extract file paths, errors, and decisions without LLM."""
        # 兜底方案：不用 LLM，直接抽取文件路径、错误行等关键信息
        import re
        files_seen = set()
        errors = []

        for m in messages:
            text = m.get("content", "") or ""
            # extract file paths
            # 抽取文件路径（形如 xxx.yyy）
            for match in re.finditer(r'[\w./\-]+\.\w{1,5}', text):
                files_seen.add(match.group())
            # extract error lines
            # 抽取含 "error" 的行
            for line in text.splitlines():
                if "error" in line.lower():
                    errors.append(line.strip()[:150])

        parts = []
        if files_seen:
            parts.append(f"Files touched: {', '.join(sorted(files_seen)[:20])}")
        if errors:
            parts.append(f"Errors seen: {'; '.join(errors[:5])}")
        return "\n".join(parts) or "(no extractable context)"
