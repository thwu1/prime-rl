
"""
Tests for Unicode Extended Grapheme Cluster segmentation (UAX #29).

Verifies correctness against the official Unicode GraphemeBreakTest.txt
test vectors and targeted edge-case scenarios.
"""

import subprocess
import json
import os
import re

APP_DIR = "/app"
DATA_DIR = "/app/data"


def run_cmd(cmd: list[str], cwd: str = APP_DIR) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=120)


def ensure_built():
    """Make sure the project is compiled."""
    result = run_cmd(["npm", "install", "--ignore-scripts"], cwd=APP_DIR)
    assert result.returncode == 0, f"npm install failed: {result.stderr}"
    result = run_cmd(["npx", "tsc"], cwd=APP_DIR)
    assert result.returncode == 0, f"TypeScript compilation failed:\n{result.stdout}\n{result.stderr}"
    assert os.path.exists(os.path.join(APP_DIR, "dist", "cli.js")), "cli.js not found after build"


class TestGraphemeBreakOfficialVectors:
    """Run all 766 official Unicode GraphemeBreakTest.txt test vectors."""

    @classmethod
    def setup_class(cls):
        ensure_built()

    def test_all_official_vectors_pass(self):
        """Every test vector in GraphemeBreakTest.txt must produce correct boundaries."""
        result = run_cmd(
            ["node", "dist/cli.js", "test-json"],
            cwd=APP_DIR,
        )
        assert result.returncode == 0, (
            f"test-json command failed (exit {result.returncode}): {result.stdout}"
        )
        data = json.loads(result.stdout)
        total = data["total"]
        passed = data["passed"]
        failed = data["failed"]

        assert total >= 760, f"Expected at least 760 test vectors, got {total}"
        assert failed == 0, (
            f"{failed}/{total} test vectors failed. "
            f"First failures: {json.dumps(data.get('failures', [])[:5], indent=2)}"
        )


