import json
import os

from dotenv import load_dotenv
from openai import OpenAI

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

# The system prompt: the first message the model sees on every turn.
# - Identity: coding assistant running in a terminal.
# - Output conventions: concise, minimal explanation, fenced code blocks.
# - Capabilities: five file system tools, scoped to the workspace (the scoping
#   itself is a hard constraint enforced in code, not in this prompt).
SYSTEM_PROMPT = """You are a coding assistant running in the terminal, helping a developer with software engineering tasks.

Be concise. Prefer short, direct answers over long ones. When the user asks for code, return the code with minimal explanation unless they ask for more.

When returning code, use fenced code blocks and specify the language.

You have access to five file system tools (read_file, write_file, list_dir, make_dir, delete_file) operating on a workspace directory. Use them whenever a task involves reading, modifying, or organizing files. Pass paths relative to the workspace root. Prefer reading and writing real files over describing them in conversation."""


def run():
    """Run the agent's conversation loop until the user quits."""
    # The conversation history. This is the entire memory of the agent.
    # Every turn, we append to it and send the whole thing back.
    # It starts with the system prompt, so the model sees it on every call.
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

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

        # 4. Call the model with the full history and the available tools
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=registry.get_schemas(),
            # Provider-specific params; None for OpenAI, so nothing is sent.
            extra_body=EXTRA_BODY,
        )
        message = response.choices[0].message

        # 5. If the model asked for tools, run them and call the model again
        if message.tool_calls:
            # 5a. Record the assistant's tool-call message in the history
            messages.append(message.model_dump(exclude_none=True))

            # 5b. Run each requested tool and append its result to the history.
            # The model may request several calls in one response.
            for call in message.tool_calls:
                args = json.loads(call.function.arguments)
                result = registry.dispatch(call.function.name, args)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": result,
                    }
                )

            # 5c. Send everything back so the model can write its final answer
            response = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=registry.get_schemas(),
                extra_body=EXTRA_BODY,
            )
            message = response.choices[0].message

        # 6. Extract the text reply (works whether or not tools were called)
        assistant_text = message.content

        # 7. Append the reply to the history so the next turn sees it
        messages.append({"role": "assistant", "content": assistant_text})

        # 8. Show the reply
        print(f"\nAgent: {assistant_text}\n")


if __name__ == "__main__":
    run()
