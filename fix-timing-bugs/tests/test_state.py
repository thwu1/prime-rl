"""
Tests for session recording/replay system.

"""

import subprocess
import os
import select
import time
import pytest


def build():
    """Build the main programs."""
    result = subprocess.run(
        ["make", "-C", "/app", "clean", "all"],
        capture_output=True, text=True
    )
    assert result.returncode == 0, f"Build failed: {result.stderr}"


def parse_timing_file(path):
    """Parse a timing file, skipping comment/header lines."""
    entries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split()
            if len(parts) >= 2:
                entries.append((float(parts[0]), int(parts[1])))
    return entries


def run_recording(command, datafile, timingfile, timeout=30):
    """Run the recorder with a command and return parsed timing entries."""
    result = subprocess.run(
        ["/app/recorder", "-q", "-d", datafile, "-t", timingfile, "--"] +
        command,
        capture_output=True, text=True, timeout=timeout
    )
    assert result.returncode == 0, \
        f"Recorder failed (rc={result.returncode}): {result.stderr}"
    return parse_timing_file(timingfile)


class TestRecorderTimingAccuracy:
    @classmethod
    def setup_class(cls):
        build()

    def test_first_entry_precision(self, tmp_path):
        """First timing entry should have sub-second precision for
        instant-output recordings."""
        first_delays = []
        for i in range(5):
            df = str(tmp_path / f"prec_{i}.dat")
            tf = str(tmp_path / f"prec_{i}.tim")
            entries = run_recording(
                ["python3", "-c",
                 "import sys; sys.stdout.write('X'); sys.stdout.flush()"],
                df, tf
            )
            assert len(entries) >= 1, "No timing entries recorded"
            first_delays.append(entries[0][0])

        avg = sum(first_delays) / len(first_delays)
        assert avg < 0.15, (
            f"Average first-entry delay across 5 recordings is {avg:.4f}s "
            f"(values: {[f'{d:.4f}' for d in first_delays]}). "
            f"Expected < 0.15s for instant-output recordings."
        )

    def test_timing_alignment(self, tmp_path):
        """Timing entries must align with actual inter-chunk delays."""
        datafile = str(tmp_path / "align.dat")
        timingfile = str(tmp_path / "align.tim")

        script = str(tmp_path / "pattern.py")
        with open(script, "w") as f:
            f.write(
                "import sys, time\n"
                "sys.stdout.write('AA'); sys.stdout.flush()\n"
                "time.sleep(0.5)\n"
                "sys.stdout.write('BB'); sys.stdout.flush()\n"
                "time.sleep(1.0)\n"
                "sys.stdout.write('CC'); sys.stdout.flush()\n"
            )

        entries = run_recording(["python3", script], datafile, timingfile)
        assert len(entries) >= 3, (
            f"Expected >= 3 timing entries, got {len(entries)}"
        )

        delays = [e[0] for e in entries]

        assert 0.2 < delays[1] < 0.8, (
            f"Second timing entry is {delays[1]:.4f}s, expected ~0.5s "
            f"to reflect the 0.5s sleep between first and second chunks."
        )

        assert 0.7 < delays[2] < 1.5, (
            f"Third timing entry is {delays[2]:.4f}s, expected ~1.0s "
            f"to reflect the 1.0s sleep between second and third chunks."
        )

    def test_byte_counts_match_data(self, tmp_path):
        """Sum of byte counts in the timing file must equal data file
        size."""
        datafile = str(tmp_path / "bytes.dat")
        timingfile = str(tmp_path / "bytes.tim")

        script = str(tmp_path / "btest.py")
        with open(script, "w") as f:
            f.write(
                "import sys, time\n"
                "sys.stdout.write('Hello'); sys.stdout.flush()\n"
                "time.sleep(0.3)\n"
                "sys.stdout.write('World!'); sys.stdout.flush()\n"
            )

        entries = run_recording(["python3", script], datafile, timingfile)
        total_timing = sum(e[1] for e in entries)
        data_size = os.path.getsize(datafile)
        assert total_timing == data_size, (
            f"Timing byte total ({total_timing}) != data file size "
            f"({data_size})"
        )

    def test_data_content(self, tmp_path):
        """Data file must contain exact subprocess output."""
        datafile = str(tmp_path / "content.dat")
        timingfile = str(tmp_path / "content.tim")

        run_recording(
            ["python3", "-c", "print('hello world')"],
            datafile, timingfile
        )

        with open(datafile, "rb") as f:
            content = f.read()
        assert b"hello world" in content


