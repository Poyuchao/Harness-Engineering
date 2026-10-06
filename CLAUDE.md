# CLAUDE.md

This repo is the user's hands-on project for a Harness Engineering course: building an agent harness from scratch, lesson by lesson. Reply in Traditional Chinese.

## Workflow for each lesson

The user pastes a lesson transcript (English, spoken, with speech-to-text errors such as "honest" = harness, "bear loop" = bare loop, "cloud" = Claude). For each one:

1. **Implement the lesson's code** in this repo so it matches what the transcript builds.
   - Follow the transcript's design and naming, but fix real problems (bugs, version incompatibilities, unsafe patterns) and tell the user what differed and why.
   - Verify what can be verified locally (imports, direct tool calls via `registry.dispatch`, `printf 'quit\n' | .venv/Scripts/python -m harness.agent`). Say plainly what could not be tested (e.g. needs an API key).
   - If a lesson is theory/demo only with no code changes, say so instead of inventing code.
2. **Summarize the lesson** in the reply: key concepts learned and what was built.
3. **Add the lesson to `README.md`** (`# AI Engineering Notes` section), under the right chapter heading as `### <chapter>-<lesson> <title>`. Record concepts, design decisions, and any gotchas. Write it as an engineer's technical notes, not a beginner's study log: no "學到/課程/上課" wording, no references to the course or instructor. Also fold in conclusions from the user's follow-up questions about that lesson. Keep `## Project structure` in sync every lesson: new files, and also changed responsibilities of existing files (e.g. new features in agent.py) and the tool count.

Only commit/push when the user asks. Remote: https://github.com/Poyuchao/Harness-Engineering.git (`main`).

## Environment

- Windows; `python` is not on PATH. Use `.venv/Scripts/python` (or `py` outside the venv).
- Run the agent: `python -m harness.agent` from the repo root.
- `openai==1.50.0` requires `httpx<0.28` (pinned in `requirements.txt`).
- Default model `gpt-4o-mini`; setting `KIMI_API_KEY` in `.env` switches to Kimi. Never print or commit `.env`.
- Agent file operations are confined to `.workspace/` (gitignored).
