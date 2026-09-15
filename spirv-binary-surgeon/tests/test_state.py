
import subprocess
import json
import os
import struct
import pytest


def run_surgeon(*args):
    """Helper to run spirv_surgeon.py and return the result."""
    result = subprocess.run(
        ["python3", "/app/spirv_surgeon.py"] + list(args),
        capture_output=True, text=True, timeout=30
    )
    return result


class TestAnalyze:
    def test_vertex_entry_point(self):
        r = run_surgeon("analyze", "/app/modules/vertex.spv")
        assert r.returncode == 0, f"Failed: {r.stderr}"
        data = json.loads(r.stdout)
        eps = data["entry_points"]
        assert len(eps) == 1
        assert eps[0]["name"] == "main"
        assert eps[0]["execution_model"] == "Vertex"

    def test_vertex_capabilities(self):
        r = run_surgeon("analyze", "/app/modules/vertex.spv")
        data = json.loads(r.stdout)
        assert "Shader" in data["capabilities"]

    def test_vertex_descriptor_bindings(self):
        r = run_surgeon("analyze", "/app/modules/vertex.spv")
        data = json.loads(r.stdout)
        decorations = data["decorations"]
        found_set0 = False
        found_set1 = False
        for id_str, decs in decorations.items():
            for d in decs:
                if d.get("name") == "DescriptorSet":
                    if d["value"] == 0:
                        found_set0 = True
                    elif d["value"] == 1:
                        found_set1 = True
        assert found_set0, "Should find descriptor set 0"
        assert found_set1, "Should find descriptor set 1"

    def test_vertex_push_constants(self):
        r = run_surgeon("analyze", "/app/modules/vertex.spv")
        data = json.loads(r.stdout)
        pc_vars = [v for v in data["variables"] if v["storage_class"] == "PushConstant"]
        assert len(pc_vars) >= 1, "Should have push constants"

    def test_header_magic(self):
        r = run_surgeon("analyze", "/app/modules/vertex.spv")
        data = json.loads(r.stdout)
        assert data["header"]["magic"] == "0x07230203"

    def test_memory_model(self):
        r = run_surgeon("analyze", "/app/modules/vertex.spv")
        data = json.loads(r.stdout)
        assert data["memory_model"]["addressing"] == "Logical"
        assert data["memory_model"]["model"] == "GLSL450"

    def test_types_include_matrix(self):
        r = run_surgeon("analyze", "/app/modules/vertex.spv")
        data = json.loads(r.stdout)
        matrix_types = [t for t in data["types"].values() if t["kind"] == "matrix"]
        assert len(matrix_types) > 0, "Vertex shader should have matrix types"

    def test_compute_workgroup_size(self):
        r = run_surgeon("analyze", "/app/modules/compute.spv")
        data = json.loads(r.stdout)
        local_sizes = [m for m in data["execution_modes"] if "local_size" in m]
        assert len(local_sizes) > 0, "Should have local_size execution mode"
        assert local_sizes[0]["local_size"] == [256, 1, 1]

    def test_compute_buffer_variables(self):
        r = run_surgeon("analyze", "/app/modules/compute.spv")
        data = json.loads(r.stdout)
        buffer_vars = [v for v in data["variables"]
                       if v["storage_class"] in ("StorageBuffer", "Uniform")]
        assert len(buffer_vars) >= 3, \
            f"Should have at least 3 buffer variables (2 SSBOs + 1 UBO), got {len(buffer_vars)}"

    def test_fragment_sampled_image(self):
        r = run_surgeon("analyze", "/app/modules/fragment.spv")
        data = json.loads(r.stdout)
        uniform_consts = [v for v in data["variables"]
                          if v["storage_class"] == "UniformConstant"]
        assert len(uniform_consts) >= 1, "Should have at least 1 uniform constant (sampler)"

    def test_fragment_entry_point(self):
        r = run_surgeon("analyze", "/app/modules/fragment.spv")
        data = json.loads(r.stdout)
        assert data["entry_points"][0]["execution_model"] == "Fragment"
        assert data["entry_points"][0]["name"] == "main"

    def test_handcrafted_module(self):
        r = run_surgeon("analyze", "/app/modules/custom.spv")
        assert r.returncode == 0, f"Failed on hand-crafted module: {r.stderr}"
        data = json.loads(r.stdout)
        assert data["entry_points"][0]["name"] == "main"
        assert data["entry_points"][0]["execution_model"] == "GLCompute"
        local_sizes = [m for m in data["execution_modes"] if "local_size" in m]
        assert len(local_sizes) > 0
        assert local_sizes[0]["local_size"] == [64, 1, 1]

    def test_handcrafted_names(self):
        r = run_surgeon("analyze", "/app/modules/custom.spv")
        data = json.loads(r.stdout)
        name_values = list(data.get("names", {}).values())
        assert "main" in name_values, "Should find OpName 'main'"
        assert "params" in name_values, "Should find OpName 'params'"


