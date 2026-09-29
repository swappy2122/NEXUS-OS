"""Development & Testing Model Backend for NEXUS OS.

This backend provides deterministic, rule-based execution for testing
and development when no LLM provider (Ollama, OpenAI, Claude, etc.)
is configured or desired.

It satisfies :class:`BaseModelBackend` and interprets user intents
directly into tool calls without any external AI model dependencies.
"""

from __future__ import annotations

import json
import logging
import re
import shlex
from typing import Any

from core.types import ModelResponse
from models.base_backend import BaseModelBackend

logger = logging.getLogger("nexus.models.dev_backend")


class DevModelBackend(BaseModelBackend):
    """Rule-based, zero-LLM backend for development and testing.

    Translates user text commands into structured tool calls and formats
    execution summaries deterministically.
    """

    def __init__(self, name: str = "dev_backend", model_id: str = "dev-rule-engine-v1") -> None:
        super().__init__(name=name, model_id=model_id)

    async def is_available(self) -> bool:
        """Always available as it requires no external services."""
        return True

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        """Handle chat requests from agents or supervisor.

        - If `tools` is provided: parses the user intent to pick a tool and extract args.
        - If `tools` is empty/None: summarizes tool results or provides general assistance.
        """
        if not messages:
            return ModelResponse(content="NEXUS OS Dev Engine: Ready.")

        # Find the latest user message
        user_content = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_content = msg.get("content", "").strip()
                break

        # Case 1: Summarization request (agent already called tools and wants a summary)
        if not tools:
            if "Tool results:" in user_content or "Tool execution results:" in user_content:
                return ModelResponse(content=self._summarize_tool_results(user_content))
            return ModelResponse(content=self._general_response(user_content))

        # Case 2: Tool selection request (agent asking what tool to call)
        available_tool_names = [
            t["function"]["name"]
            for t in tools
            if "function" in t and "name" in t["function"]
        ]

        # Multi-intent conjunction handling: e.g. "show cpu and list running apps"
        conjunction_split = re.split(r'\b(?:and|then|after that|after)\b', user_content, flags=re.IGNORECASE)
        if len(conjunction_split) >= 2:
            matched_calls: list[dict[str, Any]] = []
            for part in conjunction_split:
                part_clean = part.strip()
                if part_clean:
                    tc = self._match_tool(part_clean, available_tool_names)
                    if tc:
                        matched_calls.append(tc)
            if len(matched_calls) >= 2:
                logger.debug("DevBackend matched multi-tool calls: %s", [c["name"] for c in matched_calls])
                return ModelResponse(tool_calls=matched_calls)

        tool_call = self._match_tool(user_content, available_tool_names)
        if tool_call:
            logger.debug("DevBackend matched tool: %s with args: %s", tool_call["name"], tool_call["arguments"])
            return ModelResponse(tool_calls=[tool_call])

        # No tool matched within the available tools
        return ModelResponse(
            content=(
                f"No suitable tool found for '{user_content}'. "
                f"Available tools: {', '.join(available_tool_names)}"
            )
        )

    # ── Tool Matching & Parameter Extraction ─────────────────────────────

    def _match_tool(
        self,
        user_text: str,
        available_tools: list[str],
    ) -> dict[str, Any] | None:
        """Match user text to one of the available tools and extract arguments."""
        clean_text = user_text.strip()
        lower_text = clean_text.lower()

        # 1. Direct tool invocation check (e.g. "file_read path=test.txt" or "system_cpu")
        for tool_name in available_tools:
            if lower_text == tool_name.lower():
                return {"name": tool_name, "arguments": {}}
            if lower_text.startswith(tool_name.lower() + " ") or lower_text.startswith(tool_name.lower() + "("):
                args_str = clean_text[len(tool_name):].strip()
                args = self._parse_explicit_args(args_str)
                return {"name": tool_name, "arguments": args}

        # 2. System Agent Tools
        if "system_cpu" in available_tools and self._is_cpu_intent(lower_text):
            per_cpu = "per cpu" in lower_text or "all cores" in lower_text or "each core" in lower_text
            return {"name": "system_cpu", "arguments": {"per_cpu": per_cpu}}

        if "system_memory" in available_tools and self._is_memory_intent(lower_text):
            return {"name": "system_memory", "arguments": {}}

        if "system_disk" in available_tools and self._is_disk_intent(lower_text):
            path = self._extract_path_arg(clean_text, default="/")
            return {"name": "system_disk", "arguments": {"path": path}}

        if "system_os" in available_tools and self._is_os_intent(lower_text):
            return {"name": "system_os", "arguments": {}}

        if "system_processes" in available_tools and self._is_processes_intent(lower_text):
            limit = self._extract_int_arg(lower_text, default=20)
            sort_by = "memory" if "memory" in lower_text or "mem" in lower_text else "cpu"
            return {"name": "system_processes", "arguments": {"limit": limit, "sort_by": sort_by}}

        if "system_info" in available_tools and self._is_sysinfo_intent(lower_text):
            return {"name": "system_info", "arguments": {}}

        if "process_run" in available_tools and self._is_process_run_intent(lower_text):
            cmd = self._extract_process_command(clean_text)
            return {"name": "process_run", "arguments": {"command": cmd}}

        # 3. File Agent Tools
        if "file_read" in available_tools and self._is_read_intent(lower_text):
            path = self._extract_path_after_keywords(clean_text, ["read file", "read", "cat", "view", "open"])
            return {"name": "file_read", "arguments": {"path": path}}

        if "file_write" in available_tools and self._is_write_intent(lower_text):
            path, content = self._extract_write_args(clean_text)
            return {"name": "file_write", "arguments": {"path": path, "content": content}}

        if "file_search" in available_tools and self._is_search_intent(lower_text):
            pattern, root_dir = self._extract_search_args(clean_text)
            search_path = root_dir if root_dir else "."
            return {"name": "file_search", "arguments": {"pattern": pattern, "path": search_path, "root_dir": search_path}}

        if "file_metadata" in available_tools and self._is_metadata_intent(lower_text):
            path = self._extract_path_after_keywords(clean_text, ["metadata", "stat", "file info", "details of"])
            return {"name": "file_metadata", "arguments": {"path": path}}

        if "file_mkdir" in available_tools and self._is_mkdir_intent(lower_text):
            path = self._extract_path_after_keywords(clean_text, ["mkdir", "create dir", "create directory", "make dir"])
            return {"name": "file_mkdir", "arguments": {"path": path}}

        if "file_move" in available_tools and self._is_move_intent(lower_text):
            src, dst = self._extract_two_paths(clean_text, ["move", "mv", "rename"])
            return {"name": "file_move", "arguments": {"source": src, "destination": dst}}

        if "file_delete" in available_tools and self._is_delete_intent(lower_text):
            path = self._extract_path_after_keywords(clean_text, ["delete file", "delete", "remove", "rm"])
            return {"name": "file_delete", "arguments": {"path": path, "confirm": True}}

        if "file_open_os" in available_tools and self._is_open_os_intent(lower_text):
            path = self._extract_path_after_keywords(clean_text, ["open with os", "os open", "launch file"])
            return {"name": "file_open_os", "arguments": {"path": path}}

        # 4. App Agent Tools
        if "app_list_installed" in available_tools and self._is_app_installed_intent(lower_text):
            limit = self._extract_int_arg(lower_text, default=50)
            return {"name": "app_list_installed", "arguments": {"limit": limit}}

        if "app_list_running" in available_tools and self._is_app_running_intent(lower_text):
            filter_kw = self._extract_app_filter(clean_text)
            args: dict[str, Any] = {}
            if filter_kw:
                args["filter_kw"] = filter_kw
            return {"name": "app_list_running", "arguments": args}

        if "app_is_running" in available_tools and self._is_app_check_intent(lower_text):
            app_name = self._extract_app_name(clean_text, ["is running", "is app running", "check running"])
            return {"name": "app_is_running", "arguments": {"app_name": app_name}}

        if "app_open" in available_tools and self._is_app_open_intent(lower_text):
            app_name = self._extract_app_name(clean_text, ["open app", "launch app", "start app", "open", "launch"])
            return {"name": "app_open", "arguments": {"app_name": app_name}}

        if "app_close" in available_tools and self._is_app_close_intent(lower_text):
            app_name = self._extract_app_name(clean_text, ["close app", "quit app", "kill app", "stop app", "close", "quit", "kill"])
            return {"name": "app_close", "arguments": {"app_name": app_name}}

        return None

    # ── Argument Parsers ─────────────────────────────────────────────────

    def _parse_explicit_args(self, text: str) -> dict[str, Any]:
        """Parse key=val, --key val, JSON, or positional arguments from string."""
        text = text.strip()
        if not text:
            return {}

        # Strip parentheses if formatted like func(arg=val)
        if text.startswith("(") and text.endswith(")"):
            text = text[1:-1].strip()

        # Try JSON parsing
        if text.startswith("{") and text.endswith("}"):
            try:
                return json.loads(text)
            except Exception:
                pass

        args: dict[str, Any] = {}

        # Match key="value" or key=value
        kv_pattern = re.compile(r'(?:--)?([a-zA-Z_]\w*)=(?:"([^"]*)"|\'([^\']*)\'|(\S+))')
        matches = kv_pattern.findall(text)
        if matches:
            for key, v1, v2, v3 in matches:
                val = v1 or v2 or v3
                # Attempt type conversion
                if val.lower() == "true":
                    args[key] = True
                elif val.lower() == "false":
                    args[key] = False
                elif val.isdigit():
                    args[key] = int(val)
                else:
                    try:
                        args[key] = float(val)
                    except ValueError:
                        args[key] = val
            return args

        # Match flag style: --key "val" or --key val
        flag_pattern = re.compile(r'--([a-zA-Z_]\w*)\s+(?:"([^"]*)"|\'([^\']*)\'|(\S+))')
        flag_matches = flag_pattern.findall(text)
        if flag_matches:
            for key, v1, v2, v3 in flag_matches:
                val = v1 or v2 or v3
                if val.lower() == "true":
                    args[key] = True
                elif val.lower() == "false":
                    args[key] = False
                elif val.isdigit():
                    args[key] = int(val)
                else:
                    args[key] = val
            return args

        # If simple single positional token without key, treat as path/command/app_name
        words = text.strip().split()
        if len(words) == 1:
            clean_val = words[0].strip("'\"")
            return {"path": clean_val, "command": clean_val, "app_name": clean_val}

        return {}

    def _extract_path_arg(self, text: str, default: str = "/") -> str:
        """Extract a path argument from text or return default."""
        words = text.split()
        for w in words[1:]:
            if "/" in w or "\\" in w or "." in w:
                return w.strip("'\"")
        return default

    def _extract_int_arg(self, text: str, default: int) -> int:
        """Find an integer in the text or return default."""
        match = re.search(r'\b(\d+)\b', text)
        if match:
            return int(match.group(1))
        return default

    def _extract_path_after_keywords(self, text: str, keywords: list[str]) -> str:
        """Extract path after matching leading keyword phrase."""
        lower = text.lower()
        for kw in sorted(keywords, key=len, reverse=True):
            idx = lower.find(kw)
            if idx != -1:
                remainder = text[idx + len(kw):].strip()
                # Clean up punctuation and prepositions (e.g. "of /path", "from /path")
                for prep in ["file", "from", "at", "to", "path", ":", "="]:
                    if remainder.lower().startswith(prep):
                        remainder = remainder[len(prep):].strip()
                parts = shlex.split(remainder) if remainder else []
                if parts:
                    return parts[0]
                return remainder.strip("'\"")
        words = text.split()
        return words[-1] if len(words) > 1 else ""

    def _extract_process_command(self, text: str) -> str:
        """Extract command to run from process_run intent."""
        clean = text.strip()
        lower = clean.lower()
        for kw in ["process_run", "run", "exec", "execute", "shell", "cmd"]:
            if lower.startswith(kw):
                cmd = clean[len(kw):].strip()
                # Strip leading --command= or command=
                cmd = re.sub(r'^(?:--command=|command=)', '', cmd).strip()
                if (cmd.startswith('"') and cmd.endswith('"')) or (cmd.startswith("'") and cmd.endswith("'")):
                    cmd = cmd[1:-1]
                return cmd
        return clean

    def _extract_write_args(self, text: str) -> tuple[str, str]:
        """Extract path and content for file_write."""
        # Check explicit path=... content=...
        explicit = self._parse_explicit_args(text)
        if "path" in explicit and "content" in explicit:
            return str(explicit["path"]), str(explicit["content"])

        # Check 'write <path> <content>'
        words = text.split(maxsplit=2)
        if len(words) >= 3:
            return words[1].strip("'\""), words[2]
        elif len(words) == 2:
            return words[1].strip("'\""), ""
        return "output.txt", ""

    def _extract_search_args(self, text: str) -> tuple[str, str]:
        """Extract pattern and root_dir for file_search."""
        words = text.split()
        pattern = "*"
        root_dir = "."
        for w in words:
            if "*" in w or "?" in w or w.startswith("."):
                pattern = w.strip("'\"")
            elif "/" in w:
                root_dir = w.strip("'\"")
        if pattern == "*" and len(words) > 1:
            last = words[-1].strip("'\"")
            if not last.startswith("-") and last not in ["search", "find", "files"]:
                pattern = last
        return pattern, root_dir

    def _extract_two_paths(self, text: str, keywords: list[str]) -> tuple[str, str]:
        """Extract source and destination paths for file_move."""
        explicit = self._parse_explicit_args(text)
        if "source" in explicit and "destination" in explicit:
            return str(explicit["source"]), str(explicit["destination"])

        # Positional extraction
        clean = text
        for kw in keywords:
            if clean.lower().startswith(kw):
                clean = clean[len(kw):].strip()
                break
        parts = clean.split()
        if len(parts) >= 2:
            return parts[0].strip("'\""), parts[1].strip("'\"")
        return "", ""

    def _extract_app_name(self, text: str, keywords: list[str]) -> str:
        """Extract app name from text."""
        explicit = self._parse_explicit_args(text)
        if "app_name" in explicit:
            return str(explicit["app_name"])

        lower = text.lower()

        # Check 'is <app> running' pattern
        is_running_match = re.search(r'\bis\s+(?:app\s+)?(.+?)\s+running\b', lower)
        if is_running_match:
            return is_running_match.group(1).strip()

        # Check multi-word targets first
        for multi in ["file manager", "file-manager"]:
            if multi in lower:
                return "file manager"

        for kw in sorted(keywords, key=len, reverse=True):
            if kw in lower:
                idx = lower.find(kw)
                remainder = text[idx + len(kw):].strip()
                # Clean prefix words like "is running firefox" -> "firefox"
                for word in ["application", "app", ":", "="]:
                    if remainder.lower().startswith(word):
                        remainder = remainder[len(word):].strip()
                if remainder:
                    if remainder.lower().startswith("file manager"):
                        return "file manager"
                    return remainder.split()[0].strip("'\"?")
        # Fallback to last word
        words = text.split()
        return words[-1].strip("'\"?") if words else ""

    def _extract_app_filter(self, text: str) -> str | None:
        """Extract keyword filter for running apps."""
        explicit = self._parse_explicit_args(text)
        if "filter_kw" in explicit:
            return str(explicit["filter_kw"])
        for kw in ["matching", "named", "filter", "with"]:
            if kw in text.lower():
                idx = text.lower().find(kw)
                remainder = text[idx + len(kw):].strip()
                if remainder:
                    return remainder.split()[0].strip("'\"")
        return None

    # ── Intent Checkers ──────────────────────────────────────────────────

    def _is_cpu_intent(self, text: str) -> bool:
        return any(k in text for k in ["cpu", "processor", "core usage", "system_cpu"])

    def _is_memory_intent(self, text: str) -> bool:
        return any(k in text for k in ["memory", "ram", "swap", "system_memory"])

    def _is_disk_intent(self, text: str) -> bool:
        return any(k in text for k in ["disk", "storage", "drive", "df", "system_disk"])

    def _is_os_intent(self, text: str) -> bool:
        return any(k in text for k in ["system_os", "os info", "uname", "platform", "operating system"])

    def _is_processes_intent(self, text: str) -> bool:
        return any(k in text for k in ["system_processes", "processes", "process list", "top", "tasks"]) and not self._is_process_run_intent(text)

    def _is_sysinfo_intent(self, text: str) -> bool:
        return any(k in text for k in ["system_info", "sysinfo", "specs", "system info", "machine info"])

    def _is_process_run_intent(self, text: str) -> bool:
        return any(text.startswith(k) or f" {k}" in text for k in ["process_run", "run ", "exec ", "execute ", "shell ", "cmd "])

    def _is_read_intent(self, text: str) -> bool:
        return any(k in text for k in ["file_read", "read file", "read ", "cat ", "view file", "view "])

    def _is_write_intent(self, text: str) -> bool:
        return any(k in text for k in ["file_write", "write file", "write ", "create file", "echo "])

    def _is_search_intent(self, text: str) -> bool:
        return any(k in text for k in ["file_search", "search ", "find ", "glob ", "list files", "ls"])

    def _is_metadata_intent(self, text: str) -> bool:
        return any(k in text for k in ["file_metadata", "metadata", "stat ", "file info"])

    def _is_mkdir_intent(self, text: str) -> bool:
        return any(k in text for k in ["file_mkdir", "mkdir", "create dir", "create directory", "make dir"])

    def _is_move_intent(self, text: str) -> bool:
        return any(k in text for k in ["file_move", "move ", "mv ", "rename "])

    def _is_delete_intent(self, text: str) -> bool:
        return any(k in text for k in ["file_delete", "delete file", "delete ", "remove file", "remove ", "rm "])

    def _is_open_os_intent(self, text: str) -> bool:
        return any(k in text for k in ["file_open_os", "open with os", "os open"])

    def _is_app_installed_intent(self, text: str) -> bool:
        return any(k in text for k in ["app_list_installed", "installed apps", "list installed", "installed applications", "list apps"])

    def _is_app_running_intent(self, text: str) -> bool:
        return any(k in text for k in ["app_list_running", "running apps", "list running", "running applications", "active apps"])

    def _is_app_check_intent(self, text: str) -> bool:
        return (
            any(k in text for k in ["app_is_running", "is running", "is app running", "check running"])
            or bool(re.search(r'\bis\s+.+\s+running\b', text))
        )

    def _is_app_open_intent(self, text: str) -> bool:
        lower = text.lower().strip()
        open_prefixes = [
            "app_open", "open app", "launch app", "start app", "launch ",
            "open firefox", "launch firefox",
            "open files", "open file manager",
            "open downloads", "open documents", "open home",
        ]
        if any(k in lower for k in open_prefixes):
            return True
        if lower.startswith("open ") and not lower.startswith("open file "):
            return True
        return False

    def _is_app_close_intent(self, text: str) -> bool:
        return any(k in text for k in ["app_close", "close app", "quit app", "kill app", "terminate app", "stop app"])

    # ── Summary & Formatting ─────────────────────────────────────────────

    def _summarize_tool_results(self, message: str) -> str:
        """Format raw tool results into a structured, readable summary."""
        lines = message.splitlines()
        results = [line for line in lines if line.startswith("[✓]") or line.startswith("[✗]")]

        if not results:
            return message

        output_parts: list[str] = []
        for res in results:
            output_parts.append(res)

        return "\n".join(output_parts)

    def _general_response(self, text: str) -> str:
        """Helpful response when no tool was requested or general query given."""
        return (
            "NEXUS OS (Development Mode)\n"
            "Ready to test agents and tools.\n\n"
            "Supported Agents & Commands:\n"
            "  • System Agent: cpu, memory, disk, os, processes, run <cmd>\n"
            "  • File Agent:   read <path>, write <path> <text>, search <pattern>, stat <path>, mkdir <path>\n"
            "  • App Agent:    list installed, list running, is <app> running, open <app>, close <app>\n"
            "  • Multi-Agent:  combine intents with 'and', e.g., 'show cpu and list running apps'\n\n"
            "Type 'help' in the CLI for more command syntax and examples."
        )
