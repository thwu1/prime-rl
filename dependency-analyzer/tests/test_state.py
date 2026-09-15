"""Tests for the Feature Dependency Analysis Pipeline.
Verifies Makefile targets, raw imports, resolved deps, DOT graph,
SQLite database, analysis JSON, and dynamic anti-cheat.
"""

import json
import os
import re
import shutil
import sqlite3
import subprocess

import pytest


CODEBASE = "/app/codebase"
OUTPUT_DIR = "/app/output"


def run_pipeline():
    """Run the Makefile pipeline and return parsed JSON outputs."""
    if os.path.exists(OUTPUT_DIR):
        shutil.rmtree(OUTPUT_DIR)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    result = subprocess.run(
        ["make", "-C", "/app", "all"],
        capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, (
        f"make all failed:\n{result.stderr}\n{result.stdout}"
    )

    outputs = {}
    for name in ["raw_imports.json", "resolved_deps.json", "analysis.json"]:
        path = os.path.join(OUTPUT_DIR, name)
        assert os.path.exists(path), f"{name} not created"
        with open(path) as f:
            outputs[name] = json.load(f)
    return outputs


@pytest.fixture(scope="module")
def pipeline():
    return run_pipeline()


# ── Makefile ────────────────────────────────────────────────────


def test_makefile_exists():
    assert os.path.exists("/app/Makefile"), "Makefile not found at /app/Makefile"


def test_makefile_has_targets():
    with open("/app/Makefile") as f:
        content = f.read()
    for target in ["extract", "resolve", "graph", "store", "analyze", "clean", "all"]:
        assert re.search(rf"^{target}\b", content, re.MULTILINE), (
            f"Makefile missing target: {target}"
        )


# ── Raw Imports (extract stage) ─────────────────────────────────


def test_raw_imports_source_count(pipeline):
    raw = pipeline["raw_imports.json"]
    assert isinstance(raw, dict)
    assert len(raw) == 9, (
        f"Expected 9 source modules, got {len(raw)}: {sorted(raw.keys())}"
    )


def test_raw_imports_excludes_init(pipeline):
    raw = pipeline["raw_imports.json"]
    for key in raw:
        assert "__init__" not in key, f"__init__.py in raw imports: {key}"


def test_raw_imports_excludes_conftest(pipeline):
    raw = pipeline["raw_imports.json"]
    for key in raw:
        assert "conftest" not in key, f"conftest.py in raw imports: {key}"


def test_raw_imports_excludes_tests(pipeline):
    raw = pipeline["raw_imports.json"]
    for key in raw:
        assert not os.path.basename(key).startswith("test_"), (
            f"Test file in raw imports: {key}"
        )


def test_relative_imports_cipher(pipeline):
    """crypto/cipher.py must have a relative import."""
    raw = pipeline["raw_imports.json"]
    cipher_imports = raw.get("crypto/cipher.py", [])
    assert any(i["type"] == "relative" for i in cipher_imports), (
        f"No relative import in crypto/cipher.py: {cipher_imports}"
    )


def test_relative_imports_sign(pipeline):
    """crypto/sign.py must have exactly 2 relative imports."""
    raw = pipeline["raw_imports.json"]
    sign_imports = raw.get("crypto/sign.py", [])
    rel_count = sum(1 for i in sign_imports if i["type"] == "relative")
    assert rel_count == 2, (
        f"Expected 2 relative imports in crypto/sign.py, got {rel_count}"
    )


def test_raw_import_record_fields(pipeline):
    """Each import record must have module, names, line, type."""
    raw = pipeline["raw_imports.json"]
    for module, imports in raw.items():
        for imp in imports:
            for field in ["module", "names", "line", "type"]:
                assert field in imp, (
                    f"Missing field '{field}' in {module}: {imp}"
                )
            assert imp["type"] in ("absolute", "relative", "conditional"), (
                f"Invalid type '{imp['type']}' in {module}"
            )


# ── Resolved Dependencies (resolve stage) ──────────────────────


EXPECTED_GRAPH = {
    "crypto/cipher.py": ["crypto/hash.py"],
    "crypto/hash.py": [],
    "crypto/sign.py": ["crypto/cipher.py", "crypto/hash.py"],
    "network/dns.py": ["network/transport.py"],
    "network/protocol.py": [],
    "network/transport.py": ["network/protocol.py"],
    "storage/block.py": [],
    "storage/filesystem.py": ["storage/block.py"],
    "storage/journal.py": ["crypto/hash.py", "storage/filesystem.py"],
}


def test_resolved_deps_keys(pipeline):
    resolved = pipeline["resolved_deps.json"]
    assert set(resolved.keys()) == set(EXPECTED_GRAPH.keys()), (
        f"Key diff: {set(resolved.keys()) ^ set(EXPECTED_GRAPH.keys())}"
    )


def test_resolved_deps_values(pipeline):
    resolved = pipeline["resolved_deps.json"]
    for key, expected in EXPECTED_GRAPH.items():
        actual = sorted(resolved[key])
        assert actual == sorted(expected), (
            f"Deps for {key}: {actual} != {sorted(expected)}"
        )


def test_relative_imports_resolved_correctly(pipeline):
    """Relative import from crypto/cipher.py must resolve to crypto/hash.py."""
    resolved = pipeline["resolved_deps.json"]
    assert "crypto/hash.py" in resolved.get("crypto/cipher.py", []), (
        "Relative import crypto/cipher.py -> crypto/hash.py not resolved"
    )


def test_cross_package_dependency(pipeline):
    """storage/journal.py must depend on crypto/hash.py."""
    resolved = pipeline["resolved_deps.json"]
    assert "crypto/hash.py" in resolved.get("storage/journal.py", []), (
        "Cross-package dep missing: storage/journal.py -> crypto/hash.py"
    )


# ── Graphviz (graph stage) ──────────────────────────────────────


def test_dot_file_exists(pipeline):
    assert os.path.exists(os.path.join(OUTPUT_DIR, "deps.dot")), (
        "deps.dot not found"
    )


def test_svg_file_exists(pipeline):
    assert os.path.exists(os.path.join(OUTPUT_DIR, "deps.svg")), (
        "deps.svg not found"
    )


def test_dot_has_subgraph_clusters(pipeline):
    with open(os.path.join(OUTPUT_DIR, "deps.dot")) as f:
        dot = f.read()
    for pkg in ["crypto", "network", "storage"]:
        assert f"subgraph cluster_{pkg}" in dot, (
            f"Missing subgraph cluster_{pkg} in DOT file"
        )


def test_dot_has_edges(pipeline):
    with open(os.path.join(OUTPUT_DIR, "deps.dot")) as f:
        dot = f.read()
    assert "->" in dot, "No edges found in DOT file"


def test_dot_contains_cross_package_edge(pipeline):
    """DOT must represent the journal -> hash cross-package edge."""
    with open(os.path.join(OUTPUT_DIR, "deps.dot")) as f:
        dot = f.read().lower()
    assert "journal" in dot, "journal node missing from DOT"
    assert "hash" in dot, "hash node missing from DOT"


def test_svg_valid(pipeline):
    svg_path = os.path.join(OUTPUT_DIR, "deps.svg")
    with open(svg_path) as f:
        content = f.read()
    assert "<svg" in content, "SVG file doesn't contain <svg> tag"


# ── SQLite Database (store stage) ───────────────────────────────


def test_db_exists(pipeline):
    assert os.path.exists(os.path.join(OUTPUT_DIR, "analysis.db")), (
        "analysis.db not found"
    )


def test_db_schema_tables(pipeline):
    db = sqlite3.connect(os.path.join(OUTPUT_DIR, "analysis.db"))
    cursor = db.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cursor.fetchall()}
    required = {"modules", "dependencies", "test_cones", "features", "feature_tests"}
    assert required <= tables, f"Missing tables: {required - tables}"
    db.close()


