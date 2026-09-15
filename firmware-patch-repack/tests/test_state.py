
import struct
import hashlib
import hmac as hmac_mod
import json
import os
import subprocess
import pytest

FIRMWARE_PATH = "/app/firmware_patched.bin"

HEADER_SIZE = 44
DIR_ENTRY_SIZE = 64


def xor_crypt(data, key):
    return bytes(d ^ key[i % len(key)] for i, d in enumerate(data))


def parse_fwpk(data):
    """Parse FWPK container returning header info and section list."""
    magic = data[:4]
    version = struct.unpack("<H", data[4:6])[0]
    num_sections = struct.unpack("<H", data[6:8])[0]
    dir_offset = struct.unpack("<I", data[8:12])[0]
    stored_hmac = data[12:44]

    sections = []
    for i in range(num_sections):
        base = dir_offset + i * DIR_ENTRY_SIZE
        name = data[base : base + 16].rstrip(b"\x00").decode("ascii")
        offset = struct.unpack("<I", data[base + 16 : base + 20])[0]
        length = struct.unpack("<I", data[base + 20 : base + 24])[0]
        flags = struct.unpack("<I", data[base + 24 : base + 28])[0]
        sha256_hash = data[base + 32 : base + 64]
        section_data = data[offset : offset + length]
        sections.append(
            {
                "name": name,
                "offset": offset,
                "length": length,
                "flags": flags,
                "sha256": sha256_hash,
                "data": section_data,
            }
        )

    return {
        "magic": magic,
        "version": version,
        "num_sections": num_sections,
        "dir_offset": dir_offset,
        "stored_hmac": stored_hmac,
        "sections": sections,
    }


def get_section(parsed, name):
    for s in parsed["sections"]:
        if s["name"] == name:
            return s
    raise KeyError(f"Section '{name}' not found")


@pytest.fixture
def firmware_data():
    assert os.path.exists(FIRMWARE_PATH), f"Not found: {FIRMWARE_PATH}"
    with open(FIRMWARE_PATH, "rb") as f:
        return f.read()


@pytest.fixture
def parsed(firmware_data):
    return parse_fwpk(firmware_data)


@pytest.fixture
def extracted_fs(parsed, tmp_path):
    """Decompress payload section and extract CPIO filesystem."""
    payload = get_section(parsed, "payload")
    gz_path = tmp_path / "payload.gz"
    gz_path.write_bytes(payload["data"])
    result = subprocess.run(["gunzip", "-c", str(gz_path)], capture_output=True)
    assert result.returncode == 0, f"GZIP decompression failed: {result.stderr.decode()}"

    extract_dir = tmp_path / "root"
    extract_dir.mkdir()
    result = subprocess.run(
        ["cpio", "-id", "--no-absolute-filenames"],
        input=result.stdout,
        capture_output=True,
        cwd=str(extract_dir),
    )
    assert result.returncode == 0, f"CPIO extraction failed: {result.stderr.decode()}"
    return extract_dir


# ---------------------------------------------------------------------------
# Container integrity
# ---------------------------------------------------------------------------


class TestFWPKContainer:
    def test_magic(self, parsed):
        assert parsed["magic"] == b"FWPK", f"Bad magic: {parsed['magic']!r}"

    def test_version(self, parsed):
        assert parsed["version"] == 2

    def test_num_sections(self, parsed):
        assert parsed["num_sections"] == 4

    def test_has_required_sections(self, parsed):
        names = {s["name"] for s in parsed["sections"]}
        for required in ("meta", "payload", "config.enc", "hmac.key"):
            assert required in names, f"Missing section: {required}"

    def test_per_section_sha256(self, parsed):
        for s in parsed["sections"]:
            computed = hashlib.sha256(s["data"]).digest()
            assert computed == s["sha256"], (
                f"SHA-256 mismatch for section '{s['name']}': "
                f"stored={s['sha256'].hex()[:16]}... computed={computed.hex()[:16]}..."
            )

    def test_hmac_integrity(self, parsed):
        hmac_key = get_section(parsed, "hmac.key")["data"]
        all_data = b"".join(s["data"] for s in parsed["sections"])
        h = hmac_mod.new(hmac_key, all_data, hashlib.sha256)
        computed = h.digest()
        assert computed == parsed["stored_hmac"], "HMAC-SHA256 verification failed"


