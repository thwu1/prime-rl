
"""
Verify the ACVP CTR-DRBG response by checking SHA-256 hashes of returned bits.
Hashes are pre-computed from NIST ACVP reference test vectors and cannot be
reversed to obtain expected output.
"""

import hashlib
import json
import os
import pytest


# SHA-256 hashes of the raw bytes of each expected returnedBits value.
# Keyed by (tgId, tcId).
EXPECTED_HASHES = {
    (1, 1): "0f886d482597df95440c0c48a5ab720946e2183baf5de42289cd240318ae5036",
    (1, 2): "dbab51f30315f820371e2e14283a3ac58dbf557dceda3a2e9ca756e213843fa4",
    (1, 3): "249408c4fe008675faa6e9209d27064036b2f153dd9150c52aadb65d5d0173ea",
    (7, 91): "ddb6fd74890df6e01cfaf5e065d185ec5c3bd7ef7d98a703f540c293cd0d3799",
    (7, 92): "ee7efcf3da049bdf219e295c71a7da18070876106c232959f155251eadd1b445",
    (7, 93): "33f4f7f5cc4f7b35463ba391a2ac16f12d36709d51e63120ab4d20653b9e773e",
    (9, 121): "4cbb9e62a8e93ab9a527e563ff7166d12d0e40c8205e6b5722e6271b765a7fde",
    (9, 122): "2c334c35abba589425ca31493561331fd5cd3be8c7ef389d172b239b09ad2771",
    (9, 123): "c58329c8e02a27ab8052efb12079c8b768d56ee3e54bce5a01b9b6530116fd19",
    (15, 211): "4267e1e09715ad94597b1eeb96e0b07b1d83c5f4eb688164b6e12b3771057779",
    (15, 212): "21b9a1010a5b841b194d29591f7050f2151a5fcfe874e198dfef366046cca4c9",
    (15, 213): "cb9cdeca4ecd879a64868cbff1585eae2eb4a3c4d07dd331376bac2cf70fa588",
}


@pytest.fixture(scope="module")
def response():
    path = "/app/response.json"
    assert os.path.exists(path), f"Response file not found at {path}"
    with open(path) as f:
        return json.load(f)


def test_response_structure(response):
    """Verify the response JSON has the correct top-level structure."""
    assert "vsId" in response, "Missing vsId"
    assert response["vsId"] == 42, f"Wrong vsId: {response['vsId']}"
    assert "testGroups" in response, "Missing testGroups"
    assert len(response["testGroups"]) == 4, (
        f"Expected 4 test groups, got {len(response['testGroups'])}"
    )


def test_all_test_groups_present(response):
    """Verify all expected test group IDs are present."""
    tg_ids = {tg["tgId"] for tg in response["testGroups"]}
    expected_tg_ids = {1, 7, 9, 15}
    assert tg_ids == expected_tg_ids, (
        f"Expected test group IDs {expected_tg_ids}, got {tg_ids}"
    )


def test_all_test_cases_present(response):
    """Verify all expected test case IDs are present in each group."""
    expected_tc_ids = {
        1: {1, 2, 3},
        7: {91, 92, 93},
        9: {121, 122, 123},
        15: {211, 212, 213},
    }
    for tg in response["testGroups"]:
        tg_id = tg["tgId"]
        tc_ids = {tc["tcId"] for tc in tg["tests"]}
        assert tc_ids == expected_tc_ids[tg_id], (
            f"tgId={tg_id}: expected tcIds {expected_tc_ids[tg_id]}, got {tc_ids}"
        )


def _check_returned_bits(response, tg_id, tc_id):
    """Helper: verify a single test case's returnedBits against its SHA-256 hash."""
    for tg in response["testGroups"]:
        if tg["tgId"] != tg_id:
            continue
        for tc in tg["tests"]:
            if tc["tcId"] != tc_id:
                continue
            rb_hex = tc["returnedBits"]
            # Normalize to uppercase hex, strip whitespace
            rb_hex = rb_hex.strip().upper()
            # Verify it's valid hex
            try:
                rb_bytes = bytes.fromhex(rb_hex)
            except ValueError:
                pytest.fail(
                    f"tgId={tg_id} tcId={tc_id}: returnedBits is not valid hex"
                )
            actual_hash = hashlib.sha256(rb_bytes).hexdigest()
            expected_hash = EXPECTED_HASHES[(tg_id, tc_id)]
            assert actual_hash == expected_hash, (
                f"tgId={tg_id} tcId={tc_id}: returnedBits hash mismatch. "
                f"Got {actual_hash[:16]}..., expected {expected_hash[:16]}..."
            )
            return
    pytest.fail(f"tgId={tg_id} tcId={tc_id} not found in response")


# AES-128 with derivation function, prediction resistance
def test_tg1_tc1(response):
    _check_returned_bits(response, 1, 1)

def test_tg1_tc2(response):
    _check_returned_bits(response, 1, 2)

def test_tg1_tc3(response):
    _check_returned_bits(response, 1, 3)

# AES-256 without derivation function, prediction resistance
def test_tg7_tc91(response):
    _check_returned_bits(response, 7, 91)

def test_tg7_tc92(response):
    _check_returned_bits(response, 7, 92)

def test_tg7_tc93(response):
    _check_returned_bits(response, 7, 93)

# AES-128 with derivation function, explicit reseed
def test_tg9_tc121(response):
    _check_returned_bits(response, 9, 121)

def test_tg9_tc122(response):
    _check_returned_bits(response, 9, 122)

def test_tg9_tc123(response):
    _check_returned_bits(response, 9, 123)

# AES-256 without derivation function, explicit reseed
def test_tg15_tc211(response):
    _check_returned_bits(response, 15, 211)

def test_tg15_tc212(response):
    _check_returned_bits(response, 15, 212)

def test_tg15_tc213(response):
    _check_returned_bits(response, 15, 213)
