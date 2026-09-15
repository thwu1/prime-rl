"""Tests for registry hive forensic recovery and adversarial hive construction.

Verifies Phase 1 (fragment extraction, technique identification) and
Phase 2 (crafted hive structural validity, payload concealment, technique novelty).

"""
import json
import os
import struct
import subprocess

import pytest

FINDINGS_PATH = "/app/findings.json"
CRAFTED_PATH = "/app/crafted.regf"
PAYLOAD = b"P0_h1v3_cr4ft"
PAYLOAD_STR = "P0_h1v3_cr4ft"
HBIN_HDR_SIZE = 0x20


@pytest.fixture
def findings():
    with open(FINDINGS_PATH) as f:
        return json.load(f)


# ═══════════════════════════════════════════════════════════════════
# Phase 1 — Forensic Recovery
# ═══════════════════════════════════════════════════════════════════


class TestOutputExists:
    def test_findings_file(self):
        assert os.path.isfile(FINDINGS_PATH), "findings.json not found"


class TestStructure:
    def test_has_fragments(self, findings):
        assert "fragments" in findings

    def test_has_techniques(self, findings):
        assert "techniques" in findings

    def test_has_combined_flag(self, findings):
        assert "combined_flag" in findings

    def test_four_fragments(self, findings):
        assert len(findings["fragments"]) == 4

    def test_four_techniques(self, findings):
        assert len(findings["techniques"]) == 4


class TestFragments:
    def test_baseline_fragment(self, findings):
        assert findings["fragments"].get("baseline.regf") == "Pr0j3ct_"

    def test_alpha_fragment(self, findings):
        assert findings["fragments"].get("suspect_alpha.regf") == "Z3r0_"

    def test_bravo_fragment(self, findings):
        assert findings["fragments"].get("suspect_bravo.regf") == "R3gf_"

    def test_charlie_fragment(self, findings):
        assert findings["fragments"].get("suspect_charlie.regf") == "FrE3"

    def test_fragments_nonempty(self, findings):
        for fname, frag in findings["fragments"].items():
            assert isinstance(frag, str) and len(frag) > 0, \
                f"Fragment for {fname} is empty or not a string"


class TestCombinedFlag:
    def test_exact_value(self, findings):
        assert findings["combined_flag"] == "Pr0j3ct_Z3r0_R3gf_FrE3"

    def test_matches_sorted_fragments(self, findings):
        expected = "".join(
            findings["fragments"][k]
            for k in sorted(findings["fragments"].keys())
        )
        assert findings["combined_flag"] == expected

    def test_flag_length(self, findings):
        assert len(findings["combined_flag"]) == 22


class TestTechniques:
    def test_baseline_technique(self, findings):
        t = findings["techniques"].get("baseline.regf", "").lower()
        assert any(kw in t for kw in [
            "plain", "standard", "none", "normal", "unmodified",
            "visible", "direct", "clear", "open",
        ]), f"Baseline technique should indicate plaintext access, got: '{t}'"

    def test_alpha_technique_mentions_version(self, findings):
        t = findings["techniques"].get("suspect_alpha.regf", "").lower()
        assert "version" in t, \
            f"Alpha technique should mention version spoofing, got: '{t}'"

    def test_bravo_technique_mentions_slack(self, findings):
        t = findings["techniques"].get("suspect_bravo.regf", "").lower()
        assert any(kw in t for kw in ["slack", "pad"]), \
            f"Bravo technique should mention slack/padding space, got: '{t}'"

    def test_charlie_technique_mentions_deletion(self, findings):
        t = findings["techniques"].get("suspect_charlie.regf", "").lower()
        assert any(kw in t for kw in [
            "delet", "free", "carv", "residu", "recov", "remnant",
        ]), f"Charlie technique should mention deleted/free cells, got: '{t}'"


class TestCrossValidation:
    def test_all_hive_files_represented(self, findings):
        expected = {"baseline.regf", "suspect_alpha.regf",
                    "suspect_bravo.regf", "suspect_charlie.regf"}
        assert set(findings["fragments"].keys()) == expected

    def test_techniques_cover_all_hives(self, findings):
        expected = {"baseline.regf", "suspect_alpha.regf",
                    "suspect_bravo.regf", "suspect_charlie.regf"}
        assert set(findings["techniques"].keys()) == expected

    def test_evidence_files_exist(self):
        evidence_dir = "/app/evidence"
        expected = {"baseline.regf", "suspect_alpha.regf",
                    "suspect_bravo.regf", "suspect_charlie.regf"}
        actual = {f for f in os.listdir(evidence_dir) if f.endswith(".regf")}
        assert actual == expected


# ═══════════════════════════════════════════════════════════════════
# Phase 2 — Adversarial Hive Construction
# ═══════════════════════════════════════════════════════════════════


class TestCraftedExists:
    def test_file_exists(self):
        assert os.path.isfile(CRAFTED_PATH), "crafted.regf not found"

    def test_minimum_size(self):
        sz = os.path.getsize(CRAFTED_PATH)
        assert sz >= 0x2000, f"Hive too small ({sz} bytes), need header + hbin"


