# Conduit

Use your AI subscriptions like an API.

Conduit is a local proxy that lets API-first AI coding tools talk to subscription-backed model auth. It was built first for Cursor's Agent harness and ChatGPT/Codex subscription auth, then expanded to support Anthropic-native Claude routing. It handles streaming responses, tool calls, image inputs, prompt-cache visibility, and Cursor-readable usage reporting.

This is local-first infrastructure. Your tool talks to Conduit. Conduit talks to the upstream subscription-backed service using your local OAuth state. You keep the keys, tokens, logs, and config on your machine.

## What Works

- Cursor Agent requests through the OpenAI-compatible `/codex` endpoint
- Anthropic-native clients through the `/anthropic` or `/claude` endpoint
- Chat Completions-style streaming responses
- Native Anthropic Messages streaming pass-through
- Streaming tool calls and tool result continuation
- Chat image inputs mapped to Responses image input parts
- Prompt cache keys and cache-hit usage reporting
- Cursor model picker entries for custom model/effort presets
- Fusion-style compound aliases with private panel/judge calls
- Direct ChatGPT/Codex OAuth login through Conduit
- Direct Claude/Anthropic OAuth login through Conduit
- Browser OAuth and device-code OAuth
- Cloudflare Quick Tunnel helper
- User-scoped config in `~/.conduit`
- Windows and Linux-friendly CLI workflows

## Install

From a local checkout:

```powershell
cd C:\Dev\copperfin-conduit
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

The CLI executable is:

```powershell
.\.venv\Scripts\conduit.exe --help
```

On Linux or macOS:

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -e .
./.venv/bin/conduit --help
```

The package name is `copperfin-conduit`; the executable is `conduit`.

## First Run

Create the user config directory:

```powershell
conduit init
```

Conduit stores durable local state in:

```text
~/.conduit
```

That means:

```text
Windows: C:\Users\<you>\.conduit
Linux:   /home/<you>/.conduit
macOS:   /Users/<you>/.conduit
```

Important files:

```text
~/.conduit/.env                 Local proxy configuration
~/.conduit/auth.json            ChatGPT/Codex OAuth token state
~/.conduit/anthropic_auth.json  Claude/Anthropic OAuth token state
~/.conduit/logs                 Proxy logs
~/.conduit/run                  Background process metadata
~/.conduit/tools                Managed helper binaries, such as cloudflared
```

## Authenticate

ChatGPT/Codex browser login:

```powershell
conduit auth login --provider codex
```

ChatGPT/Codex headless device-code login:

```powershell
conduit auth login --provider codex --method device
```

Device login prints a verification URL and user code, then waits for auth to succeed. Press `Esc` to cancel. `Ctrl+C` also works because terminals remain terminals, regrettably.

Claude browser login:

```powershell
conduit auth login --provider anthropic
```

Anthropic OAuth uses a local callback at `http://localhost:53692/callback`, following the same Claude Pro/Max OAuth shape used by Pi Mono. If the browser does not open, rerun with `--no-browser` and open the printed URL manually.

Check status:

```powershell
conduit auth status --provider codex
conduit auth status --provider anthropic
```

Refresh the stored token:

```powershell
conduit auth refresh --provider codex
conduit auth refresh --provider anthropic
```

Log out:

```powershell
conduit auth logout --provider codex
conduit auth logout --provider anthropic
```

If you already have a working Codex CLI login and want to migrate it:

```powershell
conduit auth import-codex
```

That copies `~/.codex/auth.json` into `~/.conduit/auth.json`.

## Start The Proxy

Foreground:

```powershell
conduit start --foreground --port 20129
```

Background:

```powershell
conduit start --background --port 20129
```

Stop a background instance:

```powershell
conduit stop --port 20129
```

Check the setup:

```powershell
conduit doctor
```

Run smoke tests:

```powershell
conduit smoke --root-url http://127.0.0.1:20129
```

Run the prompt-cache probe too:

