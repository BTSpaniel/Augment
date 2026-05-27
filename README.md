<p align="center">
  <img src="assets/augment-logo.svg" alt="Augment local AI workspace logo" width="160" />
</p>

<p align="center">
  <strong>Local-first AI workbench for streaming chat, ReAct tools, memory, context budgeting, and guarded file edits.</strong>
</p>

<p align="center">
  <img alt="Python 3.11+" src="https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white" />
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-local%20server-009688?style=flat-square&logo=fastapi&logoColor=white" />
  <img alt="Vanilla UI" src="https://img.shields.io/badge/UI-vanilla%20HTML%2FCSS%2FJS-f7df1e?style=flat-square&logo=javascript&logoColor=111111" />
  <img alt="License MIT" src="https://img.shields.io/badge/License-MIT-111827?style=flat-square" />
</p>

<p align="center">
  <a href="#quick-start">Quick Start</a>
  ·
  <a href="#features">Features</a>
  ·
  <a href="#configuration">Configuration</a>
  ·
  <a href="#usage">Usage</a>
  ·
  <a href="#license">License</a>
</p>

# Augment

Augment is a compact, local AI workbench for building, researching, editing, and thinking with LLMs. It keeps the useful parts of larger agent systems: provider routing, a ReAct loop, safe workspace tools, session memory, prompt budgeting, and a hosted chat UI, without forcing you into dashboards, work orders, agent swarms, or remote orchestration.

It is designed for developers who want a fast local assistant that can inspect a workspace, use tools, stream responses live, remember useful context, and write files with guardrails.

## Highlights

- **Local web UI**: A polished vanilla HTML/CSS/JS chat interface served by FastAPI.
- **CLI included**: Chat, list tools, and run the HTTP server from your terminal.
- **OpenAI-compatible providers**: Works with Groq, OpenAI-compatible APIs, local servers, llama.cpp, vLLM, LM Studio-style endpoints, and similar providers.
- **ReAct tool loop**: One assistant loop with structured tool calls, parallel read/search plans, and sequential mutations.
- **Live streaming**: Token deltas, reasoning deltas, tool events, context stats, and final answers stream over SSE.
- **Reload-aware streaming groundwork**: Active stream registry support gives long-running chat tasks a path toward browser reload recovery.
- **Context intelligence**: Prompt sections are budgeted by model context window, placed into smart/dumb zones, and measured with token-aware diagnostics.
- **Memory layers**: Session history, scratchboards, turn state, mailbox notes, user model hints, and persistent memory context.
- **Coding discipline**: Project conventions, user rules, per-session coding contracts, edit receipts, and a hard style gate for generated code files.
- **Tool safety**: Workspace-scoped file tools, sensitive path guards, mutation receipts, and no silent claims about edits.

## Quick Start

### 1. Clone the repository

```powershell
git clone https://github.com/your-org/augment.git
cd augment
```

### 2. Create a virtual environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

On macOS or Linux:

```bash
python -m venv .venv
source .venv/bin/activate
```

### 3. Install Augment

```powershell
python -m pip install -e ".[all,dev]"
python -m playwright install chromium
```

### 4. Create a config file

```powershell
copy config.example.yaml config.yaml
```

On macOS or Linux:

```bash
cp config.example.yaml config.yaml
```

### 5. Set your provider key

```powershell
$env:AUGMENT_API_KEY = "your-api-key"
```

On macOS or Linux:

```bash
export AUGMENT_API_KEY="your-api-key"
```

### 6. Start the app

```powershell
augment serve --host 127.0.0.1 --port 8787
```

Then open:

```text
http://127.0.0.1:8787
```

## Requirements

- Python 3.11 or newer
- A provider compatible with OpenAI-style chat completions
- An API key or a local model endpoint
- Modern browser for the web UI

Core Python dependencies are defined in `pyproject.toml`:

- `fastapi`
- `uvicorn[standard]`
- `httpx`
- `h2`
- `pydantic`
- `PyYAML`
- `requests`
- `urllib3`
- `charset-normalizer`

Optional feature extras:

- `augment[browser]`: Playwright browser automation, screenshots, and Patchwright visual verification.
- `augment[web]`: DDGS/crawl4ai-powered web/news/research with HTTP and browser fallback.
- `augment[all]`: Browser and web extras together.

Development dependencies:

- `pytest`
- `pytest-asyncio`

## Configuration

Augment reads `config.yaml` from the project root. Start from `config.example.yaml`:

```yaml
server:
  host: 127.0.0.1
  port: 8787

workspace_root: .
data_dir: data

provider:
  id: default
  name: OpenAI Compatible
  endpoint: https://api.groq.com/openai/v1
  api_key_env: AUGMENT_API_KEY
  model: llama-3.1-8b-instant
  timeout_seconds: 120

loop:
  max_iterations: 10
  temperature: 0.2

context:
  total_budget_chars: 24000
```

The context budget setting is a conservative starter value. Runtime budgeting can scale from provider context-window metadata when the active model exposes it.

### Provider notes

The default provider is OpenAI-compatible. You can point it at:

- OpenAI-compatible hosted APIs
- Groq
- OpenRouter-style gateways
- vLLM
- llama.cpp server
- LM Studio-compatible local endpoints
- Other providers that expose compatible chat/completions behavior

Provider settings can also be managed through the web UI under **Settings → Providers & Keys**.

