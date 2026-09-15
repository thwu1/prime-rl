"""Tests for multi-tenant BGP policy engine configuration via GoBGP gRPC API."""

import json
import os
import sys

import pytest

sys.path.insert(0, '/app/generated')
import grpc
from api import gobgp_pb2, gobgp_pb2_grpc


@pytest.fixture(scope="module")
def stub():
    channel = grpc.insecure_channel('localhost:50051')
    s = gobgp_pb2_grpc.GoBgpServiceStub(channel)
    try:
        s.GetBgp(gobgp_pb2.GetBgpRequest())
    except grpc.RpcError:
        pytest.skip("Cannot connect to gobgpd on localhost:50051")
    return s


# ---------------------------------------------------------------------------
# Global config
# ---------------------------------------------------------------------------
class TestGlobalConfig:
    def test_asn(self, stub):
        resp = stub.GetBgp(gobgp_pb2.GetBgpRequest())
        g = getattr(resp, 'global')
        assert g.asn == 65000, f"Expected ASN 65000, got {g.asn}"

    def test_router_id(self, stub):
        resp = stub.GetBgp(gobgp_pb2.GetBgpRequest())
        g = getattr(resp, 'global')
        assert g.router_id == "10.255.0.1", f"Expected router-id 10.255.0.1, got {g.router_id}"


# ---------------------------------------------------------------------------
# Prefix-sets
# ---------------------------------------------------------------------------
class TestPrefixSets:
    def _get(self, stub):
        result = {}
        for resp in stub.ListDefinedSet(gobgp_pb2.ListDefinedSetRequest(
                defined_type=gobgp_pb2.DEFINED_TYPE_PREFIX)):
            ds = resp.defined_set
            result[ds.name] = ds
        return result

    def test_total_count(self, stub):
        ps = self._get(stub)
        assert len(ps) == 5, f"Expected 5 prefix-sets, got {len(ps)}: {sorted(ps.keys())}"

    def test_bogon_exists_with_eight_entries(self, stub):
        ps = self._get(stub)
        assert "bogon-prefixes" in ps, "Missing bogon-prefixes"
        assert len(ps["bogon-prefixes"].prefixes) == 8, (
            f"bogon-prefixes should have 8 entries, got {len(ps['bogon-prefixes'].prefixes)}"
        )

    def test_tenant_prefix_sets_exist(self, stub):
        ps = self._get(stub)
        for name in ["tenant-acme-prefixes", "tenant-globex-prefixes",
                      "tenant-initech-prefixes", "tenant-umbrella-prefixes"]:
            assert name in ps, f"Missing prefix-set: {name}"

    def test_acme_has_two_prefixes(self, stub):
        ps = self._get(stub)
        assert len(ps["tenant-acme-prefixes"].prefixes) == 2

    def test_umbrella_has_three_prefixes(self, stub):
        ps = self._get(stub)
        assert len(ps["tenant-umbrella-prefixes"].prefixes) == 3


# ---------------------------------------------------------------------------
# Community-sets
# ---------------------------------------------------------------------------
class TestCommunitySets:
    def _get(self, stub):
        result = {}
        for resp in stub.ListDefinedSet(gobgp_pb2.ListDefinedSetRequest(
                defined_type=gobgp_pb2.DEFINED_TYPE_COMMUNITY)):
            ds = resp.defined_set
            result[ds.name] = ds
        return result

    def test_total_count(self, stub):
        cs = self._get(stub)
        assert len(cs) == 8, f"Expected 8 community-sets, got {len(cs)}: {sorted(cs.keys())}"

    def test_identity_sets_exist(self, stub):
        cs = self._get(stub)
        for name in ["tenant-acme-community", "tenant-globex-community",
                      "tenant-initech-community", "tenant-umbrella-community"]:
            assert name in cs, f"Missing community-set: {name}"

    def test_export_allowed_sets_exist(self, stub):
        cs = self._get(stub)
        for name in ["tenant-acme-export-allowed", "tenant-globex-export-allowed",
                      "tenant-initech-export-allowed", "tenant-umbrella-export-allowed"]:
            assert name in cs, f"Missing community-set: {name}"

    def test_umbrella_export_has_four_communities(self, stub):
        """umbrella exports to tenants 1,2,3 plus itself = 4 communities."""
        cs = self._get(stub)
        umb = cs["tenant-umbrella-export-allowed"]
        assert len(umb.list) == 4, (
            f"umbrella export-allowed should have 4 communities, got {len(umb.list)}: {list(umb.list)}"
        )

    def test_initech_export_isolated(self, stub):
        """initech has empty export_to_tenants => only its own community."""
        cs = self._get(stub)
        ini = cs["tenant-initech-export-allowed"]
        assert len(ini.list) == 1, (
            f"initech export-allowed should have 1 community (isolated), got {len(ini.list)}"
        )

    def test_acme_export_has_two(self, stub):
        """acme exports to tenant 2 => own + globex = 2."""
        cs = self._get(stub)
        acme = cs["tenant-acme-export-allowed"]
        assert len(acme.list) == 2


