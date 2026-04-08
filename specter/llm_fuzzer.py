"""LLM-guided Monte Carlo random walk with adaptive strategy selection.

Replaces hardcoded mutation weights and mechanical stale detection with
LLM-driven decisions.  The LLM acts as a strategist: it infers variable
semantics from names, selects fuzzing strategies based on observed outcomes,
and adapts when coverage plateaus.

See LLM_GUIDED_FUZZER.md for the full design.
"""

from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SemanticProfile:
    """LLM-inferred semantic meaning for a single variable."""

    variable: str
    data_type: str  # e.g. "date", "amount", "identifier", "flag", "status_code", "counter", "text"
    description: str  # e.g. "Customer account balance in cents"
    valid_values: list[Any] = field(default_factory=list)  # concrete values to try
    value_range: dict[str, Any] | None = None  # e.g. {"min": 0, "max": 99999}
    format_pattern: str | None = None  # e.g. "YYYYMMDD", "9(5)"
    related_variables: list[str] = field(default_factory=list)  # e.g. ["END-DATE"]


@dataclass
class StrategyResult:
    """Outcome of running a strategy for N iterations."""

    strategy: str
    iterations: int
    new_paragraphs: int
    new_branches: int
    new_edges: int
    errors: int


@dataclass
class SessionMemory:
    """Structured log the LLM can query to make decisions."""

    # Coverage timeline: (iteration, paragraph_count, branch_count)
    coverage_timeline: list[tuple[int, int, int]] = field(default_factory=list)

    # Strategy effectiveness: strategy_name -> cumulative results
    strategy_history: list[StrategyResult] = field(default_factory=list)

    # Error patterns: input fingerprint -> error message
    error_patterns: list[dict[str, Any]] = field(default_factory=list)

    # Best inputs: corpus entries that achieved unique coverage
    best_inputs: list[dict[str, Any]] = field(default_factory=list)

    # Variable semantic profiles from initial LLM inference
    semantic_profiles: dict[str, SemanticProfile] = field(default_factory=dict)

    # LLM usage tracking
    llm_calls: int = 0
    tokens_used: int = 0


@dataclass
class StrategyDecision:
    """LLM's decision about what strategy to run next."""

    strategy: str  # one of the STRATEGY_NAMES
    target_paragraph: str | None = None
    focus_variables: list[str] = field(default_factory=list)
    focus_values: dict[str, list[Any]] = field(default_factory=dict)
    iterations: int = 50
    reasoning: str = ""


# Available strategy names
STRATEGY_NAMES = frozenset({
    "random_exploration",
    "single_var_mutation",
    "literal_guided",
    "directed_walk",
    "stub_outcome_variation",
    "crossover",
    "error_avoidance_replay",
})


# ---------------------------------------------------------------------------
# Variable semantics inference
# ---------------------------------------------------------------------------

def _build_variable_inference_prompt(
    var_report,
    condition_literals: dict[str, list] | None = None,
) -> str:
    """Build prompt asking LLM to infer semantic meaning from variable names."""
    var_lines = []
    for name, info in sorted(var_report.variables.items()):
        literals = info.condition_literals[:10] if info.condition_literals else []
        line = f"  {name}: classification={info.classification}"
        if literals:
            line += f", condition_values={literals!r}"
        var_lines.append(line)

    var_text = "\n".join(var_lines) if var_lines else "  (none)"

    return f"""\
You are analyzing variables from a COBOL program that has been translated to Python.
Each variable has an uppercase hyphenated name (e.g. WS-CUSTOMER-ID, ACCT-BALANCE).

Infer the semantic meaning of each variable from its name and any known condition
values.  For each variable, determine:
- data_type: one of "date", "time", "amount", "identifier", "counter", "flag",
  "status_code", "indicator", "text", "code", "numeric", "alphanumeric"
- description: brief (5-10 words) description of what it likely represents
- valid_values: 3-5 realistic example values (strings, ints, or bools matching
  COBOL conventions)
- format_pattern: if it's a date/time/structured field, the format (e.g. "YYYYMMDD")
- related_variables: names of other variables in this list that are semantically
  related (e.g. START-DATE and END-DATE)

Variables:
{var_text}

Respond with a JSON array of objects, each having:
  "variable": "<name>",
  "data_type": "<type>",
  "description": "<brief description>",
  "valid_values": [<value1>, <value2>, ...],
  "format_pattern": "<pattern or null>",
  "related_variables": ["<name>", ...]

Only output the JSON array, no other text."""


