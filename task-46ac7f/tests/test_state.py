
import json
import os
import subprocess
import pytest


@pytest.fixture(scope="session")
def pipeline_output():
    """Run the shader pipeline and return parsed JSON output."""
    result = subprocess.run(
        ["python3", "/app/shader_pipeline.py"],
        capture_output=True, text=True, cwd="/app",
    )
    assert result.returncode == 0, (
        f"shader_pipeline.py failed with exit code {result.returncode}.\n"
        f"stderr: {result.stderr}\nstdout: {result.stdout[:500]}"
    )
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        pytest.fail(f"Output is not valid JSON: {e}\nstdout: {result.stdout[:500]}")
    return data


def _find_file(data, filename):
    for f in data["files"]:
        if f["filename"] == filename:
            return f
    return None


def _find_stage(data, filename, stage_name):
    f = _find_file(data, filename)
    if f is None:
        return None
    for s in f["stages"]:
        if s["name"] == stage_name:
            return s
    return None


def _find_block(stage, block_name):
    for b in stage["uniform_blocks"]:
        if b["block_name"] == block_name:
            return b
    return None


def _members_dict(block):
    return {m["name"]: m for m in block["members"]}


# ── File-level checks ──────────────────────────────────────────

def test_file_count(pipeline_output):
    filenames = sorted(f["filename"] for f in pipeline_output["files"])
    assert len(filenames) == 5, f"Expected 5 files, got {filenames}"


def test_files_sorted(pipeline_output):
    filenames = [f["filename"] for f in pipeline_output["files"]]
    assert filenames == sorted(filenames), f"Files not sorted: {filenames}"


# ── Compilation and validation ─────────────────────────────────

def test_all_stages_compile(pipeline_output):
    for f in pipeline_output["files"]:
        for s in f["stages"]:
            assert s["compiled"] is True, (
                f"{f['filename']}:{s['name']} failed to compile"
            )


def test_all_stages_validate(pipeline_output):
    for f in pipeline_output["files"]:
        for s in f["stages"]:
            assert s["validated"] is True, (
                f"{f['filename']}:{s['name']} SPIR-V validation failed"
            )


# ── basic.glsl ─────────────────────────────────────────────────

def test_basic_stage_count(pipeline_output):
    f = _find_file(pipeline_output, "basic.glsl")
    assert f is not None
    assert len(f["stages"]) == 2
    names = [s["name"] for s in f["stages"]]
    assert "vs" in names
    assert "fs" in names


def test_basic_vs_params(pipeline_output):
    s = _find_stage(pipeline_output, "basic.glsl", "vs")
    assert s["type"] == "vertex"
    assert len(s["uniform_blocks"]) == 1
    b = _find_block(s, "vs_params")
    assert b is not None
    assert b["binding"] == 0
    m = _members_dict(b)
    assert m["mvp"]["spirv_offset"] == 0
    assert m["mvp"]["computed_offset"] == 0
    assert m["mvp"]["size"] == 64
    assert m["mvp"]["alignment"] == 16
    assert m["tint_color"]["spirv_offset"] == 64
    assert m["tint_color"]["computed_offset"] == 64
    assert m["tint_color"]["size"] == 16
    assert b["total_size"] == 80
    assert b["padding_bytes"] == 0
    assert b["optimized_size"] == 80
    assert b["all_offsets_match"] is True


def test_basic_fs_no_blocks(pipeline_output):
    s = _find_stage(pipeline_output, "basic.glsl", "fs")
    assert s["type"] == "fragment"
    assert len(s["uniform_blocks"]) == 0


def test_basic_programs(pipeline_output):
    f = _find_file(pipeline_output, "basic.glsl")
    assert len(f["programs"]) == 1
    assert f["programs"][0]["name"] == "basic"


# ── lighting.glsl (@block resolution test) ─────────────────────

def test_lighting_block_resolution(pipeline_output):
    """fs_lit uses @include_block fog_util -- compilation proves resolution."""
    s = _find_stage(pipeline_output, "lighting.glsl", "fs_lit")
    assert s is not None
    assert s["compiled"] is True, (
        "fs_lit failed to compile -- @include_block fog_util not resolved"
    )


