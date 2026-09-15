
import json
import math
import os
import subprocess
import xml.etree.ElementTree as ET

import numpy as np
import pytest
import trimesh
import yaml
from scipy.spatial import ConvexHull
from scipy.spatial.transform import Rotation

SOLVER_PATH = "/app/solver.py"
MAIN_SCENE = "/app/scene.sdf"
MAIN_CONSTRAINTS = "/app/constraints.yaml"
CYCLIC_SCENE = "/app/scene_cyclic.sdf"
CYCLIC_CONSTRAINTS = "/app/constraints_cyclic.yaml"
OUTPUT_DIR = "/tmp/test_output"
TOL = 0.01


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_solver(scene, constraints, output_dir, num_placements=1, seed=42, timeout=120):
    os.makedirs(output_dir, exist_ok=True)
    result = subprocess.run(
        [
            "python3", SOLVER_PATH,
            "--scene", scene,
            "--constraints", constraints,
            "--output-dir", output_dir,
            "--num-placements", str(num_placements),
            "--seed", str(seed),
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result


def load_json(path):
    with open(path) as f:
        return json.load(f)


def load_yaml(path):
    with open(path) as f:
        return yaml.safe_load(f)


def parse_sdf_geometries(sdf_path):
    """Parse SDF and return dict of object geometries and orientations."""
    tree = ET.parse(sdf_path)
    root = tree.getroot()
    objects = {}
    for model in root.iter("model"):
        name = model.get("name")
        pose_elem = model.find("pose")
        pose = [float(x) for x in pose_elem.text.strip().split()] if pose_elem is not None else [0]*6
        geom_elem = model.find(".//collision/geometry")
        geom = _parse_geom(geom_elem)
        objects[name] = {"geometry": geom, "orientation": pose[3:]}
    return objects


def _parse_geom(geom_elem):
    for child in geom_elem:
        if child.tag == "box":
            size = [float(x) for x in child.find("size").text.strip().split()]
            return {"type": "box", "size": size}
        elif child.tag == "cylinder":
            r = float(child.find("radius").text.strip())
            h = float(child.find("length").text.strip())
            return {"type": "cylinder", "radius": r, "length": h}
        elif child.tag == "sphere":
            r = float(child.find("radius").text.strip())
            return {"type": "sphere", "radius": r}
    return None


def make_mesh(geom):
    if geom["type"] == "box":
        return trimesh.creation.box(extents=geom["size"])
    elif geom["type"] == "cylinder":
        return trimesh.creation.cylinder(radius=geom["radius"], height=geom["length"], sections=32)
    elif geom["type"] == "sphere":
        return trimesh.creation.icosphere(radius=geom["radius"], subdivisions=3)


def pose_to_transform(pose):
    x, y, z = pose[0], pose[1], pose[2]
    roll, pitch, yaw = pose[3], pose[4], pose[5]
    R = Rotation.from_euler('XYZ', [roll, pitch, yaw]).as_matrix()
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = [x, y, z]
    return T


def get_transformed_vertices(geom, pose):
    mesh = make_mesh(geom)
    T = pose_to_transform(pose)
    mesh.apply_transform(T)
    return mesh.vertices.copy()


def get_half_extents(geom):
    if geom["type"] == "box":
        return [geom["size"][i] / 2 for i in range(3)]
    elif geom["type"] == "cylinder":
        return [geom["radius"], geom["radius"], geom["length"] / 2]
    elif geom["type"] == "sphere":
        return [geom["radius"]] * 3


def get_rotated_half_extents(geom, orientation):
    if all(abs(a) < 1e-9 for a in orientation):
        return get_half_extents(geom)
    mesh = make_mesh(geom)
    R = Rotation.from_euler('XYZ', orientation).as_matrix()
    T = np.eye(4)
    T[:3, :3] = R
    mesh.apply_transform(T)
    bounds = mesh.bounds
    return [(bounds[1][i] - bounds[0][i]) / 2 for i in range(3)]


def convex_collision(verts_a, verts_b, margin=0.0):
    """Check if two convex hulls collide (any vertex inside the other)."""
    try:
        hull_a = ConvexHull(verts_a)
        for v in verts_b:
            if np.all(hull_a.equations @ np.append(v, 1.0) <= margin):
                return True
    except Exception:
        pass
    try:
        hull_b = ConvexHull(verts_b)
        for v in verts_a:
            if np.all(hull_b.equations @ np.append(v, 1.0) <= margin):
                return True
    except Exception:
        pass
    return False


def get_related_pairs(constraints):
    """Pairs exempt from collision (transitive through support/containment chains).

    Objects inside a container that sits on a table share the table's top-face
    z-boundary.  Without transitive exemptions the collision checker would flag
    them as intersecting the table.
    """
    parent_map = {}
    for c in constraints:
        if c["predicate"] in ("on_top_of", "stacked_on", "inside"):
            parent_map.setdefault(c["subject"], set()).add(c["reference"])

    pairs = set()
    for start in list(parent_map.keys()):
        visited = set()
        queue = list(parent_map.get(start, set()))
        while queue:
            current = queue.pop()
            if current in visited:
                continue
            visited.add(current)
            pairs.add((start, current))
            pairs.add((current, start))
            for parent in parent_map.get(current, set()):
                queue.append(parent)
    return pairs


# ---------------------------------------------------------------------------
# Module-scoped fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def main_result():
    out = "/tmp/test_main_output"
    res = run_solver(MAIN_SCENE, MAIN_CONSTRAINTS, out, num_placements=1, seed=42)
    assert res.returncode == 0, f"Solver failed: {res.stderr[:500]}"
    return load_json(os.path.join(out, "placements.json"))


@pytest.fixture(scope="module")
def main_stability():
    out = "/tmp/test_main_output"
    return load_json(os.path.join(out, "stability_report.json"))


@pytest.fixture(scope="module")
def main_constraints_report():
    out = "/tmp/test_main_output"
    return load_json(os.path.join(out, "constraints_report.json"))


@pytest.fixture(scope="module")
def sdf_objects():
    return parse_sdf_geometries(MAIN_SCENE)


@pytest.fixture(scope="module")
def constraint_data():
    return load_yaml(MAIN_CONSTRAINTS)


@pytest.fixture(scope="module")
def multi_result():
    out = "/tmp/test_multi_output"
    res = run_solver(MAIN_SCENE, MAIN_CONSTRAINTS, out, num_placements=10, seed=42)
    assert res.returncode == 0, f"Solver failed: {res.stderr[:500]}"
    return load_json(os.path.join(out, "placements.json"))


# ---------------------------------------------------------------------------
# Tests: basics
# ---------------------------------------------------------------------------

class TestSolverBasics:
    def test_solver_file_exists(self):
        assert os.path.isfile(SOLVER_PATH), "solver.py not found at /app/solver.py"

    def test_main_scene_runs(self):
        out = "/tmp/test_basics_run"
        res = run_solver(MAIN_SCENE, MAIN_CONSTRAINTS, out)
        assert res.returncode == 0, f"Exit {res.returncode}: {res.stderr[:500]}"

    def test_output_files_exist(self):
        out = "/tmp/test_basics_run"
        for fname in ["placements.json", "solved_scene.sdf",
                       "stability_report.json", "constraints_report.json"]:
            assert os.path.isfile(os.path.join(out, fname)), f"Missing {fname}"

    def test_placements_structure(self, main_result):
        assert "placements" in main_result
        assert len(main_result["placements"]) >= 1
        assert "metadata" in main_result

    def test_all_objects_present(self, main_result, sdf_objects):
        p = main_result["placements"][0]["objects"]
        for name in sdf_objects:
            assert name in p, f"Object '{name}' missing from output"

    def test_poses_are_6dof(self, main_result, sdf_objects):
        p = main_result["placements"][0]["objects"]
        for name in sdf_objects:
            pose = p[name]["pose"]
            assert len(pose) == 6, f"{name} pose not 6DOF: {pose}"
            assert all(isinstance(v, (int, float)) for v in pose)


# ---------------------------------------------------------------------------
# Tests: anchor positions
# ---------------------------------------------------------------------------

class TestAnchorPositions:
    def test_workbench_anchor(self, main_result):
        pose = main_result["placements"][0]["objects"]["workbench"]["pose"]
        assert abs(pose[0]) < TOL and abs(pose[1]) < TOL
        assert abs(pose[2] - 0.4) < TOL

    def test_shelf_anchor(self, main_result):
        pose = main_result["placements"][0]["objects"]["storage_shelf"]["pose"]
        assert abs(pose[0] - 2.5) < TOL
        assert abs(pose[1]) < TOL
        assert abs(pose[2] - 0.6) < TOL


# ---------------------------------------------------------------------------
# Tests: on_top_of z-values (SDF center-of-geometry)
# ---------------------------------------------------------------------------

class TestOnTopOf:
    def _check_z(self, placement, sdf_objects, subj, ref):
        sp = placement[subj]["pose"]
        rp = placement[ref]["pose"]
        ref_rhe = get_rotated_half_extents(sdf_objects[ref]["geometry"],
                                           sdf_objects[ref]["orientation"])
        subj_rhe = get_rotated_half_extents(sdf_objects[subj]["geometry"],
                                            sdf_objects[subj]["orientation"])
        expected_z = rp[2] + ref_rhe[2] + subj_rhe[2]
        assert abs(sp[2] - expected_z) < TOL, \
            f"{subj}.z={sp[2]:.4f}, expected={expected_z:.4f}"

    def test_robot_base_plate_on_workbench(self, main_result, sdf_objects):
        p = main_result["placements"][0]["objects"]
        self._check_z(p, sdf_objects, "robot_base_plate", "workbench")

    def test_calibration_cube_on_workbench(self, main_result, sdf_objects):
        p = main_result["placements"][0]["objects"]
        self._check_z(p, sdf_objects, "calibration_cube", "workbench")

    def test_tool_caddy_on_workbench(self, main_result, sdf_objects):
        p = main_result["placements"][0]["objects"]
        self._check_z(p, sdf_objects, "tool_caddy", "workbench")

    def test_parts_tray_on_workbench(self, main_result, sdf_objects):
        p = main_result["placements"][0]["objects"]
        self._check_z(p, sdf_objects, "parts_tray", "workbench")

    def test_alignment_jig_on_workbench(self, main_result, sdf_objects):
        p = main_result["placements"][0]["objects"]
        self._check_z(p, sdf_objects, "alignment_jig", "workbench")

    def test_spec_binder_on_shelf(self, main_result, sdf_objects):
        p = main_result["placements"][0]["objects"]
        self._check_z(p, sdf_objects, "spec_binder", "storage_shelf")

    def test_ref_gauge_on_shelf(self, main_result, sdf_objects):
        p = main_result["placements"][0]["objects"]
        self._check_z(p, sdf_objects, "ref_gauge", "storage_shelf")


# ---------------------------------------------------------------------------
# Tests: stacked_on (z + xy alignment)
# ---------------------------------------------------------------------------

class TestStackedOn:
    def _check_stacked(self, placement, sdf_objects, subj, ref):
        sp = placement[subj]["pose"]
        rp = placement[ref]["pose"]
        ref_rhe = get_rotated_half_extents(sdf_objects[ref]["geometry"],
                                           sdf_objects[ref]["orientation"])
        subj_rhe = get_rotated_half_extents(sdf_objects[subj]["geometry"],
                                            sdf_objects[subj]["orientation"])
        expected_z = rp[2] + ref_rhe[2] + subj_rhe[2]
        assert abs(sp[2] - expected_z) < TOL, \
            f"{subj}.z={sp[2]:.4f}, expected={expected_z:.4f}"
        assert abs(sp[0] - rp[0]) < TOL, f"{subj}.x not aligned with {ref}.x"
        assert abs(sp[1] - rp[1]) < TOL, f"{subj}.y not aligned with {ref}.y"

    def test_gripper_mount_on_base_plate(self, main_result, sdf_objects):
        p = main_result["placements"][0]["objects"]
        self._check_stacked(p, sdf_objects, "gripper_mount", "robot_base_plate")

    def test_sensor_module_on_gripper_mount(self, main_result, sdf_objects):
        p = main_result["placements"][0]["objects"]
        self._check_stacked(p, sdf_objects, "sensor_module", "gripper_mount")

    def test_gauge_cap_on_ref_gauge(self, main_result, sdf_objects):
        p = main_result["placements"][0]["objects"]
        self._check_stacked(p, sdf_objects, "gauge_cap", "ref_gauge")

    def test_stack_ascending_z(self, main_result):
        p = main_result["placements"][0]["objects"]
        z_base = p["robot_base_plate"]["pose"][2]
        z_mount = p["gripper_mount"]["pose"][2]
        z_sensor = p["sensor_module"]["pose"][2]
        assert z_mount > z_base, f"gripper_mount.z ({z_mount}) <= base.z ({z_base})"
        assert z_sensor > z_mount, f"sensor.z ({z_sensor}) <= mount.z ({z_mount})"


# ---------------------------------------------------------------------------
# Tests: inside containment
# ---------------------------------------------------------------------------

class TestInsideRelation:
    def _check_inside(self, placement, sdf_objects, subj, ref):
        sp = placement[subj]["pose"]
        rp = placement[ref]["pose"]
        subj_rhe = get_rotated_half_extents(sdf_objects[subj]["geometry"],
                                            sdf_objects[subj]["orientation"])
        ref_rhe = get_rotated_half_extents(sdf_objects[ref]["geometry"],
                                           sdf_objects[ref]["orientation"])
        # z: subject rests on container bottom
        expected_z = rp[2] - ref_rhe[2] + subj_rhe[2]
        assert abs(sp[2] - expected_z) < TOL, \
            f"{subj}.z={sp[2]:.4f}, expected={expected_z:.4f}"
        # xy containment
        for ax, label in [(0, "x"), (1, "y")]:
            assert sp[ax] - subj_rhe[ax] >= rp[ax] - ref_rhe[ax] - TOL, \
                f"{subj} {label}_min outside {ref}"
            assert sp[ax] + subj_rhe[ax] <= rp[ax] + ref_rhe[ax] + TOL, \
                f"{subj} {label}_max outside {ref}"

    def test_probe_alpha_inside_tool_caddy(self, main_result, sdf_objects):
        p = main_result["placements"][0]["objects"]
        self._check_inside(p, sdf_objects, "probe_alpha", "tool_caddy")

    def test_probe_beta_inside_tool_caddy(self, main_result, sdf_objects):
        p = main_result["placements"][0]["objects"]
        self._check_inside(p, sdf_objects, "probe_beta", "tool_caddy")

    def test_bushing_inside_parts_tray(self, main_result, sdf_objects):
        p = main_result["placements"][0]["objects"]
        self._check_inside(p, sdf_objects, "bushing", "parts_tray")

    def test_dowel_pin_inside_parts_tray(self, main_result, sdf_objects):
        p = main_result["placements"][0]["objects"]
        self._check_inside(p, sdf_objects, "dowel_pin", "parts_tray")

    def test_bearing_ball_inside_parts_tray(self, main_result, sdf_objects):
        p = main_result["placements"][0]["objects"]
        self._check_inside(p, sdf_objects, "bearing_ball", "parts_tray")


# ---------------------------------------------------------------------------
# Tests: directional relations
# ---------------------------------------------------------------------------

class TestDirectionalRelations:
    def test_calibration_cube_right_of_robot_base(self, main_result):
        p = main_result["placements"][0]["objects"]
        assert p["calibration_cube"]["pose"][1] > p["robot_base_plate"]["pose"][1] + 0.05 - TOL

    def test_tool_caddy_left_of_robot_base(self, main_result):
        p = main_result["placements"][0]["objects"]
        assert p["tool_caddy"]["pose"][1] < p["robot_base_plate"]["pose"][1] - 0.03 + TOL

    def test_parts_tray_behind_calibration_cube(self, main_result):
        p = main_result["placements"][0]["objects"]
        assert p["parts_tray"]["pose"][0] < p["calibration_cube"]["pose"][0] - 0.02 + TOL

    def test_alignment_jig_in_front_of_tool_caddy(self, main_result):
        p = main_result["placements"][0]["objects"]
        assert p["alignment_jig"]["pose"][0] > p["tool_caddy"]["pose"][0] + 0.02 - TOL

    def test_ref_gauge_right_of_spec_binder(self, main_result):
        p = main_result["placements"][0]["objects"]
        assert p["ref_gauge"]["pose"][1] > p["spec_binder"]["pose"][1] + 0.02 - TOL


# ---------------------------------------------------------------------------
# Tests: next_to
# ---------------------------------------------------------------------------

class TestNextTo:
    def _check_next_to(self, placement, subj, ref, dmin, dmax):
        sp = placement[subj]["pose"]
        rp = placement[ref]["pose"]
        dist = math.sqrt((sp[0] - rp[0]) ** 2 + (sp[1] - rp[1]) ** 2)
        assert dmin - TOL <= dist <= dmax + TOL, \
            f"{subj}-{ref} dist {dist:.4f} not in [{dmin}, {dmax}]"

    def test_probe_beta_next_to_alpha(self, main_result):
        p = main_result["placements"][0]["objects"]
        self._check_next_to(p, "probe_beta", "probe_alpha", 0.025, 0.055)

    def test_dowel_pin_next_to_bushing(self, main_result):
        p = main_result["placements"][0]["objects"]
        self._check_next_to(p, "dowel_pin", "bushing", 0.03, 0.065)


# ---------------------------------------------------------------------------
# Tests: mesh-based collision freedom
# ---------------------------------------------------------------------------

class TestMeshCollision:
    def test_no_unrelated_collisions(self, main_result, sdf_objects, constraint_data):
        p = main_result["placements"][0]["objects"]
        related = get_related_pairs(constraint_data["constraints"])
        margin = constraint_data.get("settings", {}).get("collision_margin", 0.005)
        names = list(p.keys())

        # Pre-compute transformed vertices using trimesh
        verts = {}
        for name in names:
            pose = p[name]["pose"]
            geom = sdf_objects[name]["geometry"]
            verts[name] = get_transformed_vertices(geom, pose)

        violations = []
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a, b = names[i], names[j]
                if (a, b) in related:
                    continue
                if convex_collision(verts[a], verts[b], margin):
                    violations.append((a, b))

        assert not violations, f"Mesh collisions detected: {violations}"


# ---------------------------------------------------------------------------
# Tests: orientation preservation
# ---------------------------------------------------------------------------

class TestOrientationPreservation:
    def test_alignment_jig_yaw_preserved(self, main_result):
        pose = main_result["placements"][0]["objects"]["alignment_jig"]["pose"]
        assert abs(pose[5] - 0.5236) < 0.001, \
            f"alignment_jig yaw={pose[5]:.4f}, expected ~0.5236"

    def test_unrotated_objects_zero_orientation(self, main_result):
        p = main_result["placements"][0]["objects"]
        for name in ["workbench", "robot_base_plate", "calibration_cube", "tool_caddy"]:
            pose = p[name]["pose"]
            assert abs(pose[3]) < TOL and abs(pose[4]) < TOL and abs(pose[5]) < TOL, \
                f"{name} has unexpected orientation: {pose[3:]}"


# ---------------------------------------------------------------------------
# Tests: stability report
# ---------------------------------------------------------------------------

class TestStabilityReport:
    def test_report_exists(self, main_stability):
        assert "assemblies" in main_stability
        assert "all_stable" in main_stability

    def test_assembly_count(self, main_stability):
        # robot_base_plate->gripper_mount->sensor_module, ref_gauge->gauge_cap
        assert len(main_stability["assemblies"]) == 2

    def test_all_assemblies_stable(self, main_stability):
        assert main_stability["all_stable"] is True
        for asm in main_stability["assemblies"]:
            assert asm["stable"] is True

    def test_robot_stack_chain(self, main_stability):
        chains = {tuple(a["chain"]) for a in main_stability["assemblies"]}
        expected = ("robot_base_plate", "gripper_mount", "sensor_module")
        assert expected in chains, f"Missing robot stack assembly. Found: {chains}"

    def test_gauge_stack_chain(self, main_stability):
        chains = {tuple(a["chain"]) for a in main_stability["assemblies"]}
        expected = ("ref_gauge", "gauge_cap")
        assert expected in chains, f"Missing gauge stack assembly. Found: {chains}"


# ---------------------------------------------------------------------------
# Tests: constraints report
# ---------------------------------------------------------------------------

class TestConstraintsReport:
    def test_report_exists(self, main_constraints_report):
        assert "constraints" in main_constraints_report
        assert "all_satisfied" in main_constraints_report

    def test_constraint_count(self, main_constraints_report, constraint_data):
        expected = len(constraint_data["constraints"])
        actual = len(main_constraints_report["constraints"])
        assert actual == expected, f"Expected {expected} constraints, got {actual}"

    def test_all_satisfied(self, main_constraints_report):
        assert main_constraints_report["all_satisfied"] is True


# ---------------------------------------------------------------------------
# Tests: cyclic scene rejection
# ---------------------------------------------------------------------------

class TestCyclicScene:
    def test_nonzero_exit(self):
        out = "/tmp/test_cyclic_output"
        res = run_solver(CYCLIC_SCENE, CYCLIC_CONSTRAINTS, out)
        assert res.returncode != 0, \
            "Solver should exit non-zero for cyclic scene"

    def test_error_mentions_cycle(self):
        out = "/tmp/test_cyclic_output2"
        res = run_solver(CYCLIC_SCENE, CYCLIC_CONSTRAINTS, out)
        combined = (res.stdout + res.stderr).lower()
        keywords = ["cycle", "unsatisfiable", "circular", "cyclic", "dependency"]
        assert any(k in combined for k in keywords), \
            f"Error should mention cycle. Got: {res.stdout + res.stderr}"


# ---------------------------------------------------------------------------
# Tests: multiple placements
# ---------------------------------------------------------------------------

class TestMultiplePlacements:
    def test_correct_count(self, multi_result):
        assert len(multi_result["placements"]) == 10

    def test_all_valid_z(self, multi_result, sdf_objects):
        wb_rhe_z = get_half_extents(sdf_objects["workbench"]["geometry"])[2]
        rbp_rhe_z = get_half_extents(sdf_objects["robot_base_plate"]["geometry"])[2]
        for idx, pl in enumerate(multi_result["placements"]):
            rbp_z = pl["objects"]["robot_base_plate"]["pose"][2]
            wb_z = pl["objects"]["workbench"]["pose"][2]
            expected = wb_z + wb_rhe_z + rbp_rhe_z
            assert abs(rbp_z - expected) < TOL, \
                f"Placement {idx}: robot_base_plate z wrong"

    def test_diversity(self, multi_result):
        positions = [
            tuple(round(c, 6) for c in pl["objects"]["robot_base_plate"]["pose"][:2])
            for pl in multi_result["placements"]
        ]
        unique = set(positions)
        assert len(unique) > 1, \
            "All 10 placements have identical robot_base_plate positions"


# ---------------------------------------------------------------------------
# Tests: reproducibility
# ---------------------------------------------------------------------------

class TestReproducibility:
    def test_same_seed_same_output(self):
        out1 = "/tmp/test_repro1"
        out2 = "/tmp/test_repro2"
        run_solver(MAIN_SCENE, MAIN_CONSTRAINTS, out1, seed=999)
        run_solver(MAIN_SCENE, MAIN_CONSTRAINTS, out2, seed=999)
        d1 = load_json(os.path.join(out1, "placements.json"))
        d2 = load_json(os.path.join(out2, "placements.json"))
        p1 = d1["placements"][0]["objects"]
        p2 = d2["placements"][0]["objects"]
        for name in p1:
            for i in range(6):
                assert abs(p1[name]["pose"][i] - p2[name]["pose"][i]) < 1e-10, \
                    f"Non-reproducible: {name} pose[{i}] differs"
