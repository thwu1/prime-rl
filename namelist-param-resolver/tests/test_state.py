
import pytest
import json
import sys
import os

sys.path.insert(0, "/app")

REFERENCE_DIR = "/app/reference"
XML_PATH = "/app/namelist_defaults.xml"


def load_reference(name):
    path = os.path.join(REFERENCE_DIR, f"{name}.json")
    with open(path) as f:
        return json.load(f)


@pytest.fixture
def make_resolver():
    """Factory fixture to create resolvers from reference files."""
    from resolver import NamelistResolver

    def _make(name):
        ref = load_reference(name)
        return NamelistResolver(XML_PATH, ref["case_env"]), ref["expected"]
    return _make


# ===================================================================
# Default case (ne30pg2, WCYCL1850_EAM_ELM)
# ===================================================================

class TestDefaultCase:

    @pytest.fixture(autouse=True)
    def setup(self, make_resolver):
        self.resolver, self.expected = make_resolver("default")

    def test_dynamics_time_step(self):
        assert self.resolver.get("atmosphere.dynamics.time_step") == 900.0

    def test_dynamics_nsplit(self):
        assert self.resolver.get("atmosphere.dynamics.nsplit") == 2

    def test_dynamics_rsplit(self):
        assert self.resolver.get("atmosphere.dynamics.rsplit") == 3

    def test_dynamics_qsplit(self):
        assert self.resolver.get("atmosphere.dynamics.qsplit") == 1

    def test_coupling_frequency_pipe_alternation(self):
        assert self.resolver.get("atmosphere.dynamics.coupling_frequency") == 2

    def test_partmethod_default(self):
        assert self.resolver.get("atmosphere.dynamics.partmethod") == 4

    def test_microphysics_scheme(self):
        assert self.resolver.get("atmosphere.physics.microphysics.scheme") == "p3"

    def test_prescribed_ccn_enabled(self):
        assert self.resolver.get("atmosphere.physics.microphysics.do_prescribed_ccn") is True

    def test_orbital_year(self):
        assert self.resolver.get("atmosphere.physics.radiation.orbital_year") == 1850

    def test_rrtmgp_coefficients(self):
        assert self.resolver.get("atmosphere.physics.radiation.rrtmgp_coefficients") == \
            "/data/inputdata/rrtmgp/coefficients_lw.nc"

    def test_apply_tms_true(self):
        assert self.resolver.get("atmosphere.physics.turbulence.apply_tms") is True

    def test_deep_scheme(self):
        assert self.resolver.get("atmosphere.physics.convection.deep_scheme") == "zm"

    def test_apply_to_test_grids_true(self):
        assert self.resolver.get("atmosphere.physics.convection.apply_to_test_grids") is True

    def test_ic_file_resolved(self):
        assert self.resolver.get("atmosphere.initial_conditions.ic_file") == \
            "/data/inputdata/init/ne30pg2_L72.nc"

    def test_topography_file_resolved(self):
        assert self.resolver.get("atmosphere.initial_conditions.topography_file") == \
            "/data/inputdata/topo/ne30pg2_topo.nc"


# ===================================================================
# Hires case (ne120pg2, WCYCL1850_EAM_noAero)
# ===================================================================

class TestHiresCase:

    @pytest.fixture(autouse=True)
    def setup(self, make_resolver):
        self.resolver, self.expected = make_resolver("hires")

    def test_dynamics_time_step(self):
        assert self.resolver.get("atmosphere.dynamics.time_step") == 150.0

    def test_max_total_ni_hires(self):
        assert abs(self.resolver.get("atmosphere.physics.microphysics.max_total_ni") - 1480000.0) < 1.0

    def test_autoconversion_prefactor(self):
        assert self.resolver.get("atmosphere.physics.microphysics.autoconversion_prefactor") == 2700.0

    def test_prescribed_ccn_disabled_noaero(self):
        assert self.resolver.get("atmosphere.physics.microphysics.do_prescribed_ccn") is False

    def test_aerosol_rad_disabled_noaero(self):
        assert self.resolver.get("atmosphere.physics.radiation.do_aerosol_rad") is False

    def test_lambda_high_hires(self):
        assert self.resolver.get("atmosphere.physics.turbulence.lambda_high") == 0.02

    def test_radiation_dt_hires(self):
        assert self.resolver.get("atmosphere.physics.radiation.radiation_dt") == 1800.0

    def test_coupling_frequency_pipe_alternation(self):
        assert self.resolver.get("atmosphere.dynamics.coupling_frequency") == 2

    def test_ic_file_hires(self):
        assert self.resolver.get("atmosphere.initial_conditions.ic_file") == \
            "/data/inputdata/init/ne120pg2_L72.nc"

    def test_topography_file_hires(self):
        assert self.resolver.get("atmosphere.initial_conditions.topography_file") == \
            "/data/inputdata/topo/ne120pg2_topo.nc"


