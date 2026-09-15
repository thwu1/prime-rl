import json
import subprocess
import pytest
import yaml


TOOL = "/app/hydrofabric_tool.py"
HYDROFABRIC = "/app/hydrofabric.sql"
MODELS = "/app/models.json"


def run_tool(*args):
    """Run the hydrofabric tool and return the CompletedProcess."""
    result = subprocess.run(
        ["python3", TOOL] + list(args),
        capture_output=True, text=True, timeout=60
    )
    return result


# ---------------------------------------------------------------------------
# VALIDATE TESTS
# ---------------------------------------------------------------------------

class TestValidate:
    @pytest.fixture(autouse=True)
    def setup(self):
        r = run_tool("validate", HYDROFABRIC)
        assert r.returncode == 0, f"validate command failed: {r.stderr}"
        self.result = json.loads(r.stdout)

    def test_output_has_required_keys(self):
        assert "is_valid" in self.result
        assert "violations" in self.result

    def test_network_is_not_valid(self):
        assert self.result["is_valid"] is False

    def test_has_at_least_four_violations(self):
        assert len(self.result["violations"]) >= 4

    def test_dangling_reference_detected(self):
        violation_types = {v["type"] for v in self.result["violations"]}
        assert "dangling_reference" in violation_types
        dangling = [v for v in self.result["violations"]
                    if v["type"] == "dangling_reference"]
        feature_ids = set()
        for v in dangling:
            if "feature_id" in v:
                feature_ids.add(v["feature_id"])
            elif "feature_ids" in v:
                feature_ids.update(v["feature_ids"])
        assert "wb-1012" in feature_ids

    def test_orphan_nexus_detected(self):
        violation_types = {v["type"] for v in self.result["violations"]}
        assert "orphan_nexus" in violation_types
        orphans = [v for v in self.result["violations"]
                   if v["type"] == "orphan_nexus"]
        feature_ids = set()
        for v in orphans:
            if "feature_id" in v:
                feature_ids.add(v["feature_id"])
            elif "feature_ids" in v:
                feature_ids.update(v["feature_ids"])
        assert "nex-2009" in feature_ids

    def test_cycle_detected(self):
        violation_types = {v["type"] for v in self.result["violations"]}
        assert "cycle" in violation_types
        cycles = [v for v in self.result["violations"]
                  if v["type"] == "cycle"]
        cycle_nodes = set()
        for c in cycles:
            if "feature_ids" in c:
                cycle_nodes.update(c["feature_ids"])
            elif "feature_id" in c:
                cycle_nodes.add(c["feature_id"])
        # The cycle involves cat-1014, nex-2010, cat-1015, nex-2011
        expected = {"cat-1014", "nex-2010", "cat-1015", "nex-2011"}
        assert len(cycle_nodes & expected) >= 2, \
            f"Cycle nodes {cycle_nodes} should overlap with {expected}"

    def test_missing_divide_detected(self):
        violation_types = {v["type"] for v in self.result["violations"]}
        assert "missing_divide" in violation_types
        missing = [v for v in self.result["violations"]
                   if v["type"] == "missing_divide"]
        feature_ids = set()
        for v in missing:
            if "feature_id" in v:
                feature_ids.add(v["feature_id"])
            elif "feature_ids" in v:
                feature_ids.update(v["feature_ids"])
        assert "wb-1016" in feature_ids

    def test_violations_have_messages(self):
        for v in self.result["violations"]:
            assert "message" in v
            assert len(v["message"]) > 0


# ---------------------------------------------------------------------------
# DRAINAGE TESTS
# ---------------------------------------------------------------------------

