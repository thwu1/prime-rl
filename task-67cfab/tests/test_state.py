
import json
import os
import sqlite3
import xml.etree.ElementTree as ET


# ── Reference helpers ────────────────────────────────────────────────


def _parse_compsets_ref(xml_path):
    """Parse config_compsets.xml -> {alias: longname}."""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    compsets = {}
    for compset_el in root.findall(".//compset"):
        alias_el = compset_el.find("alias")
        lname_el = compset_el.find("lname")
        if alias_el is not None and lname_el is not None:
            compsets[alias_el.text.strip()] = lname_el.text.strip()
    return compsets


def _parse_atm_processes_ref(xml_path):
    """Parse atmosphere process definitions from eamxx_namelist_defaults.xml."""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    apd = root.find("atmosphere_processes_defaults")
    procs = {}
    if apd is None:
        return procs
    for child in apd:
        name = child.tag
        parent = child.get("inherit")
        # is_group if inherits from atm_proc_group or has <type>group</type>
        is_group = parent == "atm_proc_group"
        type_el = child.find("type")
        if type_el is not None and type_el.text and type_el.text.strip() == "group":
            is_group = True
        procs[name] = {"parent": parent, "is_group": is_group}
    return procs


def _find_constrained_params_ref(xml_path):
    """Find all parameter names with constraints attribute."""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    params = set()
    for el in root.iter():
        if el.get("constraints"):
            params.add(el.tag)
    return sorted(params)


def _parse_suites_ref(py_path):
    """Parse test_suites.py by exec'ing it -> dict of suite defs."""
    with open(py_path) as f:
        content = f.read()
    ns = {}
    exec(content, ns)
    return ns["_TESTS"]


def _get_suite_tests(suite_name, suites, cache=None):
    """Recursively resolve all unique tests for a suite."""
    if cache is None:
        cache = {}
    if suite_name in cache:
        return cache[suite_name]
    suite = suites[suite_name]
    tests = set()
    raw_tests = suite.get("tests", ())
    if isinstance(raw_tests, str):
        tests.add(raw_tests)
    else:
        for t in raw_tests:
            tests.add(t)
    inherit = suite.get("inherit")
    if inherit is not None:
        if isinstance(inherit, str):
            parents = [inherit]
        else:
            parents = list(inherit)
        for parent in parents:
            tests |= _get_suite_tests(parent, suites, cache)
    cache[suite_name] = tests
    return tests


def _inheritance_depth(suite_name, suites, cache=None):
    """Compute inheritance depth (0 = no parents)."""
    if cache is None:
        cache = {}
    if suite_name in cache:
        return cache[suite_name]
    suite = suites[suite_name]
    inherit = suite.get("inherit")
    if inherit is None:
        cache[suite_name] = 0
        return 0
    if isinstance(inherit, str):
        parents = [inherit]
    else:
        parents = list(inherit)
    if len(parents) == 0:
        cache[suite_name] = 0
        return 0
    max_parent = max(_inheritance_depth(p, suites, cache) for p in parents)
    depth = 1 + max_parent
    cache[suite_name] = depth
    return depth


def _parse_longname_ref(longname):
    """Parse a compset longname into components."""
    slots = ["atm", "lnd", "ice", "ocn", "rof", "glc", "wav"]
    parts = longname.split("_")
    result = {"time": parts[0]}
    for i, slot in enumerate(slots):
        if i + 1 < len(parts):
            part = parts[i + 1]
            if "%" in part:
                model, physics = part.split("%", 1)
            else:
                model, physics = part, None
            result[slot] = {"model": model, "physics": physics}
    if len(parts) > 8:
        bgc_part = parts[8]
        if bgc_part.startswith("BGC%"):
            model, physics = bgc_part.split("%", 1)
            result["bgc"] = {"model": model, "physics": physics}
    return result


def _get_physics_pipeline_variants_ref(xml_path):
    """Extract physics pipeline variants from the XML."""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    apd = root.find("atmosphere_processes_defaults")
    physics = apd.find("physics")
    variants = {}
    selector_attrs = {"hgrid", "nlev", "COMPSET", "dyn", "ntracers"}
    for el in physics:
        if el.tag == "atm_procs_list" and el.text:
            compset = el.get("COMPSET")
            if compset:
                variants[compset] = el.text.strip()
            elif not any(k in selector_attrs for k in el.attrib):
                variants["default"] = el.text.strip()
    return variants


