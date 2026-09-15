#!/usr/bin/env python3

import subprocess
import json
import os
import re
import pytest


def run_resolver(command, *args):
    """Run the resolver executable and return parsed JSON output."""
    cmd = ["/app/resolver", command] + list(args)
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"resolver exited {result.returncode}:\n"
        f"stdout: {result.stdout}\n"
        f"stderr: {result.stderr}"
    )
    return json.loads(result.stdout)


# ---------------------------------------------------------------------------
# resolve command tests
# ---------------------------------------------------------------------------


class TestResolveSimple:
    """Basic feature resolution without weak dependency interaction."""

    def test_single_leaf_feature(self):
        r = run_resolver("resolve", "acpi")
        assert r["enabled_features"] == ["acpi"]
        assert r["activated_deps"] == {}

    def test_feature_chain_smp_to_acpi(self):
        r = run_resolver("resolve", "smp")
        assert r["enabled_features"] == ["acpi", "smp"]
        assert r["activated_deps"] == {}

    def test_dep_activation_tcp(self):
        r = run_resolver("resolve", "tcp")
        assert r["enabled_features"] == ["net", "tcp"]
        assert r["activated_deps"] == {
            "smoltcp": ["alloc", "medium-ethernet", "proto-ipv4", "socket-tcp"]
        }

    def test_pci_alone_no_deps(self):
        r = run_resolver("resolve", "pci")
        assert r["enabled_features"] == ["pci"]
        assert r["activated_deps"] == {}

    def test_shell_dep_activation(self):
        r = run_resolver("resolve", "shell")
        assert r["enabled_features"] == ["shell"]
        assert r["activated_deps"] == {"simple-shell": []}


class TestResolveNameCollision:
    """Feature and optional dep sharing the same name."""

    def test_virtio_feature_activates_virtio_dep(self):
        r = run_resolver("resolve", "virtio")
        assert r["enabled_features"] == ["virtio"]
        assert r["activated_deps"] == {
            "mem-barrier": [],
            "virtio": ["alloc", "mmio"],
        }

    def test_console_alias_activates_virtio_dep(self):
        r = run_resolver("resolve", "console")
        assert r["enabled_features"] == ["console", "virtio", "virtio-console"]
        assert r["activated_deps"] == {
            "mem-barrier": [],
            "virtio": ["alloc", "mmio"],
        }


class TestResolveAccumulation:
    """Multiple features accumulating features on the same dep."""

    def test_shared_dep_accumulates_features(self):
        r = run_resolver("resolve", "tcp,udp,dhcpv4")
        assert r["enabled_features"] == ["dhcpv4", "net", "tcp", "udp"]
        assert r["activated_deps"] == {
            "smoltcp": [
                "alloc",
                "medium-ethernet",
                "proto-dhcpv4",
                "proto-ipv4",
                "socket-dhcpv4",
                "socket-tcp",
                "socket-udp",
            ]
        }


