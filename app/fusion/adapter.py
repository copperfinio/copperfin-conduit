"""Flask adapter for Fusion-style compound model aliases."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from typing import Any
from uuid import uuid4

from flask import Request, Response, current_app, jsonify

from ..anthropic.adapter import AnthropicAdapter
from ..codex.adapter import CodexAdapter
from ..common.logging import console
from .invoker import FusionModelInvoker, PanelResult
from .settings import FusionModelProfile, FusionSettings

_PANEL_SYSTEM = """You are one member of a multi-model analysis panel.

Give an independent, concise assessment for the synthesizer model.
Do not call tools, do not claim to edit files, and do not address the user directly.
Focus on correctness, risks, missing context, and the best next action."""


class FusionAdapter:
    """Run private panel analysis, then stream one tool-capable synthesizer response."""

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
            f"path={provider_path} model={model!r} "
            f"synthesizer={profile.synthesizer_model} panel={list(profile.panel_models)}"
        )

        run_id = uuid4().hex
        panel_results = self._run_panel(
            payload=payload,
            profile=profile,
            downstream_headers=downstream_headers,
            run_id=run_id,
        )
        final_payload = _synthesizer_payload(
            payload,
            profile=profile,
            panel_results=panel_results,
        )
        console.print(
            "[bold cyan]FUSION SYNTHESIZER:[/bold cyan] "
            f"inbound_model={model} synthesizer_model={profile.synthesizer_model} "
            f"panel_ok={sum(1 for result in panel_results if result.ok)}/{len(panel_results)}"
        )
        return _forward_synthesizer(
            req,
            provider_path=provider_path,
            payload=final_payload,
            invoker=self.invoker,
            run_id=run_id,
        )

    def _run_panel(
        self,
        *,
        payload: dict[str, Any],
        profile: FusionModelProfile,
        downstream_headers: dict[str, str],
        run_id: str | None = None,
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
                    phase="panel",
                    run_id=run_id,
                    label=_fusion_call_label("panel", str(panel_payload["model"])),
                )
                for panel_payload in panel_payloads
            ]
            for future in as_completed(futures):
                results.append(future.result())
        return sorted(
            results, key=lambda result: profile.panel_models.index(result.model)
        )


def _invoke_with_app_context(
    app: Any,
    invoker: FusionModelInvoker,
    *,
    model: str,
    payload: dict[str, Any],
    downstream_headers: dict[str, str],
    phase: str | None = None,
    run_id: str | None = None,
    label: str | None = None,
) -> PanelResult:
    """Run a Fusion panel invocation with Flask config available in worker threads."""
    with app.app_context():
        return invoker.invoke_text(
            model=model,
            payload=payload,
            downstream_headers=downstream_headers,
            phase=phase,
            run_id=run_id,
            label=label,
        )


def _forward_synthesizer(
    req: Request,
    *,
    provider_path: str,
    payload: dict[str, Any],
    invoker: FusionModelInvoker,
    run_id: str | None = None,
) -> Response:
    model = str(payload.get("model") or "")
    provider = invoker.provider_for_model(model)
    downstream_headers = dict(req.headers)
    label = _fusion_call_label("synthesizer", model)
    if provider == "anthropic":
        return AnthropicAdapter().forward_payload(
            payload,
            provider_path,
            downstream_headers,
            run_id=run_id,
            phase="synthesizer",
            label=label,
            telemetry_provider="fusion",
            upstream_provider="anthropic",
        )
    return CodexAdapter().forward_payload(
        payload,
        provider_path,
        downstream_headers,
        run_id=run_id,
        phase="synthesizer",
        label=label,
        telemetry_provider="fusion",
        upstream_provider="codex",
    )


def _fusion_call_label(phase: str, model: str) -> str:
    role = {"synthesizer": "Synthesizer"}.get(phase, "Panel")
    return f"{role} - {_friendly_fusion_model(model)}"


def _friendly_fusion_model(model: str) -> str:
    lowered = model.lower()
    if "gpt55" in lowered or "gpt-5.5" in lowered or "gpt 5.5" in lowered:
        return "GPT 5.5"
    if "opus48" in lowered or "opus-4-8" in lowered or "opus 4.8" in lowered:
        return "Opus 4.8"
    return model


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


def _synthesizer_payload(
    payload: dict[str, Any],
    *,
    profile: FusionModelProfile,
    panel_results: list[PanelResult],
) -> dict[str, Any]:
    out = deepcopy(payload)
    out["model"] = profile.synthesizer_model
    synthesis = _fusion_synthesis(panel_results)
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
            tool_text = "\n".join(
                _tool_call_text(tool_call) for tool_call in tool_calls
            )
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


def _panel_results_text(panel_results: list[PanelResult]) -> str:
    if not panel_results:
        return "(no panel responses)"
    blocks: list[str] = []
    for result in panel_results:
        if result.ok:
            blocks.append(f"## {result.model}\n{result.text or '(empty response)'}")
        else:
            blocks.append(
                f"## {result.model}\nERROR: {result.error or 'unknown error'}"
            )
    return "\n\n".join(blocks)


def _fusion_synthesis(panel_results: list[PanelResult]) -> str:
    parts = [
        "You are the Fusion synthesizer. A private multi-model panel ran before this turn.",
        (
            "Use the panel context below as advisory context. If it conflicts "
            "with the user, system, or tool results, prefer the higher-priority context."
        ),
        (
            "You are the final Cursor-facing responder. Preserve normal tool use, "
            "streaming behavior, and user-facing style."
        ),
        "Do not mention the panel unless it is directly useful.",
    ]
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
