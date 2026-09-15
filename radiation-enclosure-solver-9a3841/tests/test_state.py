"""Tests for the radiation heat transfer batch pipeline.

Verifies SQLite schema, view factor accuracy, radiosity solutions,
and physical consistency across multiple enclosure types.
"""

import json
import math
import os
import sqlite3
import subprocess

import numpy as np
import pytest

SIGMA = 5.670374419e-8


# ---------------------------------------------------------------------------
# Reference view-factor implementations (independent of solver)
# ---------------------------------------------------------------------------

def ref_c11(a, b, c):
    """Howell C-11: identical parallel directly opposed rectangles."""
    X = a / c
    Y = b / c
    X2, Y2 = X * X, Y * Y
    t1 = math.log(math.sqrt((1 + X2) * (1 + Y2) / (1 + X2 + Y2)))
    t2 = X * math.sqrt(1 + Y2) * math.atan(X / math.sqrt(1 + Y2))
    t3 = Y * math.sqrt(1 + X2) * math.atan(Y / math.sqrt(1 + X2))
    t4 = -X * math.atan(X)
    t5 = -Y * math.atan(Y)
    return 2.0 / (math.pi * X * Y) * (t1 + t2 + t3 + t4 + t5)


def ref_c14(w, h, l):
    """Howell C-14: two perpendicular rectangles sharing common edge l."""
    W = w / l
    H = h / l
    W2, H2 = W * W, H * H
    t1 = W * math.atan(1.0 / W)
    t2 = H * math.atan(1.0 / H)
    t3 = -math.sqrt(H2 + W2) * math.atan(1.0 / math.sqrt(H2 + W2))
    base = (1 + W2) * (1 + H2) / (1 + W2 + H2)
    fw = (W2 * (1 + W2 + H2) / ((1 + W2) * (W2 + H2))) ** W2
    fh = (H2 * (1 + H2 + W2) / ((1 + H2) * (W2 + H2))) ** H2
    t4 = 0.25 * math.log(base * fw * fh)
    return (t1 + t2 + t3 + t4) / (W * math.pi)


def ref_c40(r, a):
    """Howell C-40: two coaxial equal disks."""
    R = r / a
    X = (2 * R * R + 1) / (R * R)
    return 0.5 * (X - math.sqrt(X * X - 4))


