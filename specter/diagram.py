"""Generate Mermaid sequence and flow diagrams from execution traces."""

from __future__ import annotations

from collections import Counter
from pathlib import Path


def generate_sequence_diagram(
    call_events: list[tuple],
    max_events: int = 200,
    title: str = "Execution Sequence",
) -> str:
    """Generate a Mermaid sequence diagram from call events.

    Each event is (type, para_name, depth, caller) where type is 'enter' or 'exit'.
    """
    lines = ["sequenceDiagram"]
    lines.append(f"    Note over Program: {title}")

    # Collect participants in order of first appearance
    seen = []
    for event_type, name, depth, caller in call_events[:max_events]:
        if event_type == "enter" and name not in seen:
            seen.append(name)
    # Abbreviate long names for readability
    aliases = {}
    for name in seen:
        alias = _abbreviate(name)
        aliases[name] = alias
        lines.append(f"    participant {alias} as {name}")

    # Generate arrows from call events
    event_count = 0
    for event_type, name, depth, caller in call_events:
        if event_count >= max_events:
            lines.append("    Note over Program: ... truncated ...")
            break
        if event_type == "enter" and caller is not None:
            src = aliases.get(caller, caller)
            dst = aliases.get(name, name)
            if src != dst:
                lines.append(f"    {src}->>+{dst}: call")
                event_count += 1
        elif event_type == "exit" and caller is None:
            # Find who called this para — look for the matching enter
            dst = aliases.get(name, name)
            # On exit, the call stack has already popped, so we emit return
            # We track returns by looking at depth changes
            if depth > 1:
                # Find caller from earlier events
                parent = _find_caller(call_events, name, event_count)
                if parent:
                    src = aliases.get(parent, parent)
                    if src != dst:
                        lines.append(f"    {dst}-->>-{src}: return")
                        event_count += 1
        event_count += 1

    return "\n".join(lines)


def _find_caller(call_events: list[tuple], para_name: str, current_idx: int) -> str | None:
    """Walk backwards to find who called this paragraph."""
    for i in range(current_idx - 1, -1, -1):
        ev_type, name, depth, caller = call_events[i]
        if ev_type == "enter" and name == para_name and caller:
            return caller
    return None


def generate_flow_diagram(
    call_events: list[tuple],
    title: str = "Execution Flow",
) -> str:
    """Generate a Mermaid flowchart from call events showing call relationships with counts."""
    # Build edge counts from enter events
    edges: Counter[tuple[str, str]] = Counter()
    node_hits: Counter[str] = Counter()

    for event_type, name, depth, caller in call_events:
        if event_type == "enter":
            node_hits[name] += 1
            if caller and caller != name:
                edges[(caller, name)] += 1

    lines = ["flowchart TD"]
    lines.append(f"    %% {title}")

    # Declare nodes with hit counts
    for name in node_hits:
        alias = _abbreviate(name)
        lines.append(f"    {alias}[\"{name}<br/>{node_hits[name]}x\"]")

    # Declare edges with counts
    for (src, dst), count in sorted(edges.items(), key=lambda x: -x[1]):
        sa = _abbreviate(src)
        da = _abbreviate(dst)
        if count > 1:
            lines.append(f"    {sa} -->|{count}x| {da}")
        else:
            lines.append(f"    {sa} --> {da}")

    return "\n".join(lines)


