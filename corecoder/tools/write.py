"""File creation / overwrite."""
# 文件创建/覆写工具：新建文件或整体覆盖已有文件

from pathlib import Path
from .base import Tool
from .edit import _changed_files   # 复用 edit.py 的「本次会话改动文件」集合


class WriteFileTool(Tool):
    # 写文件工具：整体写入（小改动建议改用 edit_file）
    name = "write_file"
    description = (
        "Create a new file or completely overwrite an existing one. "
        "For small edits to existing files, prefer edit_file instead."
    )
    parameters = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path for the file",
            },
            "content": {
                "type": "string",
                "description": "Full file content to write",
            },
        },
        "required": ["file_path", "content"],
    }

    def execute(self, file_path: str, content: str) -> str:
        try:
            p = Path(file_path).expanduser().resolve()
            # 父目录不存在时自动创建（类似 mkdir -p）
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            _changed_files.add(str(p))   # 记录本次会话改动的文件
            # 统计写入行数：换行符数 +（末尾无换行时补 1）
            n_lines = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
            return f"Wrote {n_lines} lines to {file_path}"
        except Exception as e:
            return f"Error: {e}"
