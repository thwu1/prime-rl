
import subprocess
import os
import pytest


class TestPipelineStatic:
    """Tests with original 3 input log files."""

    @classmethod
    def setup_class(cls):
        subprocess.run(["rm", "-rf", "/app/output", "/app/tmp"], check=False)
        cls.result = subprocess.run(
            ["bash", "/app/pipeline.sh"],
            capture_output=True,
            text=True,
            timeout=120,
        )

    def test_pipeline_exits_successfully(self):
        assert self.result.returncode == 0, (
            f"Pipeline failed (exit {self.result.returncode}):\n"
            f"stdout: {self.result.stdout[:500]}\n"
            f"stderr: {self.result.stderr[:500]}"
        )

    # ── manifest ──

    def test_manifest_exists(self):
        assert os.path.isfile("/app/output/manifest.txt"), "manifest.txt missing"

    def test_manifest_content(self):
        with open("/app/output/manifest.txt") as f:
            content = f.read().strip()
        lines = content.split("\n")
        assert len(lines) == 3, f"Expected 3 manifest entries, got {len(lines)}"
        manifest = {}
        for line in lines:
            parts = line.split("|")
            assert len(parts) == 2, f"Malformed manifest line: {line}"
            manifest[parts[0]] = int(parts[1])
        assert manifest == {
            "server1.log": 5,
            "server2.log": 6,
            "server3.log": 4,
        }

    # ── archives ──

    def test_archive_files_exist(self):
        for i in [1, 2, 3]:
            path = f"/app/output/archive/{i}.txt"
            assert os.path.isfile(path), f"{path} does not exist"

    def test_archive_files_distinct(self):
        contents = []
        for i in [1, 2, 3]:
            with open(f"/app/output/archive/{i}.txt") as f:
                contents.append(f.read())
        assert len(set(contents)) == 3, "All 3 archive files must have distinct content"

    def test_archive_has_header(self):
        with open("/app/header.txt") as f:
            header = f.read().strip()
        for i in [1, 2, 3]:
            with open(f"/app/output/archive/{i}.txt") as f:
                content = f.read()
            assert content.startswith(header), (
                f"archive/{i}.txt should start with header"
            )

    def test_archive_content_mapping(self):
        """Archive N maps to the Nth file in sorted filename order."""
        with open("/app/header.txt") as f:
            header = f.read()
        for idx, name in enumerate(["server1.log", "server2.log", "server3.log"], 1):
            with open(f"/app/input/{name}") as f:
                log = f.read()
            with open(f"/app/output/archive/{idx}.txt") as f:
                archive = f.read()
            assert archive == header + log, (
                f"archive/{idx}.txt should equal header.txt + {name}"
            )

    # ── summary ──

    def test_summary_exists(self):
        assert os.path.isfile("/app/output/summary.txt"), "summary.txt missing"

    def test_summary_severity_counts(self):
        with open("/app/output/summary.txt") as f:
            content = f.read()
        assert "INFO: 8" in content, "Summary should report INFO: 8"
        assert "WARN: 3" in content, "Summary should report WARN: 3"
        assert "ERROR: 4" in content, "Summary should report ERROR: 4"
        assert "Total lines: 15" in content, "Summary should report Total lines: 15"

    def test_summary_file_count(self):
        with open("/app/output/summary.txt") as f:
            content = f.read()
        assert "Total files processed: 3" in content

    def test_summary_exact_format(self):
        expected_lines = [
            "PROCESSING SUMMARY",
            "=" * 40,
            "Total files processed: 3",
            "=" * 40,
            "INFO: 8",
            "WARN: 3",
            "ERROR: 4",
            "=" * 40,
            "Total lines: 15",
        ]
        with open("/app/output/summary.txt") as f:
            lines = [l.rstrip("\n") for l in f.readlines()]
        while lines and lines[-1] == "":
            lines.pop()
        assert lines == expected_lines, (
            f"Summary format mismatch.\nExpected:\n"
            + "\n".join(expected_lines)
            + f"\n\nGot:\n"
            + "\n".join(lines)
        )

    # ── alerts / burst detection ──

    def test_alerts_file_exists(self):
        assert os.path.isfile("/app/output/alerts.txt"), "alerts.txt missing"

    def test_alerts_single_burst(self):
        with open("/app/output/alerts.txt") as f:
            content = f.read().strip()
        lines = content.split("\n")
        assert len(lines) == 1, f"Expected 1 burst, got {len(lines)}: {content}"

    def test_alerts_burst_format(self):
        with open("/app/output/alerts.txt") as f:
            line = f.read().strip()
        parts = line.split("|")
        assert len(parts) == 5, f"Burst line should have 5 pipe-separated fields: {line}"
        assert parts[0] == "BURST", f"Burst line must start with BURST: {line}"

    def test_alerts_burst_timestamps(self):
        with open("/app/output/alerts.txt") as f:
            line = f.read().strip()
        parts = line.split("|")
        assert parts[1] == "2024-01-15T10:30:45", (
            f"Burst start should be 2024-01-15T10:30:45, got {parts[1]}"
        )
        assert parts[2] == "2024-01-15T10:31:45", (
            f"Burst end should be 2024-01-15T10:31:45, got {parts[2]}"
        )

    def test_alerts_burst_count(self):
        with open("/app/output/alerts.txt") as f:
            line = f.read().strip()
        parts = line.split("|")
        assert parts[3] == "3", f"Burst error count should be 3, got {parts[3]}"

    def test_alerts_burst_sources(self):
        with open("/app/output/alerts.txt") as f:
            line = f.read().strip()
        parts = line.split("|")
        files = sorted(parts[4].split(","))
        assert files == ["server1.log", "server2.log", "server3.log"], (
            f"Burst sources should be server1,server2,server3, got {parts[4]}"
        )


