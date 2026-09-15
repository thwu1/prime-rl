"""
PDDB Page Table Security Audit -- verification tests.

Independently re-derives keys, decrypts entries, scans for ECB duplicates,
computes false-positive rates, verifies nonce analysis, and validates
FSCB differential leakage metrics.

"""
import json
import hashlib
import hmac
import struct
import binascii
import math
import os
from collections import defaultdict

import pytest
from Crypto.Cipher import AES

# ── Ground truth constants ──────────────────────────────────────────────────
DEVICE_SALT = bytes.fromhex(
    "a3b7c9d1e5f20a1b3c4d5e6f7a8b9c0d"
    "1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b"
)
PBKDF2_ITERATIONS = 10000
NUM_PT_ENTRIES = 2000

EXPECTED_BASES = {
    ".System":    {"password": "precursor_boot_2024",  "num_entries": 400},
    "documents":  {"password": "my_d0cuments_key",     "num_entries": 250},
    "vault":      {"password": "pl4us1bly_d3n14bl3",   "num_entries": 180},
    "operations": {"password": "cl4ss1f1ed_alpha",     "num_entries": 120},
}

RESULTS_DIR = "/app/results"
IMAGE_PATH = "/app/pddb_image.bin"
FSCB_PATH = "/app/fscb.json"
FSCB_PREV_PATH = "/app/fscb_previous.json"


# ── Crypto helpers ──────────────────────────────────────────────────────────
def derive_key(device_salt, basis_name, password):
    per_basis_salt = hmac.new(
        device_salt, basis_name.encode("utf-8"), hashlib.sha256
    ).digest()
    stretched = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), per_basis_salt,
        PBKDF2_ITERATIONS, dklen=32,
    )
    return hmac.new(stretched, b"pddb-page-table-key", hashlib.sha256).digest()


def decrypt_entry(encrypted, key):
    return AES.new(key, AES.MODE_ECB).decrypt(encrypted)


def validate_entry(plaintext):
    data = plaintext[:12]
    stored_crc = struct.unpack("<I", plaintext[12:16])[0]
    return (binascii.crc32(data) & 0xFFFFFFFF) == stored_crc


def parse_entry(plaintext):
    vaddr = int.from_bytes(plaintext[:7], "little")
    flags = plaintext[7]
    nonce = struct.unpack("<I", plaintext[8:12])[0]
    return vaddr, flags, nonce


def read_encrypted_entries():
    with open(IMAGE_PATH, "rb") as f:
        f.seek(64)
        return [f.read(16) for _ in range(NUM_PT_ENTRIES)]


# ── Fixtures ────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def ground_truth():
    raw_entries = read_encrypted_entries()
    truth = {}
    for basis_name, info in EXPECTED_BASES.items():
        key = derive_key(DEVICE_SALT, basis_name, info["password"])
        pages = {}
        for idx, enc in enumerate(raw_entries):
            dec = decrypt_entry(enc, key)
            if validate_entry(dec):
                vaddr, flags, nonce = parse_entry(dec)
                pages[idx] = {
                    "virtual_address": vaddr,
                    "flags": flags,
                    "nonce": nonce,
                }
        assert len(pages) == info["num_entries"], (
            f"Ground truth: expected {info['num_entries']} for "
            f"{basis_name}, got {len(pages)}"
        )
        truth[basis_name] = {"key": key, "pages": pages}
    return truth


@pytest.fixture(scope="module")
def ecb_ground_truth():
    """Independently find all duplicate ciphertext blocks and attribute."""
    raw_entries = read_encrypted_entries()
    ct_to_positions = defaultdict(list)
    for idx, enc in enumerate(raw_entries):
        ct_to_positions[enc].append(idx)

    duplicates = []
    for ct, positions in ct_to_positions.items():
        if len(positions) >= 2:
            # Attribute to a basis
            basis_attr = None
            for basis_name, info in EXPECTED_BASES.items():
                key = derive_key(DEVICE_SALT, basis_name, info["password"])
                dec = decrypt_entry(ct, key)
                if validate_entry(dec):
                    basis_attr = basis_name
                    break
            for i in range(len(positions)):
                for j in range(i + 1, len(positions)):
                    duplicates.append({
                        "page_a": positions[i],
                        "page_b": positions[j],
                        "basis": basis_attr or "unknown",
                        "ciphertext_hex": ct.hex(),
                    })
    return duplicates


