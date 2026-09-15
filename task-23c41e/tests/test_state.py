
import json
import os
import pytest

AUDIT_PATH = "/app/audit.json"

# ─── Expected cross_crate_closures ───

EXPECTED_CLOSURES = {
    "q1": {
        "root_features": ["acpi", "net", "smp", "tcp"],
        "resolved_deps": {"netstack": ["alloc", "async", "socket-tcp"]},
    },
    "q2": {
        "root_features": ["fuse", "net", "net-trace", "udp", "virtio", "virtio-fs"],
        "resolved_deps": {
            "fuse-abi": ["linux", "std"],
            "mem-barrier": [],
            "netstack": ["alloc", "async", "log", "socket-udp", "verbose"],
            "virtio-hal": ["alloc"],
        },
    },
    "q3": {
        "root_features": [
            "acpi", "default", "dhcpv4", "fsgsbase", "kernel-stack",
            "net", "pci", "smp", "tcp", "virtio", "virtio-fs", "virtio-net",
        ],
        "resolved_deps": {
            "fuse-abi": ["linux", "std"],
            "mem-barrier": [],
            "netstack": ["alloc", "async", "proto-dhcpv4", "socket-dhcpv4", "socket-tcp"],
            "virtio-hal": ["alloc", "io", "pci-transport"],
        },
    },
    "q4": {
        "root_features": ["net-trace", "pci"],
        "resolved_deps": {},
    },
    "q5": {
        "root_features": ["dns", "net", "pci", "rtl8139", "virtio", "virtio-console"],
        "resolved_deps": {
            "mem-barrier": [],
            "netstack": ["socket-dns"],
            "virtio-hal": ["alloc", "io", "pci-transport"],
        },
    },
    "q6": {
        "root_features": [
            "console", "mman", "mmap", "virtio",
            "virtio-console", "virtio-vsock", "vsock",
        ],
        "resolved_deps": {
            "mem-barrier": [],
            "virtio-hal": ["alloc"],
        },
    },
    "q7": {
        "root_features": ["net", "net-trace", "pci", "tcp", "virtio", "virtio-net"],
        "resolved_deps": {
            "mem-barrier": [],
            "netstack": ["alloc", "async", "log", "socket-tcp", "verbose"],
            "virtio-hal": ["alloc", "io", "pci-transport"],
        },
    },
    "q8": {
        "root_features": ["dhcpv4", "dns", "net", "udp", "virtio", "virtio-net"],
        "resolved_deps": {
            "mem-barrier": [],
            "netstack": [
                "alloc", "async", "proto-dhcpv4",
                "socket-dhcpv4", "socket-dns", "socket-udp",
            ],
            "virtio-hal": ["alloc"],
        },
    },
    "q9": {
        "root_features": ["net-trace", "virtio", "virtio-console", "virtio-fs"],
        "resolved_deps": {
            "fuse-abi": ["linux", "std"],
            "mem-barrier": [],
            "virtio-hal": ["alloc"],
        },
    },
    "q10": {
        "root_features": [
            "acpi", "kernel-stack", "net", "net-trace",
            "smp", "tcp", "virtio", "virtio-net", "write-pcap-file",
        ],
        "resolved_deps": {
            "mem-barrier": [],
            "netstack": ["alloc", "async", "log", "socket-tcp", "verbose"],
            "virtio-hal": ["alloc"],
        },
    },
}

# ─── Expected minimum_activators ───

EXPECTED_MIN_ACTIVATORS = {
    "t1": "udp",
    "t2": "dns",
    "t3": "default",
    "t4": "console",
    "t5": None,
}

# ─── Expected conditional_analysis ───
# Sorted by (parent_feature, expression)

