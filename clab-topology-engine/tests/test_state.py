
import json
import subprocess

import yaml


def run_federator(args):
    """Run the clab_federator.py CLI tool and return the result."""
    result = subprocess.run(
        ["python3", "/app/clab_federator.py"] + args,
        capture_output=True,
        text=True,
        cwd="/app",
    )
    return result


# ---------------------------------------------------------------------------
# check: full federation feasibility
# ---------------------------------------------------------------------------


class TestCheckFull:
    """Full 3-pod federation feasibility check."""

    def test_feasible(self):
        r = run_federator(["check", "/app/federation_specs/full.federation.yml"])
        assert r.returncode == 0, r.stderr
        report = json.loads(r.stdout)
        assert report["feasible"] is True

    def test_no_errors(self):
        r = run_federator(["check", "/app/federation_specs/full.federation.yml"])
        report = json.loads(r.stdout)
        assert len(report["errors"]) == 0

    def test_pod_subnets(self):
        r = run_federator(["check", "/app/federation_specs/full.federation.yml"])
        report = json.loads(r.stdout)
        assert report["pod_subnets"]["east"] == "10.100.0.0/24"
        assert report["pod_subnets"]["west"] == "10.100.1.0/24"
        assert report["pod_subnets"]["edge"] == "10.100.2.0/24"

    def test_naming_conflicts(self):
        r = run_federator(["check", "/app/federation_specs/full.federation.yml"])
        report = json.loads(r.stdout)
        conflicts = report["naming_conflicts"]
        conflict_names = [c["name"] for c in conflicts]
        assert "spine1" in conflict_names
        assert "spine2" in conflict_names
        assert "leaf1" in conflict_names
        assert "leaf2" in conflict_names
        assert "server1" in conflict_names
        assert len(conflicts) == 5

    def test_naming_conflict_pods(self):
        r = run_federator(["check", "/app/federation_specs/full.federation.yml"])
        report = json.loads(r.stdout)
        conflicts = report["naming_conflicts"]
        for c in conflicts:
            assert set(c["pods"]) == {"east", "west"}

    def test_border_link_count(self):
        r = run_federator(["check", "/app/federation_specs/full.federation.yml"])
        report = json.loads(r.stdout)
        # 2*2 (east-west) + 2*1 (east-edge) + 2*1 (west-edge) = 8
        assert report["border_link_count"] == 8

    def test_total_node_count(self):
        r = run_federator(["check", "/app/federation_specs/full.federation.yml"])
        report = json.loads(r.stdout)
        assert report["total_node_count"] == 15


# ---------------------------------------------------------------------------
# check: infeasible federation
# ---------------------------------------------------------------------------


class TestCheckInfeasible:
    """Infeasible federation detection."""

    def test_not_feasible(self):
        r = run_federator(
            ["check", "/app/federation_specs/infeasible.federation.yml"]
        )
        assert r.returncode == 0, r.stderr
        report = json.loads(r.stdout)
        assert report["feasible"] is False

    def test_error_mentions_west(self):
        r = run_federator(
            ["check", "/app/federation_specs/infeasible.federation.yml"]
        )
        report = json.loads(r.stdout)
        errors_text = " ".join(report["errors"]).lower()
        assert "west" in errors_text

    def test_error_mentions_capacity(self):
        r = run_federator(
            ["check", "/app/federation_specs/infeasible.federation.yml"]
        )
        report = json.loads(r.stdout)
        errors_text = " ".join(report["errors"]).lower()
        assert "7" in errors_text or "nodes" in errors_text
        assert "5" in errors_text or "usable" in errors_text

    def test_pod_subnets_still_assigned(self):
        r = run_federator(
            ["check", "/app/federation_specs/infeasible.federation.yml"]
        )
        report = json.loads(r.stdout)
        assert "east" in report["pod_subnets"]
        assert "west" in report["pod_subnets"]