@pytest.fixture(scope="module")
def fscb_differential_truth(ground_truth):
    """Compute FSCB differential ground truth."""
    with open(FSCB_PATH) as f:
        fscb_current = set(json.load(f)["free_pages"])
    with open(FSCB_PREV_PATH) as f:
        fscb_prev = set(json.load(f)["free_pages"])

    transitioned = fscb_prev - fscb_current

    known_pages = set()
    for basis_name in EXPECTED_BASES:
        known_pages.update(ground_truth[basis_name]["pages"].keys())

    attributable = transitioned & known_pages
    unattributable = transitioned - known_pages

    return {
        "transitioned": len(transitioned),
        "attributable": len(attributable),
        "unattributable": len(unattributable),
        "leaked": len(unattributable) > 0,
    }


# ── Tests: Output Files ────────────────────────────────────────────────────
class TestOutputFilesExist:
    def test_bases_json(self):
        assert os.path.isfile(f"{RESULTS_DIR}/bases.json"), "bases.json missing"

    def test_page_map_json(self):
        assert os.path.isfile(f"{RESULTS_DIR}/page_map.json"), (
            "page_map.json missing"
        )

    def test_security_audit_json(self):
        assert os.path.isfile(f"{RESULTS_DIR}/security_audit.json"), (
            "security_audit.json missing"
        )


# ── Tests: Basis Discovery ─────────────────────────────────────────────────
class TestBasesDiscovery:
    def test_correct_number_of_bases(self):
        with open(f"{RESULTS_DIR}/bases.json") as f:
            bases = json.load(f)
        assert len(bases) == len(EXPECTED_BASES)

    def test_all_bases_found(self):
        with open(f"{RESULTS_DIR}/bases.json") as f:
            bases = json.load(f)
        for name in EXPECTED_BASES:
            assert name in bases, f"Basis '{name}' not discovered"

    def test_correct_passwords(self):
        with open(f"{RESULTS_DIR}/bases.json") as f:
            bases = json.load(f)
        for name, info in EXPECTED_BASES.items():
            assert bases[name]["password"] == info["password"]

    def test_correct_keys(self, ground_truth):
        with open(f"{RESULTS_DIR}/bases.json") as f:
            bases = json.load(f)
        for name in EXPECTED_BASES:
            assert bases[name]["key_hex"] == ground_truth[name]["key"].hex()

    def test_correct_entry_counts(self):
        with open(f"{RESULTS_DIR}/bases.json") as f:
            bases = json.load(f)
        for name, info in EXPECTED_BASES.items():
            assert bases[name]["num_entries"] == info["num_entries"]


# ── Tests: Page Map ─────────────────────────────────────────────────────────
class TestPageMap:
    def test_all_bases_present(self):
        with open(f"{RESULTS_DIR}/page_map.json") as f:
            pmap = json.load(f)
        for name in EXPECTED_BASES:
            assert name in pmap

    def test_entry_counts_match(self):
        with open(f"{RESULTS_DIR}/page_map.json") as f:
            pmap = json.load(f)
        for name, info in EXPECTED_BASES.items():
            assert len(pmap[name]) == info["num_entries"]

    def test_physical_pages_correct(self, ground_truth):
        with open(f"{RESULTS_DIR}/page_map.json") as f:
            pmap = json.load(f)
        for name in EXPECTED_BASES:
            expected = set(ground_truth[name]["pages"].keys())
            actual = {m["physical_page"] for m in pmap[name]}
            assert actual == expected

    def test_virtual_addresses_correct(self, ground_truth):
        with open(f"{RESULTS_DIR}/page_map.json") as f:
            pmap = json.load(f)
        for name in EXPECTED_BASES:
            agent_map = {m["physical_page"]: m for m in pmap[name]}
            for phys, expected in ground_truth[name]["pages"].items():
                assert agent_map[phys]["virtual_address"] == (
                    expected["virtual_address"]
                )

    def test_decryption_integrity(self, ground_truth):
        raw = read_encrypted_entries()
        with open(f"{RESULTS_DIR}/page_map.json") as f:
            pmap = json.load(f)
        for name in EXPECTED_BASES:
            key = ground_truth[name]["key"]
            for m in pmap[name]:
                dec = decrypt_entry(raw[m["physical_page"]], key)
                assert validate_entry(dec)


