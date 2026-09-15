
"""
Verification tests for the ACVP compliance audit task.

Validates:
  1. Agent's computed correct results match expected results
  2. Audit report structure, counts, and discrepancy locations are accurate

Ground-truth discrepancies are computed at test time by comparing
vendor responses against expected correct results, ensuring the test
is self-verifying regardless of the specific vendor bug values.
"""

import json
import os
import pytest


EXPECTED_DIR = "/tests/expected"
RESULTS_DIR = "/app/results"
VENDOR_DIR = "/app/vendor_responses"
REPORT_PATH = "/app/audit_report.json"

VECTOR_FILES = ["aes_cbc_mct.json", "aes_gcm.json", "hmac_sha256.json", "sha256.json"]


def load_json(path):
    with open(path) as f:
        return json.load(f)


def normalize_value(value):
    """Normalize any value: uppercase hex strings, recurse into lists/dicts."""
    if isinstance(value, str):
        return value.upper()
    if isinstance(value, list):
        return [normalize_value(item) for item in value]
    if isinstance(value, dict):
        return {k: normalize_value(v) for k, v in value.items()}
    return value


def normalize_tc(tc):
    """Normalize a test case dict: uppercase all string values recursively."""
    return {k: normalize_value(v) for k, v in tc.items()}


def build_tc_map(test_groups):
    """Build a map of (tgId, tcId) -> test case dict."""
    tc_map = {}
    for tg in test_groups:
        tg_id = tg["tgId"]
        for tc in tg["tests"]:
            tc_id = tc["tcId"]
            tc_map[(tg_id, tc_id)] = tc
    return tc_map


def compute_ground_truth_discrepancies():
    """Compare vendor responses against expected to get ground-truth discrepancies."""
    total_tc = 0
    total_disc = 0
    per_file = {}

    for fn in VECTOR_FILES:
        vendor = load_json(os.path.join(VENDOR_DIR, fn))
        correct = load_json(os.path.join(EXPECTED_DIR, fn))

        vendor_map = build_tc_map(vendor["testGroups"])
        correct_map = build_tc_map(correct["testGroups"])

        disc_keys = []
        for key in sorted(correct_map.keys()):
            total_tc += 1
            ctc = normalize_tc(correct_map[key])
            vtc = normalize_tc(vendor_map.get(key, {}))

            if ctc != vtc:
                total_disc += 1
                disc_keys.append(key)

        per_file[fn] = disc_keys

    return total_tc, total_disc, per_file


class TestResultFilesExist:
    """Verify that all expected result files were produced."""

    @pytest.mark.parametrize("filename", VECTOR_FILES)
    def test_result_file_exists(self, filename):
        path = os.path.join(RESULTS_DIR, filename)
        assert os.path.isfile(path), (
            f"Expected result file {path} not found. "
            f"Contents of {RESULTS_DIR}: "
            f"{os.listdir(RESULTS_DIR) if os.path.isdir(RESULTS_DIR) else 'directory does not exist'}"
        )


class TestCorrectResults:
    """Verify agent's independently computed results match expected correct results."""

    @pytest.mark.parametrize("filename", VECTOR_FILES)
    def test_vsid_and_algorithm(self, filename):
        expected = load_json(os.path.join(EXPECTED_DIR, filename))
        result = load_json(os.path.join(RESULTS_DIR, filename))
        assert result["vsId"] == expected["vsId"], \
            f"{filename}: vsId mismatch"
        assert result["algorithm"] == expected["algorithm"], \
            f"{filename}: algorithm mismatch"

    @pytest.mark.parametrize("filename", VECTOR_FILES)
    def test_group_count(self, filename):
        expected = load_json(os.path.join(EXPECTED_DIR, filename))
        result = load_json(os.path.join(RESULTS_DIR, filename))
        assert len(result["testGroups"]) == len(expected["testGroups"]), \
            f"{filename}: testGroup count mismatch"

    @pytest.mark.parametrize("filename", VECTOR_FILES)
    def test_all_test_cases_match(self, filename):
        expected = load_json(os.path.join(EXPECTED_DIR, filename))
        result = load_json(os.path.join(RESULTS_DIR, filename))

        expected_map = build_tc_map(expected["testGroups"])
        result_map = build_tc_map(result["testGroups"])

        for key in expected_map:
            assert key in result_map, \
                f"{filename}: missing test case tgId={key[0]}, tcId={key[1]}"

            exp_tc = normalize_tc(expected_map[key])
            res_tc = normalize_tc(result_map[key])

            for field in exp_tc:
                if field == "tcId":
                    continue
                assert field in res_tc, \
                    f"{filename} tcId={key[1]}: missing field '{field}'"
                if field == "resultsArray":
                    exp_arr = exp_tc[field]
                    res_arr = res_tc[field]
                    assert len(res_arr) == len(exp_arr), \
                        f"{filename} tcId={key[1]}: resultsArray length " \
                        f"{len(res_arr)} != expected {len(exp_arr)}"
                    for idx, (exp_entry, res_entry) in enumerate(
                        zip(exp_arr, res_arr)
                    ):
                        assert res_entry == exp_entry, \
                            f"{filename} tcId={key[1]}: resultsArray[{idx}] " \
                            f"mismatch — got {res_entry!r}, " \
                            f"expected {exp_entry!r}"
                else:
                    assert res_tc[field] == exp_tc[field], \
                        f"{filename} tcId={key[1]}: {field} mismatch — " \
                        f"got {res_tc[field]!r}, expected {exp_tc[field]!r}"


