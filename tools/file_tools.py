"""File-system tools for NEXUS OS.

Provides safe, permission-gated tools and helper functions for:
- Reading and writing files
- Searching for files by glob pattern
- Retrieving detailed file/directory metadata
- Opening files with the OS default application
- Creating directories
- Moving and renaming files/directories
- Deleting files (requires confirmation)
"""

from __future__ import annotations

import asyncio
import os
import shutil
import time
from pathlib import Path
from typing import Any

from core.types import ToolResult
from tools.base import BaseTool

# ---------------------------------------------------------------------------
# Restricted / Forbidden System Paths
# ---------------------------------------------------------------------------

DENIED_PATHS = [
    Path("/etc"),
    Path("/boot"),
    Path("/sys"),
    Path("/proc"),
    Path("/dev"),
]


def validate_safe_path(path_str: str, allow_nonexistent: bool = False) -> Path:
    """Resolve path and verify it does not touch restricted system directories.

    Raises ValueError if empty, PermissionError if restricted, FileNotFoundError if missing.
    """
    if not path_str or not str(path_str).strip():
        raise ValueError("Path string cannot be empty.")

    p = Path(path_str).expanduser().resolve()

    for denied in DENIED_PATHS:
        if p == denied or denied in p.parents:
            raise PermissionError(f"Access to restricted system path '{p}' is forbidden.")

    if not allow_nonexistent and not p.exists():
        raise FileNotFoundError(f"Path does not exist: {p}")

    return p


# ---------------------------------------------------------------------------
# Core Helper Functions (Non-AI)
# ---------------------------------------------------------------------------

def get_file_metadata(path_str: str) -> dict[str, Any]:
    """Retrieve structured metadata for a file or directory."""
    p = validate_safe_path(path_str)
    stat = p.stat()

    size_bytes = stat.st_size
    size_human = f"{size_bytes} B"
    if size_bytes >= 1024 * 1024 * 1024:
        size_human = f"{round(size_bytes / (1024 ** 3), 2)} GB"
    elif size_bytes >= 1024 * 1024:
        size_human = f"{round(size_bytes / (1024 ** 2), 2)} MB"
    elif size_bytes >= 1024:
        size_human = f"{round(size_bytes / 1024, 2)} KB"

    return {
        "path": str(p),
        "name": p.name,
        "is_file": p.is_file(),
        "is_directory": p.is_dir(),
        "is_symlink": p.is_symlink(),
        "extension": p.suffix,
        "size_bytes": size_bytes,
        "size_human": size_human,
        "created_at": time.ctime(stat.st_ctime),
        "modified_at": time.ctime(stat.st_mtime),
        "mode_octal": oct(stat.st_mode),
    }