# ── Tests: ECB Vulnerability ───────────────────────────────────────────────
class TestECBVulnerability:
    def test_section_exists(self):
        with open(f"{RESULTS_DIR}/security_audit.json") as f:
            audit = json.load(f)
        assert "ecb_vulnerability" in audit

    def test_duplicate_count(self, ecb_ground_truth):
        with open(f"{RESULTS_DIR}/security_audit.json") as f:
            audit = json.load(f)
        assert audit["ecb_vulnerability"]["total_duplicate_pairs"] == (
            len(ecb_ground_truth)
        )

    def test_vulnerability_detected(self, ecb_ground_truth):
        with open(f"{RESULTS_DIR}/security_audit.json") as f:
            audit = json.load(f)
        expected = len(ecb_ground_truth) > 0
        assert audit["ecb_vulnerability"]["vulnerability_present"] == expected

    def test_duplicate_pairs_match(self, ecb_ground_truth):
        with open(f"{RESULTS_DIR}/security_audit.json") as f:
            audit = json.load(f)
        agent_pairs = audit["ecb_vulnerability"]["duplicate_pairs"]

        def normalize(pairs):
            result = []
            for p in pairs:
                a = min(p["page_a"], p["page_b"])
                b = max(p["page_a"], p["page_b"])
                result.append((a, b, p["basis"], p["ciphertext_hex"]))
            return sorted(result)

        assert normalize(agent_pairs) == normalize(ecb_ground_truth)


# ── Tests: Integrity Analysis ──────────────────────────────────────────────
class TestIntegrityAnalysis:
    def test_section_exists(self):
        with open(f"{RESULTS_DIR}/security_audit.json") as f:
            audit = json.load(f)
        assert "integrity_analysis" in audit

    def test_per_entry_rate(self):
        with open(f"{RESULTS_DIR}/security_audit.json") as f:
            audit = json.load(f)
        rate = audit["integrity_analysis"]["per_entry_false_positive_rate"]
        expected = 1.0 / (2**32)
        assert abs(rate - expected) < 1e-12, (
            f"Expected {expected:.15e}, got {rate:.15e}"
        )

    def test_per_credential_expected(self):
        with open(f"{RESULTS_DIR}/security_audit.json") as f:
            audit = json.load(f)
        val = audit["integrity_analysis"][
            "expected_false_positives_per_credential"
        ]
        expected = NUM_PT_ENTRIES / (2**32)
        assert abs(val - expected) < 1e-9, (
            f"Expected {expected:.12e}, got {val:.12e}"
        )


# ── Tests: Nonce Analysis ──────────────────────────────────────────────────
class TestNonceAnalysis:
    def test_section_exists(self):
        with open(f"{RESULTS_DIR}/security_audit.json") as f:
            audit = json.load(f)
        assert "nonce_analysis" in audit

    def test_per_basis_probabilities(self):
        with open(f"{RESULTS_DIR}/security_audit.json") as f:
            audit = json.load(f)
        probs = audit["nonce_analysis"]["per_basis_collision_probability"]
        for name, info in EXPECTED_BASES.items():
            n = info["num_entries"]
            expected = 1.0 - math.exp(-n * (n - 1) / (2.0 * (2**32)))
            assert name in probs, f"Missing probability for {name}"
            assert abs(probs[name] - expected) < 1e-6

    def test_cross_basis_probabilities(self):
        with open(f"{RESULTS_DIR}/security_audit.json") as f:
            audit = json.load(f)
        cross = audit["nonce_analysis"]["cross_basis_collision_probability"]

        names = list(EXPECTED_BASES.keys())
        expected_sorted = []
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                n1 = EXPECTED_BASES[names[i]]["num_entries"]
                n2 = EXPECTED_BASES[names[j]]["num_entries"]
                expected_sorted.append(
                    1.0 - math.exp(-n1 * n2 / (2**32))
                )
        expected_sorted.sort()
        actual_sorted = sorted(cross.values())

        assert len(actual_sorted) == len(expected_sorted)
        for e, a in zip(expected_sorted, actual_sorted):
            assert abs(a - e) < 1e-6

    def test_actual_nonce_collisions(self, ground_truth):
        with open(f"{RESULTS_DIR}/security_audit.json") as f:
            audit = json.load(f)
        collisions = audit["nonce_analysis"]["actual_nonce_collisions"]

        # Independently find intra-basis nonce duplicates
        expected = set()
        for basis_name in EXPECTED_BASES:
            nonces = [
                v["nonce"]
                for v in ground_truth[basis_name]["pages"].values()
            ]
            seen = set()
            for n in nonces:
                if n in seen:
                    expected.add((basis_name, n))
                seen.add(n)

        actual = {(c["basis"], c["nonce"]) for c in collisions}
        assert actual == expected, (
            f"Nonce collision mismatch: expected {expected}, got {actual}"
        )


