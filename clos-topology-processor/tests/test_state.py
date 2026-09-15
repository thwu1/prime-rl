"""Tests for the containerlab topology factoring compiler.

"""

import json
import os
import subprocess
import sys
import tempfile

import yaml

sys.path.insert(0, "/app")
from resolver import resolve_topology, load_topology


COMPILER = "/app/topo_compiler.py"
TOPO_DIR = "/app/topologies"


def run_compiler(topo_path):
    """Run the topology compiler and return stdout."""
    result = subprocess.run(
        [sys.executable, COMPILER, topo_path],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"Compiler failed: exit={result.returncode}\n"
        f"stderr: {result.stderr}\nstdout: {result.stdout}"
    )
    return result.stdout


def resolve_from_yaml(yaml_str):
    """Parse YAML string and resolve topology."""
    topo = yaml.safe_load(yaml_str)
    return resolve_topology(topo)


def assert_resolved_equal(flat_path, factored_yaml):
    """Assert that flat and factored topologies resolve to the same state."""
    flat_topo = load_topology(flat_path)
    flat_resolved = resolve_topology(flat_topo)

    factored_topo = yaml.safe_load(factored_yaml)
    factored_resolved = resolve_topology(factored_topo)

    assert flat_resolved["name"] == factored_resolved["name"], (
        f"Name mismatch: {flat_resolved['name']} != {factored_resolved['name']}"
    )

    assert set(flat_resolved["nodes"].keys()) == set(factored_resolved["nodes"].keys()), (
        f"Node set mismatch: {set(flat_resolved['nodes'].keys())} "
        f"!= {set(factored_resolved['nodes'].keys())}"
    )

    for node_name in flat_resolved["nodes"]:
        flat_node = flat_resolved["nodes"][node_name]
        fact_node = factored_resolved["nodes"][node_name]
        for field in ("kind", "image", "type"):
            assert flat_node[field] == fact_node[field], (
                f"Node {node_name}.{field}: {flat_node[field]!r} != {fact_node[field]!r}"
            )
        for field in ("env", "labels"):
            assert flat_node[field] == fact_node[field], (
                f"Node {node_name}.{field}:\n"
                f"  flat={flat_node[field]}\n  fact={fact_node[field]}"
            )


def has_inheritance(topo_data):
    """Check that the factored topology uses inheritance features."""
    t = topo_data.get("topology", {})
    has_defaults = bool(t.get("defaults"))
    has_kinds = bool(t.get("kinds"))
    has_groups = bool(t.get("groups"))
    return has_defaults or has_kinds or has_groups


def count_node_keys(topo_data):
    """Count total key-value pairs at the node level (excluding group refs)."""
    total = 0
    for node in (topo_data.get("topology", {}).get("nodes") or {}).values():
        if node is None:
            continue
        for key, val in node.items():
            if key == "group":
                continue
            if isinstance(val, dict):
                total += len(val)
            else:
                total += 1
    return total


# ---- Basic topology: 4 nodes, single kind, two clear groups ----


class TestBasicTopology:
    """Test factoring of the basic 4-node topology."""

    @classmethod
    def setup_class(cls):
        cls.flat_path = os.path.join(TOPO_DIR, "basic.flat.yml")
        cls.output = run_compiler(cls.flat_path)
        cls.factored = yaml.safe_load(cls.output)

    def test_valid_yaml(self):
        assert self.factored is not None
        assert "name" in self.factored
        assert "topology" in self.factored

    def test_semantic_equivalence(self):
        assert_resolved_equal(self.flat_path, self.output)

    def test_uses_inheritance(self):
        assert has_inheritance(self.factored), (
            "Factored topology must use defaults, kinds, or groups"
        )

    def test_reduces_node_properties(self):
        flat = load_topology(self.flat_path)
        flat_keys = count_node_keys(flat)
        fact_keys = count_node_keys(self.factored)
        assert fact_keys < flat_keys, (
            f"Factoring should reduce node-level properties: "
            f"flat={flat_keys}, factored={fact_keys}"
        )

    def test_links_preserved(self):
        flat = load_topology(self.flat_path)
        flat_links = flat.get("topology", {}).get("links", [])
        fact_links = self.factored.get("topology", {}).get("links", [])
        assert len(flat_links) == len(fact_links), "Link count must be preserved"

    def test_name_preserved(self):
        flat = load_topology(self.flat_path)
        assert self.factored["name"] == flat["name"]

    def test_db_port_isolation(self):
        """DB_PORT differs between db1 and db2, must not be factored out."""
        resolved = resolve_from_yaml(self.output)
        assert resolved["nodes"]["db1"]["env"]["DB_PORT"] == "5432"
        assert resolved["nodes"]["db2"]["env"]["DB_PORT"] == "5433"
        for name in ("web1", "web2"):
            assert "DB_PORT" not in resolved["nodes"][name]["env"]


# ---- Mixed topology: 6 nodes, two kinds, cross-kind groups ----


