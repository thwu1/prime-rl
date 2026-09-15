
import pytest
import json
import os
import math
import xml.etree.ElementTree as ET


# ============================================================
# Helper functions
# ============================================================

def parse_xml(path):
    """Parse an XML file and return the root element."""
    tree = ET.parse(path)
    return tree.getroot()


def get_surfaces(root):
    """Extract surfaces from geometry XML root."""
    return {s.get('id'): s for s in root.findall('.//surface')}


def get_cells(root):
    """Extract cells from geometry XML root."""
    return {c.get('id'): c for c in root.findall('.//cell')}


def get_materials(root):
    """Extract materials from materials XML root."""
    return {m.get('id'): m for m in root.findall('.//material')}


def get_nuclides(material_elem):
    """Extract nuclide dict {name: ao} from a material element."""
    return {n.get('name'): float(n.get('ao')) for n in material_elem.findall('nuclide')}


def approx(a, b, rel_tol=1e-3, abs_tol=1e-8):
    """Check if two floats are approximately equal."""
    return abs(a - b) <= max(rel_tol * max(abs(a), abs(b)), abs_tol)


# ============================================================
# Test: Translator exists
# ============================================================

class TestTranslatorExists:
    def test_translator_file_exists(self):
        assert os.path.exists('/app/translator/mcnp_to_openmc.py'), \
            "Translator script must exist at /app/translator/mcnp_to_openmc.py"

    def test_translator_is_python(self):
        with open('/app/translator/mcnp_to_openmc.py') as f:
            content = f.read()
        assert 'import' in content or 'def ' in content, \
            "Translator must be a Python script"


# ============================================================
# Test: HMF003 (Topsy) translation
# ============================================================

class TestHMF003Geometry:
    @pytest.fixture
    def root(self):
        return parse_xml('/app/output/hmf003/geometry.xml')

    def test_surface_count(self, root):
        surfaces = root.findall('.//surface')
        assert len(surfaces) == 2

    def test_surface_types(self, root):
        surfs = get_surfaces(root)
        assert surfs['1'].get('type') == 'sphere'
        assert surfs['2'].get('type') == 'sphere'

    def test_surface_radii(self, root):
        surfs = get_surfaces(root)
        coeffs1 = [float(c) for c in surfs['1'].get('coeffs').split()]
        coeffs2 = [float(c) for c in surfs['2'].get('coeffs').split()]
        assert approx(coeffs1[-1], 6.782)
        assert approx(coeffs2[-1], 11.862)

    def test_vacuum_boundary(self, root):
        surfs = get_surfaces(root)
        assert surfs['2'].get('boundary') == 'vacuum'
        assert surfs['1'].get('boundary') is None or surfs['1'].get('boundary') != 'vacuum'

    def test_cell_count(self, root):
        cells = root.findall('.//cell')
        assert len(cells) == 2

    def test_cell_materials(self, root):
        cells = get_cells(root)
        assert cells['1'].get('material') == '1'
        assert cells['2'].get('material') == '2'


class TestHMF003Materials:
    @pytest.fixture
    def root(self):
        return parse_xml('/app/output/hmf003/materials.xml')

    def test_material_count(self, root):
        mats = root.findall('.//material')
        assert len(mats) == 2

    def test_core_u235(self, root):
        mats = get_materials(root)
        nuclides = get_nuclides(mats['1'])
        assert 'U235' in nuclides
        assert approx(nuclides['U235'], 4.4917e-2)

    def test_core_u234(self, root):
        mats = get_materials(root)
        nuclides = get_nuclides(mats['1'])
        assert 'U234' in nuclides
        assert approx(nuclides['U234'], 4.921e-4)

    def test_core_u238(self, root):
        mats = get_materials(root)
        nuclides = get_nuclides(mats['1'])
        assert 'U238' in nuclides
        assert approx(nuclides['U238'], 2.5993e-3)

    def test_reflector_u238(self, root):
        mats = get_materials(root)
        nuclides = get_nuclides(mats['2'])
        assert 'U238' in nuclides
        assert approx(nuclides['U238'], 4.747e-2, rel_tol=1e-3)

    def test_reflector_u235(self, root):
        mats = get_materials(root)
        nuclides = get_nuclides(mats['2'])
        assert 'U235' in nuclides
        assert approx(nuclides['U235'], 3.4428e-4)

    def test_density_sum(self, root):
        """Materials should use density units='sum'."""
        mats = get_materials(root)
        for mid, m in mats.items():
            density = m.find('density')
            assert density is not None
            assert density.get('units') == 'sum'


