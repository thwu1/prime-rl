"""
Verification tests for GLSL ES 3.00 conformance pipeline audit.

"""

import json
import os
import subprocess
import tempfile
import pytest

VALIDATOR = "/app/glsl_link_validator.py"
RUN_TESTS = "/app/run_tests.py"
MANIFEST = "/app/test_harness/manifest.json"
DIAGNOSTIC_REPORT = "/app/diagnostic_report.json"


def run_validator(vert_src, frag_src):
    """Write shaders to temp files and invoke the validator."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".vert", delete=False) as vf:
        vf.write(vert_src)
        vp = vf.name
    with tempfile.NamedTemporaryFile(mode="w", suffix=".frag", delete=False) as ff:
        ff.write(frag_src)
        fp = ff.name
    try:
        r = subprocess.run(
            ["python3", VALIDATOR, vp, fp],
            capture_output=True, text=True, timeout=30,
        )
        assert r.returncode == 0, f"Validator error: {r.stderr}"
        return json.loads(r.stdout)
    finally:
        os.unlink(vp)
        os.unlink(fp)


# =====================================================================
# Pipeline integration test
# =====================================================================


class TestPipelinePass:
    """The full test pipeline must pass after repairs."""

    def test_run_tests_exits_zero(self):
        r = subprocess.run(
            ["python3", RUN_TESTS],
            capture_output=True, text=True, timeout=120,
        )
        assert r.returncode == 0, f"run_tests.py failed:\n{r.stdout}\n{r.stderr}"


# =====================================================================
# Validator bug-fix verification (novel shader pairs)
# =====================================================================


class TestStructNameFix:
    """Struct types with different names but same structure must link."""

    def test_different_names_same_structure_passes(self):
        vert = """\
#version 300 es
struct TypeA { vec3 pos; float val; };
in vec4 aPosition;
out TypeA vData;
void main() {
    gl_Position = aPosition;
    vData.pos = vec3(0.0);
    vData.val = 1.0;
}
"""
        frag = """\
#version 300 es
precision mediump float;
struct TypeB { vec3 pos; float val; };
in TypeB vData;
out vec4 fragColor;
void main() { fragColor = vec4(vData.pos, vData.val); }
"""
        result = run_validator(vert, frag)
        assert result["valid"] is True, f"Errors: {result['errors']}"


class TestStructOrderFix:
    """Struct member order must matter (not set comparison)."""

    def test_reordered_struct_detected(self):
        vert = """\
#version 300 es
struct Info { float alpha; vec3 beta; int gamma; };
in vec4 aPosition;
out Info vInfo;
void main() {
    gl_Position = aPosition;
    vInfo.alpha = 1.0;
    vInfo.beta = vec3(0.0);
    vInfo.gamma = 1;
}
"""
        frag = """\
#version 300 es
precision mediump float;
struct Info { int gamma; float alpha; vec3 beta; };
in Info vInfo;
out vec4 fragColor;
void main() { fragColor = vec4(vInfo.alpha); }
"""
        result = run_validator(vert, frag)
        assert result["valid"] is False
        cats = {e["category"] for e in result["errors"]}
        assert "STRUCT_MISMATCH" in cats


class TestArrayOnTypeFix:
    """Array-on-type syntax (type[N] name) must be parsed."""

    def test_array_on_type_valid(self):
        vert = """\
#version 300 es
in vec4 aPosition;
out float[3] vWeights;
void main() {
    gl_Position = aPosition;
    vWeights[0] = 0.5;
    vWeights[1] = 0.3;
    vWeights[2] = 0.2;
}
"""
        frag = """\
#version 300 es
precision mediump float;
in float vWeights[3];
out vec4 fragColor;
void main() { fragColor = vec4(vWeights[0]); }
"""
        result = run_validator(vert, frag)
        assert result["valid"] is True, f"Errors: {result['errors']}"

    def test_array_on_type_size_mismatch(self):
        vert = """\
#version 300 es
in vec4 aPosition;
out vec3[2] vDirs;
void main() {
    gl_Position = aPosition;
    vDirs[0] = vec3(1.0, 0.0, 0.0);
    vDirs[1] = vec3(0.0, 1.0, 0.0);
}
"""
        frag = """\
