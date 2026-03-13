from __future__ import annotations

import os
import random
import sys

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tb.ai_tb import create_tb


REQUIRED_PORTS = (
    "clk1",
    "clk1_rst_n",
    "data_in",
    "data_in_valid",
    "clk1_ready",
    "clk2",
    "clk2_rst_n",
    "data_out",
    "data_out_valid",
    "clk2_ready",
)

REQUIRED_INTERNAL_PATHS = (
    "dut.a_reg",
    "dut.have_a",
    "dut.hold_word",
    "dut.hold_valid",
    "dut.out_data_reg",
    "dut.out_valid_reg",
    "dut.clk1_ready",
    "dut.data_out",
    "dut.data_out_valid",
    "dut.af_wrclk",
    "dut.af_wr_rst_n",
    "dut.af_wr_data",
    "dut.af_wr_valid",
    "dut.af_wr_ready",
    "dut.af_rd_clk",
    "dut.af_rd_rst_n",
    "dut.af_rd_data",
    "dut.af_rd_valid",
    "dut.af_rd_ready",
)


async def _read_zero_state(tb) -> dict[str, int]:
    return {
        "a_reg": int(await tb.read_backdoor("dut.a_reg")),
        "have_a": int(await tb.read_backdoor("dut.have_a")),
        "hold_word": int(await tb.read_backdoor("dut.hold_word")),
        "hold_valid": int(await tb.read_backdoor("dut.hold_valid")),
        "out_data_reg": int(await tb.read_backdoor("dut.out_data_reg")),
        "out_valid_reg": int(await tb.read_backdoor("dut.out_valid_reg")),
    }


async def _assert_zero_state(tb) -> None:
    state = await _read_zero_state(tb)
    assert state == {name: 0 for name in state}


async def _run_pack_order_case(tb) -> None:
    first = 1 & tb.mask_in
    second = 0

    await tb.set_output_ready(1)

    accepted, _ = await tb.clk1_step(first, 1)
    assert accepted
    assert int(await tb.read_backdoor("dut.a_reg")) == first
    assert int(await tb.read_backdoor("dut.have_a")) == 1

    accepted, _ = await tb.clk1_step(second, 0)
    assert not accepted
    assert int(await tb.read_backdoor("dut.a_reg")) == first
    assert int(await tb.read_backdoor("dut.have_a")) == 1

    accepted, _ = await tb.clk1_step(second, 1)
    assert accepted
    assert int(await tb.read_backdoor("dut.have_a")) == 0
    assert await tb.drain()
    assert tb.observed_words == [tb.pack_pair(first, second)]

    accepted, _ = await tb.clk1_step(first, 1)
    assert accepted
    await tb.idle_clk1(3)
    assert int(await tb.read_backdoor("dut.a_reg")) == first
    assert int(await tb.read_backdoor("dut.have_a")) == 1

    await tb.send_beats([first])
    await tb.idle_clk1(1)
    assert await tb.drain()
    assert tb.observed_words == [
        tb.pack_pair(first, second),
        tb.pack_pair(first, first),
    ]


async def _drive_random_ready(tb, stop_flag: dict[str, bool], seed: int) -> None:
    rng = random.Random(seed)
    while not stop_flag["stop"]:
        await tb.set_output_ready(0 if rng.randrange(4) == 0 else 1)
        await RisingEdge(tb.top.clk2)
    await tb.set_output_ready(1)


async def _wait_for_dual_buffer(tb, timeout_cycles: int = 400) -> bool:
    for _ in range(timeout_cycles):
        await RisingEdge(tb.top.clk2)
        await ReadOnly()
        if int(tb.top.data_out_valid.value) and int(await tb.read_backdoor("dut.af_rd_valid")):
            return True
    return False


def _expected_param(name: str) -> int | None:
    value = os.getenv(name)
    return None if value is None else int(value, 0)


@cocotb.test()
async def run_basic(dut):
    """Smoke test for end-to-end transfer."""
    tb = await create_tb(dut)
    await tb.set_output_ready(1)
    await tb.send_beats([0, 1 & tb.mask_in, 1 & tb.mask_in, 0])
    await tb.idle_clk1(1)
    assert await tb.drain()
    assert tb.observed_words == tb.expected_words()