def test_lighting_vs_uniforms(pipeline_output):
    s = _find_stage(pipeline_output, "lighting.glsl", "vs_lit")
    assert s["type"] == "vertex"
    b = _find_block(s, "vs_uniforms")
    assert b is not None
    m = _members_dict(b)
    assert m["view_proj"]["spirv_offset"] == 0
    assert m["view_proj"]["size"] == 64
    assert m["model"]["spirv_offset"] == 64
    assert m["model"]["size"] == 64
    # vec3 alignment = 16 (the key gotcha)
    assert m["eye_pos"]["spirv_offset"] == 128
    assert m["eye_pos"]["size"] == 12
    assert m["eye_pos"]["alignment"] == 16
    assert b["total_size"] == 144
    assert b["padding_bytes"] == 4
    assert b["optimized_size"] == 144
    assert b["all_offsets_match"] is True


def test_lighting_fs_uniforms(pipeline_output):
    s = _find_stage(pipeline_output, "lighting.glsl", "fs_lit")
    b = _find_block(s, "fs_uniforms")
    assert b is not None
    m = _members_dict(b)
    # vec3 + float packing
    assert m["light_dir"]["spirv_offset"] == 0
    assert m["light_dir"]["size"] == 12
    assert m["light_dir"]["alignment"] == 16
    assert m["light_intensity"]["spirv_offset"] == 12
    assert m["light_color"]["spirv_offset"] == 16
    assert m["ambient_strength"]["spirv_offset"] == 28
    assert m["ambient_color"]["spirv_offset"] == 32
    assert m["specular_power"]["spirv_offset"] == 44
    assert m["fog_color"]["spirv_offset"] == 48
    assert m["fog_density"]["spirv_offset"] == 64
    assert m["fog_start"]["spirv_offset"] == 68
    assert m["uv_scale"]["spirv_offset"] == 72
    assert m["uv_scale"]["size"] == 8
    assert m["uv_scale"]["alignment"] == 8
    assert b["total_size"] == 80
    assert b["padding_bytes"] == 0
    assert b["optimized_size"] == 80
    assert b["all_offsets_match"] is True


# ── compute.glsl (SSBO exclusion test) ─────────────────────────

def test_compute_ssbo_excluded(pipeline_output):
    """Storage buffer (ssbo) must NOT appear in uniform_blocks."""
    s = _find_stage(pipeline_output, "compute.glsl", "cs_particles")
    assert s is not None
    assert s["type"] == "compute"
    assert len(s["uniform_blocks"]) == 1, (
        f"Expected 1 UBO (cs_params only), got {len(s['uniform_blocks'])}: "
        f"{[b['block_name'] for b in s['uniform_blocks']]}"
    )
    assert s["uniform_blocks"][0]["block_name"] == "cs_params"


def test_compute_cs_params(pipeline_output):
    s = _find_stage(pipeline_output, "compute.glsl", "cs_particles")
    b = _find_block(s, "cs_params")
    assert b is not None
    m = _members_dict(b)
    assert m["delta_time"]["spirv_offset"] == 0
    assert m["num_particles"]["spirv_offset"] == 4
    # gravity vec3: align 16, jumps from 8 -> 16
    assert m["gravity"]["spirv_offset"] == 16
    assert m["gravity"]["size"] == 12
    assert m["gravity"]["alignment"] == 16
    assert m["damping"]["spirv_offset"] == 28
    assert m["bounds_min"]["spirv_offset"] == 32
    assert m["bounds_max"]["spirv_offset"] == 48
    assert m["transform"]["spirv_offset"] == 64
    assert m["transform"]["size"] == 64
    assert m["emit_color"]["spirv_offset"] == 128
    assert m["emit_rate"]["spirv_offset"] == 144
    # life_range vec2: align 8, 148 -> 152
    assert m["life_range"]["spirv_offset"] == 152
    assert m["life_range"]["size"] == 8
    assert m["max_particles"]["spirv_offset"] == 160
    assert b["total_size"] == 176
    assert b["padding_bytes"] == 24
    assert b["optimized_size"] == 160
    assert b["all_offsets_match"] is True


# ── pathological.glsl ──────────────────────────────────────────

def test_pathological_offsets(pipeline_output):
    s = _find_stage(pipeline_output, "pathological.glsl", "vs_path")
    assert s is not None
    b = _find_block(s, "path_params")
    assert b is not None
    m = _members_dict(b)
    assert m["a"]["spirv_offset"] == 0
    assert m["b"]["spirv_offset"] == 16
    assert m["c"]["spirv_offset"] == 28
    assert m["d"]["spirv_offset"] == 32
    assert m["e"]["spirv_offset"] == 48
    assert m["f"]["spirv_offset"] == 56
    assert m["g"]["spirv_offset"] == 64
    assert m["h"]["spirv_offset"] == 80
    assert m["h"]["size"] == 64
    assert m["i_val"]["spirv_offset"] == 144
    assert m["j"]["spirv_offset"] == 160
    assert m["k"]["spirv_offset"] == 176
    assert m["l"]["spirv_offset"] == 184
    assert m["m"]["spirv_offset"] == 188
    assert m["n"]["spirv_offset"] == 192
    assert m["o"]["spirv_offset"] == 204
    assert m["p"]["spirv_offset"] == 208
    assert b["total_size"] == 224
    assert b["padding_bytes"] == 44
    assert b["optimized_size"] == 192
    assert b["all_offsets_match"] is True


