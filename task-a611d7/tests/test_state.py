
import json
import os
import re
import pytest
import networkx as nx

MONOREPO_DIR = "/app/monorepo"
REPORT_PATH = "/app/audit_report.json"
SVG_PATH = "/app/dep_graph.svg"


def parse_build_files():
    """Parse all BUILD files and return declared dependency dict.

    Handles both standard py_library BUILD files (with "//name" labels)
    and py_service macro BUILD files (with bare "name" in service_deps
    and "//name" in internal_deps).
    """
    # Discover all packages (dirs with BUILD files)
    all_packages = set()
    for entry in sorted(os.listdir(MONOREPO_DIR)):
        pkg_dir = os.path.join(MONOREPO_DIR, entry)
        if os.path.isdir(pkg_dir) and os.path.isfile(
            os.path.join(pkg_dir, "BUILD")
        ):
            all_packages.add(entry)

    graph = {}
    for pkg in sorted(all_packages):
        pkg_dir = os.path.join(MONOREPO_DIR, pkg)
        build_path = os.path.join(pkg_dir, "BUILD")
        with open(build_path) as f:
            content = f.read()

        deps = set()

        # Match standard "//name" label deps (from deps= or internal_deps=)
        for m in re.finditer(r'"//(\w+)"', content):
            dep = m.group(1)
            if dep in all_packages:
                deps.add(dep)

        # Handle py_service macro: extract bare names from service_deps
        if "py_service(" in content:
            svc_match = re.search(
                r"service_deps\s*=\s*\[(.*?)\]", content, re.DOTALL
            )
            if svc_match:
                for m in re.finditer(r'"(\w+)"', svc_match.group(1)):
                    dep = m.group(1)
                    if dep in all_packages:
                        deps.add(dep)

        graph[pkg] = sorted(deps)
    return graph


def parse_source_imports():
    """Parse Python source files and return actual import dict.

    Handles both top-level and indented imports (e.g. inside try/except).
    """
    # Use same package set as BUILD parser
    packages = set()
    for entry in os.listdir(MONOREPO_DIR):
        pkg_dir = os.path.join(MONOREPO_DIR, entry)
        if os.path.isdir(pkg_dir) and os.path.isfile(
            os.path.join(pkg_dir, "BUILD")
        ):
            packages.add(entry)

    graph = {}
    for pkg in sorted(packages):
        module_path = os.path.join(MONOREPO_DIR, pkg, "module.py")
        if not os.path.isfile(module_path):
            graph[pkg] = []
            continue

        with open(module_path) as f:
            content = f.read()

        imports = set()
        # No ^ anchor - matches indented imports too
        for match in re.finditer(
            r"(?:from|import)\s+monorepo\.(\w+)", content
        ):
            dep = match.group(1)
            if dep in packages and dep != pkg:
                imports.add(dep)

        graph[pkg] = sorted(imports)

    return graph


def load_report():
    assert os.path.isfile(REPORT_PATH), (
        f"Report file not found at {REPORT_PATH}"
    )
    with open(REPORT_PATH) as f:
        return json.load(f)


def build_declared_digraph(declared):
    G = nx.DiGraph()
    for pkg in declared:
        G.add_node(pkg)
    for pkg, deps in declared.items():
        for dep in deps:
            G.add_edge(pkg, dep)
    return G


def build_condensed_dag(G):
    """Build condensed DAG from a directed graph with possible cycles."""
    scc_labels = {}
    for scc in nx.strongly_connected_components(G):
        label = "|".join(sorted(scc))
        for node in scc:
            scc_labels[node] = label

    condensed = nx.DiGraph()
    for node in G.nodes():
        condensed.add_node(scc_labels[node])
    for u, v in G.edges():
        src = scc_labels[u]
        dst = scc_labels[v]
        if src != dst:
            condensed.add_edge(src, dst)

    return condensed, scc_labels