class TestReplayerCorrectness:
    @classmethod
    def setup_class(cls):
        build()

    def test_replayer_emits_first_chunk_promptly(self, tmp_path):
        """First data chunk must appear without anomalous delay."""
        datafile = str(tmp_path / "prompt.dat")
        timingfile = str(tmp_path / "prompt.tim")

        with open(datafile, "wb") as f:
            f.write(b"FIRSTSECOND_DATA")
        with open(timingfile, "w") as f:
            f.write("0.01 5\n")
            f.write("2.0 11\n")

        proc = subprocess.Popen(
            ["/app/replayer", "-d", datafile, "-t", timingfile],
            stdout=subprocess.PIPE
        )

        try:
            fd = proc.stdout.fileno()
            readable, _, _ = select.select([fd], [], [], 1.0)
            if readable:
                data = os.read(fd, 1024)
                assert len(data) >= 5, (
                    f"First output chunk too small ({len(data)} bytes)"
                )
            else:
                assert False, (
                    "Replayer did not emit first data chunk within 1.0s "
                    "-- output appears to be deferred beyond the first "
                    "timing entry."
                )
        finally:
            proc.kill()
            proc.wait()

    def test_replayer_all_data_uniform(self, tmp_path):
        """Replayer must output all data with uniform chunk sizes."""
        datafile = str(tmp_path / "uniform.dat")
        timingfile = str(tmp_path / "uniform.tim")

        with open(datafile, "wb") as f:
            f.write(b"AAABBBCCC")
        with open(timingfile, "w") as f:
            f.write("0.001 3\n0.001 3\n0.001 3\n")

        result = subprocess.run(
            ["/app/replayer", "-d", datafile, "-t", timingfile,
             "-s", "100"],
            capture_output=True, timeout=10
        )
        assert result.stdout == b"AAABBBCCC", (
            f"Replayer output {result.stdout!r} != b'AAABBBCCC'"
        )

    def test_replayer_all_data_varied(self, tmp_path):
        """Replayer must output all data with varied chunk sizes."""
        datafile = str(tmp_path / "varied.dat")
        timingfile = str(tmp_path / "varied.tim")

        with open(datafile, "wb") as f:
            f.write(b"ABCDEFGHIJ")
        with open(timingfile, "w") as f:
            f.write("0.001 1\n0.001 2\n0.001 3\n0.001 4\n")

        result = subprocess.run(
            ["/app/replayer", "-d", datafile, "-t", timingfile,
             "-s", "100"],
            capture_output=True, timeout=10
        )
        assert result.stdout == b"ABCDEFGHIJ", (
            f"Replayer output {result.stdout!r} != b'ABCDEFGHIJ'"
        )

    def test_replayer_handles_header(self, tmp_path):
        """Replayer must correctly skip header lines in timing files."""
        datafile = str(tmp_path / "hdr.dat")
        timingfile = str(tmp_path / "hdr.tim")

        with open(datafile, "wb") as f:
            f.write(b"TESTDATA")
        with open(timingfile, "w") as f:
            f.write("# recorder v1.0 ts=2024-01-01T00:00:00 "
                    "cmd=test\n")
            f.write("0.001 4\n0.001 4\n")

        result = subprocess.run(
            ["/app/replayer", "-d", datafile, "-t", timingfile,
             "-s", "100"],
            capture_output=True, timeout=10
        )
        assert result.stdout == b"TESTDATA", (
            f"Replayer output with header: {result.stdout!r} != "
            f"b'TESTDATA'"
        )


