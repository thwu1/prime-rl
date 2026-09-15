
import subprocess
import json
import re
import os
import pytest

EXPANSION_SPEC = {
    "new_junctions": [
        {"id": "41", "elevation_ft": 720, "demand_gpm": 100, "pattern": "1"},
        {"id": "42", "elevation_ft": 730, "demand_gpm": 100, "pattern": "1"},
        {"id": "43", "elevation_ft": 715, "demand_gpm": 120, "pattern": "1"},
        {"id": "44", "elevation_ft": 735, "demand_gpm": 80, "pattern": "1"},
    ],
    "new_pipes": [
        {"id": "201", "from": "31", "to": "41", "length_ft": 4000, "roughness": 130},
        {"id": "202", "from": "41", "to": "42", "length_ft": 3000, "roughness": 130},
        {"id": "203", "from": "32", "to": "43", "length_ft": 3500, "roughness": 130},
        {"id": "204", "from": "43", "to": "44", "length_ft": 2500, "roughness": 130},
    ],
    "constraints": {
        "min_pressure_psi": 20.0,
        "max_budget_usd": 500000,
    },
}

PIPE_CATALOG_COSTS = {
    "4": 8, "6": 14, "8": 22, "10": 32, "12": 45,
    "14": 62, "16": 82, "18": 105, "20": 132,
}

VALID_DIAMETERS = {4, 6, 8, 10, 12, 14, 16, 18, 20}

ORIGINAL_JUNCTIONS = ["10", "11", "12", "13", "21", "22", "23", "31", "32"]
ORIGINAL_PIPES = ["10", "11", "12", "21", "22", "31", "110", "111", "112", "113", "121", "122"]


def parse_inp_sections(inp_path):
    """Parse an EPANET .inp file into a dict of {section_name: [lines]}."""
    with open(inp_path) as f:
        content = f.read()
    sections = {}
    current_section = None
    current_lines = []
    for line in content.split("\n"):
        m = re.match(r"\[(\w+)\]", line.strip())
        if m:
            if current_section:
                sections[current_section] = current_lines
            current_section = m.group(1).upper()
            current_lines = []
        elif current_section:
            current_lines.append(line)
    if current_section:
        sections[current_section] = current_lines
    return sections


