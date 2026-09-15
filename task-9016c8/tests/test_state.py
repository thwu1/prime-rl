
"""
Tests for distributed training strategies.
Verifies correctness (Model.check), step counts, and peak memory.
"""

import asyncio
import sys
import pytest

sys.path.insert(0, "/app")
from simulator import Model, Dist
from strategies import basic, grad_accum, ddp, fsdp, pipeline_fsdp


def run_distributed(coro_factory, num_ranks, model_kwargs):
    """Run a distributed strategy across multiple ranks and return Model.check results."""
    async def _run():
        dist = Dist(num_ranks)
        models = await asyncio.gather(*[
            coro_factory(Model(rank=i, dist=dist, **model_kwargs))
            for i in range(num_ranks)
        ])
        return Model.check(list(models))
    return asyncio.run(_run())


class TestBasicTraining:
    """Strategy 1: Standard single-device training."""

    def _run(self):
        m = basic(Model(layers=2, batches=4, rank=0, dist=Dist(1)))
        return Model.check([m])

    def test_correctness(self):
        assert self._run()["passed"], "basic strategy failed correctness check"

    def test_steps(self):
        r = self._run()
        assert r["steps"] <= 12, f"basic: steps={r['steps']} exceeds target 12"

    def test_memory(self):
        r = self._run()
        assert r["max_memory"] <= 4_600_000, \
            f"basic: max_memory={r['max_memory']} exceeds target 4,600,000"


class TestGradAccum:
    """Strategy 2: Gradient accumulation."""

    def _run(self):
        m = grad_accum(Model(layers=2, batches=4, rank=0, dist=Dist(1)))
        return Model.check([m])

    def test_correctness(self):
        assert self._run()["passed"], "grad_accum strategy failed correctness check"

    def test_steps(self):
        r = self._run()
        assert r["steps"] <= 32, f"grad_accum: steps={r['steps']} exceeds target 32"

    def test_memory(self):
        r = self._run()
        assert r["max_memory"] <= 3_800_000, \
            f"grad_accum: max_memory={r['max_memory']} exceeds target 3,800,000"


class TestDDP:
    """Strategy 3: Distributed Data Parallel."""

    def _run(self):
        return run_distributed(ddp, 4, dict(layers=2, batches=4))

    def test_correctness(self):
        assert self._run()["passed"], "DDP strategy failed correctness check"

    def test_steps(self):
        r = self._run()
        assert r["steps"] <= 14, f"DDP: steps={r['steps']} exceeds target 14"

    def test_memory(self):
        r = self._run()
        assert r["max_memory"] <= 3_400_000, \
            f"DDP: max_memory={r['max_memory']} exceeds target 3,400,000"


class TestFSDP:
    """Strategy 4: Fully-Sharded Data Parallel."""

    def _run(self):
        return run_distributed(fsdp, 4, dict(layers=6, batches=4))

    def test_correctness(self):
        assert self._run()["passed"], "FSDP strategy failed correctness check"

    def test_steps(self):
        r = self._run()
        assert r["steps"] <= 50, f"FSDP: steps={r['steps']} exceeds target 50"

    def test_memory(self):
        r = self._run()
        assert r["max_memory"] <= 5_200_000, \
            f"FSDP: max_memory={r['max_memory']} exceeds target 5,200,000"


class TestPipelineFSDP:
    """Strategy 5: Pipeline Parallelism + FSDP (combined)."""

    def _run(self):
        return run_distributed(pipeline_fsdp, 16, dict(layers=4, batches=4))

    def test_correctness(self):
        assert self._run()["passed"], "Pipeline+FSDP strategy failed correctness check"

    def test_steps(self):
        r = self._run()
        assert r["steps"] <= 90, f"Pipeline+FSDP: steps={r['steps']} exceeds target 90"

    def test_memory(self):
        r = self._run()
        assert r["max_memory"] <= 2_400_000, \
            f"Pipeline+FSDP: max_memory={r['max_memory']} exceeds target 2,400,000"