# ---------------------------------------------------------------------------
# allocate-ips: full federation
# ---------------------------------------------------------------------------


class TestIPAllocationFull:
    """IP allocation for full 3-pod federation."""

    def test_east_pod_ips(self):
        r = run_federator(
            ["allocate-ips", "/app/federation_specs/full.federation.yml"]
        )
        assert r.returncode == 0, r.stderr
        data = json.loads(r.stdout)
        assert data["east-leaf1"] == "10.100.0.2"
        assert data["east-leaf2"] == "10.100.0.3"
        assert data["east-server1"] == "10.100.0.4"
        assert data["east-spine1"] == "10.100.0.5"
        assert data["east-spine2"] == "10.100.0.6"

    def test_west_pod_ips(self):
        r = run_federator(
            ["allocate-ips", "/app/federation_specs/full.federation.yml"]
        )
        assert r.returncode == 0, r.stderr
        data = json.loads(r.stdout)
        assert data["west-leaf1"] == "10.100.1.2"
        assert data["west-leaf2"] == "10.100.1.3"
        assert data["west-leaf3"] == "10.100.1.4"
        assert data["west-server1"] == "10.100.1.5"
        assert data["west-server2"] == "10.100.1.6"
        assert data["west-spine1"] == "10.100.1.7"
        assert data["west-spine2"] == "10.100.1.8"

    def test_edge_pod_ips(self):
        r = run_federator(
            ["allocate-ips", "/app/federation_specs/full.federation.yml"]
        )
        assert r.returncode == 0, r.stderr
        data = json.loads(r.stdout)
        assert data["edge-firewall"] == "10.100.2.2"
        assert data["edge-router1"] == "10.100.2.3"
        assert data["edge-router2"] == "10.100.2.4"

    def test_all_ips_unique(self):
        r = run_federator(
            ["allocate-ips", "/app/federation_specs/full.federation.yml"]
        )
        data = json.loads(r.stdout)
        ips = list(data.values())
        assert len(ips) == len(set(ips)), f"Duplicate IPs found: {data}"

    def test_total_allocations(self):
        r = run_federator(
            ["allocate-ips", "/app/federation_specs/full.federation.yml"]
        )
        data = json.loads(r.stdout)
        assert len(data) == 15


# ---------------------------------------------------------------------------
# allocate-ips: simple federation
# ---------------------------------------------------------------------------


class TestIPAllocationSimple:
    """IP allocation for simple 2-pod federation."""

    def test_east_ips(self):
        r = run_federator(
            ["allocate-ips", "/app/federation_specs/simple.federation.yml"]
        )
        assert r.returncode == 0, r.stderr
        data = json.loads(r.stdout)
        assert data["east-spine1"] == "10.200.0.5"
        assert data["east-leaf1"] == "10.200.0.2"

    def test_west_ips(self):
        r = run_federator(
            ["allocate-ips", "/app/federation_specs/simple.federation.yml"]
        )
        data = json.loads(r.stdout)
        assert data["west-spine1"] == "10.200.1.7"
        assert data["west-leaf3"] == "10.200.1.4"

    def test_total_allocations(self):
        r = run_federator(
            ["allocate-ips", "/app/federation_specs/simple.federation.yml"]
        )
        data = json.loads(r.stdout)
        assert len(data) == 12


# ---------------------------------------------------------------------------
# allocate-ips: infeasible exits with error
# ---------------------------------------------------------------------------


class TestIPAllocationInfeasible:
    """Infeasible federation should fail gracefully."""

    def test_exits_nonzero(self):
        r = run_federator(
            ["allocate-ips", "/app/federation_specs/infeasible.federation.yml"]
        )
        assert r.returncode != 0


# ---------------------------------------------------------------------------
# federate: full federation merged topology
# ---------------------------------------------------------------------------