class TestMixedTopology:
    """Test factoring of the mixed-kind 6-node topology."""

    @classmethod
    def setup_class(cls):
        cls.flat_path = os.path.join(TOPO_DIR, "mixed.flat.yml")
        cls.output = run_compiler(cls.flat_path)
        cls.factored = yaml.safe_load(cls.output)

    def test_semantic_equivalence(self):
        assert_resolved_equal(self.flat_path, self.output)

    def test_uses_inheritance(self):
        assert has_inheritance(self.factored)

    def test_reduces_node_properties(self):
        flat = load_topology(self.flat_path)
        flat_keys = count_node_keys(flat)
        fact_keys = count_node_keys(self.factored)
        assert fact_keys < flat_keys

    def test_multi_kind_handling(self):
        """Factored topology must handle multiple kinds correctly."""
        resolved = resolve_from_yaml(self.output)
        assert resolved["nodes"]["leaf2"]["kind"] == "nokia_srlinux"
        assert resolved["nodes"]["leaf2"]["image"] == "ghcr.io/nokia/srlinux:latest"
        assert resolved["nodes"]["spine1"]["kind"] == "linux"

    def test_monitor_env_isolation(self):
        """Servers must NOT have MONITOR env var (not shared by all nodes)."""
        resolved = resolve_from_yaml(self.output)
        for sname in ("server1", "server2"):
            assert "MONITOR" not in resolved["nodes"][sname]["env"], (
                f"{sname} should not have MONITOR in env"
            )

    def test_vendor_env_isolation(self):
        """Only nokia nodes should have VENDOR env."""
        resolved = resolve_from_yaml(self.output)
        for name, node in resolved["nodes"].items():
            if node["kind"] == "nokia_srlinux":
                assert node["env"].get("VENDOR") == "nokia"
            else:
                assert "VENDOR" not in node["env"], (
                    f"{name} (kind={node['kind']}) should not have VENDOR"
                )

    def test_debug_env_isolation(self):
        """DEBUG env must only be on server2."""
        resolved = resolve_from_yaml(self.output)
        assert resolved["nodes"]["server2"]["env"].get("DEBUG") == "true"
        for name in ("spine1", "spine2", "leaf1", "leaf2", "server1"):
            assert "DEBUG" not in resolved["nodes"][name]["env"]

    def test_links_preserved(self):
        flat = load_topology(self.flat_path)
        flat_links = flat.get("topology", {}).get("links", [])
        fact_links = self.factored.get("topology", {}).get("links", [])
        assert len(flat_links) == len(fact_links)


# ---- Tricky topology: subtle map overlap pitfalls ----


class TestTrickyTopology:
    """Test factoring of the tricky topology with subtle map overlaps."""

    @classmethod
    def setup_class(cls):
        cls.flat_path = os.path.join(TOPO_DIR, "tricky.flat.yml")
        cls.output = run_compiler(cls.flat_path)
        cls.factored = yaml.safe_load(cls.output)

    def test_semantic_equivalence(self):
        assert_resolved_equal(self.flat_path, self.output)

    def test_uses_inheritance(self):
        assert has_inheritance(self.factored)

    def test_reduces_node_properties(self):
        flat = load_topology(self.flat_path)
        flat_keys = count_node_keys(flat)
        fact_keys = count_node_keys(self.factored)
        assert fact_keys < flat_keys

    def test_feature_a_isolation(self):
        """FEATURE_A must only be on alpha, beta, gamma -- not on others."""
        resolved = resolve_from_yaml(self.output)
        for name in ("alpha", "beta", "gamma"):
            assert resolved["nodes"][name]["env"].get("FEATURE_A") == "on", (
                f"{name} should have FEATURE_A=on"
            )
        for name in ("delta", "epsilon", "zeta"):
            assert "FEATURE_A" not in resolved["nodes"][name]["env"], (
                f"{name} should NOT have FEATURE_A"
            )

    def test_feature_b_isolation(self):
        """FEATURE_B must only be on alpha."""
        resolved = resolve_from_yaml(self.output)
        assert resolved["nodes"]["alpha"]["env"].get("FEATURE_B") == "on"
        for name in ("beta", "gamma", "delta", "epsilon", "zeta"):
            assert "FEATURE_B" not in resolved["nodes"][name]["env"]

    def test_feature_c_isolation(self):
        """FEATURE_C must only be on gamma."""
        resolved = resolve_from_yaml(self.output)
        assert resolved["nodes"]["gamma"]["env"].get("FEATURE_C") == "on"
        for name in ("alpha", "beta", "delta", "epsilon", "zeta"):
            assert "FEATURE_C" not in resolved["nodes"][name]["env"]

    def test_shared_env_on_all(self):
        """SHARED=common must be on all nodes."""
        resolved = resolve_from_yaml(self.output)
        for name in resolved["nodes"]:
            assert resolved["nodes"][name]["env"]["SHARED"] == "common"

    def test_mode_per_node(self):
        """Each node must have correct MODE."""
        resolved = resolve_from_yaml(self.output)
        expected = {
            "alpha": "batch",
            "beta": "batch",
            "gamma": "streaming",
            "delta": "routing",
            "epsilon": "routing",
            "zeta": "passive",
        }
        for name, mode in expected.items():
            assert resolved["nodes"][name]["env"]["MODE"] == mode, (
                f"{name} MODE should be {mode}, "
                f"got {resolved['nodes'][name]['env'].get('MODE')}"
            )

    def test_staging_env_label(self):
        """gamma must have env=staging label, others prod."""
        resolved = resolve_from_yaml(self.output)
        assert resolved["nodes"]["gamma"]["labels"]["env"] == "staging"
        for name in ("alpha", "beta", "delta", "epsilon", "zeta"):
            assert resolved["nodes"][name]["labels"]["env"] == "prod", (
                f"{name} labels.env should be prod, "
                f"got {resolved['nodes'][name]['labels'].get('env')}"
            )

    def test_factoring_quality(self):
        """The factored topology should achieve significant reduction."""
        flat = load_topology(self.flat_path)
        flat_keys = count_node_keys(flat)
        fact_keys = count_node_keys(self.factored)
        reduction = (flat_keys - fact_keys) / flat_keys
        assert reduction >= 0.4, (
            f"Factoring quality too low: {reduction:.1%} reduction "
            f"(flat={flat_keys}, factored={fact_keys})"
        )

    def test_links_preserved(self):
        flat = load_topology(self.flat_path)
        flat_links = flat.get("topology", {}).get("links", [])
        fact_links = self.factored.get("topology", {}).get("links", [])
        assert len(flat_links) == len(fact_links)