class TestResolveWeakDeps:
    """Weak dependency (X?/Y) resolution requiring fixpoint iteration."""

    def test_weak_dep_does_not_fire_when_target_inactive(self):
        """pci has virtio?/pci but virtio dep is not active from pci alone."""
        r = run_resolver("resolve", "pci")
        assert r["enabled_features"] == ["pci"]
        assert r["activated_deps"] == {}

    def test_weak_dep_fires_when_target_activated(self):
        """pci's virtio?/pci fires because virtio-net activates the virtio dep."""
        r = run_resolver("resolve", "pci,virtio-net")
        assert r["enabled_features"] == ["net", "pci", "virtio", "virtio-net"]
        assert r["activated_deps"]["virtio"] == ["alloc", "mmio", "pci"]
        assert r["activated_deps"]["mem-barrier"] == []

    def test_cascading_weak_deps_write_pcap_tcp(self):
        """tcp activates smoltcp, write-pcap enables net-trace.
        net-trace's smoltcp?/log and smoltcp?/verbose fire.
        write-pcap's smoltcp?/pcap fires."""
        r = run_resolver("resolve", "write-pcap,tcp")
        assert r["enabled_features"] == ["net", "net-trace", "tcp", "write-pcap"]
        smoltcp_feats = r["activated_deps"]["smoltcp"]
        assert "log" in smoltcp_feats
        assert "verbose" in smoltcp_feats
        assert "pcap" in smoltcp_feats
        assert "socket-tcp" in smoltcp_feats
        assert "alloc" in smoltcp_feats

    def test_weak_deps_fire_via_trace_alias(self):
        """trace alias -> net-trace, combined with tcp activating smoltcp."""
        r = run_resolver("resolve", "trace,tcp")
        assert r["enabled_features"] == ["net", "net-trace", "tcp", "trace"]
        smoltcp_feats = r["activated_deps"]["smoltcp"]
        assert "log" in smoltcp_feats
        assert "verbose" in smoltcp_feats
        assert "socket-tcp" in smoltcp_feats

    def test_weak_deps_net_trace_udp(self):
        """net-trace's weak smoltcp?/log and smoltcp?/verbose fire
        because udp activates smoltcp."""
        r = run_resolver("resolve", "net-trace,udp")
        assert r["enabled_features"] == ["net", "net-trace", "udp"]
        smoltcp_feats = r["activated_deps"]["smoltcp"]
        assert "log" in smoltcp_feats
        assert "verbose" in smoltcp_feats
        assert "socket-udp" in smoltcp_feats
        assert "alloc" in smoltcp_feats

    def test_cross_feature_weak_dep_interaction(self):
        """rtl8139 enables pci, virtio-fs enables virtio dep.
        pci's virtio?/pci should fire because virtio dep is now active."""
        r = run_resolver("resolve", "rtl8139,virtio-fs")
        assert r["enabled_features"] == [
            "net", "pci", "rtl8139", "virtio", "virtio-fs"
        ]
        assert r["activated_deps"]["virtio"] == ["alloc", "mmio", "pci"]
        assert "fuse-abi" in r["activated_deps"]
        assert "mem-barrier" in r["activated_deps"]
        assert "volatile" in r["activated_deps"]
        assert "endian-num" in r["activated_deps"]


class TestResolveDefault:
    """Resolution of the 'default' meta-feature."""

    def test_default_feature_set(self):
        r = run_resolver("resolve", "default")
        expected_features = [
            "acpi", "default", "dhcpv4", "fsgsbase", "net", "pci",
            "pci-ids", "smp", "tcp", "virtio", "virtio-fs",
            "virtio-net", "virtio-vsock",
        ]
        assert r["enabled_features"] == expected_features

    def test_default_activates_smoltcp_correctly(self):
        r = run_resolver("resolve", "default")
        smoltcp_feats = r["activated_deps"]["smoltcp"]
        assert "socket-tcp" in smoltcp_feats
        assert "proto-dhcpv4" in smoltcp_feats
        assert "socket-dhcpv4" in smoltcp_feats
        assert "alloc" in smoltcp_feats
        assert "medium-ethernet" in smoltcp_feats
        assert "proto-ipv4" in smoltcp_feats

    def test_default_virtio_gets_pci_via_weak_dep(self):
        r = run_resolver("resolve", "default")
        assert r["activated_deps"]["virtio"] == ["alloc", "mmio", "pci"]

    def test_default_activates_expected_deps(self):
        r = run_resolver("resolve", "default")
        assert "fuse-abi" in r["activated_deps"]
        assert "mem-barrier" in r["activated_deps"]
        assert "pci-ids-db" in r["activated_deps"]
        assert "smoltcp" in r["activated_deps"]
        assert "virtio" in r["activated_deps"]


# ---------------------------------------------------------------------------
# trace command tests
# ---------------------------------------------------------------------------


