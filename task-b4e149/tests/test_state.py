"""
Tests for the fixed evrecord/evreplay/evanalyze/evaudit toolkit.

"""

import subprocess
import os
import re
import time
import pytest

APP_DIR = "/app"
BIN_DIR = os.path.join(APP_DIR, "bin")
SRC_DIR = os.path.join(APP_DIR, "src")


def run_cmd(cmd, timeout=60, cwd=APP_DIR):
    result = subprocess.run(
        cmd, shell=True, cwd=cwd,
        capture_output=True, text=True, timeout=timeout
    )
    return result


def build():
    result = run_cmd("make clean && make")
    assert result.returncode == 0, f"Build failed: {result.stderr}"


def parse_timing_file(path):
    entries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) == 2:
                try:
                    delay = float(parts[0])
                    nbytes = int(parts[1])
                    entries.append((delay, nbytes))
                except ValueError:
                    continue
    return entries


class TestBuild:
    def test_programs_compile(self):
        """All four programs should compile without errors."""
        build()
        for prog in ["evrecord", "evreplay", "evanalyze", "evaudit"]:
            path = os.path.join(BIN_DIR, prog)
            assert os.path.isfile(path), f"{prog} binary not found at {path}"
            assert os.access(path, os.X_OK), f"{prog} is not executable"


