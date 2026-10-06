"""Bash tool: the meta tool. Runs a shell command string in the workspace.

Unlike git.py (argument list, no shell), this hands the model a real shell so
pipes, redirects, chaining, and substitution all work natively. That is also
a security concern; command allow/deny lists come in a later layer.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

from harness.tools.filesystem import WORKSPACE
from harness.tools.registry import tool

# Long enough for pip installs, curl, or a git clone; short enough not to hang.
BASH_TIMEOUT = 60


def _find_bash() -> str:
    """Locate a bash executable.

    On Windows, `bash` on PATH is usually the WSL launcher, so use Git Bash,
    which ships next to git.exe.
    """
    if os.name == "nt":
        git = shutil.which("git")
        if git:
            candidate = Path(git).resolve().parents[1] / "bin" / "bash.exe"
            if candidate.exists():
                return str(candidate)
        return r"C:\Program Files\Git\bin\bash.exe"
    return shutil.which("bash") or "/bin/bash"


BASH = _find_bash()

# Put the harness's own Python first on PATH, so `python` inside bash resolves
# to the same interpreter (e.g. the venv) even if the venv isn't activated.
_ENV = os.environ.copy()
_ENV["PATH"] = str(Path(sys.executable).parent) + os.pathsep + _ENV.get("PATH", "")


def _combine_output(stdout: str, stderr: str) -> str:
    """Return stdout, with stderr appended when present (both can be useful)."""
    stdout, stderr = stdout.strip(), stderr.strip()
    if stdout and stderr:
        return f"{stdout}\n--- stderr ---\n{stderr}"
    return stdout or stderr


@tool
def bash(command: str) -> str:
    """Run a bash command in the workspace and return its output.

    The command runs with the workspace as its working directory, with full
    shell interpretation: pipes, redirects, command chaining, and substitution
    all work. stdout and stderr are both returned. Each call starts a fresh
    shell, so `cd` does not persist between calls.
    """
    try:
        result = subprocess.run(
            [BASH, "-c", command],
            cwd=WORKSPACE,
            env=_ENV,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=BASH_TIMEOUT,
            check=False,  # non-zero exit is reported to the model, not raised
        )
    except subprocess.TimeoutExpired:
        return f"[command timed out after {BASH_TIMEOUT}s and was killed]"

    output = _combine_output(result.stdout, result.stderr) or "(no output)"
    # Square brackets mark harness-generated info, distinct from shell output,
    # so the model can't mistake a failed command for a successful one.
    if result.returncode != 0:
        return f"[bash exited with code {result.returncode}]\n{output}"
    return output