# ---------------------------------------------------------------------------
# Gateway binary security configuration
# ---------------------------------------------------------------------------


class TestSecurityConfig:
    """Verify the SECCFG block in the gateway binary is properly hardened."""

    MARKER = b"SECCFG\x00\x00"

    def _read_seccfg(self, binary_data):
        idx = binary_data.find(self.MARKER)
        assert idx >= 0, "SECCFG marker not found in binary"
        return {
            "max_channel": struct.unpack_from("<H", binary_data, idx + 8)[0],
            "require_auth": binary_data[idx + 10],
            "tls_mode": binary_data[idx + 11],
            "session_timeout": struct.unpack_from("<I", binary_data, idx + 12)[0],
            "allow_debug": binary_data[idx + 16],
            "cert_verify": binary_data[idx + 17],
            "min_key_bits": struct.unpack_from("<H", binary_data, idx + 18)[0],
        }

    def test_max_channel(self, extracted_fs):
        gw = (extracted_fs / "usr" / "bin" / "gateway").read_bytes()
        assert self._read_seccfg(gw)["max_channel"] == 16

    def test_require_auth(self, extracted_fs):
        gw = (extracted_fs / "usr" / "bin" / "gateway").read_bytes()
        assert self._read_seccfg(gw)["require_auth"] == 1

    def test_tls_required(self, extracted_fs):
        gw = (extracted_fs / "usr" / "bin" / "gateway").read_bytes()
        assert self._read_seccfg(gw)["tls_mode"] == 2

    def test_debug_disabled(self, extracted_fs):
        gw = (extracted_fs / "usr" / "bin" / "gateway").read_bytes()
        assert self._read_seccfg(gw)["allow_debug"] == 0

    def test_cert_verify_enabled(self, extracted_fs):
        gw = (extracted_fs / "usr" / "bin" / "gateway").read_bytes()
        assert self._read_seccfg(gw)["cert_verify"] == 1

    def test_min_key_bits(self, extracted_fs):
        gw = (extracted_fs / "usr" / "bin" / "gateway").read_bytes()
        assert self._read_seccfg(gw)["min_key_bits"] == 2048

    def test_session_timeout_preserved(self, extracted_fs):
        gw = (extracted_fs / "usr" / "bin" / "gateway").read_bytes()
        assert self._read_seccfg(gw)["session_timeout"] == 86400


# ---------------------------------------------------------------------------
# Gateway binary execution
# ---------------------------------------------------------------------------


