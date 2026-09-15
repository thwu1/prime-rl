
import json
import os
import pytest


def from_base35(s: str) -> int:
    """Convert a base-35 string to integer (digits 0-9, letters a-y)."""
    result = 0
    for c in s:
        result *= 35
        if "0" <= c <= "9":
            result += ord(c) - ord("0")
        elif "a" <= c <= "y":
            result += ord(c) - ord("a") + 10
        else:
            raise ValueError(f"Invalid base-35 character: {c}")
    return result


# Deterministic Miller-Rabin with fixed witnesses (sufficient for numbers up to ~3000 bits)
_MR_WITNESSES = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59, 61, 67, 71]


def is_probable_prime(n: int) -> bool:
    if n < 2:
        return False
    for p in _MR_WITNESSES:
        if n == p:
            return True
        if n % p == 0:
            return False
    r, d = 0, n - 1
    while d % 2 == 0:
        r += 1
        d //= 2
    for a in _MR_WITNESSES:
        x = pow(a, d, n)
        if x == 1 or x == n - 1:
            continue
        for _ in range(r - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


@pytest.fixture(scope="module")
def challenge():
    with open("/app/challenge/challenge.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def answer():
    assert os.path.isfile("/app/answer.json"), "answer.json not found at /app/answer.json"
    with open("/app/answer.json") as f:
        return json.load(f)


class TestPart1Factoring:
    """Verify Coppersmith partial factoring of RSA modulus."""

    def test_factors_exist(self, answer):
        assert "part1_p" in answer, "Missing part1_p in answer.json"
        assert "part1_q" in answer, "Missing part1_q in answer.json"

    def test_product_equals_N(self, challenge, answer):
        N = int(challenge["part1_factoring"]["N"])
        p = int(answer["part1_p"])
        q = int(answer["part1_q"])
        assert p * q == N, f"p * q != N"

    def test_factors_nontrivial(self, answer):
        p = int(answer["part1_p"])
        q = int(answer["part1_q"])
        assert p > 1, "p must be > 1"
        assert q > 1, "q must be > 1"

    def test_factors_prime(self, answer):
        p = int(answer["part1_p"])
        q = int(answer["part1_q"])
        assert is_probable_prime(p), "p is not prime"
        assert is_probable_prime(q), "q is not prime"


class TestPart2StereotypedMessage:
    """Verify Coppersmith stereotyped message recovery."""

    def test_suffix_exists(self, answer):
        assert "part2_suffix" in answer, "Missing part2_suffix in answer.json"

    def test_suffix_length(self, challenge, answer):
        expected_len = challenge["part2_stereotyped_message"]["unknown_suffix_length"]
        suffix = answer["part2_suffix"]
        assert len(suffix) == expected_len, (
            f"Suffix length {len(suffix)} != expected {expected_len}"
        )

    def test_suffix_valid_base35(self, answer):
        suffix = answer["part2_suffix"]
        valid = set("0123456789abcdefghijklmnopqrstuvwxy")
        for c in suffix:
            assert c in valid, f"Invalid base-35 character in suffix: {c}"

    def test_encryption_matches(self, challenge, answer):
        ch = challenge["part2_stereotyped_message"]
        N = int(ch["N"])
        e = ch["e"]
        c = int(ch["ciphertext"])
        prefix = ch["known_prefix_base35"]
        suffix = answer["part2_suffix"]
        full_message = from_base35(prefix + suffix)
        computed_c = pow(full_message, e, N)
        assert computed_c == c, "Encrypting (prefix + suffix)^e mod N does not match ciphertext"


class TestPart3HastadBroadcast:
    """Verify Hastad broadcast attack with linear padding."""

    def test_message_exists(self, answer):
        assert "part3_message" in answer, "Missing part3_message in answer.json"

    def test_message_positive(self, answer):
        m = int(answer["part3_message"])
        assert m > 0, "Message must be positive"

    def test_message_bit_length(self, answer):
        m = int(answer["part3_message"])
        assert m.bit_length() <= 300, f"Message has {m.bit_length()} bits, expected <= 300"

    def test_all_instances_match(self, challenge, answer):
        m = int(answer["part3_message"])
        for i, inst in enumerate(challenge["part3_hastad_broadcast"]["instances"]):
            N_i = int(inst["N"])
            b_i = int(inst["b"])
            c_i = int(inst["c"])
            computed = pow(m + b_i, 3, N_i)
            assert computed == c_i, (
                f"Instance {i}: (m + b_{i})^3 mod N_{i} does not match c_{i}"
            )