# ---------------------------------------------------------------------------
# AS-path-sets
# ---------------------------------------------------------------------------
class TestAsPathSets:
    def _get(self, stub):
        result = {}
        for resp in stub.ListDefinedSet(gobgp_pb2.ListDefinedSetRequest(
                defined_type=gobgp_pb2.DEFINED_TYPE_AS_PATH)):
            ds = resp.defined_set
            result[ds.name] = ds
        return result

    def test_total_count(self, stub):
        aps = self._get(stub)
        assert len(aps) == 2, f"Expected 2 AS-path-sets, got {len(aps)}: {sorted(aps.keys())}"

    def test_expected_names(self, stub):
        aps = self._get(stub)
        assert "tenant-acme-reject-origins" in aps
        assert "tenant-initech-reject-origins" in aps

    def test_initech_has_two_entries(self, stub):
        """initech rejects AS 65050 and 65051."""
        aps = self._get(stub)
        ini = aps["tenant-initech-reject-origins"]
        assert len(ini.list) == 2, f"Expected 2 entries, got {len(ini.list)}"


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------
class TestPolicies:
    def _get(self, stub):
        result = {}
        for resp in stub.ListPolicy(gobgp_pb2.ListPolicyRequest()):
            p = resp.policy
            result[p.name] = p
        return result

    def test_total_count(self, stub):
        pol = self._get(stub)
        assert len(pol) == 9, f"Expected 9 policies, got {len(pol)}: {sorted(pol.keys())}"

    def test_global_bogon_policy_exists(self, stub):
        pol = self._get(stub)
        assert "global-bogon-reject" in pol
        assert len(pol["global-bogon-reject"].statements) >= 1

    def test_import_policies_exist(self, stub):
        pol = self._get(stub)
        for name in ["tenant-acme-import", "tenant-globex-import",
                      "tenant-initech-import", "tenant-umbrella-import"]:
            assert name in pol, f"Missing import policy: {name}"

    def test_export_policies_exist(self, stub):
        pol = self._get(stub)
        for name in ["tenant-acme-export", "tenant-globex-export",
                      "tenant-initech-export", "tenant-umbrella-export"]:
            assert name in pol, f"Missing export policy: {name}"

    def test_acme_import_has_origin_rejection(self, stub):
        """acme has reject_as_origins=[65099] => needs reject-origins + accept stmts."""
        pol = self._get(stub)
        assert len(pol["tenant-acme-import"].statements) >= 2

    def test_initech_import_has_origin_rejection(self, stub):
        """initech has reject_as_origins=[65050,65051]."""
        pol = self._get(stub)
        assert len(pol["tenant-initech-import"].statements) >= 2

    def test_globex_import_no_extra_rejection(self, stub):
        """globex has empty reject_as_origins => only accept stmt."""
        pol = self._get(stub)
        assert len(pol["tenant-globex-import"].statements) >= 1

    def test_export_policies_have_accept_and_reject(self, stub):
        pol = self._get(stub)
        for name in ["tenant-acme-export", "tenant-globex-export",
                      "tenant-initech-export", "tenant-umbrella-export"]:
            assert len(pol[name].statements) >= 2, (
                f"{name} should have >= 2 statements (accept + reject-all)"
            )


