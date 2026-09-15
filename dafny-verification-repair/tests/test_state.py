
import subprocess
import os
import re
import pytest

PROGRAMS = ["sel_sort.dfy", "insertion_sort.dfy", "seq_max_sum.dfy"]
APP_DIR = "/app"
ORIGINALS_DIR = "/app/.originals"


def extract_specs(content):
    """Extract requires/ensures lines, ignoring comments."""
    specs = []
    in_block_comment = False
    for line in content.split("\n"):
        stripped = line.strip()
        if "/*" in stripped and "*/" not in stripped:
            in_block_comment = True
            continue
        if "*/" in stripped:
            in_block_comment = False
            continue
        if in_block_comment:
            continue
        if stripped.startswith("//"):
            continue
        if "requires" in stripped or "ensures" in stripped:
            normalized = re.sub(r"\s+", " ", stripped).strip()
            specs.append(normalized)
    return specs


class TestDafnyPrograms:

    @pytest.mark.parametrize("program", PROGRAMS)
    def test_file_exists(self, program):
        filepath = os.path.join(APP_DIR, program)
        assert os.path.exists(filepath), f"{filepath} does not exist"

    @pytest.mark.parametrize("program", PROGRAMS)
    def test_no_assume_false(self, program):
        filepath = os.path.join(APP_DIR, program)
        with open(filepath, "r") as f:
            content = f.read()
        assert not re.search(
            r"\bassume\s+false\b", content
        ), f"Cheating: 'assume false' in {program}"

    @pytest.mark.parametrize("program", PROGRAMS)
    def test_no_verify_false(self, program):
        filepath = os.path.join(APP_DIR, program)
        with open(filepath, "r") as f:
            content = f.read()
        assert (
            "{:verify false}" not in content
        ), f"Cheating: '{{:verify false}}' in {program}"

    @pytest.mark.parametrize("program", PROGRAMS)
    def test_specs_preserved(self, program):
        original_path = os.path.join(ORIGINALS_DIR, program)
        modified_path = os.path.join(APP_DIR, program)

        with open(original_path, "r") as f:
            original_specs = extract_specs(f.read())
        with open(modified_path, "r") as f:
            modified_specs = extract_specs(f.read())

        for spec in original_specs:
            assert spec in modified_specs, (
                f"Original spec missing from {program}: {spec}"
            )

    @pytest.mark.parametrize("program", PROGRAMS)
    def test_dafny_verifies(self, program):
        filepath = os.path.join(APP_DIR, program)
        result = subprocess.run(
            ["dafny", "verify", filepath],
            capture_output=True,
            text=True,
            timeout=180,
        )
        combined = result.stdout + "\n" + result.stderr
        assert "0 errors" in combined, (
            f"Dafny verification failed for {program}:\n{combined}"
        )
        # Ensure something was actually verified (not an empty/skipped file)
        assert "verified" in combined.lower(), (
            f"No verification output for {program}:\n{combined}"
        )
