import json
import os

from dotenv import load_dotenv
from openai import OpenAI

from harness.memory import load_agents_md
from harness.tools import registry

load_dotenv()

# Pick the backend based on which key is set in .env.
# Kimi speaks the OpenAI API, so the same SDK works: we only swap
# the API key and base URL.
if os.getenv("KIMI_API_KEY"):
    MODEL = "kimi-k2.6"
    client = OpenAI(
        api_key=os.getenv("KIMI_API_KEY"),
        base_url=os.getenv("KIMI_BASE_URL", "https://api.moonshot.ai/v1"),
    )
    # Kimi K2.6+ thinks by default. Disable it to save tokens and avoid
    # handling `reasoning_content` in responses.
    EXTRA_BODY = {"thinking": {"type": "disabled"}}
else:
    # Default: OpenAI. gpt-4o-mini is cheap and fast.
    MODEL = "gpt-4o-mini"
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    EXTRA_BODY = None

# Max tool-call rounds per user turn. When hit, the harness forces the model
# to summarize and hand control back to the user instead of looping forever.
STEP_BUDGET = 25

# Synthetic system message injected when the step budget is exceeded. Tells
# the model why it must stop and what shape the response should take.
BUDGET_EXCEEDED_MESSAGE = f"""You have reached the step budget for this turn ({STEP_BUDGET} tool-call rounds). Do not make any more tool calls. Instead, respond directly to the user with:
1. What you accomplished in this turn.
2. What remains to be done.
3. What the user should ask next to continue the work.
Your response will be the final message for this turn. The user will reply to it, and you can continue from there."""

# The system prompt: the first message the model sees on every turn.
# - Identity: coding assistant running in a terminal.
# - Output conventions: concise, minimal explanation, fenced code blocks.
# - Capabilities: five file system tools, scoped to the workspace (the scoping
#   itself is a hard constraint enforced in code, not in this prompt).
# - Git: six versioning tools. The workspace is auto-initialized as a repo in
#   code (hard); the commit/branch habits below are soft guidance.
# - Bash: the meta tool, for anything the specific tools don't cover.
# - Memory: how to maintain AGENTS.md. Loading it is done by the harness
#   (hard); deciding what to write is left to the model (soft).
SYSTEM_PROMPT = """You are a coding assistant running in the terminal, helping a developer with software engineering tasks.

Be concise. Prefer short, direct answers over long ones. When the user asks for code, return the code with minimal explanation unless they ask for more.

When returning code, use fenced code blocks and specify the language.

You have access to five file system tools (read_file, write_file, list_dir, make_dir, delete_file) operating on a workspace directory. Use them whenever a task involves reading, modifying, or organizing files. Pass paths relative to the workspace root. Prefer reading and writing real files over describing them in conversation.

You have six git tools (git_status, git_diff, git_log, git_commit, git_checkout, git_branch) for versioning your work. The workspace is already initialized as a git repository.
- Commit frequently. Small, focused commits are easier to roll back.
- Commit before doing anything risky (large writes, deleting files, restructuring). A commit before the risky step gives you a recovery point.
- Write meaningful commit messages that describe what and why, in the present tense (e.g. "Add user authentication module").
- When trying an alternative approach, create a branch first so the main line of work stays intact.

You have one more tool: bash. It executes shell commands in the workspace with full shell interpretation, so pipes, redirects, and command chaining all work. Use bash for anything the specific tools above don't cover: running scripts (python foo.py, node foo.js), invoking system utilities (grep, curl, wc), installing packages (pip install ...), or exploring the environment (ls, pwd, which python).
- Prefer the specific tools when they apply. To read a file, use read_file, not `cat`. To commit, use git_commit. The specific tools are safer, faster, and clearer to trace.
- Reach for bash when the specific tools don't cover what you need, which is often, because software work is varied.
- bash commands use the workspace as their working directory. `cd` inside a bash command does not persist to the next call; each call starts fresh from the workspace root.

The workspace contains an AGENTS.md file: your durable memory across sessions. It is automatically loaded into your context at the start of every session. Update it with write_file when you learn something worth remembering for future sessions. Good things to write:
- Project context: what this codebase is, what it does, who uses it.
- Conventions you've observed: code style, libraries, naming patterns.
- Decisions that have been made and the reasoning behind them.
- Gotchas: quirks, non-obvious dependencies, things that tripped up earlier sessions.
- Active tasks: what is currently being worked on. Clear them when complete.
When updating AGENTS.md, keep its existing structure and section headings, and add to the relevant section instead of replacing unrelated content. If a section still holds a parenthetical hint like "(What this project is...)", replace the hint with real content."""


