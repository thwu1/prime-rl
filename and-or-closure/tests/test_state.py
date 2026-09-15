"""
Tests for AND-OR Closure pipeline: verifies database results, CMake build
artifacts, and pipeline orchestration.

"""

import sqlite3
import struct
import os
import glob
import pytest


DB_PATH = "/app/lattice.db"


# ---------------------------------------------------------------------------
# Reference implementations
# ---------------------------------------------------------------------------

def brute_force_closure_size(values):
    """Compute |closure| by iterating AND/OR until fixed point. Small inputs only."""
    closure = set(values)
    changed = True
    while changed:
        changed = False
        items = list(closure)
        new = set()
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                a, b = items[i], items[j]
                av = a & b
                ov = a | b
                if av not in closure:
                    new.add(av)
                if ov not in closure:
                    new.add(ov)
        if new:
            closure.update(new)
            changed = True
    return len(closure)


def reference_solver(values):
    """
    Efficient reference: equivalence classes + DAG + order-ideal counting.
    Uses brute-force 2^R enumeration for R <= 22, MITM for R <= 30.
    """
    values = list(set(values))
    n = len(values)
    if n <= 1:
        return max(n, 0)

    all_and = values[0]
    all_or = values[0]
    for v in values[1:]:
        all_and &= v
        all_or |= v

    active_mask = all_and ^ all_or
    if active_mask == 0:
        return 1

    active_bits = []
    for b in range(41):
        if (active_mask >> b) & 1:
            active_bits.append(b)
    num_active = len(active_bits)

    patterns = set()
    for v in values:
        p = 0
        for i, b in enumerate(active_bits):
            if (v >> b) & 1:
                p |= 1 << i
        patterns.add(p)
    unique_patterns = sorted(patterns)

    bit_columns = {}
    for i in range(num_active):
        col = tuple((p >> i) & 1 for p in unique_patterns)
        if col not in bit_columns:
            bit_columns[col] = i
    representatives = sorted(bit_columns.values())
    R = len(representatives)

    implies = [0] * R
    for ri in range(R):
        bi = representatives[ri]
        mask = (1 << num_active) - 1
        for p in unique_patterns:
            if (p >> bi) & 1:
                mask &= p
        imp = 0
        for rj in range(R):
            bj = representatives[rj]
            if (mask >> bj) & 1:
                imp |= 1 << rj
        implies[ri] = imp

    if R <= 22:
        count = 0
        for s in range(1 << R):
            valid = True
            for i in range(R):
                if (s >> i) & 1:
                    if (implies[i] & s) != implies[i]:
                        valid = False
                        break
            if valid:
                count += 1
        return count
    else:
        return _count_mitm(R, implies)


def _count_mitm(R, implies):
    """Meet-in-the-middle order-ideal counting for R > 22."""
    h = R // 2
    sh = R - h
    h_mask = (1 << h) - 1
    sh_mask = (1 << sh) - 1

    implies_fh = [implies[i] & h_mask for i in range(h)]
    implies_sh = [((implies[h + j]) >> h) & sh_mask for j in range(sh)]
    req_fh = [implies[h + j] & h_mask for j in range(sh)]
    force_sh = [((implies[i]) >> h) & sh_mask for i in range(h)]

    up_sh = [0] * h
    for j in range(sh):
        for i in range(h):
            if (req_fh[j] >> i) & 1:
                up_sh[i] |= 1 << j

    comp_sh = [0] * sh
    for j in range(sh):
        m = 1 << j
        for k in range(sh):
            if k == j:
                continue
            if (implies_sh[j] >> k) & 1:
                m |= 1 << k
            if (implies_sh[k] >> j) & 1:
                m |= 1 << k
        comp_sh[j] = m

    ac = [0] * (1 << sh)
    ac[0] = 1
    for m in range(1, 1 << sh):
        j = m.bit_length() - 1
        without_j = m & ~(1 << j)
        without_comp = without_j & ~comp_sh[j]
        ac[m] = ac[without_j] + ac[without_comp]

    comp_fh = [0] * h
    for i in range(h):
        m = 1 << i
        for k in range(h):
            if k == i:
                continue
            if (implies_fh[i] >> k) & 1:
                m |= 1 << k
            if (implies_fh[k] >> i) & 1:
                m |= 1 << k
        comp_fh[i] = m

    total = 0

    def rec(idx, ac_mask, down_bl, up_bl):
        nonlocal total
        if idx == h:
            blocked = down_bl | up_bl
            free = sh_mask & ~blocked
            total += ac[free]
            return
        rec(idx + 1, ac_mask, down_bl, up_bl)
        if (comp_fh[idx] & ac_mask) == 0:
            rec(idx + 1,
                ac_mask | (1 << idx),
                down_bl | force_sh[idx],
                up_bl | up_sh[idx])

    rec(0, 0, 0, 0)
    return total