# ===================================================================
# SCREAM case (ne4pg2, SCREAM_SSP245)
# ===================================================================

class TestScreamCase:

    @pytest.fixture(autouse=True)
    def setup(self, make_resolver):
        self.resolver, self.expected = make_resolver("scream")

    def test_dynamics_time_step(self):
        assert self.resolver.get("atmosphere.dynamics.time_step") == 1800.0

    def test_nsplit_128_levels(self):
        assert self.resolver.get("atmosphere.dynamics.nsplit") == 4

    def test_rsplit_unchanged(self):
        assert self.resolver.get("atmosphere.dynamics.rsplit") == 3

    def test_qsplit_40_tracers_128_levels(self):
        assert self.resolver.get("atmosphere.dynamics.qsplit") == 4

    def test_coupling_frequency_ne4(self):
        assert self.resolver.get("atmosphere.dynamics.coupling_frequency") == 4

    def test_deep_convection_disabled(self):
        assert self.resolver.get("atmosphere.physics.convection.deep_scheme") == "none"

    def test_orbital_year_ssp(self):
        assert self.resolver.get("atmosphere.physics.radiation.orbital_year") == 2015

    def test_apply_tms_false_ne4(self):
        assert self.resolver.get("atmosphere.physics.turbulence.apply_tms") is False

    def test_apply_to_test_grids_false_ne4(self):
        assert self.resolver.get("atmosphere.physics.convection.apply_to_test_grids") is False

    def test_ic_file_scream(self):
        assert self.resolver.get("atmosphere.initial_conditions.ic_file") == \
            "/data/inputdata/init/ne4pg2_L128.nc"

    def test_topography_file_scream(self):
        assert self.resolver.get("atmosphere.initial_conditions.topography_file") == \
            "/data/inputdata/topo/ne4pg2_topo.nc"


# ===================================================================
# Hybrid case (ne120pg2, SSP245_2010_EAM, nlev=128, ntracers=40)
# ===================================================================

class TestHybridCase:

    @pytest.fixture(autouse=True)
    def setup(self, make_resolver):
        self.resolver, self.expected = make_resolver("hybrid")

    def test_dynamics_time_step(self):
        assert self.resolver.get("atmosphere.dynamics.time_step") == 150.0

    def test_nsplit_128_levels(self):
        assert self.resolver.get("atmosphere.dynamics.nsplit") == 4

    def test_qsplit_compound_selector(self):
        assert self.resolver.get("atmosphere.dynamics.qsplit") == 4

    def test_orbital_year_last_match_wins(self):
        """SSP and 2010 both match the compset; SSP appears later in XML."""
        assert self.resolver.get("atmosphere.physics.radiation.orbital_year") == 2015

    def test_max_total_ni_hires(self):
        assert abs(self.resolver.get("atmosphere.physics.microphysics.max_total_ni") - 1480000.0) < 1.0

    def test_deep_scheme_non_scream(self):
        assert self.resolver.get("atmosphere.physics.convection.deep_scheme") == "zm"

    def test_apply_to_test_grids_true(self):
        assert self.resolver.get("atmosphere.physics.convection.apply_to_test_grids") is True

    def test_coupling_frequency_pipe(self):
        assert self.resolver.get("atmosphere.dynamics.coupling_frequency") == 2

    def test_ic_file_hybrid(self):
        assert self.resolver.get("atmosphere.initial_conditions.ic_file") == \
            "/data/inputdata/init/ne120pg2_L128.nc"

    def test_topography_file_hybrid(self):
        assert self.resolver.get("atmosphere.initial_conditions.topography_file") == \
            "/data/inputdata/topo/ne120pg2_topo.nc"


