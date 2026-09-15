
"""
Verification tests for multi-layer WAF bypass, credential decryption, and patch task.

Checks:
1. All 4 decrypted credential flags are correct
2. Patched YAML config exists and is valid
3. Patched WAF module exists with correct interface
4. Patched WAF blocks UNION ALL/DISTINCT SELECT bypass
5. Patched WAF blocks form-feed/vertical-tab subquery bypass
6. Patched WAF blocks all SQLite schema alias variants
7. Patched WAF blocks trusted header bypass
8. Patched WAF allows legitimate queries
9. Patched WAF is not trivially broad
10. Patched WAF preserves standard injection blocking
"""

import hashlib
import importlib.util
import os
import yaml

SEED = 'waf-bypass-ctf-2024'


def _gen_credential(n):
    h = hashlib.sha256(f"{SEED}-credential-{n}".encode()).hexdigest()[:24]
    return f"FLAG{{{h}}}"


EXPECTED_FLAGS = [_gen_credential(i) for i in range(1, 5)]
FLAGS_PATH = '/app/flags.txt'
PATCHED_WAF_PATH = '/app/waf_patched.py'
PATCHED_YAML_PATH = '/app/waf_rules_patched.yaml'


def _load_patched_waf():
    """Load the patched WAF module with patched YAML config."""
    spec = importlib.util.spec_from_file_location("waf_patched", PATCHED_WAF_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.WAF(config_path=PATCHED_YAML_PATH)


def test_flags_decrypted():
    """All 4 decrypted credential values must be correct."""
    assert os.path.exists(FLAGS_PATH), f"{FLAGS_PATH} not found"
    with open(FLAGS_PATH) as f:
        extracted = [line.strip() for line in f if line.strip()]
    for flag in EXPECTED_FLAGS:
        assert flag in extracted, f"Missing or incorrect credential: {flag[:12]}..."


def test_patched_yaml_exists():
    """Patched YAML config must exist and be valid with rules."""
    assert os.path.exists(PATCHED_YAML_PATH), f"{PATCHED_YAML_PATH} not found"
    with open(PATCHED_YAML_PATH) as f:
        config = yaml.safe_load(f)
    assert 'rules' in config, "Patched YAML must have 'rules' section"
    assert isinstance(config['rules'], list), "'rules' must be a list"
    assert len(config['rules']) >= 3, "Patched YAML must have at least 3 rules"


def test_patched_waf_exists():
    """Patched WAF module must exist and expose correct interface."""
    assert os.path.exists(PATCHED_WAF_PATH), f"{PATCHED_WAF_PATH} not found"
    waf = _load_patched_waf()
    result = waf.check("id = 1")
    assert isinstance(result, tuple) and len(result) == 2, \
        "check() must return a 2-tuple (allowed, triggered_rules)"
    # Verify headers parameter is accepted
    result2 = waf.check("id = 1", headers={"X-Test": "value"})
    assert isinstance(result2, tuple) and len(result2) == 2


def test_patched_waf_blocks_union_all_select():
    """Patched WAF must block UNION ALL/DISTINCT SELECT variants."""
    waf = _load_patched_waf()
    payloads = [
        "1=0 UNION ALL SELECT 1,2,3,4,5 FROM secrets",
        "1=0 UNION DISTINCT SELECT * FROM secrets",
        "1=0 UNION  ALL  SELECT 1,2,3 FROM t",
        "x' UNION ALL SELECT id,name,val,0,0 FROM t WHERE '1'='1",
    ]
    for payload in payloads:
        allowed, _ = waf.check(payload)
        assert not allowed, f"Patched WAF must block: {payload}"


def test_patched_waf_blocks_formfeed_subquery():
    """Patched WAF must block subqueries using form-feed or vertical-tab."""
    waf = _load_patched_waf()
    payloads = [
        "username = 'admin' AND (\x0cSELECT 1) = 1",
        "username = 'admin' AND (\x0bSELECT 1) = 1",
    ]
    for payload in payloads:
        allowed, _ = waf.check(payload)
        assert not allowed, \
            f"Patched WAF must block subquery with special whitespace: {repr(payload)}"


def test_patched_waf_blocks_schema_variants():
    """Patched WAF must block all SQLite schema discovery aliases."""
    waf = _load_patched_waf()
    payloads = [
        "id = 1 AND sqlite_schema IS NOT NULL",
        "id = 1 AND sqlite_temp_master IS NOT NULL",
        "id = 1 AND sqlite_temp_schema IS NOT NULL",
    ]
    for payload in payloads:
        allowed, _ = waf.check(payload)
        assert not allowed, f"Patched WAF must block schema reference: {payload}"


def test_patched_waf_blocks_header_bypass():
    """Patched WAF must not allow bypassing rules via trusted headers."""
    waf = _load_patched_waf()
    # OR tautology is ONLY blocked by YAML rule Y02, not by any Python rule.
    # If the header bypass still works, Y02 is skipped and this passes through.
    headers = {"X-Forwarded-By": "internal-waf-proxy"}
    payload = "1 OR 1=1"
    allowed, _ = waf.check(payload, headers=headers)
    assert not allowed, \
        "Patched WAF must not skip YAML rules when X-Forwarded-By header is present"
    # Also test UNION SELECT with header
    payload2 = "1=0 UNION SELECT * FROM users"
    allowed2, _ = waf.check(payload2, headers=headers)
    assert not allowed2, \
        "Patched WAF must block UNION SELECT even with trusted header"


def test_patched_waf_allows_legitimate_queries():
    """Patched WAF must not block legitimate queries."""
    waf = _load_patched_waf()
    queries = [
        "username = 'admin'",
        "department = 'Engineering'",
        "role = 'user' AND department = 'Engineering'",
        "id >= 2",
        "username LIKE 'a%'",
        "email = 'jdoe@corp.local'",
        "id BETWEEN 1 AND 3",
        "department IN ('IT', 'HR')",
        "role != 'admin'",
        "id = 1",
    ]
    for query in queries:
        allowed, triggered = waf.check(query)
        assert allowed, \
            f"Patched WAF must allow legitimate query: {query} (triggered: {triggered})"


def test_patched_waf_not_trivially_broad():
    """Patched WAF must not block everything indiscriminately."""
    waf = _load_patched_waf()
    simple = ["1=1", "id = 1", "username = 'test'", "role != 'admin'"]
    for q in simple:
        allowed, _ = waf.check(q)
        assert allowed, f"WAF appears trivially broad, blocking: {q}"


def test_patched_waf_preserves_standard_blocks():
    """Patched WAF must still block standard SQL injection patterns."""
    waf = _load_patched_waf()
    payloads = [
        "1=0 UNION SELECT * FROM users",
        "1 OR 1=1",
        "1; DROP TABLE users",
        "1 AND (SELECT * FROM sqlite_master)",
        "id=1 AND char(65)",
    ]
    for payload in payloads:
        allowed, _ = waf.check(payload)
        assert not allowed, f"Patched WAF must still block: {payload}"