EXPECTED_CONDITIONALS = [
    {
        "expression": "netstack?/proto-dhcpv4",
        "parent_feature": "dhcpv4",
        "always_fires": True,
        "trigger_features": ["default", "dhcpv4", "dns", "tcp", "udp"],
    },
    {
        "expression": "netstack?/socket-dhcpv4",
        "parent_feature": "dhcpv4",
        "always_fires": True,
        "trigger_features": ["default", "dhcpv4", "dns", "tcp", "udp"],
    },
    {
        "expression": "netstack?/socket-dns",
        "parent_feature": "dns",
        "always_fires": True,
        "trigger_features": ["default", "dhcpv4", "dns", "tcp", "udp"],
    },
    {
        "expression": "netstack?/log",
        "parent_feature": "net-trace",
        "always_fires": False,
        "trigger_features": ["default", "dhcpv4", "dns", "tcp", "udp"],
    },
    {
        "expression": "netstack?/verbose",
        "parent_feature": "net-trace",
        "always_fires": False,
        "trigger_features": ["default", "dhcpv4", "dns", "tcp", "udp"],
    },
    {
        "expression": "virtio-hal?/pci-transport",
        "parent_feature": "pci",
        "always_fires": False,
        "trigger_features": [
            "console", "default", "fs", "fuse", "virtio",
            "virtio-console", "virtio-fs", "virtio-net",
            "virtio-vsock", "vsock",
        ],
    },
    {
        "expression": "netstack?/socket-tcp",
        "parent_feature": "tcp",
        "always_fires": True,
        "trigger_features": ["default", "dhcpv4", "dns", "tcp", "udp"],
    },
    {
        "expression": "netstack?/socket-udp",
        "parent_feature": "udp",
        "always_fires": True,
        "trigger_features": ["default", "dhcpv4", "dns", "tcp", "udp"],
    },
    {
        "expression": "virtio-hal?/alloc",
        "parent_feature": "virtio",
        "always_fires": True,
        "trigger_features": [
            "console", "default", "fs", "fuse", "virtio",
            "virtio-console", "virtio-fs", "virtio-net",
            "virtio-vsock", "vsock",
        ],
    },
    {
        "expression": "fuse-abi?/linux",
        "parent_feature": "virtio-fs",
        "always_fires": True,
        "trigger_features": ["default", "fs", "fuse", "virtio-fs"],
    },
]

# ─── Expected dominance_pairs ───

EXPECTED_DOMINANCE = [
    ["kernel-stack", "acpi"],
    ["kernel-stack", "smp"],
    ["rtl8139", "pci"],
    ["smp", "acpi"],
    ["write-pcap-file", "net-trace"],
]


@pytest.fixture(scope="module")
def audit():
    assert os.path.exists(AUDIT_PATH), f"Audit file not found at {AUDIT_PATH}"
    with open(AUDIT_PATH) as f:
        return json.load(f)


# ═══════════════════════════════════════════
#  Section 1: cross_crate_closures
# ═══════════════════════════════════════════

class TestClosuresStructure:
    def test_section_exists(self, audit):
        assert "cross_crate_closures" in audit

    def test_all_query_ids_present(self, audit):
        closures = audit["cross_crate_closures"]
        for qid in EXPECTED_CLOSURES:
            assert qid in closures, f"Missing closure for {qid}"


class TestClosureQ1:
    """tcp + smp: basic dep activation and conditional forwarding with sub-crate chain."""

    def test_root_features(self, audit):
        actual = sorted(audit["cross_crate_closures"]["q1"]["root_features"])
        assert actual == EXPECTED_CLOSURES["q1"]["root_features"]

    def test_resolved_deps(self, audit):
        actual = audit["cross_crate_closures"]["q1"]["resolved_deps"]
        expected = EXPECTED_CLOSURES["q1"]["resolved_deps"]
        assert set(actual.keys()) == set(expected.keys())
        for dep in expected:
            assert sorted(actual[dep]) == expected[dep], f"q1 dep {dep} mismatch"


class TestClosureQ2:
    """fuse + udp + net-trace: alias chain, multiple deps, sub-crate feature chains."""

    def test_root_features(self, audit):
        actual = sorted(audit["cross_crate_closures"]["q2"]["root_features"])
        assert actual == EXPECTED_CLOSURES["q2"]["root_features"]

    def test_resolved_deps_keys(self, audit):
        actual = audit["cross_crate_closures"]["q2"]["resolved_deps"]
        expected = EXPECTED_CLOSURES["q2"]["resolved_deps"]
        assert set(actual.keys()) == set(expected.keys())

    def test_netstack_features(self, audit):
        actual = sorted(audit["cross_crate_closures"]["q2"]["resolved_deps"]["netstack"])
        assert actual == ["alloc", "async", "log", "socket-udp", "verbose"]

    def test_fuse_abi_features(self, audit):
        actual = sorted(audit["cross_crate_closures"]["q2"]["resolved_deps"]["fuse-abi"])
        assert actual == ["linux", "std"]

    def test_virtio_hal_features(self, audit):
        actual = sorted(audit["cross_crate_closures"]["q2"]["resolved_deps"]["virtio-hal"])
        assert actual == ["alloc"]

    def test_mem_barrier_empty(self, audit):
        actual = audit["cross_crate_closures"]["q2"]["resolved_deps"]["mem-barrier"]
        assert actual == []


