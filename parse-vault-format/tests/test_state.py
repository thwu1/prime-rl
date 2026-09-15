"""Tests for the vault binary archive parser.
Verifies parser output against known expected values for two vaults.
Does NOT contain the encryption algorithm — solver must reverse engineer it."""
import json
import os
import hashlib
import subprocess

import pytest

VAULT_PATH = "/app/archive.vault"
RESULTS_DIR = "/app/results"
PARSER_PATH = "/app/vault_parser.py"

EXTRA_VAULT_PATH = "/app/test_extra.vault"
EXTRA_RESULTS_DIR = "/app/results_extra"

# ---- Expected values for the MAIN vault (7 files, seed=0x4B) ----
EXPECTED_FILE_COUNT = 7
EXPECTED_FILE_NAMES = [
    "config.ini",
    "firmware.bin",
    "keys.db",
    "manifest.json",
    "secret.dat",
    "checksums.txt",
    "system_diagnostics_report_" + "a" * 96 + "_v2.log",
]
EXPECTED_VERIFICATION_TOKEN = (
    "f2aebc738e980c665ef77e4448dbe5fc85e4c4e171b3f05b636b433ebf30fe5b"
)
EXPECTED_INTEGRITY_HASH = (
    "f882d1286d05b934bdcc0fcabd20e343c64b5b0652fda2b9fced77b09fc2c86e"
)
EXPECTED_SHA256 = {
    "config.ini": "96d310c96a846c39a853e849a8c4ee874c085c57c309d6a3d83ae7fb13700efa",
    "firmware.bin": "4133d1269ecfae54c5c0823f7d91d43f4878b6a50138c361012786b28b5745a8",
    "keys.db": "6378d28f56aa8a5c40ded3f59ad314260cc72e8b911a395b17e3dcbd8d45a591",
    "manifest.json": "da29dc5078c011e76aec0c150c2b8cfad1bf1cef1fb4be0b9b6ae8c101a74fd9",
    "secret.dat": "5f5bd58614495be1845877aae138afe9d38652acf7d7fd2187beeea32ac9362e",
    "checksums.txt": "0fb202fd2002f92ed0f0f1a79ada696e031e88f02ff660d252abb90e50c28e27",
}
EXPECTED_CRC32 = {
    "config.ini": "0x0F9CB6AE",
    "firmware.bin": "0x85FB26AA",
    "keys.db": "0x27F4DD30",
}

# ---- Expected values for the EXTRA test vault (3 files, seed=0x37) ----
EXTRA_FILE_COUNT = 3
EXTRA_FILE_NAMES = ["alpha.txt", "beta.bin", "gamma.json"]
EXTRA_VERIFICATION_TOKEN = (
    "2081856fe117262b3e17cfda981c772509cfa0a5d423229e245887bb372e0faf"
)
EXTRA_INTEGRITY_HASH = (
    "094491e19e6785608af03b20042ff8e25e89df732fcace1fab22fd2078c69dfe"
)
EXTRA_SHA256 = {
    "alpha.txt": "1d1dd7c442ac48b75680687651e4e4dd3d59b8305709e4047896fd8318e7d03e",
    "beta.bin": "6c5e66a9898820a9bb702eb6e93e76e1a623b4e46563f11b990ceb79b250c08e",
    "gamma.json": "cdeffe42495fc2e7ebfe97bd95a9283bf9f1d81b5b0211bccc892403c01ccc87",
}