def _call_model(messages: list, **kwargs):
    """Call the model with the full history and the available tools."""
    response = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        tools=registry.get_schemas(),
        # Provider-specific params; None for OpenAI, so nothing is sent.
        extra_body=EXTRA_BODY,
        **kwargs,
    )
    return response.choices[0].message


TRACE_MAX_LINES = 20


def _trace(name: str, args: dict, result: str) -> None:
    """Print a tool call and its raw result, so the user sees what actually ran
    instead of relying on the model's summary of it."""
    print(f"\n  [tool] {name}({json.dumps(args, ensure_ascii=False)})")
    lines = result.splitlines() or [""]
    for line in lines[:TRACE_MAX_LINES]:
        print(f"  | {line}")
    if len(lines) > TRACE_MAX_LINES:
        print(f"  | ... ({len(lines) - TRACE_MAX_LINES} more lines)")


def run():
    """Run the agent's conversation loop until the user quits."""
    # Load cross-session memory. The harness does this every session (hard
    # constraint) rather than trusting the model to remember to read it.
    agents_md = load_agents_md()

    # The conversation history: the agent's working memory for this session.
    # Every turn, we append to it and send the whole thing back.
    # It starts with two system messages, the instructions and then AGENTS.md.
    # The model reads them as one context; keeping them separate makes each
    # layer easy to tell apart when debugging.
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": agents_md},
    ]

    print("Agent ready. Type 'quit' or 'exit' to leave.\n")

    while True:
        # 1. Get user input
        user_input = input("You: ").strip()

        # 2. Handle exit commands and empty input
        if user_input.lower() in ("quit", "exit"):
            print("Goodbye!")
            break
        if not user_input:
            continue

        # 3. Append the user's message to the history
        messages.append({"role": "user", "content": user_input})

        # 4. ReAct loop: reason (model call) -> act (run tools) -> observe
        # (results go into history) -> repeat until the model answers in text.
        step_count = 0
        while True:
            message = _call_model(messages)

            # 4a. No tool calls: the model has its final answer.
            if not message.tool_calls:
                break

            # 4b. Out of budget: drop the pending tool calls, tell the model to
            # wrap up, and get a text-only summary for the user.
            if step_count >= STEP_BUDGET:
                messages.append({"role": "system", "content": BUDGET_EXCEEDED_MESSAGE})
                message = _call_model(messages, tool_choice="none")
                break

            # 4c. Record the tool-call message, run each tool, append results.
            # The model may request several calls in one response.
            messages.append(message.model_dump(exclude_none=True))
            for call in message.tool_calls:
                args = json.loads(call.function.arguments)
                result = registry.dispatch(call.function.name, args)
                _trace(call.function.name, args, result)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": result,
                    }
                )
            step_count += 1

        # 5. After the loop, message.content should hold real text. If not,
        # something unexpected happened (API edge case, loop bug, credits ran
        # out). Fail loudly rather than hide it behind a placeholder.
        assistant_text = message.content
        if not assistant_text:
            raise RuntimeError(
                "ReAct loop ended but message.content is empty. This shouldn't "
                "happen; check the API response and the loop's termination logic."
            )

        # 6. Append the reply to the history so the next turn sees it
        messages.append({"role": "assistant", "content": assistant_text})

        # 7. Show the reply
        print(f"\nAgent: {assistant_text}\n")


if __name__ == "__main__":
    run()