def test_db_modules_count(pipeline):
    db = sqlite3.connect(os.path.join(OUTPUT_DIR, "analysis.db"))
    cursor = db.cursor()
    cursor.execute("SELECT COUNT(*) FROM modules")
    count = cursor.fetchone()[0]
    assert count == 9, f"Expected 9 modules, got {count}"
    db.close()


def test_db_modules_paths(pipeline):
    db = sqlite3.connect(os.path.join(OUTPUT_DIR, "analysis.db"))
    cursor = db.cursor()
    cursor.execute("SELECT path FROM modules ORDER BY path")
    paths = [row[0] for row in cursor.fetchall()]
    expected_paths = sorted(EXPECTED_GRAPH.keys())
    assert paths == expected_paths, f"Module paths: {paths} != {expected_paths}"
    db.close()


def test_db_dependency_import_type(pipeline):
    """crypto/cipher.py -> crypto/hash.py must have import_type='relative'."""
    db = sqlite3.connect(os.path.join(OUTPUT_DIR, "analysis.db"))
    cursor = db.cursor()
    cursor.execute("""
        SELECT d.import_type
        FROM dependencies d
        JOIN modules m1 ON d.source_id = m1.id
        JOIN modules m2 ON d.target_id = m2.id
        WHERE m1.path = 'crypto/cipher.py' AND m2.path = 'crypto/hash.py'
    """)
    row = cursor.fetchone()
    assert row is not None, "Dependency crypto/cipher.py -> crypto/hash.py not in DB"
    assert row[0] == "relative", (
        f"Expected import_type='relative', got '{row[0]}'"
    )
    db.close()