# ===================================================================
# Negation edge cases
# ===================================================================

class TestNegation:

    def test_negated_compset_prevents_match(self):
        """ne120pg2 passes hgrid negation, but SCREAM compset should fail COMPSET negation."""
        from resolver import NamelistResolver
        r = NamelistResolver(XML_PATH, {
            "ATM_GRID": "ne120pg2",
            "COMPSET": "SCREAM_noAero",
            "CMAKE_OPTIONS": "SCREAM_NUM_VERTICAL_LEV 72 SCREAM_NUM_TRACERS 10",
            "DIN_LOC_ROOT": "/data/inputdata",
        })
        assert r.get("atmosphere.physics.convection.apply_to_test_grids") is False

    def test_negated_exact_selector_passes(self):
        from resolver import NamelistResolver
        r = NamelistResolver(XML_PATH, {
            "ATM_GRID": "ne30pg2",
            "COMPSET": "WCYCL1850_EAM_ELM",
            "CMAKE_OPTIONS": "SCREAM_NUM_VERTICAL_LEV 72 SCREAM_NUM_TRACERS 10",
            "DIN_LOC_ROOT": "/data/inputdata",
        })
        assert r.get("atmosphere.physics.turbulence.apply_tms") is True

    def test_negated_exact_selector_blocks(self):
        from resolver import NamelistResolver
        r = NamelistResolver(XML_PATH, {
            "ATM_GRID": "ne4pg2",
            "COMPSET": "WCYCL1850_EAM_ELM",
            "CMAKE_OPTIONS": "SCREAM_NUM_VERTICAL_LEV 72 SCREAM_NUM_TRACERS 10",
            "DIN_LOC_ROOT": "/data/inputdata",
        })
        assert r.get("atmosphere.physics.turbulence.apply_tms") is False


# ===================================================================
# Constraint validation
# ===================================================================

class TestConstraintValidation:

    @pytest.fixture(autouse=True)
    def setup(self, make_resolver):
        self.resolver, _ = make_resolver("default")

    def test_negative_time_step_rejected(self):
        with pytest.raises(ValueError):
            self.resolver.set("atmosphere.dynamics.time_step", "-1")

    def test_zero_time_step_rejected(self):
        with pytest.raises(ValueError):
            self.resolver.set("atmosphere.dynamics.time_step", "0")

    def test_qsplit_above_upper_bound_rejected(self):
        """qsplit constraint: gt 0 @@ le 10 — value 11 should fail."""
        with pytest.raises(ValueError):
            self.resolver.set("atmosphere.dynamics.qsplit", "11")

    def test_qsplit_zero_rejected(self):
        """qsplit constraint: gt 0 @@ le 10 — value 0 should fail."""
        with pytest.raises(ValueError):
            self.resolver.set("atmosphere.dynamics.qsplit", "0")

    def test_compound_constraint_mod_fails(self):
        """radiation_dt must be gt 0 AND mod 300 eq 0; 100 fails mod check."""
        with pytest.raises(ValueError):
            self.resolver.set("atmosphere.physics.radiation.radiation_dt", "100")

    def test_compound_constraint_passes(self):
        self.resolver.set("atmosphere.physics.radiation.radiation_dt", "600")
        assert self.resolver.get("atmosphere.physics.radiation.radiation_dt") == 600.0

    def test_valid_values_rejected(self):
        with pytest.raises(ValueError):
            self.resolver.set("atmosphere.physics.microphysics.scheme", "thompson")

    def test_valid_values_accepted(self):
        self.resolver.set("atmosphere.physics.microphysics.scheme", "mg2")
        assert self.resolver.get("atmosphere.physics.microphysics.scheme") == "mg2"

    def test_partmethod_odd_rejected(self):
        """partmethod constraint: ge 0 @@ mod 2 eq 0; odd values fail."""
        with pytest.raises(ValueError):
            self.resolver.set("atmosphere.dynamics.partmethod", "5")

    def test_partmethod_negative_rejected(self):
        with pytest.raises(ValueError):
            self.resolver.set("atmosphere.dynamics.partmethod", "-1")

    def test_partmethod_even_accepted(self):
        self.resolver.set("atmosphere.dynamics.partmethod", "6")
        assert self.resolver.get("atmosphere.dynamics.partmethod") == 6


