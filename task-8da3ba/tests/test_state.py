"""Tests for the RDLA Scene Graph Analyzer."""

import subprocess
import json
import os
import pytest

ANALYZER_PATH = "/app/rdla_analyzer.py"
SCENES_DIR = "/app/scenes"


def run_analyzer(scene_file):
    """Run the RDLA analyzer on a scene file and return parsed JSON output."""
    result = subprocess.run(
        ["python3", ANALYZER_PATH, scene_file],
        capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, f"Analyzer failed with exit code {result.returncode}.\nstderr: {result.stderr}\nstdout: {result.stdout}"
    output = json.loads(result.stdout)
    assert "objects" in output, "Missing 'objects' key in output"
    assert "bindings" in output, "Missing 'bindings' key in output"
    assert "scene_variables" in output, "Missing 'scene_variables' key in output"
    assert "issues" in output, "Missing 'issues' key in output"
    assert "complexity_score" in output, "Missing 'complexity_score' key in output"
    return output


# ============================================================
# Scene 1: valid_cornell.rdla — valid Cornell Box, no issues
# ============================================================

class TestValidCornell:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.result = run_analyzer(os.path.join(SCENES_DIR, "valid_cornell.rdla"))

    def test_object_count(self):
        assert len(self.result["objects"]) == 19

    def test_camera(self):
        objs = {o["name"]: o["type"] for o in self.result["objects"]}
        assert objs["/scene/camera"] == "PerspectiveCamera"

    def test_materials(self):
        objs = {o["name"]: o["type"] for o in self.result["objects"]}
        assert objs["/scene/surfacing/white_wall"] == "DwaBaseMaterial"
        assert objs["/scene/surfacing/red_wall"] == "DwaBaseMaterial"
        assert objs["/scene/surfacing/green_wall"] == "DwaBaseMaterial"
        assert objs["/scene/surfacing/glass_sphere"] == "DwaSolidDielectricMaterial"
        assert objs["/scene/surfacing/metal_box"] == "DwaMetalMaterial"

    def test_maps(self):
        objs = {o["name"]: o["type"] for o in self.result["objects"]}
        assert objs["/scene/maps/glass_checker"] == "CheckerboardMap"

    def test_geometries(self):
        objs = {o["name"]: o["type"] for o in self.result["objects"]}
        assert objs["/scene/geometry/floor"] == "RdlMeshGeometry"
        assert objs["/scene/geometry/ceiling"] == "RdlMeshGeometry"
        assert objs["/scene/geometry/glass_ball"] == "SphereGeometry"
        assert objs["/scene/geometry/tall_box"] == "BoxGeometry"
        assert objs["/scene/geometry/left_wall"] == "RdlMeshGeometry"
        assert objs["/scene/geometry/right_wall"] == "RdlMeshGeometry"
        assert objs["/scene/geometry/back_wall"] == "RdlMeshGeometry"

    def test_lights(self):
        objs = {o["name"]: o["type"] for o in self.result["objects"]}
        assert objs["/scene/lights/ceiling_light"] == "RectLight"

    def test_scene_org(self):
        objs = {o["name"]: o["type"] for o in self.result["objects"]}
        assert objs["/scene/light_set"] == "LightSet"
        assert objs["/scene/geo_set"] == "GeometrySet"
        assert objs["/scene/render_layer"] == "Layer"
        assert objs["/scene/output/beauty"] == "RenderOutput"

    def test_binding_count(self):
        assert len(self.result["bindings"]) == 1

    def test_binding_glass_checker(self):
        b = self.result["bindings"][0]
        assert b["source"] == "/scene/surfacing/glass_sphere"
        assert b["attribute"] == "albedo"
        assert b["target"] == "/scene/maps/glass_checker"

    def test_scene_variables(self):
        sv = self.result["scene_variables"]
        assert sv["image_width"] == 512
        assert sv["image_height"] == 512
        assert sv["pixel_samples"] == 64
        assert sv["max_depth"] == 8

    def test_no_issues(self):
        assert len(self.result["issues"]) == 0

    def test_complexity_score(self):
        # G=7, S=64, D=8, T=1, L=1
        # 7*64*(8^1.5)*(1+0.5)*(1+0.3) = 19767.31
        assert abs(self.result["complexity_score"] - 19767.31) < 0.02


# ============================================================
# Scene 2: cyclic_maps.rdla — circular dependency in map chain
# ============================================================

class TestCyclicMaps:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.result = run_analyzer(os.path.join(SCENES_DIR, "cyclic_maps.rdla"))

    def test_object_count(self):
        assert len(self.result["objects"]) == 10

    def test_noise_maps(self):
        objs = {o["name"]: o["type"] for o in self.result["objects"]}
        assert objs["/scene/maps/noise_a"] == "NoiseMap"
        assert objs["/scene/maps/noise_b"] == "NoiseMap"

    def test_binding_count(self):
        assert len(self.result["bindings"]) == 3

    def test_bindings(self):
        bset = {(b["source"], b["attribute"], b["target"]) for b in self.result["bindings"]}
        assert ("/scene/surfacing/wall", "albedo", "/scene/maps/noise_a") in bset
        assert ("/scene/maps/noise_a", "input", "/scene/maps/noise_b") in bset
        assert ("/scene/maps/noise_b", "input", "/scene/maps/noise_a") in bset

    def test_circular_dependency_detected(self):
        cycle_issues = [i for i in self.result["issues"] if i["type"] == "circular_dependency"]
        assert len(cycle_issues) >= 1
        cycle = cycle_issues[0]["cycle"]
        assert "/scene/maps/noise_a" in cycle
        assert "/scene/maps/noise_b" in cycle

    def test_no_other_issue_types(self):
        non_cycle = [i for i in self.result["issues"] if i["type"] != "circular_dependency"]
        assert len(non_cycle) == 0

    def test_complexity_score(self):
        # G=1, S=16, D=5, T=0, L=1
        # 1*16*(5^1.5)*(1)*(1.3) = 232.55
        assert abs(self.result["complexity_score"] - 232.55) < 0.02


# ============================================================
# Scene 3: multi_issue.rdla — multiple validation issues
# ============================================================

class TestMultiIssue:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.result = run_analyzer(os.path.join(SCENES_DIR, "multi_issue.rdla"))

    def test_object_count(self):
        assert len(self.result["objects"]) == 12

    def test_object_types(self):
        objs = {o["name"]: o["type"] for o in self.result["objects"]}
        assert objs["/scene/surfacing/bad_glass"] == "DwaSolidDielectricMaterial"
        assert objs["/scene/surfacing/textured"] == "DwaBaseMaterial"
        assert objs["/scene/surfacing/unused_fabric"] == "DwaFabricMaterial"
        assert objs["/scene/surfacing/floor_mat"] == "DwaBaseMaterial"
        assert objs["/scene/lights/key"] == "RectLight"
        assert objs["/scene/lights/fill"] == "DistantLight"

    def test_binding_count(self):
        assert len(self.result["bindings"]) == 1

    def test_binding_to_missing(self):
        b = self.result["bindings"][0]
        assert b["source"] == "/scene/surfacing/textured"
        assert b["attribute"] == "albedo"
        assert b["target"] == "/scene/maps/missing_texture"

    def test_unresolved_reference(self):
        unresolved = [i for i in self.result["issues"] if i["type"] == "unresolved_reference"]
        assert len(unresolved) >= 1
        ur = unresolved[0]
        assert ur["source"] == "/scene/surfacing/textured"
        assert ur["attribute"] == "albedo"
        assert ur["target"] == "/scene/maps/missing_texture"

    def test_invalid_ior(self):
        invalid_ior = [i for i in self.result["issues"]
                       if i["type"] == "invalid_parameter" and i.get("attribute") == "ior"]
        assert len(invalid_ior) >= 1
        ip = invalid_ior[0]
        assert ip["object"] == "/scene/surfacing/bad_glass"
        assert ip["value"] == 0.5

    def test_invalid_roughness(self):
        invalid_rough = [i for i in self.result["issues"]
                         if i["type"] == "invalid_parameter" and i.get("attribute") == "roughness"]
        assert len(invalid_rough) >= 1
        ip = invalid_rough[0]
        assert ip["object"] == "/scene/surfacing/unused_fabric"
        assert ip["value"] == 1.5

    def test_orphaned_objects(self):
        orphans = {i["object"] for i in self.result["issues"] if i["type"] == "orphaned_object"}
        assert "/scene/surfacing/textured" in orphans
        assert "/scene/surfacing/unused_fabric" in orphans

    def test_complexity_score(self):
        # G=2, S=32, D=6, T=1, L=2
        # 2*32*(6^1.5)*(1.5)*(1.6) = 2257.45
        assert abs(self.result["complexity_score"] - 2257.45) < 0.02


# ============================================================
# Dynamic test: clean scene generated at runtime (anti-cheat)
# ============================================================

class TestDynamicClean:
    SCENE = '''SceneVariables {
    ["image_width"] = 256,
    ["image_height"] = 256,
    ["pixel_samples"] = 8,
    ["max_depth"] = 4
}

PerspectiveCamera("/test/cam") {
    ["focal"] = 50.0
}

DwaBaseMaterial("/test/mat") {
    ["albedo"] = bind(CheckerboardMap("/test/checker")),
    ["roughness"] = 0.5
}

CheckerboardMap("/test/checker") {
    ["color_a"] = Rgb(1, 1, 1),
    ["color_b"] = Rgb(0, 0, 0)
}

RdlMeshGeometry("/test/geo") {
    ["node_xform"] = translate(0, 0, 0)
}

RectLight("/test/light") {
    ["width"] = 1.0,
    ["height"] = 1.0,
    ["intensity"] = 5.0
}

LightSet("/test/ls") {
    ["lights"] = {RectLight("/test/light")}
}

Layer("/test/layer") {
    {RdlMeshGeometry("/test/geo"), "", DwaBaseMaterial("/test/mat"), LightSet("/test/ls")}
}

RenderOutput("/test/output") {
    ["file_name"] = "test.exr",
    ["result"] = "beauty",
    ["camera"] = PerspectiveCamera("/test/cam")
}
'''

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        scene_file = tmp_path / "dynamic_clean.rdla"
        scene_file.write_text(self.SCENE)
        self.result = run_analyzer(str(scene_file))

    def test_object_count(self):
        assert len(self.result["objects"]) == 8

    def test_object_types(self):
        objs = {o["name"]: o["type"] for o in self.result["objects"]}
        assert objs["/test/cam"] == "PerspectiveCamera"
        assert objs["/test/mat"] == "DwaBaseMaterial"
        assert objs["/test/checker"] == "CheckerboardMap"
        assert objs["/test/geo"] == "RdlMeshGeometry"
        assert objs["/test/light"] == "RectLight"
        assert objs["/test/ls"] == "LightSet"
        assert objs["/test/layer"] == "Layer"
        assert objs["/test/output"] == "RenderOutput"

    def test_bindings(self):
        assert len(self.result["bindings"]) == 1
        b = self.result["bindings"][0]
        assert b["source"] == "/test/mat"
        assert b["attribute"] == "albedo"
        assert b["target"] == "/test/checker"

    def test_no_issues(self):
        assert len(self.result["issues"]) == 0

    def test_complexity_score(self):
        # G=1, S=8, D=4, T=0, L=1
        # 1*8*(4^1.5)*(1.0)*(1.3) = 1*8*8*1*1.3 = 83.2
        assert abs(self.result["complexity_score"] - 83.2) < 0.02


# ============================================================
# Dynamic test: scene with known issue generated at runtime
# ============================================================

class TestDynamicWithIssue:
    SCENE = '''SceneVariables {
    ["pixel_samples"] = 16,
    ["max_depth"] = 3
}

PerspectiveCamera("/dyn/cam") {
    ["focal"] = 50.0
}

DwaSolidDielectricMaterial("/dyn/bad_mat") {
    ["ior"] = 0.8,
    ["roughness"] = 0.2
}

SphereGeometry("/dyn/sphere") {
    ["radius"] = 1.0
}

RectLight("/dyn/light") {
    ["intensity"] = 3.0,
    ["width"] = 1.0,
    ["height"] = 1.0
}

LightSet("/dyn/ls") {
    ["lights"] = {RectLight("/dyn/light")}
}

Layer("/dyn/layer") {
    {SphereGeometry("/dyn/sphere"), "", DwaSolidDielectricMaterial("/dyn/bad_mat"), LightSet("/dyn/ls")}
}

RenderOutput("/dyn/output") {
    ["file_name"] = "dyn.exr",
    ["result"] = "beauty",
    ["camera"] = PerspectiveCamera("/dyn/cam")
}
'''

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        scene_file = tmp_path / "dynamic_issue.rdla"
        scene_file.write_text(self.SCENE)
        self.result = run_analyzer(str(scene_file))

    def test_object_count(self):
        assert len(self.result["objects"]) == 7

    def test_invalid_ior_detected(self):
        invalid = [i for i in self.result["issues"] if i["type"] == "invalid_parameter"]
        assert len(invalid) >= 1
        assert any(
            i["object"] == "/dyn/bad_mat" and i["attribute"] == "ior" and i["value"] == 0.8
            for i in invalid
        )

    def test_no_orphans(self):
        orphans = [i for i in self.result["issues"] if i["type"] == "orphaned_object"]
        assert len(orphans) == 0

    def test_complexity_score(self):
        # G=1, S=16, D=3, T=1, L=1
        # 1*16*(3^1.5)*(1.5)*(1.3) = 162.12
        assert abs(self.result["complexity_score"] - 162.12) < 0.02