def test_db_test_cones(pipeline):
    """Verify test_journal.py cone in database."""
    db = sqlite3.connect(os.path.join(OUTPUT_DIR, "analysis.db"))
    cursor = db.cursor()
    cursor.execute("""
        SELECT m.path FROM test_cones tc
        JOIN modules m ON tc.module_id = m.id
        WHERE tc.test_path = 'tests/test_journal.py'
        ORDER BY m.path
    """)
    cone = [row[0] for row in cursor.fetchall()]
    expected = sorted([
        "crypto/hash.py", "storage/block.py",
        "storage/filesystem.py", "storage/journal.py",
    ])
    assert cone == expected, f"Journal cone in DB: {cone} != {expected}"
    db.close()


def test_db_features(pipeline):
    db = sqlite3.connect(os.path.join(OUTPUT_DIR, "analysis.db"))
    cursor = db.cursor()
    cursor.execute("SELECT DISTINCT feature_id FROM features ORDER BY feature_id")
    feature_ids = [row[0] for row in cursor.fetchall()]
    assert feature_ids == [0, 1], f"Feature IDs in DB: {feature_ids}"
    db.close()


def test_db_feature_tests(pipeline):
    db = sqlite3.connect(os.path.join(OUTPUT_DIR, "analysis.db"))
    cursor = db.cursor()
    cursor.execute("""
        SELECT test_path FROM feature_tests
        WHERE feature_id = 0 ORDER BY test_path
    """)
    tests_f0 = [row[0] for row in cursor.fetchall()]
    assert tests_f0 == ["tests/test_dns.py", "tests/test_transport.py"], (
        f"Feature 0 tests in DB: {tests_f0}"
    )
    db.close()


# ── Analysis JSON (analyze stage) ──────────────────────────────


EXPECTED_CONES = {
    "tests/test_dns.py": [
        "network/dns.py", "network/protocol.py", "network/transport.py",
    ],
    "tests/test_filesystem.py": [
        "storage/block.py", "storage/filesystem.py",
    ],
    "tests/test_hash.py": [
        "crypto/hash.py",
    ],
    "tests/test_journal.py": [
        "crypto/hash.py", "storage/block.py",
        "storage/filesystem.py", "storage/journal.py",
    ],
    "tests/test_signing.py": [
        "crypto/cipher.py", "crypto/hash.py", "crypto/sign.py",
    ],
    "tests/test_transport.py": [
        "network/protocol.py", "network/transport.py",
    ],
}