# ===================================================================
# Locked parameters
# ===================================================================

class TestLockedParameters:

    @pytest.fixture(autouse=True)
    def setup(self, make_resolver):
        self.resolver, _ = make_resolver("default")

    def test_set_locked_raises(self):
        with pytest.raises(PermissionError):
            self.resolver.set("atmosphere.output.output_fields", "new_field")

    def test_append_locked_raises(self):
        with pytest.raises(PermissionError):
            self.resolver.append("atmosphere.output.output_fields", "new_field")

    def test_remove_locked_raises(self):
        with pytest.raises(PermissionError):
            self.resolver.remove("atmosphere.output.output_fields", "T_mid")

    def test_locked_value_readable(self):
        val = self.resolver.get("atmosphere.output.output_fields")
        assert isinstance(val, list)
        assert "T_mid" in val


# ===================================================================
# Array operations
# ===================================================================

class TestArrayOperations:

    @pytest.fixture(autouse=True)
    def setup(self, make_resolver):
        self.resolver, _ = make_resolver("default")

    def test_array_is_list(self):
        val = self.resolver.get("atmosphere.physics.radiation.active_gases")
        assert isinstance(val, list)
        assert len(val) == 8
        assert "h2o" in val and "n2" in val

    def test_append(self):
        self.resolver.append("atmosphere.physics.radiation.active_gases", "cfc11")
        val = self.resolver.get("atmosphere.physics.radiation.active_gases")
        assert "cfc11" in val
        assert len(val) == 9

    def test_remove(self):
        self.resolver.remove("atmosphere.physics.radiation.active_gases", "n2")
        val = self.resolver.get("atmosphere.physics.radiation.active_gases")
        assert "n2" not in val
        assert "n2o" in val
        assert len(val) == 7

    def test_remove_absent_raises(self):
        with pytest.raises(ValueError):
            self.resolver.remove("atmosphere.physics.radiation.active_gases", "argon")

    def test_append_non_array_raises(self):
        with pytest.raises(TypeError):
            self.resolver.append("atmosphere.dynamics.time_step", "999")


# ===================================================================
# Scope resolution
# ===================================================================

class TestScopeResolution:

    @pytest.fixture(autouse=True)
    def setup(self, make_resolver):
        self.resolver, _ = make_resolver("default")

    def test_full_dot_path(self):
        assert self.resolver.get("atmosphere.dynamics.time_step") == 900.0

    def test_unambiguous_short_name(self):
        assert self.resolver.get("time_step") == 900.0

    def test_scoped_microphysics_subcycles(self):
        assert self.resolver.get("microphysics::subcycles") == 1

    def test_scoped_radiation_subcycles(self):
        assert self.resolver.get("radiation::subcycles") == 3

    def test_ambiguous_short_name_raises(self):
        with pytest.raises((ValueError, KeyError)):
            self.resolver.get("subcycles")

    def test_nonexistent_raises(self):
        with pytest.raises(KeyError):
            self.resolver.get("nonexistent_param_xyz")


# ===================================================================
# YAML output
# ===================================================================

class TestYamlOutput:

    @pytest.fixture(autouse=True)
    def setup(self, make_resolver):
        self.resolver, _ = make_resolver("default")

    def test_yaml_parseable(self):
        import yaml
        output = self.resolver.to_yaml()
        data = yaml.safe_load(output)
        assert isinstance(data, dict)
        assert "atmosphere" in data

    def test_yaml_hierarchy(self):
        import yaml
        output = self.resolver.to_yaml()
        data = yaml.safe_load(output)
        assert data["atmosphere"]["dynamics"]["time_step"] == 900.0
        assert data["atmosphere"]["physics"]["microphysics"]["scheme"] == "p3"
        assert data["atmosphere"]["physics"]["radiation"]["orbital_year"] == 1850


# ===================================================================
# Parameter listing
# ===================================================================

