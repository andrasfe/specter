"""LLM-guided coverage maximization for Monte Carlo random walks.

Uses the llm_providers package (from war_rig) to connect to an LLM that
analyzes uncovered code paths and suggests input states likely to reach
them.  The LLM receives a summary of:
  - covered vs uncovered paragraphs
  - gating conditions along the path to uncovered targets
  - variable classifications and known literal values
and returns concrete variable assignments designed to satisfy those
conditions.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import random
import time
from dataclasses import dataclass, field

from .llm_providers import Message, create_provider, get_provider_from_env
from .llm_providers.protocol import LLMProvider

logger = logging.getLogger(__name__)


class LLMUnrecoverableAuthError(RuntimeError):
    """Raised when HTTP 401 persists after retries and run should abort."""


def _is_http_401_error(exc: Exception) -> bool:
    """Best-effort HTTP 401 detection across provider/client exception types."""
    status_code = getattr(exc, "status_code", None)
    if status_code == 401:
        return True
    response = getattr(exc, "response", None)
    if response is not None and getattr(response, "status_code", None) == 401:
        return True

    text = str(exc).lower()
    return "401" in text and "unauthorized" in text


def _run_maybe_async(callable_obj) -> object | None:
    """Run sync/async callables safely in this sync module."""
    result = callable_obj()
    if inspect.isawaitable(result):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, result).result(timeout=30)
        return asyncio.run(result)
    return result


def _reconnect_provider(provider: LLMProvider) -> LLMProvider:
    """Best-effort disconnect/reconnect for provider auth/session refresh."""
    refreshed: LLMProvider = provider

    # 1) Try explicit disconnect/close hooks first.
    for method_name in ("disconnect", "close", "aclose"):
        method = getattr(refreshed, method_name, None)
        if callable(method):
            try:
                _run_maybe_async(method)
            except Exception as exc:  # pragma: no cover - best-effort cleanup
                logger.debug("Provider %s() failed during reconnect prep: %s", method_name, exc)

    # 2) Try provider-native refresh/reconnect hooks.
    for method_name in ("reconnect", "refresh", "reset", "reinitialize"):
        method = getattr(refreshed, method_name, None)
        if callable(method):
            try:
                maybe_new = _run_maybe_async(method)
                if maybe_new is not None:
                    refreshed = maybe_new
                logger.info("Provider reconnect via %s()", method_name)
                return refreshed
            except Exception as exc:
                logger.warning("Provider %s() failed during reconnect: %s", method_name, exc)

    # 3) SafeChain-specific cache reset + re-instantiation.
    try:
        if hasattr(refreshed, "_models") and isinstance(getattr(refreshed, "_models"), dict):
            getattr(refreshed, "_models").clear()
            logger.info("Provider model cache cleared during reconnect")
    except Exception as exc:  # pragma: no cover - best-effort cleanup
        logger.debug("Failed to clear provider model cache: %s", exc)

    try:
        default_model = getattr(refreshed, "default_model", None)
        config_path = getattr(refreshed, "_config_path", None)
        refreshed = refreshed.__class__(
            default_model=default_model,
            config_path=config_path,
        )
        logger.info("Provider instance recreated during reconnect")
    except Exception as exc:
        logger.debug("Provider re-instantiation skipped: %s", exc)

    return refreshed


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CoverageGap:
    """An uncovered paragraph with its path constraints."""

    target: str
    path: list[str]
    gating_conditions: list[dict]
    attempt_count: int = 0
    resolved: bool = False


@dataclass
class LLMSuggestion:
    """A suggested input state from the LLM."""

    target: str
    variable_assignments: dict[str, object]
    stub_overrides: dict[str, str] | None = None
    reasoning: str = ""


@dataclass
class LLMCoverageState:
    """Tracks LLM-guided coverage maximization state across rounds."""

    gaps: list[CoverageGap] = field(default_factory=list)
    suggestions_tried: int = 0
    suggestions_hit: int = 0
    llm_calls: int = 0
    tokens_used: int = 0


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

def _build_coverage_prompt(
    gaps: list[CoverageGap],
    covered_paragraphs: set[str],
    var_report,
    max_targets: int = 5,
) -> str:
    """Build a prompt describing the coverage gaps for the LLM."""
    # Select the most promising gaps (fewest attempts, shortest path)
    ranked = sorted(
        [g for g in gaps if not g.resolved],
        key=lambda g: (g.attempt_count, len(g.path)),
    )[:max_targets]

    if not ranked:
        return ""

    # Variable context
    var_context_lines = []
    relevant_vars: set[str] = set()
    for gap in ranked:
        for gc in gap.gating_conditions:
            relevant_vars.add(gc["variable"])

    for var_name in sorted(relevant_vars):
        info = var_report.variables.get(var_name)
        if info:
            literals = info.condition_literals[:10] if info.condition_literals else []
            var_context_lines.append(
                f"  {var_name}: classification={info.classification}, "
                f"known_values={literals!r}"
            )

    var_context = "\n".join(var_context_lines) if var_context_lines else "  (none)"

    # Gap descriptions
    gap_blocks = []
    for gap in ranked:
        conditions_desc = []
        for gc in gap.gating_conditions:
            neg = "NOT " if gc.get("negated") else ""
            conditions_desc.append(
                f"    {neg}{gc['variable']} must be in {gc['values']!r}"
            )
        cond_text = "\n".join(conditions_desc) if conditions_desc else "    (no conditions extracted)"
        gap_blocks.append(
            f"  Target: {gap.target}\n"
            f"  Path: {' -> '.join(gap.path)}\n"
            f"  Conditions:\n{cond_text}\n"
            f"  Previous attempts: {gap.attempt_count}"
        )

    gaps_text = "\n\n".join(gap_blocks)

    prompt = f"""\
