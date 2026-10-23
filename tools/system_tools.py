"""System information tools for NEXUS OS.

Read-only tools that report on host system state — CPU usage, memory usage,
disk usage, operating system details, and running process summaries.

All operations are strictly read-only and use the ``system.read`` permission scope.
No shutdown, reboot, privilege escalation, or destructive commands are implemented.
"""

from __future__ import annotations

import os
import platform
import shutil
import time
from pathlib import Path
from typing import Any

from core.types import ToolResult
from security.models import ActionCategory, RiskLevel
from tools.base import BaseTool

# ---------------------------------------------------------------------------
# Core Read-Only System Helper Functions
# ---------------------------------------------------------------------------

def get_cpu_info() -> dict[str, Any]:
    """Retrieve read-only CPU metrics and load average."""
    cpu_count = os.cpu_count() or 1

    load_1 = load_5 = load_15 = 0.0
    try:
        load_1, load_5, load_15 = os.getloadavg()
    except (AttributeError, OSError):
        pass

    # Read CPU model name from /proc/cpuinfo if available
    cpu_model = "Unknown"
    try:
        proc_cpu = Path("/proc/cpuinfo")
        if proc_cpu.exists():
            for line in proc_cpu.read_text(encoding="utf-8", errors="replace").splitlines():
                if "model name" in line:
                    cpu_model = line.split(":", 1)[1].strip()
                    break
    except Exception:
        pass

    # Estimated CPU usage percentage based on 1-min load average and CPU count
    usage_percent = round(min(100.0, (load_1 / cpu_count) * 100.0), 1)

    return {
        "architecture": platform.machine(),
        "cpu_count_logical": cpu_count,
        "cpu_model": cpu_model,
        "load_average_1min": round(load_1, 2),
        "load_average_5min": round(load_5, 2),
        "load_average_15min": round(load_15, 2),
        "estimated_usage_percent": usage_percent,
    }


def get_memory_info() -> dict[str, Any]:
    """Retrieve read-only RAM and swap memory metrics."""
    mem_total = 0
    mem_free = 0
    mem_available = 0
    swap_total = 0
    swap_free = 0

    try:
        proc_mem = Path("/proc/meminfo")
        if proc_mem.exists():
            for line in proc_mem.read_text(encoding="utf-8", errors="replace").splitlines():
                parts = line.split()
                if not parts:
                    continue
                key = parts[0].rstrip(":")
                val = int(parts[1]) * 1024  # kB → bytes

                if key == "MemTotal":
                    mem_total = val
                elif key == "MemFree":
                    mem_free = val
                elif key == "MemAvailable":
                    mem_available = val
                elif key == "SwapTotal":
                    swap_total = val
                elif key == "SwapFree":
                    swap_free = val
    except Exception:
        pass

    if mem_available == 0:
        mem_available = mem_free

    mem_used = max(0, mem_total - mem_available)
    mem_used_pct = round((mem_used / mem_total) * 100.0, 1) if mem_total > 0 else 0.0

    swap_used = max(0, swap_total - swap_free)
    swap_used_pct = round((swap_used / swap_total) * 100.0, 1) if swap_total > 0 else 0.0

    return {
        "memory_total_bytes": mem_total,
        "memory_total_gb": round(mem_total / (1024 ** 3), 2),
        "memory_used_gb": round(mem_used / (1024 ** 3), 2),
        "memory_available_gb": round(mem_available / (1024 ** 3), 2),
        "memory_used_percent": mem_used_pct,
        "swap_total_gb": round(swap_total / (1024 ** 3), 2),
        "swap_used_gb": round(swap_used / (1024 ** 3), 2),
        "swap_used_percent": swap_used_pct,
    }


def get_disk_info(path: str = "/") -> dict[str, Any]:
    """Retrieve read-only disk space metrics for a partition."""
    try:
        usage = shutil.disk_usage(path)
        total = usage.total
        free = usage.free
        used = usage.used
        used_pct = round((used / total) * 100.0, 1) if total > 0 else 0.0

        return {
            "path": path,
            "total_bytes": total,
            "total_gb": round(total / (1024 ** 3), 2),
            "used_gb": round(used / (1024 ** 3), 2),
            "free_gb": round(free / (1024 ** 3), 2),
            "used_percent": used_pct,
        }
    except Exception as exc:
        return {
            "path": path,
            "error": str(exc),
        }


def get_os_info() -> dict[str, Any]:
    """Retrieve operating system and kernel metadata."""
    uptime_seconds = 0.0
    try:
        proc_uptime = Path("/proc/uptime")
        if proc_uptime.exists():
            uptime_seconds = float(proc_uptime.read_text().split()[0])
    except Exception:
        pass

    return {
        "os_system": platform.system(),
        "os_release": platform.release(),
        "os_version": platform.version(),
        "architecture": platform.machine(),
        "hostname": platform.node(),
        "uptime_seconds": round(uptime_seconds, 1),
        "uptime_hours": round(uptime_seconds / 3600, 1),
        "python_version": platform.python_version(),
    }


