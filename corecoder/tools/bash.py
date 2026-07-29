# 带安全检查的 shell 命令执行工具。
# Claude Code 的 BashTool 有 1143 行，这里是精简版：
# - 输出捕获 + 截断（保留头尾，省略中间）
# - 超时支持
# - 危险命令检测
# - 工作目录跟踪（感知 cd 命令）

import os
import re
import subprocess
import threading
from .base import Tool

# 跨命令跟踪 cwd（Claude Code 也这么做）。使用线程本地存储，这样当智能体并行
# 执行多个工具时，两个 bash 调用不会在同一个全局变量上竞争：
# 每个工作线程都携带自己独立的 cwd。
_local = threading.local()

# 危险命令正则模式：可能破坏文件系统或泄露密钥的命令
_DANGEROUS_PATTERNS = [
    # 针对根目录/家目录的递归删除（-f 强制标志可选）
    (r"\brm\s+(-\w*)?-r\w*\s+(/|~|\$HOME)", "recursive delete on home/root"),
    # 同时出现递归(-r/-R) 和 强制(-f) 标志（顺序/空格任意）
    (r"\brm\b(?=(?:.*\s)?-\w*[rR])(?=(?:.*\s)?-\w*f)", "force recursive delete"),
    # 同上，但写成 --recursive / --force 长格式
    (r"\brm\b.*--recursive\b.*--force\b|\brm\b.*--force\b.*--recursive\b", "force recursive delete"),
    (r"\bmkfs\b", "format filesystem"),                       # 格式化文件系统
    (r"\bdd\s+.*of=/dev/", "raw disk write"),                 # 原始磁盘写入
    (r">\s*/dev/sd[a-z]", "overwrite block device"),          # 覆写块设备
    (r"\bchmod\s+(-R\s+)?777\s+/", "chmod 777 on root"),      # 对根目录设 777
    (r":\(\)\s*\{.*:\|:.*\}", "fork bomb"),                   # fork 炸弹
    (r"\bcurl\b.*\|\s*(sudo\s+)?(ba)?sh\b", "pipe curl to shell"),   # curl 管道到 shell
    (r"\bwget\b.*\|\s*(sudo\s+)?(ba)?sh\b", "pipe wget to shell"),   # wget 管道到 shell
]


class BashTool(Tool):
    name = "bash"
    description = (
        "Execute a shell command. Returns stdout, stderr, and exit code. "
        "Use this for running tests, installing packages, git operations, etc."
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to run",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (default 120)",
            },
        },
        "required": ["command"],
    }

    def execute(self, command: str, timeout: int = 120) -> str:
        # 安全检查：先看命令是否命中危险模式
        warning = _check_dangerous(command)
        if warning:
            return f"⚠ Blocked: {warning}\nCommand: {command}\nIf intentional, modify the command to be more specific."

        # 使用本线程自己跟踪的工作目录（支持跨命令的 cd 跟踪）
        cwd = getattr(_local, "cwd", None) or os.getcwd()

        try:
            # 通过子进程执行 shell 命令
            proc = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                cwd=cwd,
            )

            # 命令执行成功（exit 0）时，解析 cd 以更新本线程的 cwd
            if proc.returncode == 0:
                _update_cwd(command, cwd)
            out = proc.stdout
            if proc.stderr:
                # 拼接 stderr
                out += f"\n[stderr]\n{proc.stderr}"
            if proc.returncode != 0:
                # 非 0 退出码也带上，便于排查
                out += f"\n[exit code: {proc.returncode}]"
            # 输出过长时保留头尾，丢弃中间，保留最有用的信息
            if len(out) > 15_000:
                out = (
                    out[:6000]
                    + f"\n\n... truncated ({len(out)} chars total) ...\n\n"
                    + out[-3000:]
                )
            return out.strip() or "(no output)"
        except subprocess.TimeoutExpired:
            return f"Error: timed out after {timeout}s"
        except Exception as e:
            return f"Error running command: {e}"


def _check_dangerous(cmd: str) -> str | None:
    # 命令看起来有破坏性则返回警告字符串，否则返回 None
    for pattern, reason in _DANGEROUS_PATTERNS:
        if re.search(pattern, cmd):
            return reason
    return None


def _update_cwd(command: str, current_cwd: str):
    # 按线程跟踪 cd 命令引起的目录变化
    # 遍历 && 链中的每个 cd：
    # 相对路径要相对「上一个 cd 落地的目录」解析（而非初始 cwd），
    # 这样 `cd a && cd b` 最终会停在 a/b
    running = current_cwd
    changed = False
    for part in command.split("&&"):
        part = part.strip()
        if part.startswith("cd "):
            target = part[3:].strip().strip("'\"")
            if target:
                new_dir = os.path.normpath(os.path.join(running, os.path.expanduser(target)))
                if os.path.isdir(new_dir):
                    running = new_dir
                    changed = True
    if changed:
        _local.cwd = running