EXPECTED_FEATURES = [
    {
        "id": 0,
        "tests": ["tests/test_dns.py", "tests/test_transport.py"],
        "source_files": [
            "network/dns.py", "network/protocol.py", "network/transport.py",
        ],
    },
    {
        "id": 1,
        "tests": [
            "tests/test_filesystem.py", "tests/test_hash.py",
            "tests/test_journal.py", "tests/test_signing.py",
        ],
        "source_files": [
            "crypto/cipher.py", "crypto/hash.py", "crypto/sign.py",
            "storage/block.py", "storage/filesystem.py", "storage/journal.py",
        ],
    },
]


def test_analysis_top_level_keys(pipeline):
    analysis = pipeline["analysis.json"]
    required = {
        "dependency_graph",
        "test_dependency_cones",
        "features",
        "isolation_matrix",
        "minimal_disruption_sets",
    }
    assert required <= set(analysis.keys()), (
        f"Missing keys: {required - set(analysis.keys())}"
    )


def test_analysis_graph_keys(pipeline):
    graph = pipeline["analysis.json"]["dependency_graph"]
    assert set(graph.keys()) == set(EXPECTED_GRAPH.keys()), (
        f"Key diff: {set(graph.keys()) ^ set(EXPECTED_GRAPH.keys())}"
    )


def test_analysis_graph_values(pipeline):
    graph = pipeline["analysis.json"]["dependency_graph"]
    for key, expected in EXPECTED_GRAPH.items():
        actual = sorted(graph[key])
        assert actual == sorted(expected), (
            f"Deps for {key}: {actual} != {sorted(expected)}"
        )


def test_analysis_cone_keys(pipeline):
    cones = pipeline["analysis.json"]["test_dependency_cones"]
    assert set(cones.keys()) == set(EXPECTED_CONES.keys()), (
        f"Cone key diff: {set(cones.keys()) ^ set(EXPECTED_CONES.keys())}"
    )


def test_analysis_cone_values(pipeline):
    cones = pipeline["analysis.json"]["test_dependency_cones"]
    for test, expected in EXPECTED_CONES.items():
        actual = sorted(cones[test])
        assert actual == sorted(expected), (
            f"Cone for {test}: {actual} != {sorted(expected)}"
        )


def test_analysis_cone_transitivity(pipeline):
    """test_journal must include storage/block.py via storage/filesystem.py."""
    cone = pipeline["analysis.json"]["test_dependency_cones"]["tests/test_journal.py"]
    assert "storage/block.py" in cone
    assert "crypto/hash.py" in cone


def test_analysis_feature_count(pipeline):
    assert len(pipeline["analysis.json"]["features"]) == 2


def test_analysis_feature_ids(pipeline):
    ids = [f["id"] for f in pipeline["analysis.json"]["features"]]
    assert ids == [0, 1]


def test_analysis_feature_tests(pipeline):
    for exp in EXPECTED_FEATURES:
        feat = pipeline["analysis.json"]["features"][exp["id"]]
        assert sorted(feat["tests"]) == sorted(exp["tests"]), (
            f"Feature {exp['id']} tests mismatch"
        )


def test_analysis_feature_sources(pipeline):
    for exp in EXPECTED_FEATURES:
        feat = pipeline["analysis.json"]["features"][exp["id"]]
        assert sorted(feat["source_files"]) == sorted(exp["source_files"]), (
            f"Feature {exp['id']} sources mismatch"
        )


def test_analysis_feature_ordering(pipeline):
    features = pipeline["analysis.json"]["features"]
    for i in range(len(features) - 1):
        min_a = min(features[i]["tests"])
        min_b = min(features[i + 1]["tests"])
        assert min_a < min_b, f"Feature ordering violated: {min_a} >= {min_b}"


