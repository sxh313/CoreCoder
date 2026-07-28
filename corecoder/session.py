"""Session persistence - save and resume conversations.

Claude Code maintains session state via QueryEngine (1295 lines).
CoreCoder distills this to: JSON dump of messages + model config.
"""
# 会话持久化模块：保存和恢复对话。
# Claude Code 用 QueryEngine 维护会话状态（1295 行），
# CoreCoder 精简为：把 messages + 模型配置 序列化成 JSON。

import json
import re
import time
import uuid
from pathlib import Path

# 会话文件统一存放目录：~/.corecoder/sessions/
SESSIONS_DIR = Path.home() / ".corecoder" / "sessions"
# 会话 ID 中不安全的字符（替换成 -）
_SAFE_SESSION_RE = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_SESSION_ID_LEN = 100  # keep filenames comfortably under the OS limit
# 会话 ID 最大长度，确保文件名远低于操作系统限制


def _normalize_session_id(session_id: str | None) -> str:
    # 把任意输入规整成安全的会话 ID：取最后一段、非法字符替换为 -、限长
    if not session_id:
        return _new_session_id()

    # 兼容传入路径形式，只取最后一段
    name = session_id.strip().replace("\\", "/").split("/")[-1]
    # 非法字符替换为 -
    name = _SAFE_SESSION_RE.sub("-", name).strip(".-_")
    # 超长截断
    if len(name) > _MAX_SESSION_ID_LEN:
        name = name[:_MAX_SESSION_ID_LEN].strip(".-_")
    # 处理后为空则生成新 ID
    return name or _new_session_id()


def _new_session_id() -> str:
    # 生成新会话 ID：时间戳 + uuid 前 8 位，保证唯一性
    return f"session_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"


def _session_path(session_id: str) -> Path:
    # 根据会话 ID 计算文件路径，并做路径穿越校验
    path = (SESSIONS_DIR / f"{_normalize_session_id(session_id)}.json").resolve()
    root = SESSIONS_DIR.resolve()
    # 防止 ../ 之类把文件写到会话目录之外
    if root != path.parent:
        raise ValueError("Invalid session id")
    return path


def save_session(messages: list[dict], model: str, session_id: str | None = None) -> str:
    """Save conversation to disk. Returns the session ID."""
    # 把对话保存到磁盘，返回（归一化后的）会话 ID
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

    session_id = _normalize_session_id(session_id)

    data = {
        "id": session_id,
        "model": model,
        "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "messages": messages,
    }

    path = _session_path(session_id)
    # ensure_ascii=False：保留中文等非 ASCII 字符
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return session_id


def load_session(session_id: str) -> tuple[list[dict], str] | None:
    """Load a saved session. Returns (messages, model) or None."""
    # 加载已保存的会话，返回 (messages, model)；文件不存在或损坏时返回 None
    path = _session_path(session_id)
    if not path.exists():
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data["messages"], data["model"]
    except (json.JSONDecodeError, KeyError, OSError):
        # a corrupt or truncated session file shouldn't crash resume
        # 会话文件损坏/截断不应让恢复功能崩溃
        return None


def list_sessions() -> list[dict]:
    """List available sessions, newest first."""
    # 列出所有会话，按文件名倒序（即最新在前）
    if not SESSIONS_DIR.exists():
        return []

    sessions = []
    for f in sorted(SESSIONS_DIR.glob("*.json"), reverse=True):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            # grab first user message as preview
            # 取第一条 user 消息作为预览文本
            preview = ""
            for m in data.get("messages", []):
                if m.get("role") == "user" and m.get("content"):
                    preview = m["content"][:80]
                    break
            sessions.append({
                "id": data.get("id", f.stem),
                "model": data.get("model", "?"),
                "saved_at": data.get("saved_at", "?"),
                "preview": preview,
            })
        except (json.JSONDecodeError, KeyError):
            # 单个会话文件损坏就跳过，不影响列表
            continue

    return sessions[:20]  # cap at 20
    # 最多返回 20 条