class TestParserExists:
    def test_parser_file_exists(self):
        assert os.path.isfile(PARSER_PATH), "Parser not found at /app/vault_parser.py"

    def test_parser_is_valid_python(self):
        result = subprocess.run(
            ["python3", "-c",
             f"import importlib.util; spec = importlib.util.spec_from_file_location('m', '{PARSER_PATH}'); assert spec is not None"],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0, f"Parser is not valid Python: {result.stderr}"

    def test_parser_is_self_contained(self):
        """Parser must not shell out to vault_tool."""
        with open(PARSER_PATH) as f:
            src = f.read()
        assert "vault_tool" not in src, "Parser must be self-contained — cannot depend on vault_tool binary"
        assert "subprocess" not in src or "vault_tool" not in src, (
            "Parser must not invoke vault_tool via subprocess"
        )


class TestResultsStructure:
    def test_results_dir_exists(self):
        assert os.path.isdir(RESULTS_DIR), "Results directory not found"

    def test_file_table_exists(self):
        assert os.path.isfile(os.path.join(RESULTS_DIR, "file_table.json"))

    def test_metadata_exists(self):
        assert os.path.isfile(os.path.join(RESULTS_DIR, "metadata.json"))

    def test_verification_exists(self):
        assert os.path.isfile(os.path.join(RESULTS_DIR, "verification.txt"))

    def test_integrity_exists(self):
        assert os.path.isfile(os.path.join(RESULTS_DIR, "integrity.txt"))

    def test_extracted_dir_exists(self):
        assert os.path.isdir(os.path.join(RESULTS_DIR, "extracted"))


class TestFileTable:
    @pytest.fixture(autouse=True)
    def load_file_table(self):
        path = os.path.join(RESULTS_DIR, "file_table.json")
        if os.path.isfile(path):
            with open(path) as f:
                self.table = json.load(f)
        else:
            self.table = []

    def test_file_count(self):
        assert len(self.table) == EXPECTED_FILE_COUNT, (
            f"Expected {EXPECTED_FILE_COUNT} files, got {len(self.table)}"
        )

    def test_file_names(self):
        names = [e["name"] for e in self.table]
        for expected_name in EXPECTED_FILE_NAMES:
            assert expected_name in names, f"Missing file: {expected_name}"

    def test_entries_have_required_fields(self):
        required = {"name", "compressed_size", "decompressed_size", "crc32",
                     "flags", "encrypted", "sha256"}
        for entry in self.table:
            for field in required:
                assert field in entry, (
                    f"Entry {entry.get('name', '?')} missing field: {field}"
                )

    def test_encrypted_flags(self):
        encrypted_files = {"firmware.bin", "manifest.json", "secret.dat"}
        for entry in self.table:
            if entry["name"] in encrypted_files:
                assert entry["encrypted"] is True, (
                    f"{entry['name']} should be encrypted"
                )
            elif entry["name"] in {"config.ini", "keys.db", "checksums.txt"}:
                assert entry["encrypted"] is False, (
                    f"{entry['name']} should NOT be encrypted"
                )

    def test_crc32_values(self):
        for entry in self.table:
            if entry["name"] in EXPECTED_CRC32:
                actual = entry["crc32"][:2].lower() + entry["crc32"][2:].upper()
                assert actual == EXPECTED_CRC32[entry["name"]], (
                    f"CRC mismatch for {entry['name']}: {entry['crc32']} != "
                    f"{EXPECTED_CRC32[entry['name']]}"
                )


class TestExtractedFiles:
    def _check_sha256(self, filename):
        path = os.path.join(RESULTS_DIR, "extracted", filename)
        assert os.path.isfile(path), f"{filename} not extracted"
        sha = hashlib.sha256(open(path, "rb").read()).hexdigest()
        assert sha == EXPECTED_SHA256[filename], (
            f"SHA256 mismatch for {filename}"
        )

    def test_config_ini(self):
        self._check_sha256("config.ini")

    def test_firmware_bin(self):
        self._check_sha256("firmware.bin")

    def test_keys_db(self):
        self._check_sha256("keys.db")

    def test_manifest_json(self):
        self._check_sha256("manifest.json")

    def test_secret_dat(self):
        self._check_sha256("secret.dat")

    def test_checksums_txt(self):
        self._check_sha256("checksums.txt")

    def test_secret_dat_content(self):
        path = os.path.join(RESULTS_DIR, "extracted", "secret.dat")
        if os.path.isfile(path):
            data = open(path, "rb").read()
            assert data.startswith(b"VAULT_SECRET_PAYLOAD:"), (
                "secret.dat does not start with expected payload marker"
            )

    def test_config_ini_content(self):
        path = os.path.join(RESULTS_DIR, "extracted", "config.ini")
        if os.path.isfile(path):
            content = open(path, "r").read()
            assert "VaultOS" in content
            assert "AES-256-GCM" in content

    def test_manifest_json_content(self):
        path = os.path.join(RESULTS_DIR, "extracted", "manifest.json")
        if os.path.isfile(path):
            data = json.load(open(path))
            assert data["package"] == "vault-system"
            assert data["build_id"] == "BLD-2024-0847"

    def test_long_filename_extracted(self):
        long_name = "system_diagnostics_report_" + "a" * 96 + "_v2.log"
        path = os.path.join(RESULTS_DIR, "extracted", long_name)
        assert os.path.isfile(path), f"Long-named file not extracted: {long_name[:40]}..."
        data = open(path, "rb").read()
        assert b"DIAGNOSTIC REPORT" in data
        assert b"ALL SYSTEMS OPERATIONAL" in data


class TestMetadata:
    @pytest.fixture(autouse=True)
    def load_metadata(self):
        path = os.path.join(RESULTS_DIR, "metadata.json")
        if os.path.isfile(path):
            with open(path) as f:
                self.metadata = json.load(f)
        else:
            self.metadata = {}

    def test_verification_token(self):
        assert self.metadata.get("verification_token") == EXPECTED_VERIFICATION_TOKEN

    def test_integrity_hash(self):
        assert self.metadata.get("integrity_hash") == EXPECTED_INTEGRITY_HASH

    def test_metadata_structure(self):
        assert self.metadata.get("format") == "vault-archive"
        assert self.metadata.get("version") == 3
        assert self.metadata.get("author") == "VaultMaster"
        assert self.metadata.get("entry_count") == EXPECTED_FILE_COUNT

    def test_verification_txt(self):
        path = os.path.join(RESULTS_DIR, "verification.txt")
        if os.path.isfile(path):
            token = open(path).read().strip()
            assert token == EXPECTED_VERIFICATION_TOKEN

    def test_integrity_txt(self):
        path = os.path.join(RESULTS_DIR, "integrity.txt")
        if os.path.isfile(path):
            ihash = open(path).read().strip()
            assert ihash == EXPECTED_INTEGRITY_HASH


class TestExtraVault:
    """Verify parser generalizes to a second vault with different content and seed."""

    def test_parser_runs_on_extra_vault(self):
        assert os.path.isdir(EXTRA_RESULTS_DIR), (
            "Extra results directory not found — parser must handle test_extra.vault"
        )

    def test_extra_file_table(self):
        path = os.path.join(EXTRA_RESULTS_DIR, "file_table.json")
        assert os.path.isfile(path), "file_table.json not created for extra vault"
        ft = json.load(open(path))
        assert len(ft) == EXTRA_FILE_COUNT
        names = [e["name"] for e in ft]
        for n in EXTRA_FILE_NAMES:
            assert n in names, f"Missing file in extra vault: {n}"

    def test_extra_extracted_alpha(self):
        path = os.path.join(EXTRA_RESULTS_DIR, "extracted", "alpha.txt")
        assert os.path.isfile(path), "alpha.txt not extracted from extra vault"
        sha = hashlib.sha256(open(path, "rb").read()).hexdigest()
        assert sha == EXTRA_SHA256["alpha.txt"]

    def test_extra_extracted_beta(self):
        path = os.path.join(EXTRA_RESULTS_DIR, "extracted", "beta.bin")
        assert os.path.isfile(path), "beta.bin not extracted from extra vault"
        sha = hashlib.sha256(open(path, "rb").read()).hexdigest()
        assert sha == EXTRA_SHA256["beta.bin"]

    def test_extra_extracted_gamma(self):
        path = os.path.join(EXTRA_RESULTS_DIR, "extracted", "gamma.json")
        assert os.path.isfile(path), "gamma.json not extracted from extra vault"
        sha = hashlib.sha256(open(path, "rb").read()).hexdigest()
        assert sha == EXTRA_SHA256["gamma.json"]

    def test_extra_metadata(self):
        path = os.path.join(EXTRA_RESULTS_DIR, "metadata.json")
        assert os.path.isfile(path), "metadata.json not created for extra vault"
        meta = json.load(open(path))
        assert meta["verification_token"] == EXTRA_VERIFICATION_TOKEN
        assert meta["integrity_hash"] == EXTRA_INTEGRITY_HASH

    def test_extra_verification_txt(self):
        path = os.path.join(EXTRA_RESULTS_DIR, "verification.txt")
        assert os.path.isfile(path)
        assert open(path).read().strip() == EXTRA_VERIFICATION_TOKEN

    def test_extra_integrity_txt(self):
        path = os.path.join(EXTRA_RESULTS_DIR, "integrity.txt")
        assert os.path.isfile(path)
        assert open(path).read().strip() == EXTRA_INTEGRITY_HASH
