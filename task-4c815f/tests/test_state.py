"""
Verification tests for the driver security audit, hardened allocator design,
and defense evaluation task.

Checks:
  1. audit_report.json has all 7 vulnerability types with correct metadata,
     severity scores, and exploitation classes
  2. Hardened pool allocator exists and implements canary/quarantine/poison
  3. Defense assessment has severity ranking, exploit chains, defense mapping
  4. Patched source compiles and survives all crafted triggers
  5. Original ASAN binary crashes on those same triggers
"""

import json
import os
import re
import struct
import subprocess
import pytest

# ---------- constants ----------

REQUIRED_VULN_TYPES = {
    "heap-buffer-overflow",
    "stack-buffer-overflow",
    "use-after-free",
    "double-free",
    "integer-overflow",
    "type-confusion",
    "out-of-bounds",
}

EXPECTED_CWES = {
    "heap-buffer-overflow": {"CWE-122"},
    "stack-buffer-overflow": {"CWE-121"},
    "use-after-free": {"CWE-416"},
    "double-free": {"CWE-415"},
    "integer-overflow": {"CWE-190"},
    "type-confusion": {"CWE-843"},
    "out-of-bounds": {"CWE-787", "CWE-125"},
}

EXPECTED_COMMANDS = {
    "heap-buffer-overflow": "CMD_STORE_DATA",
    "stack-buffer-overflow": "CMD_LOG_EVENT",
    "use-after-free": "CMD_MANAGE_SESSION",
    "double-free": "CMD_CLEANUP_TXN",
    "integer-overflow": "CMD_BATCH_ALLOC",
    "type-confusion": "CMD_PROCESS_PACKET",
    "out-of-bounds": "CMD_READ_CONFIG",
}

VALID_EXPLOITATION_CLASSES = {
    "arbitrary-read", "arbitrary-write", "code-execution",
    "denial-of-service", "info-leak",
}

VALID_EXPLOITABILITY = {"trivial", "moderate", "complex"}

VALID_MECHANISMS = {"allocator", "patch", "both"}

# ---------- helpers ----------

def normalize_type(t):
    aliases = {
        "heap-overflow": "heap-buffer-overflow",
        "stack-overflow": "stack-buffer-overflow",
        "uaf": "use-after-free",
        "use_after_free": "use-after-free",
        "int-overflow": "integer-overflow",
        "integer_overflow": "integer-overflow",
        "oob": "out-of-bounds",
        "oob-read": "out-of-bounds",
        "oob-write": "out-of-bounds",
        "out-of-bounds-read": "out-of-bounds",
        "out-of-bounds-write": "out-of-bounds",
    }
    t = t.lower().strip()
    return aliases.get(t, t)


def normalize_cwe(cwe):
    cwe = cwe.upper().replace(" ", "").replace("_", "")
    if cwe.startswith("CWE") and not cwe.startswith("CWE-"):
        cwe = "CWE-" + cwe[3:]
    return cwe


def make_header(cmd, sub, flags, length):
    return struct.pack("<BBHI", cmd, sub, flags, length)


def write_trigger(path, data):
    with open(path, "wb") as f:
        f.write(data)


def run_binary(binary, trigger_file, timeout=10):
    env = os.environ.copy()
    env["ASAN_OPTIONS"] = "detect_leaks=0:abort_on_error=1"
    env.pop("LD_PRELOAD", None)
    try:
        r = subprocess.run(
            [binary, trigger_file],
            capture_output=True, timeout=timeout, env=env,
        )
        return r.returncode, r.stderr.decode(errors="replace")
    except subprocess.TimeoutExpired:
        return -1, "TIMEOUT"


# ---------- trigger generators ----------

def trigger_heap_overflow():
    payload = b"\x01\x00\x00\x00" + b"A" * 256
    return make_header(0x01, 0, 0, len(payload)) + payload


def trigger_stack_overflow():
    msg = b"B" * 200
    log_evt = struct.pack("<BBH", 0, 0, 200)
    payload = log_evt + msg
    return make_header(0x02, 0, 0, len(payload)) + payload


