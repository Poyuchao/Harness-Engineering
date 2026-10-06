"""Bash tool: the meta tool. Runs a shell command string in the workspace.

Unlike git.py (argument list, no shell), this hands the model a real shell so
pipes, redirects, chaining, and substitution all work natively. That is also
a security concern, so every command first passes an allow/deny list policy.
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from harness.tools.filesystem import WORKSPACE
from harness.tools.registry import tool

# Long enough for pip installs, curl, or a git clone; short enough not to hang.
BASH_TIMEOUT = 60

# Allow list of permitted commands, matched against the first token of each
# chain segment. Empty means no restriction: any command not on the deny list
# is allowed. Populate it to lock the agent down to a known set of tools.
ALLOW_LIST: set[str] = set()

# Deny list of forbidden commands, matched the same way. Blocks specific
# dangerous commands even in an otherwise permissive setup.
# Precedence: deny wins on conflict. A command on both lists is rejected
# (fail closed, like IAM policies and firewalls).
DENY_LIST: set[str] = {"rm", "sudo", "dd"}

# Separators that split a composite command into segments, so each command
# in a chain is checked (e.g. `cd x && rm -rf y` checks both cd and rm).
CHAIN_SEPARATORS = ["&&", "||", ";", "|", "&", "\n"]
_SPLIT_RE = re.compile("|".join(re.escape(sep) for sep in CHAIN_SEPARATORS))


def _first_token(segment: str) -> str:
    """Return the command name of one segment ("" if empty).

    Skips subshell/grouping openers and leading VAR=value assignments, and
    strips paths, so `(rm x)`, `FOO=1 rm x`, and `/bin/rm x` all yield "rm".
    """
    for token in segment.strip().lstrip("({").split():
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", token):
            continue
        return Path(token.strip("'\"")).name
    return ""


def _segments(command: str) -> list[str]:
    """Split a command into its chained segments."""
    return [seg for seg in _SPLIT_RE.split(command) if seg.strip()]


def _check_policy(command: str) -> str | None:
    """Check a command against the deny and allow lists.

    Returns None if the command is permitted, or an error string if not.
    """
    tokens = [_first_token(seg) for seg in _segments(command)]
    for token in tokens:
        if token in DENY_LIST:
            return f"[policy: '{token}' is on the deny list; refusing to run]"
    if ALLOW_LIST:
        for token in tokens:
            if token not in ALLOW_LIST:
                return f"[policy: '{token}' is not on the allow list; refusing to run]"
    return None


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

    Commands are subject to the allow/deny list policy defined at the top of
    this module. If the policy refuses a command, an error is returned instead
    of executing it.
    """
    # Policy check before touching subprocess: fast rejection, no shell
    # invoked, no side effects. The model gets the error and can try a
    # different command.
    refusal = _check_policy(command)
    if refusal:
        return refusal

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