class TestHMF003Settings:
    @pytest.fixture
    def root(self):
        return parse_xml('/app/output/hmf003/settings.xml')

    def test_run_mode(self, root):
        rm = root.find('.//run_mode')
        assert rm is not None
        assert rm.text.strip() == 'eigenvalue'

    def test_particles(self, root):
        p = root.find('.//particles')
        assert p is not None
        assert int(p.text.strip()) == 10000

    def test_batches(self, root):
        b = root.find('.//batches')
        assert b is not None
        assert int(b.text.strip()) == 3000

    def test_inactive(self, root):
        i = root.find('.//inactive')
        assert i is not None
        assert int(i.text.strip()) == 20


# ============================================================
# Test: PMF001 (Jezebel) translation
# ============================================================

class TestPMF001Geometry:
    @pytest.fixture
    def root(self):
        return parse_xml('/app/output/pmf001/geometry.xml')

    def test_single_sphere(self, root):
        surfaces = root.findall('.//surface')
        assert len(surfaces) == 1
        s = surfaces[0]
        assert s.get('type') == 'sphere'
        coeffs = [float(c) for c in s.get('coeffs').split()]
        assert approx(coeffs[-1], 6.3849)

    def test_vacuum_boundary(self, root):
        surfaces = root.findall('.//surface')
        assert surfaces[0].get('boundary') == 'vacuum'

    def test_single_cell(self, root):
        cells = root.findall('.//cell')
        assert len(cells) == 1
        assert cells[0].get('material') == '1'


class TestPMF001Materials:
    @pytest.fixture
    def root(self):
        return parse_xml('/app/output/pmf001/materials.xml')

    def test_single_material(self, root):
        mats = root.findall('.//material')
        assert len(mats) == 1

    def test_plutonium_nuclides(self, root):
        mats = get_materials(root)
        nuclides = get_nuclides(mats['1'])
        assert 'Pu239' in nuclides
        assert 'Pu240' in nuclides
        assert 'Pu241' in nuclides
        assert approx(nuclides['Pu239'], 3.7047e-2)
        assert approx(nuclides['Pu240'], 1.751e-3)
        assert approx(nuclides['Pu241'], 1.17e-4)

    def test_gallium_nuclides(self, root):
        mats = get_materials(root)
        nuclides = get_nuclides(mats['1'])
        assert 'Ga69' in nuclides
        assert 'Ga71' in nuclides
        assert approx(nuclides['Ga69'], 8.2681e-4)
        assert approx(nuclides['Ga71'], 5.4854e-4)


# ============================================================
# Test: HST001 (Uranyl Nitrate Cylinder) translation
# ============================================================

class TestHST001Geometry:
    @pytest.fixture
    def root(self):
        return parse_xml('/app/output/hst001/geometry.xml')

    def test_surface_count(self, root):
        surfaces = root.findall('.//surface')
        assert len(surfaces) == 6

    def test_cylinder_surfaces(self, root):
        surfs = get_surfaces(root)
        assert surfs['1'].get('type') == 'z-cylinder'
        assert surfs['2'].get('type') == 'z-cylinder'
        coeffs1 = [float(c) for c in surfs['1'].get('coeffs').split()]
        assert approx(coeffs1[-1], 13.96)

    def test_plane_surfaces(self, root):
        surfs = get_surfaces(root)
        assert surfs['3'].get('type') == 'z-plane'
        assert surfs['4'].get('type') == 'z-plane'
        assert surfs['5'].get('type') == 'z-plane'
        assert surfs['6'].get('type') == 'z-plane'

    def test_boundary_conditions(self, root):
        surfs = get_surfaces(root)
        # Outer cylinder and top/bottom planes should be vacuum
        assert surfs['2'].get('boundary') == 'vacuum'
        assert surfs['3'].get('boundary') == 'vacuum'
        assert surfs['6'].get('boundary') == 'vacuum'
        # Inner surfaces should NOT be vacuum
        assert surfs['1'].get('boundary') is None or surfs['1'].get('boundary') != 'vacuum'
        assert surfs['4'].get('boundary') is None or surfs['4'].get('boundary') != 'vacuum'

    def test_cell_count(self, root):
        cells = root.findall('.//cell')
        assert len(cells) == 4

    def test_void_cell(self, root):
        cells = get_cells(root)
        assert cells['4'].get('material') == 'void'

    def test_material_cells(self, root):
        cells = get_cells(root)
        assert cells['1'].get('material') == '2'  # bottom wall = SS-304
        assert cells['2'].get('material') == '2'  # side walls = SS-304
        assert cells['3'].get('material') == '1'  # uranyl nitrate


