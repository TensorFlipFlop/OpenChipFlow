import os

import cocotb

from tb.fifo_tb import SyncFifoTB


@cocotb.test()
async def run_fifo_directed(dut):
    tb = SyncFifoTB(dut)
    await tb.start()

    n_words = int(os.getenv("FILL_WORDS", "32"))
    stall = int(os.getenv("STALL_CYCLES", "2"))
    rounds = int(os.getenv("ROUNDS", "2"))
    try:
        depth = int(dut.DEPTH.value)
    except Exception:
        depth = int(os.getenv("DEPTH", "16"))
    if n_words > depth:
        n_words = depth
    dut._log.info(
        f"SEED={tb.seed}, FILL_WORDS={n_words}, DEPTH={depth}, STALL_CYCLES={stall}, ROUNDS={rounds}"
    )

    for r in range(rounds):
        base = r * n_words
        for i in range(n_words):
            await tb.push(base + i)
        await tb.drain(n_words, stall_cycles=stall)
