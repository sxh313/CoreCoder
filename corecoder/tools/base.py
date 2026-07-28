# 所有工具的基类定义：统一接口 + OpenAI 函数调用 schema 生成

from abc import ABC, abstractmethod

class Tool(ABC):
    # 工具最小接口：所有具体工具（bash/read/edit 等）都继承此类

    name: str           # 工具名（模型调用时使用，需唯一）
    description: str    # 工具描述（告诉模型这个工具能干什么）
    parameters: dict    # 函数参数的 JSON Schema 定义

    @abstractmethod
    def execute(self, **kwargs) -> str:
        # 执行工具，返回文本结果（统一用字符串，方便塞进对话历史）
        ...

    def schema(self) -> dict:
        # 生成 OpenAI 函数调用格式的 schema，传给模型的 tools 参数
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