class TestAnalysis:
    """Verify the architectural evaluation document covers all required
    topics demonstrating genuine understanding of the coupled-bug
    interaction."""

    def test_analysis_exists(self):
        """ANALYSIS.md must exist at /app/ANALYSIS.md."""
        assert os.path.isfile("/app/ANALYSIS.md"), (
            "ANALYSIS.md not found at /app/ANALYSIS.md"
        )

    def test_analysis_covers_clock_precision_defect(self):
        """Analysis must discuss the clock precision mismatch."""
        if not os.path.isfile("/app/ANALYSIS.md"):
            pytest.skip("ANALYSIS.md not found")
        with open("/app/ANALYSIS.md") as f:
            text = f.read().lower()
        found = any(kw in text for kw in [
            "time(null)", "time()", "whole second", "second granularity",
            "second precision", "truncat", "integer second",
            "lacks microsecond", "no fractional",
        ])
        assert found, (
            "ANALYSIS.md must discuss the clock precision defect"
        )

    def test_analysis_covers_measurement_placement(self):
        """Analysis must discuss timing measurement placement relative
        to I/O."""
        if not os.path.isfile("/app/ANALYSIS.md"):
            pytest.skip("ANALYSIS.md not found")
        with open("/app/ANALYSIS.md") as f:
            text = f.read().lower()
        found = any(kw in text for kw in [
            "before read", "after read", "before the read",
            "after the read", "gettimeofday",
            "sampling point", "measurement point",
            "sample time", "samples time",
        ])
        assert found, (
            "ANALYSIS.md must discuss the timing measurement placement "
            "relative to the I/O call"
        )

    def test_analysis_covers_offbyone_shift(self):
        """Analysis must discuss the timing shift phenomenon."""
        if not os.path.isfile("/app/ANALYSIS.md"):
            pytest.skip("ANALYSIS.md not found")
        with open("/app/ANALYSIS.md") as f:
            text = f.read().lower()
        found = any(kw in text for kw in [
            "off-by-one", "off by one", "shifted", "shift",
            "offset by one", "one iteration", "wrong interval",
            "wrong chunk", "misalign",
        ])
        assert found, (
            "ANALYSIS.md must discuss the timing shift where each delay "
            "corresponds to the wrong chunk"
        )

    def test_analysis_covers_coupled_bug(self):
        """Analysis must discuss the interaction between recorder and
        replayer defects."""
        if not os.path.isfile("/app/ANALYSIS.md"):
            pytest.skip("ANALYSIS.md not found")
        with open("/app/ANALYSIS.md") as f:
            text = f.read().lower()
        found = any(kw in text for kw in [
            "oldblk", "compensat", "coupled", "deferred",
            "defer", "mask", "previous entry",
            "previous block", "old block",
        ])
        assert found, (
            "ANALYSIS.md must discuss the replayer's compensating "
            "behavior"
        )

    def test_analysis_discusses_migration_rationale(self):
        """Analysis must explain the migration design approach."""
        if not os.path.isfile("/app/ANALYSIS.md"):
            pytest.skip("ANALYSIS.md not found")
        with open("/app/ANALYSIS.md") as f:
            text = f.read().lower()
        found = any(kw in text for kw in [
            "migrat", "convert", "transform", "inverse",
            "legacy recording", "buggy recording",
            "corrected recording",
        ])
        assert found, (
            "ANALYSIS.md must discuss the migration/conversion "
            "design rationale"
        )

    def test_analysis_minimum_depth(self):
        """Analysis must have substantive content (not a stub)."""
        if not os.path.isfile("/app/ANALYSIS.md"):
            pytest.skip("ANALYSIS.md not found")
        with open("/app/ANALYSIS.md") as f:
            text = f.read()
        word_count = len(text.split())
        assert word_count >= 200, (
            f"ANALYSIS.md has only {word_count} words. "
            f"A substantive evaluation requires at least 200 words."
        )