def trigger_uaf():
    cmds = b""
    cmds += make_header(0x03, 0x01, 0, 0)   # CREATE
    cmds += make_header(0x03, 0x03, 0, 0)   # RESET
    cmds += make_header(0x03, 0x02, 0, 0)   # STATS
    return cmds


def trigger_double_free():
    data = b"X" * 32
    cmds = make_header(0x04, 0x01, 0, len(data)) + data
    cmds += make_header(0x04, 0x03, 0, 0)   # ROLLBACK
    return cmds


def trigger_integer_overflow():
    batch = struct.pack("<IIBxxx", 0x10000, 0x10000, 0x41)
    filler = b"C" * 100
    payload = batch + filler
    return make_header(0x05, 0, 0, len(payload)) + payload


def trigger_type_confusion():
    net = struct.pack("<IIHH", 1, 2, 80, 443)
    pkt_type = struct.pack("<I", 0x41414141)
    extra = b"\x00" * 4
    payload = net + pkt_type + extra
    return make_header(0x06, 0, 0x0101, len(payload)) + payload


def trigger_oob():
    payload = struct.pack("<IBxxx", 100, 0) + b"\x00" * 64
    return make_header(0x07, 0, 0, len(payload)) + payload


ALL_TRIGGERS = {
    "heap_overflow":     trigger_heap_overflow,
    "stack_overflow":    trigger_stack_overflow,
    "uaf":              trigger_uaf,
    "double_free":       trigger_double_free,
    "integer_overflow":  trigger_integer_overflow,
    "type_confusion":    trigger_type_confusion,
    "oob":              trigger_oob,
}


# ====================================================================
#  Test suite 1 — audit report correctness and evaluation quality
# ====================================================================

class TestAuditReport:

    REPORT = "/app/audit_report.json"

    def _load(self):
        with open(self.REPORT) as f:
            return json.load(f)

    def test_report_exists(self):
        assert os.path.exists(self.REPORT), "audit_report.json not found at /app/"

    def test_report_valid_json(self):
        data = self._load()
        assert "vulnerabilities" in data
        assert isinstance(data["vulnerabilities"], list)

    def test_report_has_seven_vulns(self):
        vulns = self._load()["vulnerabilities"]
        assert len(vulns) >= 7, f"Expected >=7, got {len(vulns)}"

    def test_report_covers_all_types(self):
        vulns = self._load()["vulnerabilities"]
        found = {normalize_type(v["type"]) for v in vulns}
        missing = REQUIRED_VULN_TYPES - found
        assert not missing, f"Missing types: {missing}"

    def test_report_correct_cwes(self):
        for v in self._load()["vulnerabilities"]:
            vtype = normalize_type(v["type"])
            if vtype in EXPECTED_CWES:
                cwe = normalize_cwe(v["cwe"])
                assert cwe in EXPECTED_CWES[vtype], \
                    f"Wrong CWE for {vtype}: got {cwe}, expected one of {EXPECTED_CWES[vtype]}"

    def test_report_correct_commands(self):
        for v in self._load()["vulnerabilities"]:
            vtype = normalize_type(v["type"])
            if vtype in EXPECTED_COMMANDS:
                assert v["command"] == EXPECTED_COMMANDS[vtype], \
                    f"Wrong command for {vtype}: got {v['command']}"

    def test_report_required_fields(self):
        required = {"id", "type", "cwe", "command", "function", "file",
                     "root_cause", "trigger", "severity_score",
                     "exploitation_class"}
        for v in self._load()["vulnerabilities"]:
            missing = required - set(v.keys())
            assert not missing, f"{v.get('id','?')} missing fields: {missing}"

    def test_report_severity_scores_valid(self):
        for v in self._load()["vulnerabilities"]:
            score = v.get("severity_score")
            assert isinstance(score, int), \
                f"{v['id']}: severity_score must be integer, got {type(score).__name__}"
            assert 1 <= score <= 10, \
                f"{v['id']}: severity_score {score} out of range [1,10]"

    def test_report_exploitation_classes_valid(self):
        for v in self._load()["vulnerabilities"]:
            ec = v.get("exploitation_class", "")
            assert ec in VALID_EXPLOITATION_CLASSES, \
                f"{v['id']}: invalid exploitation_class '{ec}'"