def parse_junctions(sections):
    """Return {junction_id: {elevation, demand, pattern}}."""
    junctions = {}
    for line in sections.get("JUNCTIONS", []):
        line = line.split(";")[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 3:
            try:
                junctions[parts[0]] = {
                    "elevation": float(parts[1]),
                    "demand": float(parts[2]),
                    "pattern": parts[3] if len(parts) > 3 else "",
                }
            except ValueError:
                continue
    return junctions


def parse_pipes(sections):
    """Return {pipe_id: {node1, node2, length, diameter, roughness}}."""
    pipes = {}
    for line in sections.get("PIPES", []):
        line = line.split(";")[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 6:
            try:
                pipes[parts[0]] = {
                    "node1": parts[1],
                    "node2": parts[2],
                    "length": float(parts[3]),
                    "diameter": float(parts[4]),
                    "roughness": float(parts[5]),
                }
            except ValueError:
                continue
    return pipes


def ensure_report_all_nodes(inp_path, out_path):
    """Rewrite the REPORT section so EPANET outputs all node results."""
    with open(inp_path) as f:
        content = f.read()
    new_report = (
        "[REPORT]\n"
        " Status             No\n"
        " Summary            No\n"
        " Page               0\n"
        " NODES              ALL\n\n"
    )
    content = re.sub(
        r"\[REPORT\].*?(?=\[|\Z)", new_report, content, flags=re.DOTALL | re.IGNORECASE
    )
    with open(out_path, "w") as f:
        f.write(content)


def run_epanet(inp_path, rpt_path):
    """Run EPANET; return exit code."""
    r = subprocess.run(
        ["/usr/local/bin/runepanet", inp_path, rpt_path],
        capture_output=True, text=True, timeout=120,
    )
    return r.returncode


def parse_node_pressures(rpt_path):
    """Parse node pressures from an EPANET .rpt file.

    Returns {timestep_str: {node_id: pressure_psi}}.
    """
    with open(rpt_path) as f:
        content = f.read()

    results = {}
    # Each node-results block starts with "Node Results" and ends before the
    # next "Link Results" or another "Node Results" or EOF.
    blocks = re.split(r"(?=Node Results)", content)

    for block in blocks:
        if "Node Results" not in block:
            continue
        lines = block.split("\n")

        # Timestep
        tm = re.search(r"at\s+(\d+:\d+)", lines[0])
        timestep = tm.group(1) if tm else "0:00"

        # Locate the header line containing "Pressure" to find column index
        pressure_col_idx = None
        for line in lines:
            if "Pressure" in line and "Node" not in line.split()[0:1]:
                header_fields = line.split()
                for k, fld in enumerate(header_fields):
                    if fld == "Pressure":
                        pressure_col_idx = k
                        break
                break

        if pressure_col_idx is None:
            continue

        # Walk past the second separator line and read data rows
        sep_count = 0
        reading = False
        node_data = {}
        for line in lines:
            if "----" in line:
                sep_count += 1
                if sep_count >= 2:
                    reading = True
                continue
            if reading:
                stripped = line.strip()
                if not stripped:
                    break
                parts = stripped.split()
                # Data index = pressure_col_idx + 1 (because parts[0] is node id)
                if len(parts) >= pressure_col_idx + 2:
                    node_id = parts[0]
                    try:
                        pressure = float(parts[pressure_col_idx + 1])
                        node_data[node_id] = pressure
                    except ValueError:
                        continue
        results[timestep] = node_data

    return results


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def expanded_sections():
    return parse_inp_sections("/app/expanded_network.inp")


@pytest.fixture(scope="module")
def expanded_junctions(expanded_sections):
    return parse_junctions(expanded_sections)


@pytest.fixture(scope="module")
def expanded_pipes(expanded_sections):
    return parse_pipes(expanded_sections)


@pytest.fixture(scope="module")
def simulation_pressures():
    """Run EPANET on the expanded network and return pressures."""
    inp = "/tmp/verify_expanded.inp"
    rpt = "/tmp/verify_expanded.rpt"
    ensure_report_all_nodes("/app/expanded_network.inp", inp)
    ret = run_epanet(inp, rpt)
    assert ret < 100, f"EPANET failed with error code {ret}"
    return parse_node_pressures(rpt)


@pytest.fixture(scope="module")
def analysis():
    with open("/app/analysis.json") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestFilesExist:
    def test_expanded_network_exists(self):
        assert os.path.isfile("/app/expanded_network.inp"), \
            "/app/expanded_network.inp not found"

    def test_analysis_json_exists(self):
        assert os.path.isfile("/app/analysis.json"), \
            "/app/analysis.json not found"


class TestNetworkStructure:
    """Verify that the expanded .inp contains the correct topology."""

    def test_original_junctions_preserved(self, expanded_junctions):
        for jid in ORIGINAL_JUNCTIONS:
            assert jid in expanded_junctions, \
                f"Original junction {jid} missing"

    def test_original_pipes_preserved(self, expanded_pipes):
        for pid in ORIGINAL_PIPES:
            assert pid in expanded_pipes, \
                f"Original pipe {pid} missing"

    def test_new_junctions_present(self, expanded_junctions):
        for jspec in EXPANSION_SPEC["new_junctions"]:
            jid = jspec["id"]
            assert jid in expanded_junctions, \
                f"New junction {jid} missing"
            j = expanded_junctions[jid]
            assert abs(j["elevation"] - jspec["elevation_ft"]) < 1.0, \
                f"Junction {jid} elevation {j['elevation']} != {jspec['elevation_ft']}"
            assert abs(j["demand"] - jspec["demand_gpm"]) < 1.0, \
                f"Junction {jid} demand {j['demand']} != {jspec['demand_gpm']}"

    def test_new_pipes_present(self, expanded_pipes):
        for pspec in EXPANSION_SPEC["new_pipes"]:
            pid = pspec["id"]
            assert pid in expanded_pipes, \
                f"New pipe {pid} missing"
            p = expanded_pipes[pid]
            nodes = {p["node1"], p["node2"]}
            expected = {pspec["from"], pspec["to"]}
            assert nodes == expected, \
                f"Pipe {pid} connects {nodes}, expected {expected}"
            assert abs(p["length"] - pspec["length_ft"]) < 1.0, \
                f"Pipe {pid} length {p['length']} != {pspec['length_ft']}"
            assert abs(p["roughness"] - pspec["roughness"]) < 1.0, \
                f"Pipe {pid} roughness {p['roughness']} != {pspec['roughness']}"

    def test_pipe_diameters_from_catalog(self, expanded_pipes):
        for pspec in EXPANSION_SPEC["new_pipes"]:
            pid = pspec["id"]
            diam = expanded_pipes[pid]["diameter"]
            assert diam in VALID_DIAMETERS, \
                f"Pipe {pid} diameter {diam} not in catalog"


class TestCostConstraint:
    def test_cost_within_budget(self, expanded_pipes):
        total = 0
        for pspec in EXPANSION_SPEC["new_pipes"]:
            pid = pspec["id"]
            diam = int(expanded_pipes[pid]["diameter"])
            length = expanded_pipes[pid]["length"]
            total += PIPE_CATALOG_COSTS[str(diam)] * length
        budget = EXPANSION_SPEC["constraints"]["max_budget_usd"]
        assert total <= budget, \
            f"Total cost ${total:,.0f} exceeds budget ${budget:,.0f}"


class TestHydraulicFeasibility:
    """Run EPANET on the expanded network and check pressure constraints."""

    def test_epanet_runs(self, simulation_pressures):
        assert len(simulation_pressures) > 0, "No results parsed from EPANET report"

    def test_all_pressures_above_minimum(self, simulation_pressures, expanded_junctions):
        min_p = EXPANSION_SPEC["constraints"]["min_pressure_psi"]
        junction_ids = set(expanded_junctions.keys())
        violations = []
        for ts, node_ps in simulation_pressures.items():
            for nid, pressure in node_ps.items():
                if nid in junction_ids and pressure < min_p:
                    violations.append((ts, nid, pressure))
        assert not violations, \
            "Pressure violations: " + "; ".join(
                f"node {v[1]} at {v[0]} hrs = {v[2]:.2f} psi" for v in violations[:10]
            )

    def test_no_negative_pressures(self, simulation_pressures, expanded_junctions):
        junction_ids = set(expanded_junctions.keys())
        for ts, node_ps in simulation_pressures.items():
            for nid, pressure in node_ps.items():
                if nid in junction_ids:
                    assert pressure >= 0, \
                        f"Negative pressure at node {nid} ({ts} hrs): {pressure:.2f} psi"


class TestAnalysisJSON:
    REQUIRED_KEYS = [
        "baseline_min_pressure_psi",
        "baseline_min_pressure_node",
        "expanded_min_pressure_psi",
        "expanded_min_pressure_node",
        "pipe_diameters",
        "total_cost_usd",
        "critical_timestep_hr",
    ]

    def test_required_fields(self, analysis):
        for key in self.REQUIRED_KEYS:
            assert key in analysis, f"Missing key '{key}' in analysis.json"

    def test_pipe_diameters_complete(self, analysis):
        for pspec in EXPANSION_SPEC["new_pipes"]:
            pid = pspec["id"]
            assert pid in analysis["pipe_diameters"], \
                f"Pipe {pid} missing from pipe_diameters"
            diam = analysis["pipe_diameters"][pid]
            assert diam in VALID_DIAMETERS, \
                f"Pipe {pid} diameter {diam} not in catalog"

    def test_cost_positive_and_within_budget(self, analysis):
        budget = EXPANSION_SPEC["constraints"]["max_budget_usd"]
        assert 0 < analysis["total_cost_usd"] <= budget

    def test_expanded_pressure_meets_constraint(self, analysis):
        min_p = EXPANSION_SPEC["constraints"]["min_pressure_psi"]
        assert analysis["expanded_min_pressure_psi"] >= min_p, \
            f"Reported expanded min pressure {analysis['expanded_min_pressure_psi']} < {min_p}"

    def test_cost_matches_network(self, analysis, expanded_pipes):
        computed = 0
        for pspec in EXPANSION_SPEC["new_pipes"]:
            pid = pspec["id"]
            diam = int(expanded_pipes[pid]["diameter"])
            length = expanded_pipes[pid]["length"]
            computed += PIPE_CATALOG_COSTS[str(diam)] * length
        assert abs(analysis["total_cost_usd"] - computed) < 1.0, \
            f"analysis cost {analysis['total_cost_usd']} != computed {computed}"

    def test_expanded_pressure_matches_simulation(self, analysis, simulation_pressures, expanded_junctions):
        junction_ids = set(expanded_junctions.keys())
        actual_min = float("inf")
        for ts, node_ps in simulation_pressures.items():
            for nid, p in node_ps.items():
                if nid in junction_ids and p < actual_min:
                    actual_min = p
        assert abs(analysis["expanded_min_pressure_psi"] - actual_min) < 1.0, \
            f"Reported min pressure {analysis['expanded_min_pressure_psi']:.2f} " \
            f"vs simulation {actual_min:.2f}"