@cocotb.test()
async def test_default_interface_and_params(dut):
    """Covers Test ID T-001."""
    tb = await create_tb(dut)

    for name in REQUIRED_PORTS:
        assert hasattr(dut, name)

    assert tb.in_w == 1
    assert tb.out_w == 2
    assert tb.param_in_w == 1
    assert tb.param_out_w == 2
    assert tb.pack_order == 0


@cocotb.test()
async def test_supported_parameterizations(dut):
    """Covers Test ID T-002."""
    tb = await create_tb(dut)

    expect_in_w = _expected_param("TB_EXPECT_IN_W")
    expect_out_w = _expected_param("TB_EXPECT_OUT_W")
    expect_pack_order = _expected_param("TB_EXPECT_PACK_ORDER")
    expect_non_default = os.getenv("TB_EXPECT_NON_DEFAULT") == "1"

    assert tb.param_in_w >= 1
    assert tb.param_out_w == 2 * tb.param_in_w
    assert tb.pack_order in (0, 1)
    assert tb.in_w == tb.param_in_w
    assert tb.out_w == tb.param_out_w
    if expect_in_w is not None:
        assert tb.param_in_w == expect_in_w
    if expect_out_w is not None:
        assert tb.param_out_w == expect_out_w
    if expect_pack_order is not None:
        assert tb.pack_order == expect_pack_order
    if expect_non_default:
        assert (tb.param_in_w, tb.param_out_w, tb.pack_order) != (1, 2, 0)


@cocotb.test()
async def test_invalid_parameter_rejected(dut):
    """Covers Test ID T-003. Illegal elaborations are expected to fail before cocotb starts."""
    tb = await create_tb(dut)

    assert os.getenv("EXPECT_INVALID_CONFIG") != "1"
    assert tb.param_in_w >= 1
    assert tb.param_out_w == 2 * tb.param_in_w
    assert tb.pack_order in (0, 1)


@cocotb.test()
async def test_named_state_visibility_and_reset_values(dut):
    """Covers Test ID T-004."""
    tb = await create_tb(dut)

    await tb.set_clk1_reset(0)
    await tb.set_clk2_reset(0)
    await tb.settle()
    await ReadOnly()

    for path in REQUIRED_INTERNAL_PATHS:
        await tb.read_backdoor(path)

    await _assert_zero_state(tb)
    assert int(dut.data_out.value) == 0
    assert int(dut.data_out_valid.value) == 0


@cocotb.test()
async def test_afifo_clock_reset_mapping(dut):
    """Covers Test ID T-005."""
    tb = await create_tb(dut)

    await tb.set_clk1_reset(0)
    await tb.set_clk2_reset(0)
    await tb.settle()
    await ReadOnly()
    assert int(await tb.read_backdoor("dut.af_wr_rst_n")) == int(dut.clk1_rst_n.value)
    assert int(await tb.read_backdoor("dut.af_rd_rst_n")) == int(dut.clk2_rst_n.value)

    await tb.set_clk1_reset(1)
    await tb.set_clk2_reset(1)
    for _ in range(4):
        await RisingEdge(dut.clk1)
        await ReadOnly()
        assert int(await tb.read_backdoor("dut.af_wrclk")) == int(dut.clk1.value)
        assert int(await tb.read_backdoor("dut.af_wr_rst_n")) == int(dut.clk1_rst_n.value)
        assert int(await tb.read_backdoor("dut.af_rd_clk")) == int(dut.clk2.value)
        assert int(await tb.read_backdoor("dut.af_rd_rst_n")) == int(dut.clk2_rst_n.value)


@cocotb.test()
async def test_pack_order_zero_acceptance_and_tail(dut):
    """Covers Test ID T-006."""
    tb = await create_tb(dut)
    if tb.pack_order != 0:
        return
    await _run_pack_order_case(tb)


@cocotb.test()
async def test_pack_order_one_acceptance_and_tail(dut):
    """Covers Test ID T-007."""
    tb = await create_tb(dut)
    if tb.pack_order != 1:
        return
    await _run_pack_order_case(tb)