```powershell
conduit smoke --root-url http://127.0.0.1:20129 --cache-probe
```

## Cursor Setup

Cursor's OpenAI-compatible settings need a public HTTPS URL. For quick testing, start a Cloudflare Quick Tunnel:

```powershell
conduit tunnel --port 20129 --install-cloudflared
```

Use the generated tunnel URL with `/codex` appended for Codex/OpenAI-compatible Cursor traffic:

```text
OpenAI API Key:       <SERVICE_API_KEY from conduit init>
Override Base URL:    https://your-tunnel.trycloudflare.com/codex
```

For Cursor, route Claude aliases through that same OpenAI override. Cursor's current Anthropic settings expose an API key field, not a custom Anthropic base URL field, so putting a real Anthropic key there bypasses Conduit. Leave Cursor's Anthropic key disabled if you want Claude traffic to go through Conduit.

The `/anthropic` and `/claude` endpoints still exist for Anthropic-compatible clients that can set a custom base URL.

You can find the key again with:

```powershell
conduit init
```

or in:

```text
~/.conduit/.env
```

Then add or enable Conduit's model IDs in Cursor's model picker.

## Model Profiles

Conduit exposes short Cursor-friendly preset model IDs by default.

Codex profiles:

```text
cp-gpt55-fast      -> gpt-5.5, low effort, priority tier
cp-gpt55-balanced  -> gpt-5.5, medium effort
cp-gpt55-high      -> gpt-5.5, high effort
cp-gpt55-xhigh     -> gpt-5.5, xhigh effort
cp-gpt55-xfast     -> gpt-5.5, xhigh effort, priority tier
```

They are configured in `~/.conduit/.env`:

```text
CODEX_MODEL_PROFILES=cp-gpt55-fast:gpt-5.5:low:priority,cp-gpt55-balanced:gpt-5.5:medium,cp-gpt55-high:gpt-5.5:high,cp-gpt55-xhigh:gpt-5.5:xhigh,cp-gpt55-xfast:gpt-5.5:xhigh:priority
```

Format:

```text
alias:upstream_model:reasoning_effort[:service_tier]
```

Supported reasoning efforts:

```text
none, minimal, low, medium, high, xhigh
```

Claude profiles:

```text
cp-opus48-high   -> claude-opus-4-8, high effort, 32k output cap
cp-opus48-xhigh  -> claude-opus-4-8, xhigh effort, 64k output cap
cp-opus48-ultra  -> claude-opus-4-8, xhigh effort, 64k output cap
cp-opus48-max    -> claude-opus-4-8, max effort, 64k output cap
cp-opus48-xfast  -> claude-opus-4-8, xhigh effort, 64k output cap, fast mode
```

They are configured in `~/.conduit/.env`:

```text
ANTHROPIC_MODEL_PROFILES=cp-opus48-high:claude-opus-4-8:high:32768,cp-opus48-xhigh:claude-opus-4-8:xhigh:65536,cp-opus48-ultra:claude-opus-4-8:xhigh:65536,cp-opus48-max:claude-opus-4-8:max:65536,cp-opus48-xfast:claude-opus-4-8:xhigh:65536:fast
```

Format:

```text
alias:upstream_model:effort[:max_tokens][:speed]
```

Supported Claude efforts:

```text
low, medium, high, xhigh, max, off
```

Anthropic documents `ultracode` as a Claude Code orchestration mode, not a separate API effort level. Conduit maps `cp-opus48-ultra` to Opus 4.8 `xhigh` because that is the actual API value.

Fast mode maps to `speed: "fast"` and the `fast-mode-2026-02-01` beta header. Anthropic currently describes it as research preview access for supported Opus models, so expect an upstream error if your account does not have access.

Fusion profiles:

```text
cp-fusion55       -> private GPT-5.5 + Opus panel, GPT-5.5 xfast final
cp-fusion55-fast  -> smaller private GPT-5.5 + Opus panel, GPT-5.5 fast final
```