class TestGraphemeSegmentationEdgeCases:
    """Targeted tests for specific segmentation edge cases."""

    @classmethod
    def setup_class(cls):
        ensure_built()

    def _segment_hex(self, hex_cps: list[str]) -> list[list[str]]:
        """Run segmenter on hex code points and return clusters as lists of hex CPs."""
        result = run_cmd(
            ["node", "dist/cli.js", "graphemes-hex"] + hex_cps,
            cwd=APP_DIR,
        )
        assert result.returncode == 0, f"segmenter failed: {result.stderr}"

        clusters = []
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            # Parse output format: [XXXX YYYY]
            match = re.search(r'\[([0-9A-Fa-f ]+)\]', line)
            if match:
                cps = match.group(1).strip().split()
                clusters.append(cps)
        return clusters

    def test_crlf_not_broken(self):
        """GB3: CR x LF -- CR+LF should be a single cluster."""
        clusters = self._segment_hex(["000D", "000A"])
        assert len(clusters) == 1, f"CR+LF should be 1 cluster, got {len(clusters)}"

    def test_cr_lf_separate_from_next(self):
        """GB4: After CR+LF there should be a break."""
        clusters = self._segment_hex(["000D", "000A", "0061"])
        assert len(clusters) == 2, f"Expected 2 clusters, got {len(clusters)}"

    def test_hangul_lv_t(self):
        """GB7+GB8: Hangul LV + T should form a single cluster."""
        clusters = self._segment_hex(["AC00", "11A8"])
        assert len(clusters) == 1, f"Hangul LV+T should be 1 cluster, got {len(clusters)}"

    def test_combining_sequence(self):
        """GB9: Base + Extend should form single cluster."""
        clusters = self._segment_hex(["0061", "0308", "0301"])
        assert len(clusters) == 1, f"a + diaeresis + acute should be 1 cluster, got {len(clusters)}"

    def test_regional_indicator_pair(self):
        """Two RI characters form a single cluster (flag)."""
        clusters = self._segment_hex(["1F1FA", "1F1F8"])
        assert len(clusters) == 1, f"Two RI chars should be 1 cluster (flag), got {len(clusters)}"

    def test_regional_indicator_three(self):
        """Three RI characters: first two pair, third is separate."""
        clusters = self._segment_hex(["1F1FA", "1F1F8", "1F1EC"])
        assert len(clusters) == 2, (
            f"Three RI chars should be 2 clusters (pair + single), got {len(clusters)}: {clusters}"
        )

    def test_regional_indicator_four(self):
        """Four RI characters should form two clusters (two flags)."""
        clusters = self._segment_hex(["1F1FA", "1F1F8", "1F1EC", "1F1E7"])
        assert len(clusters) == 2, (
            f"Four RI chars should be 2 clusters (two flags), got {len(clusters)}: {clusters}"
        )

    def test_regional_indicator_six(self):
        """Six RI characters should form three clusters (three flags)."""
        clusters = self._segment_hex(["1F1FA", "1F1F8", "1F1EC", "1F1E7", "1F1EB", "1F1F7"])
        assert len(clusters) == 3, (
            f"Six RI chars should be 3 clusters (three flags), got {len(clusters)}: {clusters}"
        )

    def test_emoji_zwj_sequence(self):
        """Extended_Pictographic + ZWJ + Extended_Pictographic should cluster."""
        clusters = self._segment_hex(["1F469", "200D", "1F680"])
        assert len(clusters) == 1, (
            f"Emoji ZWJ sequence should be 1 cluster, got {len(clusters)}: {clusters}"
        )

    def test_emoji_zwj_sequence_with_modifier(self):
        """Extended_Pictographic + Extend + ZWJ + Extended_Pictographic."""
        clusters = self._segment_hex(["1F469", "1F3FB", "200D", "1F4BB"])
        assert len(clusters) == 1, (
            f"Emoji ZWJ with modifier should be 1 cluster, got {len(clusters)}: {clusters}"
        )

    def test_indic_conjunct_cluster(self):
        """Consonant + Virama + Consonant should form single cluster."""
        clusters = self._segment_hex(["0915", "094D", "0915"])
        assert len(clusters) == 1, (
            f"Devanagari KA+VIRAMA+KA should be 1 cluster, got {len(clusters)}: {clusters}"
        )

    def test_indic_conjunct_extended(self):
        """Extended Indic conjunct with multiple consonants."""
        clusters = self._segment_hex(["0915", "094D", "0937", "093F"])
        assert len(clusters) == 1, (
            f"Devanagari conjunct KA+VIRAMA+SSA+I should be 1 cluster, got {len(clusters)}: {clusters}"
        )

    def test_supplementary_plane_single(self):
        """Single supplementary plane character should not be split into surrogates."""
        clusters = self._segment_hex(["10348"])
        assert len(clusters) == 1, (
            f"Single supplementary char should be 1 cluster, got {len(clusters)}"
        )
        assert clusters[0] == ["10348"], f"Expected ['10348'], got {clusters[0]}"

    def test_supplementary_plane_emoji(self):
        """Supplementary plane emoji should be a single cluster."""
        clusters = self._segment_hex(["1F600"])
        assert len(clusters) == 1, (
            f"Single emoji should be 1 cluster, got {len(clusters)}"
        )
        assert clusters[0] == ["1F600"], f"Expected ['1F600'], got {clusters[0]}"

    def test_supplementary_pair_independence(self):
        """Two independent supplementary characters should be separate clusters."""
        clusters = self._segment_hex(["1F600", "1F601"])
        assert len(clusters) == 2, (
            f"Two independent emoji should be 2 clusters, got {len(clusters)}"
        )

    def test_prepend_character(self):
        """Prepend x Any."""
        clusters = self._segment_hex(["0600", "0628"])
        assert len(clusters) == 1, (
            f"Prepend + letter should be 1 cluster, got {len(clusters)}"
        )

    def test_spacing_mark(self):
        """x SpacingMark."""
        clusters = self._segment_hex(["0915", "0903"])
        assert len(clusters) == 1, (
            f"Letter + SpacingMark should be 1 cluster, got {len(clusters)}"
        )

    def test_zwj_between_digits(self):
        """ZWJ between digit characters should not keep them in one cluster.
        Digits have Emoji property but are NOT Extended_Pictographic."""
        clusters = self._segment_hex(["0030", "200D", "0031"])
        assert len(clusters) == 2, (
            f"Digit+ZWJ+Digit should be 2 clusters, got {len(clusters)}: {clusters}"
        )
