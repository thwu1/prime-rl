
import json
import os
import random


RESULTS_PATH = "/app/results.json"
KEYS_PATH = "/app/keys.json"

# Ground truth: which keys are ROCA-vulnerable and their factorizations
# key_0: ROCA-vulnerable
# key_1: ROCA-vulnerable
# key_2: normal (not vulnerable)
# key_3: normal
# key_4: ROCA-vulnerable
# key_5: ROCA-vulnerable
# key_6: normal
# key_7: normal

GROUND_TRUTH = {
    "key_0": {
        "vulnerable": True,
        "p": 973375265664584233948243132246055919821555930260490327299687588838647823,
        "q": 1023457376307011973315959935087524168934603578996244094670733589503924771,
    },
    "key_1": {
        "vulnerable": True,
        "p": 657452197375017743028260865357898671087323779360819050793016597644657613,
        "q": 2260910034998731726225428369714027065425247632377439087126495418511530659,
    },
    "key_2": {
        "vulnerable": False,
    },
    "key_3": {
        "vulnerable": False,
    },
    "key_4": {
        "vulnerable": True,
        "p": 1430987773847470337133973913233168030647181879199823957956455388883479447,
        "q": 1340897994994010135561588290807741037406958770576577598012090869882276283,
    },
    "key_5": {
        "vulnerable": True,
        "p": 711206469444112063034080927666708509637874950237742164781602315380609769,
        "q": 1943439167668926704300383430022727545400713186655977501503677103578175423,
    },
    "key_6": {
        "vulnerable": False,
    },
    "key_7": {
        "vulnerable": False,
    },
}


def is_prime_miller_rabin(n, k=30):
    """Miller-Rabin primality test."""
    if n < 2:
        return False
    if n == 2 or n == 3:
        return True
    if n % 2 == 0:
        return False
    r, d = 0, n - 1
    while d % 2 == 0:
        r += 1
        d //= 2
    rng = random.Random(42)
    for _ in range(k):
        a = rng.randrange(2, n - 1)
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


def test_results_file_exists():
    """results.json must exist."""
    assert os.path.isfile(RESULTS_PATH), f"Missing {RESULTS_PATH}"


def test_results_valid_json():
    """results.json must be valid JSON."""
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    assert isinstance(data, dict), "results.json root must be a JSON object"


def test_all_keys_present():
    """All 8 keys must be present in results."""
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    for kid in [f"key_{i}" for i in range(8)]:
        assert kid in data, f"Missing key {kid} in results"


def test_vulnerable_keys_identified():
    """All ROCA-vulnerable keys must be correctly flagged."""
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    for kid, gt in GROUND_TRUTH.items():
        assert kid in data, f"Missing {kid}"
        entry = data[kid]
        assert "vulnerable" in entry, f"{kid} missing 'vulnerable' field"
        assert entry["vulnerable"] == gt["vulnerable"], (
            f"{kid}: expected vulnerable={gt['vulnerable']}, got {entry['vulnerable']}"
        )


def test_factorizations_correct():
    """For each vulnerable key, p*q must equal n and both must be prime."""
    with open(KEYS_PATH) as f:
        keys = {k["id"]: int(k["n"], 16) for k in json.load(f)}
    with open(RESULTS_PATH) as f:
        data = json.load(f)

    for kid, gt in GROUND_TRUTH.items():
        if not gt["vulnerable"]:
            continue
        entry = data[kid]
        assert "p" in entry and "q" in entry, f"{kid}: missing p or q"
        p_val = entry["p"]
        q_val = entry["q"]
        assert p_val is not None, f"{kid}: p is None"
        assert q_val is not None, f"{kid}: q is None"
        p = int(p_val)
        q = int(q_val)
        n = keys[kid]
        assert p * q == n, f"{kid}: p*q != n"
        assert p > 1 and q > 1, f"{kid}: trivial factor"
        assert is_prime_miller_rabin(p), f"{kid}: p is not prime"
        assert is_prime_miller_rabin(q), f"{kid}: q is not prime"


def test_no_false_positives():
    """Non-vulnerable keys must not be marked vulnerable."""
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    for kid, gt in GROUND_TRUTH.items():
        if gt["vulnerable"]:
            continue
        entry = data[kid]
        assert not entry.get("vulnerable", False), (
            f"{kid}: incorrectly marked as vulnerable"
        )
