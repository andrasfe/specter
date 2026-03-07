# LLM-Guided Monte Carlo Random Walk

## Overview

An intelligent Monte Carlo random walk system that uses an LLM for decision-making to generate inputs for a black-box function (the generated COBOL-to-Python code). Goals: zero errors, maximum coverage.

This replaces the current hardcoded mutation weights and mechanical stale detection in `monte_carlo.py` with adaptive, LLM-driven strategy selection.

## Core Loop

1. **Generate** an input state for the black-box function
2. **Execute** the function, observe: coverage (paragraphs, edges, branches), errors, output
3. **Record** what happened — append to a structured session log
4. **Reflect** — periodically ask the LLM to analyze the log and decide what to do next

## The LLM's Role

The LLM acts as a **strategist**, not a line-by-line executor. It receives:

- Current coverage summary (X/Y paragraphs, Z/W branches)
- Recent iteration results (last N runs: what inputs were tried, what coverage resulted, any errors)
- The "frontier" — covered paragraphs that call uncovered ones
- History of strategies tried and their yield (e.g., "mutating status vars produced 3 new paragraphs over 50 runs, flag flipping produced 0")

The LLM responds with:

- **Which variables to focus on** and what values to try
- **Which strategy to use** (e.g., "try all-success paths", "flip this specific flag", "explore error paths for SQL operations", "do a crossover between run #42 and run #87")
- **When to change approach** (e.g., "status var mutation is exhausted, switch to stub outcome exploration")

## Strategy Registry

A fixed set of available strategies the LLM can select from:

- **Random exploration** — fully random domain-aware generation
- **Single-variable mutation** — pick one var, flip it
- **Literal-guided** — use values harvested from COBOL conditions
- **Directed walk** — target a specific uncovered paragraph by satisfying its gating conditions
- **Stub outcome variation** — change what external operations return
- **Crossover** — combine inputs from two high-coverage runs
- **Error avoidance replay** — take an erroring input, minimally mutate to avoid the error while preserving coverage

## Session Memory

A structured log the LLM can query:

- **Coverage timeline** — coverage % at each checkpoint
- **Strategy effectiveness** — for each strategy, how many new coverage points it produced per N attempts
- **Error patterns** — which input patterns cause errors, so they can be avoided
- **Best inputs** — the corpus of inputs that achieved unique coverage, tagged with which strategy produced them

## Decision Cadence

The LLM is **not called every iteration** (too expensive). Instead:

- **Every K iterations** (e.g., 50-100): LLM reviews progress, picks next strategy and parameters
- **On plateau** (no new coverage for M iterations): LLM is asked for a strategy change with full context of what's been tried
- **On new error type**: LLM is asked how to avoid it while preserving the coverage gain
- **On coverage milestone** (e.g., 10% jump): LLM reviews what worked and whether to double down or diversify

## Goals (in priority order)

1. **Zero errors** — the LLM should learn which input patterns cause errors and steer away from them
2. **Maximum coverage** — paragraphs first, then branches, then edges
3. **Efficiency** — minimize iterations to reach coverage saturation

## Key Difference from Current System

The current system uses **fixed weights** (30% single-var flip, 18% literal-guided, etc.) and **mechanical stale detection** (1000 iterations -> pick nearest uncovered paragraph). The LLM replaces these with **adaptive decisions** based on observed outcomes — it can notice patterns a heuristic can't, like "every time WS-MODE is set to 'B', we reach paragraph X but error in Y, so try 'B' with a different file status."

## Implementation Notes

### Existing Infrastructure to Build On

- `monte_carlo.py` already has: corpus management, energy scoring, mutation strategies, stub outcome generation, coverage tracking (paragraphs, edges, branches), directed fuzzing, recursion avoidance
- `static_analysis.py` already has: call graphs, gating conditions, path constraints, equality constraints
- `variable_extractor.py` already has: variable classification, condition literal harvesting, stub status mapping
- `code_generator.py` already has: branch instrumentation, call depth tracking, instrumented state class

### LLM Integration Points

- The LLM call should be abstracted behind an interface so it can use any provider (Anthropic, OpenAI, etc.)
- Prompt construction should be modular — build context from session memory components
- LLM responses should be structured (JSON) with a defined schema for strategy selection
- Fallback to the current algorithmic approach if the LLM is unavailable or returns invalid responses

### What the LLM Prompt Should Contain

Each LLM call should include:
1. System prompt explaining the fuzzer's purpose and available strategies
2. Current coverage state (paragraphs hit/total, branches hit/total, edges)
3. Frontier paragraphs (covered callers of uncovered paragraphs)
4. Strategy effectiveness history (strategy -> {attempts, new_coverage_gained})
5. Recent error patterns (if any)
6. Available variables with their classifications and known condition literals
7. Request for next strategy selection as structured JSON

### Expected LLM Response Schema

```json
{
  "strategy": "directed_walk | single_var_flip | literal_guided | ...",
  "target_paragraph": "optional - for directed_walk",
  "focus_variables": ["optional - specific vars to mutate"],
  "focus_values": {"VAR-NAME": ["value1", "value2"]},
  "iterations": 50,
  "reasoning": "brief explanation of why this strategy"
}
```