class TestTrace:
    """Activation chain tracing for optional dependencies."""

    def test_trace_tcp_smoltcp(self):
        r = run_resolver("trace", "tcp", "smoltcp")
        assert r["dep"] == "smoltcp"
        assert r["activated"] is True
        assert r["features_on_dep"] == [
            "alloc", "medium-ethernet", "proto-ipv4", "socket-tcp"
        ]
        chain = r["activation_chain"]
        assert len(chain) == 2
        assert chain[0] == {
            "source_feature": "tcp", "entry": "dep:smoltcp", "type": "direct"
        }
        assert chain[1] == {
            "source_feature": "tcp", "entry": "smoltcp/socket-tcp", "type": "strong"
        }

    def test_trace_write_pcap_tcp_smoltcp(self):
        r = run_resolver("trace", "tcp,write-pcap", "smoltcp")
        assert r["activated"] is True
        chain = r["activation_chain"]
        # net-trace's weak deps + tcp's direct + write-pcap's weak
        types = [(c["source_feature"], c["type"]) for c in chain]
        assert ("net-trace", "weak") in types
        assert ("tcp", "direct") in types
        assert ("tcp", "strong") in types
        assert ("write-pcap", "weak") in types
        # Verify sorting
        keys = [(c["source_feature"], c["entry"]) for c in chain]
        assert keys == sorted(keys)

    def test_trace_pci_virtio_net_virtio(self):
        r = run_resolver("trace", "pci,virtio-net", "virtio")
        assert r["activated"] is True
        assert r["features_on_dep"] == ["alloc", "mmio", "pci"]
        chain = r["activation_chain"]
        assert {"source_feature": "pci", "entry": "virtio?/pci", "type": "weak"} in chain
        assert {"source_feature": "virtio", "entry": "dep:virtio", "type": "direct"} in chain

    def test_trace_inactive_dep(self):
        r = run_resolver("trace", "pci", "smoltcp")
        assert r["dep"] == "smoltcp"
        assert r["activated"] is False
        assert r["features_on_dep"] == []
        assert r["activation_chain"] == []

    def test_trace_default_smoltcp(self):
        r = run_resolver("trace", "default", "smoltcp")
        assert r["activated"] is True
        chain = r["activation_chain"]
        sources = {c["source_feature"] for c in chain}
        assert "dhcpv4" in sources
        assert "tcp" in sources

    def test_trace_default_virtio(self):
        r = run_resolver("trace", "default", "virtio")
        assert r["activated"] is True
        assert r["features_on_dep"] == ["alloc", "mmio", "pci"]
        chain = r["activation_chain"]
        assert {"source_feature": "pci", "entry": "virtio?/pci", "type": "weak"} in chain
        assert {"source_feature": "virtio", "entry": "dep:virtio", "type": "direct"} in chain


# ---------------------------------------------------------------------------
# impact command tests
# ---------------------------------------------------------------------------


class TestImpact:
    """Single-feature impact analysis with exclusive dep detection."""

    def test_impact_shell_exclusive_dep(self):
        """shell activates simple-shell, which no other feature does."""
        r = run_resolver("impact", "shell")
        assert r["feature"] == "shell"
        assert r["enabled_features"] == ["shell"]
        assert r["activated_deps"] == {"simple-shell": []}
        assert r["weak_deps_fired"] == []
        assert r["exclusive_deps"] == ["simple-shell"]

    def test_impact_tcp_no_exclusive(self):
        """tcp activates smoltcp, but udp/dhcpv4/dns also do."""
        r = run_resolver("impact", "tcp")
        assert r["enabled_features"] == ["net", "tcp"]
        assert "smoltcp" in r["activated_deps"]
        assert r["weak_deps_fired"] == []
        assert r["exclusive_deps"] == []

    def test_impact_rtl8139_exclusive_volatile_endian(self):
        """rtl8139 is the only feature activating volatile and endian-num."""
        r = run_resolver("impact", "rtl8139")
        assert r["enabled_features"] == ["net", "pci", "rtl8139"]
        assert r["activated_deps"] == {"endian-num": [], "volatile": []}
        assert r["weak_deps_fired"] == []
        assert r["exclusive_deps"] == ["endian-num", "volatile"]

    def test_impact_gem_net_exclusive_tock(self):
        """gem-net is the only feature activating tock-registers."""
        r = run_resolver("impact", "gem-net")
        assert r["enabled_features"] == ["gem-net", "net"]
        assert r["activated_deps"] == {"tock-registers": []}
        assert r["exclusive_deps"] == ["tock-registers"]

    def test_impact_pci_no_deps_activated(self):
        """pci only has a weak dep (virtio?/pci) which doesn't fire alone."""
        r = run_resolver("impact", "pci")
        assert r["enabled_features"] == ["pci"]
        assert r["activated_deps"] == {}
        assert r["weak_deps_fired"] == []
        assert r["exclusive_deps"] == []

    def test_impact_default_weak_dep_fires(self):
        """default's resolution activates both pci and virtio dep,
        so pci's virtio?/pci weak dep fires."""
        r = run_resolver("impact", "default")
        assert r["enabled_features"] == [
            "acpi", "default", "dhcpv4", "fsgsbase", "net", "pci",
            "pci-ids", "smp", "tcp", "virtio", "virtio-fs",
            "virtio-net", "virtio-vsock",
        ]
        assert r["weak_deps_fired"] == [
            {"source_feature": "pci", "dep": "virtio", "dep_feature": "pci"}
        ]
        # Every dep activated by default is also activated by some other feature
        assert r["exclusive_deps"] == []