## Usage

### Start the web app

```powershell
augment serve
```

### Send one CLI chat message

```powershell
augment chat "Summarize this repository."
```

### Continue an existing session

```powershell
augment chat "Continue from earlier." --session-id sess_abc123
```

### List available tools

```powershell
augment tools
```

## Web UI

The hosted UI gives you a local cockpit for:

- Chat sessions and project grouping
- Streaming assistant responses
- Live tool activity
- Reasoning/thinking panels
- Provider and model selection
- Memory inspection
- Tool pack browsing
- Skill pack browsing
- Agent profile settings
- Session status, context usage, and diagnostics

The UI is intentionally framework-free: static HTML, CSS, and JavaScript served by FastAPI.

## Features

### Streaming chat

Augment streams structured Server-Sent Events from `/api/chat/stream`:

- `started`
- `thinking`
- `token_delta`
- `reasoning_delta`
- `tool_plan`
- `tool_call`
- `tool_result`
- `bleep`
- `heartbeat`
- `error`
- `done`

The UI renders token deltas live, keeps tool activity visible, and shows context diagnostics while the model is working.

### ReAct tools

Augment runs a single ReAct loop that can call tools for:

- File listing, reading, writing, and editing
- Search and investigation
- Commands and sandbox operations
- Git operations
- Memory and wiki lookup
- Browser/web utilities
- Provider introspection
- Codex-related integration points

Read-only tools can be batched in `<tool_plan>` blocks. Mutation tools run sequentially.

### Context budgeting

The context builder organizes prompt material into attention-aware zones:

- **Smart top**: identity, conventions, user rules, coding contracts, active plan, tool policy
- **Dumb middle**: bulky reference material, memory, workspace state, skills
- **Smart bottom**: recent turn state, message ledger, chat history

Budgets scale from the active provider context window, reserve output tokens, and keep a safety buffer for tool-result expansion.

### Memory and session depth

Augment tracks useful context across turns through:

- Session history
- Persistent memory facts
- Tiered memory context
- Scratchboards
- Turn state
- Message ledger
- User model observations
- Mailbox notes

### Coding contracts and rule loading

Augment can load durable rules from:

- `AGENTS.md`
- `CONVENTIONS.md`
- `STYLE.md`
- `RULES.md`
- `.augment/RULES.md`
- `.cursorrules`
- `.windsurfrules`
- `CLAUDE.md`
- `data/rules/*.md`
- `.augment/rules/*.md`
- Per-session coding contracts

These rules are injected into the prompt and backed by tool-level gates for generated code files.

### Edit receipts and style gates

File mutations can produce edit receipts with target paths, hashes, diffs, and structural checks. Generated code files are also checked for:

- Required file-header banners
- Section markers for long files
- Public Python docstrings
- Public JavaScript JSDoc blocks

Non-compliant code writes are rejected before the file is written.

### Local file reveal

Markdown links to local files can be revealed in the operating system file browser through the `/api/files/reveal` endpoint. Paths are normalized, checked, and guarded before opening.

## API Overview

Common endpoints:

| Endpoint | Method | Purpose |
| --- | --- | --- |
| `/healthz` | `GET` | Health check |
| `/api/chat` | `POST` | Non-streaming chat |
| `/api/chat/stream` | `POST` | Streaming chat over SSE |
| `/api/tools` | `GET` | List tools |
| `/api/providers/*` | mixed | Provider discovery and settings |
| `/api/memory` | `GET` | Memory snapshot |
| `/api/sessions/*` | mixed | Session history, metadata, mailbox, contracts |
| `/api/builder/*` | mixed | Builder policies, receipts, verification |
| `/api/files/reveal` | `POST` | Reveal a local file/folder in the OS file browser |

## Project Layout

```text
augment/
  api/                 FastAPI routers
  builder/             Edit receipts, policies, verification
  context/             Prompt building, budgeting, rules, conventions
  loop/                ReAct loop
  memory/              Persistent memory system
  providers/           Provider adapters and registry
  sessions/            Session depth stores
  skills/              Skill packs
  streaming/           Active stream registry
  tools/               Tool registry and tool implementations
ui/
  index.html           Local web UI shell
  app.js               UI behavior and streaming renderer
  style.css            UI styling
data/
  rules/               Runtime rule sheets
tests/
  test_*.py            Pytest suite
```

## Development

Run the focused test suite:

```powershell
python -m pytest -q
```

Run a specific test file:

```powershell
python -m pytest tests\test_tools.py -q
```

Compile-check changed Python files:

```powershell
python -m py_compile augment\tools\files.py augment\context\builder.py
```

## Security Model

Augment is local-first, but tools are still powerful. Important constraints:

- File access is scoped to configured workspace roots where applicable.
- Sensitive paths such as `.env`, SSH keys, credentials, and key files are guarded.
- New relative writes default to a session scratch directory unless the user sets an output directory.
- Mutation tools run sequentially.
- Edit receipts record file mutation evidence.
- The assistant should not claim a file changed unless a tool actually succeeded.

You should still review generated edits before trusting or shipping them.

## Roadmap

- Complete reload-safe stream resume flow in the UI.
- Expand provider streaming parity.
- Add richer receipt inspection and verification surfaces.
- Improve rule/contract authoring from the web UI.
- Package a first-run setup wizard.

## License

Augment is released under the [MIT License](LICENSE).