def unpack_blob(n, blob):
    """Unpack a binary blob into a list of n uint64 values."""
    return list(struct.unpack(f'<{n}Q', blob))


# ---------------------------------------------------------------------------
# Known answers for large test cases (mathematically derived)
# ---------------------------------------------------------------------------

KNOWN_ANSWERS = {
    12: 1 << 20,   # 20 independent bits -> 2^20
    13: 21,        # chain of 20 -> 21
    14: 1 << 25,   # 25 independent bits -> 2^25
}


def expected_answer(test_id, values):
    """Compute expected closure size for a test case."""
    if test_id in KNOWN_ANSWERS:
        return KNOWN_ANSWERS[test_id]
    n = len(values)
    if n <= 15:
        return brute_force_closure_size(values)
    return reference_solver(values)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBuildArtifacts:
    """Verify that the CMake build system was used correctly."""

    def test_cmake_cache_exists(self):
        """CMake must have been configured (CMakeCache.txt proves cmake was run)."""
        cache_path = "/app/project/build/CMakeCache.txt"
        assert os.path.exists(cache_path), (
            "CMakeCache.txt not found at /app/project/build/CMakeCache.txt — "
            "cmake must be run to configure the project"
        )

    def test_solver_binary_exists(self):
        """A compiled solver binary must exist in the CMake build directory."""
        build_dir = "/app/project/build"
        # Look for any executable file in the build directory
        found = False
        for root, dirs, files in os.walk(build_dir):
            for f in files:
                path = os.path.join(root, f)
                if os.access(path, os.X_OK) and not f.endswith(('.cmake', '.txt', '.log', '.sh')):
                    # Check it's actually an ELF binary, not a script
                    try:
                        with open(path, 'rb') as fh:
                            magic = fh.read(4)
                            if magic == b'\x7fELF':
                                found = True
                                break
                    except (IOError, PermissionError):
                        pass
            if found:
                break
        assert found, (
            "No compiled ELF binary found in /app/project/build/ — "
            "the solver must be compiled via CMake"
        )

    def test_cmakelists_has_executable(self):
        """CMakeLists.txt must define an executable target."""
        cmake_path = "/app/project/CMakeLists.txt"
        assert os.path.exists(cmake_path), "CMakeLists.txt not found"
        with open(cmake_path) as f:
            content = f.read().lower()
        assert "add_executable" in content, (
            "CMakeLists.txt does not contain add_executable — "
            "the solver must be defined as a CMake executable target"
        )


class TestPipeline:
    """Verify the pipeline script exists and is properly structured."""

    def test_pipeline_exists(self):
        """pipeline.sh must exist at /app/pipeline.sh."""
        assert os.path.exists("/app/pipeline.sh"), (
            "Pipeline script not found at /app/pipeline.sh"
        )

    def test_pipeline_executable(self):
        """pipeline.sh must be executable."""
        assert os.access("/app/pipeline.sh", os.X_OK), (
            "/app/pipeline.sh is not executable"
        )

    def test_pipeline_uses_sqlite(self):
        """pipeline.sh or its helpers must interact with SQLite."""
        # Check pipeline.sh and any .py files it might call
        pipeline_mentions_sqlite = False
        for path in ["/app/pipeline.sh"]:
            if os.path.exists(path):
                with open(path) as f:
                    content = f.read().lower()
                if "sqlite" in content or "lattice.db" in content:
                    pipeline_mentions_sqlite = True
                    break
        # Also check referenced Python scripts
        if not pipeline_mentions_sqlite:
            for root, dirs, files in os.walk("/app"):
                for fn in files:
                    if fn.endswith('.py'):
                        fpath = os.path.join(root, fn)
                        try:
                            with open(fpath) as f:
                                if 'sqlite' in f.read().lower():
                                    pipeline_mentions_sqlite = True
                                    break
                        except (IOError, PermissionError):
                            pass
                if pipeline_mentions_sqlite:
                    break
        assert pipeline_mentions_sqlite, (
            "Pipeline does not appear to interact with SQLite — "
            "data must be read from and results written to lattice.db"
        )