class TestCraftedStructure:
    def test_regf_signature(self):
        with open(CRAFTED_PATH, "rb") as f:
            assert f.read(4) == b"regf", "Missing regf signature"

    def test_valid_checksum(self):
        with open(CRAFTED_PATH, "rb") as f:
            header = f.read(0x1000)
        cs = 0
        for i in range(0, 508, 4):
            cs ^= struct.unpack_from("<I", header, i)[0]
        cs &= 0xFFFFFFFF
        if cs == 0xFFFFFFFF:
            cs = 0xFFFFFFFE
        if cs == 0:
            cs = 1
        stored = struct.unpack_from("<I", header, 0x1FC)[0]
        assert cs == stored, "Header checksum mismatch"

    def test_major_version_valid(self):
        with open(CRAFTED_PATH, "rb") as f:
            f.seek(0x14)
            major = struct.unpack("<I", f.read(4))[0]
        assert major == 1, f"Major version must be 1 for hivexml, got {major}"

    def test_hbin_present(self):
        with open(CRAFTED_PATH, "rb") as f:
            f.seek(0x1000)
            assert f.read(4) == b"hbin", "Missing hbin signature at offset 0x1000"


class TestCraftedToolAccess:
    def test_hivexml_parses(self):
        r = subprocess.run(["hivexml", CRAFTED_PATH],
                           capture_output=True, timeout=15)
        assert r.returncode == 0, \
            f"hivexml must parse crafted hive: {r.stderr.decode(errors='replace')}"

    def test_decoy_value_accessible(self):
        r = subprocess.run(["hivexml", CRAFTED_PATH],
                           capture_output=True, timeout=15)
        output = r.stdout.decode(errors="replace")
        assert "<value" in output, \
            "Hive must contain at least one value accessible via hivexml"


class TestCraftedPayload:
    def test_payload_hidden_from_hivexml(self):
        """Payload string must NOT appear anywhere in hivexml output."""
        r = subprocess.run(["hivexml", CRAFTED_PATH],
                           capture_output=True, timeout=15)
        output = r.stdout.decode(errors="replace")
        assert PAYLOAD_STR not in output, \
            "Payload visible in hivexml output — concealment failed"

    def test_payload_in_raw_binary(self):
        """Payload must exist as contiguous bytes in the raw file."""
        with open(CRAFTED_PATH, "rb") as f:
            raw = f.read()
        found = (PAYLOAD in raw) or \
                (PAYLOAD_STR.encode("utf-16-le") in raw)
        assert found, "Payload not found in raw binary"

    def test_payload_in_hive_data_area(self):
        """Payload must be within hive data (after 4096-byte base block)."""
        with open(CRAFTED_PATH, "rb") as f:
            raw = f.read()
        hive_data = raw[0x1000:]
        found = (PAYLOAD in hive_data) or \
                (PAYLOAD_STR.encode("utf-16-le") in hive_data)
        assert found, "Payload not in hive data area (only in header?)"

    def test_payload_not_in_nk_slack(self):
        """Payload must NOT be hidden in nk cell slack space
        (that technique is used in the evidence files)."""
        with open(CRAFTED_PATH, "rb") as f:
            raw = f.read()
        hd = raw[0x1000:]
        off = HBIN_HDR_SIZE
        length = len(hd)
        while off + 4 < length:
            sv = struct.unpack_from("<i", hd, off)[0]
            if sv == 0:
                break
            absz = abs(sv)
            if absz < 8:
                break
            if sv < 0:  # allocated cell
                d = hd[off + 4:off + absz]
                if len(d) >= 0x4C and d[:2] == b"nk":
                    nl = struct.unpack_from("<H", d, 0x48)[0]
                    data_end = 0x4C + nl
                    slack = d[data_end:]
                    assert PAYLOAD not in slack, \
                        "Payload found in nk cell slack — reuses evidence technique"
            off += absz

    def test_payload_not_in_free_cell(self):
        """Payload must NOT be hidden in a free (deleted) cell
        (that technique is used in the evidence files)."""
        with open(CRAFTED_PATH, "rb") as f:
            raw = f.read()
        hd = raw[0x1000:]
        off = HBIN_HDR_SIZE
        length = len(hd)
        while off + 4 < length:
            sv = struct.unpack_from("<i", hd, off)[0]
            if sv == 0:
                break
            absz = abs(sv)
            if absz < 8:
                break
            if sv > 0:  # free cell
                d = hd[off + 4:off + absz]
                assert PAYLOAD not in d, \
                    "Payload found in free cell — reuses evidence technique"
            off += absz


class TestCraftedTechniqueReport:
    def test_crafted_technique_described(self, findings):
        assert "crafted_technique" in findings, \
            "findings.json must include crafted_technique field"
        desc = findings["crafted_technique"]
        assert isinstance(desc, str) and len(desc) > 20, \
            "Technique description must be substantive (>20 chars)"

    def test_technique_not_trivially_same(self, findings):
        """Crafted technique description must not be identical
        to any evidence technique description."""
        desc = findings.get("crafted_technique", "").strip().lower()
        for fname in ["suspect_alpha.regf", "suspect_bravo.regf",
                       "suspect_charlie.regf"]:
            ev = findings.get("techniques", {}).get(fname, "").strip().lower()
            if ev:
                assert desc != ev, \
                    f"Crafted technique is identical to {fname} technique"