def test_analysis_isolation_matrix_shape(pipeline):
    matrix = pipeline["analysis.json"]["isolation_matrix"]
    assert len(matrix) == 2
    for row in matrix:
        assert len(row) == 2


def test_analysis_isolation_matrix_diagonal(pipeline):
    matrix = pipeline["analysis.json"]["isolation_matrix"]
    assert matrix[0][0] == pytest.approx(1.0)
    assert matrix[1][1] == pytest.approx(1.0)


def test_analysis_isolation_matrix_off_diagonal(pipeline):
    matrix = pipeline["analysis.json"]["isolation_matrix"]
    assert matrix[0][1] == pytest.approx(0.0)
    assert matrix[1][0] == pytest.approx(0.0)


def test_analysis_mds_keys(pipeline):
    mds = pipeline["analysis.json"]["minimal_disruption_sets"]
    assert set(mds.keys()) == {"0", "1"}


def test_analysis_mds_feature_0(pipeline):
    mds = pipeline["analysis.json"]["minimal_disruption_sets"]
    assert sorted(mds["0"]) == ["network/protocol.py"]


def test_analysis_mds_feature_1(pipeline):
    mds = pipeline["analysis.json"]["minimal_disruption_sets"]
    assert sorted(mds["1"]) == ["crypto/hash.py", "storage/block.py"]


def test_mds_hit_constraint(pipeline):
    """Every MDS must intersect every test cone in its feature."""
    analysis = pipeline["analysis.json"]
    cones = analysis["test_dependency_cones"]
    for feat in analysis["features"]:
        fid = str(feat["id"])
        mds_set = set(analysis["minimal_disruption_sets"][fid])
        for test in feat["tests"]:
            assert mds_set & set(cones[test]), (
                f"MDS for feature {fid} doesn't hit cone of {test}"
            )


def test_mds_exclusion_constraint(pipeline):
    """Every MDS must NOT intersect cones from other features."""
    analysis = pipeline["analysis.json"]
    cones = analysis["test_dependency_cones"]
    for feat in analysis["features"]:
        fid = str(feat["id"])
        mds_set = set(analysis["minimal_disruption_sets"][fid])
        for other in analysis["features"]:
            if other["id"] == feat["id"]:
                continue
            for test in other["tests"]:
                assert not (mds_set & set(cones[test])), (
                    f"MDS for feature {fid} wrongly hits {test} "
                    f"from feature {other['id']}"
                )


def test_mds_minimality(pipeline):
    """Removing any element from MDS must break the hit constraint."""
    analysis = pipeline["analysis.json"]
    cones = analysis["test_dependency_cones"]
    for feat in analysis["features"]:
        fid = str(feat["id"])
        mds_list = analysis["minimal_disruption_sets"][fid]
        if len(mds_list) <= 1:
            continue
        for i in range(len(mds_list)):
            reduced = set(mds_list) - {mds_list[i]}
            hits_all = all(reduced & set(cones[t]) for t in feat["tests"])
            assert not hits_all, (
                f"MDS for feature {fid} is not minimal: "
                f"removing {mds_list[i]} still hits all cones"
            )


# ── Anti-Cheat: Dynamic Modification ───────────────────────────