# ====================================================================
#  Test suite 2 — hardened pool allocator design
# ====================================================================

class TestHardenedAllocator:

    POOL_C = "/app/hardened_pool/pool.c"
    POOL_H = "/app/hardened_pool/pool.h"

    def _read(self, path):
        with open(path) as f:
            return f.read()

    def test_pool_c_exists(self):
        assert os.path.isfile(self.POOL_C), \
            "hardened_pool/pool.c not found"

    def test_pool_h_exists(self):
        assert os.path.isfile(self.POOL_H), \
            "hardened_pool/pool.h not found"

    def test_api_pool_alloc(self):
        src = self._read(self.POOL_C)
        assert re.search(r"void\s*\*\s*pool_alloc\s*\(", src), \
            "pool_alloc function not found in hardened pool.c"

    def test_api_pool_free(self):
        src = self._read(self.POOL_C)
        assert re.search(r"void\s+pool_free\s*\(", src), \
            "pool_free function not found in hardened pool.c"

    def test_api_pool_tag_macro(self):
        hdr = self._read(self.POOL_H)
        assert "POOL_TAG" in hdr, "POOL_TAG macro not found in hardened pool.h"

    def test_api_pool_constants(self):
        hdr = self._read(self.POOL_H)
        assert "POOL_PAGED" in hdr, "POOL_PAGED not found in hardened pool.h"
        assert "POOL_NONPAGED" in hdr, "POOL_NONPAGED not found in hardened pool.h"

    def test_has_canary_mechanism(self):
        src = self._read(self.POOL_C)
        # Look for canary-related patterns: magic constants, canary variables,
        # or verification logic
        canary_patterns = [
            r"canary",
            r"CANARY",
            r"sentinel",
            r"SENTINEL",
            r"guard",
            r"GUARD",
            r"0x[Dd][Ee][Aa][Dd]",
            r"magic",
            r"MAGIC",
        ]
        found = any(re.search(p, src, re.IGNORECASE) for p in canary_patterns)
        assert found, \
            "No canary/sentinel/guard mechanism detected in hardened pool.c"

    def test_has_quarantine_mechanism(self):
        src = self._read(self.POOL_C)
        quarantine_patterns = [
            r"quarantine",
            r"QUARANTINE",
            r"delayed.free",
            r"free.list",
            r"free_queue",
            r"deferred",
            r"DEFERRED",
            r"recycle",
        ]
        found = any(re.search(p, src, re.IGNORECASE) for p in quarantine_patterns)
        assert found, \
            "No quarantine/delayed-free mechanism detected in hardened pool.c"

    def test_has_poison_mechanism(self):
        src = self._read(self.POOL_C)
        poison_patterns = [
            r"poison",
            r"POISON",
            r"0x[Dd][Ee]",
            r"0xDE",
            r"memset.*free",
            r"dead.beef",
            r"DEADBEEF",
            r"scribble",
        ]
        found = any(re.search(p, src, re.IGNORECASE) for p in poison_patterns)
        assert found, \
            "No memory poisoning mechanism detected in hardened pool.c"


# ====================================================================
#  Test suite 3 — defense assessment evaluation quality
# ====================================================================