class TestAuditReport:
    """Verify the audit report correctly identifies all discrepancies."""

    @pytest.fixture(autouse=True)
    def load_data(self):
        self.report = load_json(REPORT_PATH)
        self.gt_total_tc, self.gt_total_disc, self.gt_per_file = \
            compute_ground_truth_discrepancies()

    def test_report_exists(self):
        assert os.path.isfile(REPORT_PATH), "Audit report not found"

    def test_report_has_required_fields(self):
        assert isinstance(self.report.get("total_test_cases"), int), \
            "total_test_cases must be an integer"
        assert isinstance(self.report.get("total_discrepancies"), int), \
            "total_discrepancies must be an integer"
        assert isinstance(self.report.get("files"), dict), \
            "files must be a dict"

    def test_total_test_cases(self):
        assert self.report["total_test_cases"] == self.gt_total_tc, \
            f"total_test_cases: got {self.report['total_test_cases']}, " \
            f"expected {self.gt_total_tc}"

    def test_total_discrepancies(self):
        assert self.report["total_discrepancies"] == self.gt_total_disc, \
            f"total_discrepancies: got {self.report['total_discrepancies']}, " \
            f"expected {self.gt_total_disc}"

    def test_files_with_discrepancies_present(self):
        for fn in VECTOR_FILES:
            if self.gt_per_file[fn]:
                assert fn in self.report["files"], \
                    f"{fn} has {len(self.gt_per_file[fn])} discrepancies " \
                    f"but is missing from report"

    @pytest.mark.parametrize("filename", VECTOR_FILES)
    def test_discrepancy_count_per_file(self, filename):
        expected_count = len(self.gt_per_file[filename])
        reported = self.report["files"].get(filename, {}).get("discrepancies", [])
        assert len(reported) == expected_count, \
            f"{filename}: expected {expected_count} discrepancies, " \
            f"got {len(reported)}"

    @pytest.mark.parametrize("filename", VECTOR_FILES)
    def test_discrepancy_locations(self, filename):
        """Each reported discrepancy must match the ground-truth (tgId, tcId)."""
        expected_keys = set(self.gt_per_file[filename])
        reported = self.report["files"].get(filename, {}).get("discrepancies", [])
        reported_keys = set()
        for d in reported:
            assert "tgId" in d and "tcId" in d, \
                f"{filename}: discrepancy missing tgId or tcId"
            reported_keys.add((d["tgId"], d["tcId"]))

        assert reported_keys == expected_keys, \
            f"{filename}: discrepancy locations mismatch.\n" \
            f"  Expected: {sorted(expected_keys)}\n" \
            f"  Got:      {sorted(reported_keys)}"

    @pytest.mark.parametrize("filename", VECTOR_FILES)
    def test_discrepancies_have_fields(self, filename):
        """Each discrepancy must include a non-empty fields dict."""
        reported = self.report["files"].get(filename, {}).get("discrepancies", [])
        for d in reported:
            assert "fields" in d, \
                f"{filename} tcId={d.get('tcId')}: missing 'fields'"
            assert isinstance(d["fields"], dict) and len(d["fields"]) > 0, \
                f"{filename} tcId={d.get('tcId')}: 'fields' must be non-empty dict"
