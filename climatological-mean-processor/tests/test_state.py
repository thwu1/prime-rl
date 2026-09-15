
import sys
import json
import math
import pytest

sys.path.insert(0, '/app')


class TestAreaWeights:
    """Verify spherical area weight computation."""

    def test_sum_equals_4pi(self):
        from pipeline import compute_area_weights
        lat_bounds = [[-90, -45], [-45, 0], [0, 45], [45, 90]]
        lon_bounds = [[0, 60], [60, 120], [120, 180], [180, 240], [240, 300], [300, 360]]
        w = compute_area_weights(lat_bounds, lon_bounds)
        total = sum(w[i][j] for i in range(4) for j in range(6))
        assert abs(total - 4 * math.pi) < 1e-10, \
            f"Area weights sum to {total}, expected {4 * math.pi}"

    def test_polar_smaller_than_equatorial(self):
        from pipeline import compute_area_weights
        lat_bounds = [[-90, -45], [-45, 0], [0, 45], [45, 90]]
        lon_bounds = [[0, 60]]
        w = compute_area_weights(lat_bounds, lon_bounds)
        assert w[0][0] < w[1][0], \
            f"Polar cell ({w[0][0]}) should be smaller than equatorial ({w[1][0]})"
        assert w[3][0] < w[2][0]

    def test_north_south_symmetry(self):
        from pipeline import compute_area_weights
        lat_bounds = [[-90, -45], [-45, 0], [0, 45], [45, 90]]
        lon_bounds = [[0, 60]]
        w = compute_area_weights(lat_bounds, lon_bounds)
        assert abs(w[0][0] - w[3][0]) < 1e-10
        assert abs(w[1][0] - w[2][0]) < 1e-10

    def test_specific_weight_values(self):
        from pipeline import compute_area_weights
        lat_bounds = [[-90, -45], [-45, 0], [0, 45], [45, 90]]
        lon_bounds = [[0, 60]]
        w = compute_area_weights(lat_bounds, lon_bounds)
        expected_polar = (1 - math.sin(math.radians(45))) * (math.pi / 3)
        expected_equat = math.sin(math.radians(45)) * (math.pi / 3)
        assert abs(w[0][0] - expected_polar) < 1e-10, \
            f"Polar weight {w[0][0]} != expected {expected_polar}"
        assert abs(w[1][0] - expected_equat) < 1e-10, \
            f"Equatorial weight {w[1][0]} != expected {expected_equat}"

    def test_longitude_uniformity(self):
        from pipeline import compute_area_weights
        lat_bounds = [[-90, -45], [-45, 0], [0, 45], [45, 90]]
        lon_bounds = [[0, 60], [60, 120], [120, 180], [180, 240], [240, 300], [300, 360]]
        w = compute_area_weights(lat_bounds, lon_bounds)
        for i in range(4):
            for j in range(1, 6):
                assert abs(w[i][j] - w[i][0]) < 1e-10


class TestSeasonAssignment:
    """Verify meteorological season assignment with DJF year-shift."""

    def test_djf_year_boundary(self):
        from pipeline import assign_seasons
        seasons = assign_seasons(48, 2003)
        # DJF 2004 = Dec 2003 (t=11), Jan 2004 (t=12), Feb 2004 (t=13)
        assert (2004, 'DJF') in seasons, "DJF 2004 should exist"
        assert sorted(seasons[(2004, 'DJF')]) == [11, 12, 13], \
            f"DJF 2004 indices: {sorted(seasons[(2004, 'DJF')])} != [11, 12, 13]"

    def test_djf_2005(self):
        from pipeline import assign_seasons
        seasons = assign_seasons(48, 2003)
        assert (2005, 'DJF') in seasons
        assert sorted(seasons[(2005, 'DJF')]) == [23, 24, 25]

    def test_djf_2006(self):
        from pipeline import assign_seasons
        seasons = assign_seasons(48, 2003)
        assert (2006, 'DJF') in seasons
        assert sorted(seasons[(2006, 'DJF')]) == [35, 36, 37]

    def test_incomplete_djf_start_excluded(self):
        from pipeline import assign_seasons
        seasons = assign_seasons(48, 2003)
        assert (2003, 'DJF') not in seasons, \
            "DJF 2003 should be excluded (no Dec 2002)"

    def test_incomplete_djf_end_excluded(self):
        from pipeline import assign_seasons
        seasons = assign_seasons(48, 2003)
        assert (2007, 'DJF') not in seasons, \
            "DJF 2007 should be excluded (only Dec 2006)"

    def test_total_complete_seasons(self):
        from pipeline import assign_seasons
        seasons = assign_seasons(48, 2003)
        # 3 DJF + 4 MAM + 4 JJA + 4 SON = 15
        assert len(seasons) == 15, \
            f"Expected 15 complete seasons, got {len(seasons)}: {sorted(seasons.keys())}"

    def test_each_season_has_3_months(self):
        from pipeline import assign_seasons
        seasons = assign_seasons(48, 2003)
        for key, indices in seasons.items():
            assert len(indices) == 3, \
                f"Season {key} has {len(indices)} months, expected 3"

    def test_mam_indices(self):
        from pipeline import assign_seasons
        seasons = assign_seasons(48, 2003)
        assert sorted(seasons[(2003, 'MAM')]) == [2, 3, 4]
        assert sorted(seasons[(2004, 'MAM')]) == [14, 15, 16]

    def test_jja_indices(self):
        from pipeline import assign_seasons
        seasons = assign_seasons(48, 2003)
        assert sorted(seasons[(2003, 'JJA')]) == [5, 6, 7]

    def test_son_indices(self):
        from pipeline import assign_seasons
        seasons = assign_seasons(48, 2003)
        assert sorted(seasons[(2003, 'SON')]) == [8, 9, 10]