class TestHST001Materials:
    @pytest.fixture
    def root(self):
        return parse_xml('/app/output/hst001/materials.xml')

    def test_material_count(self, root):
        mats = root.findall('.//material')
        assert len(mats) == 2

    def test_thermal_scattering(self, root):
        """Material 1 must have S(a,b) thermal scattering for H in H2O."""
        mats = get_materials(root)
        sab = mats['1'].findall('sab')
        assert len(sab) >= 1
        assert sab[0].get('name') == 'c_H_in_H2O'

    def test_uranyl_nitrate_nuclides(self, root):
        mats = get_materials(root)
        nuclides = get_nuclides(mats['1'])
        # Must have all key nuclides
        expected = ['U234', 'U235', 'U236', 'U238', 'O16', 'O17', 'N14', 'H1']
        for name in expected:
            assert name in nuclides, f"Missing nuclide {name} in material 1"

    def test_uranyl_u235(self, root):
        mats = get_materials(root)
        nuclides = get_nuclides(mats['1'])
        assert approx(nuclides['U235'], 3.4777e-4)

    def test_uranyl_hydrogen(self, root):
        mats = get_materials(root)
        nuclides = get_nuclides(mats['1'])
        assert approx(nuclides['H1'], 6.322e-2)

    def test_ss304_nuclide_count(self, root):
        """SS-304 has many isotopes (C, Si, P, S, Cr, Mn, Fe, Ni, Mo)."""
        mats = get_materials(root)
        nuclides = get_nuclides(mats['2'])
        assert len(nuclides) >= 20

    def test_ss304_iron(self, root):
        mats = get_materials(root)
        nuclides = get_nuclides(mats['2'])
        assert 'Fe56' in nuclides
        assert approx(nuclides['Fe56'], 5.4917e-2, rel_tol=1e-3)

    def test_ss304_chromium(self, root):
        mats = get_materials(root)
        nuclides = get_nuclides(mats['2'])
        assert 'Cr52' in nuclides
        assert approx(nuclides['Cr52'], 1.4232e-2, rel_tol=1e-3)


# ============================================================
# Test: HMF001 reference match
# ============================================================

class TestHMF001ReferenceMatch:
    def test_geometry_surface_count(self):
        translated = parse_xml('/app/output/hmf001/geometry.xml')
        reference = parse_xml('/app/reference/hmf001/geometry.xml')
        t_surfs = translated.findall('.//surface')
        r_surfs = reference.findall('.//surface')
        assert len(t_surfs) == len(r_surfs)

    def test_geometry_cell_count(self):
        translated = parse_xml('/app/output/hmf001/geometry.xml')
        reference = parse_xml('/app/reference/hmf001/geometry.xml')
        t_cells = translated.findall('.//cell')
        r_cells = reference.findall('.//cell')
        assert len(t_cells) == len(r_cells)

    def test_geometry_surface_radii(self):
        translated = parse_xml('/app/output/hmf001/geometry.xml')
        reference = parse_xml('/app/reference/hmf001/geometry.xml')
        t_surfs = get_surfaces(translated)
        r_surfs = get_surfaces(reference)
        for sid in r_surfs:
            t_coeffs = [float(c) for c in t_surfs[sid].get('coeffs').split()]
            r_coeffs = [float(c) for c in r_surfs[sid].get('coeffs').split()]
            for tc, rc in zip(t_coeffs, r_coeffs):
                assert approx(tc, rc), \
                    f"Surface {sid} coefficients mismatch: {t_coeffs} vs {r_coeffs}"

    def test_geometry_vacuum_boundary(self):
        translated = parse_xml('/app/output/hmf001/geometry.xml')
        t_surfs = get_surfaces(translated)
        assert t_surfs['10'].get('boundary') == 'vacuum'

    def test_materials_count(self):
        translated = parse_xml('/app/output/hmf001/materials.xml')
        reference = parse_xml('/app/reference/hmf001/materials.xml')
        t_mats = translated.findall('.//material')
        r_mats = reference.findall('.//material')
        assert len(t_mats) == len(r_mats)

    def test_materials_nuclide_values(self):
        translated = parse_xml('/app/output/hmf001/materials.xml')
        reference = parse_xml('/app/reference/hmf001/materials.xml')
        t_mats = get_materials(translated)
        r_mats = get_materials(reference)
        for mid in r_mats:
            t_nucs = get_nuclides(t_mats[mid])
            r_nucs = get_nuclides(r_mats[mid])
            for name, r_val in r_nucs.items():
                assert name in t_nucs, \
                    f"Material {mid} missing nuclide {name}"
                assert approx(t_nucs[name], r_val), \
                    f"Material {mid} nuclide {name}: {t_nucs[name]} vs {r_val}"

    def test_settings_parameters(self):
        translated = parse_xml('/app/output/hmf001/settings.xml')
        rm = translated.find('.//run_mode')
        assert rm is not None and rm.text.strip() == 'eigenvalue'
        p = translated.find('.//particles')
        assert p is not None and int(p.text.strip()) == 10000
        b = translated.find('.//batches')
        assert b is not None and int(b.text.strip()) == 3000
        i = translated.find('.//inactive')
        assert i is not None and int(i.text.strip()) == 20


