"""Git tools: status, diff, log, commit, checkout, branch, all scoped to the workspace.

Versioning is a harness primitive: it lets the agent checkpoint work, roll back
mistakes, and try risky ideas on a branch. We call the git binary directly
(no extra dependency, and the model already knows git's raw output well).

Deliberately left out: remote ops (push/pull/fetch), merge, stash, rebase.
They need network access or two-way conflict resolution with the user.
"""

import subprocess

from harness.tools.filesystem import WORKSPACE, _resolve_path
from harness.tools.registry import tool

# Local git operations are fast. Anything slower is likely stuck, so kill it
# rather than freeze the agent.
GIT_TIMEOUT = 10


def _run_git(*args: str) -> str:
    """Run `git <args>` inside the workspace and return its output as text."""
    # 1. Run the git binary with the workspace as the working directory.
    result = subprocess.run(
        ["git", *args],
        cwd=WORKSPACE,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=GIT_TIMEOUT,
        check=False,  # non-zero exit is reported to the model, not raised
    )
    # 2. Prefer stdout; fall back to stderr (git writes some messages there).
    output = result.stdout.strip() or result.stderr.strip()
    if result.returncode != 0:
        return f"git exited with code {result.returncode}:\n{output}"
    return output or "(no output)"


def _check_ref(name: str) -> None:
    """Reject names that git would parse as options (e.g. '--force')."""
    if not name or name.startswith("-"):
        raise ValueError(f"Invalid ref or branch name: '{name}'")


# Auto-initialize the workspace as a git repo, so the model never has to
# remember to. Side effect: runs as soon as this module is imported.
if not (WORKSPACE / ".git").exists():
    _run_git("init", "-b", "main")
    _run_git("config", "user.name", "agent")
    _run_git("config", "user.email", "agent@harness.local")


@tool
def git_status() -> str:
    """Show which files in the workspace are modified, staged, or untracked."""
    return _run_git("status", "--short", "--branch")


@tool
def git_diff(path: str = "") -> str:
    """Show uncommitted changes in the workspace, optionally limited to one path."""
    if path:
        _resolve_path(path)  # same workspace boundary as the file tools
        return _run_git("diff", "--", path)
    return _run_git("diff")


@tool
def git_log() -> str:
    """Show the last 10 commits, one line each."""
    return _run_git("log", "--max-count=10", "--oneline")


@tool
def git_commit(message: str) -> str:
    """Stage all changes in the workspace and commit them with the given message."""
    _run_git("add", "-A")
    return _run_git("commit", "-m", message)


@tool
def git_checkout(ref: str) -> str:
    """Check out a branch name or commit hash (use this to switch branches or roll back)."""
    _check_ref(ref)
    return _run_git("checkout", ref)


@tool
def git_branch(name: str = "") -> str:
    """List branches if no name is given; otherwise create a branch with that name."""
    if not name:
        return _run_git("branch")
    _check_ref(name)
    return _run_git("branch", name)
