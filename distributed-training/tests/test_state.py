"""
Tests for distributed training strategies.

Verifies each strategy for:
  1. Correctness: Model.check() passes (all layers have complete, step-1 weights)
  2. Time budget: max simulated time across ranks <= target from cluster.db
  3. Memory budget: max peak memory across ranks <= target from cluster.db
"""

import sys
import asyncio
import sqlite3
sys.path.insert(0, '/app')

from lib import Model, Dist
from strategies import ddp, fsdp, pipeline_fsdp


def _load_config(name):
    """Load strategy configuration from cluster database."""
    conn = sqlite3.connect('/app/cluster.db')
    row = conn.execute(
        "SELECT ranks, layers, batches, max_time, max_peak_memory "
        "FROM strategy_config WHERE name = ?", (name,)
    ).fetchone()
    conn.close()
    assert row is not None, f"No config for strategy '{name}' in cluster.db"
    return {
        'ranks': row[0], 'layers': row[1], 'batches': row[2],
        'max_time': row[3], 'max_peak_memory': row[4],
    }


def _run(coro):
    return asyncio.run(coro)


async def _run_strategy(strategy_fn, cfg):
    ranks = cfg['ranks']
    dist = Dist(ranks)
    models = await asyncio.gather(*[
        strategy_fn(Model(layers=cfg['layers'], batches=cfg['batches'],
                          rank=i, dist=dist))
        for i in range(ranks)
    ])
    return models


class TestDDP:
    """Distributed Data Parallel."""

    def _cfg(self):
        return _load_config('ddp')

    def test_correctness(self):
        cfg = self._cfg()
        models = _run(_run_strategy(ddp, cfg))
        assert Model.check(models), "DDP: Model.check() failed"

    def test_time_budget(self):
        cfg = self._cfg()
        models = _run(_run_strategy(ddp, cfg))
        max_time = max(m.time for m in models)
        assert max_time <= cfg['max_time'], \
            f"DDP: max time {max_time} exceeds budget {cfg['max_time']}"

    def test_memory_budget(self):
        cfg = self._cfg()
        models = _run(_run_strategy(ddp, cfg))
        max_mem = max(m.peak_mem for m in models)
        assert max_mem <= cfg['max_peak_memory'], \
            f"DDP: peak memory {max_mem} exceeds budget {cfg['max_peak_memory']}"


class TestFSDP:
    """Fully Sharded Data Parallel."""

    def _cfg(self):
        return _load_config('fsdp')

    def test_correctness(self):
        cfg = self._cfg()
        models = _run(_run_strategy(fsdp, cfg))
        assert Model.check(models), "FSDP: Model.check() failed"

    def test_time_budget(self):
        cfg = self._cfg()
        models = _run(_run_strategy(fsdp, cfg))
        max_time = max(m.time for m in models)
        assert max_time <= cfg['max_time'], \
            f"FSDP: max time {max_time} exceeds budget {cfg['max_time']}"

    def test_memory_budget(self):
        cfg = self._cfg()
        models = _run(_run_strategy(fsdp, cfg))
        max_mem = max(m.peak_mem for m in models)
        assert max_mem <= cfg['max_peak_memory'], \
            f"FSDP: peak memory {max_mem} exceeds budget {cfg['max_peak_memory']}"


class TestPipelineFSDP:
    """Pipeline + FSDP."""

    def _cfg(self):
        return _load_config('pipeline_fsdp')

    def test_correctness(self):
        cfg = self._cfg()
        models = _run(_run_strategy(pipeline_fsdp, cfg))
        assert Model.check(models), "Pipeline+FSDP: Model.check() failed"

    def test_time_budget(self):
        cfg = self._cfg()
        models = _run(_run_strategy(pipeline_fsdp, cfg))
        max_time = max(m.time for m in models)
        assert max_time <= cfg['max_time'], \
            f"Pipeline+FSDP: max time {max_time} exceeds budget {cfg['max_time']}"

    def test_memory_budget(self):
        cfg = self._cfg()
        models = _run(_run_strategy(pipeline_fsdp, cfg))
        max_mem = max(m.peak_mem for m in models)
        assert max_mem <= cfg['max_peak_memory'], \
            f"Pipeline+FSDP: peak memory {max_mem} exceeds budget {cfg['max_peak_memory']}"