class TestRemap:
    def test_remap_validates(self):
        r = run_surgeon("remap", "/app/modules/vertex.spv",
                        "/tmp/remapped_vertex.spv", "/app/remap_config.json")
        assert r.returncode == 0, f"Remap failed: {r.stderr}"
        val = subprocess.run(["spirv-val", "/tmp/remapped_vertex.spv"],
                             capture_output=True, text=True)
        assert val.returncode == 0, f"Validation failed: {val.stderr}"

    def test_remap_changes_descriptor_sets(self):
        run_surgeon("remap", "/app/modules/vertex.spv",
                    "/tmp/remapped_vertex2.spv", "/app/remap_config.json")
        r = run_surgeon("analyze", "/tmp/remapped_vertex2.spv")
        data = json.loads(r.stdout)
        all_sets = set()
        for id_str, decs in data["decorations"].items():
            for d in decs:
                if d.get("name") == "DescriptorSet":
                    all_sets.add(d["value"])
        assert 2 in all_sets, "Should have descriptor set 2 (remapped from 0)"
        assert 3 in all_sets, "Should have descriptor set 3 (remapped from 1)"
        assert 0 not in all_sets, "Should not have descriptor set 0 after remapping"
        assert 1 not in all_sets, "Should not have descriptor set 1 after remapping"

    def test_remap_preserves_bindings(self):
        run_surgeon("remap", "/app/modules/vertex.spv",
                    "/tmp/remapped_vertex3.spv", "/app/remap_config.json")
        r = run_surgeon("analyze", "/tmp/remapped_vertex3.spv")
        data = json.loads(r.stdout)
        all_bindings = set()
        for id_str, decs in data["decorations"].items():
            for d in decs:
                if d.get("name") == "Binding":
                    all_bindings.add(d["value"])
        assert 0 in all_bindings, "Binding 0 should still exist"

    def test_remap_compute_validates(self):
        r = run_surgeon("remap", "/app/modules/compute.spv",
                        "/tmp/remapped_compute.spv", "/app/remap_config.json")
        assert r.returncode == 0
        val = subprocess.run(["spirv-val", "/tmp/remapped_compute.spv"],
                             capture_output=True, text=True)
        assert val.returncode == 0, f"Validation failed: {val.stderr}"

    def test_remap_fragment_validates(self):
        r = run_surgeon("remap", "/app/modules/fragment.spv",
                        "/tmp/remapped_fragment.spv", "/app/remap_config.json")
        assert r.returncode == 0
        val = subprocess.run(["spirv-val", "/tmp/remapped_fragment.spv"],
                             capture_output=True, text=True)
        assert val.returncode == 0, f"Validation failed: {val.stderr}"

    def test_remap_custom_validates(self):
        r = run_surgeon("remap", "/app/modules/custom.spv",
                        "/tmp/remapped_custom.spv", "/app/remap_config.json")
        assert r.returncode == 0
        val = subprocess.run(["spirv-val", "/tmp/remapped_custom.spv"],
                             capture_output=True, text=True)
        assert val.returncode == 0, f"Validation failed: {val.stderr}"


