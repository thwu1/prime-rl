
import json
import math
import os
import xml.etree.ElementTree as ET
import pytest

RESULTS_PATH = "/app/output/results.json"
OPENMC_BASE = "/app/output/openmc"
VALIDATION_LOG = "/app/output/validation.log"
BENCHMARKS_LIST = ["heu-met-fast-001", "heu-met-fast-003", "pu-met-fast-001"]


@pytest.fixture(scope="module")
def results():
    with open(RESULTS_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def benchmarks(results):
    return {b["id"]: b for b in results["benchmarks"]}


# ---------------------------------------------------------------------------
# OpenMC XML Structure
# ---------------------------------------------------------------------------

class TestOpenMCStructure:
    """All OpenMC XML files must exist and be well-formed."""

    @pytest.mark.parametrize("bench_id", BENCHMARKS_LIST)
    def test_geometry_xml_exists_and_valid(self, bench_id):
        path = f"{OPENMC_BASE}/{bench_id}/geometry.xml"
        assert os.path.isfile(path), f"Missing {path}"
        tree = ET.parse(path)
        assert tree.getroot().tag == "geometry"

    @pytest.mark.parametrize("bench_id", BENCHMARKS_LIST)
    def test_materials_xml_exists_and_valid(self, bench_id):
        path = f"{OPENMC_BASE}/{bench_id}/materials.xml"
        assert os.path.isfile(path), f"Missing {path}"
        tree = ET.parse(path)
        assert tree.getroot().tag == "materials"

    @pytest.mark.parametrize("bench_id", BENCHMARKS_LIST)
    def test_settings_xml_exists_and_valid(self, bench_id):
        path = f"{OPENMC_BASE}/{bench_id}/settings.xml"
        assert os.path.isfile(path), f"Missing {path}"
        tree = ET.parse(path)
        assert tree.getroot().tag == "settings"


# ---------------------------------------------------------------------------
# OpenMC Geometry
# ---------------------------------------------------------------------------

class TestOpenMCGeometry:
    """Geometry surfaces and cells must faithfully represent MCNP input."""

    def _parse_geom(self, bench_id):
        return ET.parse(f"{OPENMC_BASE}/{bench_id}/geometry.xml")

    def test_hmf001_surface_count(self):
        tree = self._parse_geom("heu-met-fast-001")
        surfaces = tree.findall(".//surface")
        assert len(surfaces) == 10

    def test_hmf003_surface_count(self):
        tree = self._parse_geom("heu-met-fast-003")
        surfaces = tree.findall(".//surface")
        assert len(surfaces) == 2

    def test_pmf001_surface_count(self):
        tree = self._parse_geom("pu-met-fast-001")
        surfaces = tree.findall(".//surface")
        assert len(surfaces) == 1

    def test_pmf001_sphere_radius(self):
        tree = self._parse_geom("pu-met-fast-001")
        surf = tree.findall(".//surface")[0]
        coeffs = surf.get("coeffs").split()
        radius = float(coeffs[-1])
        assert abs(radius - 6.3849) < 0.001

    def test_hmf003_inner_sphere_radius(self):
        tree = self._parse_geom("heu-met-fast-003")
        surfaces = tree.findall(".//surface")
        radii = sorted(float(s.get("coeffs").split()[-1]) for s in surfaces)
        assert abs(radii[0] - 6.782) < 0.001

    def test_hmf003_outer_sphere_radius(self):
        tree = self._parse_geom("heu-met-fast-003")
        surfaces = tree.findall(".//surface")
        radii = sorted(float(s.get("coeffs").split()[-1]) for s in surfaces)
        assert abs(radii[1] - 11.862) < 0.001

    def test_hmf001_cell_count(self):
        tree = self._parse_geom("heu-met-fast-001")
        cells = tree.findall(".//cell")
        assert len(cells) == 10

    def test_hmf003_cell_count(self):
        tree = self._parse_geom("heu-met-fast-003")
        cells = tree.findall(".//cell")
        assert len(cells) == 2

    def test_pmf001_cell_count(self):
        tree = self._parse_geom("pu-met-fast-001")
        cells = tree.findall(".//cell")
        assert len(cells) == 1

    @pytest.mark.parametrize("bench_id", BENCHMARKS_LIST)
    def test_vacuum_boundary_present(self, bench_id):
        tree = self._parse_geom(bench_id)
        surfaces = tree.findall(".//surface")
        vacuum = [s for s in surfaces if s.get("boundary") == "vacuum"]
        assert len(vacuum) >= 1, f"No vacuum boundary in {bench_id}"

    def test_hmf001_innermost_radius(self):
        tree = self._parse_geom("heu-met-fast-001")
        surfaces = tree.findall(".//surface")
        radii = sorted(float(s.get("coeffs").split()[-1]) for s in surfaces)
        assert abs(radii[0] - 1.0216) < 0.001


# ---------------------------------------------------------------------------
# OpenMC Materials
# ---------------------------------------------------------------------------

class TestOpenMCMaterials:
    """Material nuclide compositions must match MCNP data."""

    def _parse_mats(self, bench_id):
        return ET.parse(f"{OPENMC_BASE}/{bench_id}/materials.xml")

    def _get_material(self, bench_id, mat_id):
        tree = self._parse_mats(bench_id)
        for mat in tree.findall(".//material"):
            if mat.get("id") == str(mat_id):
                return mat
        return None

    def _get_nuclide_ao(self, mat_elem, nuc_name):
        for nuc in mat_elem.findall("nuclide"):
            if nuc.get("name") == nuc_name:
                return float(nuc.get("ao"))
        return None

    def test_hmf001_material_count(self):
        tree = self._parse_mats("heu-met-fast-001")
        assert len(tree.findall(".//material")) == 7

    def test_hmf003_material_count(self):
        tree = self._parse_mats("heu-met-fast-003")
        assert len(tree.findall(".//material")) == 2

    def test_pmf001_material_count(self):
        tree = self._parse_mats("pu-met-fast-001")
        assert len(tree.findall(".//material")) == 1

    def test_hmf001_mat1_u235_density(self):
        mat = self._get_material("heu-met-fast-001", 1)
        assert mat is not None
        ao = self._get_nuclide_ao(mat, "U235")
        assert ao is not None
        assert abs(ao - 4.4936e-2) < 1e-6

    def test_hmf001_mat1_u238_density(self):
        mat = self._get_material("heu-met-fast-001", 1)
        ao = self._get_nuclide_ao(mat, "U238")
        assert ao is not None
        assert abs(ao - 2.7213e-3) < 1e-6

    def test_pmf001_pu239_density(self):
        mat = self._get_material("pu-met-fast-001", 1)
        assert mat is not None
        ao = self._get_nuclide_ao(mat, "Pu239")
        assert ao is not None
        assert abs(ao - 3.7047e-2) < 1e-6

    def test_pmf001_ga_present(self):
        mat = self._get_material("pu-met-fast-001", 1)
        nucs = [n.get("name") for n in mat.findall("nuclide")]
        assert "Ga69" in nucs or "Ga71" in nucs

    def test_hmf003_mat2_u238_dominant(self):
        """Reflector material should be dominated by U-238."""
        mat = self._get_material("heu-met-fast-003", 2)
        ao_u238 = self._get_nuclide_ao(mat, "U238")
        ao_u235 = self._get_nuclide_ao(mat, "U235")
        assert ao_u238 > ao_u235 * 100

    def test_density_units_sum(self):
        """All materials should use density units='sum'."""
        for bid in BENCHMARKS_LIST:
            tree = self._parse_mats(bid)
            for mat in tree.findall(".//material"):
                density = mat.find("density")
                assert density is not None
                assert density.get("units") == "sum", \
                    f"{bid} mat {mat.get('id')} missing density units=sum"


# ---------------------------------------------------------------------------
# OpenMC Settings
# ---------------------------------------------------------------------------

class TestOpenMCSettings:
    """Settings must reproduce MCNP kcode parameters."""

    @pytest.mark.parametrize("bench_id", BENCHMARKS_LIST)
    def test_eigenvalue_mode(self, bench_id):
        tree = ET.parse(f"{OPENMC_BASE}/{bench_id}/settings.xml")
        rm = tree.find(".//run_mode")
        assert rm is not None
        assert rm.text.strip() == "eigenvalue"

    @pytest.mark.parametrize("bench_id", BENCHMARKS_LIST)
    def test_particles(self, bench_id):
        tree = ET.parse(f"{OPENMC_BASE}/{bench_id}/settings.xml")
        p = tree.find(".//particles")
        assert p is not None
        assert int(p.text.strip()) == 10000

    @pytest.mark.parametrize("bench_id", BENCHMARKS_LIST)
    def test_total_batches(self, bench_id):
        tree = ET.parse(f"{OPENMC_BASE}/{bench_id}/settings.xml")
        b = tree.find(".//batches")
        assert b is not None
        assert int(b.text.strip()) == 3000

    @pytest.mark.parametrize("bench_id", BENCHMARKS_LIST)
    def test_inactive_batches(self, bench_id):
        tree = ET.parse(f"{OPENMC_BASE}/{bench_id}/settings.xml")
        i = tree.find(".//inactive")
        assert i is not None
        assert int(i.text.strip()) == 20


# ---------------------------------------------------------------------------
# XML Validation Log
# ---------------------------------------------------------------------------

class TestValidation:
    def test_validation_log_exists(self):
        assert os.path.isfile(VALIDATION_LOG)

    def test_validation_log_nonempty(self):
        with open(VALIDATION_LOG) as f:
            content = f.read()
        assert len(content.strip()) > 0

    def test_all_benchmarks_in_log(self):
        with open(VALIDATION_LOG) as f:
            content = f.read().lower()
        for bid in BENCHMARKS_LIST:
            assert bid in content, f"{bid} not found in validation log"

    def test_no_invalid_xml(self):
        with open(VALIDATION_LOG) as f:
            content = f.read().lower()
        # xmlstarlet reports "invalid" for malformed XML
        assert "invalid" not in content, "Validation log indicates invalid XML"


# ---------------------------------------------------------------------------
# JSON Report Structure
# ---------------------------------------------------------------------------

class TestReportStructure:
    def test_output_exists(self):
        assert os.path.isfile(RESULTS_PATH)

    def test_valid_json_with_benchmarks(self, results):
        assert isinstance(results, dict)
        assert "benchmarks" in results

    def test_benchmark_count(self, results):
        assert len(results["benchmarks"]) == 3

    def test_benchmark_ids(self, benchmarks):
        expected = {"heu-met-fast-001", "heu-met-fast-003", "pu-met-fast-001"}
        assert set(benchmarks.keys()) == expected


# ---------------------------------------------------------------------------
# Material Compositions in Report
# ---------------------------------------------------------------------------

class TestReportMaterials:
    def test_hmf001_material_count(self, benchmarks):
        assert len(benchmarks["heu-met-fast-001"]["materials"]) == 7

    def test_hmf003_material_count(self, benchmarks):
        assert len(benchmarks["heu-met-fast-003"]["materials"]) == 2

    def test_pmf001_material_count(self, benchmarks):
        assert len(benchmarks["pu-met-fast-001"]["materials"]) == 1

    def test_hmf001_mat1_u235_density(self, benchmarks):
        mat = benchmarks["heu-met-fast-001"]["materials"]["1"]
        assert abs(mat["nuclides"]["U235"] - 4.4936e-2) < 1e-6

    def test_pmf001_mat1_pu239_density(self, benchmarks):
        mat = benchmarks["pu-met-fast-001"]["materials"]["1"]
        assert abs(mat["nuclides"]["Pu239"] - 3.7047e-2) < 1e-6

    def test_total_atom_density_consistency(self, benchmarks):
        for bid, bdata in benchmarks.items():
            for mid, mat in bdata["materials"].items():
                expected = sum(mat["nuclides"].values())
                actual = mat["total_atom_density"]
                assert abs(actual - expected) / expected < 0.001, \
                    f"{bid} mat {mid}: total {actual} != sum {expected}"


# ---------------------------------------------------------------------------
# Weight Fractions
# ---------------------------------------------------------------------------

class TestWeightFractions:
    def test_weight_fractions_sum_to_one(self, benchmarks):
        for bid, bdata in benchmarks.items():
            for mid, mat in bdata["materials"].items():
                wf_sum = sum(mat["weight_fractions"].values())
                assert abs(wf_sum - 1.0) < 0.002, \
                    f"{bid} mat {mid}: wf sum {wf_sum}"

    def test_hmf001_u235_dominant_by_mass(self, benchmarks):
        mat = benchmarks["heu-met-fast-001"]["materials"]["1"]
        assert mat["weight_fractions"]["U235"] > 0.90


# ---------------------------------------------------------------------------
# Enrichment
# ---------------------------------------------------------------------------

class TestEnrichment:
    def test_hmf001_enrichment(self, benchmarks):
        mat = benchmarks["heu-met-fast-001"]["materials"]["1"]
        assert abs(mat["enrichment_u235_wpct"] - 93.26) < 0.5

    def test_hmf003_core_enrichment(self, benchmarks):
        mat = benchmarks["heu-met-fast-003"]["materials"]["1"]
        assert abs(mat["enrichment_u235_wpct"] - 93.50) < 0.5

    def test_hmf003_reflector_depleted(self, benchmarks):
        mat = benchmarks["heu-met-fast-003"]["materials"]["2"]
        assert abs(mat["enrichment_u235_wpct"] - 0.711) < 0.15

    def test_pmf001_no_uranium_enrichment(self, benchmarks):
        mat = benchmarks["pu-met-fast-001"]["materials"]["1"]
        assert mat["enrichment_u235_wpct"] is None


# ---------------------------------------------------------------------------
# Cell Volumes
# ---------------------------------------------------------------------------

class TestVolumes:
    def test_pmf001_sphere_volume(self, benchmarks):
        cells = benchmarks["pu-met-fast-001"]["cells"]
        cell1 = next(c for c in cells if c["id"] == 1)
        expected = (4.0 / 3.0) * math.pi * 6.3849 ** 3
        assert abs(cell1["volume_cm3"] - expected) / expected < 0.01

    def test_hmf003_core_volume(self, benchmarks):
        cells = benchmarks["heu-met-fast-003"]["cells"]
        cell1 = next(c for c in cells if c["id"] == 1)
        expected = (4.0 / 3.0) * math.pi * 6.782 ** 3
        assert abs(cell1["volume_cm3"] - expected) / expected < 0.01

    def test_hmf003_reflector_shell_volume(self, benchmarks):
        cells = benchmarks["heu-met-fast-003"]["cells"]
        cell2 = next(c for c in cells if c["id"] == 2)
        expected = (4.0 / 3.0) * math.pi * (11.862 ** 3 - 6.782 ** 3)
        assert abs(cell2["volume_cm3"] - expected) / expected < 0.01

    def test_hmf001_nonvoid_cell_count(self, benchmarks):
        cells = benchmarks["heu-met-fast-001"]["cells"]
        assert len(cells) == 10

    def test_hmf001_innermost_shell(self, benchmarks):
        cells = benchmarks["heu-met-fast-001"]["cells"]
        cell1 = next(c for c in cells if c["id"] == 1)
        expected = (4.0 / 3.0) * math.pi * 1.0216 ** 3
        assert abs(cell1["volume_cm3"] - expected) / expected < 0.01


# ---------------------------------------------------------------------------
# Fissile Mass
# ---------------------------------------------------------------------------

class TestFissileMass:
    def test_pmf001_fissile_mass(self, benchmarks):
        mass = benchmarks["pu-met-fast-001"]["total_fissile_mass_kg"]
        assert 15.5 < mass < 16.7

    def test_hmf001_fissile_mass(self, benchmarks):
        mass = benchmarks["heu-met-fast-001"]["total_fissile_mass_kg"]
        assert 47.0 < mass < 52.0

    def test_hmf003_fissile_mass(self, benchmarks):
        mass = benchmarks["heu-met-fast-003"]["total_fissile_mass_kg"]
        assert 22.0 < mass < 25.5


# ---------------------------------------------------------------------------
# Experimental Data
# ---------------------------------------------------------------------------

class TestExperimental:
    def test_hmf001_keff(self, benchmarks):
        b = benchmarks["heu-met-fast-001"]
        assert b["experimental_keff"] == 1.0
        assert b["experimental_uncertainty"] == 0.001

    def test_hmf003_keff(self, benchmarks):
        b = benchmarks["heu-met-fast-003"]
        assert b["experimental_keff"] == 1.0
        assert b["experimental_uncertainty"] == 0.005

    def test_pmf001_keff(self, benchmarks):
        b = benchmarks["pu-met-fast-001"]
        assert b["experimental_keff"] == 1.0
        assert abs(b["experimental_uncertainty"] - 0.002) < 0.0001


# ---------------------------------------------------------------------------
# kcode Parameters in Report
# ---------------------------------------------------------------------------

class TestKcode:
    def test_kcode_particles(self, benchmarks):
        for bid, bdata in benchmarks.items():
            assert bdata["kcode"]["particles"] == 10000

    def test_kcode_batches(self, benchmarks):
        for bid, bdata in benchmarks.items():
            assert bdata["kcode"]["inactive_batches"] == 20
            assert bdata["kcode"]["total_batches"] == 3000

    def test_kcode_initial_keff(self, benchmarks):
        for bid, bdata in benchmarks.items():
            assert bdata["kcode"]["initial_keff"] == 1.0
