"""
User-facing optimization settings.

Every switch is intentionally explicit so editor integrations can expose the
trade-off instead of hiding it behind a single magic mode.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any

from config import MAX_DYNAMIC_CHARS, MAX_STATIC_CHARS, SIMILARITY_THRESHOLD


@dataclass(slots=True)
class OptimizationSettings:
    profile: str = "maximum_savings"
    skeletonization: bool = True
    semantic_pruning: bool = True
    function_level_retrieval: bool = True
    include_imports: bool = True
    include_type_skeletons: bool = True
    include_active_body: bool = True
    include_same_file_callees: bool = True
    include_cross_file_callees: bool = True
    prompt_caching: bool = True
    diff_only_output: bool = True
    fallback_chunking: bool = True
    max_files: int = 6
    max_symbols: int = 12
    max_static_chars: int = MAX_STATIC_CHARS
    max_dynamic_chars: int = MAX_DYNAMIC_CHARS
    similarity_threshold: float = SIMILARITY_THRESHOLD

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


PROFILES: dict[str, OptimizationSettings] = {
    "maximum_savings": OptimizationSettings(),
    "balanced": OptimizationSettings(
        profile="balanced",
        max_files=8,
        max_symbols=16,
        max_static_chars=MAX_STATIC_CHARS,
        max_dynamic_chars=MAX_DYNAMIC_CHARS,
        similarity_threshold=0.14,
    ),
    "quality": OptimizationSettings(
        profile="quality",
        max_files=12,
        max_symbols=28,
        max_static_chars=36000,
        max_dynamic_chars=22000,
        similarity_threshold=0.08,
    ),
    "debug_fuller": OptimizationSettings(
        profile="debug_fuller",
        skeletonization=False,
        semantic_pruning=False,
        function_level_retrieval=False,
        include_cross_file_callees=True,
        prompt_caching=False,
        diff_only_output=False,
        max_files=32,
        max_symbols=64,
        max_static_chars=120000,
        max_dynamic_chars=60000,
        similarity_threshold=0.0,
    ),
}


SETTING_OPTIONS: list[dict[str, Any]] = [
    {
        "key": "skeletonization",
        "default": True,
        "impact": "very_high",
        "latency_cost": "low",
        "description": "Replaces implementation bodies with imports, type headers, and signatures in static context.",
    },
    {
        "key": "semantic_pruning",
        "default": True,
        "impact": "very_high",
        "latency_cost": "low_on_warm_cache",
        "description": "Selects only relevant files/symbols from the vector cache instead of sending the project.",
    },
    {
        "key": "function_level_retrieval",
        "default": True,
        "impact": "high",
        "latency_cost": "low",
        "description": "Retrieves matching functions/classes as symbols, not whole files.",
    },
    {
        "key": "include_active_body",
        "default": True,
        "impact": "quality_positive_token_cost_medium",
        "latency_cost": "low",
        "description": "Adds the function at the cursor to dynamic context.",
    },
    {
        "key": "include_same_file_callees",
        "default": True,
        "impact": "quality_positive_token_cost_low",
        "latency_cost": "low",
        "description": "Adds bodies directly called by the active function when they are in the same file.",
    },
    {
        "key": "include_cross_file_callees",
        "default": True,
        "impact": "quality_positive_token_cost_medium",
        "latency_cost": "low",
        "description": "Adds matching function bodies from other files by symbol name.",
    },
    {
        "key": "prompt_caching",
        "default": True,
        "impact": "high_on_repeated_requests",
        "latency_cost": "none",
        "description": "Marks stable project context as cacheable in the prompt package.",
    },
    {
        "key": "diff_only_output",
        "default": True,
        "impact": "high_on_response_tokens",
        "latency_cost": "none",
        "description": "Instructs the assistant to return unified git diff instead of full rewritten files.",
    },
]


def resolve_settings(
    profile: str | None = None,
    overrides: dict[str, Any] | None = None,
) -> OptimizationSettings:
    selected = PROFILES.get(profile or "maximum_savings", PROFILES["maximum_savings"])
    settings = replace(selected)
    overrides = overrides or {}
    allowed = set(settings.to_dict())
    clean = {key: value for key, value in overrides.items() if key in allowed and key != "profile"}
    if clean:
        settings = replace(settings, **clean)
    if profile:
        settings.profile = profile
    return settings
