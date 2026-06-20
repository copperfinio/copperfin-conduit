"""Flask adapter for Fusion-style compound model aliases."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from typing import Any

from flask import Request, Response, current_app, jsonify

from ..anthropic.adapter import AnthropicAdapter
from ..common.logging import console
from ..codex.adapter import CodexAdapter
from .invoker import FusionModelInvoker, PanelResult
from .settings import FusionModelProfile, FusionSettings

_PANEL_SYSTEM = """You are one member of a multi-model analysis panel.

Give an independent, concise assessment for the primary coding agent.
Do not call tools, do not claim to edit files, and do not address the user directly.
Focus on correctness, risks, missing context, and the best next action."""

_JUDGE_SYSTEM = """You are the judge in a multi-model analysis panel.

Compare the panel responses and return a concise structured synthesis for the primary coding agent.
Include:
- consensus
- contradictions
- gaps or risks
- strongest recommendation

Do not address the user directly."""


class FusionAdapter:
    """Run panel analysis, then forward the original request to a primary model."""

    def __init__(
        self,
        *,
        settings: FusionSettings | None = None,
        invoker: FusionModelInvoker | None = None,
    ) -> None:
        """Initialize Fusion settings and internal invoker."""
        self.settings = settings or FusionSettings()
        self.invoker = invoker or FusionModelInvoker(fusion_settings=self.settings)

    def forward(self, req: Request, provider_path: str) -> Response:
        """Handle a Fusion profile request."""
        payload = req.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": {"message": "Request body must be JSON"}}), 400
        model = str(payload.get("model") or "").strip()
        profile = self.settings.model_profiles.get(model)
        if profile is None:
            return (
                jsonify({"error": {"message": f"Unsupported Fusion model {model!r}"}}),
                400,
            )
        if not _wants_chat_completion_response(provider_path):
            return (
                jsonify(
                    {
                        "error": {
                            "message": "Fusion profiles currently support Chat Completions requests only."
                        }
                    }
                ),
                400,
            )

        downstream_headers = dict(req.headers)
        console.print(
            "[bold cyan]FUSION INBOUND:[/bold cyan] "
            f"path={provider_path} model={model!r} primary={profile.primary_model} "
            f"panel={list(profile.panel_models)} judge={profile.judge_model}"
        )

        panel_results = self._run_panel(
            payload=payload,
            profile=profile,
            downstream_headers=downstream_headers,
        )
        judge_result = self._run_judge(
            payload=payload,
            profile=profile,
            panel_results=panel_results,
            downstream_headers=downstream_headers,
        )
        final_payload = _final_payload(
            payload,
            profile=profile,
            panel_results=panel_results,
            judge_result=judge_result,
        )
        console.print(
            "[bold cyan]FUSION PRIMARY:[/bold cyan] "
            f"inbound_model={model} primary_model={profile.primary_model} "
            f"panel_ok={sum(1 for result in panel_results if result.ok)}/{len(panel_results)} "
            f"judge_ok={judge_result.ok if judge_result else None}"
        )
        return _forward_primary(
            req,
            provider_path=provider_path,
            payload=final_payload,
            invoker=self.invoker,
        )

    def _run_panel(
        self,
        *,
        payload: dict[str, Any],
        profile: FusionModelProfile,
        downstream_headers: dict[str, str],
    ) -> list[PanelResult]:
        panel_payloads = [
            _panel_payload(
                payload,
                model=model,
                max_tokens=self.settings.panel_max_tokens,
            )
            for model in profile.panel_models
        ]
        if not panel_payloads:
            return []
        app = current_app._get_current_object()
        max_workers = min(4, len(panel_payloads))
        results: list[PanelResult] = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(
                    _invoke_with_app_context,
                    app,
                    self.invoker,
                    model=str(panel_payload["model"]),
                    payload=panel_payload,
                    downstream_headers=downstream_headers,
                )
                for panel_payload in panel_payloads
            ]
            for future in as_completed(futures):
                results.append(future.result())
        return sorted(results, key=lambda result: profile.panel_models.index(result.model))

    def _run_judge(
        self,
        *,
        payload: dict[str, Any],
        profile: FusionModelProfile,
        panel_results: list[PanelResult],
        downstream_headers: dict[str, str],
    ) -> PanelResult | None:
        if not profile.judge_model:
            return None
        judge_payload = _judge_payload(
            payload,
            model=profile.judge_model,
            panel_results=panel_results,
            max_tokens=self.settings.panel_max_tokens,
        )
        return self.invoker.invoke_text(
            model=profile.judge_model,
            payload=judge_payload,
            downstream_headers=downstream_headers,
        )


def _invoke_with_app_context(
    app: Any,
    invoker: FusionModelInvoker,
    *,
    model: str,
    payload: dict[str, Any],
    downstream_headers: dict[str, str],
) -> PanelResult:
    """Run a Fusion panel invocation with Flask config available in worker threads."""
    with app.app_context():
        return invoker.invoke_text(
            model=model,
            payload=payload,
            downstream_headers=downstream_headers,
        )


def _forward_primary(
    req: Request,
    *,
    provider_path: str,
    payload: dict[str, Any],
    invoker: FusionModelInvoker,
) -> Response:
    provider = invoker.provider_for_model(str(payload.get("model") or ""))
    downstream_headers = dict(req.headers)
    if provider == "anthropic":
        return AnthropicAdapter().forward_payload(
            payload, provider_path, downstream_headers
        )
    return CodexAdapter().forward_payload(payload, provider_path, downstream_headers)


def _panel_payload(
    payload: dict[str, Any],
    *,
    model: str,
    max_tokens: int,
) -> dict[str, Any]:
    out = _text_only_chat_payload(payload)
    out["model"] = model
    _prepend_system(out, _PANEL_SYSTEM)
    _strip_tool_controls(out)
    _apply_text_limits(out, max_tokens=max_tokens)
    return out


def _judge_payload(
    payload: dict[str, Any],
    *,
    model: str,
    panel_results: list[PanelResult],
    max_tokens: int,
) -> dict[str, Any]:
    out = _text_only_chat_payload(payload)
    out["model"] = model
    out["messages"] = [
        {"role": "system", "content": _JUDGE_SYSTEM},
        {
            "role": "user",
            "content": (
                "Original request context:\n\n"
                f"{_conversation_text(payload)}\n\n"
                "Panel responses:\n\n"
                f"{_panel_results_text(panel_results)}"
            ),
        },
    ]
    _strip_tool_controls(out)
    _apply_text_limits(out, max_tokens=max_tokens)
    return out


def _final_payload(
    payload: dict[str, Any],
    *,
    profile: FusionModelProfile,
    panel_results: list[PanelResult],
    judge_result: PanelResult | None,
) -> dict[str, Any]:
    out = deepcopy(payload)
    out["model"] = profile.primary_model
    synthesis = _fusion_synthesis(panel_results, judge_result)
    _prepend_system(out, synthesis)
    return out


def _text_only_chat_payload(payload: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(payload)
    out["messages"] = _text_only_messages(payload.get("messages"))
    return out


def _text_only_messages(messages: Any) -> list[dict[str, str]]:
    if not isinstance(messages, list):
        return [{"role": "user", "content": _content_to_text(messages)}]
    out: list[dict[str, str]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        content = _content_to_text(message.get("content"))
        if role == "tool":
            role = "user"
            content = f"[Tool result {message.get('tool_call_id') or ''}]\n{content}"
        elif role not in {"system", "developer", "user", "assistant"}:
            role = "user"
        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            tool_text = "\n".join(_tool_call_text(tool_call) for tool_call in tool_calls)
            content = "\n".join(part for part in (content, tool_text) if part)
        if content:
            out.append({"role": str(role), "content": content})
    return out or [{"role": "user", "content": ""}]


def _prepend_system(payload: dict[str, Any], text: str) -> None:
    messages = payload.get("messages")
    if not isinstance(messages, list):
        payload["messages"] = [{"role": "system", "content": text}]
        return
    payload["messages"] = [{"role": "system", "content": text}, *messages]


def _strip_tool_controls(payload: dict[str, Any]) -> None:
    for key in (
        "tools",
        "tool_choice",
        "parallel_tool_calls",
        "functions",
        "function_call",
    ):
        payload.pop(key, None)


def _apply_text_limits(payload: dict[str, Any], *, max_tokens: int) -> None:
    payload["stream"] = True
    payload["max_tokens"] = max_tokens
    payload["max_completion_tokens"] = max_tokens
    payload["max_output_tokens"] = max_tokens
    payload.pop("stream_options", None)


def _conversation_text(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    for message in _text_only_messages(payload.get("messages")):
        lines.append(f"{message['role']}: {message['content']}")
    return "\n\n".join(lines)


def _panel_results_text(panel_results: list[PanelResult]) -> str:
    if not panel_results:
        return "(no panel responses)"
    blocks: list[str] = []
    for result in panel_results:
        if result.ok:
            blocks.append(f"## {result.model}\n{result.text or '(empty response)'}")
        else:
            blocks.append(f"## {result.model}\nERROR: {result.error or 'unknown error'}")
    return "\n\n".join(blocks)


def _fusion_synthesis(
    panel_results: list[PanelResult],
    judge_result: PanelResult | None,
) -> str:
    parts = [
        "You are the primary coding agent. A private multi-model Fusion panel ran before this turn.",
        "Use the synthesis below as advisory context only. If it conflicts with the user, system, or tool results, prefer the higher-priority context.",
        "Do not mention the panel unless it is directly useful.",
    ]
    if judge_result and judge_result.ok and judge_result.text:
        parts.append(f"Judge synthesis:\n{judge_result.text}")
    parts.append(f"Panel details:\n{_panel_results_text(panel_results)}")
    return "\n\n".join(parts)


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                item_type = item.get("type")
                if item_type in {"text", "input_text", "output_text"}:
                    parts.append(str(item.get("text", "")))
                elif item_type in {"image_url", "input_image"}:
                    parts.append("[image]")
                else:
                    parts.append(f"[{item_type or 'content'}]")
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    return str(content)


def _tool_call_text(tool_call: Any) -> str:
    if not isinstance(tool_call, dict):
        return "[assistant tool call]"
    function = tool_call.get("function")
    if not isinstance(function, dict):
        return "[assistant tool call]"
    name = function.get("name") or "unknown"
    arguments = function.get("arguments") or ""
    return f"[Assistant tool call: {name} {arguments}]"


def _wants_chat_completion_response(path: str) -> bool:
    clean_path = path.strip("/")
    return clean_path == "chat/completions" or clean_path.endswith("/chat/completions")
