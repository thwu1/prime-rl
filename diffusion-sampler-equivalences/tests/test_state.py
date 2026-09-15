
import pytest
import json
import os
import math

# Hidden ground truth contacts for all three families
# Encoded as sorted (i, j) pairs with i < j and |i-j| >= 5
_GT = {
    "family_1": [
        (0,5),(0,6),(2,41),(2,49),(3,15),(4,11),(5,31),(5,35),(5,36),
        (7,12),(7,59),(9,47),(10,17),(11,57),(12,17),(12,21),(12,22),
        (13,22),(13,39),(14,37),(14,56),(15,29),(17,54),(18,33),(18,45),
        (21,41),(22,36),(22,46),(26,54),(28,33),(31,43),(31,50),(32,56),
        (33,47),(37,59),(38,46),(39,59),(43,52),(47,59),(52,58),
    ],
    "family_2": [
        (0,9),(0,22),(1,19),(1,23),(2,15),(3,14),(5,31),(6,48),(6,56),
        (7,34),(8,55),(9,32),(9,39),(10,22),(10,49),(11,30),(11,52),
        (12,18),(12,25),(13,37),(15,24),(15,40),(18,42),(18,47),(18,56),
        (19,46),(20,48),(21,32),(21,52),(22,51),(22,58),(24,39),(28,42),
        (28,58),(30,48),(34,41),(34,47),(36,49),(36,58),(42,53),
    ],
    "family_3": [
        (3,55),(3,61),(3,64),(4,32),(5,24),(5,43),(6,50),(6,65),(7,39),
        (7,70),(8,30),(11,41),(12,43),(12,46),(12,53),(12,54),(13,47),
        (14,50),(15,20),(16,44),(16,54),(18,64),(20,62),(20,64),(21,68),
        (22,66),(22,79),(23,31),(25,43),(26,78),(27,33),(29,49),(30,72),
        (32,38),(32,43),(32,50),(33,42),(35,75),(37,50),(37,55),(37,75),
        (40,45),(44,79),(45,70),(47,77),(48,67),(53,67),(54,64),(58,63),
        (64,77),
    ],
}

_EXPECTED_LENGTHS = {"family_1": 60, "family_2": 60, "family_3": 80}
_EXPECTED_NSEQ = {"family_1": 2500, "family_2": 3714, "family_3": 500}


def _load_results():
    with open("/app/results.json") as f:
        return json.load(f)


def _precision_at_L(predictions, true_contacts, L):
    true_set = set(true_contacts)
    top_L = predictions[:L]
    tp = sum(1 for p in top_L if (p[0], p[1]) in true_set or (p[1], p[0]) in true_set)
    return tp / L if L > 0 else 0.0


# ── Structure tests ────────────────────────────────────────────────

class TestResultsExist:
    def test_file_exists(self):
        assert os.path.exists("/app/results.json"), "results.json not found"

    def test_valid_json(self):
        r = _load_results()
        assert isinstance(r, dict)


class TestResultsStructure:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.results = _load_results()

    def test_has_all_families(self):
        for fam in ["family_1", "family_2", "family_3"]:
            assert fam in self.results, f"Missing key: {fam}"

    def test_family_keys(self):
        required = {"top_contacts", "precision_at_L", "n_sequences", "alignment_length"}
        for fam in ["family_1", "family_2", "family_3"]:
            keys = set(self.results[fam].keys())
            missing = required - keys
            assert not missing, f"{fam} missing keys: {missing}"

    def test_top_contacts_is_list(self):
        for fam in ["family_1", "family_2", "family_3"]:
            tc = self.results[fam]["top_contacts"]
            assert isinstance(tc, list), f"{fam}: top_contacts must be a list"

    def test_top_contacts_length(self):
        for fam in ["family_1", "family_2", "family_3"]:
            tc = self.results[fam]["top_contacts"]
            L = _EXPECTED_LENGTHS[fam]
            assert len(tc) >= L, (
                f"{fam}: expected at least {L} predictions, got {len(tc)}"
            )

    def test_contact_triple_format(self):
        for fam in ["family_1", "family_2", "family_3"]:
            for idx, entry in enumerate(self.results[fam]["top_contacts"][:5]):
                assert len(entry) == 3, (
                    f"{fam} contact {idx}: expected [i, j, score], got {entry}"
                )
                assert isinstance(entry[0], int), f"{fam} contact {idx}: i must be int"
                assert isinstance(entry[1], int), f"{fam} contact {idx}: j must be int"
                assert isinstance(entry[2], (int, float)), f"{fam} contact {idx}: score must be numeric"


