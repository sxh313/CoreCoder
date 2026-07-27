# CoreCoder 源码学习计划（模块化详细版）

> 目标：**读懂一个 AI coding agent 的核心，再 fork 出你自己的**。
> 面向：会写代码、调过 API、大概懂 function calling，但没拆开过 agent 主循环的读者。
> 组织方式：按**学习模块（Module）**推进，模块间有**依赖顺序**，**不设任何时间约束**。每个模块自定节奏，做完自测和动手题再进下一个。
> 最大优势：代码小（引擎 1081 行 / 整包 1714 行）、**能跑能断点能改**、**自带 8 篇逐行双语导读** `article/`。

---

## 0. 先认清这个项目

1. **它是什么**：一个 ~1000 行的 Python 迷你 coding agent，灵感来自 Claude Code，自称"编程 agent 里的 nanoGPT"。作者是前 Moonshot AI (Kimi) 的何宇峰，基于他自己的 Claude Code 源码分析做的"可运行注释版"。
2. **和你在学的 Claude-Code 是什么关系**：CoreCoder = Claude Code 核心**最小复刻 + 逐行注释**。同一个设计思想（主循环 / 工具 / 上下文压缩 / 子代理 / 会话），压到 1/100 的代码量。**两个对照着学，效率最高。**
3. **能跑**：和 Claude-Code（还原未完成跑不起来）相反，CoreCoder `pip install -e .` 就能跑、能下断点、能改了再跑、有 86 个测试。→ **本计划以"读 + 断点 + 改 + 测"为主**，不只是静态阅读。

### 与 Claude-Code 的对照表（贯穿全程回看）

| 概念 | Claude-Code（巨型） | CoreCoder（迷你） | 对应文章 |
|---|---|---|---|
| 主循环 | `query.ts` queryLoop（1729 行） | [agent.py](corecoder/agent.py) `chat`（150 行） | 01 |
| 上下文压缩 | `services/compact/` 15 文件 / 四级 | [context.py](corecoder/context.py)（210 行）/ 三层 | 04 |
| 工具接口 | `Tool.ts`（792 行） | [tools/base.py](corecoder/tools/base.py)（27 行） | 02 |
| 子代理 | `AgentTool` 多文件 | [tools/agent.py](corecoder/tools/agent.py)（58 行） | 05 |
| LLM/成本 | `services/api/` 多文件 | [llm.py](corecoder/llm.py)（336 行） | 03 |
| CLI/UI | `main.tsx`（4690 行）+ Ink | [cli.py](corecoder/cli.py)（270 行）+ prompt_toolkit | 06 |
| 会话 | — | [session.py](corecoder/session.py)（97 行） | 06 |

---

## 1. 真实文件规模表

| 文件 | 行数 | 角色 | 优先级 |
|---|---|---|---|
| [agent.py](corecoder/agent.py) | 150 | **主循环 + 并行工具执行** | ⭐⭐⭐ |
| [llm.py](corecoder/llm.py) | 336 | 流式客户端 + 重试 + 成本统计（最大） | ⭐⭐⭐ |
| [context.py](corecoder/context.py) | 210 | 三层上下文压缩 | ⭐⭐⭐ |
| [cli.py](corecoder/cli.py) | 270 | REPL + 斜杠命令 + 一次性模式 | ⭐⭐ |
| [tools/bash.py](corecoder/tools/bash.py) | 127 | shell + 危险命令闸 + cd 追踪 | ⭐⭐ |
| [session.py](corecoder/session.py) | 97 | 存盘/续聊 + 路径穿越防护 | ⭐⭐ |
| [tools/edit.py](corecoder/tools/edit.py) | 92 | 唯一匹配搜索替换 + diff | ⭐⭐⭐ |
| [tools/grep.py](corecoder/tools/grep.py) | 79 | 内容搜索 | ⭐ |
| [tools/agent.py](corecoder/tools/agent.py) | 58 | 子 agent 派生 | ⭐⭐ |
| [config.py](corecoder/config.py) | 57 | 环境变量配置 | ⭐ |
| [tools/read.py](corecoder/tools/read.py) | 53 | 文件读取 | ⭐ |
| [tools/glob_tool.py](corecoder/tools/glob_tool.py) | 47 | 文件名匹配 | ⭐ |
| [tools/write.py](corecoder/tools/write.py) | 38 | 文件写入 | ⭐ |
| [prompt.py](corecoder/prompt.py) | 33 | 系统提示词 | ⭐ |
| [tools/base.py](corecoder/tools/base.py) | 27 | **工具基类（全项目接口）** | ⭐⭐⭐ |
| tests/ | 863 | 86 个测试（验证材料） | ⭐⭐ |