class TestDayCounts:
    """Verify calendar-aware day counts derived from coordinate bounds."""

    def test_360day_bounds_not_standard(self):
        """360-day calendar: bounds give 30, hardcoded standard gives 31 for Jan."""
        from pipeline import get_day_counts
        bounds = [[i * 30.0, (i + 1) * 30.0] for i in range(12)]
        dc = get_day_counts(bounds, '360_day', 2003, 12)
        assert abs(dc[0] - 30.0) < 1e-10, \
            f"360_day Jan should be 30 from bounds, got {dc[0]}"

    def test_360day_all_months_30(self):
        """360-day calendar: all months should be 30 days from bounds."""
        from pipeline import get_day_counts
        bounds = [[i * 30.0, (i + 1) * 30.0] for i in range(48)]
        dc = get_day_counts(bounds, '360_day', 2003, 48)
        for t in range(48):
            assert abs(dc[t] - 30.0) < 1e-10, \
                f"360_day month {t} should be 30, got {dc[t]}"

    def test_noleap_feb_always_28(self):
        """Noleap Feb should be 28, even in years that are leap in standard."""
        from pipeline import get_day_counts
        noleap_days = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
        cumul = 0.0
        bounds = []
        for i in range(24):
            d = noleap_days[i % 12]
            bounds.append([cumul, cumul + d])
            cumul += d
        dc = get_day_counts(bounds, 'noleap', 2003, 24)
        # Feb 2004 (t=13) should be 28, not 29 (standard leap)
        assert abs(dc[13] - 28.0) < 1e-10, \
            f"noleap Feb 2004 should be 28, got {dc[13]}"

    def test_standard_feb_leap(self):
        """Standard calendar: Feb of leap year should be 29 from bounds."""
        from pipeline import get_day_counts
        std_days = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31,
                    31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
        cumul = 0.0
        bounds = []
        for d in std_days:
            bounds.append([cumul, cumul + d])
            cumul += d
        dc = get_day_counts(bounds, 'standard', 2003, 24)
        assert abs(dc[13] - 29.0) < 1e-10, \
            f"Standard Feb 2004 should be 29, got {dc[13]}"
        assert abs(dc[1] - 28.0) < 1e-10, \
            f"Standard Feb 2003 should be 28, got {dc[1]}"


