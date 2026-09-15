
import subprocess
import os
import pytest

BINARY = "/app/pipeline"
INPUT = "/app/data/numbers.txt"
PRIME = 1000003
HASH_MULT = 6364136223846793005
MOD = 2**64


def _read_numbers():
    with open(INPUT) as f:
        return [int(line.strip()) for line in f if line.strip()]


def _expected_worker_sum(nums, wid, nworkers):
    chunk = len(nums) // nworkers
    lo = wid * chunk
    hi = len(nums) if wid == nworkers - 1 else lo + chunk
    return sum((x ** 3) % PRIME for x in nums[lo:hi])


def _expected_worker_checksum(nums, wid, nworkers):
    chunk = len(nums) // nworkers
    lo = wid * chunk
    hi = len(nums) if wid == nworkers - 1 else lo + chunk
    h = 0
    for x in nums[lo:hi]:
        h = (h * HASH_MULT + x) % MOD
    return h


def _expected_total(nums, nworkers):
    return sum(_expected_worker_sum(nums, w, nworkers) for w in range(nworkers))


def _run_pipeline(nworkers, output_path):
    env = os.environ.copy()
    if os.path.exists(output_path):
        os.remove(output_path)
    try:
        r = subprocess.run(
            [BINARY, INPUT, output_path, str(nworkers)],
            timeout=15,
            capture_output=True,
            text=True,
            env=env,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(
            f"Program did not complete within 15 seconds with {nworkers} "
            f"workers — likely deadlocked"
        )
    assert r.returncode == 0, f"Exit code {r.returncode}:\nstderr: {r.stderr}"
    assert os.path.exists(output_path), "Output file not created"
    with open(output_path) as f:
        return f.read()


@pytest.fixture(scope="module")
def compiled():
    subprocess.run(["make", "-C", "/app", "clean"], capture_output=True)
    result = subprocess.run(["make", "-C", "/app"], capture_output=True, text=True)
    assert result.returncode == 0, f"Compilation failed:\n{result.stderr}"
    assert os.path.isfile(BINARY), "Binary not produced"
    return True


@pytest.fixture(scope="module")
def output_4w(compiled):
    return _run_pipeline(4, "/app/output_4w.txt")


# ---------- basic checks ----------

def test_compiles(compiled):
    assert compiled


def test_completes_without_hanging(output_4w):
    """Program must produce output within the timeout."""
    assert len(output_4w) > 0


def test_single_header(output_4w):
    """Header line must appear exactly once — no stdio buffer duplication."""
    count = output_4w.count("PIPELINE workers=")
    assert count == 1, (
        f"Header appears {count} times, expected exactly 1"
    )


# ---------- numerical correctness (4 workers) ----------

def test_correct_total_4workers(output_4w):
    nums = _read_numbers()
    expected = _expected_total(nums, 4)
    total_lines = [l for l in output_4w.splitlines() if l.startswith("TOTAL:")]
    assert len(total_lines) == 1, f"Expected 1 TOTAL line, found {len(total_lines)}"
    actual = int(total_lines[0].split(":")[1].strip())
    assert actual == expected, f"TOTAL: expected {expected}, got {actual}"


def test_per_worker_sums_4workers(output_4w):
    nums = _read_numbers()
    for w in range(4):
        expected = _expected_worker_sum(nums, w, 4)
        prefix = f"W{w}:"
        wlines = [l for l in output_4w.splitlines() if l.startswith(prefix)]
        assert len(wlines) == 1, f"Missing or duplicate W{w} line"
        sum_parts = [p for p in wlines[0].split() if p.startswith("sum=")]
        assert len(sum_parts) == 1, f"Cannot parse sum from: {wlines[0]}"
        actual = int(sum_parts[0].split("=")[1])
        assert actual == expected, f"Worker {w}: expected {expected}, got {actual}"


def test_per_worker_checksums_4workers(output_4w):
    nums = _read_numbers()
    for w in range(4):
        expected = _expected_worker_checksum(nums, w, 4)
        prefix = f"W{w}:"
        wlines = [l for l in output_4w.splitlines() if l.startswith(prefix)]
        assert len(wlines) == 1, f"Missing or duplicate W{w} line"
        ck_parts = [p for p in wlines[0].split() if p.startswith("checksum=")]
        assert len(ck_parts) == 1, f"Cannot parse checksum from: {wlines[0]}"
        actual = int(ck_parts[0].split("=")[1])
        assert actual == expected, (
            f"Worker {w} checksum: expected {expected}, got {actual}"
        )


# ---------- cross-validation and state ----------

def test_all_workers_done(output_4w):
    for w in range(4):
        prefix = f"W{w}:"
        wlines = [l for l in output_4w.splitlines() if l.startswith(prefix)]
        assert len(wlines) == 1, f"Missing W{w} line"
        assert "state=DONE" in wlines[0], (
            f"Worker {w} not in DONE state: {wlines[0]}"
        )


def test_checksum_verify_ok(output_4w):
    assert "CHECKSUM_VERIFY: OK" in output_4w, (
        "Cross-validation of checksums between pipe and shared memory failed"
    )


def test_sum_verify_ok(output_4w):
    assert "SUM_VERIFY: OK" in output_4w, (
        "Cross-validation of sums between pipe and shared memory failed"
    )


def test_progress_complete(output_4w):
    assert "PROGRESS: 4/4 DONE" in output_4w, (
        "Progress does not show all 4 workers completed"
    )


# ---------- zombie check ----------

def test_no_zombies(compiled):
    out = "/app/zombie_check.txt"
    if os.path.exists(out):
        os.remove(out)
    env = os.environ.copy()
    try:
        r = subprocess.run(
            [BINARY, INPUT, out, "4"],
            timeout=15,
            capture_output=True,
            text=True,
            env=env,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("Program deadlocked during zombie check")
    assert r.returncode == 0
    ps = subprocess.run(["ps", "aux"], capture_output=True, text=True)
    zombies = [
        l for l in ps.stdout.splitlines()
        if "pipeline" in l and ("<defunct>" in l or " Z " in l)
    ]
    assert len(zombies) == 0, f"Zombie processes found:\n" + "\n".join(zombies)


# ---------- different worker counts ----------

def test_3_workers(compiled):
    """3 workers on 1000 elements: even split (333+333+334)."""
    content = _run_pipeline(3, "/app/output_3w.txt")
    nums = _read_numbers()
    expected = _expected_total(nums, 3)
    total_lines = [l for l in content.splitlines() if l.startswith("TOTAL:")]
    assert len(total_lines) == 1
    actual = int(total_lines[0].split(":")[1].strip())
    assert actual == expected, f"3-worker TOTAL: expected {expected}, got {actual}"
    assert "CHECKSUM_VERIFY: OK" in content
    assert "SUM_VERIFY: OK" in content
    assert "PROGRESS: 3/3 DONE" in content
    header_count = content.count("PIPELINE workers=")
    assert header_count == 1, f"3-worker header appears {header_count} times"


def test_7_workers(compiled):
    """7 workers on 1000 elements: uneven split (142*6 + 148)."""
    content = _run_pipeline(7, "/app/output_7w.txt")
    nums = _read_numbers()
    expected = _expected_total(nums, 7)
    total_lines = [l for l in content.splitlines() if l.startswith("TOTAL:")]
    assert len(total_lines) == 1
    actual = int(total_lines[0].split(":")[1].strip())
    assert actual == expected, f"7-worker TOTAL: expected {expected}, got {actual}"
    assert "CHECKSUM_VERIFY: OK" in content
    assert "SUM_VERIFY: OK" in content
    assert "PROGRESS: 7/7 DONE" in content
    # Verify each worker's checksum for this uneven partition
    for w in range(7):
        expected_ck = _expected_worker_checksum(nums, w, 7)
        wlines = [l for l in content.splitlines() if l.startswith(f"W{w}:")]
        assert len(wlines) == 1, f"Missing W{w} line in 7-worker output"
        ck_parts = [p for p in wlines[0].split() if p.startswith("checksum=")]
        assert len(ck_parts) == 1
        actual_ck = int(ck_parts[0].split("=")[1])
        assert actual_ck == expected_ck, (
            f"7-worker W{w} checksum: expected {expected_ck}, got {actual_ck}"
        )


def test_1_worker(compiled):
    """Single worker edge case: entire dataset in one partition."""
    content = _run_pipeline(1, "/app/output_1w.txt")
    nums = _read_numbers()
    expected = _expected_total(nums, 1)
    total_lines = [l for l in content.splitlines() if l.startswith("TOTAL:")]
    assert len(total_lines) == 1
    actual = int(total_lines[0].split(":")[1].strip())
    assert actual == expected, f"1-worker TOTAL: expected {expected}, got {actual}"
    assert "CHECKSUM_VERIFY: OK" in content
    assert "SUM_VERIFY: OK" in content
    assert "PROGRESS: 1/1 DONE" in content
    # Verify checksum for the single worker
    expected_ck = _expected_worker_checksum(nums, 0, 1)
    wlines = [l for l in content.splitlines() if l.startswith("W0:")]
    assert len(wlines) == 1
    ck_parts = [p for p in wlines[0].split() if p.startswith("checksum=")]
    assert len(ck_parts) == 1
    actual_ck = int(ck_parts[0].split("=")[1])
    assert actual_ck == expected_ck, (
        f"1-worker checksum: expected {expected_ck}, got {actual_ck}"
    )
