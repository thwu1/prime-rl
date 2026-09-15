
import os
import json
import hashlib


# Verification digests: SHA-256 of expected values.
# These cannot be reversed to obtain the expected answers.
_FW_DIGEST = "23388aa6062ec3fec0899b9ca516fe85b01ab8afd17236da7526ec5999177bc8"
_SPEC_DIGEST = "e04fcf89b53f0341e4b1466c76683a8261943f1bff1647832352bb6d03936e07"
_PAIRS_DIGEST = "6dd56158fcc7e51bf968c261e09b6a1e902a7fa7a3de87ea2b1fba8cc4d626d6"


def _load_analysis():
    with open("/app/analysis.json", "r") as f:
        return json.load(f)


class TestAnalysisFileStructure:
    def test_file_exists(self):
        assert os.path.isfile("/app/analysis.json"), (
            "/app/analysis.json does not exist"
        )

    def test_valid_json(self):
        data = _load_analysis()
        assert isinstance(data, dict), "analysis.json root must be a JSON object"

    def test_required_keys(self):
        data = _load_analysis()
        for key in ("firmware_output", "spec_output", "deviations"):
            assert key in data, f"Missing required key: {key}"


class TestFirmwareOutput:
    def test_firmware_output_is_hex(self):
        data = _load_analysis()
        fw = data["firmware_output"].strip().lower()
        try:
            bytes.fromhex(fw)
        except ValueError:
            raise AssertionError(f"firmware_output is not valid hex: {fw!r}")

    def test_firmware_output_length(self):
        data = _load_analysis()
        fw = data["firmware_output"].strip().lower()
        assert len(fw) == 32, (
            f"firmware_output should be 32 hex chars (16 bytes), got {len(fw)}"
        )

    def test_firmware_output_correct(self):
        data = _load_analysis()
        fw = data["firmware_output"].strip().lower()
        digest = hashlib.sha256(fw.encode()).hexdigest()
        assert digest == _FW_DIGEST, "firmware_output does not match expected value"


class TestSpecOutput:
    def test_spec_output_is_hex(self):
        data = _load_analysis()
        sp = data["spec_output"].strip().lower()
        try:
            bytes.fromhex(sp)
        except ValueError:
            raise AssertionError(f"spec_output is not valid hex: {sp!r}")

    def test_spec_output_length(self):
        data = _load_analysis()
        sp = data["spec_output"].strip().lower()
        assert len(sp) == 32, (
            f"spec_output should be 32 hex chars (16 bytes), got {len(sp)}"
        )

    def test_spec_output_correct(self):
        data = _load_analysis()
        sp = data["spec_output"].strip().lower()
        digest = hashlib.sha256(sp.encode()).hexdigest()
        assert digest == _SPEC_DIGEST, "spec_output does not match expected value"


class TestDeviations:
    def test_deviations_is_list(self):
        data = _load_analysis()
        assert isinstance(data["deviations"], list), "deviations must be a list"

    def test_deviation_count(self):
        data = _load_analysis()
        assert len(data["deviations"]) == 3, (
            f"Expected exactly 3 deviations, got {len(data['deviations'])}"
        )

    def test_deviation_structure(self):
        data = _load_analysis()
        for i, dev in enumerate(data["deviations"]):
            assert "parameter" in dev, f"deviation[{i}] missing 'parameter'"
            assert "spec_value" in dev, f"deviation[{i}] missing 'spec_value'"
            assert "firmware_value" in dev, f"deviation[{i}] missing 'firmware_value'"

    def test_deviation_values_differ(self):
        data = _load_analysis()
        for i, dev in enumerate(data["deviations"]):
            assert int(dev["spec_value"]) != int(dev["firmware_value"]), (
                f"deviation[{i}]: spec_value and firmware_value must differ"
            )

    def test_deviation_pairs_correct(self):
        data = _load_analysis()
        pairs = sorted(
            [int(d["spec_value"]), int(d["firmware_value"])]
            for d in data["deviations"]
        )
        pairs_hash = hashlib.sha256(json.dumps(pairs).encode()).hexdigest()
        assert pairs_hash == _PAIRS_DIGEST, (
            "Deviation (spec_value, firmware_value) pairs do not match expected values"
        )


class TestOutputsDiffer:
    def test_firmware_and_spec_differ(self):
        data = _load_analysis()
        fw = data["firmware_output"].strip().lower()
        sp = data["spec_output"].strip().lower()
        assert fw != sp, (
            "firmware_output and spec_output should differ (there are deviations)"
        )