class TestDrainage:
    @pytest.fixture(autouse=True)
    def setup(self):
        r = run_tool("drainage", HYDROFABRIC)
        assert r.returncode == 0, f"drainage command failed: {r.stderr}"
        self.result = json.loads(r.stdout)

    def test_returns_valid_flowpath_count(self):
        # 11 valid flowpaths should be present
        assert len(self.result) == 11

    def test_headwater_simple_areas(self):
        assert abs(self.result["wb-1001"] - 5.20) < 0.01
        assert abs(self.result["wb-1004"] - 6.70) < 0.01
        assert abs(self.result["wb-1007"] - 7.50) < 0.01
        assert abs(self.result["wb-1008"] - 11.20) < 0.01
        assert abs(self.result["wb-1010"] - 3.90) < 0.01

    def test_single_upstream_accumulation(self):
        # wb-1002: cat-1001(5.2) + cat-1002(8.4) = 13.6
        assert abs(self.result["wb-1002"] - 13.60) < 0.01
        # wb-1009: cat-1010(3.9) + cat-1009(4.6) = 8.5
        assert abs(self.result["wb-1009"] - 8.50) < 0.01

    def test_confluence_accumulation(self):
        # wb-1003: cat-1001(5.2) + cat-1002(8.4) + cat-1004(6.7) + cat-1003(12.1) = 32.4
        assert abs(self.result["wb-1003"] - 32.40) < 0.01
        # wb-1005: cat-1007(7.5) + cat-1008(11.2) + cat-1005(15.3) = 34.0
        assert abs(self.result["wb-1005"] - 34.00) < 0.01

    def test_deep_downstream_accumulation(self):
        # wb-1006: 32.4 + 34.0 + 9.8 = 76.2
        assert abs(self.result["wb-1006"] - 76.20) < 0.01
        # wb-1011: 76.2 + 8.5 + 6.3 = 91.0
        assert abs(self.result["wb-1011"] - 91.00) < 0.01

    def test_error_features_excluded(self):
        assert "wb-1012" not in self.result  # dangling reference
        assert "wb-1014" not in self.result  # cycle
        assert "wb-1015" not in self.result  # cycle
        assert "wb-1016" not in self.result  # missing divide


# ---------------------------------------------------------------------------
# SUBSET TESTS
# ---------------------------------------------------------------------------

class TestSubset:
    def test_subset_nex_2003(self):
        r = run_tool("subset", HYDROFABRIC, "nex-2003")
        assert r.returncode == 0, f"subset failed: {r.stderr}"
        result = json.loads(r.stdout)

        fl_ids = sorted([fl["id"] for fl in result["flowpaths"]])
        div_ids = sorted([d["divide_id"] for d in result["divides"]])
        nex_ids = sorted([n["id"] for n in result["nexuses"]])

        assert fl_ids == ["wb-1001", "wb-1002", "wb-1003",
                          "wb-1004", "wb-1005", "wb-1007", "wb-1008"]
        assert div_ids == ["cat-1001", "cat-1002", "cat-1003",
                           "cat-1004", "cat-1005", "cat-1007", "cat-1008"]
        assert nex_ids == ["nex-2001", "nex-2002", "nex-2003", "nex-2004"]

    def test_subset_nex_2006(self):
        r = run_tool("subset", HYDROFABRIC, "nex-2006")
        assert r.returncode == 0, f"subset failed: {r.stderr}"
        result = json.loads(r.stdout)

        fl_ids = sorted([fl["id"] for fl in result["flowpaths"]])
        div_ids = sorted([d["divide_id"] for d in result["divides"]])
        nex_ids = sorted([n["id"] for n in result["nexuses"]])

        assert fl_ids == ["wb-1001", "wb-1002", "wb-1003", "wb-1004",
                          "wb-1005", "wb-1006", "wb-1007", "wb-1008",
                          "wb-1009", "wb-1010"]
        assert div_ids == ["cat-1001", "cat-1002", "cat-1003", "cat-1004",
                           "cat-1005", "cat-1006", "cat-1007", "cat-1008",
                           "cat-1009", "cat-1010"]
        assert nex_ids == ["nex-2001", "nex-2002", "nex-2003",
                           "nex-2004", "nex-2005", "nex-2006"]

    def test_subset_headwater_nexus(self):
        r = run_tool("subset", HYDROFABRIC, "nex-2001")
        assert r.returncode == 0, f"subset failed: {r.stderr}"
        result = json.loads(r.stdout)

        fl_ids = sorted([fl["id"] for fl in result["flowpaths"]])
        div_ids = sorted([d["divide_id"] for d in result["divides"]])
        nex_ids = sorted([n["id"] for n in result["nexuses"]])

        assert fl_ids == ["wb-1001"]
        assert div_ids == ["cat-1001"]
        assert nex_ids == ["nex-2001"]

    def test_subset_terminal_nexus(self):
        """Subsetting from the terminal nexus should capture the entire valid network."""
        r = run_tool("subset", HYDROFABRIC, "nex-2007")
        assert r.returncode == 0, f"subset failed: {r.stderr}"
        result = json.loads(r.stdout)

        fl_ids = sorted([fl["id"] for fl in result["flowpaths"]])
        assert fl_ids == ["wb-1001", "wb-1002", "wb-1003", "wb-1004",
                          "wb-1005", "wb-1006", "wb-1007", "wb-1008",
                          "wb-1009", "wb-1010", "wb-1011"]

    def test_subset_invalid_nexus_exits_nonzero(self):
        r = run_tool("subset", HYDROFABRIC, "nex-9999")
        assert r.returncode != 0

    def test_subset_confluence_nexus(self):
        """nex-2004 receives from two headwaters."""
        r = run_tool("subset", HYDROFABRIC, "nex-2004")
        assert r.returncode == 0, f"subset failed: {r.stderr}"
        result = json.loads(r.stdout)

        fl_ids = sorted([fl["id"] for fl in result["flowpaths"]])
        assert fl_ids == ["wb-1007", "wb-1008"]
        nex_ids = sorted([n["id"] for n in result["nexuses"]])
        assert nex_ids == ["nex-2004"]


