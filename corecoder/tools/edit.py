# 基于查找-替换的文件编辑工具（Claude Code 的核心创新）。
# 核心思路：不发送整文件重写、也不用行号补丁，
# 而是由 LLM 给出一段「精确子串」及其替换内容。
# 该子串必须在文件中恰好出现一次，从而消除歧义，让编辑安全、可审查。

import difflib
from pathlib import Path

from .base import Tool

# 跟踪本次会话中被改动的文件，供 /diff 查看变更使用
_changed_files: set[str] = set()


class EditFileTool(Tool):
    # 文件编辑工具：通过精确字符串匹配做替换
    name = "edit_file"
    description = (
        "Edit a file by replacing an exact string match. "
        "old_string must appear exactly once in the file for safety. "
        "Include enough surrounding context to ensure uniqueness."
    )
    parameters = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to the file to edit",
            },
            "old_string": {
                "type": "string",
                "description": "Exact text to find (must be unique in file)",
            },
            "new_string": {
                "type": "string",
                "description": "Replacement text",
            },
        },
        "required": ["file_path", "old_string", "new_string"],
    }

    def execute(self, file_path: str, old_string: str, new_string: str) -> str:
        try:
            p = Path(file_path).expanduser().resolve()
            if not p.exists():
                return f"Error: {file_path} not found"

            try:
                content = p.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                # 非文本文件（二进制）拒绝编辑
                return f"Error: {file_path} is not a UTF-8 text file (edit_file only edits text files)"
            # 统计 old_string 出现次数：必须恰好 1 次才安全
            occurrences = content.count(old_string)

            if occurrences == 0:
                # 没找到：返回文件开头预览，帮助模型定位
                preview = content[:500] + ("..." if len(content) > 500 else "")
                return (
                    f"Error: old_string not found in {file_path}.\n"
                    f"File starts with:\n{preview}"
                )
            if occurrences > 1:
                # 多次出现：要求模型补充更多上下文以唯一定位
                return (
                    f"Error: old_string appears {occurrences} times in {file_path}. "
                    f"Include more surrounding lines to make it unique."
                )

            # 恰好一次：执行替换（仅替换第一处，但因为只出现一次所以等价）
            new_content = content.replace(old_string, new_string, 1)
            p.write_text(new_content, encoding="utf-8")
            _changed_files.add(str(p))   # 记录本次会话改动的文件

            # 生成 unified diff，让用户/模型清楚看到具体改动
            diff = _unified_diff(content, new_content, str(p))
            return f"Edited {file_path}\n{diff}"
        except Exception as e:
            return f"Error: {e}"


def _unified_diff(old: str, new: str, filename: str, context: int = 3) -> str:
    # 生成紧凑的 unified diff，对比新旧文件内容
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    diff = difflib.unified_diff(
        old_lines, new_lines,
        fromfile=f"a/{filename}", tofile=f"b/{filename}",
        n=context,    # 上下文行数
    )
    result = "".join(diff)
    # diff 过长时截断
    if len(result) > 3000:
        result = result[:2500] + "\n... (diff truncated)\n"
    return result
