"""Reasoning display mode helpers."""

from __future__ import annotations

from typing import Any

from .exceptions import ServiceConfigurationError

DEFAULT_REASONING_DISPLAY_MODE = "mdthinkblocks"
REASONING_DISPLAY_MODES = {"mdthinkblocks", "none", "thinkblocks"}


def parse_reasoning_display_mode(value: Any) -> str:
    """Return a normalized reasoning display mode."""
    mode = str(value or DEFAULT_REASONING_DISPLAY_MODE).strip().lower()
    if mode in REASONING_DISPLAY_MODES:
        return mode
    raise ServiceConfigurationError(
        "REASONING_DISPLAY_MODE must be one of: "
        + ", ".join(sorted(REASONING_DISPLAY_MODES))
        + f".\n\nGot: {value!r}"
    )


def reasoning_start_delta(mode: str) -> dict[str, Any] | None:
    """Return the visible chunk that starts a reasoning block."""
    if mode == "mdthinkblocks":
        return {
            "role": "assistant",
            "content": "<details>\n<summary>Thought</summary>\n\n",
        }
    if mode == "thinkblocks":
        return {"role": "assistant", "content": "<think>\n"}
    return None


def reasoning_end_delta(mode: str) -> dict[str, Any] | None:
    """Return the visible chunk that ends a reasoning block."""
    if mode == "mdthinkblocks":
        return {"role": "assistant", "content": "\n\n</details>\n\n"}
    if mode == "thinkblocks":
        return {"role": "assistant", "content": "\n</think>\n\n"}
    return None


def reasoning_content_delta(text: str, mode: str) -> dict[str, Any]:
    """Return a reasoning delta with native metadata and optional visible content."""
    thinking_block = {"type": "thinking", "thinking": text}
    return {
        "role": "assistant",
        "content": None if mode == "none" else text,
        "reasoning": text,
        "reasoning_content": text,
        "reasoning_details": [{"type": "reasoning.text", "text": text}],
        "thinking_blocks": [thinking_block],
        "provider_specific_fields": {"thinking_blocks": [thinking_block]},
    }