class TestStripDebug:
    def test_strip_debug_validates(self):
        r = run_surgeon("strip-debug", "/app/modules/vertex.spv",
                        "/tmp/stripped_vertex.spv")
        assert r.returncode == 0, f"Strip-debug failed: {r.stderr}"
        val = subprocess.run(["spirv-val", "/tmp/stripped_vertex.spv"],
                             capture_output=True, text=True)
        assert val.returncode == 0, f"Validation failed: {val.stderr}"

    def test_strip_debug_removes_names(self):
        run_surgeon("strip-debug", "/app/modules/vertex.spv",
                    "/tmp/stripped_vertex2.spv")
        dis = subprocess.run(["spirv-dis", "/tmp/stripped_vertex2.spv"],
                             capture_output=True, text=True)
        assert "OpName" not in dis.stdout, "Should have no OpName after stripping"
        assert "OpMemberName" not in dis.stdout, "Should have no OpMemberName"

    def test_strip_debug_smaller(self):
        run_surgeon("strip-debug", "/app/modules/vertex.spv",
                    "/tmp/stripped_vertex3.spv")
        orig = os.path.getsize("/app/modules/vertex.spv")
        stripped = os.path.getsize("/tmp/stripped_vertex3.spv")
        assert stripped < orig, f"Stripped ({stripped}) should be smaller than original ({orig})"

    def test_strip_debug_preserves_entry_point(self):
        run_surgeon("strip-debug", "/app/modules/vertex.spv",
                    "/tmp/stripped_vertex4.spv")
        r = run_surgeon("analyze", "/tmp/stripped_vertex4.spv")
        data = json.loads(r.stdout)
        assert len(data["entry_points"]) == 1
        assert data["entry_points"][0]["name"] == "main"
        assert data["entry_points"][0]["execution_model"] == "Vertex"

    def test_strip_debug_compute_validates(self):
        r = run_surgeon("strip-debug", "/app/modules/compute.spv",
                        "/tmp/stripped_compute.spv")
        assert r.returncode == 0
        val = subprocess.run(["spirv-val", "/tmp/stripped_compute.spv"],
                             capture_output=True, text=True)
        assert val.returncode == 0, f"Validation failed: {val.stderr}"

    def test_strip_debug_custom_validates(self):
        r = run_surgeon("strip-debug", "/app/modules/custom.spv",
                        "/tmp/stripped_custom.spv")
        assert r.returncode == 0
        val = subprocess.run(["spirv-val", "/tmp/stripped_custom.spv"],
                             capture_output=True, text=True)
        assert val.returncode == 0, f"Validation failed: {val.stderr}"

    def test_strip_debug_no_source_instructions(self):
        run_surgeon("strip-debug", "/app/modules/compute.spv",
                    "/tmp/stripped_compute2.spv")
        dis = subprocess.run(["spirv-dis", "/tmp/stripped_compute2.spv"],
                             capture_output=True, text=True)
        assert "OpSource" not in dis.stdout, "Should have no OpSource after stripping"
        assert "OpModuleProcessed" not in dis.stdout, "Should have no OpModuleProcessed"


