
"""
Tests for DNS exfiltration forensics task.

Validates the agent's results.json against expected answers.
Expected values use SHA256 hashes of domain names for anti-cheat:
the test never reveals the exfiltration domain names directly.
"""
import json
import hashlib
import os
import pytest


RESULTS_PATH = "/app/results.json"

# Anti-cheat: expected domain names are stored as SHA256(domain_name)
# The test verifies the agent found the right domains without revealing them.
EXPECTED_DOMAIN_HASHES = {
    "0c3891f43aad0ac7a2347714f119dcbb41206c62c77464540547fa2646e1713c",
    "5c3f7a6d029f8f15bcef5ae4de0fdaae1f75850d9e53a55abb546ffe8e4aed57",
    "a15643d16beb8e69a880eaf54e5eda7179df64ca3275b0f959692520ae1160e2",
}

# Expected SHA256 of decoded data, keyed by SHA256(domain_name)
EXPECTED_DATA_SHA256 = {
    "0c3891f43aad0ac7a2347714f119dcbb41206c62c77464540547fa2646e1713c":
        "4882da5c0094dfcf52427b108049af0ad8186c479b79775e5854244bd8f587dd",
    "5c3f7a6d029f8f15bcef5ae4de0fdaae1f75850d9e53a55abb546ffe8e4aed57":
        "604172008ebcf3ce94316b55f7312a1e734369ef3178489d59e7f46518c52b99",
    "a15643d16beb8e69a880eaf54e5eda7179df64ca3275b0f959692520ae1160e2":
        "2eff2f742ae057c108123c79aed2dc5d6c46123f1f6ca79c81bf7feff1e7baaa",
}

# Expected XOR key hash (anti-cheat: stored as SHA256 of the hex string)
EXPECTED_XOR_KEY_HASH = hashlib.sha256(b"5a3c7f").hexdigest()


@pytest.fixture
def results():
    """Load the agent's results file."""
    assert os.path.exists(RESULTS_PATH), (
        f"Results file not found at {RESULTS_PATH}. "
        "The agent must write results.json to /app/results.json"
    )
    with open(RESULTS_PATH, 'r') as f:
        data = json.load(f)
    return data


def test_results_has_required_keys(results):
    """Verify results.json has all required top-level keys."""
    assert "exfil_domains" in results, "Missing 'exfil_domains' key"
    assert "decoded_data_sha256" in results, "Missing 'decoded_data_sha256' key"
    assert "xor_key_hex" in results, "Missing 'xor_key_hex' key"


def test_exfil_domains_count(results):
    """Verify exactly 3 exfiltration domains were identified."""
    domains = results["exfil_domains"]
    assert isinstance(domains, list), "'exfil_domains' must be a list"
    assert len(domains) == 3, (
        f"Expected exactly 3 exfiltration domains, got {len(domains)}"
    )


def test_exfil_domains_correct(results):
    """Verify the correct exfiltration domains were identified."""
    submitted_hashes = {
        hashlib.sha256(d.strip().lower().encode()).hexdigest()
        for d in results["exfil_domains"]
    }
    assert submitted_hashes == EXPECTED_DOMAIN_HASHES, (
        "Identified exfiltration domains do not match expected domains"
    )


def test_decoded_data_sha256_all_present(results):
    """Verify decoded data SHA256 is provided for each exfil domain."""
    sha256_map = results["decoded_data_sha256"]
    assert isinstance(sha256_map, dict), "'decoded_data_sha256' must be a dict"
    for domain in results["exfil_domains"]:
        assert domain in sha256_map or domain.strip().lower() in sha256_map, (
            f"Missing decoded_data_sha256 entry for domain: {domain}"
        )


def test_decoded_data_sha256_correct(results):
    """Verify each decoded data SHA256 matches expected values."""
    sha256_map = results["decoded_data_sha256"]
    for domain_raw, submitted_hash in sha256_map.items():
        domain = domain_raw.strip().lower()
        domain_hash = hashlib.sha256(domain.encode()).hexdigest()
        if domain_hash not in EXPECTED_DATA_SHA256:
            continue  # Skip domains not in our expected set
        expected_hash = EXPECTED_DATA_SHA256[domain_hash]
        assert submitted_hash.strip().lower() == expected_hash, (
            f"Decoded data SHA256 mismatch for domain '{domain}': "
            f"got {submitted_hash.strip().lower()}, expected {expected_hash}"
        )


def test_all_expected_domains_have_correct_hashes(results):
    """Verify all 3 expected domains have correct decoded data hashes."""
    sha256_map = {
        k.strip().lower(): v.strip().lower()
        for k, v in results["decoded_data_sha256"].items()
    }
    matched = 0
    for domain, submitted_hash in sha256_map.items():
        domain_hash = hashlib.sha256(domain.encode()).hexdigest()
        if domain_hash in EXPECTED_DATA_SHA256:
            expected = EXPECTED_DATA_SHA256[domain_hash]
            if submitted_hash == expected:
                matched += 1
    assert matched == 3, (
        f"Only {matched}/3 domains have correct decoded data SHA256 hashes"
    )


def test_xor_key(results):
    """Verify the XOR key is correct."""
    submitted_key = results["xor_key_hex"].strip().lower()
    submitted_key_hash = hashlib.sha256(submitted_key.encode()).hexdigest()
    assert submitted_key_hash == EXPECTED_XOR_KEY_HASH, (
        f"XOR key mismatch: submitted '{submitted_key}' does not match expected"
    )
