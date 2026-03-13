import os
import random
from collections import deque

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ReadOnly, RisingEdge


class SyncFifoTB:
    """Reusable cocotb testbench for sync_fifo (single clock, show-ahead read)."""

    def __init__(self, dut, seed=None, clock_period_ns=5):
        self.dut = dut
        self.clock_period_ns = clock_period_ns
        self.seed = seed if seed is not None else int(os.getenv("SEED", "42"))
        self.rng = random.Random(self.seed)

        self.w = len(dut.wr_data)
        self.mask = (1 << self.w) - 1
        self.expected = deque()

    async def start(self):
        cocotb.start_soon(Clock(self.dut.clk, self.clock_period_ns, unit="ns").start())
        await self.reset()

    async def reset(self, cycles=5):
        dut = self.dut
        dut.rst_n.value = 0
        dut.wr_valid.value = 0
        dut.wr_data.value = 0
        dut.rd_ready.value = 0
        for _ in range(cycles):
            await RisingEdge(dut.clk)
        dut.rst_n.value = 1
        for _ in range(2):
            await RisingEdge(dut.clk)

    async def push(self, data):
        """Push one word; waits until wr_ready."""
        dut = self.dut
        while True:
            await RisingEdge(dut.clk)
            if int(dut.wr_ready.value):
                break
        dut.wr_data.value = data & self.mask
        dut.wr_valid.value = 1
        await RisingEdge(dut.clk)
        dut.wr_valid.value = 0
        self.expected.append(data & self.mask)

    async def pop(self, stall_cycles=0):
        """Pop one word; waits until rd_valid, optionally stalls before asserting rd_ready."""
        dut = self.dut
        while True:
            await RisingEdge(dut.clk)
            if int(dut.rd_valid.value):
                break
        for _ in range(int(stall_cycles)):
            dut.rd_ready.value = 0
            await RisingEdge(dut.clk)
        dut.rd_ready.value = 1
        got = int(dut.rd_data.value)
        await RisingEdge(dut.clk)
        dut.rd_ready.value = 0
        exp = self.expected.popleft()
        assert got == exp, f"FIFO mismatch: got={got}, exp={exp}"
        return got

    async def fill_then_drain(self, n_words):
        """Directed: fill FIFO then drain FIFO, checking order."""
        for i in range(n_words):
            await self.push(i)
        await self.drain(n_words, stall_cycles=0)

    async def drain(self, n_words, stall_cycles=0):
        """Drain n_words from FIFO, checking order."""
        for _ in range(int(n_words)):
            await self.pop(stall_cycles=stall_cycles)

    async def fill_until_full(self, max_words=64):
        """Fill until FIFO reports full (or until max_words reached), then return pushed count."""
        pushed = 0
        while pushed < int(max_words):
            await ReadOnly()
            if int(self.dut.full.value):
                break
            await self.push(pushed)
            pushed += 1
        return pushed

    async def random_rw(self, n_ops=200):
        """Random mixed read/write: writer pushes n_ops words, reader drains them with stalls."""
        dut = self.dut

        async def writer():
            for _ in range(n_ops):
                data = self.rng.randrange(0, self.mask + 1)
                # random idle cycles to create bursts
                for _ in range(self.rng.randrange(0, 3)):
                    await RisingEdge(dut.clk)
                await self.push(data)

        async def reader():
            popped = 0
            while popped < n_ops:
                # random stall cycles while rd_valid is high
                stall = self.rng.randrange(0, 4)
                await self.pop(stall_cycles=stall)
                popped += 1

        w = cocotb.start_soon(writer())
        r = cocotb.start_soon(reader())
        await w
        await r