# ── multipass.glsl ─────────────────────────────────────────────

def test_multipass_stage_count(pipeline_output):
    f = _find_file(pipeline_output, "multipass.glsl")
    assert f is not None
    assert len(f["stages"]) == 4
    names = [s["name"] for s in f["stages"]]
    assert "vs_shadow" in names
    assert "fs_shadow" in names
    assert "vs_main" in names
    assert "fs_main" in names


def test_multipass_programs(pipeline_output):
    f = _find_file(pipeline_output, "multipass.glsl")
    pnames = [p["name"] for p in f["programs"]]
    assert "shadow" in pnames
    assert "main_pass" in pnames


def test_multipass_shadow_params(pipeline_output):
    s = _find_stage(pipeline_output, "multipass.glsl", "vs_shadow")
    b = _find_block(s, "shadow_params")
    assert b is not None
    m = _members_dict(b)
    assert m["light_view_proj"]["spirv_offset"] == 0
    assert m["light_pos"]["spirv_offset"] == 64
    assert m["light_pos"]["size"] == 12
    assert m["near_plane"]["spirv_offset"] == 76
    assert m["far_plane"]["spirv_offset"] == 80
    assert b["total_size"] == 96
    assert b["padding_bytes"] == 12
    assert b["optimized_size"] == 96
    assert b["all_offsets_match"] is True


def test_multipass_vs_main_params(pipeline_output):
    s = _find_stage(pipeline_output, "multipass.glsl", "vs_main")
    b = _find_block(s, "vs_main_params")
    assert b is not None
    m = _members_dict(b)
    assert m["view_proj"]["spirv_offset"] == 0
    assert m["model"]["spirv_offset"] == 64
    assert m["normal_matrix"]["spirv_offset"] == 128
    assert b["total_size"] == 192
    assert b["padding_bytes"] == 0
    assert b["all_offsets_match"] is True


def test_multipass_vs_skinning_arrays(pipeline_output):
    """Tests mat4 array handling."""
    s = _find_stage(pipeline_output, "multipass.glsl", "vs_main")
    b = _find_block(s, "vs_skinning")
    assert b is not None
    assert b["binding"] == 1
    m = _members_dict(b)
    assert m["bones"]["spirv_offset"] == 0
    assert m["bones"]["size"] == 256  # 4 * 64
    assert m["num_active_bones"]["spirv_offset"] == 256
    assert b["total_size"] == 272
    assert b["padding_bytes"] == 12
    assert b["optimized_size"] == 272
    assert b["all_offsets_match"] is True


def test_multipass_fs_material(pipeline_output):
    s = _find_stage(pipeline_output, "multipass.glsl", "fs_main")
    b = _find_block(s, "fs_material")
    assert b is not None
    m = _members_dict(b)
    assert m["base_color"]["spirv_offset"] == 0
    assert m["emissive"]["spirv_offset"] == 16
    assert m["emissive"]["size"] == 12
    assert m["metallic"]["spirv_offset"] == 28
    assert m["roughness"]["spirv_offset"] == 32
    assert m["ao"]["spirv_offset"] == 36
    assert m["uv_transform"]["spirv_offset"] == 40
    assert b["total_size"] == 48
    assert b["padding_bytes"] == 0
    assert b["all_offsets_match"] is True


def test_multipass_fs_lighting_arrays(pipeline_output):
    """Tests vec4 array handling in a complex block."""
    s = _find_stage(pipeline_output, "multipass.glsl", "fs_main")
    b = _find_block(s, "fs_lighting")
    assert b is not None
    assert b["binding"] == 1
    m = _members_dict(b)
    assert m["lights_pos"]["spirv_offset"] == 0
    assert m["lights_pos"]["size"] == 64
    assert m["lights_color"]["spirv_offset"] == 64
    assert m["lights_color"]["size"] == 64
    assert m["lights_params"]["spirv_offset"] == 128
    assert m["lights_params"]["size"] == 64
    assert m["ambient"]["spirv_offset"] == 192
    assert m["ambient"]["size"] == 12
    assert m["num_lights"]["spirv_offset"] == 204
    assert m["shadow_vp"]["spirv_offset"] == 208
    assert m["shadow_vp"]["size"] == 64
    assert m["shadow_light_pos"]["spirv_offset"] == 272
    assert m["shadow_light_pos"]["size"] == 12
    assert m["shadow_bias"]["spirv_offset"] == 284
    assert b["total_size"] == 288
    assert b["padding_bytes"] == 0
    assert b["all_offsets_match"] is True