class TestDatabaseResults:
    """Verify results in the SQLite database are correct."""

    @pytest.fixture(autouse=True)
    def setup(self):
        assert os.path.exists(DB_PATH), f"Database not found at {DB_PATH}"
        self.conn = sqlite3.connect(DB_PATH)
        yield
        self.conn.close()

    def _get_test_cases(self):
        c = self.conn.cursor()
        c.execute("SELECT id, n, values_packed FROM test_cases ORDER BY id")
        rows = c.fetchall()
        assert len(rows) > 0, "test_cases table is empty"
        return rows

    def _get_results(self):
        c = self.conn.cursor()
        c.execute("SELECT test_id, closure_size FROM results ORDER BY test_id")
        return {row[0]: row[1] for row in c.fetchall()}

    def test_results_table_populated(self):
        """All test cases must have results in the results table."""
        cases = self._get_test_cases()
        results = self._get_results()
        missing = [tc[0] for tc in cases if tc[0] not in results]
        assert len(missing) == 0, (
            f"Missing results for test_ids: {missing}"
        )

    def test_small_cases_brute_force(self):
        """Small cases (n <= 10) verified against brute-force closure."""
        cases = self._get_test_cases()
        results = self._get_results()
        for test_id, n, blob in cases:
            if n > 10:
                continue
            values = unpack_blob(n, blob)
            exp = brute_force_closure_size(values)
            got = results.get(test_id)
            assert got is not None, f"No result for test_id {test_id}"
            assert got == exp, (
                f"Test {test_id} (A={values}): expected {exp}, got {got}"
            )

    def test_medium_cases_reference(self):
        """Medium cases verified against efficient reference solver."""
        cases = self._get_test_cases()
        results = self._get_results()
        medium_ids = [9, 10, 11]
        for test_id, n, blob in cases:
            if test_id not in medium_ids:
                continue
            values = unpack_blob(n, blob)
            exp = reference_solver(values)
            got = results.get(test_id)
            assert got is not None, f"No result for test_id {test_id}"
            assert got == exp, (
                f"Test {test_id}: expected {exp}, got {got}"
            )

    def test_independent_20(self):
        """20 independent bits: 2^20 = 1048576 order ideals."""
        results = self._get_results()
        assert results.get(12) == 1 << 20, (
            f"Independent-20: expected {1 << 20}, got {results.get(12)}"
        )

    def test_chain_20(self):
        """Chain of 20 bits: 21 order ideals."""
        results = self._get_results()
        assert results.get(13) == 21, (
            f"Chain-20: expected 21, got {results.get(13)}"
        )

    def test_independent_25(self):
        """25 independent bits: 2^25 = 33554432 order ideals. Requires efficient impl."""
        results = self._get_results()
        assert results.get(14) == 1 << 25, (
            f"Independent-25: expected {1 << 25}, got {results.get(14)}"
        )

    def test_all_cases_correct(self):
        """Cross-check all results against expected answers."""
        cases = self._get_test_cases()
        results = self._get_results()
        for test_id, n, blob in cases:
            values = unpack_blob(n, blob)
            exp = expected_answer(test_id, values)
            got = results.get(test_id)
            assert got is not None, f"No result for test_id {test_id}"
            assert got == exp, (
                f"Test {test_id}: expected {exp}, got {got}"
            )