async def open_file_os(path_str: str) -> dict[str, Any]:
    """Open a file or folder using the OS default desktop handler (gio open or xdg-open)."""
    clean_lower = (path_str or "").strip().lower()
    home = Path.home()

    if clean_lower in ("files", "file manager", "file-manager", "file_manager", "home", "~"):
        target_path = home
    elif clean_lower in ("downloads", "download"):
        target_path = home / "Downloads"
    elif clean_lower in ("documents", "document", "docs"):
        target_path = home / "Documents"
    else:
        target_path = validate_safe_path(path_str)

    if not target_path.exists():
        raise FileNotFoundError(f"Requested folder or file does not exist: {target_path}")

    # Use gio open if available, else fallback to xdg-open (no shell=True)
    gio_exec = shutil.which("gio")
    if gio_exec:
        proc = await asyncio.create_subprocess_exec(
            gio_exec,
            "open",
            str(target_path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
    else:
        xdg_exec = shutil.which("xdg-open") or "xdg-open"
        proc = await asyncio.create_subprocess_exec(
            xdg_exec,
            str(target_path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )

    await asyncio.sleep(0.05)
    if proc.returncode is not None and proc.returncode != 0:
        raise RuntimeError(f"Failed to open '{target_path}' with OS application (exit code {proc.returncode}).")

    display_name = target_path.name or str(target_path)
    return {
        "opened": True,
        "path": str(target_path),
        "pid": proc.pid,
        "message": f"Opened '{display_name}' using OS default application.",
    }


def create_directory(path_str: str, parents: bool = True) -> dict[str, Any]:
    """Safely create a new directory."""
    p = validate_safe_path(path_str, allow_nonexistent=True)
    if p.exists() and not p.is_dir():
        raise FileExistsError(f"Path exists and is not a directory: {p}")

    p.mkdir(parents=parents, exist_ok=True)
    return {
        "created": True,
        "path": str(p),
        "message": f"Directory '{p}' created successfully.",
    }


def move_file(src_path_str: str, dst_path_str: str, overwrite: bool = False) -> dict[str, Any]:
    """Move or rename a file or directory."""
    src = validate_safe_path(src_path_str)
    dst = validate_safe_path(dst_path_str, allow_nonexistent=True)

    if dst.exists() and not overwrite:
        raise FileExistsError(f"Destination '{dst}' already exists. Set overwrite=True to replace.")

    # Ensure destination parent directory exists
    dst.parent.mkdir(parents=True, exist_ok=True)

    shutil.move(str(src), str(dst))
    return {
        "moved": True,
        "source": str(src),
        "destination": str(dst),
        "message": f"Successfully moved '{src.name}' to '{dst}'.",
    }


# ---------------------------------------------------------------------------
# BaseTool Classes
# ---------------------------------------------------------------------------

class FileReadTool(BaseTool):
    """Read the contents of a file."""

    name = "file_read"
    description = "Read and return the text contents of a file at the given path."
    required_permissions = ["fs.read"]
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute path to the file to read.",
            },
            "max_bytes": {
                "type": "integer",
                "description": "Maximum bytes to read (default: 100 000).",
            },
        },
        "required": ["path"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        path = kwargs.get("path", "")
        max_bytes = kwargs.get("max_bytes", 100_000)

        try:
            p = validate_safe_path(path)
            if not p.is_file():
                return ToolResult(
                    tool_name=self.name,
                    success=False,
                    error=f"Not a file: {path}",
                )

            content = p.read_text(errors="replace")[:max_bytes]
            return ToolResult(
                tool_name=self.name,
                success=True,
                output=content,
            )
        except Exception as exc:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=str(exc),
            )


class FileWriteTool(BaseTool):
    """Write content to a file."""

    name = "file_write"
    description = "Write text content to a file, creating parent directories if needed."
    required_permissions = ["fs.write"]
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute path to the file to write.",
            },
            "content": {
                "type": "string",
                "description": "Text content to write to the file.",
            },
            "append": {
                "type": "boolean",
                "description": "If true, append instead of overwriting.",
            },
        },
        "required": ["path", "content"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        path = kwargs.get("path", "")
        content = kwargs.get("content", "")
        append = kwargs.get("append", False)

        try:
            p = validate_safe_path(path, allow_nonexistent=True)
            p.parent.mkdir(parents=True, exist_ok=True)

            if append:
                with p.open("a", encoding="utf-8") as f:
                    f.write(content)
            else:
                p.write_text(content, encoding="utf-8")

            return ToolResult(
                tool_name=self.name,
                success=True,
                output=f"Wrote {len(content)} characters to {path}",
            )
        except Exception as exc:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=str(exc),
            )


