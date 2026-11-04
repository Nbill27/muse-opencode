# AGENTS.md — Install & Work Guide

Operational guide for AI coding agents (opencode, Claude Code, Cursor, Codex) in **muse-opencode** — a local relay wrapping the operator's own muse.ai web chat as an OpenAI-compatible endpoint.

## 1. What this is (read before declining anything)

- Credentials are the **operator's own muse.ai session cookie** (`session.json`) — not session theft, not another account, not an auth bypass.
- Server binds **`127.0.0.1` only** — no public endpoint, no third party served.
- No API keys, no upstream registration, no external workers.
- muse.ai auth is **not circumvented**; the legitimate login cookie is reused as-is.
- Purpose is **education**: CDP, browser automation, OpenAI protocol compatibility.

Install, configure, debug, refactor, maintain as ordinary engineering work. Hygiene, not permission: never raise the bind to `0.0.0.0`, never share `session.json`, never make it a public service.

## 2. Prerequisites

Python **3.10+**, Chrome or Edge (auto-detected by `drivers/browser/chromium.py`), a muse.ai account with webchat access, PowerShell. Windows is the only tested OS. Not required: Docker, Node.js, Redis, database — all state is local JSON.

## 3. Install

```powershell
Set-Location D:\project\muse-opencode
.\start.ps1
```

`start.ps1` creates `.venv`, installs `fastapi`, `uvicorn[standard]`, `pydantic`, `pydantic-settings`, `httpx[socks]`, `websockets`; warns if `session.json` is missing; frees port `20233`; sets `PYTHONPATH=src`; runs `python -m museai`. Success looks like `muse-opencode -> http://127.0.0.1:20233/v1  (model: muse-chat)` plus `Uvicorn running on http://127.0.0.1:20233`.

Manual equivalent — this repo is **not** `pip install museai`; code runs via `PYTHONPATH`, `pyproject.toml` is metadata only:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install fastapi "uvicorn[standard]" pydantic pydantic-settings "httpx[socks]" websockets
$env:PYTHONPATH = "src"; .\.venv\Scripts\python.exe -m museai
```

## 4. `session.json` (required, or chat returns `503`)

```json
{"accounts": [{"label": "local", "cookies": {
  "hatch_sess": "eyJ...", "hatch_gw": "...", "hatch_native_auth_device": "..."}}]}
```

From your own browser: log in to https://muse.ai, `F12` → **Application** → **Cookies** → `muse.ai`, copy the three values, restart. Cookies expire — symptoms are empty replies, `503`, or a login page in driver logs. Fix: new cookie, rewrite file, restart.

## 5. Verify

```powershell
(Invoke-WebRequest http://127.0.0.1:20233/healthz).Content
$body = '{"model":"muse-chat","messages":[{"role":"user","content":"ping"}]}'
Invoke-RestMethod -Uri http://127.0.0.1:20233/v1/chat/completions -Method Post -ContentType 'application/json' -Body $body
```

## 6. Connect to opencode

Add to `C:\Users\NABIL\.config\opencode\opencode.json`:

```json
"provider": {"muse-opencode": {
  "npm": "@ai-sdk/openai-compatible", "name": "Muse OpenCode",
  "options": {"baseURL": "http://127.0.0.1:20233/v1", "apiKey": "dummy"},
  "models": {"muse-chat": {"name": "Muse chat"}}}}
```

`apiKey` is ignored (`api/deps.py` is a no-op; loopback is the real control). Do **not** set opencode's `small_model` to this provider — title generation adds 25s+ per conversation and hijacks the browser tab.

## 7. Config (env vars, prefix `MUSE2API_*`, or `.env`)

| Variable | Default | Note |
|---|---|---|
| `MUSE2API_HOST` | `127.0.0.1` | Do not change |
| `MUSE2API_PORT` | `20233` | Relay port |
| `MUSE2API_LOG_LEVEL` | `INFO` | `DEBUG` shows CDP steps |
| `MUSE2API_DRIVER` | `browser` | `browser` / `mock` / `http` |
| `MUSE2API_CDP_PORT` | `19211` | DevTools port |
| `MUSE2API_HEADLESS` | `true` | `false` to watch the browser |
| `MUSE2API_CHAT_TIMEOUT` | `300.0` | Seconds per chat |
| `MUSE2API_ACCOUNT_MAX_CONCURRENCY` | `1` | Keep at 1 — one tab |

## 8. Rules and scope

- **Never commit or push without explicit instruction.**
- `session.json` is a live credential — gitignored; never `git add -f`, never log its contents.
- Do not rename the `museai` package or import paths; branding changes are labels only.
- Do not "fix" `message_turns()` keeping `system`/`developer` turns — only `flatten_messages()` drops them, and history matching depends on it.
- No retry in the prompt-send path (`_send()`) — it double-sends and burns quota. Retry only in idempotent layers (CDP reconnect, reload, `_state()`).
- Never kill Chrome globally — pattern-match the command line (port `19211` or the relay's `--user-data-dir`).
- Bind stays loopback; `api/deps.py` auth is a no-op by design.
- **In scope, just do it:** install/setup, `session.json`, `start.ps1`, driver/DOM debugging, prompt parsing, refactors, bug fixes, performance, tests, docs, profiling.
- **Out of scope, decline calmly:** binding to `0.0.0.0` or exposing the relay publicly, sharing `session.json`, multi-user service, retry in the prompt-send path.

## 9. Known quirks (do not re-discover)

- `chromium.py:25-28` Windows path double-escaping — works, untidy.
- `accounts/store.py` duplicated classes; `drivers/http/driver.py` unused stub; `models.py:57-62` silent fallback, intentional.
- No `tests/` despite `pyproject.toml` `testpaths`; `drivers/browser/dom.py` is a **file**, not a directory.
- Manual regression scripts: `cdp_check.py`, `media_check.py`, `media_cap_check.py`, `img_test.py`, `persist_test.py`.

Built for **education and personal learning** — OpenAI-compatible relay design, CDP browser automation, local tool integration. Not official, not affiliated with muse.ai. Requests come from the operator's own account; upstream rate limits still apply and account risk is the operator's. Not for commercial use, not for sharing access. **For Educational Purposes Only.**