# ---------------------------------------------------------------------------
# REALIZE TESTS
# ---------------------------------------------------------------------------

class TestRealize:
    @pytest.fixture(autouse=True)
    def setup(self):
        r = run_tool("realize", HYDROFABRIC, "nex-2003",
                      "--model-config", MODELS)
        assert r.returncode == 0, f"realize failed: {r.stderr}"
        self.result = json.loads(r.stdout)

    def test_has_required_top_level_keys(self):
        assert "global" in self.result
        assert "time" in self.result
        assert "catchments" in self.result

    def test_time_section_correct(self):
        t = self.result["time"]
        assert t["start_time"] == "2020-01-01 00:00:00"
        assert t["end_time"] == "2020-12-31 23:00:00"
        assert t["output_interval"] == 3600

    def test_global_has_bmi_multi_formulation(self):
        g = self.result["global"]
        assert "formulations" in g
        assert len(g["formulations"]) >= 1
        form = g["formulations"][0]
        assert form["name"] == "bmi_multi"

    def test_global_has_three_modules(self):
        form = self.result["global"]["formulations"][0]
        modules = form["params"]["modules"]
        assert len(modules) == 3

    def test_global_module_order(self):
        """Modules must be SLOTH, NoahOWP, CFE in that order."""
        modules = self.result["global"]["formulations"][0]["params"]["modules"]
        assert modules[0]["name"] == "bmi_c++"
        assert modules[1]["name"] == "bmi_fortran"
        assert modules[2]["name"] == "bmi_c"

    def test_global_retains_template_placeholders(self):
        modules = self.result["global"]["formulations"][0]["params"]["modules"]
        template_found = False
        for mod in modules:
            ic = mod["params"].get("init_config", "")
            if "{{id}}" in ic:
                template_found = True
        assert template_found, "Global formulation should retain {{id}} placeholders"

    def test_global_main_output_variable(self):
        form = self.result["global"]["formulations"][0]
        assert form["params"]["main_output_variable"] == "Q_OUT"

    def test_global_forcing_present(self):
        g = self.result["global"]
        assert "forcing" in g
        assert g["forcing"]["provider"] == "CsvPerFeature"

    def test_catchment_count(self):
        # Subset above nex-2003 has 7 catchments
        assert len(self.result["catchments"]) == 7

    def test_catchment_ids_match_subset(self):
        expected = {"cat-1001", "cat-1002", "cat-1003", "cat-1004",
                    "cat-1005", "cat-1007", "cat-1008"}
        assert set(self.result["catchments"].keys()) == expected

    def test_per_catchment_has_formulations(self):
        for cat_id, cat_config in self.result["catchments"].items():
            assert "formulations" in cat_config, \
                f"{cat_id} missing formulations"
            assert len(cat_config["formulations"]) >= 1

    def test_per_catchment_substitutes_template_ids(self):
        for cat_id, cat_config in self.result["catchments"].items():
            form = cat_config["formulations"][0]
            for mod in form["params"]["modules"]:
                ic = mod["params"].get("init_config", "")
                if ic and ic != "/dev/null":
                    assert "{{id}}" not in ic, \
                        f"{cat_id} still has {{{{id}}}} in init_config: {ic}"
                    assert cat_id in ic, \
                        f"{cat_id} not found in init_config: {ic}"

    def test_noahowp_variable_names_map(self):
        modules = self.result["global"]["formulations"][0]["params"]["modules"]
        noahowp = modules[1]
        vnm = noahowp["params"]["variables_names_map"]
        assert "PRCPNONC" in vnm
        assert vnm["PRCPNONC"] == \
            "atmosphere_water__liquid_equivalent_precipitation_rate"

    def test_cfe_registration_function(self):
        modules = self.result["global"]["formulations"][0]["params"]["modules"]
        cfe = modules[2]
        assert cfe["params"]["registration_function"] == "register_bmi_cfe"

    def test_sloth_model_params(self):
        modules = self.result["global"]["formulations"][0]["params"]["modules"]
        sloth = modules[0]
        mp = sloth["params"]["model_params"]
        assert "sloth_ice_fraction_schaake(1,double,m,node)" in mp
        assert mp["sloth_ice_fraction_schaake(1,double,m,node)"] == 0.0

    def test_per_catchment_init_configs_are_distinct(self):
        """Each catchment should have unique init_config paths."""
        configs = set()
        for cat_id, cat_config in self.result["catchments"].items():
            form = cat_config["formulations"][0]
            for mod in form["params"]["modules"]:
                ic = mod["params"].get("init_config", "")
                if ic and ic != "/dev/null":
                    configs.add(ic)
        # 7 catchments x 2 non-null init_configs (noahowp + cfe) = 14 unique paths
        assert len(configs) == 14


