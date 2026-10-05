"""File system tools: read, write, list, mkdir, delete, all bounded to the workspace."""

from pathlib import Path

from harness.tools.registry import tool

# Every file operation is scoped to this folder at the project root.
# Side effect: the folder is created as soon as this module is imported.
WORKSPACE = (Path(__file__).resolve().parents[2] / ".workspace").resolve()
WORKSPACE.mkdir(exist_ok=True)


def _resolve_path(path: str) -> Path:
    """Resolve `path` inside the workspace, refusing anything that escapes it."""
    # 1. Treat the path as relative to the workspace.
    target = (WORKSPACE / path).resolve()
    # 2. Confirm it is still inside the workspace (blocks `../` and absolute paths).
    if not target.is_relative_to(WORKSPACE):
        raise ValueError(f"Path '{path}' escapes the workspace")
    return target


@tool
def read_file(path: str) -> str:
    """Read a text file from the workspace and return its contents."""
    return _resolve_path(path).read_text(encoding="utf-8")


@tool
def write_file(path: str, content: str) -> str:
    """Write content to a file in the workspace. Overwrites the file if it exists."""
    target = _resolve_path(path)
    # Create parent directories for nested writes.
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"Wrote {len(content)} characters to {path}"


@tool
def list_dir(path: str = ".") -> str:
    """List the entries of a directory in the workspace. Directories end with '/'."""
    target = _resolve_path(path)
    if not target.is_dir():
        return f"Error: '{path}' is not a directory"
    entries = sorted(target.iterdir())
    if not entries:
        return "(empty)"
    return "\n".join(e.name + ("/" if e.is_dir() else "") for e in entries)


@tool
def make_dir(path: str) -> str:
    """Create a directory in the workspace, including any missing parents."""
    _resolve_path(path).mkdir(parents=True, exist_ok=True)
    return f"Created directory {path}"


@tool
def delete_file(path: str) -> str:
    """Delete a file from the workspace. Directories cannot be deleted."""
    target = _resolve_path(path)
    # Deleting directories is disallowed for now; relaxed in Chapter 5.
    if target.is_dir():
        return f"Error: '{path}' is a directory; deleting directories is not allowed"
    target.unlink()
    return f"Deleted {path}"