They are configured in `~/.conduit/.env`:

```text
FUSION_MODEL_PROFILES=cp-fusion55:cp-gpt55-xfast:cp-gpt55-high|cp-opus48-xhigh:cp-gpt55-balanced,cp-fusion55-fast:cp-gpt55-fast:cp-gpt55-balanced|cp-opus48-high
```

Format:

```text
alias:primary_model:panel_model_1|panel_model_2[:judge_model]
```

Fusion runs private text-only panel calls, optionally runs a judge call, then injects the synthesis as advisory system context before streaming the final primary model response back to Cursor. Tools stay on the final Cursor-facing turn; private panel calls do not execute tools.

Fusion is in-process proxy orchestration, not a CLI shim. Conduit uses Python worker threads for private panel calls and direct provider HTTP calls for Codex/Claude. It does not shell out to `codex`, Claude Code, Pi, or any other agent runtime per request.

The default Fusion profiles use Claude panel models. Keep `ENABLE_ANTHROPIC=true` and authenticate Claude with `conduit auth login --provider anthropic` if you use those defaults.

List models from a running proxy:

```powershell
conduit models --root-url http://127.0.0.1:20129/codex
conduit models --root-url http://127.0.0.1:20129/anthropic
```

## Service Install

Linux uses a user-level systemd service:

```bash
conduit service install --port 20129
systemctl --user status conduit.service
```

Windows uses Task Scheduler by default:

```powershell
conduit service install --port 20129
conduit service status
```

Why Task Scheduler instead of `sc.exe`? Because a normal Python CLI is not a native Windows Service binary. Wrapping it with `sc.exe` is how you get the classic "service did not respond" failure. Until Conduit ships a dedicated Windows service wrapper, the scheduled task is the honest no-admin startup path.

Preview actions without changing the OS:

```powershell
conduit service install --dry-run
conduit service uninstall --dry-run
```

Uninstall:

```powershell
conduit service uninstall
```

## Configuration

`conduit init` creates `~/.conduit/.env`.

Important settings:

```text
SERVICE_API_KEY          Local bearer token Cursor sends to Conduit
ENABLE_CODEX             Enables the /codex provider
CODEX_AUTH_PATH          Defaults to ~/.conduit/auth.json
CODEX_RESPONSES_URL      ChatGPT Codex backend endpoint
CODEX_SUPPORTED_MODELS   Upstream model IDs to expose
CODEX_MODEL_PROFILES     Cursor-facing model aliases
CODEX_DISCOVERY_MODE     Allows generic traffic while integrating clients
ANTHROPIC_AUTH_PATH      Defaults to ~/.conduit/anthropic_auth.json
ANTHROPIC_BASE_URL       Defaults to https://api.anthropic.com
ANTHROPIC_SUPPORTED_MODELS
ANTHROPIC_MODEL_PROFILES
ANTHROPIC_CACHE_CONTROL  auto, off, 5m, or 1h
ANTHROPIC_THINKING_DISPLAY summarized or omitted
FUSION_MODEL_PROFILES    Compound aliases exposed through /codex
FUSION_PANEL_MAX_TOKENS  Per-panel and judge output cap
FUSION_PANEL_TIMEOUT_SECONDS
```

The default generated config is Codex-first:

```text
ENABLE_AZURE=false
ENABLE_CODEX=true
```

Azure support from the original proxy code is still present, but Conduit is being developed around subscription-backed auth first.

## Usage And Cache Logs

Conduit forwards upstream usage back to Cursor in OpenAI-compatible fields:

```text
prompt_tokens
completion_tokens
total_tokens
prompt_tokens_details.cached_tokens
completion_tokens_details.reasoning_tokens
```

Proxy logs also include lines like:

```text
USAGE: input=78008 (cached=77952, 100%) output=214 (reasoning=0) total=78222
```

That lets you verify prompt caching instead of just hoping the token meter isn't committing arson.