class TestReportExists:
    def test_report_file_exists(self):
        assert os.path.isfile(REPORT_PATH), (
            f"Report file not found at {REPORT_PATH}"
        )

    def test_report_is_valid_json(self):
        with open(REPORT_PATH) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_report_has_all_keys(self):
        report = load_report()
        expected_keys = {
            "node_count",
            "declared_edge_count",
            "actual_edge_count",
            "cycles",
            "stale_deps",
            "missing_deps",
            "articulation_points",
            "bridges",
            "build_schedule",
            "critical_path_length",
            "transitive_reduction_removed",
        }
        missing = expected_keys - set(report.keys())
        assert not missing, f"Missing report keys: {missing}"


class TestGraphCounts:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.report = load_report()
        self.declared = parse_build_files()
        self.actual = parse_source_imports()

    def test_node_count(self):
        expected = len(self.declared)
        assert self.report["node_count"] == expected, (
            f"Expected {expected} nodes, got {self.report['node_count']}"
        )

    def test_declared_edge_count(self):
        expected = sum(len(deps) for deps in self.declared.values())
        assert self.report["declared_edge_count"] == expected, (
            f"Expected {expected} declared edges, got "
            f"{self.report['declared_edge_count']}"
        )

    def test_actual_edge_count(self):
        expected = sum(len(deps) for deps in self.actual.values())
        assert self.report["actual_edge_count"] == expected, (
            f"Expected {expected} actual edges, got "
            f"{self.report['actual_edge_count']}"
        )


class TestCycleDetection:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.report = load_report()
        self.declared = parse_build_files()

    def test_cycles(self):
        G = build_declared_digraph(self.declared)
        expected_sccs = []
        for scc in nx.strongly_connected_components(G):
            if len(scc) > 1:
                expected_sccs.append(sorted(scc))
        expected_sccs.sort()

        reported = [sorted(c) for c in self.report["cycles"]]
        reported.sort()

        assert reported == expected_sccs, (
            f"Expected cycles {expected_sccs}, got {reported}"
        )


class TestDependencyDiscrepancies:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.report = load_report()
        self.declared = parse_build_files()
        self.actual = parse_source_imports()

    def test_stale_deps(self):
        expected = set()
        for pkg in self.declared:
            for dep in self.declared[pkg]:
                if dep not in self.actual.get(pkg, []):
                    expected.add((pkg, dep))

        reported = set(tuple(x) for x in self.report["stale_deps"])
        assert reported == expected, (
            f"Stale deps mismatch.\n"
            f"Expected: {sorted(expected)}\n"
            f"Got: {sorted(reported)}"
        )

    def test_missing_deps(self):
        expected = set()
        for pkg in self.actual:
            for dep in self.actual[pkg]:
                if dep not in self.declared.get(pkg, []):
                    expected.add((pkg, dep))

        reported = set(tuple(x) for x in self.report["missing_deps"])
        assert reported == expected, (
            f"Missing deps mismatch.\n"
            f"Expected: {sorted(expected)}\n"
            f"Got: {sorted(reported)}"
        )


class TestGraphStructure:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.report = load_report()
        self.declared = parse_build_files()
        self.G = build_declared_digraph(self.declared)

    def test_articulation_points(self):
        G_undirected = self.G.to_undirected()
        expected = sorted(nx.articulation_points(G_undirected))
        reported = sorted(self.report["articulation_points"])
        assert reported == expected, (
            f"Articulation points mismatch.\n"
            f"Expected: {expected}\n"
            f"Got: {reported}"
        )

    def test_bridges(self):
        G_undirected = self.G.to_undirected()
        expected = set()
        for u, v in nx.bridges(G_undirected):
            expected.add(tuple(sorted([u, v])))

        reported = set(tuple(sorted(x)) for x in self.report["bridges"])
        assert reported == expected, (
            f"Bridges mismatch.\n"
            f"Expected: {sorted(expected)}\n"
            f"Got: {sorted(reported)}"
        )