class TestRealizeInvalidNexus:
    def test_realize_invalid_nexus_exits_nonzero(self):
        r = run_tool("realize", HYDROFABRIC, "nex-9999",
                      "--model-config", MODELS)
        assert r.returncode != 0


# ---------------------------------------------------------------------------
# ROUTE CONFIG TESTS
# ---------------------------------------------------------------------------

class TestRouteConfig:
    def _run_route_config(self, nexus_id):
        return run_tool("route-config", HYDROFABRIC, nexus_id)

    def test_route_config_parses_as_yaml(self):
        r = self._run_route_config("nex-2003")
        assert r.returncode == 0, f"route-config failed: {r.stderr}"
        result = yaml.safe_load(r.stdout)
        assert isinstance(result, dict)

    def test_route_config_top_level_structure(self):
        r = self._run_route_config("nex-2003")
        result = yaml.safe_load(r.stdout)
        assert "supernetwork_parameters" in result
        assert "segments" in result
        assert "compute_parameters" in result
        assert "output_parameters" in result

    def test_supernetwork_parameters(self):
        r = self._run_route_config("nex-2003")
        result = yaml.safe_load(r.stdout)
        sp = result["supernetwork_parameters"]
        assert sp["title"] == "Upstream network of nex-2003"
        assert sp["geo_file_type"] == "HYFeaturesNetwork"
        assert sp["terminal_nexus"] == "nex-2003"
        cols = sp["columns"]
        assert cols["key"] == "id"
        assert cols["downstream"] == "toid"
        assert cols["dx"] == "length_m"
        assert cols["n"] == "n"
        assert cols["s0"] == "So"
        assert cols["bw"] == "BtmWdth"
        assert cols["tw"] == "TopWdth"
        assert cols["musk"] == "MusK"
        assert cols["musx"] == "MusX"

    def test_nex_2003_segment_count(self):
        r = self._run_route_config("nex-2003")
        result = yaml.safe_load(r.stdout)
        assert len(result["segments"]) == 7

    def test_nex_2003_segment_ordering(self):
        """Segments must be ordered by hydroseq descending (upstream first)."""
        r = self._run_route_config("nex-2003")
        result = yaml.safe_load(r.stdout)
        ids = [s["id"] for s in result["segments"]]
        assert ids == ["wb-1007", "wb-1008", "wb-1001", "wb-1004",
                       "wb-1002", "wb-1005", "wb-1003"]

    def test_nex_2003_downstream_resolution(self):
        """Downstream must resolve through bipartite nexus-catchment-flowpath topology."""
        r = self._run_route_config("nex-2003")
        result = yaml.safe_load(r.stdout)
        ds = {s["id"]: s["downstream"] for s in result["segments"]}
        assert ds["wb-1007"] == "wb-1005"
        assert ds["wb-1008"] == "wb-1005"
        assert ds["wb-1001"] == "wb-1002"
        assert ds["wb-1004"] == "wb-1003"
        assert ds["wb-1002"] == "wb-1003"
        # Segments draining to the terminal nexus have empty downstream
        assert ds["wb-1005"] == ""
        assert ds["wb-1003"] == ""

    def test_nex_2003_flowpath_attribute_values(self):
        """Flowpath attributes must be correctly joined from SQLite."""
        r = self._run_route_config("nex-2003")
        result = yaml.safe_load(r.stdout)
        seg_by_id = {s["id"]: s for s in result["segments"]}

        # wb-1007: headwater stream
        s = seg_by_id["wb-1007"]
        assert abs(s["length_m"] - 4200.0) < 0.1
        assert abs(s["n"] - 0.062) < 0.001
        assert abs(s["So"] - 0.0015) < 0.0001
        assert abs(s["BtmWdth"] - 3.0) < 0.1
        assert abs(s["TopWdth"] - 6.0) < 0.1
        assert abs(s["MusK"] - 3600.0) < 0.1
        assert abs(s["MusX"] - 0.20) < 0.01
        assert abs(s["ChSlp"] - 0.035) < 0.001

        # wb-1003: larger main-stem channel
        s = seg_by_id["wb-1003"]
        assert abs(s["length_m"] - 6200.0) < 0.1
        assert abs(s["n"] - 0.045) < 0.001
        assert abs(s["So"] - 0.0006) < 0.0001
        assert abs(s["BtmWdth"] - 8.0) < 0.1
        assert abs(s["TopWdth"] - 15.0) < 0.1
        assert abs(s["MusK"] - 7200.0) < 0.1
        assert abs(s["MusX"] - 0.15) < 0.01

    def test_compute_parameters(self):
        r = self._run_route_config("nex-2003")
        result = yaml.safe_load(r.stdout)
        cp = result["compute_parameters"]
        assert cp["parallel_compute_method"] == "serial"
        assert cp["compute_kernel"] == "V02-structured"
        assert cp["assume_short_ts"] is True
        assert cp["subnetwork_target_size"] == 10000

    def test_output_parameters(self):
        r = self._run_route_config("nex-2003")
        result = yaml.safe_load(r.stdout)
        op = result["output_parameters"]
        assert op["stream_output_directory"] == "/app/output/"
        assert op["stream_output_time"] == 1
        assert op["stream_output_type"] == ".nc"

    def test_nex_2004_headwater_subset(self):
        """Confluence nexus with two headwater inputs."""
        r = self._run_route_config("nex-2004")
        assert r.returncode == 0
        result = yaml.safe_load(r.stdout)
        assert len(result["segments"]) == 2
        ids = [s["id"] for s in result["segments"]]
        assert ids == ["wb-1007", "wb-1008"]
        # Both drain directly to the terminal nexus
        for s in result["segments"]:
            assert s["downstream"] == ""

    def test_nex_2007_full_network(self):
        """Full network routing with 11 segments."""
        r = self._run_route_config("nex-2007")
        assert r.returncode == 0
        result = yaml.safe_load(r.stdout)
        assert len(result["segments"]) == 11
        ids = [s["id"] for s in result["segments"]]
        assert ids == ["wb-1010", "wb-1007", "wb-1008", "wb-1001",
                       "wb-1004", "wb-1002", "wb-1009", "wb-1005",
                       "wb-1003", "wb-1006", "wb-1011"]
        ds = {s["id"]: s["downstream"] for s in result["segments"]}
        assert ds["wb-1011"] == ""
        assert ds["wb-1006"] == "wb-1011"
        assert ds["wb-1009"] == "wb-1011"
        assert ds["wb-1003"] == "wb-1006"
        assert ds["wb-1005"] == "wb-1006"
        assert ds["wb-1010"] == "wb-1009"
        assert ds["wb-1007"] == "wb-1005"
        assert ds["wb-1008"] == "wb-1005"
        assert ds["wb-1001"] == "wb-1002"
        assert ds["wb-1004"] == "wb-1003"
        assert ds["wb-1002"] == "wb-1003"

    def test_route_config_invalid_nexus_exits_nonzero(self):
        r = self._run_route_config("nex-9999")
        assert r.returncode != 0

    def test_segments_have_all_attribute_fields(self):
        """Each segment must carry all flowpath_attributes columns."""
        r = self._run_route_config("nex-2003")
        result = yaml.safe_load(r.stdout)
        required = {"id", "downstream", "length_m", "n", "So", "BtmWdth",
                     "TopWdth", "TopWdthCC", "nCC", "MusK", "MusX",
                     "ChSlp", "Qi", "Kchan", "hydroseq"}
        for s in result["segments"]:
            assert required.issubset(set(s.keys())), \
                f"Missing keys in segment {s['id']}: {required - set(s.keys())}"

    def test_nex_2007_muskingum_variation(self):
        """Downstream channels should have higher Muskingum K."""
        r = self._run_route_config("nex-2007")
        result = yaml.safe_load(r.stdout)
        seg_by_id = {s["id"]: s for s in result["segments"]}
        # Headwater wb-1001 has MusK=3600, outlet wb-1011 has MusK=14400
        assert seg_by_id["wb-1001"]["MusK"] < seg_by_id["wb-1011"]["MusK"]
        assert abs(seg_by_id["wb-1011"]["MusK"] - 14400.0) < 0.1


