"""Tests for the backward slicer."""

from specter.backward_slicer import backward_slice


SAMPLE_MODULE = '''\
def para_TEST(state):
    """Paragraph TEST (lines 1-20)."""
    _d = state.get('_call_depth', 0) + 1
    state['_call_depth'] = _d
    if _d > _CALL_DEPTH_LIMIT:
        state['_call_depth'] = _d - 1
        return
    try:
        state._enter_para('TEST')
        state['WS-CODE'] = state.get('INPUT-CODE', '')
        _apply_stub_outcome(state, 'DLI')
        state['STATUS'] = state.get('DIBSTAT', '')
        if state['STATUS-OK']:
            state.get('_branches', set()).add(1)
            state['RESULT'] = 'OK'
        elif state['SEGMENT-NOT-FOUND']:
            state.get('_branches', set()).add(2)
            state['RESULT'] = 'NOTFOUND'
        else:
            state.get('_branches', set()).add(3)
            state['RESULT'] = 'ERROR'
        for _bid in [1, 2, 3]:
            if _bid != _eval_taken_0:
                state.get('_branches', set()).add(-_bid)
        if _to_num(state['AMOUNT']) > _to_num(state['LIMIT']):
            state.get('_branches', set()).add(4)
            state['OVER-LIMIT'] = True
        else:
            state.get('_branches', set()).add(-4)
            state['OVER-LIMIT'] = False
    finally:
        state._exit_para('TEST')
        state['_call_depth'] = state.get('_call_depth', 1) - 1
'''


class TestBackwardSlice:
    def test_basic_branch_found(self):
        sl = backward_slice(SAMPLE_MODULE, 1)
        assert "# <-- TARGET" in sl
        assert "add(1)" in sl

    def test_includes_condition(self):
        sl = backward_slice(SAMPLE_MODULE, 2)
        assert "SEGMENT-NOT-FOUND" in sl
        assert "# <-- TARGET" in sl

    def test_includes_stub_call(self):
        sl = backward_slice(SAMPLE_MODULE, 2)
        assert "_apply_stub_outcome" in sl or "DLI" in sl

    def test_includes_function_def(self):
        sl = backward_slice(SAMPLE_MODULE, 1)
        assert sl.startswith("def para_TEST(state):")

    def test_strips_boilerplate(self):
        sl = backward_slice(SAMPLE_MODULE, 1)
        assert "_call_depth" not in sl
        assert "_enter_para" not in sl
        assert "_exit_para" not in sl

    def test_negative_branch(self):
        sl = backward_slice(SAMPLE_MODULE, -4)
        assert "# <-- TARGET" in sl
        assert "add(-4)" in sl

    def test_branch_not_found(self):
        sl = backward_slice(SAMPLE_MODULE, 999)
        assert sl == ""

    def test_empty_source(self):
        sl = backward_slice("", 1)
        assert sl == ""

    def test_max_lines_respected(self):
        sl = backward_slice(SAMPLE_MODULE, 2, max_lines=5)
        assert len(sl.splitlines()) <= 5

    def test_backward_trace_includes_assignment(self):
        sl = backward_slice(SAMPLE_MODULE, 4)
        # Branch 4 checks AMOUNT > LIMIT, should show the condition
        assert "AMOUNT" in sl or "LIMIT" in sl

    def test_real_copaua0c(self):
        """Test on real generated code."""
        try:
            code = open("examples/COPAUA0C.cbl.py").read()
        except FileNotFoundError:
            return  # skip if not available

        # Branch 21: SEGMENT-NOT-FOUND in EVALUATE
        sl = backward_slice(code, 21, max_lines=40)
        assert sl, "Slice should not be empty"
        assert "SEGMENT-NOT-FOUND" in sl
        assert "# <-- TARGET" in sl

        # Branch 26: amount comparison
        sl2 = backward_slice(code, 26, max_lines=40)
        assert sl2, "Slice should not be empty"
        assert "WS-TRANSACTION-AMT" in sl2 or "WS-AVAILABLE-AMT" in sl2

    def test_evaluate_negative_probe(self):
        """Negative EVALUATE branch via for-loop pattern."""
        sl = backward_slice(SAMPLE_MODULE, -2)
        # -2 is in the for _bid loop
        assert sl  # Should find something (via the for-loop pattern)
