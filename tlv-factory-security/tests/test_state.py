"""
Tests for TLV Factory Data Manager.

"""
import pytest
import subprocess
import json
import struct
import os
import tempfile
import binascii
import base64

SCHEMA = "/app/schemas/factory_board_v1.yaml"
TLV_MANAGER = "python3 /app/tlv_manager.py"
TEST_PRIVATE_KEY = "/app/test_keys/private.pem"
TEST_PUBLIC_KEY = "/app/test_keys/public.pem"

SAMPLE_DATA = {
    "serial_number": "TB-2026-00042",
    "mac_address": "DE:AD:BE:EF:CA:FE",
    "soc_id": "0x1A2B3C4D5E6F7080",
    "hw_revision": 3,
    "production_date": "2026-01-15",
    "calibration_offset": 4096,
    "calibration_blob": base64.b64encode(bytes([1, 2, 3, 4, 5, 6])).decode()
}


@pytest.fixture
def work_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def sample_data_file(work_dir):
    path = os.path.join(work_dir, "data.json")
    with open(path, 'w') as f:
        json.dump(SAMPLE_DATA, f)
    return path


def run_cmd(cmd, check=True):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(
            f"Command failed (exit {result.returncode}): {cmd}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result


# ---- Encoding Tests ----

class TestEncoding:
    def test_encode_produces_file(self, work_dir, sample_data_file):
        output = os.path.join(work_dir, "output.tlv")
        run_cmd(f"{TLV_MANAGER} encode --schema {SCHEMA} --data {sample_data_file} --output {output}")
        assert os.path.exists(output)
        assert os.path.getsize(output) > 16

    def test_header_magic(self, work_dir, sample_data_file):
        output = os.path.join(work_dir, "output.tlv")
        run_cmd(f"{TLV_MANAGER} encode --schema {SCHEMA} --data {sample_data_file} --output {output}")
        with open(output, 'rb') as f:
            magic = struct.unpack('<I', f.read(4))[0]
        assert magic == 0xF0CAD001

    def test_header_version(self, work_dir, sample_data_file):
        output = os.path.join(work_dir, "output.tlv")
        run_cmd(f"{TLV_MANAGER} encode --schema {SCHEMA} --data {sample_data_file} --output {output}")
        with open(output, 'rb') as f:
            f.read(4)
            version = struct.unpack('<H', f.read(2))[0]
        assert version == 1

    def test_device_bound_flag_set(self, work_dir, sample_data_file):
        """soc_id present with device_bind: true -> flags bit 1 must be set."""
        output = os.path.join(work_dir, "output.tlv")
        run_cmd(f"{TLV_MANAGER} encode --schema {SCHEMA} --data {sample_data_file} --output {output}")
        with open(output, 'rb') as f:
            f.read(4)
            f.read(2)
            flags = struct.unpack('<H', f.read(2))[0]
        assert flags & 0x0002

    def test_unsigned_flag_clear(self, work_dir, sample_data_file):
        """Encoding without --sign-key -> flags bit 0 must be clear."""
        output = os.path.join(work_dir, "output.tlv")
        run_cmd(f"{TLV_MANAGER} encode --schema {SCHEMA} --data {sample_data_file} --output {output}")
        with open(output, 'rb') as f:
            f.read(4)
            f.read(2)
            flags = struct.unpack('<H', f.read(2))[0]
        assert not (flags & 0x0001)

    def test_crc32_valid(self, work_dir, sample_data_file):
        output = os.path.join(work_dir, "output.tlv")
        run_cmd(f"{TLV_MANAGER} encode --schema {SCHEMA} --data {sample_data_file} --output {output}")
        with open(output, 'rb') as f:
            data = f.read()
        _, _, _, payload_len, expected_crc = struct.unpack('<IHHII', data[:16])
        payload = data[16:16 + payload_len]
        actual_crc = binascii.crc32(payload) & 0xFFFFFFFF
        assert actual_crc == expected_crc

    def test_blob_size_unsigned(self, work_dir, sample_data_file):
        """Unsigned blob size = 16 + payload_len exactly."""
        output = os.path.join(work_dir, "output.tlv")
        run_cmd(f"{TLV_MANAGER} encode --schema {SCHEMA} --data {sample_data_file} --output {output}")
        with open(output, 'rb') as f:
            data = f.read()
        _, _, flags, payload_len, _ = struct.unpack('<IHHII', data[:16])
        assert not (flags & 0x0001)
        assert len(data) == 16 + payload_len


# ---- Round-trip Tests ----

class TestRoundTrip:
    def test_all_fields(self, work_dir, sample_data_file):
        output = os.path.join(work_dir, "output.tlv")
        run_cmd(f"{TLV_MANAGER} encode --schema {SCHEMA} --data {sample_data_file} --output {output}")
        result = run_cmd(f"{TLV_MANAGER} decode --schema {SCHEMA} --input {output}")
        decoded = json.loads(result.stdout)

        assert decoded["serial_number"] == "TB-2026-00042"
        assert decoded["mac_address"].upper() == "DE:AD:BE:EF:CA:FE"
        assert decoded["hw_revision"] == 3
        assert decoded["production_date"] == "2026-01-15"
        assert decoded["calibration_offset"] == 4096

    def test_mac_format(self, work_dir, sample_data_file):
        output = os.path.join(work_dir, "output.tlv")
        run_cmd(f"{TLV_MANAGER} encode --schema {SCHEMA} --data {sample_data_file} --output {output}")
        result = run_cmd(f"{TLV_MANAGER} decode --schema {SCHEMA} --input {output}")
        decoded = json.loads(result.stdout)
        parts = decoded["mac_address"].split(":")
        assert len(parts) == 6
        for p in parts:
            assert len(p) == 2
            int(p, 16)

    def test_binary_field(self, work_dir, sample_data_file):
        output = os.path.join(work_dir, "output.tlv")
        run_cmd(f"{TLV_MANAGER} encode --schema {SCHEMA} --data {sample_data_file} --output {output}")
        result = run_cmd(f"{TLV_MANAGER} decode --schema {SCHEMA} --input {output}")
        decoded = json.loads(result.stdout)
        decoded_bytes = base64.b64decode(decoded["calibration_blob"])
        assert decoded_bytes == bytes([1, 2, 3, 4, 5, 6])

    def test_hex_field(self, work_dir, sample_data_file):
        output = os.path.join(work_dir, "output.tlv")
        run_cmd(f"{TLV_MANAGER} encode --schema {SCHEMA} --data {sample_data_file} --output {output}")
        result = run_cmd(f"{TLV_MANAGER} decode --schema {SCHEMA} --input {output}")
        decoded = json.loads(result.stdout)
        soc_id = decoded["soc_id"].lower()
        assert soc_id == "0x1a2b3c4d5e6f7080"

    def test_minimal_data(self, work_dir):
        """Round-trip with only required fields."""
        minimal = {"serial_number": "SN001", "mac_address": "00:11:22:33:44:55"}
        data_path = os.path.join(work_dir, "minimal.json")
        with open(data_path, 'w') as f:
            json.dump(minimal, f)

        output = os.path.join(work_dir, "output.tlv")
        run_cmd(f"{TLV_MANAGER} encode --schema {SCHEMA} --data {data_path} --output {output}")
        result = run_cmd(f"{TLV_MANAGER} decode --schema {SCHEMA} --input {output}")
        decoded = json.loads(result.stdout)
        assert decoded["serial_number"] == "SN001"
        assert decoded["mac_address"].upper() == "00:11:22:33:44:55"
        assert "hw_revision" not in decoded
        assert "soc_id" not in decoded

    def test_no_device_bound_flag_without_soc_id(self, work_dir):
        """Blob without soc_id should not have device-bound flag."""
        minimal = {"serial_number": "SN001", "mac_address": "00:11:22:33:44:55"}
        data_path = os.path.join(work_dir, "minimal.json")
        with open(data_path, 'w') as f:
            json.dump(minimal, f)
        output = os.path.join(work_dir, "output.tlv")
        run_cmd(f"{TLV_MANAGER} encode --schema {SCHEMA} --data {data_path} --output {output}")
        with open(output, 'rb') as f:
            f.read(4)
            f.read(2)
            flags = struct.unpack('<H', f.read(2))[0]
        assert not (flags & 0x0002)


# ---- Signing / Verification Tests ----

class TestSigning:
    def test_sign_then_verify(self, work_dir, sample_data_file):
        unsigned = os.path.join(work_dir, "unsigned.tlv")
        signed = os.path.join(work_dir, "signed.tlv")
        run_cmd(f"{TLV_MANAGER} encode --schema {SCHEMA} --data {sample_data_file} --output {unsigned}")
        run_cmd(f"{TLV_MANAGER} sign --input {unsigned} --key {TEST_PRIVATE_KEY} --output {signed}")
        result = run_cmd(f"{TLV_MANAGER} verify --input {signed} --key {TEST_PUBLIC_KEY}")
        assert result.returncode == 0

    def test_encode_with_sign_key(self, work_dir, sample_data_file):
        signed = os.path.join(work_dir, "signed.tlv")
        run_cmd(
            f"{TLV_MANAGER} encode --schema {SCHEMA} --data {sample_data_file} "
            f"--output {signed} --sign-key {TEST_PRIVATE_KEY}"
        )
        result = run_cmd(f"{TLV_MANAGER} verify --input {signed} --key {TEST_PUBLIC_KEY}")
        assert result.returncode == 0

    def test_signed_flag_set(self, work_dir, sample_data_file):
        signed = os.path.join(work_dir, "signed.tlv")
        run_cmd(
            f"{TLV_MANAGER} encode --schema {SCHEMA} --data {sample_data_file} "
            f"--output {signed} --sign-key {TEST_PRIVATE_KEY}"
        )
        with open(signed, 'rb') as f:
            f.read(4)
            f.read(2)
            flags = struct.unpack('<H', f.read(2))[0]
        assert flags & 0x0001

    def test_signed_blob_size(self, work_dir, sample_data_file):
        """Signed blob = 16 + payload_len + 2 + sig_len."""
        signed = os.path.join(work_dir, "signed.tlv")
        run_cmd(
            f"{TLV_MANAGER} encode --schema {SCHEMA} --data {sample_data_file} "
            f"--output {signed} --sign-key {TEST_PRIVATE_KEY}"
        )
        with open(signed, 'rb') as f:
            data = f.read()
        _, _, flags, payload_len, _ = struct.unpack('<IHHII', data[:16])
        assert flags & 0x0001
        sig_offset = 16 + payload_len
        sig_len = struct.unpack('<H', data[sig_offset:sig_offset + 2])[0]
        assert len(data) == 16 + payload_len + 2 + sig_len

    def test_tampered_blob_fails(self, work_dir, sample_data_file):
        signed = os.path.join(work_dir, "signed.tlv")
        run_cmd(
            f"{TLV_MANAGER} encode --schema {SCHEMA} --data {sample_data_file} "
            f"--output {signed} --sign-key {TEST_PRIVATE_KEY}"
        )
        with open(signed, 'rb') as f:
            data = bytearray(f.read())
        data[20] ^= 0xFF
        tampered = os.path.join(work_dir, "tampered.tlv")
        with open(tampered, 'wb') as f:
            f.write(data)
        result = run_cmd(f"{TLV_MANAGER} verify --input {tampered} --key {TEST_PUBLIC_KEY}", check=False)
        assert result.returncode != 0

    def test_decode_signed_with_verify(self, work_dir, sample_data_file):
        signed = os.path.join(work_dir, "signed.tlv")
        run_cmd(
            f"{TLV_MANAGER} encode --schema {SCHEMA} --data {sample_data_file} "
            f"--output {signed} --sign-key {TEST_PRIVATE_KEY}"
        )
        result = run_cmd(
            f"{TLV_MANAGER} decode --schema {SCHEMA} --input {signed} "
            f"--verify-key {TEST_PUBLIC_KEY}"
        )
        decoded = json.loads(result.stdout)
        assert decoded["serial_number"] == "TB-2026-00042"


# ---- Device Binding Tests ----

class TestDeviceBinding:
    def test_correct_soc_id(self, work_dir, sample_data_file):
        output = os.path.join(work_dir, "output.tlv")
        run_cmd(f"{TLV_MANAGER} encode --schema {SCHEMA} --data {sample_data_file} --output {output}")
        result = run_cmd(
            f"{TLV_MANAGER} decode --schema {SCHEMA} --input {output} "
            f"--bind-soc-id 0x1A2B3C4D5E6F7080"
        )
        decoded = json.loads(result.stdout)
        assert decoded["serial_number"] == "TB-2026-00042"

    def test_wrong_soc_id(self, work_dir, sample_data_file):
        output = os.path.join(work_dir, "output.tlv")
        run_cmd(f"{TLV_MANAGER} encode --schema {SCHEMA} --data {sample_data_file} --output {output}")
        result = run_cmd(
            f"{TLV_MANAGER} decode --schema {SCHEMA} --input {output} "
            f"--bind-soc-id 0xDEADBEEF00000000",
            check=False
        )
        assert result.returncode != 0

    def test_case_insensitive_soc_id(self, work_dir, sample_data_file):
        output = os.path.join(work_dir, "output.tlv")
        run_cmd(f"{TLV_MANAGER} encode --schema {SCHEMA} --data {sample_data_file} --output {output}")
        result = run_cmd(
            f"{TLV_MANAGER} decode --schema {SCHEMA} --input {output} "
            f"--bind-soc-id 0x1a2b3c4d5e6f7080"
        )
        decoded = json.loads(result.stdout)
        assert decoded["serial_number"] == "TB-2026-00042"


# ---- Policy Filter Tests ----

class TestPolicyFilter:
    def test_lockdown_limits_fields(self, work_dir, sample_data_file):
        signed = os.path.join(work_dir, "signed.tlv")
        run_cmd(
            f"{TLV_MANAGER} encode --schema {SCHEMA} --data {sample_data_file} "
            f"--output {signed} --sign-key {TEST_PRIVATE_KEY}"
        )
        result = run_cmd(
            f"{TLV_MANAGER} policy-filter --schema {SCHEMA} --input {signed} "
            f"--policy /app/policies/lockdown.yaml --verify-key {TEST_PUBLIC_KEY}"
        )
        decoded = json.loads(result.stdout)
        assert "serial_number" in decoded
        assert "mac_address" in decoded
        assert "hw_revision" not in decoded
        assert "calibration_offset" not in decoded
        assert "calibration_blob" not in decoded
        assert "production_date" not in decoded

    def test_development_shows_all(self, work_dir, sample_data_file):
        output = os.path.join(work_dir, "output.tlv")
        run_cmd(f"{TLV_MANAGER} encode --schema {SCHEMA} --data {sample_data_file} --output {output}")
        result = run_cmd(
            f"{TLV_MANAGER} policy-filter --schema {SCHEMA} --input {output} "
            f"--policy /app/policies/development.yaml"
        )
        decoded = json.loads(result.stdout)
        assert "serial_number" in decoded
        assert "mac_address" in decoded
        assert "hw_revision" in decoded
        assert "calibration_offset" in decoded
        assert "production_date" in decoded

    def test_lockdown_rejects_unsigned(self, work_dir, sample_data_file):
        output = os.path.join(work_dir, "output.tlv")
        run_cmd(f"{TLV_MANAGER} encode --schema {SCHEMA} --data {sample_data_file} --output {output}")
        result = run_cmd(
            f"{TLV_MANAGER} policy-filter --schema {SCHEMA} --input {output} "
            f"--policy /app/policies/lockdown.yaml",
            check=False
        )
        assert result.returncode != 0

    def test_factory_shows_calibration(self, work_dir, sample_data_file):
        signed = os.path.join(work_dir, "signed.tlv")
        run_cmd(
            f"{TLV_MANAGER} encode --schema {SCHEMA} --data {sample_data_file} "
            f"--output {signed} --sign-key {TEST_PRIVATE_KEY}"
        )
        result = run_cmd(
            f"{TLV_MANAGER} policy-filter --schema {SCHEMA} --input {signed} "
            f"--policy /app/policies/factory.yaml --verify-key {TEST_PUBLIC_KEY}"
        )
        decoded = json.loads(result.stdout)
        assert "calibration_offset" in decoded
        assert "calibration_blob" in decoded
        assert "production_date" not in decoded

    def test_factory_rejects_unbound(self, work_dir):
        """Factory policy rejects blobs without device binding."""
        minimal = {"serial_number": "SN001", "mac_address": "00:11:22:33:44:55"}
        data_path = os.path.join(work_dir, "minimal.json")
        with open(data_path, 'w') as f:
            json.dump(minimal, f)
        signed = os.path.join(work_dir, "signed.tlv")
        run_cmd(
            f"{TLV_MANAGER} encode --schema {SCHEMA} --data {data_path} "
            f"--output {signed} --sign-key {TEST_PRIVATE_KEY}"
        )
        result = run_cmd(
            f"{TLV_MANAGER} policy-filter --schema {SCHEMA} --input {signed} "
            f"--policy /app/policies/factory.yaml --verify-key {TEST_PUBLIC_KEY}",
            check=False
        )
        assert result.returncode != 0


# ---- Policy Transition Tests ----

class TestPolicyTransition:
    def test_dev_to_factory(self):
        result = run_cmd(
            f"{TLV_MANAGER} policy-transition "
            f"--from-policy /app/policies/development.yaml "
            f"--to-policy /app/policies/factory.yaml "
            f"--policy-dir /app/policies"
        )
        assert result.returncode == 0

    def test_dev_to_lockdown(self):
        result = run_cmd(
            f"{TLV_MANAGER} policy-transition "
            f"--from-policy /app/policies/development.yaml "
            f"--to-policy /app/policies/lockdown.yaml "
            f"--policy-dir /app/policies"
        )
        assert result.returncode == 0

    def test_factory_to_lockdown(self):
        result = run_cmd(
            f"{TLV_MANAGER} policy-transition "
            f"--from-policy /app/policies/factory.yaml "
            f"--to-policy /app/policies/lockdown.yaml "
            f"--policy-dir /app/policies"
        )
        assert result.returncode == 0

    def test_lockdown_to_dev_denied(self):
        result = run_cmd(
            f"{TLV_MANAGER} policy-transition "
            f"--from-policy /app/policies/lockdown.yaml "
            f"--to-policy /app/policies/development.yaml "
            f"--policy-dir /app/policies",
            check=False
        )
        assert result.returncode != 0

    def test_lockdown_to_factory_denied(self):
        result = run_cmd(
            f"{TLV_MANAGER} policy-transition "
            f"--from-policy /app/policies/lockdown.yaml "
            f"--to-policy /app/policies/factory.yaml "
            f"--policy-dir /app/policies",
            check=False
        )
        assert result.returncode != 0

    def test_factory_to_dev_denied(self):
        result = run_cmd(
            f"{TLV_MANAGER} policy-transition "
            f"--from-policy /app/policies/factory.yaml "
            f"--to-policy /app/policies/development.yaml "
            f"--policy-dir /app/policies",
            check=False
        )
        assert result.returncode != 0


# ---- Error Handling Tests ----

class TestErrorHandling:
    def test_wrong_magic(self, work_dir, sample_data_file):
        output = os.path.join(work_dir, "output.tlv")
        run_cmd(f"{TLV_MANAGER} encode --schema {SCHEMA} --data {sample_data_file} --output {output}")
        with open(output, 'rb') as f:
            data = bytearray(f.read())
        data[0] = 0xFF
        corrupted = os.path.join(work_dir, "corrupted.tlv")
        with open(corrupted, 'wb') as f:
            f.write(data)
        result = run_cmd(f"{TLV_MANAGER} decode --schema {SCHEMA} --input {corrupted}", check=False)
        assert result.returncode != 0

    def test_corrupted_crc(self, work_dir, sample_data_file):
        output = os.path.join(work_dir, "output.tlv")
        run_cmd(f"{TLV_MANAGER} encode --schema {SCHEMA} --data {sample_data_file} --output {output}")
        with open(output, 'rb') as f:
            data = bytearray(f.read())
        # Corrupt the CRC field directly (bytes 12-15)
        data[12] ^= 0xFF
        corrupted = os.path.join(work_dir, "corrupted.tlv")
        with open(corrupted, 'wb') as f:
            f.write(data)
        result = run_cmd(f"{TLV_MANAGER} decode --schema {SCHEMA} --input {corrupted}", check=False)
        assert result.returncode != 0

    def test_truncated_blob(self, work_dir, sample_data_file):
        output = os.path.join(work_dir, "output.tlv")
        run_cmd(f"{TLV_MANAGER} encode --schema {SCHEMA} --data {sample_data_file} --output {output}")
        with open(output, 'rb') as f:
            data = f.read()
        truncated = os.path.join(work_dir, "truncated.tlv")
        with open(truncated, 'wb') as f:
            f.write(data[:10])
        result = run_cmd(f"{TLV_MANAGER} decode --schema {SCHEMA} --input {truncated}", check=False)
        assert result.returncode != 0

    def test_missing_required_field(self, work_dir):
        bad_data = {"serial_number": "SN001"}  # missing required mac_address
        data_path = os.path.join(work_dir, "bad.json")
        with open(data_path, 'w') as f:
            json.dump(bad_data, f)
        output = os.path.join(work_dir, "output.tlv")
        result = run_cmd(
            f"{TLV_MANAGER} encode --schema {SCHEMA} --data {data_path} --output {output}",
            check=False
        )
        assert result.returncode != 0
