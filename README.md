# muse-opencode

<p align="center">
  <img src="docs/pahlawan.jpeg" alt="Pahlawan datang" width="220">
</p>

A local, OpenAI-compatible HTTP relay that drives **your own muse.ai web chat** through a real Chromium tab over the Chrome DevTools Protocol. It exposes `/v1/chat/completions`, `/v1/models`, `/v1/images/generations`, `/v1/videos`, and a small admin API — so any OpenAI client (opencode, the OpenAI SDK, LangChain, plain `curl`) can talk to muse.ai without an official API key.

> **For Educational Purposes Only.** See [Disclaimer](#14-disclaimer).

---

## Table of contents

1. [What this is](#1-what-this-is)
2. [What this is not](#2-what-this-is-not)
3. [Requirements](#3-requirements)
4. [Quick start](#4-quick-start)
5. [Manual install](#5-manual-install)
6. [`session.json`](#6-sessionjson)
7. [Verify the relay](#7-verify-the-relay)
8. [Connect opencode](#8-connect-opencode)
9. [Connect the OpenAI SDK / curl](#9-connect-the-openai-sdk--curl)
10. [API reference](#10-api-reference)
11. [Architecture](#11-architecture)
12. [Configuration](#12-configuration)
13. [Account pool](#13-account-pool)
14. [Latency, honestly](#14-latency-honestly)
15. [Troubleshooting](#15-troubleshooting)
16. [Known quirks](#16-known-quirks)
17. [Security model](#17-security-model)
18. [Disclaimer](#18-disclaimer)

---

## 1. What this is

- A **relay**, not a scraper library. It runs a FastAPI server on `127.0.0.1` and translates OpenAI request shapes into real browser interactions.
- **Cookie-based.** Authentication is the `hatch_sess` / `hatch_gw` / `hatch_native_auth_device` cookies from a normal muse.ai login, stored in `session.json`.
- **Browser-driven.** A Chromium instance is launched (or attached to) with remote debugging enabled. Prompts are typed into the composer, sent, and the assistant's reply bubbles are polled and streamed back as SSE.
- **Multi-account capable.** `session.json` can hold several accounts; the pool handles rotation, cooldowns, and failover.
- **Media capable.** Image generation, image edits (not implemented upstream), and video tasks are routed through the same browser session.

### How a chat request flows

```
client → POST /v1/chat/completions
       → gateway.py        (pick account, resolve model, build prompt)
       → prompt.py         (flatten OpenAI messages into one text block)
       → driver.py         (attach CDP → open/reuse thread → type → send)
       → muse.ai web chat  (upstream generation — the slow part)
       → DOM polling       (read bubbles, detect completion)
       → SSE chunks back to client
```

---

## 2. What this is not

- Not an official muse.ai product, SDK, or API. muse.ai has no public API; this wraps the web UI.
- Not a way to bypass authentication. It reuses a legitimate login cookie you already own.
- Not a public or multi-user service. It binds `127.0.0.1` only, and the auth dependency is deliberately a no-op.
- Not a scraper that fights the UI. It types like a human and reads the rendered DOM.
- Not fast. The upstream model does the work; this relay adds a few seconds of overhead on top.

---

## 3. Requirements

| Requirement | Notes |
|---|---|
| **Windows 10/11** | Only tested OS. PowerShell 5.1+ or 7+. |
| **Python 3.10+** | 3.11/3.12 recommended. |
| **Chrome or Edge** | Auto-detected by `drivers/browser/chromium.py`. Override with `MUSE2API_CHROMIUM_PATH`. |
| **muse.ai account** | Must have webchat access. |
| **~200 MB disk** | venv + browser profile + `data/` media cache. |

**Not required:** Docker, Node.js, Redis, Postgres, any database. All state is local JSON under `data/`.

---

## 4. Quick start

```powershell
Set-Location D:\project\muse-opencode
.\start.ps1
```

`start.ps1` does the following, in order:

1. `Set-Location` to its own directory.
2. Sets `PYTHONPATH` to `src` (the package is **not** pip-installed).
3. Creates `.venv` and installs dependencies **if `.venv` is missing**.
4. Warns if `session.json` is missing.
5. Frees port `20233` from any stale listener.
6. Runs `python -m museai`.

Expected output:

```
muse-opencode -> http://127.0.0.1:20233/v1  (model: muse-chat)
INFO:     Started server process [12345]
INFO:     Uvicorn running on http://127.0.0.1:20233 (Press CTRL+C to quit)
```

The first chat request will launch Chromium (headless by default) and may take 20–40 seconds. Subsequent requests reuse a warm page.

---

## 5. Manual install

The repo is **not** installable via `pip install museai`. `pyproject.toml` exists for metadata and tooling only; the code runs from `src` via `PYTHONPATH`.

```powershell
Set-Location D:\project\muse-opencode

python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install fastapi "uvicorn[standard]" pydantic pydantic-settings "httpx[socks]" websockets

$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m museai
```

### Dependencies, and what each is for

| Package | Used for |
|---|---|
| `fastapi` | HTTP routing, request validation, SSE. |
| `uvicorn[standard]` | ASGI server. |
| `pydantic` | Request/response schemas. |
| `pydantic-settings` | `MUSE2API_*` env + `.env` loading. |
| `httpx[socks]` | Session renewal calls (with SOCKS proxy support). |
| `websockets` | Raw CDP WebSocket transport. |

### Optional: run it as a background process

```powershell
Start-Process -FilePath ".\.venv\Scripts\python.exe" `
  -ArgumentList "-m","museai" `
  -WorkingDirectory "D:\project\muse-opencode" `
  -RedirectStandardOutput "D:\temp\opencode\relay.log" `
  -RedirectStandardError  "D:\temp\opencode\relay.err" `
  -WindowStyle Hidden
```

To stop it without killing your normal browser, match on the command line:

```powershell
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -like "*-m museai*" } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

---

## 6. `session.json`

This file is **required**. Without it, `/v1/chat/completions` returns `503`.

Create `session.json` in the repo root:

```json
{
  "accounts": [
    {
      "label": "local",
      "cookies": {
        "hatch_sess": "eyJhbGciOi...",
        "hatch_gw": "...",
        "hatch_native_auth_device": "..."
      }
    }
  ]
}
```

### How to get the cookie values

1. Open Chrome and log in to <https://muse.ai>.
2. Press `F12` → **Application** tab → **Storage** → **Cookies** → `https://muse.ai`.
3. Copy the values of `hatch_sess`, `hatch_gw`, and `hatch_native_auth_device`.
4. Paste them into `session.json`.
5. Restart the relay.

### Multiple accounts

Add more objects to the `accounts` array. Give each a unique `label`:

```json
{
  "accounts": [
    { "label": "main",  "cookies": { "hatch_sess": "...", "hatch_gw": "...", "hatch_native_auth_device": "..." } },
    { "label": "alt",   "cookies": { "hatch_sess": "...", "hatch_gw": "...", "hatch_native_auth_device": "..." } }
  ]
}
```

### Cookie expiry

Cookies expire. Symptoms:

- Replies come back empty or truncated.
- `/v1/chat/completions` returns `503`.
- Driver logs show a login page instead of the composer.

Fix: grab fresh cookie values, rewrite `session.json`, restart. `MUSE2API_KEEPALIVE_ENABLED=true` can renew sessions automatically, but it is off by default and imperfect.

> `session.json` is a **live credential**. It is gitignored. Never `git add -f` it, never paste its contents into a log, an issue, or a chat.

---

## 7. Verify the relay

```powershell
# health
(Invoke-WebRequest http://127.0.0.1:20233/healthz).Content
# → {"ok":true,"version":"0.1.0"}

# models
(Invoke-WebRequest http://127.0.0.1:20233/v1/models).Content

# a real chat
$body = '{"model":"muse-chat","messages":[{"role":"user","content":"Say hello in five words."}]}'
Invoke-RestMethod -Uri http://127.0.0.1:20233/v1/chat/completions `
  -Method Post -ContentType 'application/json' -Body $body
```

```powershell
# admin: account state
Invoke-RestMethod http://127.0.0.1:20233/admin/accounts

# admin: driver + pool status
Invoke-RestMethod http://127.0.0.1:20233/admin/status
```

---

## 8. Connect opencode

Add a provider to `C:\Users\<you>\.config\opencode\opencode.json`:

```json
{
  "provider": {
    "muse-opencode": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Muse OpenCode",
      "options": {
        "baseURL": "http://127.0.0.1:20233/v1",
        "apiKey": "dummy"
      },
      "models": {
        "muse-chat": { "name": "Muse chat" }
      }
    }
  }
}
```

Then select `muse-opencode/muse-chat` as your model.

**Two important notes:**

- `apiKey` is ignored. `api/deps.py` returns `None` unconditionally — loopback binding is the real access control.
- **Do not** point opencode's `small_model` at this provider. Title generation fires an extra chat request per conversation, which costs 25+ seconds and hijacks the browser tab mid-work.

---

## 9. Connect the OpenAI SDK / curl

### curl

```powershell
$body = '{"model":"muse-chat","messages":[{"role":"user","content":"Explain CDP in one sentence."}]}'
curl.exe -s -X POST http://127.0.0.1:20233/v1/chat/completions `
  -H "Content-Type: application/json" `
  --data-binary $body
```

For large payloads, write the JSON to a file and use `--data-binary "@file.json"` to avoid shell quoting issues.

### Streaming

```powershell
$body = '{"model":"muse-chat","messages":[{"role":"user","content":"Count to five."}],"stream":true}'
curl.exe -N -X POST http://127.0.0.1:20233/v1/chat/completions `
  -H "Content-Type: application/json" `
  --data-binary $body
```

### Python (OpenAI SDK)

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:20233/v1", api_key="dummy")

resp = client.chat.completions.create(
    model="muse-chat",
    messages=[{"role": "user", "content": "Say hello in five words."}],
)
print(resp.choices[0].message.content)
```

---

## 10. API reference

### OpenAI-compatible

| Method | Path | Notes |
|---|---|---|
| `POST` | `/v1/chat/completions` | `stream` supported. Only `user` turns are forwarded. |
| `GET` | `/v1/models` | Returns `muse-chat` and `muse-image`. |
| `POST` | `/v1/images/generations` | `n` bounded `1..4`. |
| `POST` | `/v1/images/edits` | Returns `FeatureNotImplemented`. |
| `POST` | `/v1/videos` | Creates a background video task. |
| `GET` | `/v1/videos/{task_id}` | Poll task state. |
| `GET` | `/v1/media/{name}` | Serve cached media bytes. |
| `POST` | `/v1/responses` | Stub; not implemented. |

### Admin

| Method | Path | Notes |
|---|---|---|
| `GET` | `/admin/status` | Version, driver, capabilities, pool snapshot. |
| `GET` | `/admin/accounts` | Returns `{"data": [...]}` — parse `.data`. |
| `POST` | `/admin/accounts` | Add an account. |
| `PATCH` | `/admin/accounts/{id}` | Update label / cookies / state. |
| `DELETE` | `/admin/accounts/{id}` | Remove an account. |
| `POST` | `/admin/accounts/{id}/reset` | Clear failures and cooldown. |
| `POST` | `/admin/accounts/{id}/renew` | Attempt session renewal. |
| `GET` | `/admin/tasks` | List media/video tasks. |
| `POST` | `/admin/tasks/{task_id}/cancel` | Cancel a running task. |

### Health

| Method | Path | Notes |
|---|---|---|
| `GET` | `/healthz` | `{"ok":true,"version":"0.1.0"}` |

---

## 11. Architecture

```
muse-opencode/
├── start.ps1                      launcher: venv, PYTHONPATH, port cleanup
├── pyproject.toml                 metadata + tooling only (not pip-installed)
├── session.json                   YOUR cookies — gitignored, required
├── data/                          runtime state (auto-created)
│   ├── accounts.json              pool state
│   ├── tasks.json                 media/video task records
│   ├── api_key                    generated key (unused on loopback)
│   ├── media/                     cached images and videos
│   └── browser-profile/           Chromium user-data-dir
└── src/museai/
    ├── __main__.py                entrypoint: `python -m museai`
    ├── app.py                     FastAPI app assembly
    ├── config.py                  Settings — all MUSE2API_* vars
    ├── errors.py                  typed exceptions → HTTP status
    ├── log.py                     logging setup
    ├── api/
    │   ├── deps.py                auth deps (deliberate no-ops on loopback)
    │   ├── schemas.py             request/response models
    │   └── routes/
    │       ├── chat.py            /v1/chat/completions
    │       ├── models.py          /v1/models
    │       ├── images.py          /v1/images/*
    │       ├── videos.py          /v1/videos*
    │       ├── media.py           /v1/media/{name}
    │       ├── responses.py       /v1/responses (stub)
    │       ├── admin.py           /admin/*
    │       └── health.py          /healthz
    ├── core/
    │   ├── prompt.py              flatten_messages(), message_turns(), strip_harness_noise()
    │   ├── media.py               media caching + URL building
    │   └── models.py              model registry and availability
    ├── drivers/
    │   ├── base.py                Driver protocol
    │   ├── registry.py            driver name → class
    │   ├── mock.py                offline driver for tests
    │   ├── http/driver.py         unused stub
    │   └── browser/
    │       ├── chromium.py        browser discovery + launch
    │       ├── cdp.py             CDP WebSocket client
    │       ├── dom.py             DOM selectors and bubble parsing (a FILE)
    │       └── driver.py          the real driver: type, send, poll, stream
    ├── accounts/
    │   ├── model.py               Account dataclass + is_available()
    │   ├── pool.py                acquire(), cooldowns, failover
    │   ├── store.py               load/save accounts.json
    │   └── keepalive.py           optional session renewal loop
    ├── services/
    │   ├── container.py           dependency container
    │   ├── gateway.py             request orchestration + retry policy
    │   └── tasks.py               background media/video tasks
    └── upstream/
        └── muse.py                muse.ai endpoint constants
```

### Key design decisions

- **Prompt flattening.** OpenAI messages are flattened into a single text block. With one `user` turn, the text is sent verbatim. With two or more, each turn becomes `[Role]\ntext` and a fixed instruction block is appended. `system` and `developer` turns are **dropped** — muse.ai's chat UI has no equivalent channel.
- **Hot page reuse.** The driver keeps the last successful thread URL. If the next request's history matches, it types only the new delta instead of starting a new thread. This is what makes multi-turn conversations fast.
- **No retry in `_send()`.** Retrying a prompt send double-sends and burns quota. Retries live only in idempotent layers: CDP reconnect, page reload, state polling.
- **One tab at a time.** `account_max_concurrency` defaults to `1` because the browser is a single resource. Real throttling happens here, not at the HTTP layer.

---

## 12. Configuration

All settings come from environment variables prefixed `MUSE2API_`, or from a `.env` file in the repo root. Source of truth: `src/museai/config.py`.

### Server

| Variable | Default | Description |
|---|---|---|
| `MUSE2API_HOST` | `127.0.0.1` | Bind address. Do not change. |
| `MUSE2API_PORT` | `20233` | Relay port. |
| `MUSE2API_LOG_LEVEL` | `INFO` | `DEBUG` logs every CDP step. |
| `MUSE2API_PUBLIC_BASE` | `""` | External base URL for media links. Empty = derive from request. |
| `MUSE2API_DATA_DIR` | `data` | Runtime state directory. |

### Auth

| Variable | Default | Description |
|---|---|---|
| `MUSE2API_API_KEY` | `""` | Intended bearer key for `/v1/*`. Unused — `deps.py` is a no-op. |
| `MUSE2API_ADMIN_KEY` | `""` | Intended bearer key for `/admin/*`. Unused. |

### Driver

| Variable | Default | Description |
|---|---|---|
| `MUSE2API_DRIVER` | `browser` | `browser`, `mock`, or `http`. |
| `MUSE2API_SITE_URL` | `https://muse.ai` | Upstream base URL. |
| `MUSE2API_CHROMIUM_PATH` | `""` | Explicit browser binary. Empty = auto-detect. |
| `MUSE2API_CDP_PORT` | `19211` | Chrome DevTools Protocol port. |
| `MUSE2API_HEADLESS` | `true` | `false` to watch the browser work. |
| `MUSE2API_BROWSER_PROXY` | `""` | Proxy for the browser only, e.g. `socks5://127.0.0.1:10808`. |
| `MUSE2API_BROWSER_PROFILE_DIR` | `None` | Custom Chromium profile dir. Default `data/browser-profile`. |
| `MUSE2API_PAGE_READY_TIMEOUT` | `45.0` | Seconds to wait for the composer. |

### Timeouts (seconds)

| Variable | Default | Description |
|---|---|---|
| `MUSE2API_CHAT_TIMEOUT` | `300.0` | Total budget per chat request. |
| `MUSE2API_FIRST_TOKEN_TIMEOUT` | `45.0` | Deadline before the first token appears. |
| `MUSE2API_IMAGE_TIMEOUT` | `240.0` | Per image generation. |
| `MUSE2API_VIDEO_TIMEOUT` | `600.0` | Per video task. |

### Account pool

| Variable | Default | Description |
|---|---|---|
| `MUSE2API_POOL_STRATEGY` | `affinity` | `affinity`, `lru`, or `round_robin`. |
| `MUSE2API_POOL_ACQUIRE_TIMEOUT` | `60.0` | Max wait for a free account. |
| `MUSE2API_ACCOUNT_MAX_CONCURRENCY` | `1` | Concurrent chats per account. Keep at `1`. |
| `MUSE2API_ACCOUNT_COOLDOWN` | `120.0` | Seconds an account rests after a failure. |
| `MUSE2API_MAX_FAILOVER` | `2` | Retries across other accounts on failure. |

### Keepalive

| Variable | Default | Description |
|---|---|---|
| `MUSE2API_KEEPALIVE_ENABLED` | `false` | Background session renewal. |
| `MUSE2API_KEEPALIVE_INTERVAL` | `21600` | Renewal interval in seconds (6 h). |

### Example `.env`

```dotenv
MUSE2API_LOG_LEVEL=INFO
MUSE2API_HEADLESS=true
MUSE2API_CHAT_TIMEOUT=300
MUSE2API_ACCOUNT_MAX_CONCURRENCY=1
MUSE2API_POOL_STRATEGY=affinity
```

---

## 13. Account pool

The pool decides which account serves a request and when an account rests.

| Strategy | Behaviour |
|---|---|
| `affinity` | Prefers the account that served the current hot page, so the browser tab is reused. Default and fastest. |
| `lru` | Least-recently-used among available accounts. |
| `round_robin` | Rotates in order. |

### States

| State | Meaning |
|---|---|
| `ACTIVE` | Ready to serve. |
| `COOLING` | Failed recently; resting until `cooldown_until`. |
| `DISABLED` | Manually disabled via admin API. |

### Cooldown rules

- A failure sets `COOLING` for `ACCOUNT_COOLDOWN` seconds.
- An `UpstreamTimeout` does **not** trigger cooldown — a slow model is not a broken account. It only increments the failure counter.
- Once the cooldown timestamp passes, `is_available()` heals the account back to `ACTIVE`.
- `acquire()` waits up to `POOL_ACQUIRE_TIMEOUT`, capped at the soonest recovery time, so a cooling account that recovers mid-wait becomes usable instead of invisible.
- If the pool holds a single account, failover is skipped and the real upstream error surfaces (`504`), rather than a misleading `503 no usable account`.

### Admin shortcuts

```powershell
# see every account and its state
Invoke-RestMethod http://127.0.0.1:20233/admin/accounts

# clear failures + cooldown on one account
Invoke-RestMethod -Method Post http://127.0.0.1:20233/admin/accounts/0/reset

# try to renew a session
Invoke-RestMethod -Method Post http://127.0.0.1:20233/admin/accounts/0/renew
```

---

## 14. Latency, honestly

Measured on a warm page, single account, headless Chromium:

| Stage | Typical | Notes |
|---|---|---|
| Relay overhead before send | 2.8–4.8 s | Attach, thread lookup, prompt build. |
| First token | 20–38 s | **Upstream muse.ai generation.** Not relay cost. |
| Full non-stream reply | 28–50 s | Dominated by upstream. |
| Polling loop | ~14 ms/poll | Negligible. |
| Hot-page reuse saving | ~5–6 s | Compared to opening a new thread. |

**Reality:** roughly 24 seconds of every request is the upstream model thinking. The relay's controllable overhead is about 5–6 seconds, and hot-page reuse is the single biggest win available. There is no configuration that makes muse.ai generate faster.

If you need sub-second responses, this relay is the wrong tool.

---

## 15. Troubleshooting

### `503 no usable account in pool`

| Cause | Fix |
|---|---|
| `session.json` missing or empty | Create it — see [§6](#6-sessionjson). |
| All cookies expired | Refresh cookie values, restart. |
| Every account is `COOLING` | Wait out `ACCOUNT_COOLDOWN`, or `POST /admin/accounts/{id}/reset`. |
| Single account timed out | Real upstream timeout — check `/admin/status`, retry. |

### `500 Internal Server Error`

The relay raised an exception. Check `relay.err` first — never guess.

```powershell
Get-Content D:\temp\opencode\relay.err -Tail 40
```

Common causes: stale code in a long-running process (restart), a driver `AttributeError` from an in-flight edit, or a malformed request body.

### Empty or truncated replies

Usually cookie expiry. Confirm with:

```powershell
Invoke-RestMethod http://127.0.0.1:20233/admin/status
```

If the driver reports a login page, refresh `session.json`.

### Browser tab hijacked mid-work

Something is firing extra requests — most often opencode's `small_model` title generation. Remove this provider from `small_model`.

### Port `20233` already in use

```powershell
Get-NetTCPConnection -LocalPort 20233 -State Listen |
  Select-Object -ExpandProperty OwningProcess -Unique |
  ForEach-Object { Stop-Process -Id $_ -Force }
```

### Relay is running but Chrome is not

Check the CDP port:

```powershell
(Invoke-WebRequest http://127.0.0.1:19211/json/version).Content
```

If empty, the browser died. Restart the relay — it will relaunch.

### Never kill Chrome globally

Your normal browsing session shares the process name. Always pattern-match:

```powershell
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -like "*remote-debugging-port=19211*" -or $_.CommandLine -like "*-m museai*" } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

---

## 16. Known quirks

Documented so nobody re-discovers them as "bugs":

- `drivers/browser/chromium.py:25-28` — Windows path double-escaping. Works, but untidy.
- `accounts/store.py` — duplicated class definitions. Harmless, worth consolidating.
- `drivers/http/driver.py` — unused stub. Kept for the driver registry shape.
- `core/models.py:57-62` — silent model fallback. Intentional; an unknown model degrades to `muse-chat` instead of erroring.
- `drivers/browser/dom.py` is a **file**, not a directory.
- No `tests/` directory despite `pyproject.toml` declaring `testpaths`. Verification is done with manual scripts.
- `flatten_messages()` appends a fixed `[Instruction]` block whenever there is more than one turn. Expected behaviour, not duplication.
- `message_turns()` intentionally keeps `system` and `developer` turns while `flatten_messages()` drops them. History matching depends on this asymmetry — do not "fix" it.

### Manual regression scripts

The repo has no `tests/` directory. Verification is done with standalone scripts kept **outside** the repo (this project uses `D:\temp\opencode`). Run them after touching the driver or prompt layer:

```powershell
$env:PYTHONPATH = "D:\project\muse-opencode\src"
Set-Location D:\temp\opencode

D:\project\muse-opencode\.venv\Scripts\python.exe cdp_check.py         # CDP connectivity
D:\project\muse-opencode\.venv\Scripts\python.exe media_check.py       # media serving
D:\project\muse-opencode\.venv\Scripts\python.exe media_cap_check.py   # image n bounds
D:\project\muse-opencode\.venv\Scripts\python.exe img_test.py          # image generation
D:\project\muse-opencode\.venv\Scripts\python.exe persist_test.py      # state persistence
```

They expect the relay to already be running on `127.0.0.1:20233`.

---

## 17. Security model

This is a **local developer tool**, and the security model is built around that assumption.

| Control | Implementation |
|---|---|
| Network exposure | Binds `127.0.0.1` only. No `0.0.0.0`, ever. |
| Authentication | Deliberately absent. `api/deps.py` returns `None` — loopback is the boundary. |
| Credentials at rest | `session.json`, gitignored, plaintext. Protect it like a password. |
| Credentials in transit | Never leave the machine. Cookies go to muse.ai over TLS. |
| Browser isolation | Dedicated Chromium profile under `data/browser-profile`. |
| Logging | Never logs cookie values. `DEBUG` logs CDP steps, not secrets. |

**Do not** expose this relay to a network, tunnel it publicly, or share `session.json`. If you need remote access, use an SSH tunnel to loopback — never a public bind.

---

## 18. Disclaimer

This project is built for **education and personal learning**: OpenAI-compatible relay design, Chrome DevTools Protocol automation, prompt translation, and local tool integration.

- Not official. Not affiliated with, endorsed by, or supported by muse.ai.
- All requests originate from the operator's own account using the operator's own login cookie. No authentication is bypassed.
- Upstream rate limits and terms of service still apply. Account risk is entirely the operator's.
- Not for commercial use. Not for resale. Not for providing access to third parties.
- No warranty. No support. Use at your own risk.

**For Educational Purposes Only.**
