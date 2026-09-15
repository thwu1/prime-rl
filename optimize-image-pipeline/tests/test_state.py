
import subprocess
import time
import os

COMPILE = ["g++", "-O2", "-std=c++17", "-lm"]


def _build(src_dir, binary):
    """Compile pipeline.cpp from src_dir into binary."""
    src = os.path.join(src_dir, "pipeline.cpp")
    assert os.path.exists(src), f"Source not found: {src}"
    r = subprocess.run(
        COMPILE + ["-o", binary, src],
        capture_output=True, text=True, timeout=120,
    )
    assert r.returncode == 0, f"Compilation failed:\n{r.stderr}"


def _run(binary, timeout=240):
    """Run binary, return (stdout_stripped, wall_seconds)."""
    start = time.monotonic()
    r = subprocess.run(
        [binary], capture_output=True, text=True, timeout=timeout,
    )
    elapsed = time.monotonic() - start
    assert r.returncode == 0, (
        f"Program exited with code {r.returncode}:\n{r.stderr}"
    )
    return r.stdout.strip(), elapsed


# ---- fixtures built once per module --------------------------------

class TestPipeline:
    @classmethod
    def setup_class(cls):
        _build("/tests/baseline", "/tmp/baseline_bin")
        _build("/app", "/tmp/optimized_bin")

    # ---- correctness -----------------------------------------------

    def test_output_matches_baseline(self):
        """Optimized output must be bit-identical to baseline."""
        ref_out, _ = _run("/tmp/baseline_bin")
        opt_out, _ = _run("/tmp/optimized_bin")
        assert opt_out == ref_out, (
            f"Output differs from baseline.\n"
            f"=== Expected ===\n{ref_out}\n\n"
            f"=== Got ===\n{opt_out}"
        )

    # ---- performance -----------------------------------------------

    def test_achieves_2x_speedup(self):
        """Optimized pipeline must run >= 2x faster than baseline."""
        base_times = []
        opt_times = []
        for _ in range(3):
            _, bt = _run("/tmp/baseline_bin")
            base_times.append(bt)
            _, ot = _run("/tmp/optimized_bin")
            opt_times.append(ot)

        base_best = min(base_times)
        opt_best = min(opt_times)
        speedup = base_best / opt_best

        assert speedup >= 2.0, (
            f"Speedup {speedup:.2f}x < required 2.0x. "
            f"Baseline best: {base_best:.2f}s, "
            f"Optimized best: {opt_best:.2f}s"
        )