class TestFederateFull:
    """Merged topology for full 3-pod federation."""

    def setup_method(self):
        r = run_federator(
            ["federate", "/app/federation_specs/full.federation.yml"]
        )
        assert r.returncode == 0, r.stderr
        self.topo = yaml.safe_load(r.stdout)
        self.nodes = self.topo["topology"]["nodes"]
        self.links = self.topo["topology"]["links"]

    def test_federation_name(self):
        assert self.topo["name"] == "multi-dc"

    def test_mgmt_subnet(self):
        assert self.topo["mgmt"]["ipv4-subnet"] == "10.100.0.0/22"

    def test_node_count(self):
        assert len(self.nodes) == 15

    def test_prefixed_node_exists(self):
        assert "east-spine1" in self.nodes
        assert "west-leaf3" in self.nodes
        assert "edge-router1" in self.nodes

    def test_unprefixed_node_absent(self):
        assert "spine1" not in self.nodes
        assert "leaf1" not in self.nodes
        assert "router1" not in self.nodes

    def test_kind_resolved_through_group(self):
        """East spine1's kind should resolve to 'srl' via group->kind chain."""
        assert self.nodes["east-spine1"]["kind"] == "srl"
        assert self.nodes["east-spine2"]["kind"] == "srl"

    def test_kind_default_for_west(self):
        """West nodes should resolve to 'linux' (no kinds/groups in west)."""
        assert self.nodes["west-spine1"]["kind"] == "linux"
        assert self.nodes["west-leaf1"]["kind"] == "linux"

    def test_image_resolved_from_kind_def(self):
        """East spine1 should get srl kind's image."""
        assert self.nodes["east-spine1"]["image"] == "ghcr.io/nokia/srlinux"

    def test_image_default(self):
        assert self.nodes["east-leaf1"]["image"] == "alpine:latest"
        assert self.nodes["west-spine1"]["image"] == "alpine:latest"

    def test_env_resolved_from_kind(self):
        """East spine1 should have DISTRO=srlinux from srl kind definition."""
        assert self.nodes["east-spine1"]["env"]["DISTRO"] == "srlinux"

    def test_federation_label(self):
        assert (
            self.nodes["east-spine1"]["labels"]["clab-federation-pod"]
            == "east"
        )
        assert (
            self.nodes["west-leaf1"]["labels"]["clab-federation-pod"] == "west"
        )
        assert (
            self.nodes["edge-router1"]["labels"]["clab-federation-pod"]
            == "edge"
        )

    def test_mgmt_ipv4_assigned(self):
        assert self.nodes["east-spine1"]["mgmt-ipv4"] == "10.100.0.5"
        assert self.nodes["west-spine1"]["mgmt-ipv4"] == "10.100.1.7"
        assert self.nodes["edge-router1"]["mgmt-ipv4"] == "10.100.2.3"

    def test_total_links(self):
        # 5 east + 8 west + 3 edge internal + 8 border = 24
        assert len(self.links) == 24

    def test_internal_links_prefixed(self):
        """First link should be east's first internal link, prefixed."""
        eps = set(self.links[0]["endpoints"])
        assert eps == {"east-spine1:eth1", "east-leaf1:eth1"}

    def test_border_link_east_west_spines(self):
        """east-spine1:eth3 should connect to west-spine1:eth4."""
        found = False
        for link in self.links:
            eps = set(link["endpoints"])
            if eps == {"east-spine1:eth3", "west-spine1:eth4"}:
                found = True
                break
        assert found, "Missing east-spine1:eth3 <-> west-spine1:eth4 border link"

    def test_border_link_east_edge(self):
        """east-spine1:eth5 should connect to edge-router1:eth3."""
        found = False
        for link in self.links:
            eps = set(link["endpoints"])
            if eps == {"east-spine1:eth5", "edge-router1:eth3"}:
                found = True
                break
        assert found, "Missing east-spine1:eth5 <-> edge-router1:eth3 border link"

    def test_border_link_west_edge(self):
        """west-spine1:eth6 should connect to edge-router1:eth5."""
        found = False
        for link in self.links:
            eps = set(link["endpoints"])
            if eps == {"west-spine1:eth6", "edge-router1:eth5"}:
                found = True
                break
        assert found, "Missing west-spine1:eth6 <-> edge-router1:eth5 border link"

    def test_no_group_in_merged_nodes(self):
        """Group field should be removed from flat merged output."""
        for name, node in self.nodes.items():
            assert "group" not in node, f"{name} has 'group' field in merged output"

    def test_all_link_nodes_exist(self):
        """Every node referenced in a link must exist in nodes."""
        for link in self.links:
            for ep in link["endpoints"]:
                node = ep.split(":")[0]
                assert node in self.nodes, f"Link references unknown node: {node}"