class TestMergeReflection:
    def test_merge_all_stages(self):
        r = run_surgeon("merge-reflection",
                        "/app/modules/vertex.spv",
                        "/app/modules/fragment.spv",
                        "/app/modules/compute.spv")
        assert r.returncode == 0, f"Merge failed: {r.stderr}"
        data = json.loads(r.stdout)
        assert len(data["modules"]) == 3

    def test_merge_vertex_fragment_bindings(self):
        r = run_surgeon("merge-reflection",
                        "/app/modules/vertex.spv",
                        "/app/modules/fragment.spv")
        data = json.loads(r.stdout)
        assert len(data["modules"]) == 2
        all_bindings = []
        for mod in data["modules"]:
            for b in mod.get("bindings", []):
                all_bindings.append((b.get("set"), b.get("binding")))
        assert (0, 0) in all_bindings, "Should find set=0, binding=0 (CameraUBO)"
        assert (1, 0) in all_bindings, "Should find set=1, binding=0 (ModelUBO)"
        assert (0, 1) in all_bindings, "Should find set=0, binding=1 (texSampler)"
        assert (0, 2) in all_bindings, "Should find set=0, binding=2 (LightUBO)"

    def test_merge_push_constants(self):
        r = run_surgeon("merge-reflection",
                        "/app/modules/vertex.spv",
                        "/app/modules/compute.spv")
        data = json.loads(r.stdout)
        has_pc = [mod for mod in data["modules"] if mod.get("push_constants")]
        assert len(has_pc) == 2, "Both vertex and compute have push constants"

    def test_merge_io_interface(self):
        r = run_surgeon("merge-reflection",
                        "/app/modules/vertex.spv",
                        "/app/modules/fragment.spv")
        data = json.loads(r.stdout)
        # Find vertex module
        vertex_mod = None
        fragment_mod = None
        for mod in data["modules"]:
            for ep in mod.get("entry_points", []):
                if ep.get("execution_model") == "Vertex":
                    vertex_mod = mod
                elif ep.get("execution_model") == "Fragment":
                    fragment_mod = mod
        assert vertex_mod is not None, "Should find vertex module"
        assert fragment_mod is not None, "Should find fragment module"
        # Vertex has 3 inputs and 3 outputs (plus gl_Position built-in)
        assert len(vertex_mod.get("inputs", [])) >= 3, "Vertex should have >= 3 inputs"
        assert len(vertex_mod.get("outputs", [])) >= 3, "Vertex should have >= 3 outputs"
        # Fragment has 3 inputs and 1 output
        assert len(fragment_mod.get("inputs", [])) >= 3, "Fragment should have >= 3 inputs"
        assert len(fragment_mod.get("outputs", [])) >= 1, "Fragment should have >= 1 output"


class TestBinaryParsing:
    def test_no_spirv_dis_dependency(self):
        """Verify the tool does not shell out to spirv-dis for analysis."""
        spirv_dis_path = None
        for path in ["/usr/bin/spirv-dis", "/usr/local/bin/spirv-dis"]:
            if os.path.exists(path):
                spirv_dis_path = path
                break
        if spirv_dis_path is None:
            pytest.skip("spirv-dis not found")

        backup_path = spirv_dis_path + ".backup"
        os.rename(spirv_dis_path, backup_path)
        try:
            r = run_surgeon("analyze", "/app/modules/vertex.spv")
            assert r.returncode == 0, \
                f"Analysis must work without spirv-dis (direct binary parsing): {r.stderr}"
            data = json.loads(r.stdout)
            assert data["entry_points"][0]["name"] == "main"
        finally:
            os.rename(backup_path, spirv_dis_path)

    def test_output_binary_structure(self):
        """Verify output SPIR-V has valid binary structure."""
        run_surgeon("remap", "/app/modules/vertex.spv",
                    "/tmp/binary_check.spv", "/app/remap_config.json")
        with open("/tmp/binary_check.spv", "rb") as f:
            data = f.read()
        assert len(data) >= 20, "Output too short"
        magic = struct.unpack('<I', data[:4])[0]
        assert magic == 0x07230203, f"Invalid magic: 0x{magic:08x}"
        words = struct.unpack(f'<{len(data)//4}I', data)
        pos = 5
        while pos < len(words):
            wc = words[pos] >> 16
            assert wc > 0, f"Zero word count at word {pos}"
            assert pos + wc <= len(words), f"Instruction overflow at word {pos}"
            pos += wc
        assert pos == len(words), "Instructions should exactly fill the module"

    def test_roundtrip_identity(self):
        """Parse and re-serialize without changes should produce identical binary."""
        # Remap with empty mapping = identity
        empty_map = "/tmp/empty_map.json"
        with open(empty_map, "w") as f:
            json.dump({}, f)
        run_surgeon("remap", "/app/modules/custom.spv",
                    "/tmp/roundtrip.spv", empty_map)
        with open("/app/modules/custom.spv", "rb") as f:
            orig = f.read()
        with open("/tmp/roundtrip.spv", "rb") as f:
            rt = f.read()
        assert orig == rt, "Round-trip with empty mapping should produce identical binary"
