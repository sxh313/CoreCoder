"""File reading with line numbers."""
# 文件读取工具：读取文件内容并带行号输出

from pathlib import Path
from .base import Tool


class ReadFileTool(Tool):
    # 文件读取工具：带行号返回文件内容，便于后续 edit_file 定位
    name = "read_file"
    description = (
        "Read a file's contents with line numbers. "
        "Always read a file before editing it."
    )
    parameters = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to the file",
            },
            "offset": {
                "type": "integer",
                "description": "Start line (1-based). Default 1.",
            },
            "limit": {
                "type": "integer",
                "description": "Max lines to read. Default 2000.",
            },
        },
        "required": ["file_path"],
    }

    def execute(self, file_path: str, offset: int = 1, limit: int = 2000) -> str:
        try:
            p = Path(file_path).expanduser().resolve()
            if not p.exists():
                return f"Error: {file_path} not found"
            if not p.is_file():
                return f"Error: {file_path} is a directory, not a file"

            # errors="replace"：遇到解码错误用占位符替代，避免读取二进制片段时崩溃
            text = p.read_text(encoding="utf-8", errors="replace")
            lines = text.splitlines()
            total = len(lines)

            # offset 是 1-based，转换为 0-based 切片起点
            start = max(0, offset - 1)
            chunk = lines[start : start + limit]
            # 每行前加「行号\t」
            numbered = [f"{start + i + 1}\t{ln}" for i, ln in enumerate(chunk)]
            result = "\n".join(numbered)

            # 若还有未展示的行，追加提示
            if total > start + limit:
                result += f"\n... ({total} lines total, showing {start+1}-{start+len(chunk)})"
            return result or "(empty file)"
        except Exception as e:
            return f"Error: {e}"