def _parse_semantic_profiles(response_text: str) -> dict[str, SemanticProfile]:
    """Parse LLM response into SemanticProfile objects."""
    text = response_text.strip()

    # Extract JSON from code fences if present
    if "```" in text:
        parts = text.split("```")
        for part in parts[1::2]:
            lines = part.strip().split("\n", 1)
            if len(lines) > 1 and lines[0].strip().lower() in ("json", ""):
                text = lines[1]
            else:
                text = part
            break

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("[")
        end = text.rfind("]")
        if start >= 0 and end > start:
            try:
                data = json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                logger.warning("Failed to parse variable inference response as JSON")
                return {}
        else:
            logger.warning("No JSON array found in variable inference response")
            return {}

    if not isinstance(data, list):
        data = [data]

    profiles: dict[str, SemanticProfile] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        var_name = item.get("variable", "")
        if not var_name:
            continue
        profiles[var_name.upper()] = SemanticProfile(
            variable=var_name.upper(),
            data_type=item.get("data_type", "text"),
            description=item.get("description", ""),
            valid_values=item.get("valid_values", []),
            format_pattern=item.get("format_pattern"),
            related_variables=[v.upper() for v in item.get("related_variables", [])],
        )

    return profiles


def infer_variable_semantics(
    provider,
    var_report,
    model: str | None = None,
) -> dict[str, SemanticProfile]:
    """Query LLM to infer semantic meaning of all variables.

    Called once at session start.  Returns a dict of variable name -> SemanticProfile.
    Falls back to empty dict on LLM failure.
    """
    from .llm_coverage import _query_llm_sync

    prompt = _build_variable_inference_prompt(var_report)
    if not prompt:
        return {}

    try:
        response_text, tokens = _query_llm_sync(provider, prompt, model)
        profiles = _parse_semantic_profiles(response_text)
        logger.info(
            "Inferred semantic profiles for %d/%d variables (%d tokens)",
            len(profiles), len(var_report.variables), tokens,
        )
        return profiles
    except Exception as e:
        logger.warning("Variable semantics inference failed: %s", e)
        return {}


# ---------------------------------------------------------------------------
# Strategy decision prompt
# ---------------------------------------------------------------------------

