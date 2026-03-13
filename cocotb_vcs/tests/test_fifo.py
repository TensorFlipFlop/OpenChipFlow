import os

import cocotb

from tb.fifo_tb import SyncFifoTB


@cocotb.test()
async def run_fifo_smoke(dut):
    tb = SyncFifoTB(dut)
    await tb.start()

    max_fill = int(os.getenv("MAX_FILL", "64"))
    dut._log.info(f"SEED={tb.seed}, MAX_FILL={max_fill} (fill until full or cap)")

    n_fill = await tb.fill_until_full(max_words=max_fill)
    dut._log.info(f"Filled {n_fill} words; full={int(dut.full.value)}")
    await tb.drain(n_fill)


@cocotb.test()
async def run_fifo_random(dut):
    tb = SyncFifoTB(dut)
    await tb.start()

    n_ops = int(os.getenv("N", "200"))
    dut._log.info(f"SEED={tb.seed}, N={n_ops}")

    await tb.random_rw(n_ops=n_ops)