# ── Contact validity tests ─────────────────────────────────────────

class TestContactValidity:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.results = _load_results()

    def test_separation_constraint(self):
        for fam in ["family_1", "family_2", "family_3"]:
            L = _EXPECTED_LENGTHS[fam]
            for idx, (i, j, _) in enumerate(self.results[fam]["top_contacts"][:L]):
                assert abs(i - j) >= 5, (
                    f"{fam} contact {idx}: |{i}-{j}| = {abs(i-j)} < 5"
                )

    def test_positions_in_range(self):
        for fam in ["family_1", "family_2", "family_3"]:
            L = _EXPECTED_LENGTHS[fam]
            for idx, (i, j, _) in enumerate(self.results[fam]["top_contacts"][:L]):
                assert 0 <= i < L, f"{fam} contact {idx}: i={i} out of range [0, {L})"
                assert 0 <= j < L, f"{fam} contact {idx}: j={j} out of range [0, {L})"

    def test_no_self_contacts(self):
        for fam in ["family_1", "family_2", "family_3"]:
            L = _EXPECTED_LENGTHS[fam]
            for idx, (i, j, _) in enumerate(self.results[fam]["top_contacts"][:L]):
                assert i != j, f"{fam} contact {idx}: self-contact ({i}, {i})"

    def test_scores_sorted_descending(self):
        for fam in ["family_1", "family_2", "family_3"]:
            scores = [s for _, _, s in self.results[fam]["top_contacts"]]
            for k in range(len(scores) - 1):
                assert scores[k] >= scores[k + 1] - 1e-12, (
                    f"{fam}: scores not sorted at index {k}: "
                    f"{scores[k]:.6f} < {scores[k+1]:.6f}"
                )


# ── Metadata tests ─────────────────────────────────────────────────

class TestMetadata:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.results = _load_results()

    def test_alignment_lengths(self):
        for fam, expected_L in _EXPECTED_LENGTHS.items():
            reported = self.results[fam]["alignment_length"]
            assert reported == expected_L, (
                f"{fam}: alignment_length should be {expected_L}, got {reported}"
            )

    def test_sequence_counts(self):
        for fam, expected_N in _EXPECTED_NSEQ.items():
            reported = self.results[fam]["n_sequences"]
            assert reported == expected_N, (
                f"{fam}: n_sequences should be {expected_N}, got {reported}"
            )


# ── Precision tests ────────────────────────────────────────────────

class TestFamily1Precision:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.results = _load_results()
        self.fam = "family_1"
        self.L = _EXPECTED_LENGTHS[self.fam]
        self.preds = [
            (int(c[0]), int(c[1])) for c in self.results[self.fam]["top_contacts"][:self.L]
        ]
        self.prec = _precision_at_L(
            self.results[self.fam]["top_contacts"], _GT[self.fam], self.L
        )

    def test_precision_at_L(self):
        assert self.prec >= 0.50, (
            f"family_1 precision@L = {self.prec:.3f} < 0.50"
        )

    def test_self_assessment_accuracy(self):
        reported = self.results[self.fam]["precision_at_L"]
        assert reported is not None, "family_1 must report precision_at_L"
        assert abs(reported - self.prec) < 0.15, (
            f"family_1 self-assessment {reported:.3f} vs actual {self.prec:.3f} "
            f"differ by {abs(reported - self.prec):.3f} (> 0.15)"
        )


class TestFamily2Precision:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.results = _load_results()
        self.fam = "family_2"
        self.L = _EXPECTED_LENGTHS[self.fam]
        self.prec = _precision_at_L(
            self.results[self.fam]["top_contacts"], _GT[self.fam], self.L
        )

    def test_precision_at_L(self):
        assert self.prec >= 0.40, (
            f"family_2 precision@L = {self.prec:.3f} < 0.40"
        )


class TestFamily3Precision:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.results = _load_results()
        self.fam = "family_3"
        self.L = _EXPECTED_LENGTHS[self.fam]
        self.prec = _precision_at_L(
            self.results[self.fam]["top_contacts"], _GT[self.fam], self.L
        )

    def test_precision_at_L(self):
        assert self.prec >= 0.30, (
            f"family_3 precision@L = {self.prec:.3f} < 0.30"
        )


