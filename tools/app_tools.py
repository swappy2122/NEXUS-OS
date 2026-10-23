"""Linux application management tools for NEXUS OS.

Provides safe, structured OS-level functions and tools for:
- Listing installed desktop applications (.desktop parsing)
- Listing running applications/processes (/proc & ps)
- Checking if a specific application or PID is running
- Launching applications asynchronously without shell=True
- Terminating running processes safely by PID or name
"""

from __future__ import annotations
import asyncio
import os
import shutil
import signal
from pathlib import Path
from typing import Any

from core.types import ToolResult
from security.models import ActionCategory, RiskLevel
from tools.base import BaseTool

# ---------------------------------------------------------------------------
# Validation Helpers
# ---------------------------------------------------------------------------

FORBIDDEN_CHARS = {";", "|", "&", "$", "`", "\x00", "\n", "\r", "<", ">"}


def validate_app_name(name: str) -> str:
    """Validate and sanitize an application name or path.

    Raises ValueError if invalid or dangerous characters are present.
    """
    if not isinstance(name, str):
        raise ValueError("Application name must be a string.")
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("Application name cannot be empty.")

    for char in FORBIDDEN_CHARS:
        if char in cleaned:
            raise ValueError(f"Invalid character {char!r} in application name.")

    return cleaned


def validate_arguments(args: list[str] | None) -> list[str]:
    """Validate command line arguments list."""
    if args is None:
        return []
    if not isinstance(args, (list, tuple)):
        raise ValueError("Arguments must be a list of strings.")
    validated: list[str] = []
    for i, arg in enumerate(args):
        if not isinstance(arg, str):
            raise ValueError(f"Argument at index {i} must be a string.")
        if "\x00" in arg:
            raise ValueError(f"Null byte found in argument at index {i}.")
        validated.append(arg)
    return validated


# ---------------------------------------------------------------------------
# Core OS Application Management Functions (Non-AI)
# ---------------------------------------------------------------------------

DESKTOP_ENTRY_DIRS = [
    Path("/usr/share/applications"),
    Path("/usr/local/share/applications"),
    Path("~/.local/share/applications").expanduser(),
    Path("/var/lib/flatpak/exports/share/applications"),
    Path("/var/lib/snapd/desktop/applications"),
]


def parse_desktop_file(path: Path) -> dict[str, Any] | None:
    """Parse a Linux .desktop entry file into structured metadata."""
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None

    in_desktop_entry = False
    name = None
    exec_cmd = None
    comment = ""
    icon = ""
    no_display = False
    entry_type = "Application"

    for line in content.splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            in_desktop_entry = (line == "[Desktop Entry]")
            continue

        if not in_desktop_entry or not line or line.startswith("#"):
            continue

        if "=" in line:
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip()

            if key == "Name" and name is None:
                name = val
            elif key == "Exec" and exec_cmd is None:
                exec_cmd = val
            elif key == "Comment" and not comment:
                comment = val
            elif key == "Icon" and not icon:
                icon = val
            elif key == "NoDisplay":
                no_display = (val.lower() == "true")
            elif key == "Type":
                entry_type = val

    if not name or entry_type != "Application":
        return None

    return {
        "name": name,
        "exec": exec_cmd or "",
        "comment": comment,
        "icon": icon,
        "no_display": no_display,
        "desktop_file": str(path),
    }


async def list_installed_applications(filter_kw: str | None = None) -> list[dict[str, Any]]:
    """List installed desktop applications from standard Linux entry locations."""
    kw = (filter_kw or "").strip().lower()
    applications: list[dict[str, Any]] = []
    seen_names: set[str] = set()

    for app_dir in DESKTOP_ENTRY_DIRS:
        if not app_dir.is_dir():
            continue

        for desktop_file in app_dir.glob("*.desktop"):
            app_info = parse_desktop_file(desktop_file)
            if not app_info:
                continue

            if app_info.get("no_display") and not kw:
                continue

            name = app_info["name"]
            if name.lower() in seen_names:
                continue

            if kw:
                searchable = f"{name} {app_info.get('comment', '')} {app_info.get('exec', '')}".lower()
                if kw not in searchable:
                    continue

            seen_names.add(name.lower())
            applications.append(app_info)

    return sorted(applications, key=lambda a: a["name"].lower())


