"""CoreCoder - Minimal AI coding agent inspired by Claude Code's architecture."""
# CoreCoder 包入口：受 Claude Code 架构启发、最小化的 AI 代码智能体

__version__ = "0.4.0"    # 包版本号

# 暴露核心类与工具清单，方便外部 `from corecoder import Agent, LLM, ...`
from corecoder.agent import Agent
from corecoder.llm import LLM
from corecoder.config import Config
from corecoder.tools import ALL_TOOLS

# __all__ 限定 `from corecoder import *` 时导出的符号
__all__ = ["Agent", "LLM", "Config", "ALL_TOOLS", "__version__"]