# ============================================================
# Test: Validation report
# ============================================================

class TestValidationReport:
    @pytest.fixture
    def report(self):
        with open('/app/analysis/validation_report.json') as f:
            return json.load(f)

    def test_file_exists(self):
        assert os.path.exists('/app/analysis/validation_report.json')

    def test_total_entries(self, report):
        assert report['total_entries'] == 487

    def test_total_benchmarks(self, report):
        assert report['total_benchmarks'] >= 80

    def test_has_categories(self, report):
        assert 'categories' in report
        cats = report['categories']
        assert len(cats) >= 15

    def test_expected_categories_present(self, report):
        cats = report['categories']
        for expected in ['heu-met-fast', 'pu-met-fast', 'heu-sol-therm',
                         'mix-met-fast', 'leu-comp-therm', 'pu-sol-therm']:
            assert expected in cats, f"Missing category: {expected}"

    def test_category_structure(self, report):
        cats = report['categories']
        for cat_name, cat_data in cats.items():
            assert 'count' in cat_data
            assert 'mean_keff' in cat_data
            assert 'weighted_mean_keff' in cat_data
            assert 'chi_squared' in cat_data
            assert 'reduced_chi_squared' in cat_data
            assert 'birge_ratio' in cat_data

    def test_heu_met_fast_count(self, report):
        hmf = report['categories']['heu-met-fast']
        assert hmf['count'] >= 90

    def test_heu_met_fast_mean_keff(self, report):
        hmf = report['categories']['heu-met-fast']
        assert 0.998 < hmf['mean_keff'] < 1.003

    def test_chi_squared_positive(self, report):
        for cat_name, cat_data in report['categories'].items():
            assert cat_data['chi_squared'] >= 0

    def test_birge_ratio_positive(self, report):
        for cat_name, cat_data in report['categories'].items():
            assert cat_data['birge_ratio'] >= 0

    def test_fissile_summary(self, report):
        assert 'fissile_summary' in report
        fissile = report['fissile_summary']
        for expected in ['heu', 'pu', 'leu', 'mix', 'ieu', 'u233']:
            assert expected in fissile, f"Missing fissile type: {expected}"
            assert 'count' in fissile[expected]
            assert 'mean_keff' in fissile[expected]

    def test_outliers_exist(self, report):
        assert 'outliers' in report
        assert len(report['outliers']) >= 1

    def test_outlier_structure(self, report):
        for outlier in report['outliers']:
            assert 'benchmark' in outlier
            assert 'keff' in outlier
            assert 'uncertainty' in outlier
            assert 'deviation_sigma' in outlier

    def test_mmf008_outlier(self, report):
        """mix-met-fast-008 case 8h (keff=1.03, sigma=0.0025) should be flagged."""
        outlier_benchmarks = [o['benchmark'] for o in report['outliers']]
        assert any('mix-met-fast-008' in b for b in outlier_benchmarks), \
            "mix-met-fast-008 should be identified as containing outlier cases"

    def test_outlier_deviation_threshold(self, report):
        """All outliers should have |deviation_sigma| > 3."""
        for outlier in report['outliers']:
            assert abs(outlier['deviation_sigma']) > 3.0
