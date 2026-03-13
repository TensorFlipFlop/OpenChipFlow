from __future__ import annotations

import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ReadOnly, RisingEdge, Timer


class AITestbench:
    def __init__(self, dut):
        self.top = dut
        self.core = dut.dut
        self.in_w = len(dut.data_in)
        self.out_w = len(dut.data_out)
        self.mask_in = (1 << self.in_w) - 1
        self.mask_out = (1 << self.out_w) - 1
        self.param_in_w = self._read_param("IN_W", self.in_w)
        self.param_out_w = self._read_param("OUT_W", self.out_w)
        self.pack_order = self._read_param("PACK_ORDER", 0)
        self.clk1_period_ps = 10_000
        self.clk2_period_ps = 20_000
        self.accepted_beats: list[int] = []
        self.observed_words: list[int] = []
        self._clocks_started = False
        self._monitor_task = None
        self._capture_outputs = False

    def _read_param(self, name: str, default: int) -> int:
        for owner in (self.core, self.top):
            try:
                handle = getattr(owner, name)
            except AttributeError:
                continue
            value = handle.value if hasattr(handle, "value") else handle
            try:
                return int(value)
            except TypeError:
                continue
        env_value = os.getenv(name)
        return int(env_value, 0) if env_value is not None else default

    def _resolve(self, path: str):
        node = self.top
        for part in path.split("."):
            node = getattr(node, part)
        return node

    async def settle(self) -> None:
        await Timer(1, "ps")

    async def start_clocks(
        self,
        clk1_period_ps: int = 10_000,
        clk2_period_ps: int = 20_000,
    ) -> None:
        if self._clocks_started:
            return
        self.clk1_period_ps = clk1_period_ps
        self.clk2_period_ps = clk2_period_ps
        cocotb.start_soon(Clock(self.top.clk1, clk1_period_ps, unit="ps").start())
        cocotb.start_soon(Clock(self.top.clk2, clk2_period_ps, unit="ps").start())
        self._clocks_started = True

    def start_output_monitor(self) -> None:
        if self._monitor_task is None:
            self._monitor_task = cocotb.start_soon(self._monitor_outputs())

    async def _monitor_outputs(self) -> None:
        await ReadOnly()
        stable_data = int(self.top.data_out.value) & self.mask_out
        stable_valid = int(self.top.data_out_valid.value)
        while True:
            await RisingEdge(self.top.clk2)
            await ReadOnly()
            ready_now = int(self.top.clk2_ready.value)
            rst_now = int(self.top.clk2_rst_n.value)
            if self._capture_outputs and rst_now and stable_valid and ready_now:
                self.observed_words.append(stable_data)
            stable_data = int(self.top.data_out.value) & self.mask_out
            stable_valid = int(self.top.data_out_valid.value)

    def clear_scoreboards(self) -> None:
        self.accepted_beats.clear()
        self.observed_words.clear()

    async def reset(self, clk1_cycles: int = 3, clk2_cycles: int = 3) -> None:
        self._capture_outputs = False
        await self.settle()
        self.top.clk1_rst_n.value = 0
        self.top.clk2_rst_n.value = 0
        self.top.data_in.value = 0
        self.top.data_in_valid.value = 0
        self.top.clk2_ready.value = 0
        for _ in range(clk1_cycles):
            await RisingEdge(self.top.clk1)
        for _ in range(clk2_cycles):
            await RisingEdge(self.top.clk2)
        await self.settle()
        self.top.clk1_rst_n.value = 1
        self.top.clk2_rst_n.value = 1
        self.clear_scoreboards()
        await self.settle()
        self._capture_outputs = True

    async def drive_input(self, data: int = 0, valid: int = 0) -> None:
        await self.settle()
        self.top.data_in.value = int(data) & self.mask_in
        self.top.data_in_valid.value = int(valid)

    async def idle_input(self) -> None:
        await self.drive_input(0, 0)

    async def set_output_ready(self, value: int) -> None:
        await self.settle()
        self.top.clk2_ready.value = int(value)

    async def set_clk1_reset(self, value: int) -> None:
        await self.settle()
        self.top.clk1_rst_n.value = int(value)

    async def set_clk2_reset(self, value: int) -> None:
        await self.settle()
        self.top.clk2_rst_n.value = int(value)

    async def assert_clk1_reset_between_edges(self) -> None:
        await RisingEdge(self.top.clk1)
        await Timer(max(1, self.clk1_period_ps // 4), "ps")
        self.top.clk1_rst_n.value = 0
        await self.settle()

    async def release_clk1_reset_between_edges(self) -> None:
        await RisingEdge(self.top.clk1)
        await Timer(max(1, self.clk1_period_ps // 4), "ps")
        self.top.clk1_rst_n.value = 1
        await self.settle()

    async def assert_clk2_reset_between_edges(self) -> None:
        await RisingEdge(self.top.clk2)
        await Timer(max(1, self.clk2_period_ps // 4), "ps")
        self.top.clk2_rst_n.value = 0
        await self.settle()

    async def release_clk2_reset_between_edges(self) -> None:
        await RisingEdge(self.top.clk2)
        await Timer(max(1, self.clk2_period_ps // 4), "ps")
        self.top.clk2_rst_n.value = 1
        await self.settle()

    async def read_backdoor(self, path: str) -> int:
        return int(self._resolve(path).value)

    async def clk1_step(self, data: int = 0, valid: int = 0) -> tuple[bool, int]:
        await self.drive_input(data, valid)
        await ReadOnly()
        ready_before = int(self.top.clk1_ready.value)
        rst_before = int(self.top.clk1_rst_n.value)
        await RisingEdge(self.top.clk1)
        await ReadOnly()
        rst_after = int(self.top.clk1_rst_n.value)
        accepted = bool(valid and ready_before and rst_before and rst_after)
        if accepted:
            self.accepted_beats.append(int(data) & self.mask_in)
        return accepted, ready_before

    async def idle_clk1(self, cycles: int = 1) -> None:
        for _ in range(cycles):
            await self.clk1_step(0, 0)

    async def wait_clk2_cycles(self, cycles: int = 1) -> None:
        for _ in range(cycles):
            await RisingEdge(self.top.clk2)
            await ReadOnly()

    async def send_beats(
        self,
        beats: list[int],
        max_wait_cycles_per_beat: int = 1024,
    ) -> None:
        for index, beat in enumerate(beats):
            for _ in range(max_wait_cycles_per_beat):
                accepted, _ = await self.clk1_step(beat, 1)
                if accepted:
                    break
            else:
                raise AssertionError(f"input stalled before beat index {index}")

    def pack_pair(self, first: int, second: int) -> int:
        first &= self.mask_in
        second &= self.mask_in
        if self.pack_order == 0:
            return ((first << self.in_w) | second) & self.mask_out
        if self.pack_order == 1:
            return ((second << self.in_w) | first) & self.mask_out
        raise AssertionError(f"unsupported PACK_ORDER={self.pack_order}")

    def expected_words(self) -> list[int]:
        return [
            self.pack_pair(self.accepted_beats[index], self.accepted_beats[index + 1])
            for index in range(0, len(self.accepted_beats) - 1, 2)
        ]

    async def wait_output_valid(self, timeout_cycles: int = 400) -> bool:
        await ReadOnly()
        if int(self.top.data_out_valid.value):
            return True
        for _ in range(timeout_cycles):
            await RisingEdge(self.top.clk2)
            await ReadOnly()
            if int(self.top.data_out_valid.value):
                return True
        return False

    async def wait_observed(self, count: int, timeout_cycles: int = 400) -> bool:
        if len(self.observed_words) >= count:
            return True
        for _ in range(timeout_cycles):
            await RisingEdge(self.top.clk2)
            await ReadOnly()
            if len(self.observed_words) >= count:
                return True
        return False

    async def wait_backdoor(
        self,
        path: str,
        value: int,
        clock_name: str,
        timeout_cycles: int = 400,
    ) -> bool:
        clock = self.top.clk1 if clock_name == "clk1" else self.top.clk2
        if int(await self.read_backdoor(path)) == int(value):
            return True
        for _ in range(timeout_cycles):
            await RisingEdge(clock)
            await ReadOnly()
            if int(await self.read_backdoor(path)) == int(value):
                return True
        return False

    async def fill_until_hold_valid(self, max_cycles: int = 4096) -> None:
        beat = 0
        for _ in range(max_cycles):
            await self.clk1_step(beat, 1)
            if int(await self.read_backdoor("dut.hold_valid")):
                await self.idle_input()
                return
            beat = (beat + 1) & self.mask_in
        raise AssertionError("hold_valid did not assert")

    async def block_and_load_output(self, first: int, second: int) -> int:
        expected_word = self.pack_pair(first, second)
        await self.set_output_ready(0)
        await self.send_beats([first, second])
        await self.idle_input()
        if not await self.wait_output_valid():
            raise AssertionError("data_out_valid did not assert")
        return expected_word

    async def drain(self, timeout_cycles: int = 4000) -> bool:
        await self.set_output_ready(1)
        quiescent_cycles = 0
        for _ in range(timeout_cycles):
            await RisingEdge(self.top.clk2)
            await ReadOnly()
            idle = (
                int(self.top.data_out_valid.value) == 0
                and int(await self.read_backdoor("dut.hold_valid")) == 0
                and int(await self.read_backdoor("dut.have_a")) == 0
                and int(await self.read_backdoor("dut.af_rd_valid")) == 0
            )
            complete = len(self.observed_words) >= len(self.expected_words())
            quiescent_cycles = quiescent_cycles + 1 if idle and complete else 0
            if quiescent_cycles >= 4:
                return True
        return False


async def create_tb(dut) -> AITestbench:
    tb = AITestbench(dut)
    await tb.start_clocks()
    await tb.reset()
    tb.start_output_monitor()
    return tb
