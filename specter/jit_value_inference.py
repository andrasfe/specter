"""Lazy LLM-backed variable value inference for coverage generation.

Provides a shared cached service that infers semantically plausible values on
demand from variable names, COBOL field facts, literals, and optional local
comments. The coverage engine can use this for semantic generation while
retaining heuristic generation as a safe fallback.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import time
from pathlib import Path
from typing import Any

from .llm_coverage import _query_llm_sync
from .llm_fuzzer import SemanticProfile, _parse_semantic_profiles, generate_value_from_profile
from .persistence_utils import atomic_write_json
from .variable_domain import VariableDomain, _coerce_numeric_value

logger = logging.getLogger(__name__)


def _cache_key(
    var_name: str,
    domain: VariableDomain,
    target_paragraph: str | None,
    op_key: str | None,
    comment_hints: list[str] | None,
) -> str:
    payload = {
        "variable": var_name.upper(),
        "data_type": domain.data_type,
        "max_length": domain.max_length,
        "precision": domain.precision,
        "signed": domain.signed,
        "min_value": domain.min_value,
        "max_value": domain.max_value,
        "literals": list(domain.condition_literals),
        "values_88": dict(domain.valid_88_values),
        "target": target_paragraph or "",
        "op_key": op_key or "",
        "comments": list(comment_hints or []),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _build_inference_prompt(
    var_name: str,
    domain: VariableDomain,
    *,
    target_paragraph: str | None = None,
    op_key: str | None = None,
    comment_hints: list[str] | None = None,
) -> str:
    literal_text = list(domain.condition_literals)[:10]
    values_88 = dict(list(domain.valid_88_values.items())[:8])
    comment_text = "\n".join(f"- {line}" for line in (comment_hints or [])[:5]) or "- none"
    range_text = "unknown"
    if domain.min_value is not None or domain.max_value is not None:
        range_text = f"min={domain.min_value!r}, max={domain.max_value!r}"

    return f"""\
You are inferring realistic candidate values for one COBOL variable used during
coverage-guided test generation.

Variable: {var_name}
Classification: {domain.classification}
COBOL type facts:
- data_type: {domain.data_type}
- max_length: {domain.max_length}
- precision: {domain.precision}
- signed: {domain.signed}
- numeric_range: {range_text}
- set_by_stub: {domain.set_by_stub or 'none'}

Known literals from conditions: {literal_text!r}
Known 88-level values: {values_88!r}
Target paragraph: {target_paragraph or 'none'}
Stub operation context: {op_key or 'none'}
Nearby comments:
{comment_text}

Infer the business meaning just in time and return ONLY JSON, either a single
object or a one-element array with these fields:
- variable
- data_type
- description
- valid_values: 3-8 high-value candidate values matching COBOL conventions
- value_range: optional object with min/max when numeric
- format_pattern
- related_variables

