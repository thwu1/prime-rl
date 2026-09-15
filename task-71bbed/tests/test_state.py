
import subprocess
import os
import json
import pytest

CRACKME_ALPHA = '/app/crackme_alpha'
CRACKME_BETA = '/app/crackme_beta'
VM_RUNNER = '/app/vm_runner'
KEYGEN_ALPHA = '/app/keygen_alpha.py'
KEYGEN_BETA = '/app/keygen_beta.py'
KEYGEN_UNIVERSAL = '/app/keygen_universal.py'
KEYGEN_GAMMA = '/app/keygen_gamma.py'
GAMMA_BC = '/app/gamma.bc'
GAMMA_KEY = '/app/gamma_key.bin'
AUDIT = '/app/audit.json'

TEST_USERNAMES = [
    'admin',
    'test',
    'reverser2024',
    'hello_world',
    'x',
]


# --------------- helpers ---------------

def _run_keygen(keygen_path, *args):
    result = subprocess.run(
        ['python3', keygen_path] + list(args),
        capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, \
        f"Keygen {keygen_path} failed with args {args}: {result.stderr}"
    serial = result.stdout.strip()
    assert len(serial) > 0, "Keygen produced empty output"
    int(serial, 16)
    return serial


def _verify_serial(binary, username, serial):
    result = subprocess.run(
        [binary, username, serial],
        capture_output=True, text=True, timeout=10
    )
    return 'ACCESS GRANTED' in result.stdout


def _verify_gamma_serial(username, serial):
    result = subprocess.run(
        [VM_RUNNER, GAMMA_BC, GAMMA_KEY, username, serial],
        capture_output=True, text=True, timeout=10
    )
    return 'ACCESS GRANTED' in result.stdout


# --------------- existence checks ---------------

def test_binaries_exist():
    for path in [CRACKME_ALPHA, CRACKME_BETA, VM_RUNNER]:
        assert os.path.isfile(path), f"Binary not found at {path}"
        assert os.access(path, os.X_OK), f"{path} is not executable"


def test_keygen_alpha_exists():
    assert os.path.isfile(KEYGEN_ALPHA)


def test_keygen_beta_exists():
    assert os.path.isfile(KEYGEN_BETA)


def test_keygen_universal_exists():
    assert os.path.isfile(KEYGEN_UNIVERSAL)


def test_keygen_gamma_exists():
    assert os.path.isfile(KEYGEN_GAMMA)


def test_gamma_files_exist():
    assert os.path.isfile(GAMMA_BC), f"Bytecode not found at {GAMMA_BC}"
    assert os.path.isfile(GAMMA_KEY), f"Key not found at {GAMMA_KEY}"


def test_gamma_key_size():
    sz = os.path.getsize(GAMMA_KEY)
    assert sz == 4, f"gamma_key.bin must be exactly 4 bytes, got {sz}"


def test_gamma_bytecode_nontrivial():
    sz = os.path.getsize(GAMMA_BC)
    assert sz >= 60, \
        f"gamma.bc is only {sz} bytes — too small for a real VM program"


def test_audit_exists():
    assert os.path.isfile(AUDIT)


# --------------- alpha keygen ---------------

@pytest.mark.parametrize("username", TEST_USERNAMES)
def test_keygen_alpha_produces_valid_serial(username):
    serial = _run_keygen(KEYGEN_ALPHA, username)
    assert _verify_serial(CRACKME_ALPHA, username, serial), \
        f"Serial '{serial}' rejected by crackme_alpha for '{username}'"


def test_alpha_keygen_different_serials():
    serials = set()
    for username in TEST_USERNAMES:
        serials.add(_run_keygen(KEYGEN_ALPHA, username))
    assert len(serials) == len(TEST_USERNAMES)


def test_alpha_rejects_wrong_serial():
    result = subprocess.run(
        [CRACKME_ALPHA, 'admin', '0'],
        capture_output=True, text=True, timeout=10
    )
    assert 'ACCESS DENIED' in result.stdout


# --------------- beta keygen ---------------

@pytest.mark.parametrize("username", TEST_USERNAMES)
def test_keygen_beta_produces_valid_serial(username):
    serial = _run_keygen(KEYGEN_BETA, username)
    assert _verify_serial(CRACKME_BETA, username, serial), \
        f"Serial '{serial}' rejected by crackme_beta for '{username}'"


def test_beta_keygen_different_serials():
    serials = set()
    for username in TEST_USERNAMES:
        serials.add(_run_keygen(KEYGEN_BETA, username))
    assert len(serials) == len(TEST_USERNAMES)


def test_beta_rejects_wrong_serial():
    result = subprocess.run(
        [CRACKME_BETA, 'admin', '0'],
        capture_output=True, text=True, timeout=10
    )
    assert 'ACCESS DENIED' in result.stdout


# --------------- cross rejection (alpha / beta) ---------------

def test_cross_rejection():
    alpha_serial = _run_keygen(KEYGEN_ALPHA, 'admin')
    beta_serial = _run_keygen(KEYGEN_BETA, 'admin')
    assert alpha_serial != beta_serial
    assert not _verify_serial(CRACKME_ALPHA, 'admin', beta_serial)
    assert not _verify_serial(CRACKME_BETA, 'admin', alpha_serial)


# --------------- universal keygen ---------------

@pytest.mark.parametrize("binary,username", [
    (CRACKME_ALPHA, 'admin'),
    (CRACKME_ALPHA, 'reverser2024'),
    (CRACKME_ALPHA, 'x'),
    (CRACKME_BETA, 'admin'),
    (CRACKME_BETA, 'reverser2024'),
    (CRACKME_BETA, 'x'),
])
def test_universal_keygen(binary, username):
    serial = _run_keygen(KEYGEN_UNIVERSAL, binary, username)
    assert _verify_serial(binary, username, serial)


def test_universal_keygen_matches_specific():
    for binary, specific in [
        (CRACKME_ALPHA, KEYGEN_ALPHA),
        (CRACKME_BETA, KEYGEN_BETA),
    ]:
        uni = _run_keygen(KEYGEN_UNIVERSAL, binary, 'test')
        spec = _run_keygen(specific, 'test')
        assert uni == spec, f"Universal ({uni}) != specific ({spec})"


# --------------- gamma keygen ---------------

@pytest.mark.parametrize("username", TEST_USERNAMES)
def test_keygen_gamma_produces_valid_serial(username):
    serial = _run_keygen(KEYGEN_GAMMA, username)
    assert _verify_gamma_serial(username, serial), \
        f"Serial '{serial}' rejected by vm_runner for '{username}'"


def test_gamma_different_serials():
    serials = set()
    for username in TEST_USERNAMES:
        serials.add(_run_keygen(KEYGEN_GAMMA, username))
    assert len(serials) == len(TEST_USERNAMES)


def test_gamma_rejects_wrong_serial():
    result = subprocess.run(
        [VM_RUNNER, GAMMA_BC, GAMMA_KEY, 'admin', '0'],
        capture_output=True, text=True, timeout=10
    )
    assert 'ACCESS DENIED' in result.stdout


def test_gamma_cross_rejection():
    """Gamma serials must be rejected by alpha/beta and vice versa."""
    gamma_serial = _run_keygen(KEYGEN_GAMMA, 'admin')
    alpha_serial = _run_keygen(KEYGEN_ALPHA, 'admin')
    beta_serial = _run_keygen(KEYGEN_BETA, 'admin')

    # All three should be distinct
    assert len({gamma_serial, alpha_serial, beta_serial}) == 3, \
        "All three schemes must produce different serials"

    # Gamma serial rejected by alpha and beta
    assert not _verify_serial(CRACKME_ALPHA, 'admin', gamma_serial)
    assert not _verify_serial(CRACKME_BETA, 'admin', gamma_serial)

    # Alpha/beta serials rejected by gamma
    assert not _verify_gamma_serial('admin', alpha_serial)
    assert not _verify_gamma_serial('admin', beta_serial)


def test_gamma_avalanche():
    """Single-character input changes must flip >35% of output bits."""
    pairs = [
        ('admin', 'bdmin'),
        ('admin', 'admim'),
        ('test', 'tess'),
        ('hello', 'hellp'),
        ('world', 'xorld'),
    ]
    total_flips = 0
    for u1, u2 in pairs:
        s1 = int(_run_keygen(KEYGEN_GAMMA, u1), 16)
        s2 = int(_run_keygen(KEYGEN_GAMMA, u2), 16)
        flips = bin(s1 ^ s2).count('1')
        total_flips += flips

    avg_flips = total_flips / len(pairs)
    # 35% of 64 bits = 22.4
    assert avg_flips > 22, \
        f"Avalanche quality too low: avg {avg_flips:.1f} bits differ (need >22)"


# --------------- audit JSON ---------------

def _load_audit():
    with open(AUDIT, 'r') as f:
        return json.load(f)


def test_audit_valid_json():
    _load_audit()


def test_audit_top_level_structure():
    a = _load_audit()
    assert 'schemes' in a, "Missing 'schemes'"
    assert 'ranking' in a, "Missing 'ranking'"
    assert 'ranking_justification' in a, "Missing 'ranking_justification'"
    assert 'attack_vectors' in a, "Missing 'attack_vectors'"


def test_audit_scheme_fields():
    a = _load_audit()
    required = [
        'key_derivation_stages',
        'algorithms_used',
        'anti_analysis_techniques',
        'avalanche_quality',
        'estimated_re_hours',
    ]
    for name in ['alpha', 'beta', 'gamma']:
        assert name in a['schemes'], f"Missing scheme '{name}'"
        entry = a['schemes'][name]
        for field in required:
            assert field in entry, f"Missing '{field}' in schemes.{name}"
        assert isinstance(entry['key_derivation_stages'], int)
        assert isinstance(entry['algorithms_used'], list)
        assert len(entry['algorithms_used']) >= 1
        assert isinstance(entry['anti_analysis_techniques'], list)
        assert entry['avalanche_quality'] in ('poor', 'moderate', 'good', 'excellent')
        assert isinstance(entry['estimated_re_hours'], (int, float))


def test_audit_ranking():
    a = _load_audit()
    ranking = a['ranking']
    assert isinstance(ranking, list)
    assert set(ranking) == {'alpha', 'beta', 'gamma'}, \
        f"ranking must contain exactly alpha, beta, gamma — got {ranking}"


def test_audit_justification_length():
    a = _load_audit()
    j = a['ranking_justification']
    assert isinstance(j, str)
    assert len(j) >= 200, \
        f"ranking_justification too short ({len(j)} chars, need >=200)"


def test_audit_attack_vectors():
    a = _load_audit()
    av = a['attack_vectors']
    for name in ['alpha', 'beta', 'gamma']:
        assert name in av, f"Missing attack_vectors.{name}"
        assert isinstance(av[name], list)
    # Alpha and beta must have identified weaknesses
    assert len(av['alpha']) >= 1, "alpha should have at least 1 attack vector"
    assert len(av['beta']) >= 1, "beta should have at least 1 attack vector"


def test_audit_gamma_novel_algorithms():
    """Gamma must use algorithms not found in alpha or beta."""
    a = _load_audit()
    gamma_algos = [s.lower() for s in a['schemes']['gamma']['algorithms_used']]
    # These are the known alpha/beta algorithm names
    forbidden_fragments = ['fnv', 'djb2', 'murmurhash', 'xxhash', 'crc-64']
    for algo in gamma_algos:
        for frag in forbidden_fragments:
            assert frag not in algo, \
                f"Gamma algorithm '{algo}' contains '{frag}' — " \
                f"gamma must use novel algorithms not from alpha/beta"


def test_audit_different_algorithms_per_scheme():
    """Each scheme must list different algorithms."""
    a = _load_audit()
    alpha_set = frozenset(s.lower() for s in a['schemes']['alpha']['algorithms_used'])
    beta_set = frozenset(s.lower() for s in a['schemes']['beta']['algorithms_used'])
    gamma_set = frozenset(s.lower() for s in a['schemes']['gamma']['algorithms_used'])
    assert alpha_set != beta_set, "Alpha and beta must have different algorithms"
    assert alpha_set != gamma_set, "Alpha and gamma must have different algorithms"
    assert beta_set != gamma_set, "Beta and gamma must have different algorithms"
