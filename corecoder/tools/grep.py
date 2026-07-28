"""Content search with regex support."""
# 文件内容搜索工具：支持正则表达式

import re
from pathlib import Path
from .base import Tool

# skip these dirs to avoid noise
# 搜索时跳过这些目录，避免噪声和无意义结果
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".tox", "dist", "build"}


class GrepTool(Tool):
    # grep 工具：在文件内容里做正则搜索
    name = "grep"
    description = (
        "Search file contents with regex. "
        "Returns matching lines with file path and line number."
    )
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Regex pattern to search for",
            },
            "path": {
                "type": "string",
                "description": "File or directory to search (default: cwd)",
            },
            "include": {
                "type": "string",
                "description": "Only search files matching this glob (e.g. '*.py')",
            },
        },
        "required": ["pattern"],
    }

    def execute(self, pattern: str, path: str = ".", include: str | None = None) -> str:
        try:
            regex = re.compile(pattern)   # 预编译正则
        except re.error as e:
            return f"Invalid regex: {e}"

        base = Path(path).expanduser().resolve()
        if not base.exists():
            return f"Error: {path} not found"

        if base.is_file():
            # 单个文件：直接搜该文件
            files = [base]
        else:
            # 目录：递归收集文件
            files = self._walk(base, include)

        matches = []
        for fp in files:
            try:
                text = fp.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            # 逐行匹配，记录「文件:行号: 内容」
            for lineno, line in enumerate(text.splitlines(), 1):
                if regex.search(line):
                    matches.append(f"{fp}:{lineno}: {line.rstrip()}")
                    if len(matches) >= 200:
                        # 命中数上限，防止结果过长
                        matches.append("... (200 match limit reached)")
                        return "\n".join(matches)

        return "\n".join(matches) if matches else "No matches found."

    @staticmethod
    def _walk(root: Path, include: str | None) -> list[Path]:
        """Walk dir tree, skipping junk dirs."""
        # 遍历目录树，跳过垃圾目录
        results = []
        for item in root.rglob(include or "*"):
            # skip junk dirs *inside* the search root - matching item.parts would
            # also catch an ancestor named e.g. "build" and hide the whole tree
            # 只跳过「搜索根目录内部」的垃圾目录；
            # 若直接匹配 item.parts，会连名为 build 的祖先目录也一起跳过，导致整棵树被隐藏
            if any(part in _SKIP_DIRS for part in item.relative_to(root).parts):
                continue
            if item.is_file():
                results.append(item)
            if len(results) >= 5000:
                # 收集上限，防止超大目录耗尽内存
                break
        return results