class TestBuildSchedule:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.report = load_report()
        self.declared = parse_build_files()
        self.G = build_declared_digraph(self.declared)
        self.condensed, self.scc_labels = build_condensed_dag(self.G)

    def test_all_packages_present(self):
        schedule = self.report["build_schedule"]
        all_pkgs = set()
        for layer in schedule:
            all_pkgs.update(layer)

        expected_pkgs = set(self.declared.keys())
        assert all_pkgs == expected_pkgs, (
            f"Missing: {expected_pkgs - all_pkgs}, "
            f"Extra: {all_pkgs - expected_pkgs}"
        )

    def test_no_duplicates(self):
        schedule = self.report["build_schedule"]
        flat = [pkg for layer in schedule for pkg in layer]
        assert len(flat) == len(set(flat)), "Duplicate packages in schedule"

    def test_valid_topological_ordering(self):
        schedule = self.report["build_schedule"]
        layer_map = {}
        for i, layer in enumerate(schedule):
            for pkg in layer:
                layer_map[pkg] = i

        for pkg, deps in self.declared.items():
            for dep in deps:
                if self.scc_labels.get(pkg) == self.scc_labels.get(dep):
                    continue
                assert layer_map.get(dep, -1) < layer_map.get(pkg, -1), (
                    f"Dep {dep} (layer {layer_map.get(dep)}) must come "
                    f"before {pkg} (layer {layer_map.get(pkg)})"
                )

    def test_scc_members_same_layer(self):
        schedule = self.report["build_schedule"]
        layer_map = {}
        for i, layer in enumerate(schedule):
            for pkg in layer:
                layer_map[pkg] = i

        for scc in nx.strongly_connected_components(self.G):
            if len(scc) > 1:
                layers = {
                    layer_map[node] for node in scc if node in layer_map
                }
                assert len(layers) == 1, (
                    f"SCC {sorted(scc)} members are in different layers: "
                    f"{layers}"
                )


class TestCriticalPath:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.report = load_report()
        self.declared = parse_build_files()
        self.G = build_declared_digraph(self.declared)
        self.condensed, _ = build_condensed_dag(self.G)

    def test_critical_path_length(self):
        expected = nx.dag_longest_path_length(self.condensed)
        assert self.report["critical_path_length"] == expected, (
            f"Expected critical path length {expected}, "
            f"got {self.report['critical_path_length']}"
        )


class TestTransitiveReduction:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.report = load_report()
        self.declared = parse_build_files()
        self.G = build_declared_digraph(self.declared)
        self.condensed, self.scc_labels = build_condensed_dag(self.G)

    def test_transitive_reduction_edges(self):
        tr = nx.transitive_reduction(self.condensed)
        removed_condensed = set()
        for u, v in self.condensed.edges():
            if not tr.has_edge(u, v):
                removed_condensed.add((u, v))

        expected_removed = set()
        for pkg, deps in self.declared.items():
            for dep in deps:
                src = self.scc_labels[pkg]
                dst = self.scc_labels[dep]
                if src != dst and (src, dst) in removed_condensed:
                    expected_removed.add((pkg, dep))

        reported = set(
            tuple(x) for x in self.report["transitive_reduction_removed"]
        )
        assert reported == expected_removed, (
            f"Transitive reduction mismatch.\n"
            f"Expected: {sorted(expected_removed)}\n"
            f"Got: {sorted(reported)}"
        )


class TestVisualization:
    def test_svg_exists(self):
        assert os.path.isfile(SVG_PATH), (
            f"Dependency graph SVG not found at {SVG_PATH}"
        )

    def test_svg_is_valid(self):
        with open(SVG_PATH) as f:
            content = f.read()
        assert "<svg" in content.lower(), (
            "dep_graph.svg does not contain valid SVG markup"
        )

    def test_svg_contains_all_packages(self):
        declared = parse_build_files()
        with open(SVG_PATH) as f:
            content = f.read()
        missing = [pkg for pkg in declared if pkg not in content]
        assert not missing, (
            f"Packages missing from SVG visualization: {missing}"
        )
