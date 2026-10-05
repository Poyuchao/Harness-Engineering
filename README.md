# Agent Harness

A from-scratch agent harness, built over the course of nine chapters.

## Setup

```bash
git clone <repo-url>
cd agent-harness
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in OPENAI_API_KEY
```

## Run

```bash
python -m harness.agent
```