def _get_grid_rad_frequencies_ref(xml_path):
    """Extract grid-specific radiation frequency overrides."""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    apd = root.find("atmosphere_processes_defaults")
    rrtmgp = apd.find("rrtmgp")
    freqs = {}
    for el in rrtmgp:
        if el.tag == "rad_frequency" and el.text:
            hgrid = el.get("hgrid")
            compset = el.get("COMPSET")
            if hgrid:
                freqs[hgrid] = el.text.strip()
            elif compset:
                freqs[f"COMPSET:{compset}"] = el.text.strip()
    return freqs


def _get_eamxx_default_pipeline_ref(xml_path):
    """Get the default eamxx atmosphere process list."""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    apd = root.find("atmosphere_processes_defaults")
    eamxx = apd.find("eamxx")
    selector_attrs = {"hgrid", "nlev", "COMPSET", "dyn", "ntracers"}
    for el in eamxx:
        if el.tag == "atm_procs_list" and el.text:
            if not any(k in selector_attrs for k in el.attrib):
                return el.text.strip()
    return None


# ── Tests ────────────────────────────────────────────────────────────


class TestOutputFilesExist:
    def test_query_results_exists(self):
        assert os.path.exists("/app/query_results.json"), "query_results.json not found"

    def test_database_exists(self):
        assert os.path.exists("/app/e3sm_config.db"), "e3sm_config.db not found"

    def test_query_results_valid_json(self):
        with open("/app/query_results.json") as f:
            data = json.load(f)
        assert isinstance(data, dict)


class TestDatabaseSchema:
    def setup_method(self):
        self.conn = sqlite3.connect("/app/e3sm_config.db")
        self.cur = self.conn.cursor()

    def teardown_method(self):
        self.conn.close()

    def test_compsets_table_exists(self):
        self.cur.execute("SELECT count(*) FROM compsets")
        count = self.cur.fetchone()[0]
        assert count > 0

    def test_atm_processes_table_exists(self):
        self.cur.execute("SELECT count(*) FROM atm_processes")
        count = self.cur.fetchone()[0]
        assert count > 0

    def test_test_suites_table_exists(self):
        self.cur.execute("SELECT count(*) FROM test_suites")
        count = self.cur.fetchone()[0]
        assert count > 0

    def test_compsets_has_alias_column(self):
        self.cur.execute("SELECT alias FROM compsets LIMIT 1")
        assert self.cur.fetchone() is not None

    def test_compsets_has_longname_column(self):
        self.cur.execute("SELECT longname FROM compsets LIMIT 1")
        assert self.cur.fetchone() is not None

    def test_atm_processes_has_parent_column(self):
        self.cur.execute("SELECT parent FROM atm_processes LIMIT 1")

    def test_atm_processes_has_is_group_column(self):
        self.cur.execute("SELECT is_group FROM atm_processes LIMIT 1")

    def test_test_suites_has_columns(self):
        self.cur.execute("SELECT direct_test_count, inherits_from FROM test_suites LIMIT 1")


class TestDatabaseContents:
    def setup_method(self):
        self.conn = sqlite3.connect("/app/e3sm_config.db")
        self.cur = self.conn.cursor()
        self.compsets = _parse_compsets_ref("/app/config_compsets.xml")
        self.procs = _parse_atm_processes_ref("/app/eamxx_namelist_defaults.xml")
        self.suites = _parse_suites_ref("/app/test_suites.py")

    def teardown_method(self):
        self.conn.close()

    def test_compsets_count_matches(self):
        self.cur.execute("SELECT count(*) FROM compsets")
        db_count = self.cur.fetchone()[0]
        assert db_count == len(self.compsets)

    def test_specific_compset_in_db(self):
        self.cur.execute("SELECT longname FROM compsets WHERE alias='WCYCL1850'")
        row = self.cur.fetchone()
        assert row is not None
        assert row[0] == self.compsets["WCYCL1850"]

    def test_atm_processes_count_matches(self):
        self.cur.execute("SELECT count(*) FROM atm_processes")
        db_count = self.cur.fetchone()[0]
        assert db_count == len(self.procs)

    def test_specific_process_parent(self):
        self.cur.execute("SELECT parent FROM atm_processes WHERE name='p3'")
        row = self.cur.fetchone()
        assert row is not None
        assert row[0] == "atm_proc_base"

    def test_group_processes(self):
        self.cur.execute("SELECT name FROM atm_processes WHERE is_group=1 ORDER BY name")
        groups = [r[0] for r in self.cur.fetchall()]
        expected_groups = sorted(
            name for name, info in self.procs.items() if info["is_group"]
        )
        assert groups == expected_groups

    def test_test_suites_count_matches(self):
        self.cur.execute("SELECT count(*) FROM test_suites")
        db_count = self.cur.fetchone()[0]
        assert db_count == len(self.suites)

    def test_specific_suite_direct_count(self):
        self.cur.execute(
            "SELECT direct_test_count FROM test_suites WHERE name='e3sm_mosart_sediment'"
        )
        row = self.cur.fetchone()
        assert row is not None
        raw = self.suites["e3sm_mosart_sediment"].get("tests", ())
        expected = 1 if isinstance(raw, str) else len(raw)
        assert row[0] == expected