class TestDefenseAssessment:

    ASSESS = "/app/defense_assessment.json"
    REPORT = "/app/audit_report.json"

    def _load_assess(self):
        with open(self.ASSESS) as f:
            return json.load(f)

    def _load_report(self):
        with open(self.REPORT) as f:
            return json.load(f)

    def _vuln_ids(self):
        return {v["id"] for v in self._load_report()["vulnerabilities"]}

    def test_file_exists(self):
        assert os.path.isfile(self.ASSESS), \
            "defense_assessment.json not found at /app/"

    def test_valid_json(self):
        data = self._load_assess()
        assert isinstance(data, dict)

    def test_severity_ranking_exists(self):
        data = self._load_assess()
        assert "severity_ranking" in data, "Missing severity_ranking"
        assert isinstance(data["severity_ranking"], list)

    def test_severity_ranking_has_all_vulns(self):
        data = self._load_assess()
        ranking_ids = {e["vuln_id"] for e in data["severity_ranking"]}
        report_ids = self._vuln_ids()
        missing = report_ids - ranking_ids
        assert not missing, f"severity_ranking missing vuln IDs: {missing}"

    def test_severity_ranking_fields(self):
        data = self._load_assess()
        for entry in data["severity_ranking"]:
            assert "vuln_id" in entry, "severity_ranking entry missing vuln_id"
            assert "severity_score" in entry, \
                f"{entry.get('vuln_id','?')} missing severity_score"
            assert "exploitability" in entry, \
                f"{entry.get('vuln_id','?')} missing exploitability"
            assert "justification" in entry, \
                f"{entry.get('vuln_id','?')} missing justification"

    def test_severity_ranking_valid_values(self):
        data = self._load_assess()
        for entry in data["severity_ranking"]:
            assert entry["exploitability"] in VALID_EXPLOITABILITY, \
                f"{entry['vuln_id']}: invalid exploitability '{entry['exploitability']}'"
            score = entry["severity_score"]
            assert isinstance(score, int) and 1 <= score <= 10, \
                f"{entry['vuln_id']}: severity_score {score} invalid"

    def test_severity_ranking_ordered(self):
        data = self._load_assess()
        scores = [e["severity_score"] for e in data["severity_ranking"]]
        assert scores == sorted(scores, reverse=True), \
            f"severity_ranking not ordered highest-first: {scores}"

    def test_severity_justifications_nontrivial(self):
        data = self._load_assess()
        for entry in data["severity_ranking"]:
            just = entry.get("justification", "")
            assert len(just) >= 30, \
                f"{entry['vuln_id']}: justification too short ({len(just)} chars)"

    def test_exploit_chains_exist(self):
        data = self._load_assess()
        assert "exploit_chains" in data, "Missing exploit_chains"
        chains = data["exploit_chains"]
        assert isinstance(chains, list) and len(chains) >= 1, \
            "exploit_chains must contain at least one chain analysis"

    def test_exploit_chains_structure(self):
        data = self._load_assess()
        for chain in data["exploit_chains"]:
            assert "chain_id" in chain, "Chain missing chain_id"
            assert "vulnerabilities" in chain, \
                f"{chain.get('chain_id','?')} missing vulnerabilities"
            assert isinstance(chain["vulnerabilities"], list) and \
                   len(chain["vulnerabilities"]) >= 2, \
                f"{chain['chain_id']}: chain must reference >=2 vulnerabilities"
            assert "description" in chain, \
                f"{chain['chain_id']} missing description"
            assert "escalated_impact" in chain, \
                f"{chain['chain_id']} missing escalated_impact"

    def test_exploit_chains_reference_valid_ids(self):
        data = self._load_assess()
        report_ids = self._vuln_ids()
        for chain in data["exploit_chains"]:
            for vid in chain["vulnerabilities"]:
                assert vid in report_ids, \
                    f"Chain {chain['chain_id']} references unknown vuln '{vid}'"

    def test_defense_mapping_exists(self):
        data = self._load_assess()
        assert "defense_mapping" in data, "Missing defense_mapping"
        assert isinstance(data["defense_mapping"], dict)

    def test_defense_mapping_covers_all_vulns(self):
        data = self._load_assess()
        mapping_ids = set(data["defense_mapping"].keys())
        report_ids = self._vuln_ids()
        missing = report_ids - mapping_ids
        assert not missing, f"defense_mapping missing vuln IDs: {missing}"

    def test_defense_mapping_valid_mechanisms(self):
        data = self._load_assess()
        for vid, entry in data["defense_mapping"].items():
            assert "mechanism" in entry, f"{vid} missing mechanism"
            assert entry["mechanism"] in VALID_MECHANISMS, \
                f"{vid}: invalid mechanism '{entry['mechanism']}'"
            assert "rationale" in entry, f"{vid} missing rationale"
            assert len(entry["rationale"]) >= 20, \
                f"{vid}: rationale too short ({len(entry['rationale'])} chars)"


