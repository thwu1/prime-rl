
import subprocess
import os
import select
import json


def test_build():
    """Both tools must compile without errors."""
    r = subprocess.run(["make", "-C", "/app", "clean"], capture_output=True)
    r = subprocess.run(["make", "-C", "/app"], capture_output=True)
    assert r.returncode == 0, f"Build failed:\n{r.stderr.decode()}"
    assert os.path.isfile("/app/sesrec"), "sesrec binary not found"
    assert os.path.isfile("/app/sesplay"), "sesplay binary not found"


def test_v1_timing_accuracy():
    """
    In v1 mode, the second timing entry for 'echo -n A; sleep 2; echo -n B'
    must reflect the ~2-second sleep gap. With a clock-before-read bug the
    entry would be near zero.
    """
    for f in ["/tmp/t_v1a_ts", "/tmp/t_v1a_tm"]:
        if os.path.exists(f):
            os.remove(f)

    cmd = [
        "/app/sesrec", "-q", "-f", "v1",
        "-o", "/tmp/t_v1a_ts",
        "-T", "/tmp/t_v1a_tm",
        "-c", "echo -n A; sleep 2; echo -n B",
    ]
    subprocess.run(cmd, timeout=15)

    with open("/tmp/t_v1a_tm") as f:
        lines = [l for l in f.readlines() if l.strip()]

    assert len(lines) >= 2, (
        f"Expected >= 2 timing entries, got {len(lines)}"
    )

    delays = [float(line.split()[0]) for line in lines]

    assert delays[1] > 1.5, (
        f"Second delay is {delays[1]:.4f}s (expected ~2s). "
        "Clock may be sampled before the blocking read."
    )
    assert delays[1] < 3.5, (
        f"Second delay is {delays[1]:.4f}s (too large, expected ~2s)"
    )


def test_v1_initial_precision():
    """
    In v1 mode, the initial timestamp must use sub-second precision.
    Run five times with a fast command; every first-entry delay must be small.
    A whole-second time source would produce values uniformly in [0, 1).
    """
    for i in range(5):
        ts = f"/tmp/t_prec{i}_ts"
        tm = f"/tmp/t_prec{i}_tm"
        for f in [ts, tm]:
            if os.path.exists(f):
                os.remove(f)

        cmd = ["/app/sesrec", "-q", "-f", "v1",
               "-o", ts, "-T", tm, "-c", "echo x"]
        subprocess.run(cmd, timeout=10)

        with open(tm) as f:
            first_delay = float(f.readline().split()[0])

        assert first_delay < 0.4, (
            f"Run {i}: first delay is {first_delay:.4f}s. "
            "Initial timestamp may lack sub-second precision."
        )


def test_default_format_v2():
    """Default format (no -f flag) should produce v2 timing with header."""
    for f in ["/tmp/t_def_ts", "/tmp/t_def_tm"]:
        if os.path.exists(f):
            os.remove(f)

    cmd = ["/app/sesrec", "-q",
           "-o", "/tmp/t_def_ts", "-T", "/tmp/t_def_tm",
           "-c", "echo hello"]
    subprocess.run(cmd, timeout=10)

    with open("/tmp/t_def_tm") as f:
        first_line = f.readline()

    assert first_line.strip() == "# sesrec-timing v2 monotonic", (
        f"Default format should be v2. First line: {first_line!r}"
    )


def test_v2_monotonic_timestamps():
    """
    v2 timestamps should be absolute monotonic values, monotonically
    increasing, and plausibly large (not small deltas).
    """
    for f in ["/tmp/t_v2m_ts", "/tmp/t_v2m_tm"]:
        if os.path.exists(f):
            os.remove(f)

    cmd = ["/app/sesrec", "-q", "-f", "v2",
           "-o", "/tmp/t_v2m_ts", "-T", "/tmp/t_v2m_tm",
           "-c", "echo -n A; sleep 0.1; echo -n B; sleep 0.1; echo -n C"]
    subprocess.run(cmd, timeout=10)

    with open("/tmp/t_v2m_tm") as f:
        lines = f.readlines()

    assert lines[0].strip() == "# sesrec-timing v2 monotonic"

    data_lines = [l for l in lines[1:] if l.strip()]
    assert len(data_lines) >= 1, "No data lines in v2 timing"

    timestamps = [float(line.split()[0]) for line in data_lines]

    # Absolute monotonic timestamps should be large (seconds since boot)
    assert timestamps[0] > 1.0, (
        f"First timestamp {timestamps[0]} looks like a delta, not absolute"
    )

    # Should be monotonically increasing
    for i in range(1, len(timestamps)):
        assert timestamps[i] >= timestamps[i - 1], (
            f"Timestamps not monotonic at index {i}: "
            f"{timestamps[i]} < {timestamps[i - 1]}"
        )