class TestTotalCompsets:
    def test_value(self):
        with open("/app/query_results.json") as f:
            results = json.load(f)
        expected = len(_parse_compsets_ref("/app/config_compsets.xml"))
        assert results["total_compsets"] == expected


class TestAtmProcessHierarchy:
    def setup_method(self):
        with open("/app/query_results.json") as f:
            self.results = json.load(f)
        self.procs = _parse_atm_processes_ref("/app/eamxx_namelist_defaults.xml")

    def test_all_processes_present(self):
        hierarchy = self.results["atm_process_hierarchy"]
        assert set(hierarchy.keys()) == set(self.procs.keys())

    def test_parents_correct(self):
        hierarchy = self.results["atm_process_hierarchy"]
        for name, info in self.procs.items():
            assert hierarchy[name] == info["parent"], f"Wrong parent for {name}"

    def test_atm_proc_base_has_no_parent(self):
        hierarchy = self.results["atm_process_hierarchy"]
        assert hierarchy["atm_proc_base"] is None

    def test_p3_inherits_atm_proc_base(self):
        hierarchy = self.results["atm_process_hierarchy"]
        assert hierarchy["p3"] == "atm_proc_base"

    def test_mac_aero_mic_inherits_atm_proc_group(self):
        hierarchy = self.results["atm_process_hierarchy"]
        assert hierarchy["mac_aero_mic"] == "atm_proc_group"

    def test_mam4_aci_inherits_mam4_atm_proc_base(self):
        hierarchy = self.results["atm_process_hierarchy"]
        assert hierarchy["mam4_aci"] == "mam4_atm_proc_base"


class TestNumAtmProcesses:
    def test_value(self):
        with open("/app/query_results.json") as f:
            results = json.load(f)
        expected = len(_parse_atm_processes_ref("/app/eamxx_namelist_defaults.xml"))
        assert results["num_atm_processes"] == expected

    def test_greater_than_20(self):
        with open("/app/query_results.json") as f:
            results = json.load(f)
        assert results["num_atm_processes"] > 20


class TestConstrainedParams:
    def test_correct_list(self):
        with open("/app/query_results.json") as f:
            results = json.load(f)
        expected = _find_constrained_params_ref("/app/eamxx_namelist_defaults.xml")
        assert results["constrained_params"] == expected

    def test_contains_number_of_subcycles(self):
        with open("/app/query_results.json") as f:
            results = json.load(f)
        assert "number_of_subcycles" in results["constrained_params"]

    def test_contains_se_tstep(self):
        with open("/app/query_results.json") as f:
            results = json.load(f)
        assert "se_tstep" in results["constrained_params"]

    def test_sorted(self):
        with open("/app/query_results.json") as f:
            results = json.load(f)
        lst = results["constrained_params"]
        assert lst == sorted(lst)


class TestSuiteResolvedCounts:
    def setup_method(self):
        with open("/app/query_results.json") as f:
            self.results = json.load(f)
        self.suites = _parse_suites_ref("/app/test_suites.py")

    def test_developer_count(self):
        expected = len(_get_suite_tests("e3sm_developer", self.suites))
        assert self.results["suite_resolved_counts"]["e3sm_developer"] == expected

    def test_integration_count(self):
        expected = len(_get_suite_tests("e3sm_integration", self.suites))
        assert self.results["suite_resolved_counts"]["e3sm_integration"] == expected

    def test_fates_count(self):
        expected = len(_get_suite_tests("fates", self.suites))
        assert self.results["suite_resolved_counts"]["fates"] == expected

    def test_developer_greater_than_50(self):
        assert self.results["suite_resolved_counts"]["e3sm_developer"] > 50

    def test_integration_greater_than_developer(self):
        assert (
            self.results["suite_resolved_counts"]["e3sm_integration"]
            > self.results["suite_resolved_counts"]["e3sm_developer"]
        )