class TestGatewayExecution:
    def test_validate_channel_15_accepted(self, extracted_fs):
        gw = extracted_fs / "usr" / "bin" / "gateway"
        os.chmod(str(gw), 0o755)
        result = subprocess.run(
            [str(gw), "--validate", "15"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode == 0, f"Channel 15 should be valid. stderr: {result.stderr}"
        assert "valid" in result.stdout.lower()

    def test_validate_channel_16_rejected(self, extracted_fs):
        gw = extracted_fs / "usr" / "bin" / "gateway"
        os.chmod(str(gw), 0o755)
        result = subprocess.run(
            [str(gw), "--validate", "16"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode != 0, "Channel 16 must be rejected after patching"
        assert "invalid" in result.stdout.lower()

    def test_security_dump_values(self, extracted_fs):
        gw = extracted_fs / "usr" / "bin" / "gateway"
        os.chmod(str(gw), 0o755)
        result = subprocess.run(
            [str(gw), "--security"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode == 0
        out = result.stdout
        assert "max_channel: 16" in out
        assert "require_auth: 1" in out
        assert "tls_mode: 2" in out
        assert "allow_debug: 0" in out
        assert "cert_verify: 1" in out
        assert "min_key_bits: 2048" in out


# ---------------------------------------------------------------------------
# Encrypted configuration
# ---------------------------------------------------------------------------


class TestEncryptedConfig:
    def _decrypt_config(self, parsed):
        meta = json.loads(get_section(parsed, "meta")["data"])
        key = bytes.fromhex(meta["config_key"])
        enc = get_section(parsed, "config.enc")["data"]
        return xor_crypt(enc, key).decode("ascii")

    def test_config_decrypts_to_valid_text(self, parsed):
        plaintext = self._decrypt_config(parsed)
        assert "[network]" in plaintext
        assert "[device]" in plaintext

    def test_tls_enabled(self, parsed):
        plaintext = self._decrypt_config(parsed)
        assert "tls_enabled=true" in plaintext
        assert "tls_enabled=false" not in plaintext

    def test_cipher_suite(self, parsed):
        plaintext = self._decrypt_config(parsed)
        assert "cipher_suite=AES256-GCM" in plaintext
        assert "cipher_suite=RC4-MD5" not in plaintext

    def test_other_settings_preserved(self, parsed):
        plaintext = self._decrypt_config(parsed)
        assert "bind_address=0.0.0.0" in plaintext
        assert "device_id=GW-0042" in plaintext


# ---------------------------------------------------------------------------
# SquashFS modules
# ---------------------------------------------------------------------------


class TestSquashFS:
    def test_remote_debug_disabled(self, extracted_fs):
        sqfs = extracted_fs / "opt" / "modules.sqfs"
        assert sqfs.exists(), "modules.sqfs not found"
        unsquash_dir = extracted_fs / "sqfs_extract"
        result = subprocess.run(
            ["unsquashfs", "-d", str(unsquash_dir), str(sqfs)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"unsquashfs failed: {result.stderr}"
        diag = unsquash_dir / "scripts" / "diag.py"
        assert diag.exists(), "diag.py not found in SquashFS"
        content = diag.read_text()
        assert "REMOTE_DEBUG_ENABLED = False" in content
        assert "REMOTE_DEBUG_ENABLED = True" not in content


# ---------------------------------------------------------------------------
# Metadata, version, and manifest
# ---------------------------------------------------------------------------


class TestMetadataAndManifest:
    def test_firmware_version_in_meta(self, parsed):
        meta = json.loads(get_section(parsed, "meta")["data"])
        assert meta["firmware_version"] == "2.0.0"

    def test_config_key_preserved(self, parsed):
        meta = json.loads(get_section(parsed, "meta")["data"])
        assert "config_key" in meta
        key = bytes.fromhex(meta["config_key"])
        assert len(key) > 0

    def test_version_file_in_filesystem(self, extracted_fs):
        ver = (extracted_fs / "var" / "firmware_version").read_text().strip()
        assert ver == "2.0.0"

    def test_manifest_exists_and_valid(self, extracted_fs):
        manifest_path = extracted_fs / "var" / "manifest.json"
        assert manifest_path.exists(), "manifest.json not found"
        data = json.loads(manifest_path.read_text())
        assert isinstance(data, dict)
        assert data.get("version") == "2.0.0"

    def test_manifest_gateway_sha256(self, extracted_fs):
        manifest = json.loads((extracted_fs / "var" / "manifest.json").read_text())
        gw = extracted_fs / "usr" / "bin" / "gateway"
        expected = hashlib.sha256(gw.read_bytes()).hexdigest()
        actual = manifest.get("gateway_sha256", "")
        assert actual == expected, (
            f"gateway SHA-256 mismatch: manifest={actual[:16]}... expected={expected[:16]}..."
        )

    def test_manifest_config_sha256(self, parsed, extracted_fs):
        manifest = json.loads((extracted_fs / "var" / "manifest.json").read_text())
        meta = json.loads(get_section(parsed, "meta")["data"])
        key = bytes.fromhex(meta["config_key"])
        enc = get_section(parsed, "config.enc")["data"]
        plaintext = xor_crypt(enc, key)
        expected = hashlib.sha256(plaintext).hexdigest()
        actual = manifest.get("config_sha256", "")
        assert actual == expected, (
            f"config SHA-256 mismatch: manifest={actual[:16]}... expected={expected[:16]}..."
        )