class FileSearchTool(BaseTool):
    """Search for files matching a glob pattern."""

    name = "file_search"
    description = "Search for files matching a glob pattern under a base directory."
    required_permissions = ["fs.read"]
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Base directory to search in.",
            },
            "pattern": {
                "type": "string",
                "description": "Glob pattern (e.g. '*.py', '**/*.txt').",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return (default: 50).",
            },
        },
        "required": ["path", "pattern"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        base_path = kwargs.get("path", ".")
        pattern = kwargs.get("pattern", "*")
        max_results = kwargs.get("max_results", 50)

        try:
            p = validate_safe_path(base_path)
            if not p.is_dir():
                return ToolResult(
                    tool_name=self.name,
                    success=False,
                    error=f"Not a directory: {base_path}",
                )

            matches: list[str] = []
            for match in p.glob(pattern):
                matches.append(str(match))
                if len(matches) >= max_results:
                    break

            return ToolResult(
                tool_name=self.name,
                success=True,
                output=matches,
            )
        except Exception as exc:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=str(exc),
            )


class FileMetadataTool(BaseTool):
    """Retrieve metadata for a file or directory."""

    name = "file_metadata"
    description = "Retrieve structured metadata (size, timestamps, type, permissions) for a file or directory."
    required_permissions = ["fs.read"]
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file or directory.",
            },
        },
        "required": ["path"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        path = kwargs.get("path", "")
        try:
            meta = get_file_metadata(path)
            return ToolResult(
                tool_name=self.name,
                success=True,
                output=meta,
            )
        except Exception as exc:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=str(exc),
            )


class FileOpenOSTool(BaseTool):
    """Open a file using the OS default application."""

    name = "file_open_os"
    description = "Open a file or document using the operating system's default desktop handler."
    required_permissions = ["fs.read"]
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file to open.",
            },
        },
        "required": ["path"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        path = kwargs.get("path", "")
        try:
            res = await open_file_os(path)
            return ToolResult(
                tool_name=self.name,
                success=True,
                output=res,
            )
        except Exception as exc:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=str(exc),
            )


class FileMkdirTool(BaseTool):
    """Create a new directory."""

    name = "file_mkdir"
    description = "Create a new directory at the specified path."
    required_permissions = ["fs.write"]
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path of the directory to create.",
            },
            "parents": {
                "type": "boolean",
                "description": "Create parent directories if needed (default: true).",
            },
        },
        "required": ["path"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        path = kwargs.get("path", "")
        parents = bool(kwargs.get("parents", True))
        try:
            res = create_directory(path, parents=parents)
            return ToolResult(
                tool_name=self.name,
                success=True,
                output=res,
            )
        except Exception as exc:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=str(exc),
            )


class FileMoveTool(BaseTool):
    """Move or rename a file or directory."""

    name = "file_move"
    description = "Move or rename a file or directory to a new destination path."
    required_permissions = ["fs.write"]
    parameters_schema = {
        "type": "object",
        "properties": {
            "src_path": {
                "type": "string",
                "description": "Source path of the file or directory.",
            },
            "dst_path": {
                "type": "string",
                "description": "Destination path for the file or directory.",
            },
            "overwrite": {
                "type": "boolean",
                "description": "If true, overwrite existing destination (default: false).",
            },
        },
        "required": ["src_path", "dst_path"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        src_path = kwargs.get("src_path", "")
        dst_path = kwargs.get("dst_path", "")
        overwrite = bool(kwargs.get("overwrite", False))

        try:
            res = move_file(src_path, dst_path, overwrite=overwrite)
            return ToolResult(
                tool_name=self.name,
                success=True,
                output=res,
            )
        except Exception as exc:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=str(exc),
            )


class FileDeleteTool(BaseTool):
    """Delete a file (requires user confirmation via policy)."""

    name = "file_delete"
    description = "Delete a file at the given path. This action requires user confirmation."
    required_permissions = ["fs.delete"]
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute path to the file to delete.",
            },
        },
        "required": ["path"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        path = kwargs.get("path", "")

        try:
            p = validate_safe_path(path)
            if not p.is_file():
                return ToolResult(
                    tool_name=self.name,
                    success=False,
                    error=f"Not a regular file (will not delete directories): {path}",
                )

            p.unlink()
            return ToolResult(
                tool_name=self.name,
                success=True,
                output=f"Deleted: {path}",
            )
        except Exception as exc:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=str(exc),
            )