class TestMaxInheritanceDepth:
    def setup_method(self):
        with open("/app/query_results.json") as f:
            self.results = json.load(f)
        self.suites = _parse_suites_ref("/app/test_suites.py")

    def test_depth_value(self):
        depth_cache = {}
        max_name, max_depth = None, -1
        for name in self.suites:
            d = _inheritance_depth(name, self.suites, depth_cache)
            if d > max_depth:
                max_depth = d
                max_name = name
        result = self.results["max_inheritance_depth"]
        assert result["depth"] == max_depth
        assert _inheritance_depth(result["suite"], self.suites) == max_depth


class TestCompsetsByBGCMode:
    def setup_method(self):
        with open("/app/query_results.json") as f:
            self.results = json.load(f)
        self.compsets = _parse_compsets_ref("/app/config_compsets.xml")

    def _expected_bgc_modes(self):
        modes = {}
        for alias, lname in self.compsets.items():
            parts = lname.split("_")
            for p in parts:
                if p.startswith("BGC%"):
                    mode = p.split("%", 1)[1]
                    modes.setdefault(mode, []).append(alias)
        return {m: sorted(v) for m, v in modes.items()}

    def test_correct_modes(self):
        expected = self._expected_bgc_modes()
        result = self.results["compsets_by_bgc_mode"]
        assert set(result.keys()) == set(expected.keys())
        for mode in expected:
            assert sorted(result[mode]) == expected[mode], f"Mismatch for BGC mode {mode}"

    def test_each_mode_sorted(self):
        for mode, aliases in self.results["compsets_by_bgc_mode"].items():
            assert aliases == sorted(aliases), f"BGC mode {mode} not sorted"


class TestCompsetComponentBreakdown:
    def setup_method(self):
        with open("/app/query_results.json") as f:
            self.results = json.load(f)
        self.compsets = _parse_compsets_ref("/app/config_compsets.xml")

    def test_all_three_present(self):
        cc = self.results["compset_component_breakdown"]
        assert "CRYO1850-DISMF" in cc
        assert "MPAS_LISIO_JRA1p5" in cc
        assert "WCYCLXX2010" in cc

    def test_longnames_match(self):
        cc = self.results["compset_component_breakdown"]
        for alias in ["CRYO1850-DISMF", "MPAS_LISIO_JRA1p5", "WCYCLXX2010"]:
            assert cc[alias]["longname"] == self.compsets[alias]

    def test_cryo_dismf_time(self):
        cc = self.results["compset_component_breakdown"]["CRYO1850-DISMF"]
        ref = _parse_longname_ref(self.compsets["CRYO1850-DISMF"])
        assert cc["time"] == ref["time"]

    def test_cryo_dismf_atm(self):
        cc = self.results["compset_component_breakdown"]["CRYO1850-DISMF"]
        assert cc["atm"]["model"] == "EAM"
        assert cc["atm"]["physics"] == "CMIP6"

    def test_cryo_dismf_ice(self):
        cc = self.results["compset_component_breakdown"]["CRYO1850-DISMF"]
        assert cc["ice"]["model"] == "MPASSI"
        assert cc["ice"]["physics"] == "DIB"

    def test_cryo_dismf_ocn(self):
        cc = self.results["compset_component_breakdown"]["CRYO1850-DISMF"]
        assert cc["ocn"]["model"] == "MPASO"
        assert cc["ocn"]["physics"] == "IBDISMF"

    def test_cryo_dismf_glc_stub(self):
        cc = self.results["compset_component_breakdown"]["CRYO1850-DISMF"]
        assert cc["glc"]["model"] == "SGLC"

    def test_mpas_lisio_atm_data(self):
        cc = self.results["compset_component_breakdown"]["MPAS_LISIO_JRA1p5"]
        assert cc["atm"]["model"] == "DATM"
        assert cc["atm"]["physics"] == "JRA-1p5"

    def test_mpas_lisio_lnd_stub(self):
        cc = self.results["compset_component_breakdown"]["MPAS_LISIO_JRA1p5"]
        assert cc["lnd"]["model"] == "SLND"

    def test_mpas_lisio_glc(self):
        cc = self.results["compset_component_breakdown"]["MPAS_LISIO_JRA1p5"]
        assert cc["glc"]["model"] == "MALI"
        assert cc["glc"]["physics"] == "SIA"

    def test_wcyclxx2010_atm(self):
        cc = self.results["compset_component_breakdown"]["WCYCLXX2010"]
        assert cc["atm"]["model"] == "SCREAM"

    def test_wcyclxx2010_lnd(self):
        cc = self.results["compset_component_breakdown"]["WCYCLXX2010"]
        assert cc["lnd"]["model"] == "ELM"
        assert cc["lnd"]["physics"] == "SPBC"

    def test_components_match_reference(self):
        cc = self.results["compset_component_breakdown"]
        for alias in ["CRYO1850-DISMF", "MPAS_LISIO_JRA1p5", "WCYCLXX2010"]:
            ref = _parse_longname_ref(self.compsets[alias])
            slots = ["atm", "lnd", "ice", "ocn", "rof", "glc", "wav"]
            for slot in slots:
                if slot in ref:
                    assert cc[alias][slot]["model"] == ref[slot]["model"], (
                        f"{alias}.{slot}.model mismatch"
                    )
                    assert cc[alias][slot]["physics"] == ref[slot]["physics"], (
                        f"{alias}.{slot}.physics mismatch"
                    )


