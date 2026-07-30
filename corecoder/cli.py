# 交互式 REPL：面向用户的终端界面

import sys
import os
import argparse

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from prompt_toolkit import prompt as pt_prompt
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings

from .agent import Agent
from .llm import LLM, LiteLLM
from .config import Config
from .session import save_session, load_session, list_sessions
from . import __version__

# rich Console 实例：负责彩色输出、Markdown 渲染、Panel 边框
console = Console()


def _parse_args():
    # 解析命令行参数（argparse），支持模型/地址/密钥覆盖、一次性 prompt、恢复会话、版本号
    p = argparse.ArgumentParser(
        prog="corecoder",
        description="Minimal AI coding agent. Works with any OpenAI-compatible LLM.",
    )
    p.add_argument("-m", "--model", help="Model name (default: $CORECODER_MODEL or gpt-5.5)")
    p.add_argument("--base-url", help="API base URL (default: $OPENAI_BASE_URL)")
    p.add_argument("--api-key", help="API key (default: $OPENAI_API_KEY)")
    p.add_argument("-p", "--prompt", help="One-shot prompt (non-interactive mode)")
    p.add_argument("-r", "--resume", metavar="ID", help="Resume a saved session")
    p.add_argument("-v", "--version", action="version", version=f"%(prog)s {__version__}")
    return p.parse_args()


def main():
    # 程序主入口：解析参数 → 读配置 → 构建 LLM/Agent → 进入 REPL 或一次性执行
    args = _parse_args()
    config = Config.from_env()

    # 命令行参数优先级高于环境变量
    if args.model:
        config.model = args.model
    if args.base_url:
        config.base_url = args.base_url
    if args.api_key:
        config.api_key = args.api_key

    if not config.api_key:
        # 没有密钥：打印配置指引后退出
        console.print("[red bold]No API key found.[/]")
        console.print(
            "Set one of: OPENAI_API_KEY, DEEPSEEK_API_KEY, or CORECODER_API_KEY\n"
            "\nExamples:\n"
            "  # OpenAI\n"
            "  export OPENAI_API_KEY=sk-...\n"
            "\n"
            "  # DeepSeek\n"
            "  export OPENAI_API_KEY=sk-... OPENAI_BASE_URL=https://api.deepseek.com\n"
            "\n"
            "  # Ollama (local)\n"
            "  export OPENAI_API_KEY=ollama OPENAI_BASE_URL=http://localhost:11434/v1 CORECODER_MODEL=qwen2.5-coder\n"
        )
        sys.exit(1)

    # 根据后端类型选择 LLM 类：litellm 或默认 openai
    llm_cls = LiteLLM if config.provider == "litellm" else LLM
    llm = llm_cls(
        model=config.model,
        api_key=config.api_key,
        base_url=config.base_url,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
    )
    agent = Agent(llm=llm, max_context_tokens=config.max_context_tokens)

    # 恢复已保存的会话（如果指定了 -r）
    if args.resume:
        loaded = load_session(args.resume)
        if loaded:
            agent.messages, loaded_model = loaded
            # 若命令行未指定模型，则用会话里保存的模型
            if not args.model:
                agent.llm.model = loaded_model
                config.model = loaded_model
            console.print(f"[green]Resumed session: {args.resume} (model: {agent.llm.model})[/green]")
        else:
            console.print(f"[red]Session '{args.resume}' not found.[/red]")
            sys.exit(1)

    # 一次性模式（-p）：跑完一条 prompt 就退出，不进 REPL
    if args.prompt:
        _run_once(agent, args.prompt)
        return

    # 否则进入交互式 REPL
    _repl(agent, config)


def _run_once(agent: Agent, prompt: str):
    # 非交互模式：执行一条 prompt 后退出
    def on_token(tok):
        # 实时把 token 打到 stdout（无缓冲，便于管道/重定向）
        print(tok, end="", flush=True)

    def on_tool(name, kwargs):
        # 工具调用时打印一行简短提示
        console.print(f"\n[dim]> {name}({_brief(kwargs)})[/dim]")

    try:
        agent.chat(prompt, on_token=on_token, on_tool=on_tool)
    except KeyboardInterrupt:
        # Ctrl+C：130 是 POSIX 惯用的「被信号中断」退出码
        console.print("\n[yellow]Interrupted.[/yellow]")
        sys.exit(130)
    except Exception as e:
        console.print(f"\n[red]Error: {e}[/red]")
        sys.exit(1)
    print()