def test_v2_timing_accuracy():
    """
    v2 mode: the gap between consecutive timestamps for a 'sleep 2'
    should be approximately 2 seconds.
    """
    for f in ["/tmp/t_v2a_ts", "/tmp/t_v2a_tm"]:
        if os.path.exists(f):
            os.remove(f)

    cmd = ["/app/sesrec", "-q", "-f", "v2",
           "-o", "/tmp/t_v2a_ts", "-T", "/tmp/t_v2a_tm",
           "-c", "echo -n A; sleep 2; echo -n B"]
    subprocess.run(cmd, timeout=15)

    with open("/tmp/t_v2a_tm") as f:
        lines = f.readlines()

    assert lines[0].strip() == "# sesrec-timing v2 monotonic"

    data_lines = [l for l in lines[1:] if l.strip()]
    assert len(data_lines) >= 2, (
        f"Expected >= 2 data lines, got {len(data_lines)}"
    )

    timestamps = [float(line.split()[0]) for line in data_lines]
    gap = timestamps[1] - timestamps[0]

    assert gap > 1.5, f"Gap is {gap:.4f}s (expected ~2s, too small)"
    assert gap < 3.5, f"Gap is {gap:.4f}s (expected ~2s, too large)"


def test_replayer_v1_synthetic():
    """Replayer produces correct output from synthetic v1 timing data."""
    with open("/tmp/t_rv1_ts", "w") as f:
        f.write("HelloWorld12345")
    with open("/tmp/t_rv1_tm", "w") as f:
        f.write("0.001000 5\n")
        f.write("0.001000 5\n")
        f.write("0.001000 5\n")

    result = subprocess.run(
        ["/app/sesplay", "-T", "/tmp/t_rv1_tm", "/tmp/t_rv1_ts"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, f"sesplay failed: {result.stderr}"
    assert result.stdout == "HelloWorld12345", (
        f"Replayer v1 output mismatch: '{result.stdout}'"
    )


def test_replayer_v2_synthetic():
    """Replayer auto-detects and correctly replays v2 format."""
    with open("/tmp/t_rv2_ts", "w") as f:
        f.write("ABCXYZ123")
    with open("/tmp/t_rv2_tm", "w") as f:
        f.write("# sesrec-timing v2 monotonic\n")
        f.write("1000.001000000 3\n")
        f.write("1000.002000000 3\n")
        f.write("1000.003000000 3\n")

    result = subprocess.run(
        ["/app/sesplay", "-T", "/tmp/t_rv2_tm", "/tmp/t_rv2_ts"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, f"sesplay failed: {result.stderr}"
    assert result.stdout == "ABCXYZ123", (
        f"Replayer v2 output mismatch: '{result.stdout}'"
    )


def test_replayer_no_defer():
    """
    The replayer must not defer the first block's emission. Given a tiny
    first delay and a large second delay, output must appear immediately.
    A deferred-emission hack would wait for the large second delay before
    producing any output at all.
    """
    with open("/tmp/t_defer_ts", "w") as f:
        f.write("XYZABC")
    with open("/tmp/t_defer_tm", "w") as f:
        f.write("0.001000 3\n")
        f.write("10.000000 3\n")

    proc = subprocess.Popen(
        ["/app/sesplay", "-T", "/tmp/t_defer_tm", "/tmp/t_defer_ts"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )

    try:
        r, _, _ = select.select([proc.stdout], [], [], 3.0)
        assert r, (
            "No output within 3s — replayer may defer first block emission."
        )
        data = os.read(proc.stdout.fileno(), 1024)
        assert b"XYZ" in data, (
            f"Expected 'XYZ' in first output, got {data!r}"
        )
    finally:
        proc.kill()
        proc.wait()


def test_analyze_v1():
    """--analyze on v1 format produces correct JSON statistics."""
    with open("/tmp/t_av1_tm", "w") as f:
        f.write("0.100000 10\n")
        f.write("2.000000 20\n")
        f.write("0.500000 15\n")

    result = subprocess.run(
        ["/app/sesplay", "--analyze", "-T", "/tmp/t_av1_tm"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, f"sesplay --analyze failed: {result.stderr}"

    data = json.loads(result.stdout)
    assert data["format_version"] == 1
    assert data["total_chunks"] == 3
    assert data["total_bytes"] == 45
    assert abs(data["total_duration_sec"] - 2.6) < 0.001
    assert abs(data["mean_delay_sec"] - 2.6 / 3) < 0.001
    assert abs(data["max_delay_sec"] - 2.0) < 0.001
    assert abs(data["min_delay_sec"] - 0.1) < 0.001


def test_analyze_v2():
    """--analyze on v2 format produces correct JSON statistics."""
    with open("/tmp/t_av2_tm", "w") as f:
        f.write("# sesrec-timing v2 monotonic\n")
        f.write("1000.100000 10\n")
        f.write("1002.100000 20\n")
        f.write("1002.600000 15\n")

    result = subprocess.run(
        ["/app/sesplay", "--analyze", "-T", "/tmp/t_av2_tm"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, f"sesplay --analyze failed: {result.stderr}"

    data = json.loads(result.stdout)
    assert data["format_version"] == 2
    assert data["total_chunks"] == 3
    assert data["total_bytes"] == 45
    assert abs(data["total_duration_sec"] - 2.5) < 0.001
    # mean = 2.5 / (3-1) = 1.25
    assert abs(data["mean_delay_sec"] - 1.25) < 0.001
    assert abs(data["max_delay_sec"] - 2.0) < 0.001
    assert abs(data["min_delay_sec"] - 0.5) < 0.001


def test_analyze_single_chunk():
    """--analyze handles single-chunk v2 recording correctly (edge case)."""
    with open("/tmp/t_asc_tm", "w") as f:
        f.write("# sesrec-timing v2 monotonic\n")
        f.write("1000.100000 42\n")

    result = subprocess.run(
        ["/app/sesplay", "--analyze", "-T", "/tmp/t_asc_tm"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, f"sesplay --analyze failed: {result.stderr}"

    data = json.loads(result.stdout)
    assert data["format_version"] == 2
    assert data["total_chunks"] == 1
    assert data["total_bytes"] == 42
    assert abs(data["total_duration_sec"]) < 0.001
    assert abs(data["mean_delay_sec"]) < 0.001
    assert abs(data["max_delay_sec"]) < 0.001
    assert abs(data["min_delay_sec"]) < 0.001


def test_monotonic_clock_source():
    """sesrec source code should use CLOCK_MONOTONIC for robust timing."""
    with open("/app/src/sesrec.c") as f:
        src = f.read()
    assert "CLOCK_MONOTONIC" in src, (
        "sesrec must use CLOCK_MONOTONIC for timing"
    )


def test_end_to_end_v2():
    """Full round-trip: record with v2 (default), replay, verify content."""
    marker = "E2E_V2_MARKER_98765"
    for f in ["/tmp/t_e2e2_ts", "/tmp/t_e2e2_tm"]:
        if os.path.exists(f):
            os.remove(f)

    cmd = [
        "/app/sesrec", "-q",
        "-o", "/tmp/t_e2e2_ts",
        "-T", "/tmp/t_e2e2_tm",
        "-c", f"echo {marker}",
    ]
    subprocess.run(cmd, timeout=10)

    # Verify v2 header is present (default format)
    with open("/tmp/t_e2e2_tm") as f:
        assert f.readline().strip() == "# sesrec-timing v2 monotonic"

    result = subprocess.run(
        ["/app/sesplay", "-T", "/tmp/t_e2e2_tm", "/tmp/t_e2e2_ts"],
        capture_output=True, text=True, timeout=10,
    )
    assert marker in result.stdout, (
        f"Expected '{marker}' in replayed output, got: '{result.stdout[:200]}'"
    )
