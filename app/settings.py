"""Application configuration."""

from environs import Env

from .anthropic.settings import (
    parse_anthropic_model_profiles,
    parse_anthropic_supported_models,
    parse_cache_control,
    parse_thinking_display,
)
from .codex.settings import (
    parse_codex_model_profiles,
    parse_codex_model_rewrites,
    parse_codex_supported_models,
)
from .fusion.settings import parse_fusion_model_profiles
from .models import parse_model_deployments
from .reasoning_display import (
    DEFAULT_REASONING_DISPLAY_MODE,
    parse_reasoning_display_mode,
)

env = Env()
env.read_env()

ENV = env.str("FLASK_ENV", default="production")
DEBUG = ENV == "development"
RECORD_TRAFFIC = env.bool("RECORD_TRAFFIC", False)
LOG_CONTEXT = env.bool("LOG_CONTEXT", True)
LOG_COMPLETION = env.bool("LOG_COMPLETION", True)
REASONING_DISPLAY_MODE = parse_reasoning_display_mode(
    env.str("REASONING_DISPLAY_MODE", DEFAULT_REASONING_DISPLAY_MODE)
)
DASHBOARD_PORT = env.int("DASHBOARD_PORT", 20130)

SERVICE_API_KEY = env.str("SERVICE_API_KEY", "change-me")

ENABLE_AZURE = env.bool("ENABLE_AZURE", True)
ENABLE_CODEX = env.bool("ENABLE_CODEX", False)
ENABLE_ANTHROPIC = env.bool("ENABLE_ANTHROPIC", False)

AZURE_BASE_URL = env.str("AZURE_BASE_URL", "change_me").rstrip("/")
AZURE_API_KEY = env.str("AZURE_API_KEY", "change_me")

AZURE_SUMMARY_LEVEL = env.str("AZURE_SUMMARY_LEVEL", default="") or "detailed"
AZURE_VERBOSITY_LEVEL = env.str("AZURE_VERBOSITY_LEVEL", default="") or "medium"
AZURE_TRUNCATION = env.str("AZURE_TRUNCATION", default="") or "disabled"
raw_model_deployments = env.str("AZURE_MODEL_DEPLOYMENTS", default="")
AZURE_MODEL_DEPLOYMENTS = parse_model_deployments(raw_model_deployments)

AZURE_RESPONSES_API_URL = f"{AZURE_BASE_URL}/openai/v1/responses"

CODEX_AUTH_PATH = env.path("CODEX_AUTH_PATH", "~/.conduit/auth.json")
CODEX_RESPONSES_URL = env.str(
    "CODEX_RESPONSES_URL", "https://chatgpt.com/backend-api/codex/responses"
)
CODEX_SUPPORTED_MODELS = parse_codex_supported_models(
    env.str("CODEX_SUPPORTED_MODELS", default="")
)
CODEX_MODEL_REWRITES = parse_codex_model_rewrites(
    env.str("CODEX_MODEL_REWRITES", default=""),
    supported_models=CODEX_SUPPORTED_MODELS,
)
CODEX_MODEL_PROFILES = parse_codex_model_profiles(
    env.str("CODEX_MODEL_PROFILES", default=""),
    supported_models=CODEX_SUPPORTED_MODELS,
)
CODEX_ORIGINATOR = env.str("CODEX_ORIGINATOR", "conduit")
CODEX_USER_AGENT = env.str("CODEX_USER_AGENT", "conduit/0.1.0")
CODEX_DISCOVERY_MODE = env.bool("CODEX_DISCOVERY_MODE", False)
CODEX_TOKEN_REFRESH_SKEW_SECONDS = env.int("CODEX_TOKEN_REFRESH_SKEW_SECONDS", 300)
CODEX_REQUEST_TIMEOUT_SECONDS = env.float("CODEX_REQUEST_TIMEOUT_SECONDS", 600)

ANTHROPIC_AUTH_PATH = env.path("ANTHROPIC_AUTH_PATH", "~/.conduit/anthropic_auth.json")
ANTHROPIC_BASE_URL = env.str("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
ANTHROPIC_API_VERSION = env.str("ANTHROPIC_API_VERSION", "2023-06-01")
ANTHROPIC_SUPPORTED_MODELS = parse_anthropic_supported_models(
    env.str("ANTHROPIC_SUPPORTED_MODELS", default="")
)
ANTHROPIC_MODEL_PROFILES = parse_anthropic_model_profiles(
    env.str("ANTHROPIC_MODEL_PROFILES", default=""),
    supported_models=ANTHROPIC_SUPPORTED_MODELS,
)
ANTHROPIC_CACHE_CONTROL = parse_cache_control(
    env.str("ANTHROPIC_CACHE_CONTROL", default="auto")
)
ANTHROPIC_CACHE_TTL = env.str("ANTHROPIC_CACHE_TTL", default="5m")
ANTHROPIC_THINKING_DISPLAY = parse_thinking_display(
    env.str("ANTHROPIC_THINKING_DISPLAY", default="summarized")
)
ANTHROPIC_EAGER_TOOL_STREAMING = env.bool("ANTHROPIC_EAGER_TOOL_STREAMING", True)
ANTHROPIC_CLAUDE_CODE_VERSION = env.str("ANTHROPIC_CLAUDE_CODE_VERSION", "2.1.75")
ANTHROPIC_TOKEN_REFRESH_SKEW_SECONDS = env.int(
    "ANTHROPIC_TOKEN_REFRESH_SKEW_SECONDS", 300
)
ANTHROPIC_REQUEST_TIMEOUT_SECONDS = env.float("ANTHROPIC_REQUEST_TIMEOUT_SECONDS", 600)

_FUSION_SUPPORTED_MODELS = set(CODEX_SUPPORTED_MODELS)
_FUSION_SUPPORTED_MODELS.update(CODEX_MODEL_PROFILES)
_FUSION_SUPPORTED_MODELS.update(ANTHROPIC_SUPPORTED_MODELS)
_FUSION_SUPPORTED_MODELS.update(ANTHROPIC_MODEL_PROFILES)
FUSION_MODEL_PROFILES = parse_fusion_model_profiles(
    env.str("FUSION_MODEL_PROFILES", default=""),
    supported_models=_FUSION_SUPPORTED_MODELS,
)
FUSION_PANEL_MAX_TOKENS = env.int("FUSION_PANEL_MAX_TOKENS", 2048)
FUSION_PANEL_TIMEOUT_SECONDS = env.float("FUSION_PANEL_TIMEOUT_SECONDS", 180)