class TestEamxxDefaultPipeline:
    def test_value(self):
        with open("/app/query_results.json") as f:
            results = json.load(f)
        expected = _get_eamxx_default_pipeline_ref("/app/eamxx_namelist_defaults.xml")
        assert results["eamxx_default_pipeline"] == expected

    def test_contains_physics(self):
        with open("/app/query_results.json") as f:
            results = json.load(f)
        assert "physics" in results["eamxx_default_pipeline"]

    def test_contains_homme(self):
        with open("/app/query_results.json") as f:
            results = json.load(f)
        assert "homme" in results["eamxx_default_pipeline"]


class TestPhysicsPipelineVariants:
    def setup_method(self):
        with open("/app/query_results.json") as f:
            self.results = json.load(f)
        self.expected = _get_physics_pipeline_variants_ref(
            "/app/eamxx_namelist_defaults.xml"
        )

    def test_all_keys_present(self):
        result = self.results["physics_pipeline_variants"]
        assert set(result.keys()) == set(self.expected.keys())

    def test_default_value(self):
        result = self.results["physics_pipeline_variants"]
        assert result["default"] == self.expected["default"]

    def test_all_values_correct(self):
        result = self.results["physics_pipeline_variants"]
        for key in self.expected:
            assert result[key] == self.expected[key], f"Mismatch for key {key}"

    def test_mam4xx_variant_has_mam4_processes(self):
        result = self.results["physics_pipeline_variants"]
        mam4_key = [k for k in result if "MAM4xx" in k]
        assert len(mam4_key) > 0
        val = result[mam4_key[0]]
        assert "mam4_optics" in val
        assert "mam4_wetscav" in val


class TestGridRadFrequencies:
    def setup_method(self):
        with open("/app/query_results.json") as f:
            self.results = json.load(f)
        self.expected = _get_grid_rad_frequencies_ref("/app/eamxx_namelist_defaults.xml")

    def test_all_keys_present(self):
        result = self.results["grid_rad_frequencies"]
        assert set(result.keys()) == set(self.expected.keys())

    def test_all_values_correct(self):
        result = self.results["grid_rad_frequencies"]
        for key in self.expected:
            assert str(result[key]) == str(self.expected[key]), (
                f"Mismatch for key {key}: got {result[key]}, expected {self.expected[key]}"
            )

    def test_ne4_has_frequency_1(self):
        result = self.results["grid_rad_frequencies"]
        assert str(result.get("ne4np4", "")) == "1"

    def test_ne1024_has_frequency_3(self):
        result = self.results["grid_rad_frequencies"]
        assert str(result.get("ne1024np4", "")) == "3"


class TestCryoCompsets:
    def setup_method(self):
        with open("/app/query_results.json") as f:
            self.results = json.load(f)
        self.compsets = _parse_compsets_ref("/app/config_compsets.xml")

    def test_correct_list(self):
        expected = sorted(
            alias for alias, lname in self.compsets.items() if "MPASSI%DIB" in lname
        )
        assert self.results["cryo_compsets"] == expected

    def test_contains_cryo1850(self):
        assert "CRYO1850" in self.results["cryo_compsets"]

    def test_contains_cryo_dismf(self):
        assert "CRYO1850-DISMF" in self.results["cryo_compsets"]

    def test_not_contains_wcycl(self):
        assert "WCYCL1850" not in self.results["cryo_compsets"]

    def test_sorted(self):
        lst = self.results["cryo_compsets"]
        assert lst == sorted(lst)