class TestClosureQ3:
    """Default features: comprehensive cross-crate resolution."""

    def test_root_features(self, audit):
        actual = sorted(audit["cross_crate_closures"]["q3"]["root_features"])
        assert actual == EXPECTED_CLOSURES["q3"]["root_features"]

    def test_default_in_features(self, audit):
        assert "default" in audit["cross_crate_closures"]["q3"]["root_features"]

    def test_resolved_deps(self, audit):
        actual = audit["cross_crate_closures"]["q3"]["resolved_deps"]
        expected = EXPECTED_CLOSURES["q3"]["resolved_deps"]
        assert set(actual.keys()) == set(expected.keys())
        for dep in expected:
            assert sorted(actual[dep]) == expected[dep], f"q3 dep {dep} mismatch"

    def test_virtio_hal_has_pci_transport(self, audit):
        vh = audit["cross_crate_closures"]["q3"]["resolved_deps"]["virtio-hal"]
        assert "pci-transport" in vh
        assert "io" in vh


class TestClosureQ4:
    """pci + net-trace: conditionals must NOT fire when deps are not enabled."""

    def test_root_features(self, audit):
        actual = sorted(audit["cross_crate_closures"]["q4"]["root_features"])
        assert actual == ["net-trace", "pci"]

    def test_no_resolved_deps(self, audit):
        actual = audit["cross_crate_closures"]["q4"]["resolved_deps"]
        assert actual == {} or actual == []


class TestClosureQ5:
    """rtl8139 + dns + virtio-console: order-independent cross-crate resolution."""

    def test_root_features(self, audit):
        actual = sorted(audit["cross_crate_closures"]["q5"]["root_features"])
        assert actual == EXPECTED_CLOSURES["q5"]["root_features"]

    def test_virtio_hal_pci_transport(self, audit):
        vh = audit["cross_crate_closures"]["q5"]["resolved_deps"]["virtio-hal"]
        assert "pci-transport" in vh, "pci's conditional on virtio-hal must fire"
        assert "io" in vh, "pci-transport must chain to io within virtio-hal"

    def test_netstack_socket_dns(self, audit):
        ns = audit["cross_crate_closures"]["q5"]["resolved_deps"]["netstack"]
        assert "socket-dns" in ns

    def test_resolved_deps(self, audit):
        actual = audit["cross_crate_closures"]["q5"]["resolved_deps"]
        expected = EXPECTED_CLOSURES["q5"]["resolved_deps"]
        assert set(actual.keys()) == set(expected.keys())
        for dep in expected:
            assert sorted(actual[dep]) == expected[dep], f"q5 dep {dep} mismatch"


class TestClosureQ6:
    """console + vsock + mmap: deprecated aliases with no dep-feature forwarding."""

    def test_root_features(self, audit):
        actual = sorted(audit["cross_crate_closures"]["q6"]["root_features"])
        assert actual == EXPECTED_CLOSURES["q6"]["root_features"]

    def test_resolved_deps(self, audit):
        actual = audit["cross_crate_closures"]["q6"]["resolved_deps"]
        expected = EXPECTED_CLOSURES["q6"]["resolved_deps"]
        assert set(actual.keys()) == set(expected.keys())
        for dep in expected:
            assert sorted(actual[dep]) == expected[dep], f"q6 dep {dep} mismatch"


class TestClosureQ7:
    """tcp + virtio-net + net-trace + pci: all conditionals fire simultaneously."""

    def test_root_features(self, audit):
        actual = sorted(audit["cross_crate_closures"]["q7"]["root_features"])
        assert actual == EXPECTED_CLOSURES["q7"]["root_features"]

    def test_resolved_deps(self, audit):
        actual = audit["cross_crate_closures"]["q7"]["resolved_deps"]
        expected = EXPECTED_CLOSURES["q7"]["resolved_deps"]
        assert set(actual.keys()) == set(expected.keys())
        for dep in expected:
            assert sorted(actual[dep]) == expected[dep], f"q7 dep {dep} mismatch"