class TestTwoStageCollapse:
    """Verify two-stage climatological collapse."""

    def test_two_stage_differs_from_single_pass(self):
        """Two-stage must produce different result from single-pass
        when season instances have different total day counts."""
        from pipeline import climatological_mean

        data = [
            [[100.0]], [[200.0]], [[300.0]],
            [[400.0]], [[500.0]], [[600.0]],
        ]
        day_counts = [31.0, 31.0, 28.0, 31.0, 31.0, 29.0]
        seasons = {(1, 'X'): [0, 1, 2], (2, 'X'): [3, 4, 5]}

        clim = climatological_mean(data, seasons, day_counts)

        y1 = (31 * 100 + 31 * 200 + 28 * 300) / 90.0
        y2 = (31 * 400 + 31 * 500 + 29 * 600) / 91.0
        expected = (y1 + y2) / 2.0

        single_pass = (31 * 100 + 31 * 200 + 28 * 300 +
                       31 * 400 + 31 * 500 + 29 * 600) / 181.0
        assert abs(expected - single_pass) > 0.5, \
            "Test data must distinguish two-stage from single-pass"

        assert abs(clim['X'][0][0] - expected) < 1e-10, \
            f"Two-stage result {clim['X'][0][0]} != expected {expected}"

    def test_equal_weights_same_as_simple_mean(self):
        """When all instances have same day structure, two-stage = simple mean."""
        from pipeline import climatological_mean

        data = [
            [[10.0]], [[20.0]], [[30.0]],
            [[40.0]], [[50.0]], [[60.0]],
        ]
        day_counts = [30.0, 30.0, 30.0, 30.0, 30.0, 30.0]
        seasons = {(1, 'X'): [0, 1, 2], (2, 'X'): [3, 4, 5]}

        clim = climatological_mean(data, seasons, day_counts)
        assert abs(clim['X'][0][0] - 35.0) < 1e-10


class TestCellMethods:
    """Verify CF cell_methods format with qualifiers."""

    def test_format_with_within_qualifier(self):
        from pipeline import format_cell_methods
        ops = [{'axes': 'time', 'method': 'mean', 'qualifiers': {'within': 'years'}}]
        cm = format_cell_methods(ops)
        assert 'within: years' in cm, \
            f"cell_methods missing 'within: years': {cm}"

    def test_format_with_over_qualifier(self):
        from pipeline import format_cell_methods
        ops = [{'axes': 'time', 'method': 'mean', 'qualifiers': {'over': 'years'}}]
        cm = format_cell_methods(ops)
        assert 'over: years' in cm, \
            f"cell_methods missing 'over: years': {cm}"

    def test_format_area_mean(self):
        from pipeline import format_cell_methods
        ops = [{'axes': 'area', 'method': 'mean'}]
        cm = format_cell_methods(ops)
        assert cm == 'area: mean'

    def test_full_chain(self):
        from pipeline import format_cell_methods
        ops = [
            {'axes': 'time', 'method': 'mean', 'qualifiers': {'within': 'years'}},
            {'axes': 'time', 'method': 'mean', 'qualifiers': {'over': 'years'}},
            {'axes': 'area', 'method': 'mean'},
        ]
        cm = format_cell_methods(ops)
        assert cm.count('time: mean') == 2, \
            f"Expected 2 'time: mean' in: {cm}"
        assert 'within: years' in cm
        assert 'over: years' in cm
        assert 'area: mean' in cm