# ---------------------------------------------------------------------------
# federate: simple federation
# ---------------------------------------------------------------------------


class TestFederateSimple:
    """Merged topology for simple 2-pod federation."""

    def setup_method(self):
        r = run_federator(
            ["federate", "/app/federation_specs/simple.federation.yml"]
        )
        assert r.returncode == 0, r.stderr
        self.topo = yaml.safe_load(r.stdout)

    def test_node_count(self):
        assert len(self.topo["topology"]["nodes"]) == 12

    def test_total_links(self):
        # 5 east + 8 west internal + 1 border = 14
        assert len(self.topo["topology"]["links"]) == 14

    def test_single_border_link(self):
        """east-spine1:eth3 should connect to west-spine1:eth4."""
        links = self.topo["topology"]["links"]
        found = False
        for link in links:
            eps = set(link["endpoints"])
            if eps == {"east-spine1:eth3", "west-spine1:eth4"}:
                found = True
                break
        assert found, "Missing border link east-spine1:eth3 <-> west-spine1:eth4"

    def test_federation_name(self):
        assert self.topo["name"] == "dual-dc"


# ---------------------------------------------------------------------------
# federate: infeasible exits with error
# ---------------------------------------------------------------------------


class TestFederateInfeasible:
    """Infeasible federation should fail gracefully."""

    def test_exits_nonzero(self):
        r = run_federator(
            ["federate", "/app/federation_specs/infeasible.federation.yml"]
        )
        assert r.returncode != 0

    def test_stderr_has_error(self):
        r = run_federator(
            ["federate", "/app/federation_specs/infeasible.federation.yml"]
        )
        assert len(r.stderr.strip()) > 0


# ---------------------------------------------------------------------------
# inventory: full federation
# ---------------------------------------------------------------------------