class TestOverallQuality:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.results = _load_results()
        self.precisions = {}
        for fam in ["family_1", "family_2", "family_3"]:
            L = _EXPECTED_LENGTHS[fam]
            self.precisions[fam] = _precision_at_L(
                self.results[fam]["top_contacts"], _GT[fam], L
            )

    def test_at_least_two_strong(self):
        strong = sum(1 for p in self.precisions.values() if p >= 0.45)
        assert strong >= 2, (
            f"Need precision@L >= 0.45 on at least 2 families, got {strong}. "
            f"Precisions: {', '.join(f'{k}={v:.3f}' for k,v in self.precisions.items())}"
        )


class TestFamily1PrecisionNotNull:
    def test_family_1_has_precision(self):
        results = _load_results()
        val = results["family_1"]["precision_at_L"]
        assert val is not None, "family_1 precision_at_L must not be null"
        assert isinstance(val, (int, float)), "precision_at_L must be numeric"
        assert 0.0 <= val <= 1.0, f"precision_at_L={val} out of [0,1]"


# ── Contact map heatmap PNG tests ──────────────────────────────────

class TestContactMapPNG:
    _PNG_MAGIC = b'\x89PNG\r\n\x1a\n'

    @pytest.mark.parametrize("fam", ["family_1", "family_2", "family_3"])
    def test_png_exists(self, fam):
        path = f"/app/contact_map_{fam}.png"
        assert os.path.exists(path), f"{path} not found"

    @pytest.mark.parametrize("fam", ["family_1", "family_2", "family_3"])
    def test_png_valid_header(self, fam):
        path = f"/app/contact_map_{fam}.png"
        with open(path, "rb") as f:
            header = f.read(8)
        assert header == self._PNG_MAGIC, (
            f"{fam} PNG has invalid header bytes"
        )

    @pytest.mark.parametrize("fam", ["family_1", "family_2", "family_3"])
    def test_png_minimum_size(self, fam):
        path = f"/app/contact_map_{fam}.png"
        size = os.path.getsize(path)
        assert size >= 1000, (
            f"{fam} PNG is only {size} bytes, expected at least 1000"
        )


# ── Pipeline report TSV tests ─────────────────────────────────────

class TestPipelineReport:
    _EXPECTED_HEADER = "family\tn_sequences\talignment_length\tneff\ttop_score\tprecision_at_L"

    def _read_lines(self):
        with open("/app/pipeline_report.tsv") as f:
            return [line.rstrip("\n") for line in f if line.strip()]

    def test_report_exists(self):
        assert os.path.exists("/app/pipeline_report.tsv"), (
            "pipeline_report.tsv not found"
        )

    def test_report_header(self):
        lines = self._read_lines()
        assert len(lines) >= 1, "pipeline_report.tsv is empty"
        assert lines[0] == self._EXPECTED_HEADER, (
            f"Header mismatch: got {lines[0]!r}"
        )

    def test_report_row_count(self):
        lines = self._read_lines()
        assert len(lines) == 4, (
            f"Expected 4 lines (header + 3 data rows), got {len(lines)}"
        )

    def test_report_family_names(self):
        lines = self._read_lines()
        families = [line.split("\t")[0] for line in lines[1:]]
        assert families == ["family_1", "family_2", "family_3"], (
            f"Family names should be family_1, family_2, family_3; got {families}"
        )

    def test_report_numeric_fields(self):
        lines = self._read_lines()
        for line in lines[1:]:
            cols = line.split("\t")
            assert len(cols) == 6, (
                f"Expected 6 columns, got {len(cols)} in: {line}"
            )
            fam = cols[0]
            n_seq = int(cols[1])
            assert n_seq > 0, f"{fam}: n_sequences must be > 0"
            aln_len = int(cols[2])
            assert aln_len > 0, f"{fam}: alignment_length must be > 0"
            neff = float(cols[3])
            assert neff > 0, f"{fam}: neff must be > 0"
            top_score = float(cols[4])
            assert top_score > 0, f"{fam}: top_score must be > 0"

    def test_report_precision_column(self):
        lines = self._read_lines()
        # family_1 should have a numeric precision in [0, 1]
        cols_1 = lines[1].split("\t")
        assert cols_1[0] == "family_1"
        prec_1 = float(cols_1[5])
        assert 0.0 <= prec_1 <= 1.0, (
            f"family_1 precision_at_L={prec_1} not in [0, 1]"
        )
        # family_2 and family_3 should have "NA"
        for idx in [2, 3]:
            cols = lines[idx].split("\t")
            assert cols[5] == "NA", (
                f"{cols[0]} precision_at_L should be 'NA', got {cols[5]!r}"
            )
