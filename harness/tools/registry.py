"""Tool registry: stores tools, generates schemas, and dispatches calls."""

import inspect
from dataclasses import dataclass
from typing import Any, Callable

from pydantic import TypeAdapter


@dataclass
class Tool:
    """The shape of every tool the harness exposes to the model."""

    name: str
    description: str
    fn: Callable[..., Any]  # the function that actually does the work
    schema: dict  # JSON schema of the arguments, generated automatically


class ToolRegistry:
    """Holds tools, exposes their schemas, and dispatches incoming calls."""

    def __init__(self):
        # name -> Tool
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get_schemas(self) -> list[dict]:
        """Return every tool in the OpenAI tool-schema format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.schema,
                },
            }
            for t in self._tools.values()
        ]

    def dispatch(self, name: str, args: dict) -> str:
        """Run the named tool with the model's arguments and return a string.

        Errors are returned as text rather than raised, so the model can see
        what went wrong and report it cleanly.
        """
        if name not in self._tools:
            return f"Error: unknown tool '{name}'"
        try:
            result = self._tools[name].fn(**args)
            return str(result)
        except Exception as e:
            return f"Error: {e}"


# Module-level registry that the rest of the harness imports.
registry = ToolRegistry()


def tool(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator: register `fn` as a tool.

    The name comes from the function name, the description from its
    docstring, and the argument schema from its type hints.
    """
    registry.register(
        Tool(
            name=fn.__name__,
            description=inspect.getdoc(fn) or "",
            fn=fn,
            schema=TypeAdapter(fn).json_schema(),
        )
    )
    # Return the function unchanged so it can still be called normally.
    return fn