# ---------------------------------------------------------------------------
# Import policy actions (MED, AS-prepend, community tagging)
# ---------------------------------------------------------------------------
class TestImportPolicyActions:
    """Verify that import policies apply correct route attribute modifications."""

    def _get_policies(self, stub):
        result = {}
        for resp in stub.ListPolicy(gobgp_pb2.ListPolicyRequest()):
            result[resp.policy.name] = resp.policy
        return result

    def _find_accept_stmt(self, policy):
        """Find the ACCEPT statement in a policy (the one applying route modifications)."""
        for stmt in policy.statements:
            if stmt.actions.route_action == gobgp_pb2.ROUTE_ACTION_ACCEPT:
                return stmt
        return None

    def test_acme_import_med_100(self, stub):
        """acme has med_adjustment=100."""
        pol = self._get_policies(stub)
        stmt = self._find_accept_stmt(pol["tenant-acme-import"])
        assert stmt is not None, "No accept statement in tenant-acme-import"
        assert stmt.actions.med.value == 100, (
            f"Expected MED value 100 for acme, got {stmt.actions.med.value}"
        )

    def test_initech_import_med_negative50(self, stub):
        """initech has med_adjustment=-50."""
        pol = self._get_policies(stub)
        stmt = self._find_accept_stmt(pol["tenant-initech-import"])
        assert stmt is not None, "No accept statement in tenant-initech-import"
        assert stmt.actions.med.value == -50, (
            f"Expected MED value -50 for initech, got {stmt.actions.med.value}"
        )

    def test_umbrella_import_med_200(self, stub):
        """umbrella has med_adjustment=200."""
        pol = self._get_policies(stub)
        stmt = self._find_accept_stmt(pol["tenant-umbrella-import"])
        assert stmt is not None, "No accept statement in tenant-umbrella-import"
        assert stmt.actions.med.value == 200, (
            f"Expected MED value 200 for umbrella, got {stmt.actions.med.value}"
        )

    def test_globex_import_as_prepend(self, stub):
        """globex has as_prepend: asn=65002, repeat=2."""
        pol = self._get_policies(stub)
        stmt = self._find_accept_stmt(pol["tenant-globex-import"])
        assert stmt is not None, "No accept statement in tenant-globex-import"
        assert stmt.actions.as_prepend.asn == 65002, (
            f"Expected AS-prepend ASN 65002, got {stmt.actions.as_prepend.asn}"
        )
        assert stmt.actions.as_prepend.repeat == 2, (
            f"Expected AS-prepend repeat 2, got {stmt.actions.as_prepend.repeat}"
        )

    def test_umbrella_import_as_prepend(self, stub):
        """umbrella has as_prepend: asn=65004, repeat=3."""
        pol = self._get_policies(stub)
        stmt = self._find_accept_stmt(pol["tenant-umbrella-import"])
        assert stmt is not None, "No accept statement in tenant-umbrella-import"
        assert stmt.actions.as_prepend.asn == 65004, (
            f"Expected AS-prepend ASN 65004, got {stmt.actions.as_prepend.asn}"
        )
        assert stmt.actions.as_prepend.repeat == 3, (
            f"Expected AS-prepend repeat 3, got {stmt.actions.as_prepend.repeat}"
        )

    def test_acme_import_community_tag(self, stub):
        """acme import accept statement should add community 65000:1."""
        pol = self._get_policies(stub)
        stmt = self._find_accept_stmt(pol["tenant-acme-import"])
        assert stmt is not None, "No accept statement in tenant-acme-import"
        comms = list(stmt.actions.community.communities)
        assert "65000:1" in comms, (
            f"Expected community 65000:1 in acme import, got {comms}"
        )

    def test_umbrella_import_community_tag(self, stub):
        """umbrella import accept statement should add community 65000:4."""
        pol = self._get_policies(stub)
        stmt = self._find_accept_stmt(pol["tenant-umbrella-import"])
        assert stmt is not None, "No accept statement in tenant-umbrella-import"
        comms = list(stmt.actions.community.communities)
        assert "65000:4" in comms, (
            f"Expected community 65000:4 in umbrella import, got {comms}"
        )


