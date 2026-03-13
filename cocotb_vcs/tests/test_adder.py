import os

import cocotb
try:
    from cocotb_coverage.coverage import CoverPoint, coverage_db
    _HAVE_COCOTB_COVERAGE = True
except ImportError:  # pragma: no cover
    _HAVE_COCOTB_COVERAGE = False

    def CoverPoint(*_args, **_kwargs):
        def _decorator(func):
            return func

        return _decorator

    class _DummyCoverageDB:
        def export_to_yaml(self, *_args, **_kwargs) -> None:
            return None

    coverage_db = _DummyCoverageDB()

from tb.adder_tb import AdderTB


# 覆盖采样：a/b 边界值 + 是否进位
@CoverPoint("adder.a_bins", xf=lambda a, b, co, w: a, bins=[0, 1, (1 << (8 - 1)) - 1, (1 << 8) - 1])
@CoverPoint("adder.b_bins", xf=lambda a, b, co, w: b, bins=[0, 1, (1 << (8 - 1)) - 1, (1 << 8) - 1])
@CoverPoint("adder.carry", xf=lambda a, b, co, w: co, bins=[0, 1])
def sample_cov(a, b, co, w):
    pass


@cocotb.test()
async def run_adder_random(dut):
    tb = AdderTB(dut)
    await tb.start()

    n_tests = int(os.getenv("N", "200"))
    dut._log.info(f"SEED={tb.seed}, N={n_tests}")

    cocotb.start_soon(tb.sink())

    for _ in range(n_tests):
        a = tb.rng.randrange(0, tb.mask + 1)
        b = tb.rng.randrange(0, tb.mask + 1)
        await tb.send(a, b)

        exp = a + b
        carry_out = 1 if (exp >> tb.w) else 0
        sample_cov(a, b, carry_out, tb.w)

    await tb.wait_empty()
    if _HAVE_COCOTB_COVERAGE:
        coverage_db.export_to_yaml("coverage.yml")
        dut._log.info("Coverage written to coverage.yml")
    else:
        dut._log.info("cocotb-coverage not installed; skip coverage.yml export")


@cocotb.test()
async def run_adder_smoke(dut):
    tb = AdderTB(dut)
    await tb.start()

    dut._log.info(f"SEED={tb.seed} (smoke)")

    # Deterministic stimulus + always-ready sink to validate basic function.
    cocotb.start_soon(tb.sink(ready_gen=lambda: 1))

    vectors = [
        (0, 0),
        (0, 1),
        (1, 0),
        (1, 1),
        (tb.mask, 0),
        (0, tb.mask),
        (tb.mask, 1),
        (1, tb.mask),
        (tb.mask, tb.mask),
    ]
    for a, b in vectors:
        await tb.send(a, b)
        exp = a + b
        carry_out = 1 if (exp >> tb.w) else 0
        sample_cov(a, b, carry_out, tb.w)

    await tb.wait_empty()
    if _HAVE_COCOTB_COVERAGE:
        coverage_db.export_to_yaml("coverage.yml")
        dut._log.info("Coverage written to coverage.yml")