# ── Tests: FSCB Deniability ────────────────────────────────────────────────
class TestFSCBDeniability:
    def test_section_exists(self):
        with open(f"{RESULTS_DIR}/security_audit.json") as f:
            audit = json.load(f)
        assert "fscb_deniability" in audit

    def test_unknown_pages(self):
        with open(f"{RESULTS_DIR}/security_audit.json") as f:
            audit = json.load(f)
        total_valid = sum(
            info["num_entries"] for info in EXPECTED_BASES.values()
        )
        expected = NUM_PT_ENTRIES - total_valid
        assert audit["fscb_deniability"]["unknown_pages"] == expected

    def test_confirmed_free(self):
        with open(f"{RESULTS_DIR}/security_audit.json") as f:
            audit = json.load(f)
        with open(FSCB_PATH) as f:
            fscb = json.load(f)
        assert audit["fscb_deniability"]["confirmed_free"] == len(
            fscb["free_pages"]
        )

    def test_max_hidden(self):
        with open(f"{RESULTS_DIR}/security_audit.json") as f:
            audit = json.load(f)
        d = audit["fscb_deniability"]
        assert d["max_potentially_hidden"] == (
            d["unknown_pages"] - d["confirmed_free"]
        )

    def test_deniability_ratio(self):
        with open(f"{RESULTS_DIR}/security_audit.json") as f:
            audit = json.load(f)
        d = audit["fscb_deniability"]
        expected = d["confirmed_free"] / d["unknown_pages"]
        assert abs(d["deniability_ratio"] - expected) < 1e-6


# ── Tests: FSCB Differential ───────────────────────────────────────────────
class TestFSCBDifferential:
    def test_section_exists(self):
        with open(f"{RESULTS_DIR}/security_audit.json") as f:
            audit = json.load(f)
        assert "fscb_differential" in audit

    def test_transitioned_count(self, fscb_differential_truth):
        with open(f"{RESULTS_DIR}/security_audit.json") as f:
            audit = json.load(f)
        assert audit["fscb_differential"]["transitioned_from_free"] == (
            fscb_differential_truth["transitioned"]
        )

    def test_attributable_count(self, fscb_differential_truth):
        with open(f"{RESULTS_DIR}/security_audit.json") as f:
            audit = json.load(f)
        assert audit["fscb_differential"]["attributable_to_known_bases"] == (
            fscb_differential_truth["attributable"]
        )

    def test_unattributable_count(self, fscb_differential_truth):
        with open(f"{RESULTS_DIR}/security_audit.json") as f:
            audit = json.load(f)
        assert audit["fscb_differential"]["unattributable_transitions"] == (
            fscb_differential_truth["unattributable"]
        )

    def test_leaked_activity(self, fscb_differential_truth):
        with open(f"{RESULTS_DIR}/security_audit.json") as f:
            audit = json.load(f)
        assert audit["fscb_differential"]["leaked_hidden_activity"] == (
            fscb_differential_truth["leaked"]
        )