# ---------------------------------------------------------------------------
# jq dep analysis tests
# ---------------------------------------------------------------------------


class TestDepAnalysis:
    """Verify jq-produced dependency analysis cross-references metadata."""

    def test_structure_and_count(self):
        """dep_analysis.json has all 9 optional deps, sorted by name."""
        with open("/app/dep_analysis.json") as f:
            data = json.load(f)
        assert "optional_deps" in data
        assert len(data["optional_deps"]) == 9
        names = [d["name"] for d in data["optional_deps"]]
        assert names == sorted(names)

    def test_smoltcp_cross_reference(self):
        """smoltcp: defaults from metadata, activated by tcp/udp/dhcpv4/dns,
        weak-referenced by net-trace/write-pcap."""
        with open("/app/dep_analysis.json") as f:
            data = json.load(f)
        by_name = {d["name"]: d for d in data["optional_deps"]}
        s = by_name["smoltcp"]
        assert s["default_features"] == ["alloc", "medium-ethernet", "proto-ipv4"]
        assert s["activating_features"] == ["dhcpv4", "dns", "tcp", "udp"]
        assert s["weak_referencing_features"] == ["net-trace", "write-pcap"]

    def test_virtio_cross_reference(self):
        """virtio: defaults from metadata, activated only by virtio feature,
        weak-referenced by pci."""
        with open("/app/dep_analysis.json") as f:
            data = json.load(f)
        by_name = {d["name"]: d for d in data["optional_deps"]}
        v = by_name["virtio"]
        assert v["default_features"] == ["alloc", "mmio"]
        assert v["activating_features"] == ["virtio"]
        assert v["weak_referencing_features"] == ["pci"]


# ---------------------------------------------------------------------------
# graphviz feature graph tests
# ---------------------------------------------------------------------------


class TestFeatureGraph:
    """Verify DOT graph structure and SVG rendering."""

    def test_dot_file_valid_digraph(self):
        """DOT file exists and declares a digraph."""
        assert os.path.exists("/app/feature_graph.dot")
        with open("/app/feature_graph.dot") as f:
            content = f.read()
        assert "digraph" in content
        assert content.count("{") >= 1
        assert content.count("}") >= 1

    def test_svg_rendered(self):
        """SVG file was produced by graphviz dot."""
        assert os.path.exists("/app/feature_graph.svg")
        with open("/app/feature_graph.svg") as f:
            content = f.read()
        assert "<svg" in content

    def test_dot_node_shapes(self):
        """Features use box shape, deps use ellipse shape."""
        with open("/app/feature_graph.dot") as f:
            content = f.read()
        assert re.search(r'shape\s*=\s*"?box"?', content), \
            "Missing box-shaped feature nodes"
        assert re.search(r'shape\s*=\s*"?ellipse"?', content), \
            "Missing ellipse-shaped dep nodes"

    def test_dot_edge_styles(self):
        """Graph uses dashed (strong dep) and dotted (weak dep) edge styles."""
        with open("/app/feature_graph.dot") as f:
            content = f.read()
        assert "dashed" in content, "Missing dashed edges for strong dep activation"
        assert "dotted" in content, "Missing dotted edges for weak dep references"
