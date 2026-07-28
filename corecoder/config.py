"""Configuration - env vars and defaults."""
# 配置模块：从环境变量读取配置，并提供默认值

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv():
    """Load .env from cwd, walking up to home dir. No-op if python-dotenv missing."""
    # 从当前目录加载 .env，逐级向上查找直到家目录；未装 python-dotenv 则静默跳过
    try:
        from dotenv import load_dotenv
        # search cwd first, then parent dirs up to ~
        # 先在当前目录找 .env，找不到再逐级向父目录找，直到家目录
        env_path = Path(".env")
        if not env_path.exists():
            cur = Path.cwd()
            home = Path.home()
            while cur != home and cur != cur.parent:
                candidate = cur / ".env"
                if candidate.exists():
                    env_path = candidate
                    break
                cur = cur.parent
        # override=False：不覆盖已经存在的环境变量（命令行/系统优先）
        load_dotenv(env_path, override=False)
    except ImportError:
        pass  # python-dotenv not installed, silently skip
        # 没装 python-dotenv，静默跳过


@dataclass
class Config:
    # 全局配置数据类：保存模型、密钥、各类生成参数
    model: str = "gpt-5.5"                  # 默认模型
    api_key: str = ""                       # API 密钥
    base_url: str | None = None             # 接口地址（兼容不同服务商）
    max_tokens: int = 4096                  # 单次生成最大 token
    temperature: float = 0.0                # 采样温度（0 = 确定性输出）
    max_context_tokens: int = 128_000       # 上下文窗口上限
    provider: str = "openai"                # 后端类型：openai / litellm

    @classmethod
    def from_env(cls) -> "Config":
        # load .env if present (won't override existing env vars)
        # 加载 .env（不会覆盖已存在的环境变量）
        _load_dotenv()
        # pick up common env vars automatically
        # 按优先级读取常见的 API 密钥环境变量
        api_key = (
            os.getenv("CORECODER_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or os.getenv("DEEPSEEK_API_KEY")
            or ""
        )
        return cls(
            model=os.getenv("CORECODER_MODEL", "gpt-5.5"),
            api_key=api_key,
            base_url=os.getenv("OPENAI_BASE_URL") or os.getenv("CORECODER_BASE_URL"),
            max_tokens=int(os.getenv("CORECODER_MAX_TOKENS", "4096")),
            temperature=float(os.getenv("CORECODER_TEMPERATURE", "0")),
            max_context_tokens=int(os.getenv("CORECODER_MAX_CONTEXT", "128000")),
            provider=os.getenv("CORECODER_PROVIDER", "openai"),
        )
