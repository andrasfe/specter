from __future__ import annotations

from pathlib import Path

from specter.memory_models import MemoryState, SuccessState
from specter.memory_store import MemoryStore, derive_memory_dir


def test_derive_memory_dir_from_store_stem(tmp_path: Path):
    store = tmp_path / "cases.jsonl"
    memory_dir = derive_memory_dir(store)
    assert memory_dir == tmp_path / "cases_memory"


def test_memory_store_round_trip_state(tmp_path: Path):
    store = MemoryStore(tmp_path / "run_memory")
    state = MemoryState()
    state.meta["program_id"] = "TESTPROG"
    state.successes.append(
        SuccessState(
            target="baseline",
            input_state={"WS-CODE": "00"},
            stub_outcomes=[["READ:IN", [["FS-IN", "00"]]]],
            paragraphs_hit=["MAIN"],
            branches_hit=["1:T"],
            timestamp=123.0,
        )
    )

    store.save_state(state)
    loaded = store.load_state()

    assert loaded.meta["program_id"] == "TESTPROG"
    assert len(loaded.successes) == 1
    assert loaded.successes[0].target == "baseline"
    assert loaded.successes[0].input_state["WS-CODE"] == "00"


def test_memory_store_prune_and_checkpoint(tmp_path: Path):
    store = MemoryStore(tmp_path / "run_memory", max_successes=2)
    state = MemoryState()

    for idx in range(3):
        store.append_success(
            state,
            SuccessState(
                target=f"t{idx}",
                input_state={"I": idx},
                timestamp=float(idx),
            ),
        )

    assert len(state.successes) == 2
    assert [s.target for s in state.successes] == ["t1", "t2"]

    store.checkpoint(state, round_num=7, tc_count=42, extra_meta={"mode": "python"})
    loaded = store.load_state()
    assert loaded.meta["last_round"] == 7
    assert loaded.meta["last_tc_count"] == 42
    assert loaded.meta["mode"] == "python"