class TestPipelineDynamic:
    """Re-run pipeline with a 4th log file to verify generalization."""

    @classmethod
    def setup_class(cls):
        subprocess.run(["rm", "-rf", "/app/output", "/app/tmp"], check=False)
        with open("/app/input/server4.log", "w") as f:
            f.write("2024-01-16T08:00:00|ERROR|Service crash alpha\n")
            f.write("2024-01-16T08:00:15|ERROR|Service crash beta\n")
            f.write("2024-01-16T08:00:30|ERROR|Service crash gamma\n")
            f.write("2024-01-16T08:01:00|WARN|Recovery initiated\n")
            f.write("2024-01-16T08:02:00|WARN|Recovery completed\n")
        cls.result = subprocess.run(
            ["bash", "/app/pipeline.sh"],
            capture_output=True,
            text=True,
            timeout=120,
        )

    @classmethod
    def teardown_class(cls):
        if os.path.exists("/app/input/server4.log"):
            os.remove("/app/input/server4.log")
        subprocess.run(["rm", "-rf", "/app/output", "/app/tmp"], check=False)

    def test_dynamic_pipeline_succeeds(self):
        assert self.result.returncode == 0, (
            f"Pipeline failed with added file:\n"
            f"stdout: {self.result.stdout[:500]}\n"
            f"stderr: {self.result.stderr[:500]}"
        )

    def test_dynamic_manifest_has_four_entries(self):
        with open("/app/output/manifest.txt") as f:
            lines = f.read().strip().split("\n")
        assert len(lines) == 4, f"Expected 4 manifest entries, got {len(lines)}"

    def test_dynamic_manifest_includes_server4(self):
        with open("/app/output/manifest.txt") as f:
            content = f.read()
        assert "server4.log|5" in content, (
            f"Manifest should contain server4.log|5"
        )

    def test_dynamic_severity_counts(self):
        with open("/app/output/summary.txt") as f:
            content = f.read()
        assert "INFO: 8" in content, "INFO count should remain 8"
        assert "WARN: 5" in content, "WARN count should be 3+2=5"
        assert "ERROR: 7" in content, "ERROR count should be 4+3=7"
        assert "Total files processed: 4" in content
        assert "Total lines: 20" in content, "Total should be 8+5+7=20"

    def test_dynamic_four_archives_exist(self):
        for i in range(1, 5):
            path = f"/app/output/archive/{i}.txt"
            assert os.path.isfile(path), f"{path} does not exist"

    def test_dynamic_archives_distinct(self):
        contents = []
        for i in range(1, 5):
            with open(f"/app/output/archive/{i}.txt") as f:
                contents.append(f.read())
        assert len(set(contents)) == 4, "All 4 archive files must be distinct"

    def test_dynamic_two_bursts(self):
        with open("/app/output/alerts.txt") as f:
            content = f.read().strip()
        lines = content.split("\n")
        assert len(lines) == 2, f"Expected 2 bursts with 4 files, got {len(lines)}: {content}"

    def test_dynamic_original_burst_preserved(self):
        with open("/app/output/alerts.txt") as f:
            content = f.read().strip()
        lines = content.split("\n")
        parts = lines[0].split("|")
        assert parts[0] == "BURST"
        assert parts[1] == "2024-01-15T10:30:45", (
            f"First burst start should be 2024-01-15T10:30:45, got {parts[1]}"
        )
        assert parts[2] == "2024-01-15T10:31:45", (
            f"First burst end should be 2024-01-15T10:31:45, got {parts[2]}"
        )
        assert parts[3] == "3"

    def test_dynamic_new_burst(self):
        with open("/app/output/alerts.txt") as f:
            content = f.read().strip()
        lines = content.split("\n")
        parts = lines[1].split("|")
        assert parts[0] == "BURST"
        assert parts[1] == "2024-01-16T08:00:00", (
            f"Second burst start should be 2024-01-16T08:00:00, got {parts[1]}"
        )
        assert parts[2] == "2024-01-16T08:00:30", (
            f"Second burst end should be 2024-01-16T08:00:30, got {parts[2]}"
        )
        assert parts[3] == "3"
        assert parts[4] == "server4.log", (
            f"Second burst should only involve server4.log, got {parts[4]}"
        )

    def test_dynamic_summary_format(self):
        expected_lines = [
            "PROCESSING SUMMARY",
            "=" * 40,
            "Total files processed: 4",
            "=" * 40,
            "INFO: 8",
            "WARN: 5",
            "ERROR: 7",
            "=" * 40,
            "Total lines: 20",
        ]
        with open("/app/output/summary.txt") as f:
            lines = [l.rstrip("\n") for l in f.readlines()]
        while lines and lines[-1] == "":
            lines.pop()
        assert lines == expected_lines, (
            f"Summary format mismatch.\nExpected:\n"
            + "\n".join(expected_lines)
            + f"\n\nGot:\n"
            + "\n".join(lines)
        )