# ====================================================================
#  Test suite 4 — patched code compiles and survives triggers
# ====================================================================

class TestPatchedCode:

    PATCH_DIR = "/app/patched"

    @classmethod
    def setup_class(cls):
        if not os.path.isdir(cls.PATCH_DIR):
            pytest.skip("Patched directory not found")
        subprocess.run(["make", "clean"], cwd=cls.PATCH_DIR,
                       capture_output=True)
        r = subprocess.run(["make", "asan"], cwd=cls.PATCH_DIR,
                           capture_output=True)
        cls.compile_ok = r.returncode == 0
        cls.compile_err = r.stderr.decode(errors="replace")

    def test_patched_compiles(self):
        assert self.compile_ok, f"Compile failed:\n{self.compile_err[:800]}"

    def test_patched_uses_hardened_pool(self):
        """Verify the patched pool.c is the hardened version, not the original."""
        pool_c = os.path.join(self.PATCH_DIR, "src", "pool.c")
        assert os.path.isfile(pool_c), "patched/src/pool.c not found"
        with open(pool_c) as f:
            src = f.read()
        hardened_indicators = [
            r"canary|CANARY|sentinel|SENTINEL|guard|GUARD",
            r"quarantine|QUARANTINE|delayed.free|deferred|DEFERRED",
        ]
        found = sum(1 for pat in hardened_indicators
                    if re.search(pat, src, re.IGNORECASE))
        assert found >= 2, \
            "Patched pool.c does not appear to be the hardened allocator"

    @pytest.mark.parametrize("name", list(ALL_TRIGGERS.keys()))
    def test_patched_no_crash(self, name):
        if not self.compile_ok:
            pytest.skip("patched code did not compile")
        binary = os.path.join(self.PATCH_DIR, "vdriver_asan")
        trig = f"/tmp/trig_patched_{name}.bin"
        write_trigger(trig, ALL_TRIGGERS[name]())
        rc, stderr = run_binary(binary, trig)
        assert rc == 0, \
            f"Patched crashed on {name} (rc={rc}):\n{stderr[:500]}"
        assert "ERROR: AddressSanitizer" not in stderr, \
            f"ASAN error in patched for {name}:\n{stderr[:500]}"


# ====================================================================
#  Test suite 5 — original code actually has the vulnerabilities
# ====================================================================

class TestOriginalVulns:

    ORIG_BIN = "/app/vdriver_asan_original"

    @classmethod
    def setup_class(cls):
        if not os.path.exists(cls.ORIG_BIN):
            orig = "/app"
            subprocess.run(["make", "clean"], cwd=orig, capture_output=True)
            r = subprocess.run(["make", "asan"], cwd=orig, capture_output=True)
            if r.returncode == 0 and os.path.exists(f"{orig}/vdriver_asan"):
                cls.ORIG_BIN = f"{orig}/vdriver_asan"
            else:
                pytest.skip("Cannot build original ASAN binary")

    @pytest.mark.parametrize("name", list(ALL_TRIGGERS.keys()))
    def test_original_crashes(self, name):
        trig = f"/tmp/trig_orig_{name}.bin"
        write_trigger(trig, ALL_TRIGGERS[name]())
        rc, stderr = run_binary(self.ORIG_BIN, trig)
        assert rc != 0, \
            f"Original did NOT crash on {name} — vulnerability may be missing"