class TestClosureQ8:
    """dhcpv4 + dns + udp + virtio-net: multiple network protocols with sub-crate chains."""

    def test_root_features(self, audit):
        actual = sorted(audit["cross_crate_closures"]["q8"]["root_features"])
        assert actual == EXPECTED_CLOSURES["q8"]["root_features"]

    def test_netstack_has_all_protocols(self, audit):
        ns = sorted(audit["cross_crate_closures"]["q8"]["resolved_deps"]["netstack"])
        assert ns == [
            "alloc", "async", "proto-dhcpv4",
            "socket-dhcpv4", "socket-dns", "socket-udp",
        ]


class TestClosureQ9:
    """virtio-fs + virtio-console + net-trace: net-trace conditionals don't fire."""

    def test_root_features(self, audit):
        actual = sorted(audit["cross_crate_closures"]["q9"]["root_features"])
        assert actual == EXPECTED_CLOSURES["q9"]["root_features"]

    def test_no_netstack(self, audit):
        deps = audit["cross_crate_closures"]["q9"]["resolved_deps"]
        assert "netstack" not in deps

    def test_fuse_abi_present(self, audit):
        deps = audit["cross_crate_closures"]["q9"]["resolved_deps"]
        assert "fuse-abi" in deps
        assert sorted(deps["fuse-abi"]) == ["linux", "std"]


class TestClosureQ10:
    """kernel-stack + write-pcap-file + tcp + virtio-net: chained features + cross-activation."""

    def test_root_features(self, audit):
        actual = sorted(audit["cross_crate_closures"]["q10"]["root_features"])
        assert actual == EXPECTED_CLOSURES["q10"]["root_features"]

    def test_netstack_has_verbose(self, audit):
        ns = audit["cross_crate_closures"]["q10"]["resolved_deps"]["netstack"]
        assert "verbose" in ns, (
            "write-pcap-file enables net-trace; tcp enables netstack; "
            "net-trace's netstack?/verbose must fire"
        )
        assert "log" in ns, "verbose chains to log within netstack"

    def test_resolved_deps(self, audit):
        actual = audit["cross_crate_closures"]["q10"]["resolved_deps"]
        expected = EXPECTED_CLOSURES["q10"]["resolved_deps"]
        assert set(actual.keys()) == set(expected.keys())
        for dep in expected:
            assert sorted(actual[dep]) == expected[dep], f"q10 dep {dep} mismatch"


# ═══════════════════════════════════════════
#  Section 2: minimum_activators
# ═══════════════════════════════════════════

class TestMinimumActivators:
    def test_section_exists(self, audit):
        assert "minimum_activators" in audit

    def test_t1_netstack_socket_udp(self, audit):
        assert audit["minimum_activators"]["t1"] == "udp"

    def test_t2_netstack_socket_dns(self, audit):
        assert audit["minimum_activators"]["t2"] == "dns"

    def test_t3_virtio_hal_io(self, audit):
        assert audit["minimum_activators"]["t3"] == "default"

    def test_t4_virtio_hal_alloc(self, audit):
        assert audit["minimum_activators"]["t4"] == "console"

    def test_t5_netstack_verbose_null(self, audit):
        assert audit["minimum_activators"]["t5"] is None


# ═══════════════════════════════════════════
#  Section 3: conditional_analysis
# ═══════════════════════════════════════════