class TestInventoryFull:
    """Ansible inventory for full 3-pod federation."""

    def setup_method(self):
        r = run_federator(
            ["inventory", "/app/federation_specs/full.federation.yml"]
        )
        assert r.returncode == 0, r.stderr
        self.inv = yaml.safe_load(r.stdout)

    def test_srl_group_exists(self):
        assert "srl" in self.inv["all"]["children"]

    def test_linux_group_exists(self):
        assert "linux" in self.inv["all"]["children"]

    def test_srl_group_hosts(self):
        """East spines should be in srl group (kind resolved through group)."""
        srl_hosts = self.inv["all"]["children"]["srl"]["hosts"]
        assert "clab-multi-dc-east-spine1" in srl_hosts
        assert "clab-multi-dc-east-spine2" in srl_hosts

    def test_west_spines_in_linux(self):
        """West spines should be in linux group (no srl kind in west)."""
        linux_hosts = self.inv["all"]["children"]["linux"]["hosts"]
        assert "clab-multi-dc-west-spine1" in linux_hosts
        assert "clab-multi-dc-west-spine2" in linux_hosts

    def test_edge_in_linux(self):
        linux_hosts = self.inv["all"]["children"]["linux"]["hosts"]
        assert "clab-multi-dc-edge-router1" in linux_hosts
        assert "clab-multi-dc-edge-firewall" in linux_hosts

    def test_hostname_format(self):
        """Hostnames must follow clab-<fed-name>-<pod>-<node> pattern."""
        all_hosts = []
        for kind_data in self.inv["all"]["children"].values():
            all_hosts.extend(kind_data.get("hosts", {}).keys())
        for host in all_hosts:
            assert host.startswith("clab-multi-dc-"), f"Bad hostname: {host}"

    def test_srl_ansible_vars(self):
        srl = self.inv["all"]["children"]["srl"]
        assert "vars" in srl
        assert srl["vars"]["ansible_network_os"] == "nokia.srlinux.srlinux"
        assert srl["vars"]["ansible_connection"] == "ansible.netcommon.httpapi"
        assert srl["vars"]["ansible_user"] == "admin"
        assert srl["vars"]["ansible_password"] == "NokiaSrl1!"

    def test_linux_no_special_vars(self):
        linux = self.inv["all"]["children"]["linux"]
        if "vars" in linux:
            assert "ansible_network_os" not in linux["vars"]

    def test_ansible_host_ip(self):
        srl_hosts = self.inv["all"]["children"]["srl"]["hosts"]
        assert (
            srl_hosts["clab-multi-dc-east-spine1"]["ansible_host"]
            == "10.100.0.5"
        )

    def test_total_hosts(self):
        total = 0
        for kind_data in self.inv["all"]["children"].values():
            total += len(kind_data.get("hosts", {}))
        assert total == 15


# ---------------------------------------------------------------------------
# inventory: infeasible exits with error
# ---------------------------------------------------------------------------


class TestInventoryInfeasible:
    """Infeasible federation inventory should fail."""

    def test_exits_nonzero(self):
        r = run_federator(
            ["inventory", "/app/federation_specs/infeasible.federation.yml"]
        )
        assert r.returncode != 0


# ---------------------------------------------------------------------------
# check: simple federation
# ---------------------------------------------------------------------------


class TestCheckSimple:
    """Simple 2-pod federation check."""

    def test_feasible(self):
        r = run_federator(
            ["check", "/app/federation_specs/simple.federation.yml"]
        )
        assert r.returncode == 0, r.stderr
        report = json.loads(r.stdout)
        assert report["feasible"] is True

    def test_border_link_count(self):
        r = run_federator(
            ["check", "/app/federation_specs/simple.federation.yml"]
        )
        report = json.loads(r.stdout)
        assert report["border_link_count"] == 1

    def test_total_node_count(self):
        r = run_federator(
            ["check", "/app/federation_specs/simple.federation.yml"]
        )
        report = json.loads(r.stdout)
        assert report["total_node_count"] == 12


# ---------------------------------------------------------------------------
# check: advanced federation (exercises Go source edge cases)
# ---------------------------------------------------------------------------


class TestCheckAdvanced:
    """Advanced federation with complex property resolution."""

    def test_feasible(self):
        r = run_federator(
            ["check", "/app/federation_specs/advanced.federation.yml"]
        )
        assert r.returncode == 0, r.stderr
        report = json.loads(r.stdout)
        assert report["feasible"] is True

    def test_no_naming_conflicts(self):
        r = run_federator(
            ["check", "/app/federation_specs/advanced.federation.yml"]
        )
        report = json.loads(r.stdout)
        assert len(report["naming_conflicts"]) == 0

    def test_border_link_count(self):
        r = run_federator(
            ["check", "/app/federation_specs/advanced.federation.yml"]
        )
        report = json.loads(r.stdout)
        # 2 east border * 2 advanced border = 4
        assert report["border_link_count"] == 4

    def test_total_node_count(self):
        r = run_federator(
            ["check", "/app/federation_specs/advanced.federation.yml"]
        )
        report = json.loads(r.stdout)
        # 5 east + 6 advanced = 11
        assert report["total_node_count"] == 11


