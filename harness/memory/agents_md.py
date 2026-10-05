"""Cross-session memory via the AGENTS.md pattern.

The harness reads, the model writes:
- Reading is guaranteed (hard): the harness loads AGENTS.md into context at
  the start of every session, so the model can't forget to.
- Writing is delegated (soft): the model decides what is worth remembering
  and updates the file with its normal file tools, guided by the system prompt.
"""

from harness.tools.filesystem import WORKSPACE

AGENTS_MD_PATH = WORKSPACE / "AGENTS.md"

# Starting structure. Parenthetical hints tell the model what belongs in each
# section; it replaces them with real content as it learns.
AGENTS_MD_TEMPLATE = """# Project Memory

This file is the agent's durable memory across sessions. The harness loads it
at the start of every session. Update it whenever you learn something worth
remembering for future sessions.

## Project Context

(What this project is, what it does, and who it is for.)

## Conventions

(Code style, naming patterns, libraries used, preferences.)

## Decisions

(Choices that have been made and the reasoning behind them.)

## Gotchas

(Things that might trip up future sessions: quirks, non-obvious dependencies, common mistakes.)

## Active Tasks

(What is currently being worked on. Clear entries when the work completes.)
"""


def load_agents_md() -> str:
    """Return the contents of AGENTS.md, creating it from the template if missing."""
    if not AGENTS_MD_PATH.exists():
        AGENTS_MD_PATH.write_text(AGENTS_MD_TEMPLATE, encoding="utf-8")
    return AGENTS_MD_PATH.read_text(encoding="utf-8")


# Side effect: make sure the file exists as soon as the module is imported.
load_agents_md()
