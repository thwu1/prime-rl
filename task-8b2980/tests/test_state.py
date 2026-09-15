"""
Tests for distributed training strategies.
Verifies correctness (Model.check) and efficiency (time, memory) constraints.
"""

import asyncio
import sys
import pytest

sys.path.insert(0, '/app')
from lib import Model, Dist


def _run_strategy(strategy_fn, ranks, layers, batches, timeout=120):
    """Run a distributed strategy across multiple simulated ranks."""
    async def _inner():
        dist = Dist(ranks)
        return await asyncio.wait_for(
            asyncio.gather(*[
                strategy_fn(Model(layers=layers, batches=batches, rank=i, dist=dist))
                for i in range(ranks)
            ]),
            timeout=timeout
        )
    return asyncio.run(_inner())


class TestFSDP:
    """Test Fully-Sharded Data Parallel strategy."""

    def test_correctness(self):
        """FSDP must produce correct, complete weights across all ranks."""
        from strategies import fsdp
        models = _run_strategy(fsdp, ranks=4, layers=6, batches=4)
        Model.check(models)

    def test_time_constraint(self):
        """FSDP simulated time must be <= 25."""
        from strategies import fsdp
        models = _run_strategy(fsdp, ranks=4, layers=6, batches=4)
        Model.check(models)
        max_time = max(m.time for m in models)
        assert max_time <= 25, \
            f"FSDP time {max_time:.1f} exceeds limit of 25"

    def test_memory_constraint(self):
        """FSDP peak memory per rank must be <= 2,800,000."""
        from strategies import fsdp
        models = _run_strategy(fsdp, ranks=4, layers=6, batches=4)
        Model.check(models)
        peak_mem = max(m.peak_memory() for m in models)
        assert peak_mem <= 2_800_000, \
            f"FSDP peak memory {peak_mem:,.0f} exceeds limit of 2,800,000"


class TestGPipe:
    """Test GPipe pipeline schedule strategy."""

    def test_correctness(self):
        """GPipe must produce correct, complete weights across all ranks."""
        from strategies import gpipe
        models = _run_strategy(gpipe, ranks=4, layers=8, batches=4)
        Model.check(models)

    def test_time_constraint(self):
        """GPipe simulated time must be <= 40."""
        from strategies import gpipe
        models = _run_strategy(gpipe, ranks=4, layers=8, batches=4)
        Model.check(models)
        max_time = max(m.time for m in models)
        assert max_time <= 40, \
            f"GPipe time {max_time:.1f} exceeds limit of 40"

    def test_memory_constraint(self):
        """GPipe peak memory per rank must be <= 4,500,000."""
        from strategies import gpipe
        models = _run_strategy(gpipe, ranks=4, layers=8, batches=4)
        Model.check(models)
        peak_mem = max(m.peak_memory() for m in models)
        assert peak_mem <= 4_500_000, \
            f"GPipe peak memory {peak_mem:,.0f} exceeds limit of 4,500,000"


class TestPipelineFSDP:
    """Test combined Pipeline + FSDP strategy."""

    def test_correctness(self):
        """Pipeline+FSDP must produce correct, complete weights across all ranks."""
        from strategies import pipeline_fsdp
        models = _run_strategy(pipeline_fsdp, ranks=16, layers=4, batches=4, timeout=180)
        Model.check(models)

    def test_time_constraint(self):
        """Pipeline+FSDP simulated time must be <= 20."""
        from strategies import pipeline_fsdp
        models = _run_strategy(pipeline_fsdp, ranks=16, layers=4, batches=4, timeout=180)
        Model.check(models)
        max_time = max(m.time for m in models)
        assert max_time <= 20, \
            f"Pipeline+FSDP time {max_time:.1f} exceeds limit of 20"

    def test_memory_constraint(self):
        """Pipeline+FSDP peak memory per rank must be <= 1,500,000."""
        from strategies import pipeline_fsdp
        models = _run_strategy(pipeline_fsdp, ranks=16, layers=4, batches=4, timeout=180)
        Model.check(models)
        peak_mem = max(m.peak_memory() for m in models)
        assert peak_mem <= 1_500_000, \
            f"Pipeline+FSDP peak memory {peak_mem:,.0f} exceeds limit of 1,500,000"
