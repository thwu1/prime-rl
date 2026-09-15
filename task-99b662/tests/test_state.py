
import base64
import hashlib
import json
import os
import pytest


# === DER parsing helpers ===

def parse_der_length(data, offset):
    if data[offset] < 0x80:
        return data[offset], offset + 1
    num_bytes = data[offset] & 0x7f
    offset += 1
    length = int.from_bytes(data[offset:offset + num_bytes], 'big')
    return length, offset + num_bytes


def parse_der_integer(data, offset):
    assert data[offset] == 0x02, f"Expected INTEGER tag 0x02 at offset {offset}, got {data[offset]:#x}"
    offset += 1
    length, offset = parse_der_length(data, offset)
    value = int.from_bytes(data[offset:offset + length], 'big')
    return value, offset + length


def parse_der_sequence_start(data, offset):
    assert data[offset] == 0x30, f"Expected SEQUENCE tag 0x30 at offset {offset}, got {data[offset]:#x}"
    offset += 1
    length, offset = parse_der_length(data, offset)
    return length, offset


def skip_der_element(data, offset):
    """Skip any DER element, return offset past it."""
    offset += 1  # skip tag
    length, offset = parse_der_length(data, offset)
    return offset + length


def parse_sig_der(data):
    """Parse DER DSA-Sig-Value: SEQUENCE { INTEGER r, INTEGER s }."""
    _, offset = parse_der_sequence_start(data, 0)
    r, offset = parse_der_integer(data, offset)
    s, offset = parse_der_integer(data, offset)
    return r, s


def parse_pem_der(pem_text):
    """Extract DER bytes from PEM text."""
    lines = pem_text.strip().split('\n')
    b64_lines = []
    in_body = False
    for line in lines:
        if line.startswith('-----BEGIN'):
            in_body = True
            continue
        if line.startswith('-----END'):
            break
        if in_body:
            b64_lines.append(line.strip())
    return base64.b64decode(''.join(b64_lines))


def parse_dsa_params_pem(pem_text):
    """Parse DSA PARAMETERS PEM -> (p, q, g)."""
    der = parse_pem_der(pem_text)
    _, offset = parse_der_sequence_start(der, 0)
    p_val, offset = parse_der_integer(der, offset)
    q_val, offset = parse_der_integer(der, offset)
    g_val, offset = parse_der_integer(der, offset)
    return p_val, q_val, g_val


def parse_dsa_pubkey_pem(pem_text):
    """Parse SubjectPublicKeyInfo PEM -> y value."""
    der = parse_pem_der(pem_text)
    # SEQUENCE { SEQUENCE { OID, SEQUENCE{p,q,g} }, BIT STRING { INTEGER y } }
    _, offset = parse_der_sequence_start(der, 0)
    # Skip AlgorithmIdentifier SEQUENCE
    offset_after_algo = skip_der_element(der, offset)
    # BIT STRING
    assert der[offset_after_algo] == 0x03, "Expected BIT STRING tag"
    offset_after_algo += 1
    bs_length, offset_bs = parse_der_length(der, offset_after_algo)
    assert der[offset_bs] == 0x00, "Expected 0 unused bits"
    y_val, _ = parse_der_integer(der, offset_bs + 1)
    return y_val


def parse_dsa_privkey_pem(pem_text):
    """Parse traditional DSA private key PEM -> (version, p, q, g, y, x)."""
    der = parse_pem_der(pem_text)
    _, offset = parse_der_sequence_start(der, 0)
    version, offset = parse_der_integer(der, offset)
    p_val, offset = parse_der_integer(der, offset)
    q_val, offset = parse_der_integer(der, offset)
    g_val, offset = parse_der_integer(der, offset)
    y_val, offset = parse_der_integer(der, offset)
    x_val, offset = parse_der_integer(der, offset)
    return version, p_val, q_val, g_val, y_val, x_val


# === Load challenge data ===

with open("/app/data/params.pem") as f:
    p, q, g = parse_dsa_params_pem(f.read())

PUB_KEYS = {}
for kid in ["alpha", "beta", "gamma"]:
    with open(f"/app/data/keys/{kid}.pub.pem") as f:
        PUB_KEYS[kid] = parse_dsa_pubkey_pem(f.read())