def get_running_processes_summary() -> dict[str, Any]:
    """Retrieve read-only summary of running user processes."""
    proc_dir = Path("/proc")
    total_procs = 0
    procs_sample: list[dict[str, Any]] = []

    if proc_dir.is_dir():
        for pid_dir in proc_dir.iterdir():
            if not pid_dir.name.isdigit():
                continue

            pid = int(pid_dir.name)
            total_procs += 1

            if len(procs_sample) < 20:
                try:
                    comm_path = pid_dir / "comm"
                    if comm_path.exists():
                        name = comm_path.read_text(encoding="utf-8", errors="replace").strip()
                        if not name.startswith("[") and pid >= 10:
                            procs_sample.append({"pid": pid, "name": name})
                except (PermissionError, FileNotFoundError):
                    pass

    return {
        "total_running_processes": total_procs,
        "sample_count": len(procs_sample),
        "sample_processes": procs_sample,
    }


# ---------------------------------------------------------------------------
# BaseTool Subclasses
# ---------------------------------------------------------------------------

class SystemInfoTool(BaseTool):
    """Return a complete snapshot of system state."""

    name = "system_info"
    description = (
        "Return system status snapshot including OS metadata, CPU load, "
        "memory usage, disk usage, and process summary."
    )
    required_permissions = ["system.read"]
    action_category = ActionCategory.READ_ONLY
    risk_level = RiskLevel.LOW
    parameters_schema = {
        "type": "object",
        "properties": {},
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            snapshot = {
                "os": get_os_info(),
                "cpu": get_cpu_info(),
                "memory": get_memory_info(),
                "disk": get_disk_info("/"),
                "processes": get_running_processes_summary(),
            }
            return ToolResult(
                tool_name=self.name,
                success=True,
                output=snapshot,
            )
        except Exception as exc:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=f"Failed to retrieve system info: {exc}",
            )


class SystemCpuTool(BaseTool):
    """Retrieve detailed read-only CPU metrics."""

    name = "system_cpu"
    description = "Retrieve read-only CPU usage, core counts, architecture, and load averages."
    required_permissions = ["system.read"]
    action_category = ActionCategory.READ_ONLY
    risk_level = RiskLevel.LOW
    parameters_schema = {
        "type": "object",
        "properties": {},
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            info = get_cpu_info()
            return ToolResult(
                tool_name=self.name,
                success=True,
                output=info,
            )
        except Exception as exc:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=str(exc),
            )


class SystemMemoryTool(BaseTool):
    """Retrieve detailed read-only RAM and Swap memory metrics."""

    name = "system_memory"
    description = "Retrieve read-only RAM and swap memory metrics (total, used, free, percentage)."
    required_permissions = ["system.read"]
    parameters_schema = {
        "type": "object",
        "properties": {},
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            info = get_memory_info()
            return ToolResult(
                tool_name=self.name,
                success=True,
                output=info,
            )
        except Exception as exc:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=str(exc),
            )


class SystemDiskTool(BaseTool):
    """Retrieve read-only disk partition usage metrics."""

    name = "system_disk"
    description = "Retrieve read-only disk space usage (total, used, free, percentage)."
    required_permissions = ["system.read"]
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Partition mount path to inspect (default: '/').",
            },
        },
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        path = kwargs.get("path", "/")
        try:
            info = get_disk_info(path)
            return ToolResult(
                tool_name=self.name,
                success=True,
                output=info,
            )
        except Exception as exc:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=str(exc),
            )


class SystemOsTool(BaseTool):
    """Retrieve operating system and kernel metadata."""

    name = "system_os"
    description = "Retrieve OS name, release, kernel version, hostname, and system uptime."
    required_permissions = ["system.read"]
    parameters_schema = {
        "type": "object",
        "properties": {},
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            info = get_os_info()
            return ToolResult(
                tool_name=self.name,
                success=True,
                output=info,
            )
        except Exception as exc:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=str(exc),
            )


class SystemProcessesTool(BaseTool):
    """Retrieve read-only process summary."""

    name = "system_processes"
    description = "Retrieve read-only process count and running process snapshot."
    required_permissions = ["system.read"]
    parameters_schema = {
        "type": "object",
        "properties": {},
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            info = get_running_processes_summary()
            return ToolResult(
                tool_name=self.name,
                success=True,
                output=info,
            )
        except Exception as exc:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=str(exc),
            )