class TestRecorderTiming:
    """Test that the recorder produces accurate timing data."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        build()
        self.timing_file = str(tmp_path / "timing.txt")
        self.data_file = str(tmp_path / "data.txt")
        self.test_script = str(tmp_path / "test_cmd.sh")

        with open(self.test_script, "w") as f:
            f.write("#!/bin/bash\n")
            f.write('echo "ALPHA"\n')
            f.write("sleep 1\n")
            f.write('echo "BRAVO"\n')
            f.write("sleep 2\n")
            f.write('echo "CHARLIE"\n')
        os.chmod(self.test_script, 0o755)

    def record(self):
        cmd = (
            f"{BIN_DIR}/evrecord {self.timing_file} {self.data_file} "
            f"bash {self.test_script}"
        )
        result = run_cmd(cmd, timeout=30)
        assert result.returncode == 0, f"Recording failed: {result.stderr}"

    def test_first_entry_small(self):
        """First timing entry should be small (near-instant output).

        With the time(NULL) bug, this value is a random fraction of a
        second (0.0 to 1.0). After fixing, it should be well under 0.3s.
        We run multiple trials to increase detection reliability.
        """
        for trial in range(3):
            self.record()
            entries = parse_timing_file(self.timing_file)
            assert len(entries) >= 3, (
                f"Trial {trial}: expected >= 3 entries, got {len(entries)}"
            )
            assert entries[0][0] < 0.3, (
                f"Trial {trial}: first entry delay {entries[0][0]:.3f}s "
                f"too large (expected < 0.3s)"
            )
            time.sleep(0.37)

    def test_sleep_timing_accuracy(self):
        """Timing entries should match actual sleep delays.

        After a 1-second sleep, the next entry's delay should be ~1.0s.
        After a 2-second sleep, the next entry's delay should be ~2.0s.
        With the off-by-one bug, these are shifted: entry[1] would be
        ~0.0s and entry[2] would be ~1.0s.
        """
        self.record()
        entries = parse_timing_file(self.timing_file)
        assert len(entries) >= 3, (
            f"Expected >= 3 entries, got {len(entries)}"
        )

        # Find the two largest delays - they should correspond to the sleeps
        delays = sorted([e[0] for e in entries], reverse=True)

        assert abs(delays[0] - 2.0) < 0.4, (
            f"Largest delay {delays[0]:.3f}s not close to 2.0s"
        )
        assert abs(delays[1] - 1.0) < 0.3, (
            f"Second-largest delay {delays[1]:.3f}s not close to 1.0s"
        )

    def test_total_timing(self):
        """Sum of all timing entries should approximate total session."""
        self.record()
        entries = parse_timing_file(self.timing_file)
        total_delay = sum(e[0] for e in entries)

        assert abs(total_delay - 3.0) < 0.8, (
            f"Total delay {total_delay:.3f}s not close to 3.0s"
        )

    def test_byte_counts(self):
        """Byte counts should match actual output sizes."""
        self.record()
        entries = parse_timing_file(self.timing_file)

        # "ALPHA\n" (6) + "BRAVO\n" (6) + "CHARLIE\n" (8) = 20 bytes
        total_bytes = sum(e[1] for e in entries)
        assert total_bytes == 20, (
            f"Total bytes {total_bytes} != expected 20"
        )


class TestRecorderSource:
    """Verify structural fixes in the recorder source code."""

    def test_no_time_null_for_timing(self):
        """Recorder should not use time(NULL) for timing initialization.

        time(NULL) only provides whole-second resolution; the reference
        timestamp must use gettimeofday() for microsecond precision.
        """
        with open(os.path.join(SRC_DIR, "evrecord.c")) as f:
            src = f.read()

        assert "ref_stamp = time(" not in src and \
               "ref_stamp=time(" not in src, \
            "ref_stamp should not be initialized with time()"


class TestReplayerSource:
    """Verify the replayer has no compensating hacks."""

    def test_no_prev_blk_hack(self):
        """Replayer should not use prev_blk compensation pattern."""
        with open(os.path.join(SRC_DIR, "evreplay.c")) as f:
            src = f.read()

        assert "prev_blk" not in src, (
            "Replayer should not use prev_blk compensation hack"
        )
        assert "old_blk" not in src and "oldblk" not in src, (
            "Replayer should not use old_blk/oldblk compensation hack"
        )


class TestAnalyzer:
    """Test that the analyzer produces correct statistics."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        build()
        self.timing_file = str(tmp_path / "timing.txt")
        self.data_file = str(tmp_path / "data.txt")
        self.test_script = str(tmp_path / "test_cmd.sh")

        with open(self.test_script, "w") as f:
            f.write("#!/bin/bash\n")
            f.write('echo "ALPHA"\n')
            f.write("sleep 1\n")
            f.write('echo "BRAVO"\n')
            f.write("sleep 2\n")
            f.write('echo "CHARLIE"\n')
        os.chmod(self.test_script, 0o755)

    def record_and_analyze(self):
        cmd = (
            f"{BIN_DIR}/evrecord {self.timing_file} {self.data_file} "
            f"bash {self.test_script}"
        )
        result = run_cmd(cmd, timeout=30)
        assert result.returncode == 0

        cmd = f"{BIN_DIR}/evanalyze {self.timing_file}"
        result = run_cmd(cmd, timeout=10)
        assert result.returncode == 0
        return result.stdout

    def test_all_entries_counted(self):
        """Analyzer should count all entries, not skip the first one."""
        output = self.record_and_analyze()

        entries_match = re.search(r'Total entries:\s+(\d+)', output)
        analyzed_match = re.search(r'Analyzed entries:\s+(\d+)', output)

        assert entries_match and analyzed_match, (
            f"Could not parse analyzer output:\n{output}"
        )

        total = int(entries_match.group(1))
        analyzed = int(analyzed_match.group(1))

        assert total == analyzed, (
            f"Analyzer skipping entries: total={total}, analyzed={analyzed}"
        )

    def test_total_time_accurate(self):
        """Analyzer total time should be approximately 3 seconds."""
        output = self.record_and_analyze()

        time_match = re.search(r'Total time:\s+([\d.]+)', output)
        assert time_match, f"Could not find total time in:\n{output}"

        total_time = float(time_match.group(1))
        assert abs(total_time - 3.0) < 0.8, (
            f"Total time {total_time:.3f}s not close to 3.0s"
        )

    def test_analyzer_source_no_skip(self):
        """Analyzer source should not skip the first entry."""
        with open(os.path.join(SRC_DIR, "evanalyze.c")) as f:
            lines = f.readlines()

        for i, line in enumerate(lines):
            if 'total_entries == 1' in line:
                context = ''.join(lines[i:i+8])
                assert 'continue' not in context, (
                    "Analyzer should not skip first entry with 'continue'"
                )
                break