@cocotb.test()
async def test_write_side_hold_priority_and_ready_rule(dut):
    """Covers Test ID T-008."""
    tb = await create_tb(dut)

    await tb.set_output_ready(0)
    await tb.fill_until_hold_valid()
    await tb.settle()
    await ReadOnly()

    hold_word = int(await tb.read_backdoor("dut.hold_word"))
    hold_valid = int(await tb.read_backdoor("dut.hold_valid"))
    have_a = int(await tb.read_backdoor("dut.have_a"))

    assert hold_valid == 1
    assert int(await tb.read_backdoor("dut.af_wr_valid")) == 1
    assert int(await tb.read_backdoor("dut.af_wr_data")) == hold_word
    assert int(dut.clk1_ready.value) == (1 if have_a == 0 else 0)

    if have_a == 0:
        accepted, _ = await tb.clk1_step(1 & tb.mask_in, 1)
        assert accepted
        assert int(await tb.read_backdoor("dut.have_a")) == 1
        assert int(dut.clk1_ready.value) == 0
        assert int(await tb.read_backdoor("dut.af_wr_data")) == hold_word

    await tb.reset()
    await tb.set_output_ready(1)

    first = 1 & tb.mask_in
    second = 0
    accepted, _ = await tb.clk1_step(first, 1)
    assert accepted
    assert int(await tb.read_backdoor("dut.have_a")) == 1
    assert int(await tb.read_backdoor("dut.hold_valid")) == 0
    assert int(dut.clk1_ready.value) == 1

    await tb.drive_input(second, 1)
    await ReadOnly()
    ready_before = int(dut.clk1_ready.value)
    rst_before = int(dut.clk1_rst_n.value)
    assert ready_before == 1
    assert int(await tb.read_backdoor("dut.af_wr_valid")) == 1
    assert int(await tb.read_backdoor("dut.af_wr_data")) == tb.pack_pair(first, second)
    assert int(await tb.read_backdoor("dut.hold_valid")) == 0

    await RisingEdge(dut.clk1)
    await ReadOnly()
    if rst_before and ready_before and int(dut.clk1_rst_n.value):
        tb.accepted_beats.append(second & tb.mask_in)
    await tb.idle_input()


@cocotb.test()
async def test_random_backpressure_preserves_sequence(dut):
    """Covers Test ID T-009."""
    tb = await create_tb(dut)
    beats = [index & tb.mask_in for index in range(96)]
    stop_flag = {"stop": False}
    ready_task = cocotb.start_soon(_drive_random_ready(tb, stop_flag, seed=20260312))

    await tb.send_beats(beats, max_wait_cycles_per_beat=4096)
    await tb.idle_clk1(1)
    stop_flag["stop"] = True
    await ready_task

    assert await tb.drain(timeout_cycles=8000)
    assert tb.observed_words == tb.expected_words()


@cocotb.test()
async def test_output_mapping_and_af_rd_ready_rule(dut):
    """Covers Test ID T-010."""
    tb = await create_tb(dut)

    await tb.settle()
    await ReadOnly()
    assert int(await tb.read_backdoor("dut.out_valid_reg")) == 0
    assert int(await tb.read_backdoor("dut.af_rd_ready")) == 1

    expected_word = await tb.block_and_load_output(1 & tb.mask_in, 0)
    assert int(await tb.read_backdoor("dut.out_data_reg")) == expected_word
    assert int(await tb.read_backdoor("dut.out_valid_reg")) == 1
    assert int(dut.data_out.value) == int(await tb.read_backdoor("dut.out_data_reg"))
    assert int(dut.data_out_valid.value) == int(await tb.read_backdoor("dut.out_valid_reg"))
    assert int(await tb.read_backdoor("dut.af_rd_ready")) == 0

    await tb.set_output_ready(1)
    await tb.settle()
    await ReadOnly()
    assert int(await tb.read_backdoor("dut.af_rd_ready")) == 1


@cocotb.test()
async def test_same_cycle_refill_no_bubble(dut):
    """Covers Test ID T-011."""
    tb = await create_tb(dut)

    await tb.set_output_ready(0)
    await tb.send_beats([1 & tb.mask_in, 0, 0, 1 & tb.mask_in])
    await tb.idle_clk1(1)

    assert await _wait_for_dual_buffer(tb)
    current_word = int(dut.data_out.value)
    next_word = int(await tb.read_backdoor("dut.af_rd_data"))

    await tb.set_output_ready(1)
    await tb.settle()
    await ReadOnly()
    assert int(await tb.read_backdoor("dut.af_rd_ready")) == 1

    await RisingEdge(dut.clk2)
    await ReadOnly()
    assert int(await tb.read_backdoor("dut.out_valid_reg")) == 1
    assert int(dut.data_out_valid.value) == 1
    assert int(await tb.read_backdoor("dut.out_data_reg")) == next_word
    assert int(dut.data_out.value) == next_word
    assert current_word != next_word

    assert await tb.drain()
    assert tb.observed_words == tb.expected_words()


