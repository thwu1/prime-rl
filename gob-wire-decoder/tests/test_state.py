
import subprocess
import json
import os
import glob
import pytest


GOBDECODE = "/app/gobdecode/gobdecode"
TESTDATA = "/app/testdata"


def get_test_fixtures():
    """Return list of (name, gob_path, json_path) tuples."""
    gob_files = sorted(glob.glob(os.path.join(TESTDATA, "*.gob")))
    fixtures = []
    for gob_path in gob_files:
        name = os.path.splitext(os.path.basename(gob_path))[0]
        json_path = os.path.join(TESTDATA, name + ".json")
        if os.path.exists(json_path):
            fixtures.append((name, gob_path, json_path))
    return fixtures


class TestBuild:
    def test_decoder_builds(self):
        """The gobdecode binary must exist and be executable."""
        assert os.path.isfile(GOBDECODE), f"Binary not found at {GOBDECODE}"
        assert os.access(GOBDECODE, os.X_OK), f"Binary not executable at {GOBDECODE}"

    def test_build_no_encoding_gob(self):
        """The decoder must not import encoding/gob."""
        result = subprocess.run(
            ["grep", "-r", '"encoding/gob"', "/app/gobdecode/"],
            capture_output=True, text=True
        )
        assert result.returncode != 0, "Decoder must not import encoding/gob"


class TestFixtures:
    @pytest.fixture(autouse=True)
    def check_binary(self):
        if not os.path.isfile(GOBDECODE) or not os.access(GOBDECODE, os.X_OK):
            pytest.skip("gobdecode binary not built")

    @staticmethod
    def compact_json(data):
        """Normalize JSON by parsing and re-serializing compactly."""
        parsed = json.loads(data)
        return json.dumps(parsed, separators=(",", ":"), sort_keys=True)

    @pytest.mark.parametrize(
        "name,gob_path,json_path",
        get_test_fixtures(),
        ids=[f[0] for f in get_test_fixtures()],
    )
    def test_fixture(self, name, gob_path, json_path):
        """Run gobdecode on each .gob file and compare to expected .json."""
        with open(gob_path, "rb") as f:
            gob_data = f.read()

        result = subprocess.run(
            [GOBDECODE],
            input=gob_data,
            capture_output=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"gobdecode failed for {name}: stderr={result.stderr.decode('utf-8', errors='replace')}"
        )

        actual_json = result.stdout.decode("utf-8").strip()
        with open(json_path, "r") as f:
            expected_json = f.read().strip()

        actual_compact = self.compact_json(actual_json)
        expected_compact = self.compact_json(expected_json)

        assert actual_compact == expected_compact, (
            f"JSON mismatch for {name}:\n"
            f"  expected: {expected_compact[:500]}\n"
            f"  actual:   {actual_compact[:500]}"
        )


class TestEdgeCases:
    @pytest.fixture(autouse=True)
    def check_binary(self):
        if not os.path.isfile(GOBDECODE) or not os.access(GOBDECODE, os.X_OK):
            pytest.skip("gobdecode binary not built")

    def test_empty_input(self):
        """Empty input must produce an empty JSON array []."""
        result = subprocess.run(
            [GOBDECODE],
            input=b"",
            capture_output=True,
            timeout=10,
        )
        assert result.returncode == 0, (
            f"Non-zero exit on empty input: {result.stderr.decode('utf-8', errors='replace')}"
        )
        out = result.stdout.decode("utf-8").strip()
        parsed = json.loads(out)
        assert parsed == [], f"Expected empty array [], got {out}"

    def test_point_22_33_known_bytes(self):
        """The canonical Point{22,33} example from the gob documentation."""
        raw = bytes([
            0x1f, 0xff, 0x81, 0x03, 0x01, 0x01, 0x05, 0x50,
            0x6f, 0x69, 0x6e, 0x74, 0x01, 0xff, 0x82, 0x00,
            0x01, 0x02, 0x01, 0x01, 0x58, 0x01, 0x04, 0x00,
            0x01, 0x01, 0x59, 0x01, 0x04, 0x00, 0x00, 0x00,
            0x07, 0xff, 0x82, 0x01, 0x2c, 0x01, 0x42, 0x00,
        ])
        result = subprocess.run(
            [GOBDECODE],
            input=raw,
            capture_output=True,
            timeout=10,
        )
        assert result.returncode == 0, (
            f"Failed on canonical Point bytes: {result.stderr.decode('utf-8', errors='replace')}"
        )
        out = json.loads(result.stdout.decode("utf-8"))
        assert len(out) == 1
        point = out[0]
        assert point["X"] == 22, f"Expected X=22, got {point.get('X')}"
        assert point["Y"] == 33, f"Expected Y=33, got {point.get('Y')}"

    def test_singleton_int_3(self):
        """The canonical singleton int(3) = bytes 03 04 00 06."""
        raw = bytes([0x03, 0x04, 0x00, 0x06])
        result = subprocess.run(
            [GOBDECODE],
            input=raw,
            capture_output=True,
            timeout=10,
        )
        assert result.returncode == 0, (
            f"Failed on singleton int(3): {result.stderr.decode('utf-8', errors='replace')}"
        )
        out = json.loads(result.stdout.decode("utf-8"))
        assert len(out) == 1
        assert out[0] == 3, f"Expected 3, got {out[0]}"

    def test_minimum_fixture_count(self):
        """Ensure at least 27 test fixtures exist."""
        fixtures = get_test_fixtures()
        assert len(fixtures) >= 27, (
            f"Expected at least 27 test fixtures, found {len(fixtures)}"
        )