def _build_strategy_prompt(
    memory: SessionMemory,
    covered_paragraphs: set[str],
    all_paragraphs: set[str],
    frontier: set[str],
    total_branches: int,
    covered_branches: int,
    var_report,
) -> str:
    """Build prompt asking LLM to select the next fuzzing strategy."""
    uncovered = all_paragraphs - covered_paragraphs
    coverage_pct = (len(covered_paragraphs) / len(all_paragraphs) * 100
                    if all_paragraphs else 0)
    branch_pct = (covered_branches / total_branches * 100
                  if total_branches else 0)

    # Recent strategy history (last 5)
    recent_strategies = memory.strategy_history[-5:]
    strategy_lines = []
    for sr in recent_strategies:
        strategy_lines.append(
            f"  {sr.strategy}: {sr.iterations} iters, "
            f"+{sr.new_paragraphs} paras, +{sr.new_branches} branches, "
            f"{sr.errors} errors"
        )
    strategy_text = "\n".join(strategy_lines) if strategy_lines else "  (no history yet)"

    # Error patterns (last 3 unique)
    error_lines = []
    seen_errors: set[str] = set()
    for ep in reversed(memory.error_patterns[-10:]):
        msg = ep.get("error", "")
        if msg not in seen_errors:
            seen_errors.add(msg)
            focus_vars = ep.get("focus_variables", [])
            error_lines.append(f"  {msg[:100]} (vars: {focus_vars[:3]})")
        if len(error_lines) >= 3:
            break
    error_text = "\n".join(error_lines) if error_lines else "  (no errors)"

    # Semantic profiles for uncovered-related variables
    profile_lines = []
    for var_name, profile in sorted(memory.semantic_profiles.items()):
        profile_lines.append(
            f"  {var_name}: {profile.data_type} — {profile.description}"
            f" (values: {profile.valid_values[:5]!r})"
        )
    profile_text = "\n".join(profile_lines[:30]) if profile_lines else "  (no profiles)"

    # Frontier
    frontier_text = ", ".join(sorted(frontier)[:15])
    if len(frontier) > 15:
        frontier_text += f"... (+{len(frontier) - 15} more)"

    # Available variables with classification
    var_lines = []
    for name, info in sorted(var_report.variables.items()):
        var_lines.append(f"  {name}: {info.classification}")
    var_text = "\n".join(var_lines[:40]) if var_lines else "  (none)"

    return f"""\
You are guiding a coverage-directed fuzzer for a COBOL-to-Python program.
Your goal: maximize paragraph and branch coverage while avoiding errors.

## Current State
- Paragraphs covered: {len(covered_paragraphs)}/{len(all_paragraphs)} ({coverage_pct:.0f}%)
- Branches covered: {covered_branches}/{total_branches} ({branch_pct:.0f}%)
- Uncovered paragraphs: {', '.join(sorted(uncovered)[:20])}{"..." if len(uncovered) > 20 else ""}
- Frontier (covered callers of uncovered): {frontier_text}

## Recent Strategy Results
{strategy_text}

## Recent Error Patterns
{error_text}

## Variable Semantic Profiles
{profile_text}

## Available Variables
{var_text}

## Available Strategies
- random_exploration: fully random domain-aware generation
- single_var_mutation: pick one variable, change its value
- literal_guided: use values from COBOL conditions
- directed_walk: target a specific uncovered paragraph by satisfying gating conditions
- stub_outcome_variation: change what external operations (SQL, file I/O) return
- crossover: combine inputs from two high-coverage runs
- error_avoidance_replay: take an erroring input, minimally mutate to avoid the error

Select the best strategy for the next batch of iterations.

Respond with a JSON object:
{{
  "strategy": "<strategy_name>",
  "target_paragraph": "<optional — for directed_walk>",
  "focus_variables": ["<optional — specific variables to mutate>"],
  "focus_values": {{"VAR-NAME": ["value1", "value2"]}},
  "iterations": <number 25-100>,
  "reasoning": "<brief explanation>"
}}

Only output the JSON object, no other text."""


def _parse_strategy_decision(response_text: str) -> StrategyDecision | None:
    """Parse LLM response into a StrategyDecision."""
    text = response_text.strip()

    # Extract JSON from code fences if present
    if "```" in text:
        parts = text.split("```")
        for part in parts[1::2]:
            lines = part.strip().split("\n", 1)
            if len(lines) > 1 and lines[0].strip().lower() in ("json", ""):
                text = lines[1]
            else:
                text = part
            break

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                logger.warning("Failed to parse strategy decision as JSON")
                return None
        else:
            return None

    if not isinstance(data, dict):
        return None

    strategy = data.get("strategy", "")
    if strategy not in STRATEGY_NAMES:
        logger.warning("Unknown strategy %r, falling back to random_exploration", strategy)
        strategy = "random_exploration"

    return StrategyDecision(
        strategy=strategy,
        target_paragraph=data.get("target_paragraph"),
        focus_variables=data.get("focus_variables", []),
        focus_values=data.get("focus_values", {}),
        iterations=max(10, min(200, data.get("iterations", 50))),
        reasoning=data.get("reasoning", ""),
    )