# ---------------------------------------------------------------------------
# Global policy assignment
# ---------------------------------------------------------------------------
class TestGlobalPolicyAssignment:
    def test_bogon_reject_assigned_as_global_import(self, stub):
        found = False
        for resp in stub.ListPolicyAssignment(gobgp_pb2.ListPolicyAssignmentRequest(
                name="global",
                direction=gobgp_pb2.POLICY_DIRECTION_IMPORT)):
            policy_names = [p.name for p in resp.assignment.policies]
            if "global-bogon-reject" in policy_names:
                found = True
        assert found, "global-bogon-reject not assigned as global import policy"


# ---------------------------------------------------------------------------
# Peer groups
# ---------------------------------------------------------------------------
class TestPeerGroups:
    def _get(self, stub):
        result = {}
        for resp in stub.ListPeerGroup(gobgp_pb2.ListPeerGroupRequest()):
            pg = resp.peer_group
            result[pg.conf.peer_group_name] = pg
        return result

    def test_total_count(self, stub):
        pgs = self._get(stub)
        assert len(pgs) == 4, f"Expected 4 peer groups, got {len(pgs)}: {sorted(pgs.keys())}"

    def test_names(self, stub):
        pgs = self._get(stub)
        for name in ["pg-acme", "pg-globex", "pg-initech", "pg-umbrella"]:
            assert name in pgs, f"Missing peer group: {name}"

    def test_acme_asn(self, stub):
        pgs = self._get(stub)
        assert pgs["pg-acme"].conf.peer_asn == 65001

    def test_globex_asn(self, stub):
        pgs = self._get(stub)
        assert pgs["pg-globex"].conf.peer_asn == 65002

    def test_initech_asn(self, stub):
        pgs = self._get(stub)
        assert pgs["pg-initech"].conf.peer_asn == 65003

    def test_umbrella_asn(self, stub):
        pgs = self._get(stub)
        assert pgs["pg-umbrella"].conf.peer_asn == 65004

    def test_import_policy_bindings(self, stub):
        """Each peer group must have its tenant's import policy bound."""
        pgs = self._get(stub)
        for tenant in ["acme", "globex", "initech", "umbrella"]:
            pg = pgs[f"pg-{tenant}"]
            import_pols = [p.name for p in pg.apply_policy.import_policy.policies]
            assert f"tenant-{tenant}-import" in import_pols, (
                f"pg-{tenant} missing import policy binding for tenant-{tenant}-import"
            )

    def test_export_policy_bindings(self, stub):
        """Each peer group must have its tenant's export policy bound."""
        pgs = self._get(stub)
        for tenant in ["acme", "globex", "initech", "umbrella"]:
            pg = pgs[f"pg-{tenant}"]
            export_pols = [p.name for p in pg.apply_policy.export_policy.policies]
            assert f"tenant-{tenant}-export" in export_pols, (
                f"pg-{tenant} missing export policy binding for tenant-{tenant}-export"
            )


# ---------------------------------------------------------------------------
# state.json
# ---------------------------------------------------------------------------
class TestStateJson:
    def test_file_exists(self):
        assert os.path.exists('/app/state.json'), "/app/state.json not found"

    def _load(self):
        with open('/app/state.json') as f:
            return json.load(f)

    def test_top_level_keys(self):
        state = self._load()
        for key in ['global_config', 'defined_sets', 'policies', 'peer_groups']:
            assert key in state, f"Missing key in state.json: {key}"

    def test_defined_sets_sublists(self):
        state = self._load()
        ds = state['defined_sets']
        for key in ['prefix_sets', 'community_sets', 'as_path_sets']:
            assert key in ds, f"Missing defined_sets sub-key: {key}"

    def test_prefix_sets_count(self):
        state = self._load()
        assert len(state['defined_sets']['prefix_sets']) == 5

    def test_community_sets_count(self):
        state = self._load()
        assert len(state['defined_sets']['community_sets']) == 8

    def test_as_path_sets_count(self):
        state = self._load()
        assert len(state['defined_sets']['as_path_sets']) == 2

    def test_policies_count(self):
        state = self._load()
        assert len(state['policies']) == 9

    def test_peer_groups_count(self):
        state = self._load()
        assert len(state['peer_groups']) == 4

    def test_global_asn(self):
        state = self._load()
        assert state['global_config']['asn'] == 65000
