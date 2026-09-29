#!/usr/bin/env python3
"""NEXUS OS — Developer & Testing CLI.

A simple, structured command-line interface for development and testing.

Route:
    CLI → NEXUS Core → Supervisor → Agent → Tool

Usage:
    # Interactive REPL:
    python cli.py

    # Single-command execution:
    python cli.py "show cpu usage"
    python cli.py "file_read path=nexus.toml"
    python cli.py "list running apps"

    # JSON output mode (ideal for scripting/testing):
    python cli.py --json "system_memory"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any

# Enable readline for command history and line editing if available
try:
    import readline  # noqa: F401
except ImportError:
    pass

from core.constants import SYSTEM_NAME, VERSION
from core.nexus import NexusCore, NexusResponse


# ── ANSI Color Codes ────────────────────────────────────────────────────────

class Colors:
    """Terminal ANSI colors with automatic TTY detection."""
    ENABLED = sys.stdout.isatty()

    RESET = "\033[0m" if ENABLED else ""
    BOLD = "\033[1m" if ENABLED else ""
    DIM = "\033[2m" if ENABLED else ""

    RED = "\033[31m" if ENABLED else ""
    GREEN = "\033[32m" if ENABLED else ""
    YELLOW = "\033[33m" if ENABLED else ""
    BLUE = "\033[34m" if ENABLED else ""
    MAGENTA = "\033[35m" if ENABLED else ""
    CYAN = "\033[36m" if ENABLED else ""
    WHITE = "\033[37m" if ENABLED else ""


# ── Formatter ────────────────────────────────────────────────────────────────

def format_structured_response(response: NexusResponse, width: int = 70) -> str:
    """Format a NexusResponse into a structured, readable terminal box."""
    c = Colors
    status_label = f"{c.GREEN}[SUCCESS]{c.RESET}" if response.success else f"{c.RED}[ERROR]{c.RESET}"
    border_color = c.CYAN if response.success else c.RED

    lines = []
    lines.append(f"{border_color}┌─{c.RESET}{status_label}{border_color}{'─' * (width - 11)}┐{c.RESET}")

    # Metadata block
    lines.append(f"{border_color}│{c.RESET}  {c.BOLD}Task ID:{c.RESET}       {response.task_id}")
    lines.append(f"{border_color}│{c.RESET}  {c.BOLD}Route:{c.RESET}         {c.MAGENTA}{response.route_display}{c.RESET}")
    lines.append(
        f"{border_color}│{c.RESET}  {c.BOLD}Execution:{c.RESET}     "
        f"mode={c.YELLOW}{response.execution_mode}{c.RESET}  "
        f"agent={c.YELLOW}{response.agent_used}{c.RESET}  "
        f"duration={c.YELLOW}{response.duration_ms:.1f}ms{c.RESET}"
    )

    # Tool Executions block
    if response.tool_calls:
        lines.append(f"{border_color}├─[Tool Executions]{'─' * (width - 19)}┤{c.RESET}")
        for tc in response.tool_calls:
            mark = f"{c.GREEN}✓{c.RESET}" if tc.success else f"{c.RED}✗{c.RESET}"
            duration = f"({tc.duration_ms:.1f}ms)"
            args_str = json.dumps(tc.arguments) if tc.arguments else ""
            lines.append(f"{border_color}│{c.RESET}   {mark} {c.BOLD}{tc.tool_name}{c.RESET} {c.DIM}{args_str}{c.RESET} {c.YELLOW}{duration}{c.RESET}")
            if not tc.success and tc.error:
                lines.append(f"{border_color}│{c.RESET}      {c.RED}Error: {tc.error}{c.RESET}")

    # Output block
    if response.output:
        lines.append(f"{border_color}├─[Output]{'─' * (width - 10)}┤{c.RESET}")
        for out_line in response.output.strip().splitlines():
            lines.append(f"{border_color}│{c.RESET}  {out_line}")

    # Error block
    if response.error:
        lines.append(f"{border_color}├─[Error Details]{'─' * (width - 17)}┤{c.RESET}")
        for err_line in response.error.strip().splitlines():
            lines.append(f"{border_color}│{c.RESET}  {c.RED}{err_line}{c.RESET}")

    lines.append(f"{border_color}└{'─' * width}┘{c.RESET}")
    return "\n".join(lines)


# ── Banner & Help ────────────────────────────────────────────────────────────

def print_banner() -> None:
    """Print the interactive CLI header banner."""
    c = Colors
    banner = f"""{c.CYAN}
