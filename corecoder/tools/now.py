import time 
from .base import Tool
from datetime import datetime, timezone, timedelta

class NowTool(Tool):
    name = "now"
    description = "Get the current timestamp in seconds."
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def execute(self) -> str:
        # return str(int(time.time()))
        cst = timezone(timedelta(hours=8))   # 固定 UTC+8 偏移
        return datetime.now(cst).strftime("%Y-%m-%d %H:%M:%S (北京时间)")