class TestMigrator:
    """Verify the migrator correctly transforms legacy recordings."""

    @classmethod
    def setup_class(cls):
        build()

    def test_migrator_exists(self):
        """Migrator binary must exist at /app/migrator."""
        assert os.path.isfile("/app/migrator"), (
            "migrator binary not found at /app/migrator"
        )

    def test_migrator_corrects_timing(self, tmp_path):
        """Migrator must produce correctly-timed output from a
        synthetically buggy recording."""
        if not os.path.isfile("/app/migrator"):
            pytest.skip("migrator not built")

        in_data = str(tmp_path / "buggy.dat")
        in_timing = str(tmp_path / "buggy.tim")
        out_data = str(tmp_path / "fixed.dat")
        out_timing = str(tmp_path / "fixed.tim")

        with open(in_data, "wb") as f:
            f.write(b"AABBCCDD")  # 4 chunks, 2 bytes each

        # Simulate a buggy recording: garbage first delay, then
        # each subsequent delay is shifted forward by one position
        with open(in_timing, "w") as f:
            f.write("# recorder v1.0 ts=2024-01-01T00:00:00 cmd=test\n")
            f.write("0.743218 2\n")
            f.write("0.001500 2\n")
            f.write("1.002000 2\n")
            f.write("0.500000 2\n")

        result = subprocess.run(
            ["/app/migrator", "-d", in_data, "-t", in_timing,
             "-D", out_data, "-T", out_timing],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0, (
            f"Migrator failed: {result.stderr}"
        )

        entries = parse_timing_file(out_timing)
        assert len(entries) == 4, (
            f"Expected 4 migrated entries, got {len(entries)}"
        )

        # After correction: entry 0 gets delay 0.001500
        assert abs(entries[0][0] - 0.001500) < 0.0001, (
            f"Migrated entry 0 delay {entries[0][0]:.6f} != ~0.001500"
        )
        assert entries[0][1] == 2

        # Entry 1 gets delay 1.002000
        assert abs(entries[1][0] - 1.002000) < 0.0001, (
            f"Migrated entry 1 delay {entries[1][0]:.6f} != ~1.002000"
        )
        assert entries[1][1] == 2

        # Entry 2 gets delay 0.500000
        assert abs(entries[2][0] - 0.500000) < 0.0001, (
            f"Migrated entry 2 delay {entries[2][0]:.6f} != ~0.500000"
        )
        assert entries[2][1] == 2

        # Last entry: unrecoverable, should be ~0
        assert entries[3][0] < 0.001, (
            f"Migrated last entry delay {entries[3][0]:.6f} should "
            f"be ~0.0 (unrecoverable)"
        )
        assert entries[3][1] == 2

    def test_migrator_preserves_data(self, tmp_path):
        """Migrator must copy the data file unchanged."""
        if not os.path.isfile("/app/migrator"):
            pytest.skip("migrator not built")

        in_data = str(tmp_path / "orig.dat")
        in_timing = str(tmp_path / "orig.tim")
        out_data = str(tmp_path / "out.dat")
        out_timing = str(tmp_path / "out.tim")

        payload = b"Hello, World! This is test data with various bytes."
        with open(in_data, "wb") as f:
            f.write(payload)
        with open(in_timing, "w") as f:
            f.write("0.500000 25\n")
            f.write("0.001000 25\n")

        result = subprocess.run(
            ["/app/migrator", "-d", in_data, "-t", in_timing,
             "-D", out_data, "-T", out_timing],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0

        with open(out_data, "rb") as f:
            assert f.read() == payload, (
                "Migrator must copy data file unchanged"
            )

    def test_migrator_single_entry(self, tmp_path):
        """Migrator must handle single-entry recordings gracefully."""
        if not os.path.isfile("/app/migrator"):
            pytest.skip("migrator not built")

        in_data = str(tmp_path / "single.dat")
        in_timing = str(tmp_path / "single.tim")
        out_data = str(tmp_path / "out.dat")
        out_timing = str(tmp_path / "out.tim")

        with open(in_data, "wb") as f:
            f.write(b"X")
        with open(in_timing, "w") as f:
            f.write("0.543210 1\n")

        result = subprocess.run(
            ["/app/migrator", "-d", in_data, "-t", in_timing,
             "-D", out_data, "-T", out_timing],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0

        entries = parse_timing_file(out_timing)
        assert len(entries) == 1
        assert entries[0][0] < 0.001, (
            f"Single-entry delay should be ~0, got {entries[0][0]:.6f}"
        )
        assert entries[0][1] == 1

    def test_migrator_handles_comments(self, tmp_path):
        """Migrator must skip comment lines in timing files."""
        if not os.path.isfile("/app/migrator"):
            pytest.skip("migrator not built")

        in_data = str(tmp_path / "hdr.dat")
        in_timing = str(tmp_path / "hdr.tim")
        out_data = str(tmp_path / "out.dat")
        out_timing = str(tmp_path / "out.tim")

        with open(in_data, "wb") as f:
            f.write(b"AABB")
        with open(in_timing, "w") as f:
            f.write("# recorder v1.0 ts=2024-01-01T00:00:00 cmd=echo\n")
            f.write("# extra comment line\n")
            f.write("0.800000 2\n")
            f.write("0.005000 2\n")

        result = subprocess.run(
            ["/app/migrator", "-d", in_data, "-t", in_timing,
             "-D", out_data, "-T", out_timing],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0

        entries = parse_timing_file(out_timing)
        assert len(entries) == 2
        assert abs(entries[0][0] - 0.005000) < 0.0001
        assert entries[0][1] == 2
        assert entries[1][0] < 0.001
        assert entries[1][1] == 2

    def test_migrator_byte_counts_unchanged(self, tmp_path):
        """Byte counts must remain in their original positions after
        migration."""
        if not os.path.isfile("/app/migrator"):
            pytest.skip("migrator not built")

        in_data = str(tmp_path / "bc.dat")
        in_timing = str(tmp_path / "bc.tim")
        out_data = str(tmp_path / "out.dat")
        out_timing = str(tmp_path / "out.tim")

        with open(in_data, "wb") as f:
            f.write(b"A" * 15)  # 15 bytes total
        with open(in_timing, "w") as f:
            f.write("0.900000 5\n")
            f.write("0.010000 3\n")
            f.write("1.500000 7\n")

        result = subprocess.run(
            ["/app/migrator", "-d", in_data, "-t", in_timing,
             "-D", out_data, "-T", out_timing],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0

        entries = parse_timing_file(out_timing)
        assert len(entries) == 3
        # Byte counts must stay: 5, 3, 7
        assert entries[0][1] == 5
        assert entries[1][1] == 3
        assert entries[2][1] == 7
        # Delays corrected
        assert abs(entries[0][0] - 0.010000) < 0.0001
        assert abs(entries[1][0] - 1.500000) < 0.0001
        assert entries[2][0] < 0.001


class TestValidator:
    @classmethod
    def setup_class(cls):
        build()

    def test_validator_exists(self):
        """Validator binary must exist at /app/validator."""
        assert os.path.isfile("/app/validator"), (
            "validator binary not found at /app/validator"
        )

    def test_validator_accepts_valid_recording(self, tmp_path):
        """Validator must exit 0 on a correct recording."""
        if not os.path.isfile("/app/validator"):
            pytest.skip("validator not built")

        datafile = str(tmp_path / "valid.dat")
        timingfile = str(tmp_path / "valid.tim")

        run_recording(
            ["python3", "-c",
             "import sys, time; "
             "sys.stdout.write('hello'); sys.stdout.flush(); "
             "time.sleep(0.2); "
             "sys.stdout.write('world'); sys.stdout.flush()"],
            datafile, timingfile
        )

        result = subprocess.run(
            ["/app/validator", "-d", datafile, "-t", timingfile],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0, (
            f"Validator rejected a valid recording: {result.stderr}"
        )

    def test_validator_rejects_byte_mismatch(self, tmp_path):
        """Validator must exit 1 when byte counts don't match data
        file size."""
        if not os.path.isfile("/app/validator"):
            pytest.skip("validator not built")

        datafile = str(tmp_path / "bad_bytes.dat")
        timingfile = str(tmp_path / "bad_bytes.tim")

        with open(datafile, "wb") as f:
            f.write(b"ABCDE")  # 5 bytes
        with open(timingfile, "w") as f:
            f.write("0.1 3\n0.2 5\n")  # claims 8 bytes total

        result = subprocess.run(
            ["/app/validator", "-d", datafile, "-t", timingfile],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 1, (
            f"Validator accepted recording with byte count mismatch "
            f"(timing says 8, data is 5 bytes)"
        )

    def test_validator_rejects_negative_delay(self, tmp_path):
        """Validator must exit 1 when a timing entry has negative
        delay."""
        if not os.path.isfile("/app/validator"):
            pytest.skip("validator not built")

        datafile = str(tmp_path / "neg_delay.dat")
        timingfile = str(tmp_path / "neg_delay.tim")

        with open(datafile, "wb") as f:
            f.write(b"ABCDEF")  # 6 bytes
        with open(timingfile, "w") as f:
            f.write("0.1 3\n-0.5 3\n")  # negative delay

        result = subprocess.run(
            ["/app/validator", "-d", datafile, "-t", timingfile],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 1, (
            "Validator accepted recording with negative delay"
        )

    def test_validator_handles_header_comments(self, tmp_path):
        """Validator must skip comment lines in timing files."""
        if not os.path.isfile("/app/validator"):
            pytest.skip("validator not built")

        datafile = str(tmp_path / "hdr.dat")
        timingfile = str(tmp_path / "hdr.tim")

        with open(datafile, "wb") as f:
            f.write(b"ABCDEF")  # 6 bytes
        with open(timingfile, "w") as f:
            f.write("# recorder v1.0 ts=2024-01-01T00:00:00 "
                    "cmd=test\n")
            f.write("0.1 3\n0.2 3\n")  # 6 bytes total

        result = subprocess.run(
            ["/app/validator", "-d", datafile, "-t", timingfile],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0, (
            f"Validator failed on recording with header comments: "
            f"{result.stderr}"
        )


class TestEndToEnd:
    @classmethod
    def setup_class(cls):
        build()

    def test_record_and_replay_content(self, tmp_path):
        """Full round-trip: record and replay, verifying content
        preservation."""
        datafile = str(tmp_path / "e2e.dat")
        timingfile = str(tmp_path / "e2e.tim")

        result = subprocess.run(
            ["/app/recorder", "-q", "-d", datafile, "-t", timingfile,
             "--", "python3", "-c",
             "import sys; "
             "sys.stdout.write('round-trip-test'); "
             "sys.stdout.flush()"],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, \
            f"Recorder failed: {result.stderr}"

        result = subprocess.run(
            ["/app/replayer", "-d", datafile, "-t", timingfile,
             "-s", "100"],
            capture_output=True, timeout=30
        )
        assert b"round-trip-test" in result.stdout, (
            f"Round-trip replay failed. Output: {result.stdout!r}"
        )

    def test_record_replay_timing_fidelity(self, tmp_path):
        """Recorded timing must reflect actual delays and replayer
        must reproduce all content."""
        datafile = str(tmp_path / "fidelity.dat")
        timingfile = str(tmp_path / "fidelity.tim")

        script = str(tmp_path / "ftscript.py")
        with open(script, "w") as f:
            f.write(
                "import sys, time\n"
                "sys.stdout.write('X'); sys.stdout.flush()\n"
                "time.sleep(0.4)\n"
                "sys.stdout.write('Y'); sys.stdout.flush()\n"
            )

        result = subprocess.run(
            ["/app/recorder", "-q", "-d", datafile, "-t", timingfile,
             "--", "python3", script],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0

        entries = parse_timing_file(timingfile)
        assert len(entries) >= 2, \
            f"Expected >= 2 entries, got {len(entries)}"
        assert entries[0][0] < 0.3, (
            f"First delay {entries[0][0]:.4f}s too large"
        )
        assert 0.2 < entries[1][0] < 0.8, (
            f"Second delay {entries[1][0]:.4f}s not ~0.4s"
        )

        result = subprocess.run(
            ["/app/replayer", "-d", datafile, "-t", timingfile,
             "-s", "100"],
            capture_output=True, timeout=30
        )
        assert result.stdout == b"XY", (
            f"Replay output {result.stdout!r} != b'XY'"
        )