# ---------------------------------------------------------------------------
# GRAPH TESTS
# ---------------------------------------------------------------------------

class TestGraph:
    def test_graph_outputs_valid_dot(self):
        """Graph subcommand must produce valid DOT syntax."""
        r = run_tool("graph", HYDROFABRIC, "nex-2003", "--format", "dot")
        assert r.returncode == 0, f"graph failed: {r.stderr}"
        output = r.stdout.strip()
        assert output.startswith("digraph"), "Output must start with 'digraph'"
        assert output.endswith("}"), "Output must end with '}'"

    def test_graph_renders_with_graphviz(self):
        """DOT output must successfully render with the dot command."""
        r = run_tool("graph", HYDROFABRIC, "nex-2003", "--format", "dot")
        assert r.returncode == 0
        result = subprocess.run(
            ["dot", "-Tsvg"],
            input=r.stdout, capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, \
            f"dot rendering failed: {result.stderr}"
        assert len(result.stdout) > 100, "SVG output too small"

    def test_graph_flowpath_node_count_nex_2003(self):
        """Upstream of nex-2003 has 7 flowpath nodes."""
        r = run_tool("graph", HYDROFABRIC, "nex-2003", "--format", "dot")
        assert r.returncode == 0
        assert r.stdout.count("shape=box") == 7

    def test_graph_nexus_node_count_nex_2003(self):
        """Upstream of nex-2003 has 4 nexus nodes."""
        r = run_tool("graph", HYDROFABRIC, "nex-2003", "--format", "dot")
        assert r.returncode == 0
        assert r.stdout.count("shape=diamond") == 4

    def test_graph_terminal_nexus_bold(self):
        """The pour-point nexus must have style=bold."""
        r = run_tool("graph", HYDROFABRIC, "nex-2003", "--format", "dot")
        assert r.returncode == 0
        # Find nex-2003 node definition and verify bold styling
        found_bold = False
        for line in r.stdout.split("\n"):
            if '"nex-2003"' in line and "shape=" in line:
                assert "style=bold" in line, \
                    f"Terminal nexus nex-2003 must have style=bold: {line}"
                found_bold = True
                break
        assert found_bold, "nex-2003 node definition with shape attribute not found"

    def test_graph_flowpath_to_nexus_edges(self):
        """Flowpaths must have directed edges to their downstream nexus."""
        r = run_tool("graph", HYDROFABRIC, "nex-2003", "--format", "dot")
        assert r.returncode == 0
        assert '"wb-1001" -> "nex-2001"' in r.stdout
        assert '"wb-1002" -> "nex-2002"' in r.stdout
        assert '"wb-1003" -> "nex-2003"' in r.stdout
        assert '"wb-1004" -> "nex-2002"' in r.stdout
        assert '"wb-1005" -> "nex-2003"' in r.stdout
        assert '"wb-1007" -> "nex-2004"' in r.stdout
        assert '"wb-1008" -> "nex-2004"' in r.stdout

    def test_graph_nexus_to_flowpath_edges(self):
        """Nexuses must have directed edges to their downstream flowpath."""
        r = run_tool("graph", HYDROFABRIC, "nex-2003", "--format", "dot")
        assert r.returncode == 0
        assert '"nex-2001" -> "wb-1002"' in r.stdout
        assert '"nex-2002" -> "wb-1003"' in r.stdout
        assert '"nex-2004" -> "wb-1005"' in r.stdout

    def test_graph_terminal_has_no_downstream_edge(self):
        """Terminal nexus should not have an outgoing edge to a flowpath."""
        r = run_tool("graph", HYDROFABRIC, "nex-2003", "--format", "dot")
        assert r.returncode == 0
        # nex-2003 drains to cat-1006/wb-1006 which is NOT in this subset
        for line in r.stdout.split("\n"):
            if '"nex-2003" ->' in line:
                assert False, \
                    f"Terminal nexus nex-2003 should not have downstream edge: {line}"

    def test_graph_full_network(self):
        """Full network graph with 11 flowpaths and 7 nexuses."""
        r = run_tool("graph", HYDROFABRIC, "nex-2007", "--format", "dot")
        assert r.returncode == 0
        assert r.stdout.count("shape=box") == 11
        assert r.stdout.count("shape=diamond") == 7
        # Verify rendering
        result = subprocess.run(
            ["dot", "-Tsvg"],
            input=r.stdout, capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0

    def test_graph_invalid_nexus_exits_nonzero(self):
        r = run_tool("graph", HYDROFABRIC, "nex-9999", "--format", "dot")
        assert r.returncode != 0

    def test_graph_headwater_nexus(self):
        """Single flowpath + single nexus for headwater."""
        r = run_tool("graph", HYDROFABRIC, "nex-2001", "--format", "dot")
        assert r.returncode == 0
        assert r.stdout.count("shape=box") == 1
        assert r.stdout.count("shape=diamond") == 1
        assert '"wb-1001" -> "nex-2001"' in r.stdout