╔══════════════════════════════════════════════════════════════════════════════╗
║                     {c.BOLD}NEXUS OS — Dev & Testing CLI{c.RESET}{c.CYAN} (v{VERSION})                    ║
║         Route: CLI → NEXUS Core → Supervisor → Agent → Tool                  ║
║                  {c.DIM}[Zero-LLM Deterministic Mode Enabled]{c.RESET}{c.CYAN}                       ║
╚══════════════════════════════════════════════════════════════════════════════╝{c.RESET}
Type a command to test, {c.BOLD}'help'{c.RESET} for examples, {c.BOLD}'status'{c.RESET} for info, or {c.BOLD}'exit'{c.RESET} to quit.
"""
    print(banner)


def print_help() -> None:
    """Print command examples categorized by agent and tool."""
    c = Colors
    help_text = f"""
{c.BOLD}AVAILABLE COMMANDS & EXAMPLES:{c.RESET}

  {c.CYAN}System Agent Tools:{c.RESET}
    cpu                              Check CPU usage
    memory                           Check RAM & Swap usage
    disk                             Check root disk space
    os                               Display operating system & kernel info
    processes                        List top processes by CPU
    sysinfo                          Overall hardware & OS specifications
    run echo hello world             Execute a shell command via process_run

  {c.CYAN}File Agent Tools:{c.RESET}
    read nexus.toml                  Read file content
    write test.txt Hello Nexus       Create or overwrite a file
    search *.py                      Search for files matching glob pattern
    stat nexus.toml                  View detailed file metadata
    mkdir test_dir                   Create a new directory
    move test.txt test_renamed.txt   Move or rename a file
    delete test_renamed.txt          Delete a file

  {c.CYAN}App Agent Tools:{c.RESET}
    installed apps                   List installed desktop applications
    running apps                     List currently active applications
    is python running                Check if an app/process is active
    open app firefox                 Launch an application
    close app firefox                Close an application

  {c.CYAN}Multi-Agent Workflows:{c.RESET}
    show cpu and list running apps   Runs SystemAgent & AppAgent concurrently

  {c.CYAN}Direct Tool Syntax:{c.RESET}
    system_cpu per_cpu=true
    file_read path="nexus.toml"
    file_write path="sample.txt" content="hello"
    process_run command="ls -la"

  {c.CYAN}CLI Control Commands:{c.RESET}
    status                           Display system & registry diagnostics
    agents                           List registered agents and capabilities
    tools                            List registered tools
    format [box|json]                Toggle output formatting style
    history                          Show conversation history for current session
    clear                            Clear terminal screen
    exit / quit / q                  Exit the CLI