async def list_running_applications(filter_kw: str | None = None) -> list[dict[str, Any]]:
    """List currently running processes/applications via /proc or ps fallback."""
    kw = (filter_kw or "").strip().lower()
    proc_dir = Path("/proc")
    processes: list[dict[str, Any]] = []

    if proc_dir.is_dir():
        for pid_dir in proc_dir.iterdir():
            if not pid_dir.name.isdigit():
                continue

            pid = int(pid_dir.name)
            try:
                comm_path = pid_dir / "comm"
                cmdline_path = pid_dir / "cmdline"

                if not comm_path.exists():
                    continue

                name = comm_path.read_text(encoding="utf-8", errors="replace").strip()
                cmdline = ""
                if cmdline_path.exists():
                    cmd_bytes = cmdline_path.read_bytes()
                    cmdline = " ".join(
                        part.decode(errors="replace")
                        for part in cmd_bytes.split(b"\x00")
                        if part
                    ).strip()

                # Filter out kernel threads (empty cmdline or bracketed names)
                if not cmdline and (name.startswith("[") or pid < 10):
                    continue

                if kw and kw not in name.lower() and kw not in cmdline.lower():
                    continue

                processes.append({
                    "pid": pid,
                    "name": name,
                    "cmdline": cmdline or name,
                })
            except (PermissionError, FileNotFoundError):
                continue

        return sorted(processes, key=lambda p: p["name"].lower())

    # Fallback using ps command without shell=True
    try:
        proc = await asyncio.create_subprocess_exec(
            "ps", "-e", "-o", "pid,comm,args",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        lines = stdout.decode(errors="replace").splitlines()

        for line in lines[1:]:
            parts = line.strip().split(maxsplit=2)
            if len(parts) >= 2:
                p_pid = int(parts[0])
                p_name = parts[1]
                p_cmd = parts[2] if len(parts) > 2 else p_name

                if kw and kw not in p_name.lower() and kw not in p_cmd.lower():
                    continue

                processes.append({
                    "pid": p_pid,
                    "name": p_name,
                    "cmdline": p_cmd,
                })
    except Exception:
        pass

    return sorted(processes, key=lambda p: p["name"].lower())


async def is_application_running(app_name: str | None = None, pid: int | None = None) -> dict[str, Any]:
    """Check whether an application or PID is currently running."""
    if not app_name and pid is None:
        raise ValueError("Must specify either app_name or pid to check status.")

    if pid is not None:
        try:
            os.kill(pid, 0)
            return {
                "running": True,
                "pid": pid,
                "app_name": app_name,
                "matching_pids": [pid],
            }
        except (ProcessLookupError, PermissionError) as exc:
            running = isinstance(exc, PermissionError)
            return {
                "running": running,
                "pid": pid,
                "app_name": app_name,
                "matching_pids": [pid] if running else [],
            }

    clean_name = validate_app_name(app_name or "")
    running_apps = await list_running_applications()

    # Check matching processes (including nautilus for file manager)
    search_names = [clean_name.lower()]
    if clean_name.lower() in ("files", "file manager", "file_manager", "file-manager"):
        search_names.append("nautilus")

    matching_pids = [
        p["pid"] for p in running_apps
        if any(s == p["name"].lower() or s in p["name"].lower() for s in search_names)
    ]

    return {
        "running": len(matching_pids) > 0,
        "app_name": clean_name,
        "matching_pids": matching_pids,
        "count": len(matching_pids),
    }


FILE_MANAGER_ALIASES = {"files", "file manager", "file_manager", "file-manager", "home"}


def resolve_app_or_folder_command(
    app_name: str,
    arguments: list[str] | None = None,
) -> tuple[str, list[str], str]:
    """Resolve an application name or system location to a safe executable command and arguments.

    Maps:
        - "files", "file manager", "home" → gio open "$HOME"
        - "downloads"                     → gio open "$HOME/Downloads"
        - "documents"                     → gio open "$HOME/Documents"
        - Other applications (e.g. firefox) → executable from PATH

    Returns:
        tuple of (executable_path, args_list, display_name)

    Raises:
        FileNotFoundError: If a requested folder or executable does not exist.
        ValueError: If app_name is invalid.
    """
    clean_name = validate_app_name(app_name)
    clean_args = validate_arguments(arguments)
    name_lower = clean_name.lower().strip()

    home = Path.home()
    gio_exec = shutil.which("gio")
    xdg_exec = shutil.which("xdg-open")
    opener = gio_exec or xdg_exec

    # Helper to construct opener arguments safely
    def _make_open_args(target_path: Path) -> tuple[str, list[str]]:
        if not target_path.exists():
            raise FileNotFoundError(f"Requested folder does not exist: {target_path}")
        if gio_exec:
            return gio_exec, ["open", str(target_path)]
        if xdg_exec:
            return xdg_exec, [str(target_path)]
        raise FileNotFoundError("No desktop file opener ('gio' or 'xdg-open') found in system PATH.")

    # 1. Map File Manager / Home folder
    if name_lower in FILE_MANAGER_ALIASES:
        exec_path, args = _make_open_args(home)
        return exec_path, args, "Files"

    # 2. Map Downloads folder
    if name_lower in ("downloads", "download"):
        exec_path, args = _make_open_args(home / "Downloads")
        return exec_path, args, "Downloads"

    # 3. Map Documents folder
    if name_lower in ("documents", "document", "docs"):
        exec_path, args = _make_open_args(home / "Documents")
        return exec_path, args, "Documents"

    # 4. Check if app_name is an explicit directory path (e.g. "~", "~/Desktop", "/tmp")
    if name_lower.startswith("~") or name_lower.startswith("/"):
        expanded = Path(clean_name).expanduser().resolve()
        if expanded.is_dir():
            exec_path, args = _make_open_args(expanded)
            return exec_path, args, str(expanded)

    # 5. Standard Application executable in PATH (e.g. firefox, vlc, gedit)
    executable = shutil.which(clean_name) or shutil.which(name_lower)
    if not executable and Path(clean_name).exists():
        executable = str(Path(clean_name).resolve())
    if not executable:
        executable = clean_name
    if not shutil.which(executable) and not Path(executable).exists():
        raise FileNotFoundError(f"Executable '{clean_name}' not found in system PATH.")

    return executable, clean_args, clean_name


async def launch_application(app_name: str, arguments: list[str] | None = None) -> dict[str, Any]:
    """Safely launch an application or system folder without using shell=True."""
    executable, clean_args, display_name = resolve_app_or_folder_command(app_name, arguments)

    # Spawn process using create_subprocess_exec (no shell=True)
    proc = await asyncio.create_subprocess_exec(
        executable,
        *clean_args,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        start_new_session=True,
    )

    await asyncio.sleep(0.05)
    if proc.returncode is not None and proc.returncode != 0:
        raise RuntimeError(f"Application '{display_name}' exited immediately with status code {proc.returncode}.")

    return {
        "pid": proc.pid,
        "app_name": display_name,
        "arguments": clean_args,
        "status": "running",
        "message": f"Successfully launched {display_name} (PID: {proc.pid}).",
    }


async def terminate_application(
    app_name: str | None = None,
    pid: int | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Safely terminate an application by name or PID."""
    if not app_name and pid is None:
        raise ValueError("Must specify either app_name or pid to terminate an application.")

    sig = signal.SIGKILL if force else signal.SIGTERM
    terminated_pids: list[int] = []
    errors: list[str] = []

    if pid is not None:
        try:
            os.kill(pid, sig)
            terminated_pids.append(pid)
        except ProcessLookupError:
            errors.append(f"Process with PID {pid} not found.")
        except PermissionError:
            errors.append(f"Permission denied to terminate PID {pid}.")
        except Exception as exc:
            errors.append(f"Error terminating PID {pid}: {exc}")

    if app_name:
        clean_name = validate_app_name(app_name)
        status_info = await is_application_running(app_name=clean_name)
        matching_pids = status_info.get("matching_pids", [])

        for p_pid in matching_pids:
            if p_pid in terminated_pids:
                continue
            try:
                os.kill(p_pid, sig)
                terminated_pids.append(p_pid)
            except ProcessLookupError:
                pass
            except PermissionError:
                errors.append(f"Permission denied to terminate PID {p_pid}.")
            except Exception as exc:
                errors.append(f"Error terminating PID {p_pid}: {exc}")

    if terminated_pids:
        return {
            "success": True,
            "app_name": app_name,
            "pid": pid,
            "terminated_pids": terminated_pids,
            "message": f"Successfully closed {len(terminated_pids)} process(es) (PIDs: {terminated_pids}).",
            "warnings": errors if errors else None,
        }

    return {
        "success": False,
        "app_name": app_name,
        "pid": pid,
        "terminated_pids": [],
        "error": "; ".join(errors) if errors else f"No process found matching '{app_name or pid}'.",
    }


# ---------------------------------------------------------------------------
# BaseTool Implementations for Agent Integration
# ---------------------------------------------------------------------------

class AppListInstalledTool(BaseTool):
    """List installed desktop applications on the host system."""

    name = "app_list_installed"
    description = (
        "List installed desktop applications found in system and user "
        "application entry directories."
    )
    required_permissions = ["app.list"]
    action_category = ActionCategory.READ_ONLY
    risk_level = RiskLevel.LOW
    parameters_schema = {
        "type": "object",
        "properties": {
            "filter": {
                "type": "string",
                "description": "Optional keyword filter for application name or category.",
            },
        },
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        filter_kw = kwargs.get("filter")
        try:
            apps = await list_installed_applications(filter_kw=filter_kw)
            return ToolResult(
                tool_name=self.name,
                success=True,
                output={
                    "count": len(apps),
                    "applications": apps,
                },
            )
        except Exception as exc:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=f"Failed to list installed applications: {exc}",
            )


class AppListRunningTool(BaseTool):
    """List currently running processes and applications."""

    name = "app_list_running"
    description = (
        "List currently running applications and processes on the host system."
    )
    required_permissions = ["app.list"]
    action_category = ActionCategory.READ_ONLY
    risk_level = RiskLevel.LOW
    parameters_schema = {
        "type": "object",
        "properties": {
            "filter": {
                "type": "string",
                "description": "Optional keyword filter for process name or command.",
            },
        },
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        filter_kw = kwargs.get("filter")
        try:
            processes = await list_running_applications(filter_kw=filter_kw)
            return ToolResult(
                tool_name=self.name,
                success=True,
                output={
                    "count": len(processes),
                    "processes": processes,
                },
            )
        except Exception as exc:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=f"Failed to list running processes: {exc}",
            )


class AppIsRunningTool(BaseTool):
    """Check whether a specific application or process is currently running."""

    name = "app_is_running"
    description = (
        "Check whether a specific application or PID is currently running."
    )
    required_permissions = ["app.list"]
    action_category = ActionCategory.READ_ONLY
    risk_level = RiskLevel.LOW
    parameters_schema = {
        "type": "object",
        "properties": {
            "app_name": {
                "type": "string",
                "description": "Name of the process or application to check.",
            },
            "pid": {
                "type": "integer",
                "description": "Specific process ID (PID) to check.",
            },
        },
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        app_name = kwargs.get("app_name")
        pid = kwargs.get("pid")
        try:
            status = await is_application_running(app_name=app_name, pid=pid)
            return ToolResult(
                tool_name=self.name,
                success=True,
                output=status,
            )
        except Exception as exc:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=str(exc),
            )


class AppOpenTool(BaseTool):
    """Launch an application on the system."""

    name = "app_open"
    description = (
        "Launch an application on the host system by executable name or path."
    )
    required_permissions = ["app.open"]
    action_category = ActionCategory.NORMAL
    risk_level = RiskLevel.LOW
    parameters_schema = {
        "type": "object",
        "properties": {
            "app_name": {
                "type": "string",
                "description": "Executable name or command (e.g. 'firefox', 'vlc', 'gedit').",
            },
            "arguments": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional command-line arguments to pass to the application.",
            },
        },
        "required": ["app_name"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        app_name = kwargs.get("app_name") or ""
        arguments = kwargs.get("arguments")
        try:
            result = await launch_application(app_name, arguments)
            return ToolResult(
                tool_name=self.name,
                success=True,
                output=result,
            )
        except (ValueError, FileNotFoundError, RuntimeError) as exc:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=str(exc),
            )
        except Exception as exc:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=f"Failed to launch application '{app_name}': {exc}",
            )


class AppCloseTool(BaseTool):
    """Close/terminate a running application by name or PID."""

    name = "app_close"
    description = (
        "Close or terminate a running application by process name or PID. "
        "Requires user confirmation."
    )
    required_permissions = ["app.close"]
    action_category = ActionCategory.SENSITIVE
    risk_level = RiskLevel.MEDIUM
    parameters_schema = {
        "type": "object",
        "properties": {
            "app_name": {
                "type": "string",
                "description": "Name of the process or application to close (e.g. 'firefox').",
            },
            "pid": {
                "type": "integer",
                "description": "Specific process ID (PID) to close.",
            },
            "force": {
                "type": "boolean",
                "description": "If true, send SIGKILL (force terminate) instead of SIGTERM.",
            },
        },
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        app_name = kwargs.get("app_name")
        pid = kwargs.get("pid")
        force = bool(kwargs.get("force", False))
        try:
            res = await terminate_application(app_name=app_name, pid=pid, force=force)
            return ToolResult(
                tool_name=self.name,
                success=res.get("success", False),
                output=res if res.get("success") else None,
                error=res.get("error") if not res.get("success") else None,
            )
        except Exception as exc:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=str(exc),
            )