# ---------------------------------------------------------------------------
# allocate-ips: advanced federation
# ---------------------------------------------------------------------------


class TestIPAllocationAdvanced:
    """IP allocation for advanced federation."""

    def test_east_ips(self):
        r = run_federator(
            ["allocate-ips", "/app/federation_specs/advanced.federation.yml"]
        )
        assert r.returncode == 0, r.stderr
        data = json.loads(r.stdout)
        assert data["east-leaf1"] == "10.50.0.2"
        assert data["east-spine1"] == "10.50.0.5"

    def test_advanced_core_ips(self):
        r = run_federator(
            ["allocate-ips", "/app/federation_specs/advanced.federation.yml"]
        )
        data = json.loads(r.stdout)
        assert data["advanced-access1"] == "10.50.1.2"
        assert data["advanced-access2"] == "10.50.1.3"
        assert data["advanced-core1"] == "10.50.1.4"
        assert data["advanced-core2"] == "10.50.1.5"
        assert data["advanced-distrib1"] == "10.50.1.6"
        assert data["advanced-distrib2"] == "10.50.1.7"

    def test_total_allocations(self):
        r = run_federator(
            ["allocate-ips", "/app/federation_specs/advanced.federation.yml"]
        )
        data = json.loads(r.stdout)
        assert len(data) == 11


# ---------------------------------------------------------------------------
# federate: advanced -- property resolution from Go source edge cases
# ---------------------------------------------------------------------------


class TestAdvancedResolution:
    """Tests that exercise non-obvious property resolution paths
    from the Go source: defaults.group->kind resolution and
    kind->group fallback in GetNodeGroup."""

    def setup_method(self):
        r = run_federator(
            ["federate", "/app/federation_specs/advanced.federation.yml"]
        )
        assert r.returncode == 0, r.stderr
        self.topo = yaml.safe_load(r.stdout)
        self.nodes = self.topo["topology"]["nodes"]

    def test_distrib_kind_via_defaults_group(self):
        """distrib1/2 kind must be 'ceos' -- resolved via
        defaults.group='base-group' -> groups.base-group.kind='ceos'.
        This exercises GetNodeKind's defaults.group fallback path."""
        assert self.nodes["advanced-distrib1"]["kind"] == "ceos"
        assert self.nodes["advanced-distrib2"]["kind"] == "ceos"

    def test_distrib_image_from_ceos_kind(self):
        """distrib1 image must come from the ceos kind definition."""
        assert self.nodes["advanced-distrib1"]["image"] == "ceos:4.32.0F"

    def test_distrib_env_from_ceos_kind(self):
        """distrib1 must have DISTRO=arista_eos from ceos kind env."""
        assert self.nodes["advanced-distrib1"]["env"]["DISTRO"] == "arista_eos"

    def test_distrib_labels_from_base_group(self):
        """distrib1 must have managed=true from base-group labels.
        Group is resolved as 'base-group' via defaults.group."""
        assert self.nodes["advanced-distrib1"]["labels"]["managed"] == "true"

    def test_core_kind_explicit(self):
        """core1 has explicit kind=srl."""
        assert self.nodes["advanced-core1"]["kind"] == "srl"

    def test_core_group_via_kind_fallback(self):
        """core1 labels must include vendor=nokia from srl-infra group.
        This exercises GetNodeGroup's kind->group fallback:
        core1 has no explicit group, but kind=srl, and srl kind has
        group=srl-infra, so resolved group is srl-infra."""
        assert self.nodes["advanced-core1"]["labels"]["vendor"] == "nokia"
        assert self.nodes["advanced-core1"]["labels"]["tier"] == "core"

    def test_core_env_from_srl_kind(self):
        """core1 must have DISTRO=srlinux from srl kind."""
        assert self.nodes["advanced-core1"]["env"]["DISTRO"] == "srlinux"

    def test_core_image(self):
        """core1 image from srl kind."""
        assert self.nodes["advanced-core1"]["image"] == "ghcr.io/nokia/srlinux"

    def test_access_kind_from_group(self):
        """access1 kind must be 'linux' from access group."""
        assert self.nodes["advanced-access1"]["kind"] == "linux"

    def test_access_image_from_linux_kind(self):
        """access1 image must be alpine:latest from linux kind definition."""
        assert self.nodes["advanced-access1"]["image"] == "alpine:latest"

    def test_access_labels_from_group(self):
        """access1 must have tier=access from access group."""
        assert self.nodes["advanced-access1"]["labels"]["tier"] == "access"

    def test_total_node_count(self):
        assert len(self.nodes) == 11

    def test_total_link_count(self):
        links = self.topo["topology"]["links"]
        # 5 east + 6 advanced internal + 4 border = 15
        assert len(links) == 15

    def test_border_link_east_spine1_to_core1(self):
        """east-spine1:eth3 should connect to advanced-core1:eth3."""
        links = self.topo["topology"]["links"]
        found = False
        for link in links:
            eps = set(link["endpoints"])
            if eps == {"east-spine1:eth3", "advanced-core1:eth3"}:
                found = True
                break
        assert found, "Missing east-spine1:eth3 <-> advanced-core1:eth3"

    def test_border_link_east_spine2_to_core2(self):
        """east-spine2:eth4 should connect to advanced-core2:eth4."""
        links = self.topo["topology"]["links"]
        found = False
        for link in links:
            eps = set(link["endpoints"])
            if eps == {"east-spine2:eth4", "advanced-core2:eth4"}:
                found = True
                break
        assert found, "Missing east-spine2:eth4 <-> advanced-core2:eth4"

    def test_no_group_in_output(self):
        """Group field must be absent from all resolved nodes."""
        for name, node in self.nodes.items():
            assert "group" not in node, f"{name} has 'group' in merged output"


