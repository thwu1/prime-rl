
import subprocess
import os


class TestDataLoader:
    @classmethod
    def setup_class(cls):
        """Ensure npm deps are installed and test file is copied."""
        os.makedirs('/app/src/__tests__', exist_ok=True)
        if os.path.exists('/tests/dataloader.test.ts'):
            subprocess.run(
                ['cp', '/tests/dataloader.test.ts', '/app/src/__tests__/dataloader.test.ts'],
                check=True,
            )
        subprocess.run(
            ['npm', 'install'],
            cwd='/app',
            capture_output=True,
            timeout=120,
        )

    def _run_jest(self, test_pattern=None):
        cmd = ['npx', 'jest', '--forceExit', '--no-cache']
        if test_pattern:
            cmd.extend(['-t', test_pattern])
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            cwd='/app',
        )
        return result

    def test_batch_scheduling(self):
        result = self._run_jest('batches loads within promise chains')
        assert result.returncode == 0, (
            f"Batch scheduling test failed:\n{result.stdout}\n{result.stderr}"
        )

    def test_cache_hit_coalescing(self):
        result = self._run_jest('coalesces cached and fresh loads')
        assert result.returncode == 0, (
            f"Cache-hit coalescing test failed:\n{result.stdout}\n{result.stderr}"
        )

    def test_max_batch_size(self):
        result = self._run_jest('respects maxBatchSize')
        assert result.returncode == 0, (
            f"maxBatchSize test failed:\n{result.stdout}\n{result.stderr}"
        )

    def test_array_length_invariant(self):
        result = self._run_jest('rejects when values length mismatch')
        assert result.returncode == 0, (
            f"Array length invariant test failed:\n{result.stdout}\n{result.stderr}"
        )

    def test_failed_dispatch_cache_clearing(self):
        result = self._run_jest('clears cache on failed dispatch')
        assert result.returncode == 0, (
            f"Failed dispatch cache clearing test failed:\n{result.stdout}\n{result.stderr}"
        )

    def test_lru_cache_recency(self):
        result = self._run_jest('get promotes entry to MRU position')
        assert result.returncode == 0, (
            f"LRU cache recency test failed:\n{result.stdout}\n{result.stderr}"
        )

    def test_lru_with_dataloader_eviction(self):
        result = self._run_jest('evicts LRU entries causing re-fetch')
        assert result.returncode == 0, (
            f"LRU + DataLoader eviction test failed:\n{result.stdout}\n{result.stderr}"
        )

    def test_lru_multiple_gets_reorder(self):
        result = self._run_jest('multiple gets reorder LRU correctly')
        assert result.returncode == 0, (
            f"LRU multiple gets reorder test failed:\n{result.stdout}\n{result.stderr}"
        )

    def test_coalescer_promise_chain_batching(self):
        result = self._run_jest('coalesces loads from promise chains across loaders')
        assert result.returncode == 0, (
            f"BatchCoalescer promise chain batching test failed:\n{result.stdout}\n{result.stderr}"
        )

    def test_coalescer_reentrant_dispatch(self):
        result = self._run_jest('handles re-entrant loads after dispatch')
        assert result.returncode == 0, (
            f"BatchCoalescer re-entrant dispatch test failed:\n{result.stdout}\n{result.stderr}"
        )

    def test_scope_bounded_lru(self):
        result = self._run_jest('uses bounded LRU caching via scope')
        assert result.returncode == 0, (
            f"RequestScope bounded LRU test failed:\n{result.stdout}\n{result.stderr}"
        )

    def test_scope_dispose_clears_caches(self):
        result = self._run_jest('dispose clears all loader caches')
        assert result.returncode == 0, (
            f"RequestScope dispose test failed:\n{result.stdout}\n{result.stderr}"
        )

    def test_scope_dispose_multiple_loaders(self):
        result = self._run_jest('dispose across multiple loaders clears all')
        assert result.returncode == 0, (
            f"RequestScope multi-loader dispose test failed:\n{result.stdout}\n{result.stderr}"
        )

    def test_scope_reentrant_across_loaders(self):
        result = self._run_jest('re-entrant loads across scoped loaders')
        assert result.returncode == 0, (
            f"RequestScope re-entrant test failed:\n{result.stdout}\n{result.stderr}"
        )

    def test_full_suite(self):
        result = self._run_jest()
        assert result.returncode == 0, (
            f"Full Jest suite failed:\n{result.stdout}\n{result.stderr}"
        )