def test_anti_cheat_new_module():
    """Add a cross-cutting module bridging features, re-run full pipeline."""
    firewall_code = (
        '"""Network firewall with cross-package deps."""\n'
        "\n"
        "from network.dns import DNSResolver\n"
        "from crypto.hash import sha256\n"
        "\n"
        "\n"
        "class Firewall:\n"
        "    def __init__(self):\n"
        "        self.resolver = DNSResolver()\n"
        "        self.rules = []\n"
        "\n"
        "    def check(self, hostname: str) -> str:\n"
        "        ip = self.resolver.resolve(hostname)\n"
        "        return sha256(ip.encode())\n"
    )
    test_firewall_code = (
        "from network.firewall import Firewall\n"
        "\n"
        "\n"
        "def test_firewall_init():\n"
        "    fw = Firewall()\n"
        "    assert fw.rules == []\n"
        "\n"
        "\n"
        "def test_firewall_check():\n"
        "    fw = Firewall()\n"
        "    result = fw.check('example.com')\n"
        "    assert isinstance(result, str)\n"
    )

    try:
        with open(os.path.join(CODEBASE, "network/firewall.py"), "w") as f:
            f.write(firewall_code)
        with open(os.path.join(CODEBASE, "tests/test_firewall.py"), "w") as f:
            f.write(test_firewall_code)

        # Clean and re-run full pipeline
        if os.path.exists(OUTPUT_DIR):
            shutil.rmtree(OUTPUT_DIR)
        os.makedirs(OUTPUT_DIR, exist_ok=True)

        result = subprocess.run(
            ["make", "-C", "/app", "all"],
            capture_output=True, text=True, timeout=180,
        )
        assert result.returncode == 0, (
            f"make all failed after modification:\n{result.stderr}"
        )

        with open(os.path.join(OUTPUT_DIR, "analysis.json")) as f:
            data = json.load(f)

        # New source file must appear in dependency graph
        assert "network/firewall.py" in data["dependency_graph"], (
            "network/firewall.py missing from dependency_graph"
        )
        firewall_deps = sorted(data["dependency_graph"]["network/firewall.py"])
        assert firewall_deps == ["crypto/hash.py", "network/dns.py"], (
            f"firewall deps: {firewall_deps}"
        )

        # New test file in cones
        assert "tests/test_firewall.py" in data["test_dependency_cones"], (
            "test_firewall.py missing from cones"
        )
        cone = sorted(data["test_dependency_cones"]["tests/test_firewall.py"])
        for expected_mod in [
            "network/firewall.py", "crypto/hash.py",
            "network/dns.py", "network/transport.py", "network/protocol.py",
        ]:
            assert expected_mod in cone, f"{expected_mod} missing from firewall cone"

        # Firewall bridges features: all tests collapse into 1 feature
        assert len(data["features"]) == 1, (
            f"Expected 1 feature after bridge, got {len(data['features'])}"
        )
        assert len(data["features"][0]["tests"]) == 7, (
            f"Expected 7 tests, got {len(data['features'][0]['tests'])}"
        )

        # Isolation matrix 1x1
        assert len(data["isolation_matrix"]) == 1
        assert data["isolation_matrix"][0][0] == pytest.approx(1.0)

        # MDS for merged feature must hit all 7 cones, size 3
        mds_set = set(data["minimal_disruption_sets"]["0"])
        cones = data["test_dependency_cones"]
        for test in data["features"][0]["tests"]:
            assert mds_set & set(cones[test]), (
                f"Merged MDS doesn't hit cone of {test}"
            )
        assert len(mds_set) == 3, (
            f"Merged MDS size {len(mds_set)}, expected 3"
        )

        # DOT file must include firewall
        assert os.path.exists(os.path.join(OUTPUT_DIR, "deps.dot"))
        with open(os.path.join(OUTPUT_DIR, "deps.dot")) as f:
            dot = f.read()
        assert "firewall" in dot.lower(), "firewall missing from DOT file"

        # SQLite DB must have 10 modules
        db = sqlite3.connect(os.path.join(OUTPUT_DIR, "analysis.db"))
        cursor = db.cursor()
        cursor.execute("SELECT COUNT(*) FROM modules")
        count = cursor.fetchone()[0]
        assert count == 10, f"Expected 10 modules after bridge, got {count}"
        db.close()

    finally:
        for p in [
            os.path.join(CODEBASE, "network/firewall.py"),
            os.path.join(CODEBASE, "tests/test_firewall.py"),
        ]:
            if os.path.exists(p):
                os.remove(p)