with open("/app/data/challenges.json") as f:
    CHALLENGES = json.load(f)


# === Crypto helpers ===

def modinv(a, m):
    a = a % m
    g_val, x = m, 0
    b, y = a, 1
    while b > 0:
        quo = g_val // b
        g_val, b = b, g_val - quo * b
        x, y = y, x - quo * y
    if g_val != 1:
        raise ValueError("No modular inverse")
    return x % m


def sha1_int(msg):
    return int(hashlib.sha1(msg.encode("utf-8")).hexdigest(), 16)


def dsa_verify(h, r, s, y):
    if not (0 < r < q and 0 < s < q):
        return False
    w = modinv(s, q)
    u1 = (h * w) % q
    u2 = (r * w) % q
    v = (pow(g, u1, p) * pow(y, u2, p)) % p % q
    return v == r


# === Fixtures ===

@pytest.fixture(scope="module")
def results():
    path = "/app/results/results.json"
    assert os.path.exists(path), "results.json not found at /app/results/results.json"
    with open(path) as f:
        return json.load(f)


# === Test Classes ===

class TestResultsStructure:
    def test_results_file_exists(self):
        assert os.path.exists("/app/results/results.json"), "results.json must exist"

    def test_has_recovered_keys(self, results):
        assert "recovered_private_keys" in results, "Missing 'recovered_private_keys'"

    def test_has_forged_signatures(self, results):
        assert "forged_signatures" in results, "Missing 'forged_signatures'"

    def test_all_key_ids_present(self, results):
        for kid in ["alpha", "beta", "gamma"]:
            assert kid in results["recovered_private_keys"], f"Missing key: {kid}"

    def test_all_challenges_present(self, results):
        forged_ids = {s["challenge_id"] for s in results["forged_signatures"]}
        for ch in CHALLENGES:
            assert ch["challenge_id"] in forged_ids, (
                f"Missing forged sig for challenge_id={ch['challenge_id']}"
            )


class TestRecoveredPrivateKeys:
    def test_alpha_key_valid(self, results):
        x = int(results["recovered_private_keys"]["alpha"], 16)
        assert 0 < x < q, "Alpha private key out of range"
        assert pow(g, x, p) == PUB_KEYS["alpha"], "Alpha: g^x mod p != y"

    def test_beta_key_valid(self, results):
        x = int(results["recovered_private_keys"]["beta"], 16)
        assert 0 < x < q, "Beta private key out of range"
        assert pow(g, x, p) == PUB_KEYS["beta"], "Beta: g^x mod p != y"

    def test_gamma_key_valid(self, results):
        x = int(results["recovered_private_keys"]["gamma"], 16)
        assert 0 < x < q, "Gamma private key out of range"
        assert pow(g, x, p) == PUB_KEYS["gamma"], "Gamma: g^x mod p != y"


class TestPEMPrivateKeys:
    """Verify recovered private keys are valid traditional OpenSSL DSA PEM files."""

    def _check_pem_key(self, kid):
        path = f"/app/results/{kid}.priv.pem"
        assert os.path.exists(path), f"{kid}.priv.pem not found"

        with open(path) as f:
            content = f.read()

        assert "-----BEGIN DSA PRIVATE KEY-----" in content, \
            f"Missing BEGIN DSA PRIVATE KEY header in {kid}.priv.pem"
        assert "-----END DSA PRIVATE KEY-----" in content, \
            f"Missing END DSA PRIVATE KEY footer in {kid}.priv.pem"

        version, p_pem, q_pem, g_pem, y_pem, x_pem = parse_dsa_privkey_pem(content)
        assert version == 0, "PEM version must be 0"
        assert p_pem == p, "PEM p parameter mismatch"
        assert q_pem == q, "PEM q parameter mismatch"
        assert g_pem == g, "PEM g parameter mismatch"
        assert 0 < x_pem < q, f"Private key x out of range for {kid}"
        assert pow(g, x_pem, p) == PUB_KEYS[kid], f"g^x mod p != y for {kid}"
        assert y_pem == PUB_KEYS[kid], f"PEM y doesn't match public key for {kid}"

    def test_alpha_pem(self):
        self._check_pem_key("alpha")

    def test_beta_pem(self):
        self._check_pem_key("beta")

    def test_gamma_pem(self):
        self._check_pem_key("gamma")