class TestEvaudit:
    """Test the evaudit recording validation tool."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        build()
        self.tmp_path = tmp_path

    def test_audit_correct_recording(self):
        """evaudit should PASS a recording produced by the fixed recorder."""
        timing_file = str(self.tmp_path / "timing.txt")
        data_file = str(self.tmp_path / "data.txt")
        test_script = str(self.tmp_path / "test_cmd.sh")

        with open(test_script, "w") as f:
            f.write("#!/bin/bash\n")
            f.write('printf "HELLO"\n')
            f.write("sleep 1\n")
            f.write('printf "WORLD"\n')
        os.chmod(test_script, 0o755)

        cmd = (
            f"{BIN_DIR}/evrecord {timing_file} {data_file} "
            f"bash {test_script}"
        )
        result = run_cmd(cmd, timeout=30)
        assert result.returncode == 0

        cmd = f"{BIN_DIR}/evaudit {timing_file} {data_file}"
        result = run_cmd(cmd, timeout=10)
        assert result.returncode == 0, (
            f"evaudit failed on valid recording:\n{result.stdout}\n{result.stderr}"
        )
        assert "Verdict: PASS" in result.stdout
        assert "Byte match: yes" in result.stdout
        assert "[ok]" in result.stdout

    def test_audit_detects_anomalous_first_delay(self):
        """evaudit should flag a large first-entry delay as anomalous."""
        timing_file = str(self.tmp_path / "timing_bad.txt")
        data_file = str(self.tmp_path / "data_bad.txt")

        # Synthetic timing with large first delay (simulates time() bug)
        with open(timing_file, "w") as f:
            f.write("0.832456 6\n")
            f.write("1.000000 6\n")

        # Data file with matching byte count so only first-delay triggers failure
        with open(data_file, "w") as f:
            f.write("# Session started: 2024-01-15 10:30:00 UTC\n")
            f.write("ALPHA\nBRAVO\n")  # 12 bytes
            f.write("\n# Session ended (1.832 seconds)\n")

        cmd = f"{BIN_DIR}/evaudit {timing_file} {data_file}"
        result = run_cmd(cmd, timeout=10)
        assert result.returncode == 1, (
            f"evaudit should FAIL for anomalous first delay:\n{result.stdout}"
        )
        assert "Verdict: FAIL" in result.stdout
        assert "[anomalous]" in result.stdout

    def test_audit_detects_byte_mismatch(self):
        """evaudit should detect when timing byte counts don't match data."""
        timing_file = str(self.tmp_path / "timing_mismatch.txt")
        data_file = str(self.tmp_path / "data_mismatch.txt")

        # Timing says 8 bytes total, but data has 12 bytes of content
        with open(timing_file, "w") as f:
            f.write("0.001000 5\n")
            f.write("0.001000 3\n")

        with open(data_file, "w") as f:
            f.write("# Session started: 2024-01-15 10:30:00 UTC\n")
            f.write("HELLO WORLD\n")  # 12 bytes
            f.write("\n# Session ended (0.002 seconds)\n")

        cmd = f"{BIN_DIR}/evaudit {timing_file} {data_file}"
        result = run_cmd(cmd, timeout=10)
        assert result.returncode == 1, (
            f"evaudit should FAIL for byte mismatch:\n{result.stdout}"
        )
        assert "Verdict: FAIL" in result.stdout
        assert "Byte match: no" in result.stdout

    def test_audit_detects_negative_delay(self):
        """evaudit should detect negative timing delays."""
        timing_file = str(self.tmp_path / "timing_neg.txt")
        data_file = str(self.tmp_path / "data_neg.txt")

        with open(timing_file, "w") as f:
            f.write("0.001000 3\n")
            f.write("-0.500000 3\n")

        with open(data_file, "w") as f:
            f.write("# Session started: 2024-01-15 10:30:00 UTC\n")
            f.write("FOOBAR")  # 6 bytes, no trailing newline
            f.write("\n# Session ended (0.001 seconds)\n")

        cmd = f"{BIN_DIR}/evaudit {timing_file} {data_file}"
        result = run_cmd(cmd, timeout=10)
        assert result.returncode == 1, (
            f"evaudit should FAIL for negative delay:\n{result.stdout}"
        )
        assert "Verdict: FAIL" in result.stdout
        assert "Negative delays: 1" in result.stdout

    def test_audit_rejects_empty_timing(self):
        """evaudit should FAIL on an empty timing file."""
        timing_file = str(self.tmp_path / "timing_empty.txt")
        data_file = str(self.tmp_path / "data_empty.txt")

        with open(timing_file, "w") as f:
            pass  # empty

        with open(data_file, "w") as f:
            f.write("# Session started: 2024-01-15 10:30:00 UTC\n")
            f.write("\n# Session ended (0.000 seconds)\n")

        cmd = f"{BIN_DIR}/evaudit {timing_file} {data_file}"
        result = run_cmd(cmd, timeout=10)
        assert result.returncode == 1, (
            f"evaudit should FAIL for empty timing:\n{result.stdout}"
        )
        assert "Verdict: FAIL" in result.stdout
        assert "Timing entries: 0" in result.stdout


