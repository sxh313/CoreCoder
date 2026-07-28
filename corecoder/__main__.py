# 模块执行入口：当以 `python -m corecoder` 方式运行时执行 main()
# （pyproject.toml 的 [project.scripts] 入口也是 cli.main，二者等价）
from corecoder.cli import main

main()