# ---- Edge cases ----


class TestEdgeCases:
    """Test edge cases in factoring."""

    def test_single_node_topology(self):
        """Single-node topology should still produce valid output."""
        single = {
            "name": "single",
            "topology": {
                "nodes": {
                    "only": {
                        "kind": "linux",
                        "image": "alpine:3",
                        "type": "",
                        "env": {"KEY": "val"},
                        "labels": {"l": "v"},
                    }
                },
                "links": [],
            },
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yml", delete=False
        ) as f:
            yaml.dump(single, f)
            f.flush()
            output = run_compiler(f.name)
        os.unlink(f.name)
        factored = yaml.safe_load(output)
        factored_resolved = resolve_topology(factored)
        flat_resolved = resolve_topology(single)
        assert flat_resolved["nodes"]["only"] == factored_resolved["nodes"]["only"]

    def test_all_identical_nodes(self):
        """All-identical nodes should be maximally factored."""
        identical = {
            "name": "identical",
            "topology": {
                "nodes": {
                    f"n{i}": {
                        "kind": "linux",
                        "image": "alpine:3",
                        "type": "worker",
                        "env": {"A": "1", "B": "2"},
                        "labels": {"x": "y"},
                    }
                    for i in range(1, 5)
                },
                "links": [],
            },
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yml", delete=False
        ) as f:
            yaml.dump(identical, f)
            f.flush()
            output = run_compiler(f.name)
        os.unlink(f.name)
        factored = yaml.safe_load(output)
        factored_resolved = resolve_topology(factored)
        flat_resolved = resolve_topology(identical)
        for name in identical["topology"]["nodes"]:
            assert flat_resolved["nodes"][name] == factored_resolved["nodes"][name]
        fact_keys = count_node_keys(factored)
        flat_keys = count_node_keys(identical)
        assert fact_keys < flat_keys, "Identical nodes should be heavily factored"

    def test_no_shared_env(self):
        """Nodes with completely disjoint env should not get spurious keys."""
        disjoint = {
            "name": "disjoint",
            "topology": {
                "nodes": {
                    "a": {
                        "kind": "linux",
                        "image": "alpine:3",
                        "type": "x",
                        "env": {"ONLY_A": "1"},
                        "labels": {},
                    },
                    "b": {
                        "kind": "linux",
                        "image": "alpine:3",
                        "type": "x",
                        "env": {"ONLY_B": "2"},
                        "labels": {},
                    },
                },
                "links": [],
            },
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yml", delete=False
        ) as f:
            yaml.dump(disjoint, f)
            f.flush()
            output = run_compiler(f.name)
        os.unlink(f.name)
        factored = yaml.safe_load(output)
        factored_resolved = resolve_topology(factored)
        flat_resolved = resolve_topology(disjoint)
        # Node a must not have ONLY_B and vice versa
        assert flat_resolved["nodes"]["a"] == factored_resolved["nodes"]["a"]
        assert flat_resolved["nodes"]["b"] == factored_resolved["nodes"]["b"]
        assert "ONLY_B" not in factored_resolved["nodes"]["a"]["env"]
        assert "ONLY_A" not in factored_resolved["nodes"]["b"]["env"]