def ref_c135(r1, r2):
    """Howell C-135: concentric spheres."""
    ratio = r1 / r2
    return {"F12": 1.0, "F21": ratio ** 2, "F22": 1.0 - ratio ** 2}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def pipeline():
    """Run the pipeline once for all tests."""
    result = subprocess.run(
        ["bash", "/app/radpipe.sh"],
        capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, (
        f"Pipeline failed (exit {result.returncode}):\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    yield


@pytest.fixture
def db(pipeline):
    """Provide a SQLite connection to results.db."""
    assert os.path.exists("/app/results.db"), "results.db not found after pipeline"
    conn = sqlite3.connect("/app/results.db")
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def get_enclosure_id(db, name):
    row = db.execute(
        "SELECT id FROM enclosures WHERE name = ?", (name,)
    ).fetchone()
    assert row is not None, f"Enclosure '{name}' not found in database"
    return row["id"]


def get_vf_matrix(db, enc_id):
    rows = db.execute(
        "SELECT surface_from, surface_to, value FROM view_factors "
        "WHERE enclosure_id = ?",
        (enc_id,),
    ).fetchall()
    return {(r["surface_from"], r["surface_to"]): r["value"] for r in rows}


def get_surface_results(db, enc_id):
    rows = db.execute(
        "SELECT name, area, emissivity, bc_type, bc_value, "
        "radiosity, net_heat_flux, equilibrium_temp "
        "FROM surface_results WHERE enclosure_id = ?",
        (enc_id,),
    ).fetchall()
    return {r["name"]: dict(r) for r in rows}


# =====================================================================
# Schema & completeness tests
# =====================================================================

class TestSchema:

    def test_db_exists(self, db):
        """Database connection succeeds (fixture ensures file exists)."""
        pass

    def test_enclosures_table_columns(self, db):
        cols = [r[1] for r in db.execute("PRAGMA table_info(enclosures)").fetchall()]
        for c in ("id", "name", "type", "geometry"):
            assert c in cols, f"Column '{c}' missing from enclosures"

    def test_view_factors_table_columns(self, db):
        cols = [r[1] for r in db.execute("PRAGMA table_info(view_factors)").fetchall()]
        for c in ("enclosure_id", "surface_from", "surface_to", "value"):
            assert c in cols, f"Column '{c}' missing from view_factors"

    def test_surface_results_table_columns(self, db):
        cols = [r[1] for r in db.execute("PRAGMA table_info(surface_results)").fetchall()]
        for c in ("enclosure_id", "name", "area", "emissivity", "bc_type",
                   "bc_value", "radiosity", "net_heat_flux", "equilibrium_temp"):
            assert c in cols, f"Column '{c}' missing from surface_results"

    def test_all_enclosures_present(self, db):
        names = sorted(
            r[0] for r in db.execute("SELECT name FROM enclosures").fetchall()
        )
        expected = sorted([
            "blackbody_cube", "box_furnace", "cylinder_heater",
            "long_duct", "spheres_radiator",
        ])
        assert names == expected, f"Expected {expected}, got {names}"

    def test_view_factors_populated(self, db):
        cnt = db.execute("SELECT COUNT(*) FROM view_factors").fetchone()[0]
        # 5 enclosures: box(36) + duct(36) + cyl(9) + sph(4) + bb_cube(36) = 121
        assert cnt >= 85, f"Too few view_factor rows: {cnt}"

    def test_surface_results_populated(self, db):
        cnt = db.execute("SELECT COUNT(*) FROM surface_results").fetchone()[0]
        # 6+6+3+2+6 = 23
        assert cnt >= 23, f"Too few surface_results rows: {cnt}"


# =====================================================================
# Box furnace (4×3×2) view-factor tests
# =====================================================================

class TestBoxViewFactors:

    NAMES = ["floor", "ceiling", "front", "back", "left", "right"]
    AREAS = {"floor": 12.0, "ceiling": 12.0, "front": 8.0, "back": 8.0,
             "left": 6.0, "right": 6.0}
    Lx, Ly, Lz = 4.0, 3.0, 2.0

    @pytest.fixture
    def vf(self, db):
        return get_vf_matrix(db, get_enclosure_id(db, "box_furnace"))

    def test_summation(self, vf):
        for si in self.NAMES:
            total = sum(vf.get((si, sj), 0.0) for sj in self.NAMES)
            assert abs(total - 1.0) < 1e-4, f"Summation for {si}: {total}"

    def test_reciprocity(self, vf):
        for i, si in enumerate(self.NAMES):
            for j, sj in enumerate(self.NAMES):
                if j <= i:
                    continue
                lhs = self.AREAS[si] * vf.get((si, sj), 0.0)
                rhs = self.AREAS[sj] * vf.get((sj, si), 0.0)
                assert abs(lhs - rhs) < 1e-4, (
                    f"Reciprocity {si}<->{sj}: {lhs} vs {rhs}"
                )

    def test_opposed_c11(self, vf):
        cases = [
            (("floor", "ceiling"), ref_c11(self.Lx, self.Ly, self.Lz)),
            (("front", "back"), ref_c11(self.Lx, self.Lz, self.Ly)),
            (("left", "right"), ref_c11(self.Ly, self.Lz, self.Lx)),
        ]
        for (si, sj), ref in cases:
            val = vf.get((si, sj), 0.0)
            assert abs(val - ref) / ref < 1e-4, (
                f"{si}->{sj}: {val} vs {ref}"
            )

    def test_adjacent_c14_floor_front(self, vf):
        ref = ref_c14(self.Ly, self.Lz, self.Lx)
        for pair in [("floor", "front"), ("floor", "back"),
                     ("ceiling", "front"), ("ceiling", "back")]:
            val = vf.get(pair, 0.0)
            assert abs(val - ref) / ref < 1e-4, f"{pair}: {val} vs {ref}"

    def test_adjacent_c14_floor_left(self, vf):
        ref = ref_c14(self.Lx, self.Lz, self.Ly)
        for pair in [("floor", "left"), ("floor", "right"),
                     ("ceiling", "left"), ("ceiling", "right")]:
            val = vf.get(pair, 0.0)
            assert abs(val - ref) / ref < 1e-4, f"{pair}: {val} vs {ref}"

    def test_adjacent_c14_front_left(self, vf):
        ref = ref_c14(self.Lx, self.Ly, self.Lz)
        for pair in [("front", "left"), ("front", "right"),
                     ("back", "left"), ("back", "right")]:
            val = vf.get(pair, 0.0)
            assert abs(val - ref) / ref < 1e-4, f"{pair}: {val} vs {ref}"


# =====================================================================
# Long duct (10×1×1) view-factor tests
# =====================================================================

class TestLongDuctViewFactors:

    NAMES = ["floor", "ceiling", "front", "back", "left", "right"]
    AREAS = {"floor": 10.0, "ceiling": 10.0, "front": 10.0, "back": 10.0,
             "left": 1.0, "right": 1.0}

    @pytest.fixture
    def vf(self, db):
        return get_vf_matrix(db, get_enclosure_id(db, "long_duct"))

    def test_summation(self, vf):
        for si in self.NAMES:
            total = sum(vf.get((si, sj), 0.0) for sj in self.NAMES)
            assert abs(total - 1.0) < 1e-4, f"Summation for {si}: {total}"

    def test_reciprocity(self, vf):
        for i, si in enumerate(self.NAMES):
            for j, sj in enumerate(self.NAMES):
                if j <= i:
                    continue
                lhs = self.AREAS[si] * vf.get((si, sj), 0.0)
                rhs = self.AREAS[sj] * vf.get((sj, si), 0.0)
                assert abs(lhs - rhs) < 1e-3, (
                    f"Reciprocity {si}<->{sj}: {lhs} vs {rhs}"
                )

    def test_small_endwall_vf(self, vf):
        """In a 10×1×1 box, left->right should be very small."""
        ref = ref_c11(1.0, 1.0, 10.0)
        val = vf.get(("left", "right"), 0.0)
        assert abs(val - ref) / max(ref, 1e-10) < 1e-4
        assert val < 0.05

    def test_floor_ceiling_accuracy(self, vf):
        ref = ref_c11(10.0, 1.0, 1.0)
        val = vf.get(("floor", "ceiling"), 0.0)
        assert abs(val - ref) / ref < 1e-4


# =====================================================================
# Cylinder heater (r=0.5, h=1.0) view-factor tests
# =====================================================================

class TestCylinderViewFactors:

    NAMES = ["bottom", "top", "lateral"]
    r, h = 0.5, 1.0
    A_DISK = math.pi * 0.25
    A_LAT = math.pi

    @pytest.fixture
    def vf(self, db):
        return get_vf_matrix(db, get_enclosure_id(db, "cylinder_heater"))

    def test_bottom_top_c40(self, vf):
        ref = ref_c40(self.r, self.h)
        val = vf.get(("bottom", "top"), 0.0)
        assert abs(val - ref) / ref < 1e-4

    def test_symmetry(self, vf):
        assert abs(
            vf.get(("bottom", "top"), 0) - vf.get(("top", "bottom"), 0)
        ) < 1e-6

    def test_summation(self, vf):
        for si in self.NAMES:
            total = sum(vf.get((si, sj), 0.0) for sj in self.NAMES)
            assert abs(total - 1.0) < 1e-4, f"Cyl summation {si}: {total}"

    def test_lateral_self_vf_positive(self, vf):
        val = vf.get(("lateral", "lateral"), 0.0)
        assert val > 0.05, f"Lateral self-VF should be positive: {val}"

    def test_lateral_self_vf_reference(self, vf):
        F_bt = ref_c40(self.r, self.h)
        F_ld = self.A_DISK * (1 - F_bt) / self.A_LAT
        ref_self = 1.0 - 2 * F_ld
        val = vf.get(("lateral", "lateral"), 0.0)
        assert abs(val - ref_self) < 1e-4

    def test_reciprocity(self, vf):
        A = {"bottom": self.A_DISK, "top": self.A_DISK, "lateral": self.A_LAT}
        for si, sj in [("bottom", "top"), ("bottom", "lateral"),
                        ("top", "lateral")]:
            lhs = A[si] * vf.get((si, sj), 0)
            rhs = A[sj] * vf.get((sj, si), 0)
            assert abs(lhs - rhs) < 1e-4


# =====================================================================
# Concentric spheres (r1=0.3, r2=1.0) view-factor tests
# =====================================================================

class TestSpheresViewFactors:

    NAMES = ["inner", "outer"]
    r1, r2 = 0.3, 1.0
    A1 = 4 * math.pi * 0.09
    A2 = 4 * math.pi * 1.0

    @pytest.fixture
    def vf(self, db):
        return get_vf_matrix(db, get_enclosure_id(db, "spheres_radiator"))

    def test_inner_to_outer_is_one(self, vf):
        val = vf.get(("inner", "outer"), 0.0)
        assert abs(val - 1.0) < 1e-6

    def test_inner_self_is_zero(self, vf):
        val = vf.get(("inner", "inner"), 0.0)
        assert abs(val) < 1e-6

    def test_outer_to_inner(self, vf):
        ref = ref_c135(self.r1, self.r2)
        val = vf.get(("outer", "inner"), 0.0)
        assert abs(val - ref["F21"]) < 1e-4

    def test_outer_self_vf(self, vf):
        ref = ref_c135(self.r1, self.r2)
        val = vf.get(("outer", "outer"), 0.0)
        assert abs(val - ref["F22"]) < 1e-4

    def test_summation(self, vf):
        for si in self.NAMES:
            total = sum(vf.get((si, sj), 0.0) for sj in self.NAMES)
            assert abs(total - 1.0) < 1e-4

    def test_reciprocity(self, vf):
        lhs = self.A1 * vf.get(("inner", "outer"), 0)
        rhs = self.A2 * vf.get(("outer", "inner"), 0)
        assert abs(lhs - rhs) < 1e-4


# =====================================================================
# Radiosity / energy / heat-transfer tests
# =====================================================================

class TestRadiosity:

    def test_box_energy_conservation(self, db):
        enc_id = get_enclosure_id(db, "box_furnace")
        sr = get_surface_results(db, enc_id)
        total = sum(sr[s]["area"] * sr[s]["net_heat_flux"] for s in sr)
        scale = max(abs(sr[s]["area"] * sr[s]["net_heat_flux"]) for s in sr)
        assert abs(total) < 1e-3 * scale, f"Box energy: {total}"

    def test_box_adiabatic_wall(self, db):
        enc_id = get_enclosure_id(db, "box_furnace")
        sr = get_surface_results(db, enc_id)
        assert abs(sr["back"]["net_heat_flux"]) < 1.0

    def test_box_equilibrium_temp_exists(self, db):
        enc_id = get_enclosure_id(db, "box_furnace")
        sr = get_surface_results(db, enc_id)
        T = sr["back"]["equilibrium_temp"]
        assert T is not None, "Missing equilibrium temp for adiabatic wall"

    def test_box_equilibrium_temp_range(self, db):
        enc_id = get_enclosure_id(db, "box_furnace")
        sr = get_surface_results(db, enc_id)
        T = sr["back"]["equilibrium_temp"]
        assert 400 < T < 1200, f"Back wall T={T} out of range"

    def test_box_hot_positive_flux(self, db):
        enc_id = get_enclosure_id(db, "box_furnace")
        sr = get_surface_results(db, enc_id)
        assert sr["floor"]["net_heat_flux"] > 0

    def test_box_cold_negative_flux(self, db):
        enc_id = get_enclosure_id(db, "box_furnace")
        sr = get_surface_results(db, enc_id)
        assert sr["ceiling"]["net_heat_flux"] < 0

    def test_cyl_energy_conservation(self, db):
        enc_id = get_enclosure_id(db, "cylinder_heater")
        sr = get_surface_results(db, enc_id)
        total = sum(sr[s]["area"] * sr[s]["net_heat_flux"] for s in sr)
        scale = max(abs(sr[s]["area"] * sr[s]["net_heat_flux"]) for s in sr)
        assert abs(total) < 1e-3 * scale

    def test_cyl_equilibrium_temp(self, db):
        enc_id = get_enclosure_id(db, "cylinder_heater")
        sr = get_surface_results(db, enc_id)
        T = sr["lateral"]["equilibrium_temp"]
        assert T is not None
        assert 500 < T < 1000

    def test_spheres_energy_conservation(self, db):
        enc_id = get_enclosure_id(db, "spheres_radiator")
        sr = get_surface_results(db, enc_id)
        total = sum(sr[s]["area"] * sr[s]["net_heat_flux"] for s in sr)
        scale = max(abs(sr[s]["area"] * sr[s]["net_heat_flux"]) for s in sr)
        assert abs(total) < 1e-3 * scale

    def test_spheres_inner_positive_flux(self, db):
        enc_id = get_enclosure_id(db, "spheres_radiator")
        sr = get_surface_results(db, enc_id)
        assert sr["inner"]["net_heat_flux"] > 0, "Hot inner sphere should emit"

    def test_blackbody_radiosity(self, db):
        enc_id = get_enclosure_id(db, "blackbody_cube")
        sr = get_surface_results(db, enc_id)
        J_floor = sr["floor"]["radiosity"]
        J_expected = SIGMA * 800.0 ** 4
        assert abs(J_floor - J_expected) / J_expected < 1e-5

    def test_blackbody_energy_conservation(self, db):
        enc_id = get_enclosure_id(db, "blackbody_cube")
        sr = get_surface_results(db, enc_id)
        total = sum(sr[s]["area"] * sr[s]["net_heat_flux"] for s in sr)
        scale = max(abs(sr[s]["area"] * sr[s]["net_heat_flux"]) for s in sr)
        assert abs(total) < 1e-2 * scale

    def test_duct_energy_conservation(self, db):
        enc_id = get_enclosure_id(db, "long_duct")
        sr = get_surface_results(db, enc_id)
        total = sum(sr[s]["area"] * sr[s]["net_heat_flux"] for s in sr)
        scale = max(abs(sr[s]["area"] * sr[s]["net_heat_flux"]) for s in sr)
        assert abs(total) < 1e-3 * scale

    def test_duct_adiabatic(self, db):
        enc_id = get_enclosure_id(db, "long_duct")
        sr = get_surface_results(db, enc_id)
        assert abs(sr["back"]["net_heat_flux"]) < 1.0

    def test_radiosity_consistency(self, db):
        """Independently verify radiosity for box_furnace."""
        enc_id = get_enclosure_id(db, "box_furnace")
        vf = get_vf_matrix(db, enc_id)
        sr = get_surface_results(db, enc_id)

        NAMES = ["floor", "ceiling", "front", "back", "left", "right"]
        surfs_cfg = [
            {"name": "floor", "emissivity": 0.85, "condition": "temperature", "value": 1200.0},
            {"name": "ceiling", "emissivity": 0.70, "condition": "temperature", "value": 400.0},
            {"name": "front", "emissivity": 0.60, "condition": "temperature", "value": 900.0},
            {"name": "back", "emissivity": 0.90, "condition": "heatflux", "value": 0.0},
            {"name": "left", "emissivity": 0.75, "condition": "temperature", "value": 600.0},
            {"name": "right", "emissivity": 0.80, "condition": "temperature", "value": 800.0},
        ]
        props = {s["name"]: s for s in surfs_cfg}
        N = 6
        F = np.zeros((N, N))
        for i, si in enumerate(NAMES):
            for j, sj in enumerate(NAMES):
                F[i, j] = vf.get((si, sj), 0.0)

        A = np.zeros((N, N))
        b = np.zeros(N)
        for i, si in enumerate(NAMES):
            eps = props[si]["emissivity"]
            if props[si]["condition"] == "temperature":
                for j in range(N):
                    A[i, j] = (1.0 if i == j else 0.0) - (1 - eps) * F[i, j]
                b[i] = eps * SIGMA * props[si]["value"] ** 4
            else:
                for j in range(N):
                    A[i, j] = (1.0 if i == j else 0.0) - F[i, j]
                b[i] = props[si]["value"]

        J_ref = np.linalg.solve(A, b)
        for i, si in enumerate(NAMES):
            solver_J = sr[si]["radiosity"]
            rel = abs(solver_J - J_ref[i]) / max(abs(J_ref[i]), 1.0)
            assert rel < 1e-3, (
                f"Radiosity mismatch {si}: solver={solver_J}, ref={J_ref[i]}"
            )
