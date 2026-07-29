# 工具注册表：集中导入并实例化所有工具，供 Agent 使用

from .bash import BashTool
from .read import ReadFileTool
from .write import WriteFileTool
from .edit import EditFileTool
from .glob_tool import GlobTool
from .grep import GrepTool
from .agent import AgentTool
from .now import NowTool

# 所有工具的默认实例列表：实例化顺序即工具注册顺序
ALL_TOOLS = [
    BashTool(),
    ReadFileTool(),
    WriteFileTool(),
    EditFileTool(),
    GlobTool(),
    GrepTool(),
    AgentTool(),
    NowTool(),
]

def get_tool(name: str):
    # 按工具名查找工具实例，找不到返回 None
    for t in ALL_TOOLS:
        if t.name == name:
            return t
    return None