class TestParameterListing:

    @pytest.fixture(autouse=True)
    def setup(self, make_resolver):
        self.resolver, _ = make_resolver("default")

    def test_list_all(self):
        params = self.resolver.list_params()
        assert len(params) == 31

    def test_list_dynamics(self):
        params = self.resolver.list_params("atmosphere.dynamics")
        assert len(params) == 6

    def test_list_microphysics(self):
        params = self.resolver.list_params("atmosphere.physics.microphysics")
        assert len(params) == 5
        assert "atmosphere.physics.microphysics.scheme" in params


# ===================================================================
# Explain — resolution trace
# ===================================================================

class TestExplain:

    @pytest.fixture(autouse=True)
    def setup(self, make_resolver):
        self.resolver, _ = make_resolver("default")

    def test_explain_time_step_structure(self):
        """Verify explain returns all candidate elements with correct match info."""
        trace = self.resolver.explain("atmosphere.dynamics.time_step")
        assert trace["path"] == "atmosphere.dynamics.time_step"
        assert trace["final_value"] == 900.0
        assert trace["type"] == "real"
        elements = trace["elements"]
        assert len(elements) == 4  # default + ne4pg2 + ne30pg2 + ne120pg2
        winners = [e for e in elements if e.get("is_winner")]
        assert len(winners) == 1
        assert winners[0]["selectors"] == {"hgrid": "ne30pg2"}
        assert winners[0]["matched"] is True

    def test_explain_default_wins(self):
        """When no selectored elements match, default wins."""
        trace = self.resolver.explain("atmosphere.dynamics.rsplit")
        assert trace["final_value"] == 3
        elements = trace["elements"]
        assert len(elements) == 1  # only default
        assert elements[0]["is_winner"] is True
        assert elements[0]["selectors"] == {}

    def test_explain_negated_selector(self):
        """Explain should show the raw negated selector attribute."""
        trace = self.resolver.explain("atmosphere.physics.turbulence.apply_tms")
        assert trace["final_value"] is True
        elements = trace["elements"]
        assert len(elements) == 2
        winners = [e for e in elements if e.get("is_winner")]
        assert len(winners) == 1
        assert "hgrid" in winners[0]["selectors"]
        assert winners[0]["selectors"]["hgrid"] == "!ne4pg2"

    def test_explain_last_match_wins_multiple(self):
        """For hybrid case, orbital_year has 3 elements, 2010 and SSP both match."""
        from resolver import NamelistResolver
        r = NamelistResolver(XML_PATH, {
            "ATM_GRID": "ne120pg2",
            "COMPSET": "SSP245_2010_EAM",
            "CMAKE_OPTIONS": "SCREAM_NUM_VERTICAL_LEV 128 SCREAM_NUM_TRACERS 40",
            "DIN_LOC_ROOT": "/data/inputdata",
        })
        trace = r.explain("atmosphere.physics.radiation.orbital_year")
        assert trace["final_value"] == 2015
        elements = trace["elements"]
        assert len(elements) == 3  # default(1850) + 2010 + SSP(2015)
        # Both selectored elements match but last wins
        matched_elements = [e for e in elements if e["matched"]]
        assert len(matched_elements) == 3  # default + 2010 + SSP
        assert elements[-1]["is_winner"] is True
        assert elements[-1]["text"].strip() == "2015"

    def test_explain_compound_selectors(self):
        """apply_to_test_grids has compound selectors (hgrid AND COMPSET)."""
        trace = self.resolver.explain("atmosphere.physics.convection.apply_to_test_grids")
        elements = trace["elements"]
        assert len(elements) == 2
        selectored = [e for e in elements if e["selectors"]]
        assert len(selectored) == 1
        sels = selectored[0]["selectors"]
        assert "hgrid" in sels
        assert "COMPSET" in sels


# ===================================================================
# Diff — configuration comparison
# ===================================================================