You are analyzing a COBOL program that has been translated to Python.
The program uses a flat state dict where all variables are uppercase
keys (e.g. 'WS-STATUS', 'WS-FLAG').

Currently covered paragraphs ({len(covered_paragraphs)}):
  {', '.join(sorted(covered_paragraphs)[:30])}{"..." if len(covered_paragraphs) > 30 else ""}

Uncovered targets to reach:
{gaps_text}

Relevant variables:
{var_context}

For each target, suggest variable assignments (as a JSON object) that
would satisfy the gating conditions and cause execution to reach that
paragraph.  Status variables like SQLCODE, EIBRESP, file STATUS codes
control program flow after external operations.

Respond with a JSON array of objects, each having:
  "target": "<paragraph name>",
  "variables": {{"VAR-NAME": value, ...}},
  "reasoning": "<brief explanation>"

Values should be strings, integers, or booleans matching COBOL conventions.
Only output the JSON array, no other text."""

    return prompt


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

def _parse_llm_response(response_text: str) -> list[LLMSuggestion]:
    """Parse the LLM response into suggestions."""
    suggestions = []
    text = response_text.strip()

    # Extract JSON array from response (handle markdown code blocks)
    if "```" in text:
        # Find content between code fences
        parts = text.split("```")
        for part in parts[1::2]:
            # Strip optional language tag
            lines = part.strip().split("\n", 1)
            if len(lines) > 1 and lines[0].strip().lower() in ("json", ""):
                text = lines[1]
            else:
                text = part
            break

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try to find a JSON array in the text
        start = text.find("[")
        end = text.rfind("]")
        if start >= 0 and end > start:
            try:
                data = json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                logger.warning("Failed to parse LLM response as JSON")
                return []
        else:
            logger.warning("No JSON array found in LLM response")
            return []

    if not isinstance(data, list):
        data = [data]

    for item in data:
        if not isinstance(item, dict):
            continue
        target = item.get("target", "")
        variables = item.get("variables", {})
        reasoning = item.get("reasoning", "")
        if target and isinstance(variables, dict):
            suggestions.append(LLMSuggestion(
                target=target,
                variable_assignments=variables,
                reasoning=reasoning,
            ))

    return suggestions


# ---------------------------------------------------------------------------
# LLM interaction
# ---------------------------------------------------------------------------

async def _query_llm(
    provider: LLMProvider,
    prompt: str | list,
    model: str | None = None,
) -> tuple[str, int]:
    """Send a prompt to the LLM and return (response_text, tokens_used).

    Args:
        prompt: Either a string (wrapped in system+user messages) or a
                pre-built list of Message objects for multi-turn conversations.
    """
    if isinstance(prompt, list):
        messages = prompt
    else:
        messages = [
            Message(
                role="system",
                content=(
                    "You are an expert at analyzing COBOL program control flow. "
                    "You suggest precise variable values to reach uncovered code paths. "
                    "Always respond with valid JSON only."
                ),
            ),
            Message(role="user", content=prompt),
        ]

    response = await provider.complete(
        messages,
        model=model,
        temperature=0.4,
    )

    return response.content, response.tokens_used


def _query_llm_sync(
    provider: LLMProvider,
    prompt: str | list,
    model: str | None = None,
) -> tuple[str, int]:
    """Synchronous wrapper for _query_llm with 401 backoff/retry.

    Args:
        prompt: Either a string or a list of Message objects for multi-turn.
    """

    current_provider = provider

    def _run_once() -> tuple[str, int]:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, _query_llm(current_provider, prompt, model))
                return future.result(timeout=120)
        return asyncio.run(_query_llm(current_provider, prompt, model))

    for attempt in range(1, _LLM_MAX_RETRIES + 1):
        try:
            return _run_once()
        except Exception as exc:
            if not _is_http_401_error(exc):
                raise

            if attempt >= _LLM_MAX_RETRIES:
                raise LLMUnrecoverableAuthError(
                    f"LLM auth failed with HTTP 401 after {_LLM_MAX_RETRIES} attempts"
                ) from exc

            try:
                current_provider = _reconnect_provider(current_provider)
            except Exception as reconnect_exc:  # pragma: no cover - defensive
                logger.warning("Provider reconnect failed: %s", reconnect_exc)

            sleep_seconds = _LLM_401_RETRY_SCHEDULE[attempt - 1]
            logger.warning(
                "LLM request returned HTTP 401 (attempt %d/%d). Reconnected provider; sleeping %ds before retry.",
                attempt,
                _LLM_MAX_RETRIES,
                sleep_seconds,
            )
            time.sleep(sleep_seconds)

    raise LLMUnrecoverableAuthError("LLM auth failed with HTTP 401")


# ---------------------------------------------------------------------------
# Gap analysis
# ---------------------------------------------------------------------------

def build_coverage_gaps(
    uncovered: set[str],
    path_constraints_map: dict[str, object],
    gating_conditions: dict[str, list] | None,
) -> list[CoverageGap]:
    """Build CoverageGap objects for uncovered paragraphs."""
    gaps = []
    for para in sorted(uncovered):
        pc = path_constraints_map.get(para)
        path = list(pc.path) if pc and pc.path else [para]
        gc_list = []
        if pc and pc.constraints:
            for gc in pc.constraints:
                gc_list.append({
                    "variable": gc.variable,
                    "values": gc.values,
                    "negated": gc.negated,
                })
        gaps.append(CoverageGap(
            target=para,
            path=path,
            gating_conditions=gc_list,
        ))
    return gaps


# ---------------------------------------------------------------------------
# Main driver
# ---------------------------------------------------------------------------

def get_llm_provider(
    provider_name: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
) -> LLMProvider:
    """Create an LLM provider using war_rig's llm_providers.

    Tries environment-based configuration first, falls back to explicit params.
    """
    if api_key and provider_name:
        kwargs = {"api_key": api_key}
        if model:
            kwargs["default_model"] = model
        return create_provider(provider_name, **kwargs)

    return get_provider_from_env(provider_name)


_LLM_401_RETRY_SCHEDULE = (30, 60, 90)  # seconds between 401 retries
_LLM_MAX_RETRIES = len(_LLM_401_RETRY_SCHEDULE) + 1


def generate_llm_suggestions(
    provider: LLMProvider,
    covered_paragraphs: set[str],
    uncovered_paragraphs: set[str],
    path_constraints_map: dict[str, object],
    gating_conditions: dict[str, list] | None,
    var_report,
    llm_state: LLMCoverageState,
    model: str | None = None,
    max_targets: int = 5,
    max_retries: int = _LLM_MAX_RETRIES,
) -> list[LLMSuggestion]:
    """Query the LLM for input suggestions to cover uncovered paragraphs.

    Returns a list of LLMSuggestion objects with variable assignments.
    """
    # Build/update gaps
    if not llm_state.gaps:
        llm_state.gaps = build_coverage_gaps(
            uncovered_paragraphs, path_constraints_map, gating_conditions,
        )
    else:
        # Update resolved status
        for gap in llm_state.gaps:
            if gap.target in covered_paragraphs:
                gap.resolved = True

    active_gaps = [g for g in llm_state.gaps if not g.resolved]
    if not active_gaps:
        return []

    prompt = _build_coverage_prompt(
        active_gaps, covered_paragraphs, var_report, max_targets,
    )
    if not prompt:
        return []

    response_text = None
    tokens = 0
    for attempt in range(1, max_retries + 1):
        try:
            response_text, tokens = _query_llm_sync(provider, prompt, model)
            llm_state.llm_calls += 1
            llm_state.tokens_used += tokens
            break
        except Exception as e:
            if isinstance(e, LLMUnrecoverableAuthError):
                raise
            logger.warning(
                "LLM query failed (attempt %d/%d): %s",
                attempt, max_retries, e,
            )
            if attempt < max_retries:
                sleep_seconds = _LLM_401_RETRY_SCHEDULE[min(attempt - 1, len(_LLM_401_RETRY_SCHEDULE) - 1)]
                logger.info("Retrying in %d seconds...", sleep_seconds)
                time.sleep(sleep_seconds)
            else:
                logger.error("All %d LLM retry attempts exhausted", max_retries)
                return []

    if response_text is None:
        return []

    suggestions = _parse_llm_response(response_text)

    # Mark attempted gaps
    suggested_targets = {s.target for s in suggestions}
    for gap in active_gaps:
        if gap.target in suggested_targets:
            gap.attempt_count += 1

    return suggestions


def apply_suggestion(
    suggestion: LLMSuggestion,
    base_state: dict,
    var_report,
    stub_mapping: dict[str, list[str]] | None = None,
) -> dict:
    """Apply an LLM suggestion to a base state dict.

    Merges the suggested variable assignments into the base state,
    validating variable names against the known variable report.
    """
    state = dict(base_state)
    known_vars = set(var_report.variables.keys()) if var_report else set()

    for var_name, value in suggestion.variable_assignments.items():
        upper = var_name.upper()
        # Accept if it's a known variable or looks like a COBOL variable
        if upper in known_vars or (len(upper) >= 2 and "-" in upper):
            state[upper] = value

    return state