Do not explain. Output JSON only.
"""


def _normalize_candidate(domain: VariableDomain, value: Any) -> str | int | float | None:
    if value is None:
        return None
    if domain.data_type in ("alpha", "unknown", "group"):
        return str(value)

    numeric = _coerce_numeric_value(value, domain.precision)
    if domain.min_value is not None and numeric < domain.min_value:
        numeric = domain.min_value
    if domain.max_value is not None and numeric > domain.max_value:
        numeric = domain.max_value
    if domain.precision == 0:
        return int(numeric)
    return float(numeric)


def _candidate_values_from_profile(
    profile: SemanticProfile,
    domain: VariableDomain,
    rng: random.Random,
) -> list[str | int | float]:
    values: list[str | int | float] = []
    seen: set[tuple[str, str]] = set()

    def add(value: Any) -> None:
        normalized = _normalize_candidate(domain, value)
        if normalized is None:
            return
        key = (type(normalized).__name__, str(normalized))
        if key in seen:
            return
        seen.add(key)
        values.append(normalized)

    for value in profile.valid_values:
        add(value)

    if isinstance(profile.value_range, dict):
        if "min" in profile.value_range:
            add(profile.value_range.get("min"))
        if "max" in profile.value_range:
            add(profile.value_range.get("max"))
        low = profile.value_range.get("min")
        high = profile.value_range.get("max")
        if isinstance(low, (int, float)) and isinstance(high, (int, float)):
            add((low + high) / 2)

    if not values:
        add(generate_value_from_profile(profile, rng))

    return values


class JITValueInferenceService:
    """Shared cached service for lazy semantic value inference."""

    def __init__(
        self,
        provider: object | None,
        model: str | None = None,
        cache_path: str | Path | None = None,
    ):
        self.provider = provider
        self.model = model
        self.cache_path = Path(cache_path) if cache_path else None
        self._profiles: dict[str, SemanticProfile] = {}
        self.cache_hits = 0
        self.cache_misses = 0
        self.skipped_untargeted = 0
        self.skipped_out_of_scope = 0
        self.llm_successes = 0
        self.llm_failures = 0
        self.total_infer_latency_ms = 0.0
        self._events_since_summary = 0
        self._last_summary_ts = time.time()
        self._last_debug_ts = 0.0
        self.summary_every_requests = 5000
        self.summary_interval_sec = 60.0
        self.debug_min_interval_sec = 0.1
        self.require_target_paragraph_context = True
        if self.cache_path and self.cache_path.exists():
            self._load_cache()

    def snapshot_metrics(self) -> dict[str, float | int]:
        """Return a stable metrics snapshot for progress logs."""
        total = self.cache_hits + self.cache_misses
        requests = total + self.skipped_untargeted + self.skipped_out_of_scope
        hit_pct = (100.0 * self.cache_hits / total) if total else 0.0
        avg_latency_ms = (
            self.total_infer_latency_ms / self.llm_successes
            if self.llm_successes
            else 0.0
        )
        return {
            "requests": requests,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "skipped_untargeted": self.skipped_untargeted,
            "skipped_out_of_scope": self.skipped_out_of_scope,
            "cache_hit_pct": hit_pct,
            "llm_successes": self.llm_successes,
            "llm_failures": self.llm_failures,
            "avg_latency_ms": avg_latency_ms,
        }

    def _debug_event(self, msg: str, *args: object) -> None:
        if not logger.isEnabledFor(logging.DEBUG):
            return
        now = time.time()
        if (now - self._last_debug_ts) < self.debug_min_interval_sec:
            return
        self._last_debug_ts = now
        logger.debug(msg, *args)

    def _emit_periodic_summary(self, force: bool = False) -> None:
        if not logger.isEnabledFor(logging.INFO):
            return
        total = (
            self.cache_hits
            + self.cache_misses
            + self.skipped_untargeted
            + self.skipped_out_of_scope
        )
        if total <= 0:
            return
        now = time.time()
        if not force:
            if self._events_since_summary < self.summary_every_requests:
                if (now - self._last_summary_ts) < self.summary_interval_sec:
                    return

        snap = self.snapshot_metrics()
        logger.info(
            "JIT status: reqs=%d hit=%d miss=%d hit%%=%.1f skip_u=%d skip_scope=%d llm_ok=%d llm_fail=%d avg_ms=%.0f",
            int(snap["requests"]),
            int(snap["cache_hits"]),
            int(snap["cache_misses"]),
            float(snap["cache_hit_pct"]),
            int(snap["skipped_untargeted"]),
            int(snap["skipped_out_of_scope"]),
            int(snap["llm_successes"]),
            int(snap["llm_failures"]),
            float(snap["avg_latency_ms"]),
        )
        self._events_since_summary = 0
        self._last_summary_ts = now

    def _load_cache(self) -> None:
        if not self.cache_path:
            return
        try:
            raw = json.loads(self.cache_path.read_text())
        except Exception as exc:
            logger.warning("JIT inference cache read failed: %s", exc)
            return
        for key, entry in raw.items():
            if not isinstance(entry, dict):
                continue
            self._profiles[key] = SemanticProfile(
                variable=entry.get("variable", ""),
                data_type=entry.get("data_type", "text"),
                description=entry.get("description", ""),
                valid_values=entry.get("valid_values", []),
                value_range=entry.get("value_range"),
                format_pattern=entry.get("format_pattern"),
                related_variables=entry.get("related_variables", []),
            )

    def _save_cache(self) -> None:
        if not self.cache_path:
            return
        payload = {
            key: {
                "variable": profile.variable,
                "data_type": profile.data_type,
                "description": profile.description,
                "valid_values": profile.valid_values,
                "value_range": profile.value_range,
                "format_pattern": profile.format_pattern,
                "related_variables": profile.related_variables,
            }
            for key, profile in self._profiles.items()
        }
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(self.cache_path, payload, indent=2)
        except Exception as exc:
            logger.warning("JIT inference cache write failed: %s", exc)

    def infer_profile(
        self,
        var_name: str,
        domain: VariableDomain,
        *,
        target_paragraph: str | None = None,
        op_key: str | None = None,
        comment_hints: list[str] | None = None,
        allowed_variables: set[str] | None = None,
        target_key: str | None = None,
    ) -> SemanticProfile | None:
        para = target_paragraph or "none"
        op = op_key or "none"
        if self.require_target_paragraph_context and not target_paragraph:
            self.skipped_untargeted += 1
            self._events_since_summary += 1
            self._debug_event(
                "JIT skipped (untargeted) var=%s type=%s para=%s op=%s",
                var_name,
                domain.data_type,
                para,
                op,
            )
            self._emit_periodic_summary()
            return None

        # CRITICAL GATE: Skip out-of-scope only if allowlist is restrictive (has few items).
        # If allowlist is large (60+ items) or has known gating/stub vars, pass through.
        # This prevents starvation when targets have broad variable dependencies.
        if allowed_variables and len(allowed_variables) > 0:
            # Allow through if: (1) large allowlist (>60 vars suggesting heuristic broadness)
            # or (2) var is explicitly listed (precise match)
            if len(allowed_variables) <= 60:
                var_upper = var_name.upper()
                allowed_upper = {v.upper() for v in allowed_variables}
                if var_upper not in allowed_upper:
                    self.skipped_out_of_scope += 1
                    self._events_since_summary += 1
                    self._debug_event(
                        "JIT skipped (out_of_scope) var=%s type=%s para=%s target=%s",
                        var_name,
                        domain.data_type,
                        para,
                        target_key or "none",
                    )
                    self._emit_periodic_summary()
                    return None

        key = _cache_key(var_name, domain, target_paragraph, op_key, comment_hints)
        cached = self._profiles.get(key)
        if cached is not None:
            self.cache_hits += 1
            self._events_since_summary += 1
            self._debug_event(
                "JIT cache_hit var=%s type=%s para=%s op=%s",
                var_name,
                domain.data_type,
                para,
                op,
            )
            self._emit_periodic_summary()
            return cached

        self.cache_misses += 1
        self._events_since_summary += 1
        self._debug_event(
            "JIT cache_miss var=%s type=%s para=%s op=%s",
            var_name,
            domain.data_type,
            para,
            op,
        )
        if self.provider is None:
            self._debug_event(
                "JIT skipped (no provider) var=%s type=%s para=%s op=%s",
                var_name,
                domain.data_type,
                para,
                op,
            )
            self._emit_periodic_summary()
            return None

        prompt = _build_inference_prompt(
            var_name,
            domain,
            target_paragraph=target_paragraph,
            op_key=op_key,
            comment_hints=comment_hints,
        )
        infer_start = time.time()
        try:
            response_text, _tokens = _query_llm_sync(self.provider, prompt, self.model)
            profiles = _parse_semantic_profiles(response_text)
            profile = profiles.get(var_name.upper())
            if profile is None and profiles:
                profile = next(iter(profiles.values()))
            if profile is None:
                self.llm_failures += 1
                self._debug_event(
                    "JIT empty_profile var=%s type=%s para=%s op=%s",
                    var_name,
                    domain.data_type,
                    para,
                    op,
                )
                self._emit_periodic_summary()
                return None
            latency_ms = (time.time() - infer_start) * 1000.0
            self.llm_successes += 1
            self.total_infer_latency_ms += latency_ms
            self._profiles[key] = profile
            self._save_cache()
            self._debug_event(
                "JIT inferred var=%s type=%s para=%s op=%s ms=%.0f",
                var_name,
                domain.data_type,
                para,
                op,
                latency_ms,
            )
            self._emit_periodic_summary()
            return profile
        except Exception as exc:
            self.llm_failures += 1
            logger.warning("JIT variable inference failed for %s: %s", var_name, exc)
            self._debug_event(
                "JIT fallback var=%s type=%s para=%s op=%s reason=%s",
                var_name,
                domain.data_type,
                para,
                op,
                exc,
            )
            self._emit_periodic_summary()
            return None

    def generate_value(
        self,
        var_name: str,
        domain: VariableDomain,
        strategy: str,
        rng: random.Random,
        *,
        target_paragraph: str | None = None,
        op_key: str | None = None,
        comment_hints: list[str] | None = None,
        allowed_variables: set[str] | None = None,
        target_key: str | None = None,
    ) -> str | int | float | None:
        if strategy != "semantic":
            return None
        profile = self.infer_profile(
            var_name,
            domain,
            target_paragraph=target_paragraph,
            op_key=op_key,
            comment_hints=comment_hints,
            allowed_variables=allowed_variables,
            target_key=target_key,
        )
        if profile is None:
            return None
        candidates = _candidate_values_from_profile(profile, domain, rng)
        if not candidates:
            return None
        return rng.choice(candidates)