class TestForgedSignaturesJSON:
    def _verify_challenge(self, results, challenge_id):
        ch = next(c for c in CHALLENGES if c["challenge_id"] == challenge_id)
        sig = next(s for s in results["forged_signatures"]
                   if s["challenge_id"] == challenge_id)
        h = sha1_int(ch["message"])
        r = int(sig["r"], 16)
        s = int(sig["s"], 16)
        y = PUB_KEYS[ch["target_key"]]
        assert 0 < r < q, f"Challenge {challenge_id}: r out of range"
        assert 0 < s < q, f"Challenge {challenge_id}: s out of range"
        assert dsa_verify(h, r, s, y), (
            f"Challenge {challenge_id}: forged sig failed DSA verify against '{ch['target_key']}'"
        )

    def test_challenge_0(self, results):
        self._verify_challenge(results, 0)

    def test_challenge_1(self, results):
        self._verify_challenge(results, 1)

    def test_challenge_2(self, results):
        self._verify_challenge(results, 2)


class TestDERForgedSignatures:
    """Verify forged signatures exist as valid DER-encoded files."""

    def _check_der_sig(self, challenge_id):
        path = f"/app/results/forged_{challenge_id}.der"
        assert os.path.exists(path), f"forged_{challenge_id}.der not found"

        with open(path, "rb") as f:
            der_data = f.read()

        assert len(der_data) > 0, f"forged_{challenge_id}.der is empty"
        assert der_data[0] == 0x30, "DER must start with SEQUENCE tag (0x30)"

        r, s = parse_sig_der(der_data)

        ch = next(c for c in CHALLENGES if c["challenge_id"] == challenge_id)
        h = sha1_int(ch["message"])
        y = PUB_KEYS[ch["target_key"]]

        assert 0 < r < q, f"DER sig r out of range for challenge {challenge_id}"
        assert 0 < s < q, f"DER sig s out of range for challenge {challenge_id}"
        assert dsa_verify(h, r, s, y), (
            f"DER forged sig failed verification for challenge {challenge_id}"
        )

    def test_der_challenge_0(self):
        self._check_der_sig(0)

    def test_der_challenge_1(self):
        self._check_der_sig(1)

    def test_der_challenge_2(self):
        self._check_der_sig(2)


class TestPEMAndJSONConsistency:
    """Verify PEM private keys match the hex values in results.json."""

    def _check_consistency(self, results, kid):
        json_x = int(results["recovered_private_keys"][kid], 16)

        path = f"/app/results/{kid}.priv.pem"
        assert os.path.exists(path), f"{kid}.priv.pem not found for consistency check"
        with open(path) as f:
            _, _, _, _, _, pem_x = parse_dsa_privkey_pem(f.read())

        assert json_x == pem_x, f"PEM and JSON private key values differ for {kid}"

    def test_alpha_consistency(self, results):
        self._check_consistency(results, "alpha")

    def test_beta_consistency(self, results):
        self._check_consistency(results, "beta")

    def test_gamma_consistency(self, results):
        self._check_consistency(results, "gamma")


class TestDERAndJSONConsistency:
    """Verify DER forged signatures match values in results.json."""

    def _check_consistency(self, results, challenge_id):
        sig_json = next(s for s in results["forged_signatures"]
                        if s["challenge_id"] == challenge_id)
        json_r = int(sig_json["r"], 16)
        json_s = int(sig_json["s"], 16)

        path = f"/app/results/forged_{challenge_id}.der"
        assert os.path.exists(path), f"forged_{challenge_id}.der not found"
        with open(path, "rb") as f:
            der_r, der_s = parse_sig_der(f.read())

        assert json_r == der_r, f"DER and JSON r values differ for challenge {challenge_id}"
        assert json_s == der_s, f"DER and JSON s values differ for challenge {challenge_id}"

    def test_challenge_0_consistency(self, results):
        self._check_consistency(results, 0)

    def test_challenge_1_consistency(self, results):
        self._check_consistency(results, 1)

    def test_challenge_2_consistency(self, results):
        self._check_consistency(results, 2)