def generate_aggregated_flow(
    all_call_events: list[list[tuple]],
    title: str = "Aggregated Call Flow",
    top_n: int = 50,
) -> str:
    """Generate a Mermaid flowchart aggregated across multiple iterations."""
    edges: Counter[tuple[str, str]] = Counter()
    node_hits: Counter[str] = Counter()

    for events in all_call_events:
        for event_type, name, depth, caller in events:
            if event_type == "enter":
                node_hits[name] += 1
                if caller and caller != name:
                    edges[(caller, name)] += 1

    # Keep only top N nodes by hit count to avoid diagram explosion
    top_nodes = {name for name, _ in node_hits.most_common(top_n)}

    lines = ["flowchart TD"]
    lines.append(f"    %% {title}")

    for name, count in node_hits.most_common(top_n):
        alias = _abbreviate(name)
        lines.append(f"    {alias}[\"{name}<br/>{count}x\"]")

    for (src, dst), count in sorted(edges.items(), key=lambda x: -x[1]):
        if src in top_nodes and dst in top_nodes:
            sa = _abbreviate(src)
            da = _abbreviate(dst)
            if count > 1:
                lines.append(f"    {sa} -->|{count}x| {da}")
            else:
                lines.append(f"    {sa} --> {da}")

    return "\n".join(lines)


def generate_single_iteration_sequence(
    call_events: list[tuple],
    max_events: int = 300,
    title: str = "Single Iteration Sequence",
) -> str:
    """Generate a clean sequence diagram for one iteration.

    Shows the actual call/return flow with proper nesting.
    """
    lines = ["sequenceDiagram"]
    lines.append(f"    Note right of Entry: {title}")
    lines.append("    participant Entry as Program Entry")

    # Collect participants in order
    seen = []
    for event_type, name, depth, caller in call_events[:max_events]:
        if event_type == "enter" and name not in seen:
            seen.append(name)

    aliases = {}
    for name in seen:
        alias = _abbreviate(name)
        aliases[name] = alias
        lines.append(f"    participant {alias} as {name}")

    count = 0
    # Track active activations for return arrows
    stack = []
    for event_type, name, depth, caller in call_events:
        if count >= max_events:
            lines.append("    Note over Entry: ... truncated ...")
            break

        if event_type == "enter":
            dst = aliases.get(name, name)
            if caller:
                src = aliases.get(caller, caller)
            else:
                src = "Entry"
            if src != dst:
                lines.append(f"    {src}->>+{dst}: ")
            stack.append((name, caller))
            count += 1

        elif event_type == "exit":
            dst = aliases.get(name, name)
            # Find the matching caller
            if stack:
                for i in range(len(stack) - 1, -1, -1):
                    if stack[i][0] == name:
                        _, caller_name = stack.pop(i)
                        if caller_name:
                            src = aliases.get(caller_name, caller_name)
                        else:
                            src = "Entry"
                        if src != dst:
                            lines.append(f"    {dst}-->>-{src}: ")
                        count += 1
                        break

    return "\n".join(lines)


def write_diagrams(
    call_events: list[tuple],
    output_dir: Path,
    program_name: str,
    all_iterations_events: list[list[tuple]] | None = None,
) -> list[Path]:
    """Write all diagram files and return paths created."""
    output_dir.mkdir(parents=True, exist_ok=True)
    created = []

    # Single iteration sequence diagram (first/representative run)
    if call_events:
        seq_path = output_dir / f"{program_name}_sequence.mmd"
        seq_content = generate_single_iteration_sequence(
            call_events,
            title=f"{program_name} Execution Sequence",
        )
        seq_path.write_text(seq_content)
        created.append(seq_path)

        # Single iteration flow
        flow_path = output_dir / f"{program_name}_flow.mmd"
        flow_content = generate_flow_diagram(
            call_events,
            title=f"{program_name} Call Flow",
        )
        flow_path.write_text(flow_content)
        created.append(flow_path)

    # Aggregated flow across all iterations
    if all_iterations_events:
        agg_path = output_dir / f"{program_name}_aggregated_flow.mmd"
        agg_content = generate_aggregated_flow(
            all_iterations_events,
            title=f"{program_name} Aggregated Call Flow ({len(all_iterations_events)} iterations)",
        )
        agg_path.write_text(agg_content)
        created.append(agg_path)

    return created


def _abbreviate(name: str) -> str:
    """Create a valid Mermaid node ID from a paragraph name."""
    # Replace hyphens with underscores, strip non-alphanumeric
    return name.replace("-", "_").replace(" ", "_")