class TestDiff:

    @pytest.fixture(autouse=True)
    def setup(self, make_resolver):
        self.default_resolver, _ = make_resolver("default")
        self.hires_resolver, _ = make_resolver("hires")
        self.scream_resolver, _ = make_resolver("scream")

    def test_diff_changed_params(self):
        result = self.default_resolver.diff(self.hires_resolver)
        changed = result["changed"]
        assert "atmosphere.dynamics.time_step" in changed
        assert changed["atmosphere.dynamics.time_step"]["self"] == 900.0
        assert changed["atmosphere.dynamics.time_step"]["other"] == 150.0

    def test_diff_unchanged_excluded(self):
        result = self.default_resolver.diff(self.hires_resolver)
        changed = result["changed"]
        # rsplit is 3 in both default and hires
        assert "atmosphere.dynamics.rsplit" not in changed

    def test_diff_symmetry(self):
        """Diff is symmetric in keys, with swapped self/other values."""
        d1 = self.default_resolver.diff(self.hires_resolver)
        d2 = self.hires_resolver.diff(self.default_resolver)
        assert set(d1["changed"].keys()) == set(d2["changed"].keys())
        for key in d1["changed"]:
            assert d1["changed"][key]["self"] == d2["changed"][key]["other"]
            assert d1["changed"][key]["other"] == d2["changed"][key]["self"]

    def test_diff_only_self_only_other_type(self):
        """Verify only_self and only_other are lists."""
        result = self.default_resolver.diff(self.hires_resolver)
        assert isinstance(result["only_self"], list)
        assert isinstance(result["only_other"], list)

    def test_diff_multiple_changes_detected(self):
        """Default vs scream should show many differences."""
        result = self.default_resolver.diff(self.scream_resolver)
        changed = result["changed"]
        # These should differ between default and scream
        assert "atmosphere.dynamics.time_step" in changed
        assert "atmosphere.physics.convection.deep_scheme" in changed
        assert "atmosphere.physics.radiation.orbital_year" in changed
        assert "atmosphere.dynamics.coupling_frequency" in changed


# ===================================================================
# Pipe alternation in selectors
# ===================================================================

class TestPipeAlternation:

    def test_pipe_matches_first_alternative(self):
        """ne30pg2 matches the first alternative in ne30pg2|ne120pg2."""
        from resolver import NamelistResolver
        r = NamelistResolver(XML_PATH, {
            "ATM_GRID": "ne30pg2",
            "COMPSET": "WCYCL1850_EAM_ELM",
            "CMAKE_OPTIONS": "SCREAM_NUM_VERTICAL_LEV 72 SCREAM_NUM_TRACERS 10",
            "DIN_LOC_ROOT": "/data/inputdata",
        })
        assert r.get("atmosphere.dynamics.coupling_frequency") == 2

    def test_pipe_matches_second_alternative(self):
        """ne120pg2 matches the second alternative in ne30pg2|ne120pg2."""
        from resolver import NamelistResolver
        r = NamelistResolver(XML_PATH, {
            "ATM_GRID": "ne120pg2",
            "COMPSET": "WCYCL1850_EAM_ELM",
            "CMAKE_OPTIONS": "SCREAM_NUM_VERTICAL_LEV 72 SCREAM_NUM_TRACERS 10",
            "DIN_LOC_ROOT": "/data/inputdata",
        })
        assert r.get("atmosphere.dynamics.coupling_frequency") == 2

    def test_pipe_no_match_falls_through(self):
        """ne4pg2 does NOT match ne30pg2|ne120pg2, should match ne4pg2 entry."""
        from resolver import NamelistResolver
        r = NamelistResolver(XML_PATH, {
            "ATM_GRID": "ne4pg2",
            "COMPSET": "WCYCL1850_EAM_ELM",
            "CMAKE_OPTIONS": "SCREAM_NUM_VERTICAL_LEV 72 SCREAM_NUM_TRACERS 10",
            "DIN_LOC_ROOT": "/data/inputdata",
        })
        assert r.get("atmosphere.dynamics.coupling_frequency") == 4

    def test_pipe_unmatchable_uses_default(self):
        """Grid not matching any selectored entry falls back to default."""
        from resolver import NamelistResolver
        r = NamelistResolver(XML_PATH, {
            "ATM_GRID": "ne256pg2",
            "COMPSET": "WCYCL1850_EAM_ELM",
            "CMAKE_OPTIONS": "SCREAM_NUM_VERTICAL_LEV 72 SCREAM_NUM_TRACERS 10",
            "DIN_LOC_ROOT": "/data/inputdata",
        })
        assert r.get("atmosphere.dynamics.coupling_frequency") == 1