> 规模小到**每个文件都能一口气读完**，不需要 Claude-Code 那套"分层读大文件"的策略。

---

## 2. 学习模块地图（依序推进，自定节奏）

| # | 模块 | 核心文件 | 配套文章 | 前置 |
|---|---|---|---|---|
| M0 | 跑起来 + 建立体感 | README + article/00 | 导言 | — |
| M1 | 基础补课（按需） | 知识点清单 | — | — |
| M2 | 主循环 ⭐ | agent.py | 01-the-loop | M0,M1 |
| M3 | 工具系统 ⭐ | tools/* | 02-tools | M2 |
| M4 | LLM 接入与成本 ⭐ | llm.py | 03-llm-and-cost | M2 |
| M5 | 上下文三层压缩 ⭐ | context.py | 04-context | M2 |
| M6 | 并行与子 agent | agent.py + tools/agent.py | 05-parallel | M2,M3 |
| M7 | 会话与 CLI | session.py + cli.py | 06-session-cli | M2 |
| M8 | 测试 | tests/ | — | M2-M5 |
| M9 | Fork 实战 | 自改 | 07-build-your-own | 全部 |

⭐ = 最关键。

---

## 3. 基础补课（M1）—— Python 知识点清单，按需补

不设进度，读源码卡在哪就回来补对应项，用本项目文件验证。

| 知识点 | 最小子集 | 在本项目验证 |
|---|---|---|
| function calling | OpenAI tool/function-calling 协议（`tools` / `tool_calls` / `tool_call_id`） | [tools/base.py](corecoder/tools/base.py) `schema()` @18 + agent.py 工具回灌 |
| 抽象类 | `abc.ABC` / `@abstractmethod` | [tools/base.py](corecoder/tools/base.py) `Tool(ABC)` @6 |
| dataclass | `@dataclass`、字段、property | [llm.py](corecoder/llm.py) `ToolCall`@20 / `LLMResponse`@27 + `message` property@34 |
| 类型注解 | `list[dict]`、`X \| None`、`**kwargs`、`from __future__` | 全项目 |
| 并发 | `concurrent.futures.ThreadPoolExecutor`、`submit`/`result` | agent.py `_exec_tools_parallel` @117 |
| 反射 | `inspect.signature(...).bind(...)` | agent.py `_exec_tool` @109（参数预校验） |
| 正则 | `re.compile` / `finditer` / 替换 | [session.py](corecoder/session.py) @14 / [tools/bash.py](corecoder/tools/bash.py) @22 / context.py @198 |
| 路径 | `pathlib.Path`、`Path.home()` | [session.py](corecoder/session.py) @13 |
| 流式 | openai SDK `stream=True`、chunk 拼接 | [llm.py](corecoder/llm.py) `chat` @110 |
| JSON Schema | `type/properties/required` 形状 | 各工具的 `parameters` |

资源（官方稳定）：OpenAI 文档「Function Calling」· Python 官方 `abc`/`concurrent.futures`/`inspect`/`re`/`pathlib` 文档。

---

## 4. M0 — 跑起来 + 建立体感

**动手（这是 CoreCoder 相对 Claude-Code 的最大优势，别跳过）**：
```bash
cd D:\Desktop\AI\CoreCoder
pip install -e .                     # 可编辑安装，边读边改
# 配一个 provider（任选其一）
export OPENAI_API_KEY=sk-...         # 或 DeepSeek/Ollama，见 README 表格
corecoder                            # 交互式 REPL
corecoder -p "读 corecoder/agent.py，告诉我循环最多转多少轮"   # 一次性模式
```

**阅读**：
- [README_CN.md](README_CN.md)：定位、代码地图、三个关键设计决策
- [article/00-index.md](article/00-index.md)：系列导言

**产出**：能跑通一次完整回合（读文件→改代码→跑验证→给结论），建立体感再读代码。

**自测**：作者点名的三个"读懂别人才做得出的取舍"是什么？（见 README「一个 while 循环就是 agent 的本体」一节）

---

## 5. M2 — 主循环 ⭐（项目心脏）

**精读**：[agent.py](corecoder/agent.py)（150 行，**全读**）· 配 [article/01-the-loop.md](article/01-the-loop.md)

**`Agent` class @22** 逐方法读：
- `__init__` @23：`max_rounds=50` @28、`ContextManager` @34、`_tool_by_name` 字典 @32、**wire up 子代理** `AgentTool._parent_agent = self` @39-41
- `_full_messages()` @43：拼 `[system] + messages`
- `chat()` @49 — **主循环本体**：
  - @51 追加 user 消息；@52 进循环前先压缩
  - @54 `for _ in range(self.max_rounds)` —— **循环有上限，跑不飞**
  - @55 `self.llm.chat(messages, tools, on_token)` 交给模型
  - @62-64 **无 tool_calls → 返回文本，收工**
  - @68 追加 assistant 消息
  - @70-89 执行工具：单个 @71-80 / 多个并行 @81-89
  - @90-94 **`KeyboardInterrupt` → `_answer_pending_tool_calls` 回填**（防孤儿 tool 消息，见 M5）
  - @97 工具输出大就再压缩
  - @99 到上限返回 `"(reached maximum tool-call rounds)"`
- `_exec_tool()` @101：`inspect.signature.bind` @109 预校验参数 + 执行 @113
- `_exec_tools_parallel()` @117：`ThreadPoolExecutor(max_workers=8)` @128
- `_answer_pending_tool_calls()` @132：给没回执的 tool_call 补 `[interrupted]`
- `reset()` @148

**对照 Claude-Code**：这里的 `for` 循环 = Claude-Code `queryLoop` 的 `while(true)`@307；`max_rounds` 上限是 CoreCoder 多出的安全栏；注释 @66-67、@120-122 直接点名 Claude-Code 的 `StreamingToolExecutor`。

**动手验证**：
1. 在 `chat()` @54 下断点，观察每一轮 `resp.tool_calls` 的形状
2. 把 `max_rounds` 改成 2，看 agent 如何提前收尾
3. 在工具执行中按 Ctrl+C，观察 @90 的回填逻辑

**自测**：
1. 一轮循环从 `llm.chat` 到结果回灌，经过哪几步？
2. 为什么 Ctrl+C 后要 `_answer_pending_tool_calls`？不回填会怎样？（提示：OpenAI API 拒绝孤儿 `tool_calls`）
3. `_exec_tool` 为什么先 `bind` 再 `execute`？（看 @106-108 注释）

---

## 6. M3 — 工具系统 ⭐

**精读**：[tools/base.py](corecoder/tools/base.py)（27 行，全读）+ 七个工具 · 配 [article/02-tools.md](article/02-tools.md)

**接口**：`Tool(ABC)` @6 —— 只有三件套：`name` / `description` / `parameters`(JSON Schema) + `execute(**kwargs)->str` @13 + `schema()` @18（吐 OpenAI function-calling 格式）。**27 行就是全部工具契约**，对比 Claude-Code `Tool.ts` 的 792 行。

**七个工具分层读**（由小到大）：

| 工具 | 行数 | 重点 |
|---|---|---|
| [write.py](corecoder/tools/write.py) | 38 | 最简单，建立"一个工具长什么样"心智 |
| [glob_tool.py](corecoder/tools/glob_tool.py) | 47 | 文件名匹配 |
| [read.py](corecoder/tools/read.py) | 53 | 文件读取 |
| [grep.py](corecoder/tools/grep.py) | 79 | 内容搜索 |
| [edit.py](corecoder/tools/edit.py) | 92 | ⭐ **唯一匹配搜索替换**（作者点名的关键创新）：`execute` @44、`_unified_diff` @79 |
| [bash.py](corecoder/tools/bash.py) | 127 | `_DANGEROUS_PATTERNS` @22 黑名单、`execute` @60、`_check_dangerous` @103、`_update_cwd` @111（cd 追踪） |
| [agent.py](corecoder/tools/agent.py) | 58 | 子代理，放 M6 讲 |

**重点关注 edit.py**（作者反复强调的设计）：
- 为什么用"唯一匹配 old_string"而不是行号？（README：模型数偏一行就改错地方）
- 匹配不到 / 匹配多处 各怎么处理？（读 @44-78）
- 成功后为什么返回一段 diff？

**动手验证**：
1. 照 [base.py](corecoder/tools/base.py) 写一个最小新工具（如 `list_files`），加进 `ALL_TOOLS`，跑 `pytest tests/test_tools.py`
2. 给 `bash.py` 的 `_DANGEROUS_PATTERNS` @22 加一条规则，验证拦截生效
3. 故意让 edit 的 `old_string` 匹配多处，看 agent 如何反应

**自测**：
1. 定义一个新 Tool 要实现什么？
2. edit_file 失败（无匹配/多匹配）时如何"复位让模型重试"？
3. bash 的危险命令闸是"安全沙箱"还是"正则黑名单"？为什么不能算安全？（README Fork 一节）

---

## 7. M4 — LLM 接入与成本 ⭐

**精读**：[llm.py](corecoder/llm.py)（336 行，全项目最大）· 配 [article/03-llm-and-cost.md](article/03-llm-and-cost.md)

**结构**：
- `ToolCall` @20 / `LLMResponse` @27（`message` property @34）—— 数据载体
- `_PRICING` @55 —— **定价表**，成本统计的依据
- `LLM` class @84：`__init__` @85、`estimated_cost` @99（算钱）、`chat` @110（**核心：流式 + 工具调用参数拼接**）、`_call_with_retry` @193（**指数退避**）
- `LiteLLM(LLM)` @212：可选后端（路由 100+ provider），`chat` @240、`_call_with_retry` @313

**读 `chat` @110 的重点**（README 说的"脏活"都在这）：
- 流式返回里一个工具调用的参数被切成多段送达，如何按顺序拼回去
- provider 偶尔吐半截 JSON / `usage=null` 怎么兜
- 429 / 超时 / 连接中断 / 5xx 的退避重试（@193），其余 4xx 直接抛

**动手验证**：
1. 在 `chat` @110 的流式循环里下断点，观察一个 tool_call 参数如何分多个 chunk 到达
2. 把 `_PRICING` @55 里某模型价格改夸张，跑 `/tokens` 看成本变化
3. 读 [tests/test_litellm.py](tests/test_litellm.py)（251 行）看 LiteLLM 后端怎么测

**自测**：
1. 为什么 `llm.py` 是全项目最大文件？（README：不是调模型难，是兜真实世界的脏活）
2. 重试策略是什么？哪些错重试、哪些直接抛？
3. 成本是怎么算出来的？（`_PRICING` + usage）

---

## 8. M5 — 上下文三层压缩 ⭐

**精读**：[context.py](corecoder/context.py)（210 行，全读）· 配 [article/04-context.md](article/04-context.md)

**对照 Claude-Code**：文件开头 @1-13 注释直接列了 Claude-Code 的四级（HISTORY_SNIP / Microcompact / CONTEXT_COLLAPSE / Autocompact），CoreCoder 压成三层。

**`ContextManager` @37 的三档阈值** @41-43：
- `_snip_at = 50%` @41 → Layer 1
- `_summarize_at = 70%` @42 → Layer 2
- `_collapse_at = 90%` @43 → Layer 3

**`maybe_compress` @45 按代价从轻到重依次触发**：
- **Layer 1 `_snip_tool_outputs` @70**：纯机械，tool 结果 >1500 字符且 >6 行，保留首 3 + 尾 3 行（@87-91）。**不花一次模型调用。**
- **Layer 2 `_summarize_old` @109**：>70% 且消息 >10，把较早的交给 LLM 总结成摘要，保留最近 `keep_recent=8` 条
- **Layer 3 `_hard_collapse` @133**：>90%，只留最后 4 条 + 摘要（应急）

**最关键的细节 `_safe_split` @97**（作者说"做这个项目时真改过的 bug"）：
- 切分点要**回退**，绝不让一条 `tool` 消息和产生它的 assistant `tool_calls` 分开
- 否则产生**孤儿 tool 消息**，OpenAI 兼容 API 直接报错

**fallback 链**：`_get_summary` @150 先试 LLM，失败退 `_extract_key_info` @189（纯正则提取文件路径/错误行，不花模型调用）。

**动手验证**：
1. 把 `max_context_tokens` 调小（如 2000），跑一个长任务，观察三层压缩依次触发
2. 在 `_safe_split` @97 下断点，观察它如何避开孤儿 tool 消息
3. 故意制造一个会触发 Layer 3 的长会话，看 `_hard_collapse` 后 messages 长什么样

**自测**：
1. 三层压缩各自的触发条件和"代价"？（机械 / 一次模型调用 / 应急）
2. 为什么不"满了才一刀切"？（README：粗暴截断会丢早期关键决定）
3. 孤儿 tool 消息是什么？`_safe_split` 怎么防？

---

## 9. M6 — 并行执行与子 agent

**精读**：agent.py `_exec_tools_parallel` @117 + [tools/agent.py](corecoder/tools/agent.py)（58 行）· 配 [article/05-parallel-and-subagents.md](article/05-parallel-and-subagents.md)

**并行**（agent.py @117）：
- 模型一次返回多个 tool_call → `ThreadPoolExecutor(max_workers=8)` @128 并发
- 注释 @120-122 老实说：相对 Claude-Code 的流式执行器（边生成边执行），这是简化版

**子代理**（tools/agent.py）：
- `execute(task)` @36：创建子 `Agent` @44
- **`tools=[t for t in parent.tools if t.name != "agent"]` @46** —— **去掉 agent 工具本身，禁止递归派生**（作者点名的第三个设计：用"不给工具"代替"立规矩"）
- 复用父 agent 的 `llm` 连接 @45（花销算进总账）
- 结果 >5000 字截断 @54、`max_rounds=20` @48（比父 agent 的 50 更紧）

**动手验证**：
1. 给 agent 一个能触发多 tool_call 的任务，在 @128 下断点看并发
2. 让主 agent 调 `agent` 工具派子代理，确认子代理的 `tools` 里没有 `agent`
3. 思考：为什么子代理轮次上限更短、输出要截断？（上下文隔离的克制）

**自测**：
1. 子代理靠什么防止无限递归？
2. 子代理和主会话共享哪些状态？哪些隔离？（llm 共享、messages 隔离）
3. 并行执行相对"流式执行器"差在哪？（注释 @120-122）

---

## 10. M7 — 会话与 CLI

**精读**：[session.py](corecoder/session.py)（97 行）+ [cli.py](corecoder/cli.py)（270 行）· 配 [article/06-session-and-cli.md](article/06-session-and-cli.md)

**session.py 的安全核心**：
- `SESSIONS_DIR = ~/.corecoder/sessions` @13
- `_SAFE_SESSION_RE = [^A-Za-z0-9._-]+` @14 —— **会话名白名单正则**
- `_MAX_SESSION_ID_LEN = 100` @15
- `_normalize_session_id()` @18 —— **清洗会话名（路径穿越防护的关键）**：恶意会话名（`../../etc/passwd`）清洗后穿越不出去
- `save/load/list_session` @41/@59/@73

**cli.py 结构**：
- `_parse_args()` @23 / `main()` @37（入口）
- `_run_once()` @98（`-p` 一次性模式）：`on_token` @100（流式回调）、`on_tool` @103（工具回调）
- `_repl()` @117（交互式）：`_submit` @134、`_newline` @138
- `_show_help()` @246、`_brief()` @268

**动手验证**：
1. 故意用 `../../etc/passwd` 当会话名存盘，去 `~/.corecoder/sessions/` 看文件名被清洗成什么
2. 在 `_repl` @117 跟一次斜杠命令（`/compact`、`/tokens`、`/diff`）的分流
3. 对比 Claude-Code 4690 行的 `main.tsx`，体会"CLI 外壳"能精简到什么程度

**自测**：
1. 路径穿越攻击在这个项目里怎么被挡住的？
2. 一次性模式（`-p`）和 REPL 在代码上如何分流？

---

## 11. M8 — 测试（当验证材料）

**精读**：[tests/](tests/)（86 个测试）

- [test_core.py](tests/test_core.py)（233）—— 主循环 / agent
- [test_tools.py](tests/test_tools.py)（304）—— 七个工具
- [test_litellm.py](tests/test_litellm.py)（251）—— LiteLLM 后端
- [test_session.py](tests/test_session.py)（75）—— 会话 + 路径穿越

**用法**：测试是最好的"用法文档"。每读完一个模块，去对应 test 文件看它被怎么调用、边界条件是什么。动手：`pytest tests/ -q` 保持 86 绿；你改的任何东西都跑一遍测试。

**自测**：能不能给 M3 写的新工具补一个测试？

---

## 12. M9 — Fork 实战（毕业）

**配** [article/07-build-your-own.md](article/07-build-your-own.md)。挑一两条动手：

**入门级（改一处就有反馈）**：
- 改 [prompt.py](corecoder/prompt.py)（33 行）`system_prompt()` @7 —— 改一句，agent 脾气就变
- 换模型：改两个环境变量（README 表格）

**进阶级**：
- 加自定义工具：照 [base.py](corecoder/tools/base.py) 写新文件，加进 `ALL_TOOLS`（跑网页 / 调 LSP / 跑测试）
- 当库 import：`from corecoder import Agent, LLM`（README 示例）

**硬核级**（README 点名的"没做"= 留给你的入口）：
- 给 [llm.py](corecoder/llm.py) 加 fallback 模型链 + 美元硬预算闸
- 把 [bash.py](corecoder/tools/bash.py) 的正则黑名单升级成 seccomp / 容器隔离
- 把同步子代理（M6）改成异步 / 流式执行器
- 接 MCP 或 RAG

**产出**：一个 fork 出来的、你能说清每行为什么的 agent。

---

## 13. 阅读方法论（针对小项目，和 Claude-Code 不同）

1. **能跑就别只读**：每个模块都下断点、改参数、跑测试，体感 > 通读。
2. **文章和代码并排开**：`article/0X` 是逐行注释版，读代码卡住就回对应文章。
3. **测试当文档**：看不懂某函数怎么用，去 `tests/` 找它的调用。
4. **对照 Claude-Code**：每读一个 CoreCoder 模块，回看第 0 节对照表，理解"生产级把这个简化到 1/100 长什么样"。
5. **改了就跑**：`pip install -e .` 已是可编辑安装，改完直接 `corecoder` 或 `pytest`。

---

## 14. 笔记模板（建议建 `notes/`，每模块一篇）

```markdown
# Module N — [名称]

## 配套文章
article/0X-xxx.md

## 精读文件
- agent.py chat() @49：主循环

## 关键函数 + 行号
- chat() @49 / _exec_tools_parallel() @117

## 与 Claude-Code 对照
- for 循环 @54 = Claude-Code queryLoop while(true)@307

## 动手验证记录
- 改 max_rounds=2，观察到 ...

## 疑问
- ❓ ...
```

---

## 15. 卡点速查

| 卡点 | 办法 |
|---|---|
| 跑不起来 | 检查 `OPENAI_API_KEY` / `OPENAI_BASE_URL`；先 `pip install -e .` |
| function calling 不熟 | 回 M1 补；先读 base.py `schema()` @18 |
| 流式拼接看不懂 | 回 M4，断点看 chunk 序列 |
| 压缩逻辑绕 | 回 M5，从三档阈值 @41-43 入手 |
| 不知某函数怎么用 | 去 tests/ 找它的调用 |
| 想对照生产级 | 回第 0 节对照表 + 你学的 Claude-Code 计划 |

---

## 16. 模块进度勾选

- [ ] M0 跑起来 + 体感
- [ ] M1 基础补课（按需）
- [ ] M2 主循环（⭐）
- [ ] M3 工具系统（⭐）
- [ ] M4 LLM 与成本（⭐）
- [ ] M5 上下文压缩（⭐）
- [ ] M6 并行与子 agent
- [ ] M7 会话与 CLI
- [ ] M8 测试
- [ ] M9 Fork 实战