#version 300 es
precision mediump float;
in vec3 vDirs[4];
out vec4 fragColor;
void main() { fragColor = vec4(vDirs[0], 1.0); }
"""
        result = run_validator(vert, frag)
        assert result["valid"] is False
        cats = {e["category"] for e in result["errors"]}
        assert "ARRAY_SIZE_MISMATCH" in cats


class TestMultiVarDeclFix:
    """All variables in comma-separated declarations must be captured."""

    def test_multi_var_all_present(self):
        vert = """\
#version 300 es
in vec4 aPosition;
out vec3 vNormA, vNormB, vNormC;
void main() {
    gl_Position = aPosition;
    vNormA = vec3(1.0, 0.0, 0.0);
    vNormB = vec3(0.0, 1.0, 0.0);
    vNormC = vec3(0.0, 0.0, 1.0);
}
"""
        frag = """\
#version 300 es
precision mediump float;
in vec3 vNormA;
in vec3 vNormB;
in vec3 vNormC;
out vec4 fragColor;
void main() { fragColor = vec4(vNormA + vNormB + vNormC, 1.0); }
"""
        result = run_validator(vert, frag)
        assert result["valid"] is True, f"Errors: {result['errors']}"


class TestLayoutSpacesFix:
    """Layout qualifiers with whitespace must be parsed correctly."""

    def test_layout_with_spaces_match(self):
        vert = """\
#version 300 es
in vec4 aPosition;
layout(  location  =  3  ) out vec4 vData;
void main() { gl_Position = aPosition; vData = vec4(1.0); }
"""
        frag = """\
#version 300 es
precision mediump float;
layout(location = 3) in vec4 vData;
out vec4 fragColor;
void main() { fragColor = vData; }
"""
        result = run_validator(vert, frag)
        assert result["valid"] is True, f"Errors: {result['errors']}"

    def test_layout_with_spaces_mismatch(self):
        vert = """\
#version 300 es
in vec4 aPosition;
layout( location = 5 ) out vec4 vData;
void main() { gl_Position = aPosition; vData = vec4(1.0); }
"""
        frag = """\
#version 300 es
precision mediump float;
layout(location=2) in vec4 vData;
out vec4 fragColor;
void main() { fragColor = vData; }
"""
        result = run_validator(vert, frag)
        assert result["valid"] is False
        cats = {e["category"] for e in result["errors"]}
        assert "LOCATION_MISMATCH" in cats


class TestInvariantComparisonFix:
    """Invariant must be compared between both sides."""

    def test_both_invariant_passes(self):
        vert = """\
#version 300 es
in vec4 aPosition;
invariant out vec4 vPos;
void main() { gl_Position = aPosition; vPos = aPosition; }
"""
        frag = """\
#version 300 es
precision mediump float;
invariant in vec4 vPos;
out vec4 fragColor;
void main() { fragColor = vPos; }
"""
        r = run_validator(vert, frag)
        assert r["valid"] is True, f"Both invariant should pass: {r['errors']}"

    def test_fragment_only_invariant_fails(self):
        vert = """\
#version 300 es
in vec4 aPosition;
out vec4 vPos;
void main() { gl_Position = aPosition; vPos = aPosition; }
"""
        frag = """\