Claude native streams log Anthropic usage separately:

```text
ANTHROPIC USAGE: model=claude-opus-4-8 input=60000 cache_read=52000 (87%) cache_write=8000 output=900 total=120900 stop=end_turn
```

The Claude route passes native Anthropic usage back to Cursor unchanged and logs cache reads/writes from `cache_read_input_tokens`, `cache_creation_input_tokens`, and the newer `cache_creation` details when present.

Fusion panel and judge calls log their own usage:

```text
FUSION USAGE: model=cp-opus48-xhigh provider=anthropic input=60000 cache_read=52000 (87%) cache_write=8000 output=900 total=120900 stop=end_turn
FUSION USAGE: model=cp-gpt55-balanced provider=codex input=137474 cache_read=133888 (97%) cache_write=0 output=319 total=137793 stop=completed
```

The final primary response still emits normal Codex or Anthropic usage chunks/logs. Background mode starts Python unbuffered and appends to `~/.conduit/logs/conduit_<port>.out.log`, so cache and Fusion lines are available while Cursor is running instead of only after process exit.

## Development

Install editable:

```powershell
.\.venv\Scripts\python.exe -m pip install -e .
```

Run focused tests:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_codex_auth_state.py tests\test_conduit_auth.py tests\test_anthropic_auth.py tests\test_conduit_cli.py tests\test_provider_routing.py tests\test_provider_model_dispatch.py tests\test_codex_settings.py tests\test_anthropic_settings.py tests\test_codex_request_adapter.py tests\test_anthropic_request_adapter.py tests\test_codex_response_adapter.py tests\test_anthropic_openai_request_adapter.py tests\test_anthropic_openai_response_adapter.py tests\test_anthropic_routes.py tests\test_anthropic_upstream.py tests\test_fusion_settings.py tests\test_fusion_adapter.py tests\test_fusion_invoker.py -q
```

Run the package CLI without relying on PATH:

```powershell
.\.venv\Scripts\python.exe -m conduit.cli doctor
```

Compatibility wrappers remain:

```powershell
scripts\start_windows_proxy.ps1
scripts\start_proxy.py
scripts\smoke_codex_proxy.py
```

They call the `conduit` package CLI. They are not the primary interface.

## Project Status

Conduit is early. The plumbing has been proven against Cursor Agent with:

- streaming text
- streaming tool calls
- file-edit tool use
- image input
- model aliases
- prompt-cache stats
- Cursor context usage reporting
- Anthropic-native Claude OAuth routing
- Claude Opus 4.8 effort profiles
- Anthropic prompt-cache and usage logging
- Fusion-style private panel/judge routing

The project is not affiliated with OpenAI, Anthropic, Cursor, Cloudflare, or the upstream projects credited below.

Use this with accounts and tools you are authorized to use. Do not ship someone else's tokens to a hosted proxy. Do not sell access to your subscription. Do not be that guy.

## Maintainer

Conduit is maintained by Copperfin Software.

- Website: [www.copperfin.io](https://www.copperfin.io)
- Contact: [contact@copperfin.io](mailto:contact@copperfin.io)

## Acknowledgements

Conduit began as a clean fork of [`gabrii/Cursor-Azure-GPT-5`](https://github.com/gabrii/Cursor-Azure-GPT-5). That project provided the original Cursor/OpenAI-compatible proxy foundation, Azure Responses routing, and a bunch of the boring-but-necessary proxy shape.

Conduit's direct OpenAI Codex OAuth implementation is ported from [`badlogic/pi-mono`](https://github.com/badlogic/pi-mono), specifically its ChatGPT/Codex browser and device-code OAuth flow. Conduit's Claude OAuth implementation is also ported from Pi Mono's Anthropic OAuth flow. We rewrote that behavior in Python for Conduit's CLI and `~/.conduit` auth state.

Both projects are credited because pretending otherwise would be bullshit.

## License

MIT. See `LICENSE`.