class TestConditionalAnalysis:
    def test_section_exists(self, audit):
        assert "conditional_analysis" in audit

    def test_correct_count(self, audit):
        assert len(audit["conditional_analysis"]) == 10

    def _find_conditional(self, audit, parent, expr):
        for c in audit["conditional_analysis"]:
            if c["parent_feature"] == parent and c["expression"] == expr:
                return c
        pytest.fail(f"Conditional {parent} -> {expr} not found")

    def test_pci_pci_transport_not_always_fires(self, audit):
        c = self._find_conditional(audit, "pci", "virtio-hal?/pci-transport")
        assert c["always_fires"] is False

    def test_pci_pci_transport_triggers(self, audit):
        c = self._find_conditional(audit, "pci", "virtio-hal?/pci-transport")
        assert sorted(c["trigger_features"]) == [
            "console", "default", "fs", "fuse", "virtio",
            "virtio-console", "virtio-fs", "virtio-net",
            "virtio-vsock", "vsock",
        ]

    def test_tcp_socket_tcp_always_fires(self, audit):
        c = self._find_conditional(audit, "tcp", "netstack?/socket-tcp")
        assert c["always_fires"] is True

    def test_tcp_socket_tcp_triggers(self, audit):
        c = self._find_conditional(audit, "tcp", "netstack?/socket-tcp")
        assert sorted(c["trigger_features"]) == [
            "default", "dhcpv4", "dns", "tcp", "udp",
        ]

    def test_net_trace_log_not_always_fires(self, audit):
        c = self._find_conditional(audit, "net-trace", "netstack?/log")
        assert c["always_fires"] is False

    def test_net_trace_verbose_not_always_fires(self, audit):
        c = self._find_conditional(audit, "net-trace", "netstack?/verbose")
        assert c["always_fires"] is False

    def test_net_trace_log_triggers(self, audit):
        c = self._find_conditional(audit, "net-trace", "netstack?/log")
        assert sorted(c["trigger_features"]) == [
            "default", "dhcpv4", "dns", "tcp", "udp",
        ]

    def test_virtio_alloc_always_fires(self, audit):
        c = self._find_conditional(audit, "virtio", "virtio-hal?/alloc")
        assert c["always_fires"] is True

    def test_virtio_alloc_triggers(self, audit):
        c = self._find_conditional(audit, "virtio", "virtio-hal?/alloc")
        assert sorted(c["trigger_features"]) == [
            "console", "default", "fs", "fuse", "virtio",
            "virtio-console", "virtio-fs", "virtio-net",
            "virtio-vsock", "vsock",
        ]

    def test_virtio_fs_linux_always_fires(self, audit):
        c = self._find_conditional(audit, "virtio-fs", "fuse-abi?/linux")
        assert c["always_fires"] is True

    def test_virtio_fs_linux_triggers(self, audit):
        c = self._find_conditional(audit, "virtio-fs", "fuse-abi?/linux")
        assert sorted(c["trigger_features"]) == [
            "default", "fs", "fuse", "virtio-fs",
        ]

    def test_dhcpv4_conditionals(self, audit):
        for expr in ["netstack?/proto-dhcpv4", "netstack?/socket-dhcpv4"]:
            c = self._find_conditional(audit, "dhcpv4", expr)
            assert c["always_fires"] is True, f"{expr} should always fire"
            assert sorted(c["trigger_features"]) == [
                "default", "dhcpv4", "dns", "tcp", "udp",
            ]

    def test_udp_socket_udp_always_fires(self, audit):
        c = self._find_conditional(audit, "udp", "netstack?/socket-udp")
        assert c["always_fires"] is True

    def test_dns_socket_dns_always_fires(self, audit):
        c = self._find_conditional(audit, "dns", "netstack?/socket-dns")
        assert c["always_fires"] is True


# ═══════════════════════════════════════════
#  Section 4: dominance_pairs
# ═══════════════════════════════════════════

class TestDominancePairs:
    def test_section_exists(self, audit):
        assert "dominance_pairs" in audit

    def test_exact_pairs(self, audit):
        actual = sorted([sorted(p) for p in audit["dominance_pairs"]])
        # Sort each pair internally then sort the list
        expected = sorted([sorted(p) for p in EXPECTED_DOMINANCE])
        # But dominance is directed: [A, B] means A dominates B
        # Check the directed pairs
        actual_directed = sorted(
            [list(p) for p in audit["dominance_pairs"]]
        )
        assert actual_directed == EXPECTED_DOMINANCE

    def test_smp_dominates_acpi(self, audit):
        assert ["smp", "acpi"] in audit["dominance_pairs"]

    def test_kernel_stack_dominates_smp(self, audit):
        assert ["kernel-stack", "smp"] in audit["dominance_pairs"]

    def test_kernel_stack_dominates_acpi(self, audit):
        assert ["kernel-stack", "acpi"] in audit["dominance_pairs"]

    def test_rtl8139_dominates_pci(self, audit):
        assert ["rtl8139", "pci"] in audit["dominance_pairs"]

    def test_write_pcap_dominates_net_trace(self, audit):
        assert ["write-pcap-file", "net-trace"] in audit["dominance_pairs"]

    def test_no_extra_pairs(self, audit):
        assert len(audit["dominance_pairs"]) == 5