#version 300 es
precision mediump float;
invariant in vec4 vPos;
out vec4 fragColor;
void main() { fragColor = vPos; }
"""
        r = run_validator(vert, frag)
        assert r["valid"] is False
        cats = {e["category"] for e in r["errors"]}
        assert "INVARIANT_MISMATCH" in cats


# =====================================================================
# Manifest correction verification
# =====================================================================


class TestManifestCorrections:
    """Verify the manifest has correct expected values."""

    def test_case_14_centroid_is_mismatch(self):
        with open(MANIFEST) as f:
            manifest = json.load(f)
        tc = next(t for t in manifest["test_cases"] if t["id"] == "case_14")
        assert tc["expected"]["valid"] is False, \
            "case_14: centroid vs smooth default should be invalid"
        cats = {e["category"] for e in tc["expected"]["errors"]}
        assert "INTERPOLATION_MISMATCH" in cats

    def test_case_15_matching_precision_is_valid(self):
        with open(MANIFEST) as f:
            manifest = json.load(f)
        tc = next(t for t in manifest["test_cases"] if t["id"] == "case_15")
        assert tc["expected"]["valid"] is True, \
            "case_15: both highp should be valid"

    def test_case_16_different_member_names_is_mismatch(self):
        with open(MANIFEST) as f:
            manifest = json.load(f)
        tc = next(t for t in manifest["test_cases"] if t["id"] == "case_16")
        assert tc["expected"]["valid"] is False, \
            "case_16: different struct member names should be invalid"
        cats = {e["category"] for e in tc["expected"]["errors"]}
        assert "STRUCT_MISMATCH" in cats


# =====================================================================
# Diagnostic report verification
# =====================================================================


class TestDiagnosticReport:
    """Verify the diagnostic report is complete, well-formed, and correct."""

    def test_report_exists(self):
        assert os.path.isfile(DIAGNOSTIC_REPORT), \
            f"{DIAGNOSTIC_REPORT} not found"

    def test_report_valid_json_with_required_keys(self):
        with open(DIAGNOSTIC_REPORT) as f:
            report = json.load(f)
        assert isinstance(report, dict)
        for key in ("validator_bugs", "manifest_errors", "defects"):
            assert key in report, f"Missing key: {key}"

    def test_validator_bug_count(self):
        with open(DIAGNOSTIC_REPORT) as f:
            report = json.load(f)
        assert report["validator_bugs"] == 6, \
            f"Expected 6 validator bugs, got {report['validator_bugs']}"

    def test_manifest_error_count(self):
        with open(DIAGNOSTIC_REPORT) as f:
            report = json.load(f)
        assert report["manifest_errors"] == 3, \
            f"Expected 3 manifest errors, got {report['manifest_errors']}"

    def test_defects_list_has_nine_entries(self):
        with open(DIAGNOSTIC_REPORT) as f:
            report = json.load(f)
        defects = report["defects"]
        assert isinstance(defects, list)
        assert len(defects) == 9, f"Expected 9 defect entries, got {len(defects)}"

    def test_each_defect_has_required_fields(self):
        with open(DIAGNOSTIC_REPORT) as f:
            report = json.load(f)
        for i, d in enumerate(report["defects"]):
            assert "source" in d, f"Defect {i}: missing 'source'"
            assert d["source"] in ("validator", "manifest"), \
                f"Defect {i}: source must be 'validator' or 'manifest', got '{d['source']}'"
            assert "affected_cases" in d, f"Defect {i}: missing 'affected_cases'"
            assert isinstance(d["affected_cases"], list), \
                f"Defect {i}: affected_cases must be a list"
            assert len(d["affected_cases"]) > 0, \
                f"Defect {i}: affected_cases must not be empty"
            assert "root_cause" in d, f"Defect {i}: missing 'root_cause'"
            assert len(d["root_cause"]) > 10, \
                f"Defect {i}: root_cause too short"
            assert "fix_applied" in d, f"Defect {i}: missing 'fix_applied'"
            assert len(d["fix_applied"]) > 10, \
                f"Defect {i}: fix_applied too short"

    def test_defect_source_counts_match(self):
        with open(DIAGNOSTIC_REPORT) as f:
            report = json.load(f)
        v_count = sum(1 for d in report["defects"] if d["source"] == "validator")
        m_count = sum(1 for d in report["defects"] if d["source"] == "manifest")
        assert v_count == 6, f"Expected 6 validator defects, got {v_count}"
        assert m_count == 3, f"Expected 3 manifest defects, got {m_count}"

    def test_manifest_cases_14_15_16_identified(self):
        with open(DIAGNOSTIC_REPORT) as f:
            report = json.load(f)
        manifest_defects = [d for d in report["defects"] if d["source"] == "manifest"]
        all_affected = set()
        for d in manifest_defects:
            all_affected.update(d["affected_cases"])
        for case_id in ("case_14", "case_15", "case_16"):
            assert case_id in all_affected, \
                f"{case_id} not identified as a manifest error"