# ---------------------------------------------------------------------------
# graph: full federation DOT output
# ---------------------------------------------------------------------------


class TestGraphFull:
    """Graphviz DOT graph for full 3-pod federation."""

    def test_valid_dot_syntax(self):
        """DOT output must be parseable by the graphviz dot command."""
        r = run_federator(
            ["graph", "/app/federation_specs/full.federation.yml"]
        )
        assert r.returncode == 0, r.stderr
        dot_r = subprocess.run(
            ["dot", "-Tcanon"],
            input=r.stdout, capture_output=True, text=True,
        )
        assert dot_r.returncode == 0, f"Invalid DOT output: {dot_r.stderr}"

    def test_undirected_graph(self):
        """Must use undirected 'graph' format, not 'digraph'."""
        r = run_federator(
            ["graph", "/app/federation_specs/full.federation.yml"]
        )
        content = r.stdout.strip()
        assert "digraph " not in content
        assert "graph " in content

    def test_subgraph_clusters(self):
        """Each pod must be in its own subgraph cluster."""
        r = run_federator(
            ["graph", "/app/federation_specs/full.federation.yml"]
        )
        assert "cluster_east" in r.stdout
        assert "cluster_west" in r.stdout
        assert "cluster_edge" in r.stdout

    def test_all_nodes_present(self):
        """All 15 federated nodes must appear in DOT output."""
        r = run_federator(
            ["graph", "/app/federation_specs/full.federation.yml"]
        )
        for node in [
            "east-spine1", "east-spine2", "east-leaf1", "east-leaf2",
            "east-server1", "west-spine1", "west-spine2", "west-leaf1",
            "west-leaf2", "west-leaf3", "west-server1", "west-server2",
            "edge-router1", "edge-router2", "edge-firewall",
        ]:
            assert f'"{node}"' in r.stdout, f"Missing node {node} in DOT"

    def test_border_links_dashed(self):
        """Border links must have style=dashed."""
        r = run_federator(
            ["graph", "/app/federation_specs/full.federation.yml"]
        )
        assert "dashed" in r.stdout