"""
    print(help_text)


# ── Interactive REPL ─────────────────────────────────────────────────────────

async def run_interactive(core: NexusCore, session_id: str = "cli_session") -> None:
    """Run the interactive REPL loop."""
    print_banner()
    c = Colors
    output_format = "box"

    while True:
        try:
            prompt = f"{c.BOLD}{c.CYAN}nexus{c.RESET} [{c.DIM}{output_format}{c.RESET}]> "
            user_input = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{c.DIM}Exiting NEXUS CLI. Goodbye!{c.RESET}")
            break

        if not user_input:
            continue

        cmd_lower = user_input.lower()

        # Handle CLI built-ins
        if cmd_lower in ["exit", "quit", "q"]:
            print(f"{c.DIM}Exiting NEXUS CLI. Goodbye!{c.RESET}")
            break

        if cmd_lower in ["help", "?"]:
            print_help()
            continue

        if cmd_lower == "clear":
            os.system("clear" if os.name == "posix" else "cls")
            continue

        if cmd_lower == "status":
            diag = core.get_system_status()
            print(f"\n{c.BOLD}NEXUS Core Status:{c.RESET}")
            for k, v in diag.items():
                print(f"  • {c.CYAN}{k}:{c.RESET} {v}")
            print()
            continue

        if cmd_lower == "agents":
            agents = core.get_agents()
            print(f"\n{c.BOLD}Registered Agents ({len(agents)}):{c.RESET}")
            for a in agents:
                print(f"  • {c.GREEN}{a['name']}{c.RESET} — {a['description']}")
                print(f"    Capabilities: {', '.join(a['capabilities'])}")
                print(f"    Tools ({len(a['tools'])}): {', '.join(a['tools'])}")
            print()
            continue

        if cmd_lower == "tools":
            tools = core.get_tools()
            print(f"\n{c.BOLD}Registered Tools ({len(tools)}):{c.RESET}")
            for t in tools:
                perms = f"[{', '.join(t['required_permissions'])}]" if t['required_permissions'] else "[]"
                print(f"  • {c.YELLOW}{t['name']}{c.RESET} {c.DIM}{perms}{c.RESET}: {t['description']}")
            print()
            continue

        if cmd_lower.startswith("format"):
            parts = cmd_lower.split()
            if len(parts) > 1 and parts[1] in ["box", "json"]:
                output_format = parts[1]
                print(f"{c.DIM}Output format set to {output_format}{c.RESET}")
            else:
                output_format = "json" if output_format == "box" else "box"
                print(f"{c.DIM}Output format toggled to {output_format}{c.RESET}")
            continue

        if cmd_lower == "history":
            history = core.get_history(session_id)
            print(f"\n{c.BOLD}Session History ({len(history)} messages):{c.RESET}")
            for msg in history:
                role = msg.get("role", "unknown")
                color = c.GREEN if role == "user" else c.CYAN
                print(f"  {color}[{role.upper()}]{c.RESET} {msg.get('content', '')[:100]}")
            print()
            continue

        # Route through: CLI → NEXUS Core → Supervisor → Agent → Tool
        try:
            response = await core.execute(user_input, session_id=session_id)
            if output_format == "json":
                print(json.dumps(response.to_dict(), indent=2))
            else:
                print(format_structured_response(response))
        except Exception as exc:
            print(f"\n{c.RED}Execution Error:{c.RESET} {exc}\n")


# ── Single Command Execution ─────────────────────────────────────────────────

async def run_single_command(
    core: NexusCore,
    command: str,
    output_json: bool = False,
    session_id: str = "cli_single_run",
) -> int:
    """Execute a single command non-interactively and display result."""
    try:
        response = await core.execute(command, session_id=session_id)
        if output_json:
            print(json.dumps(response.to_dict(), indent=2))
        else:
            print(format_structured_response(response))
        return 0 if response.success else 1
    except Exception as exc:
        if output_json:
            print(json.dumps({"status": "error", "error": str(exc)}, indent=2))
        else:
            c = Colors
            print(f"{c.RED}Fatal Error:{c.RESET} {exc}")
        return 1


# ── Entry Point ──────────────────────────────────────────────────────────────

def main() -> None:
    """Main CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="NEXUS OS — Dev & Testing CLI (Route: CLI → Core → Supervisor → Agent → Tool)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "command",
        nargs="?",
        default=None,
        help="Command text to execute. If omitted, starts interactive REPL.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Output structured JSON instead of formatted text box.",
    )
    parser.add_argument(
        "--session-id",
        default="cli_session",
        help="Session identifier for context tracking (default: cli_session).",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable verbose debug logging.",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to nexus.toml configuration file.",
    )

    args = parser.parse_args()

    log_level = "DEBUG" if args.debug else "WARNING"
    core = NexusCore.bootstrap(
        config_path=args.config,
        use_dev_model=True,
        log_level=log_level,
    )

    if args.command:
        exit_code = asyncio.run(
            run_single_command(
                core,
                args.command,
                output_json=args.output_json,
                session_id=args.session_id,
            )
        )
        sys.exit(exit_code)
    else:
        asyncio.run(run_interactive(core, session_id=args.session_id))


if __name__ == "__main__":
    main()