def _repl(agent: Agent, config: Config):
    # 交互式主循环：读取输入 → 处理命令/调用 Agent → 输出回复
    console.print(Panel(
        f"[bold]CoreCoder[/bold] v{__version__}\n"
        f"Model: [cyan]{config.model}[/cyan]"
        + (f"  Base: [dim]{config.base_url}[/dim]" if config.base_url else "")
        + "\nType [bold]/help[/bold] for commands, [bold]Ctrl+C[/bold] to cancel, [bold]quit[/bold] to exit.",
        border_style="blue",
    ))

    # 命令历史文件：上下方向键可翻阅历史输入
    hist_path = os.path.expanduser("~/.corecoder_history")
    history = FileHistory(hist_path)

    # 按键绑定：Enter 提交；Esc+Enter 插入换行（方便粘贴代码块）
    kb = KeyBindings()

    @kb.add("enter")
    def _submit(event):
        # Enter：校验并提交当前缓冲区
        event.current_buffer.validate_and_handle()

    @kb.add("escape", "enter")
    def _newline(event):
        # Esc+Enter：插入一个换行符（多行输入）
        event.current_buffer.insert_text("\n")

    while True:
        try:
            # multiline=True：允许多行；prompt_continuation 为续行前缀
            user_input = pt_prompt(
                "You > ",
                history=history,
                multiline=True,
                key_bindings=kb,
                prompt_continuation="...  ",
            ).strip()
        except (EOFError, KeyboardInterrupt):
            # Ctrl+D / Ctrl+C：退出 REPL
            console.print("\nBye!")
            break

        if not user_input:
            # 空输入：跳过本轮
            continue

        # 内置斜杠命令处理
        if user_input.lower() in ("quit", "exit", "/quit", "/exit"):
            # 退出命令
            break
        if user_input == "/help":
            # 显示帮助
            _show_help()
            continue
        if user_input == "/reset":
            # 清空对话历史
            agent.reset()
            console.print("[yellow]Conversation reset.[/yellow]")
            continue
        if user_input == "/tokens":
            # 显示本次会话的 token 用量与估算花费
            p = agent.llm.total_prompt_tokens
            c = agent.llm.total_completion_tokens
            line = f"Tokens: [cyan]{p}[/cyan] prompt + [cyan]{c}[/cyan] completion = [bold]{p+c}[/bold] total"
            cost = agent.llm.estimated_cost
            if cost is not None:
                line += f"  (~${cost:.4f})"
            console.print(line)
            continue
        if user_input == "/model" or user_input.startswith("/model "):
            # 查看/切换当前模型（中途可换）
            new_model = user_input[7:].strip() if user_input.startswith("/model ") else ""
            if new_model:
                agent.llm.model = new_model
                config.model = new_model
                console.print(f"Switched to [cyan]{new_model}[/cyan]")
            else:
                console.print(f"Current model: [cyan]{config.model}[/cyan]")
            continue
        if user_input == "/compact":
            # 手动触发上下文压缩，并显示压缩前后 token 数对比
            from .context import estimate_tokens
            before = estimate_tokens(agent.messages)
            compressed = agent.context.maybe_compress(agent.messages, agent.llm)
            after = estimate_tokens(agent.messages)
            if compressed:
                console.print(f"[green]Compressed: {before} → {after} tokens ({len(agent.messages)} messages)[/green]")
            else:
                console.print(f"[dim]Nothing to compress ({before} tokens, {len(agent.messages)} messages)[/dim]")
            continue
        if user_input == "/save":
            # 保存当前会话到磁盘
            sid = save_session(agent.messages, config.model)
            console.print(f"[green]Session saved: {sid}[/green]")
            console.print(f"Resume with: corecoder -r {sid}")
            continue
        if user_input == "/diff":
            # 列出本次会话改动过的文件
            from .tools.edit import _changed_files
            if not _changed_files:
                console.print("[dim]No files modified this session.[/dim]")
            else:
                console.print(f"[bold]Files modified this session ({len(_changed_files)}):[/bold]")
                for f in sorted(_changed_files):
                    console.print(f"  [cyan]{f}[/cyan]")
            continue
        if user_input == "/sessions":
            # 列出所有已保存的会话
            sessions = list_sessions()
            if not sessions:
                console.print("[dim]No saved sessions.[/dim]")
            else:
                for s in sessions:
                    console.print(f"  [cyan]{s['id']}[/cyan] ({s['model']}, {s['saved_at']}) {s['preview']}")
            continue

        # 未知的斜杠命令：不发给模型，直接提示
        if user_input.startswith("/"):
            console.print(f"[yellow]Unknown command: {user_input.split()[0]} (try /help)[/yellow]")
            continue

        # 普通文本输入：交给 Agent 处理
        streamed: list[str] = []

        def on_token(tok):
            # 收到 token：累积并实时打印
            streamed.append(tok)
            print(tok, end="", flush=True)

        def on_tool(name, kwargs):
            # 工具调用：打印一行简短提示
            console.print(f"\n[dim]> {name}({_brief(kwargs)})[/dim]")

        try:
            response = agent.chat(user_input, on_token=on_token, on_tool=on_tool)
            if streamed:
                # 有流式输出：补一个换行
                print()  # newline after streamed tokens
            else:
                # 没有流式输出（例如工具调用后才生成的回复）：用 Markdown 渲染
                console.print(Markdown(response))
        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted.[/yellow]")
        except Exception as e:
            console.print(f"\n[red]Error: {e}[/red]")


def _show_help():
    # 显示帮助面板：命令清单 + 输入键位说明
    console.print(Panel(
        "[bold]Commands:[/bold]\n"
        "  /help          Show this help\n"
        "  /reset         Clear conversation history\n"
        "  /model         Show current model\n"
        "  /model <name>  Switch model mid-conversation\n"
        "  /tokens        Show token usage\n"
        "  /compact       Compress conversation context\n"
        "  /diff          Show files modified this session\n"
        "  /save          Save session to disk\n"
        "  /sessions      List saved sessions\n"
        "  quit           Exit CoreCoder\n"
        "\n"
        "[bold]Input:[/bold]\n"
        "  Enter          Submit message\n"
        "  Esc+Enter      Insert newline (for pasting code)",
        title="CoreCoder Help",
        border_style="dim",
    ))


def _brief(kwargs: dict, maxlen: int = 80) -> str:
    # 把工具参数字典渲染成简短字符串，用于工具调用提示行
    s = ", ".join(f"{k}={repr(v)[:40]}" for k, v in kwargs.items())
    return s[:maxlen] + ("..." if len(s) > maxlen else "")
