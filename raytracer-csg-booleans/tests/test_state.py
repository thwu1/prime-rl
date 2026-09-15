"""
"""
import subprocess
import os
import re
import shutil
import pytest


def run(cmd, cwd="/app", timeout=120):
    return subprocess.run(
        cmd, shell=True, cwd=cwd,
        capture_output=True, text=True, timeout=timeout
    )


class TestCSGHeaderExists:
    def test_csg_header_file_exists(self):
        assert os.path.isfile("/app/src/csg.h"), \
            "CSG header not found at /app/src/csg.h"

    def test_csg_op_enum_values(self):
        with open("/app/src/csg.h") as f:
            content = f.read()
        assert "union_op" in content, "csg_op::union_op not found in csg.h"
        assert "intersection" in content, "csg_op::intersection not found in csg.h"
        assert "difference" in content, "csg_op::difference not found in csg.h"

    def test_csg_node_class(self):
        with open("/app/src/csg.h") as f:
            content = f.read()
        assert "csg_node" in content, "csg_node class not found in csg.h"
        assert "hittable" in content, "csg_node should inherit from hittable"


class TestSceneRequirements:
    def test_scene_has_nested_csg(self):
        """The scene must include at least one nested CSG object."""
        with open("/app/src/main.cc") as f:
            content = f.read()
        # Count csg_node constructor invocations.
        # Need >= 4: three for union/intersection/difference + at least 1 more for nesting.
        count = len(re.findall(r'(?:make_shared<csg_node>|new\s+csg_node|csg_node\s*\()', content))
        assert count >= 4, \
            f"Scene must include nested CSG (a csg_node using another csg_node as child). " \
            f"Found only {count} csg_node constructions, expected >= 4."


class TestBuild:
    def test_project_compiles(self):
        shutil.rmtree("/app/build", ignore_errors=True)
        os.makedirs("/app/build")
        result = run("cmake .. && make -j$(nproc)", cwd="/app/build", timeout=120)
        assert result.returncode == 0, \
            f"Build failed:\nstdout: {result.stdout[-500:]}\nstderr: {result.stderr[-500:]}"

    def test_executable_exists(self):
        if not os.path.isfile("/app/build/raytracer"):
            os.makedirs("/app/build", exist_ok=True)
            run("cmake .. && make -j$(nproc)", cwd="/app/build", timeout=120)
        assert os.path.isfile("/app/build/raytracer"), \
            "Executable not found at /app/build/raytracer"


class TestCSGMathematicalCorrectness:
    def _ensure_built(self):
        if not os.path.isfile("/app/build/raytracer"):
            os.makedirs("/app/build", exist_ok=True)
            run("cmake .. && make -j$(nproc)", cwd="/app/build", timeout=120)

    def test_csg_test_compiles(self):
        self._ensure_built()
        result = run(
            "g++ -std=c++11 -O2 -I/app/src -o /tmp/test_csg /tests/test_csg_intersections.cc",
            cwd="/tmp", timeout=60
        )
        assert result.returncode == 0, \
            f"CSG test compilation failed:\n{result.stderr[-1000:]}"

    def test_csg_intersections_pass(self):
        self._ensure_built()
        compile_result = run(
            "g++ -std=c++11 -O2 -I/app/src -o /tmp/test_csg /tests/test_csg_intersections.cc",
            cwd="/tmp", timeout=60
        )
        if compile_result.returncode != 0:
            pytest.fail(f"Compilation failed: {compile_result.stderr[-1000:]}")

        result = run("/tmp/test_csg", cwd="/tmp", timeout=30)
        assert result.returncode == 0, \
            f"CSG math tests failed:\n{result.stdout}\n{result.stderr}"
        assert "ALL TESTS PASSED" in result.stdout, \
            f"Not all CSG tests passed:\n{result.stdout}"


class TestRenderOutput:
    def _ensure_built(self):
        if not os.path.isfile("/app/build/raytracer"):
            os.makedirs("/app/build", exist_ok=True)
            run("cmake .. && make -j$(nproc)", cwd="/app/build", timeout=120)

    def test_render_produces_valid_ppm(self):
        self._ensure_built()
        result = run("/app/build/raytracer", timeout=300)
        assert result.returncode == 0, \
            f"Render crashed:\nstderr: {result.stderr[-500:]}"

        output = result.stdout.strip()
        assert len(output) > 0, "No output produced by renderer"

        lines = output.split('\n')
        assert len(lines) > 3, "Output too short for valid PPM"
        assert lines[0] == "P3", f"Invalid PPM magic: expected 'P3', got '{lines[0]}'"

        dims = lines[1].split()
        assert len(dims) == 2, f"Invalid dimensions line: '{lines[1]}'"
        width, height = int(dims[0]), int(dims[1])
        assert width >= 100, f"Image width {width} too small (expected >= 100)"
        assert height >= 50, f"Image height {height} too small (expected >= 50)"
        assert lines[2].strip() == "255", f"Invalid max color value: '{lines[2]}'"

        # Validate all pixel values are in range
        values = []
        for line in lines[3:]:
            for tok in line.split():
                v = int(tok)
                assert 0 <= v <= 255, f"Pixel value out of range: {v}"
                values.append(v)

        expected_count = width * height * 3
        assert len(values) == expected_count, \
            f"Expected {expected_count} pixel values, got {len(values)}"

    def test_render_has_varied_content(self):
        self._ensure_built()
        result = run("/app/build/raytracer", timeout=300)
        if result.returncode != 0:
            pytest.skip("Render failed")

        lines = result.stdout.strip().split('\n')
        unique_values = set()
        for line in lines[3:]:
            for tok in line.split():
                unique_values.add(int(tok))

        assert len(unique_values) > 10, \
            f"Image too uniform ({len(unique_values)} unique values) - CSG objects may not be rendering"
