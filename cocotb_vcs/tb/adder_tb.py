import os
import random
from collections import deque

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge


class AdderTB:
    """Reusable cocotb testbench for adder."""

    def __init__(self, dut, seed=None, clock_period_ns=5):
        self.dut = dut
        self.clock_period_ns = clock_period_ns
        self.seed = seed if seed is not None else int(os.getenv("SEED", "42"))
        self.rng = random.Random(self.seed)

        self.w = len(dut.a)
        self.mask = (1 << self.w) - 1
        self.expected = deque()

    async def start(self):
        cocotb.start_soon(Clock(self.dut.clk, self.clock_period_ns, unit="ns").start())
        await self.reset()

    async def reset(self, cycles=5):
        dut = self.dut
        dut.rst_n.value = 0
        dut.in_valid.value = 0
        dut.out_ready.value = 0
        dut.a.value = 0
        dut.b.value = 0
        for _ in range(cycles):
            await RisingEdge(dut.clk)
        dut.rst_n.value = 1
        for _ in range(2):
            await RisingEdge(dut.clk)

    async def send(self, a, b):
        """Wait for in_ready then send a/b for one cycle."""
        dut = self.dut
        while True:
            await RisingEdge(dut.clk)
            if int(dut.in_ready.value):
                break
        dut.a.value = a
        dut.b.value = b
        dut.in_valid.value = 1
        await RisingEdge(dut.clk)
        dut.in_valid.value = 0
        self.expected.append(a + b)

    async def sink(self, ready_gen=None):
        """Default sink with random backpressure; checks outputs."""
        dut = self.dut
        while True:
            await RisingEdge(dut.clk)
            ready = ready_gen() if ready_gen else self.rng.choice([0, 1])
            dut.out_ready.value = ready
            if int(dut.out_valid.value) and int(dut.out_ready.value):
                exp = self.expected.popleft()
                got = int(dut.sum.value)
                assert got == exp, f"Mismatch: got {got}, exp {exp}"

    async def wait_empty(self):
        while self.expected:
            await RisingEdge(self.dut.clk)