# ---------------------------------------------------------------------------
# graph: advanced federation DOT output
# ---------------------------------------------------------------------------


class TestGraphAdvanced:
    """Graphviz DOT graph for advanced federation."""

    def test_valid_dot_syntax(self):
        r = run_federator(
            ["graph", "/app/federation_specs/advanced.federation.yml"]
        )
        assert r.returncode == 0, r.stderr
        dot_r = subprocess.run(
            ["dot", "-Tcanon"],
            input=r.stdout, capture_output=True, text=True,
        )
        assert dot_r.returncode == 0, f"Invalid DOT: {dot_r.stderr}"

    def test_two_clusters(self):
        r = run_federator(
            ["graph", "/app/federation_specs/advanced.federation.yml"]
        )
        assert "cluster_east" in r.stdout
        assert "cluster_advanced" in r.stdout

    def test_mixed_kind_nodes_present(self):
        """Nodes with different resolved kinds all appear."""
        r = run_federator(
            ["graph", "/app/federation_specs/advanced.federation.yml"]
        )
        for node in [
            "advanced-core1", "advanced-distrib1",
            "advanced-access1", "east-spine1",
        ]:
            assert f'"{node}"' in r.stdout, f"Missing {node}"


# ---------------------------------------------------------------------------
# graph: infeasible federation
# ---------------------------------------------------------------------------


class TestGraphInfeasible:
    """Graph for infeasible federation should fail."""

    def test_exits_nonzero(self):
        r = run_federator(
            ["graph", "/app/federation_specs/infeasible.federation.yml"]
        )
        assert r.returncode != 0


# ---------------------------------------------------------------------------
# jq integration: check output must be jq-queryable
# ---------------------------------------------------------------------------


class TestJqIntegration:
    """Verify JSON outputs are correctly queryable with the jq tool."""

    def test_check_jq_pod_count(self):
        """jq can count pods from check output."""
        r = run_federator(
            ["check", "/app/federation_specs/full.federation.yml"]
        )
        assert r.returncode == 0
        jq_r = subprocess.run(
            ["jq", ".pod_subnets | keys | length"],
            input=r.stdout, capture_output=True, text=True,
        )
        assert jq_r.returncode == 0, f"jq failed: {jq_r.stderr}"
        assert jq_r.stdout.strip() == "3"

    def test_allocate_jq_east_filter(self):
        """jq can filter east pod IPs from allocate-ips output."""
        r = run_federator(
            ["allocate-ips", "/app/federation_specs/full.federation.yml"]
        )
        assert r.returncode == 0
        jq_r = subprocess.run(
            ["jq", '[to_entries[] | select(.key | startswith("east-"))] | length'],
            input=r.stdout, capture_output=True, text=True,
        )
        assert jq_r.returncode == 0, f"jq failed: {jq_r.stderr}"
        assert jq_r.stdout.strip() == "5"

    def test_check_jq_naming_conflicts(self):
        """jq can extract sorted naming conflict names."""
        r = run_federator(
            ["check", "/app/federation_specs/full.federation.yml"]
        )
        jq_r = subprocess.run(
            ["jq", "[.naming_conflicts[].name] | sort"],
            input=r.stdout, capture_output=True, text=True,
        )
        assert jq_r.returncode == 0
        names = json.loads(jq_r.stdout)
        assert names == ["leaf1", "leaf2", "server1", "spine1", "spine2"]

    def test_check_jq_border_links(self):
        """jq can extract border link count."""
        r = run_federator(
            ["check", "/app/federation_specs/full.federation.yml"]
        )
        jq_r = subprocess.run(
            ["jq", ".border_link_count"],
            input=r.stdout, capture_output=True, text=True,
        )
        assert jq_r.returncode == 0
        assert jq_r.stdout.strip() == "8"