def test_multipass_block_count(pipeline_output):
    """multipass.glsl should have 5 uniform blocks across its stages."""
    f = _find_file(pipeline_output, "multipass.glsl")
    total = sum(len(s["uniform_blocks"]) for s in f["stages"])
    assert total == 5, f"Expected 5 uniform blocks total, got {total}"


def test_multipass_block_resolution(pipeline_output):
    """fs_main uses @include_block shared_types -- compilation proves resolution."""
    s = _find_stage(pipeline_output, "multipass.glsl", "fs_main")
    assert s["compiled"] is True


# ── Cross-validation across all blocks ─────────────────────────

def test_all_offsets_match(pipeline_output):
    """Every uniform block should have all SPIR-V offsets matching computed."""
    for f in pipeline_output["files"]:
        for s in f["stages"]:
            for b in s["uniform_blocks"]:
                assert b["all_offsets_match"] is True, (
                    f"{f['filename']}:{s['name']}:{b['block_name']} "
                    f"has offset mismatches"
                )


def test_total_block_count(pipeline_output):
    total = sum(
        len(s["uniform_blocks"])
        for f in pipeline_output["files"]
        for s in f["stages"]
    )
    assert total == 10, f"Expected 10 uniform blocks total, got {total}"


# ── Dynamic shader (anti-cheat) ────────────────────────────────

def test_dynamic_shader():
    """Create a previously unseen shader and verify full pipeline analysis."""
    dynamic_glsl = """\
@vs vs_dynamic
layout(binding=0) uniform dynamic_params {
    vec2 pos;
    vec3 normal;
    float scale;
    mat4 transform;
    vec4 color;
    int flags;
    vec3 velocity;
    float mass;
};
in vec4 position;
void main() { gl_Position = transform * position * scale; }
@end
@fs fs_dynamic
out vec4 frag_color;
void main() { frag_color = vec4(1.0); }
@end
@program dynamic vs_dynamic fs_dynamic
"""
    path = "/app/shaders/dynamic.glsl"
    try:
        with open(path, "w") as f:
            f.write(dynamic_glsl)
        result = subprocess.run(
            ["python3", "/app/shader_pipeline.py"],
            capture_output=True, text=True, cwd="/app",
        )
        assert result.returncode == 0, f"Pipeline failed: {result.stderr}"
        data = json.loads(result.stdout)

        # Find dynamic stage
        stage = None
        for fe in data["files"]:
            if fe["filename"] == "dynamic.glsl":
                for s in fe["stages"]:
                    if s["name"] == "vs_dynamic":
                        stage = s
                        break
        assert stage is not None, "vs_dynamic stage not found"
        assert stage["compiled"] is True
        assert stage["validated"] is True

        b = None
        for bl in stage["uniform_blocks"]:
            if bl["block_name"] == "dynamic_params":
                b = bl
                break
        assert b is not None, "dynamic_params block not found"

        m = {mem["name"]: mem for mem in b["members"]}
        # pos (vec2): offset 0
        assert m["pos"]["spirv_offset"] == 0
        assert m["pos"]["size"] == 8
        # normal (vec3): align 16, jump to 16
        assert m["normal"]["spirv_offset"] == 16
        assert m["normal"]["size"] == 12
        assert m["normal"]["alignment"] == 16
        # scale (float): packs at 28
        assert m["scale"]["spirv_offset"] == 28
        # transform (mat4): align 16, offset 32
        assert m["transform"]["spirv_offset"] == 32
        assert m["transform"]["size"] == 64
        # color (vec4): offset 96
        assert m["color"]["spirv_offset"] == 96
        # flags (int): offset 112
        assert m["flags"]["spirv_offset"] == 112
        # velocity (vec3): align 16, jump to 128
        assert m["velocity"]["spirv_offset"] == 128
        # mass (float): packs at 140
        assert m["mass"]["spirv_offset"] == 140
        assert b["total_size"] == 144
        assert b["padding_bytes"] == 20
        assert b["optimized_size"] == 128
        assert b["all_offsets_match"] is True
    finally:
        if os.path.exists(path):
            os.remove(path)