class TestEndToEnd:
    """End-to-end integration tests against reference output."""

    @pytest.fixture(autouse=True)
    def setup(self):
        with open('/app/data/reference_output.json') as f:
            self.ref = json.load(f)

    def _process(self, cal):
        from pipeline import process_field
        return process_field(f'/app/data/field_{cal}.json')

    def test_standard_djf(self):
        r = self._process('standard')
        exp = self.ref['field_standard']['global_means']['DJF']
        assert abs(r['global_means']['DJF'] - exp) < 1e-4, \
            f"Standard DJF: {r['global_means']['DJF']} != {exp}"

    def test_standard_mam(self):
        r = self._process('standard')
        exp = self.ref['field_standard']['global_means']['MAM']
        assert abs(r['global_means']['MAM'] - exp) < 1e-4

    def test_standard_jja(self):
        r = self._process('standard')
        exp = self.ref['field_standard']['global_means']['JJA']
        assert abs(r['global_means']['JJA'] - exp) < 1e-4

    def test_standard_son(self):
        r = self._process('standard')
        exp = self.ref['field_standard']['global_means']['SON']
        assert abs(r['global_means']['SON'] - exp) < 1e-4

    def test_360day_djf(self):
        r = self._process('360day')
        exp = self.ref['field_360day']['global_means']['DJF']
        assert abs(r['global_means']['DJF'] - exp) < 1e-4

    def test_360day_mam(self):
        r = self._process('360day')
        exp = self.ref['field_360day']['global_means']['MAM']
        assert abs(r['global_means']['MAM'] - exp) < 1e-4

    def test_360day_jja(self):
        r = self._process('360day')
        exp = self.ref['field_360day']['global_means']['JJA']
        assert abs(r['global_means']['JJA'] - exp) < 1e-4

    def test_360day_son(self):
        r = self._process('360day')
        exp = self.ref['field_360day']['global_means']['SON']
        assert abs(r['global_means']['SON'] - exp) < 1e-4

    def test_noleap_djf(self):
        r = self._process('noleap')
        exp = self.ref['field_noleap']['global_means']['DJF']
        assert abs(r['global_means']['DJF'] - exp) < 1e-4

    def test_noleap_jja(self):
        r = self._process('noleap')
        exp = self.ref['field_noleap']['global_means']['JJA']
        assert abs(r['global_means']['JJA'] - exp) < 1e-4

    def test_standard_vs_360day_djf_differ(self):
        """DJF weighted means must differ between standard and 360-day."""
        r_std = self._process('standard')
        r_360 = self._process('360day')
        diff = abs(r_std['global_means']['DJF'] - r_360['global_means']['DJF'])
        assert diff > 0.001, \
            f"Standard vs 360-day DJF should differ, got diff={diff}"

    def test_standard_vs_noleap_djf_differ(self):
        """DJF must differ between standard and noleap (Feb 2004 leap vs not)."""
        r_std = self._process('standard')
        r_nol = self._process('noleap')
        diff = abs(r_std['global_means']['DJF'] - r_nol['global_means']['DJF'])
        assert diff > 0.001, \
            f"Standard vs noleap DJF should differ, got diff={diff}"

    def test_standard_vs_360day_jja_differ(self):
        """JJA must differ between standard and 360-day."""
        r_std = self._process('standard')
        r_360 = self._process('360day')
        diff = abs(r_std['global_means']['JJA'] - r_360['global_means']['JJA'])
        assert diff > 0.001, \
            f"Standard vs 360-day JJA should differ, got diff={diff}"

    def test_standard_clim_0_0_djf(self):
        r = self._process('standard')
        exp = self.ref['field_standard']['climatology_0_0']['DJF']
        assert abs(r['seasonal_climatologies']['DJF'][0][0] - exp) < 1e-4

    def test_standard_clim_0_0_jja(self):
        r = self._process('standard')
        exp = self.ref['field_standard']['climatology_0_0']['JJA']
        assert abs(r['seasonal_climatologies']['JJA'][0][0] - exp) < 1e-4

    def test_seasons_used_djf(self):
        r = self._process('standard')
        exp = self.ref['field_standard']['seasons_used']['DJF']
        assert r['seasons_used']['DJF'] == exp, \
            f"DJF years: {r['seasons_used']['DJF']} != {exp}"

    def test_seasons_used_mam(self):
        r = self._process('standard')
        exp = self.ref['field_standard']['seasons_used']['MAM']
        assert r['seasons_used']['MAM'] == exp

    def test_output_cell_methods(self):
        """process_field must produce cell_methods with qualifiers."""
        r = self._process('standard')
        for sn in ['DJF', 'MAM', 'JJA', 'SON']:
            cm = r['cell_methods'][sn]
            assert 'within: years' in cm, \
                f"{sn} cell_methods missing 'within: years': {cm}"
            assert 'over: years' in cm, \
                f"{sn} cell_methods missing 'over: years': {cm}"
            assert 'area: mean' in cm
            assert cm.count('time: mean') == 2

    def test_spatial_pattern(self):
        """Spatial gradient must be preserved in climatological fields."""
        r = self._process('standard')
        djf = r['seasonal_climatologies']['DJF']
        # Data formula: +0.1 per lat, +0.01 per lon
        assert abs(djf[1][0] - djf[0][0] - 0.1) < 1e-10
        assert abs(djf[0][1] - djf[0][0] - 0.01) < 1e-10

    def test_output_keys(self):
        r = self._process('standard')
        required = {'seasonal_climatologies', 'global_means', 'cell_methods',
                     'seasons_used', 'area_weights'}
        assert set(r.keys()) == required

    def test_all_four_seasons(self):
        r = self._process('standard')
        for key in ['seasonal_climatologies', 'global_means', 'cell_methods']:
            assert set(r[key].keys()) == {'DJF', 'MAM', 'JJA', 'SON'}

    def test_climatology_shape(self):
        r = self._process('standard')
        for sn in ['DJF', 'MAM', 'JJA', 'SON']:
            clim = r['seasonal_climatologies'][sn]
            assert len(clim) == 4, f"{sn} should have 4 lat rows"
            assert len(clim[0]) == 6, f"{sn} should have 6 lon cols"

    def test_area_weights_shape(self):
        r = self._process('standard')
        w = r['area_weights']
        assert len(w) == 4
        assert len(w[0]) == 6
