
"""
Tests for the WGSL-to-C Memory Layout Bridge.

Verifies that:
  - reference_layouts.json has been corrected to match the WGSL spec
  - conformance_report.json conforms to the documented schema
  - generated C11 code compiles with gcc and passes static_assert checks
  - layout values match WGSL specification
"""

import json
import os
import subprocess
import tempfile


# ============================================================
# Reference layout correction tests
# ============================================================

def _load_reference():
    with open("/app/reference_layouts.json") as f:
        return json.load(f)


def test_reference_lightdata_direction_alignment():
    """LightData direction alignment must be 16 (vec3 rule: 4*AlignOf(f32))."""
    ref = _load_reference()
    assert ref["LightData"]["members"]["direction"]["alignment"] == 16, \
        "vec3<f32> alignment should be 4*4=16, not 3*4=12"


def test_reference_transformdata_normalmatrix_size():
    """TransformData normal_matrix size must be 48 (array<vec3<f32>,3>: 3*16)."""
    ref = _load_reference()
    assert ref["TransformData"]["members"]["normal_matrix"]["size"] == 48, \
        "mat3x3<f32> size should be 3*stride(vec3)=3*16=48, not 3*3*4=36"


def test_reference_packeddata_struct_size():
    """PackedData struct size must be 80 (roundUp(16, 76) = 80)."""
    ref = _load_reference()
    assert ref["PackedData"]["size"] == 80, \
        "struct size must be rounded up to struct alignment: roundUp(16, 76) = 80"


def test_reference_basicvertex_unchanged():
    """BasicVertex should remain correct (no errors in original)."""
    ref = _load_reference()
    bv = ref["BasicVertex"]
    assert bv["alignment"] == 16
    assert bv["size"] == 32
    assert bv["members"]["position"]["offset"] == 0
    assert bv["members"]["tex_coord"]["offset"] == 16
    assert bv["members"]["normal_x"]["offset"] == 24
    assert bv["members"]["normal_y"]["offset"] == 28


def test_reference_sceneuniforms_layout():
    """SceneUniforms uniform layout must have correct offsets and sizes."""
    ref = _load_reference()
    su = ref["SceneUniforms"]
    assert su["address_space"] == "uniform"
    assert su["alignment"] == 16
    assert su["size"] == 160
    assert su["members"]["view_proj"]["offset"] == 0
    assert su["members"]["view_proj"]["size"] == 64
    assert su["members"]["camera_pos"]["offset"] == 64
    assert su["members"]["time"]["offset"] == 76
    assert su["members"]["ambient_color"]["offset"] == 80
    assert su["members"]["ambient_color"]["size"] == 64
    assert su["members"]["main_light"]["offset"] == 144
    assert su["members"]["main_light"]["size"] == 16


# ============================================================
# Conformance report tests
# ============================================================

def test_conformance_report_exists():
    """Conformance report must exist at /app/conformance_report.json."""
    assert os.path.exists("/app/conformance_report.json"), \
        "conformance_report.json not found"


def test_conformance_report_schema():
    """Report must conform to the documented JSON schema."""
    with open("/app/conformance_report.json") as f:
        report = json.load(f)
    assert isinstance(report, dict), "report must be a JSON object"
    for name, entry in report.items():
        assert "status" in entry, f"{name} missing 'status' field"
        assert entry["status"] in ("PASS", "FAIL"), \
            f"{name} status must be 'PASS' or 'FAIL', got '{entry['status']}'"
        assert "discrepancies" in entry, f"{name} missing 'discrepancies' field"
        assert isinstance(entry["discrepancies"], list), \
            f"{name} discrepancies must be an array"
        for d in entry["discrepancies"]:
            assert "field" in d, f"{name} discrepancy missing 'field'"
            assert "reference" in d, f"{name} discrepancy missing 'reference'"
            assert "correct" in d, f"{name} discrepancy missing 'correct'"


def test_conformance_report_identifies_failures():
    """Report must identify exactly LightData, TransformData, PackedData as FAIL."""
    with open("/app/conformance_report.json") as f:
        report = json.load(f)
    failing = {name for name, info in report.items() if info.get("status") == "FAIL"}
    assert failing == {"LightData", "TransformData", "PackedData"}, \
        f"Expected 3 failing structs, got: {failing}"


def test_conformance_report_passing():
    """Report must identify BasicVertex and SceneUniforms as PASS."""
    with open("/app/conformance_report.json") as f:
        report = json.load(f)
    for name in ["BasicVertex", "SceneUniforms"]:
        assert report[name]["status"] == "PASS", \
            f"{name} should be PASS but got {report[name]['status']}"