def get_strategy_decision(
    provider,
    memory: SessionMemory,
    covered_paragraphs: set[str],
    all_paragraphs: set[str],
    frontier: set[str],
    total_branches: int,
    covered_branches: int,
    var_report,
    model: str | None = None,
) -> StrategyDecision | None:
    """Query LLM for the next strategy decision.

    Returns None on LLM failure (caller should fall back to algorithmic approach).
    """
    from .llm_coverage import _query_llm_sync

    prompt = _build_strategy_prompt(
        memory, covered_paragraphs, all_paragraphs, frontier,
        total_branches, covered_branches, var_report,
    )

    try:
        response_text, tokens = _query_llm_sync(provider, prompt, model)
        memory.llm_calls += 1
        memory.tokens_used += tokens
        decision = _parse_strategy_decision(response_text)
        if decision:
            logger.info(
                "LLM strategy decision: %s (%s), %d iters",
                decision.strategy, decision.reasoning[:60], decision.iterations,
            )
        return decision
    except Exception as e:
        logger.warning("Strategy decision LLM query failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# Strategy execution
# ---------------------------------------------------------------------------

def generate_value_from_profile(
    profile: SemanticProfile,
    rng: random.Random,
) -> Any:
    """Generate a random value using the LLM-inferred semantic profile."""
    if profile.valid_values:
        return rng.choice(profile.valid_values)

    # Fallback by data type
    if profile.data_type == "date":
        return f"{rng.randint(2020, 2026):04d}{rng.randint(1, 12):02d}{rng.randint(1, 28):02d}"
    elif profile.data_type == "time":
        return f"{rng.randint(0, 23):02d}{rng.randint(0, 59):02d}{rng.randint(0, 59):02d}"
    elif profile.data_type == "amount":
        return rng.randint(0, 99999)
    elif profile.data_type == "counter":
        return rng.randint(0, 100)
    elif profile.data_type in ("flag", "indicator"):
        return rng.choice(["Y", "N", True, False])
    elif profile.data_type == "identifier":
        return str(rng.randint(10000, 99999))
    elif profile.data_type == "status_code":
        return rng.choice(["00", "10", "  ", 0])
    elif profile.data_type == "numeric":
        return rng.randint(0, 9999)
    else:
        return rng.choice(["", " ", "TEST", "A"])


def _maybe_generate_jit_value(
    var_name: str,
    memory: SessionMemory,
    rng: random.Random,
    *,
    jit_inference=None,
    domains: dict[str, Any] | None = None,
    target_paragraph: str | None = None,
) -> Any | None:
    """Try lazy JIT semantic inference before falling back to cached profiles."""
    if jit_inference is None or not domains:
        return None

    domain = domains.get(var_name.upper())
    if domain is None:
        return None

    value = jit_inference.generate_value(
        var_name.upper(),
        domain,
        "semantic",
        rng,
        target_paragraph=target_paragraph,
    )
    if value is None:
        return None

    if var_name.upper() not in memory.semantic_profiles:
        profile = jit_inference.infer_profile(
            var_name.upper(),
            domain,
            target_paragraph=target_paragraph,
        )
        if profile is not None:
            memory.semantic_profiles[var_name.upper()] = profile
    return value


def apply_strategy_to_state(
    decision: StrategyDecision,
    base_state: dict,
    var_report,
    memory: SessionMemory,
    rng: random.Random,
    fuzzer_corpus: list | None = None,
    jit_inference=None,
    domains: dict[str, Any] | None = None,
) -> dict:
    """Apply a strategy decision to generate an input state.

    Uses semantic profiles from memory when available to generate
    domain-aware values.
    """
    state = dict(base_state)

    if decision.strategy == "random_exploration":
        # Use semantic profiles for all variables
        for name in var_report.variables:
            jit_value = _maybe_generate_jit_value(
                name,
                memory,
                rng,
                jit_inference=jit_inference,
                domains=domains,
                target_paragraph=decision.target_paragraph,
            )
            if jit_value is not None:
                state[name] = jit_value
                continue
            profile = memory.semantic_profiles.get(name)
            if profile:
                state[name] = generate_value_from_profile(profile, rng)

    elif decision.strategy == "single_var_mutation":
        # Mutate focus variables (or pick one randomly)
        targets = decision.focus_variables or [rng.choice(list(var_report.variables))]
        for var_name in targets[:1]:
            if var_name in decision.focus_values:
                state[var_name] = rng.choice(decision.focus_values[var_name])
                continue
            jit_value = _maybe_generate_jit_value(
                var_name,
                memory,
                rng,
                jit_inference=jit_inference,
                domains=domains,
                target_paragraph=decision.target_paragraph,
            )
            if jit_value is not None:
                state[var_name] = jit_value
            elif var_name in memory.semantic_profiles:
                state[var_name] = generate_value_from_profile(
                    memory.semantic_profiles[var_name], rng)

    elif decision.strategy == "literal_guided":
        # Use focus_values from LLM or condition literals
        for var_name, values in decision.focus_values.items():
            if values and var_name in var_report.variables:
                state[var_name] = rng.choice(values)
        # Also try condition literals for focus variables without explicit values
        for var_name in decision.focus_variables:
            if var_name not in decision.focus_values:
                info = var_report.variables.get(var_name)
                if info and info.condition_literals:
                    state[var_name] = rng.choice(info.condition_literals)

    elif decision.strategy == "crossover":
        # Combine inputs from two corpus entries
        if fuzzer_corpus and len(fuzzer_corpus) >= 2:
            entries = rng.sample(fuzzer_corpus, 2)
            # Take status/flag vars from entry with higher coverage
            a, b = entries
            a_cov = len(a.coverage) if hasattr(a, 'coverage') else 0
            b_cov = len(b.coverage) if hasattr(b, 'coverage') else 0
            primary = a.input_state if a_cov >= b_cov else b.input_state
            secondary = b.input_state if a_cov >= b_cov else a.input_state
            state.update(primary)
            # Crossover: take some vars from secondary
            var_names = list(var_report.variables.keys())
            n_cross = rng.randint(1, max(1, len(var_names) // 4))
            for name in rng.sample(var_names, min(n_cross, len(var_names))):
                if name in secondary:
                    state[name] = secondary[name]

    elif decision.strategy == "error_avoidance_replay":
        # Find an error pattern and minimally mutate to avoid it
        if memory.error_patterns:
            error_entry = rng.choice(memory.error_patterns)
            error_state = error_entry.get("input_state", {})
            state.update(error_state)
            # Flip one variable that might be causing the error
            focus = error_entry.get("focus_variables", [])
            if focus:
                var_name = rng.choice(focus)
                jit_value = _maybe_generate_jit_value(
                    var_name,
                    memory,
                    rng,
                    jit_inference=jit_inference,
                    domains=domains,
                    target_paragraph=decision.target_paragraph,
                )
                if jit_value is not None:
                    state[var_name] = jit_value
                else:
                    profile = memory.semantic_profiles.get(var_name)
                    if profile:
                        state[var_name] = generate_value_from_profile(profile, rng)

    # For directed_walk and stub_outcome_variation, the caller handles
    # these specially via existing infrastructure (path constraints, stub gen).

    # Apply any explicit focus_values not yet applied
    for var_name, values in decision.focus_values.items():
        if values and var_name in var_report.variables:
            if rng.random() < 0.8:  # 80% chance to apply explicit LLM values
                state[var_name] = rng.choice(values)

    return state


# ---------------------------------------------------------------------------
# Session memory updates
# ---------------------------------------------------------------------------

def record_strategy_result(
    memory: SessionMemory,
    strategy: str,
    iterations: int,
    new_paragraphs: int,
    new_branches: int,
    new_edges: int,
    errors: int,
) -> None:
    """Record the outcome of running a strategy batch."""
    memory.strategy_history.append(StrategyResult(
        strategy=strategy,
        iterations=iterations,
        new_paragraphs=new_paragraphs,
        new_branches=new_branches,
        new_edges=new_edges,
        errors=errors,
    ))


def record_error(
    memory: SessionMemory,
    error_msg: str,
    input_state: dict,
    focus_variables: list[str] | None = None,
) -> None:
    """Record an error pattern for LLM analysis."""
    if len(memory.error_patterns) >= 50:
        memory.error_patterns.pop(0)
    memory.error_patterns.append({
        "error": error_msg,
        "input_state": {k: v for k, v in input_state.items()
                        if not k.startswith("_")},
        "focus_variables": focus_variables or [],
    })


def record_coverage_checkpoint(
    memory: SessionMemory,
    iteration: int,
    paragraph_count: int,
    branch_count: int,
) -> None:
    """Record a coverage checkpoint."""
    memory.coverage_timeline.append((iteration, paragraph_count, branch_count))


def should_consult_llm(
    iteration: int,
    memory: SessionMemory,
    stale_counter: int,
    stale_threshold: int,
    regular_interval: int,
    last_coverage_count: int,
    current_coverage_count: int,
) -> str | None:
    """Determine if the LLM should be consulted and why.

    Returns a reason string, or None if no consultation needed.
    Decision cadence from the design doc:
    - Every K iterations (regular_interval)
    - On plateau (stale_counter >= stale_threshold)
    - On coverage milestone (10%+ jump)
    """
    if iteration > 0 and iteration % regular_interval == 0:
        return "regular_interval"

    if stale_counter >= stale_threshold:
        return "plateau"

    if last_coverage_count > 0 and current_coverage_count > 0:
        jump = (current_coverage_count - last_coverage_count) / last_coverage_count
        if jump >= 0.10:
            return "coverage_milestone"

    return None