@cocotb.test()
async def test_output_stable_while_blocked(dut):
    """Covers Test ID T-012."""
    tb = await create_tb(dut)

    expected_word = await tb.block_and_load_output(1 & tb.mask_in, 0)
    for _ in range(6):
        await RisingEdge(dut.clk2)
        await ReadOnly()
        assert int(dut.data_out_valid.value) == 1
        assert int(dut.data_out.value) == expected_word


@cocotb.test()
async def test_boundary_rate_sustained_throughput(dut):
    """Covers Test ID T-013."""
    tb = await create_tb(dut)

    assert tb.param_in_w == 1
    assert tb.param_out_w == 2
    await tb.set_output_ready(1)

    beats = [index & tb.mask_in for index in range(64)]
    accepted = []
    for beat in beats:
        took, _ = await tb.clk1_step(beat, 1)
        accepted.append(took)
    await tb.idle_clk1(1)

    assert all(accepted)
    assert await tb.wait_output_valid()
    for _ in range(10):
        await RisingEdge(dut.clk2)
        await ReadOnly()
        assert int(dut.data_out_valid.value) == 1

    assert await tb.drain(timeout_cycles=8000)
    assert tb.observed_words == tb.expected_words()


@cocotb.test()
async def test_clk1_async_reset_discards_partial_and_unwritten_data(dut):
    """Covers Test ID T-014."""
    tb = await create_tb(dut)

    await tb.set_output_ready(1)
    accepted, _ = await tb.clk1_step(1 & tb.mask_in, 1)
    assert accepted
    assert int(await tb.read_backdoor("dut.have_a")) == 1

    await tb.assert_clk1_reset_between_edges()
    await ReadOnly()
    assert int(await tb.read_backdoor("dut.have_a")) == 0
    assert int(await tb.read_backdoor("dut.a_reg")) == 0
    assert int(await tb.read_backdoor("dut.af_wr_valid")) == 0

    for _ in range(2):
        accepted, _ = await tb.clk1_step(1 & tb.mask_in, 1)
        assert not accepted
        assert int(await tb.read_backdoor("dut.af_wr_valid")) == 0

    await tb.release_clk1_reset_between_edges()
    tb.clear_scoreboards()
    await tb.send_beats([0, 1 & tb.mask_in])
    await tb.idle_clk1(1)
    assert await tb.drain()
    assert tb.observed_words == [tb.pack_pair(0, 1 & tb.mask_in)]

    await tb.reset()
    await tb.set_output_ready(0)
    await tb.fill_until_hold_valid()
    assert int(await tb.read_backdoor("dut.hold_valid")) == 1

    await tb.assert_clk1_reset_between_edges()
    await ReadOnly()
    assert int(await tb.read_backdoor("dut.hold_valid")) == 0
    assert int(await tb.read_backdoor("dut.hold_word")) == 0
    assert int(await tb.read_backdoor("dut.af_wr_valid")) == 0


@cocotb.test()
async def test_clk2_async_reset_invalidates_output(dut):
    """Covers Test ID T-015."""
    tb = await create_tb(dut)

    await tb.block_and_load_output(1 & tb.mask_in, 0)
    assert int(dut.data_out_valid.value) == 1

    await tb.assert_clk2_reset_between_edges()
    await ReadOnly()
    assert int(dut.data_out_valid.value) == 0
    assert int(dut.data_out.value) == 0
    assert int(await tb.read_backdoor("dut.out_valid_reg")) == 0
    assert int(await tb.read_backdoor("dut.out_data_reg")) == 0

    for _ in range(2):
        await RisingEdge(dut.clk2)
        await ReadOnly()
        assert int(dut.data_out_valid.value) == 0
        assert int(dut.data_out.value) == 0

    await tb.release_clk2_reset_between_edges()
    await ReadOnly()
    assert int(dut.data_out_valid.value) == 0

    tb.clear_scoreboards()
    await tb.set_output_ready(1)
    await tb.send_beats([1 & tb.mask_in, 1 & tb.mask_in])
    await tb.idle_clk1(1)
    assert await tb.wait_output_valid()
    assert await tb.drain()
    assert tb.observed_words == [tb.pack_pair(1 & tb.mask_in, 1 & tb.mask_in)]
