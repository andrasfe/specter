"""Cached LLM profile loading and domain augmentation bridge.

Loads or infers LLM semantic profiles for COBOL variables and bridges
them into the synthesis engine's VariableDomain model.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .llm_fuzzer import SemanticProfile

logger = logging.getLogger(__name__)


def load_or_infer_profiles(
    provider,
    var_report,
    cache_path: Path,
    model: str | None = None,
) -> dict[str, SemanticProfile]:
    """Load cached LLM profiles or infer them. Returns {} on failure."""
    cache_path = Path(cache_path)
    current_vars = sorted(var_report.variables.keys())

    # Try cache
    if cache_path.exists():
        try:
            raw = json.loads(cache_path.read_text())
            cached_vars = sorted(raw.get("_variable_names", []))
            if cached_vars == current_vars:
                profiles: dict[str, SemanticProfile] = {}
                for name, entry in raw.items():
                    if name.startswith("_"):
                        continue
                    profiles[name] = SemanticProfile(
                        variable=entry.get("variable", name),
                        data_type=entry.get("data_type", "text"),
                        description=entry.get("description", ""),
                        valid_values=entry.get("valid_values", []),
                        value_range=entry.get("value_range"),
                        format_pattern=entry.get("format_pattern"),
                        related_variables=entry.get("related_variables", []),
                    )
                logger.info(
                    "LLM profiles loaded from cache: %d vars (%s)",
                    len(profiles), cache_path,
                )
                return profiles
            else:
                logger.info("Cache invalidated (variable names changed)")
        except Exception as e:
            logger.warning("Cache read failed: %s", e)

    # Cache miss — query LLM
    from .llm_fuzzer import infer_variable_semantics

    profiles = infer_variable_semantics(provider, var_report, model=model)
    if not profiles:
        return {}

    # Write cache
    try:
        cache_data: dict = {"_variable_names": current_vars}
        for name, prof in profiles.items():
            cache_data[name] = {
                "variable": prof.variable,
                "data_type": prof.data_type,
                "description": prof.description,
                "valid_values": prof.valid_values,
                "value_range": prof.value_range,
                "format_pattern": prof.format_pattern,
                "related_variables": prof.related_variables,
            }
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache_data, indent=2, default=str))
        logger.info("LLM profiles cached to %s", cache_path)
    except Exception as e:
        logger.warning("Failed to write profile cache: %s", e)

    return profiles


def augment_domains_with_llm(
    domains: dict,  # dict[str, VariableDomain]
    profiles: dict[str, SemanticProfile],
) -> None:
    """Enrich VariableDomain objects with LLM-inferred data (mutates in-place)."""
    _TYPE_MAP = {
        "date": "date",
        "time": "time",
        "amount": "amount",
        "counter": "counter",
        "identifier": "identifier",
        "flag": "flag_bool",
        "indicator": "flag_bool",
        "status_code": "status_file",
    }
    for var_name, profile in profiles.items():
        dom = domains.get(var_name)
        if dom is None:
            continue
        if dom.semantic_type == "generic":
            mapped = _TYPE_MAP.get(profile.data_type)
            if mapped:
                dom.semantic_type = mapped
        existing = set(str(v) for v in dom.condition_literals)
        for v in profile.valid_values:
            if str(v) not in existing:
                dom.condition_literals.append(v)
                existing.add(str(v))