class TestEndToEnd:
    """End-to-end: record, replay, analyze, and audit."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        build()
        self.tmp_path = tmp_path

    def test_full_pipeline(self):
        """Recording, replay, analysis, and audit should all be consistent."""
        timing_file = str(self.tmp_path / "timing.txt")
        data_file = str(self.tmp_path / "data.txt")
        test_script = str(self.tmp_path / "test_cmd.sh")

        with open(test_script, "w") as f:
            f.write("#!/bin/bash\n")
            f.write('printf "X"\n')
            f.write("sleep 1\n")
            f.write('printf "YY"\n')
            f.write("sleep 1\n")
            f.write('printf "ZZZ"\n')
        os.chmod(test_script, 0o755)

        # Record
        cmd = (
            f"{BIN_DIR}/evrecord {timing_file} {data_file} "
            f"bash {test_script}"
        )
        result = run_cmd(cmd, timeout=30)
        assert result.returncode == 0, f"Record failed: {result.stderr}"

        # Parse timing
        entries = parse_timing_file(timing_file)
        assert len(entries) >= 3, f"Expected >= 3 entries, got {len(entries)}"

        # Verify byte counts: X(1) + YY(2) + ZZZ(3) = 6
        total_bytes = sum(e[1] for e in entries)
        assert total_bytes == 6, f"Total bytes {total_bytes} != 6"

        # Verify timing: total should be ~2s
        total_delay = sum(e[0] for e in entries)
        assert abs(total_delay - 2.0) < 0.6, (
            f"Total delay {total_delay:.3f}s not close to 2.0s"
        )

        # Replay at 1000x speed and check output content
        cmd = f"{BIN_DIR}/evreplay {timing_file} {data_file} 1000"
        result = run_cmd(cmd, timeout=10)
        assert result.returncode == 0, f"Replay failed: {result.stderr}"
        assert "XYYZZZ" in result.stdout, (
            f"Replay output missing expected data: '{result.stdout}'"
        )

        # Analyze
        cmd = f"{BIN_DIR}/evanalyze {timing_file}"
        result = run_cmd(cmd, timeout=10)
        assert result.returncode == 0

        bytes_match = re.search(r'Total bytes:\s+(\d+)', result.stdout)
        assert bytes_match, "Could not find total bytes in analyzer output"
        assert int(bytes_match.group(1)) == 6

        entries_match = re.search(r'Total entries:\s+(\d+)', result.stdout)
        analyzed_match = re.search(r'Analyzed entries:\s+(\d+)', result.stdout)
        assert entries_match and analyzed_match
        assert entries_match.group(1) == analyzed_match.group(1), (
            "Analyzer should count all entries equally"
        )

        # Audit
        cmd = f"{BIN_DIR}/evaudit {timing_file} {data_file}"
        result = run_cmd(cmd, timeout=10)
        assert result.returncode == 0, (
            f"Audit failed on valid recording:\n{result.stdout}"
        )
        assert "Verdict: PASS" in result.stdout
        assert "Byte match: yes" in result.stdout