def test_conformance_report_discrepancy_values():
    """Report must show correct before/after values for each error."""
    with open("/app/conformance_report.json") as f:
        report = json.load(f)

    ld = report["LightData"]["discrepancies"]
    assert any(d["reference"] == 12 and d["correct"] == 16 for d in ld), \
        "LightData should flag direction alignment 12->16"

    td = report["TransformData"]["discrepancies"]
    assert any(d["reference"] == 36 and d["correct"] == 48 for d in td), \
        "TransformData should flag normal_matrix size 36->48"

    pd = report["PackedData"]["discrepancies"]
    assert any(d["reference"] == 76 and d["correct"] == 80 for d in pd), \
        "PackedData should flag struct size 76->80"


def test_conformance_report_pass_empty_discrepancies():
    """PASS entries must have empty discrepancies arrays."""
    with open("/app/conformance_report.json") as f:
        report = json.load(f)
    for name in ["BasicVertex", "SceneUniforms"]:
        assert report[name]["discrepancies"] == [], \
            f"{name} is PASS but has non-empty discrepancies"


# ============================================================
# C code generation + gcc compilation tests
# ============================================================

STRUCT_NAMES = ["BasicVertex", "LightData", "TransformData",
                "SceneUniforms", "PackedData"]


def _compile_and_run(struct_name):
    """Compile a generated C file with gcc and run the binary."""
    c_file = f"/app/generated/{struct_name}.c"
    assert os.path.exists(c_file), f"{c_file} does not exist"

    with tempfile.NamedTemporaryFile(suffix=f"_{struct_name}", delete=False) as tmp:
        binary = tmp.name

    try:
        comp = subprocess.run(
            ["gcc", "-std=c11", "-Wall", "-Werror", "-o", binary, c_file],
            capture_output=True, text=True, timeout=30)
        assert comp.returncode == 0, \
            f"gcc compilation failed for {struct_name}:\n{comp.stderr}"

        run = subprocess.run(
            [binary], capture_output=True, text=True, timeout=10)
        assert run.returncode == 0, \
            f"{struct_name} binary exited with code {run.returncode}"
        assert "ALL_LAYOUT_CHECKS_PASSED" in run.stdout, \
            f"{struct_name} did not pass layout checks:\n{run.stdout}"
    finally:
        if os.path.exists(binary):
            os.unlink(binary)


def test_gcc_basic_vertex():
    """BasicVertex C code must compile and pass all static_assert checks."""
    _compile_and_run("BasicVertex")


def test_gcc_light_data():
    """LightData C code (vec3 types) must compile and pass."""
    _compile_and_run("LightData")


def test_gcc_transform_data():
    """TransformData C code (matrix types) must compile and pass."""
    _compile_and_run("TransformData")


def test_gcc_scene_uniforms():
    """SceneUniforms C code (uniform address space) must compile and pass."""
    _compile_and_run("SceneUniforms")


def test_gcc_packed_data():
    """PackedData C code (@align/@size attributes) must compile and pass."""
    _compile_and_run("PackedData")


# ============================================================
# Layout value spot checks (independent of C generation)
# ============================================================

def test_lightdata_full_layout():
    """LightData: verify all corrected member layouts."""
    ref = _load_reference()
    ld = ref["LightData"]
    assert ld["alignment"] == 16
    assert ld["size"] == 32
    assert ld["members"]["direction"]["offset"] == 0
    assert ld["members"]["direction"]["alignment"] == 16
    assert ld["members"]["direction"]["size"] == 12
    assert ld["members"]["intensity"]["offset"] == 12
    assert ld["members"]["color"]["offset"] == 16
    assert ld["members"]["color"]["alignment"] == 16
    assert ld["members"]["radius"]["offset"] == 28


def test_transformdata_full_layout():
    """TransformData: verify all corrected member layouts."""
    ref = _load_reference()
    td = ref["TransformData"]
    assert td["alignment"] == 16
    assert td["size"] == 144
    assert td["members"]["model"]["offset"] == 0
    assert td["members"]["model"]["size"] == 64
    assert td["members"]["normal_matrix"]["offset"] == 64
    assert td["members"]["normal_matrix"]["size"] == 48
    assert td["members"]["tex_transform"]["offset"] == 112
    assert td["members"]["tex_transform"]["size"] == 32


def test_packeddata_full_layout():
    """PackedData: verify all member layouts including @align/@size effects."""
    ref = _load_reference()
    pd = ref["PackedData"]
    assert pd["alignment"] == 16
    assert pd["size"] == 80
    assert pd["members"]["flags"]["offset"] == 0
    assert pd["members"]["transform"]["offset"] == 16
    assert pd["members"]["transform"]["alignment"] == 16
    assert pd["members"]["transform"]["size"] == 32
    assert pd["members"]["weight"]["offset"] == 48
    assert pd["members"]["indices"]["offset"] == 64
    assert pd["members"]["indices"]["size"] == 12
