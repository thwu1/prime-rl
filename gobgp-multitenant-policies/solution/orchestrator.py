#!/usr/bin/env python3
"""Multi-tenant BGP policy engine orchestrator for GoBGP.

Reads /app/tenants.json and configures GoBGP via its gRPC API with
per-tenant prefix filtering, community tagging, AS-path manipulation,
MED adjustment, export isolation, and peer groups.
"""

import json
import os
import subprocess
import sys
import time

# Use pre-compiled gRPC stubs
sys.path.insert(0, "/app/generated")
import grpc
from api import gobgp_pb2, gobgp_pb2_grpc


# ---------------------------------------------------------------------------
# Daemon management
# ---------------------------------------------------------------------------
def ensure_gobgpd():
    """Start gobgpd if it is not already running."""
    subprocess.Popen(
        ["gobgpd"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(2)


def wait_for_grpc(stub, timeout=30):
    """Block until the gRPC server is reachable."""
    for attempt in range(timeout):
        try:
            stub.GetBgp(gobgp_pb2.GetBgpRequest())
            return
        except grpc.RpcError:
            if attempt == timeout - 1:
                raise RuntimeError(
                    f"gobgpd gRPC not reachable after {timeout}s"
                )
            time.sleep(1)


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------
def init_global(stub, cfg):
    """Call StartBgp with the global configuration."""
    req = gobgp_pb2.StartBgpRequest()
    g = getattr(req, "global")
    g.asn = cfg["asn"]
    g.router_id = cfg["router_id"]
    g.listen_port = cfg["listen_port"]
    try:
        stub.StartBgp(req)
    except grpc.RpcError as exc:
        # Tolerate "already started"
        if "already" not in str(exc).lower():
            raise


def add_defined_set(stub, defined_type, name, *, prefixes=None, str_list=None):
    """Add a DefinedSet of the given type."""
    ds = gobgp_pb2.DefinedSet(defined_type=defined_type, name=name)
    if prefixes:
        ds.prefixes.extend(prefixes)
    if str_list:
        ds.list.extend(str_list)
    stub.AddDefinedSet(gobgp_pb2.AddDefinedSetRequest(defined_set=ds))


def make_statement(name, *, conditions=None, actions=None):
    """Build a Statement message."""
    kwargs = {"name": name}
    if conditions is not None:
        kwargs["conditions"] = conditions
    if actions is not None:
        kwargs["actions"] = actions
    return gobgp_pb2.Statement(**kwargs)


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------
def main():
    # 1. Start gobgpd & connect
    ensure_gobgpd()
    channel = grpc.insecure_channel("localhost:50051")
    stub = gobgp_pb2_grpc.GoBgpServiceStub(channel)
    wait_for_grpc(stub)

    # 2. Load tenant spec
    with open("/app/tenants.json") as fh:
        config = json.load(fh)

    global_cfg = config["global"]
    tenants = config["tenants"]
    tenant_by_id = {t["id"]: t for t in tenants}

    # 3. Initialize BGP
    init_global(stub, global_cfg)

    # 4. Bogon prefix-set (mask_length_max=32 to cover all more-specifics)
    bogon_pfxs = []
    for entry in global_cfg["bogon_prefixes"]:
        mask = int(entry.rsplit("/", 1)[1])
        bogon_pfxs.append(
            gobgp_pb2.Prefix(ip_prefix=entry, mask_length_min=mask, mask_length_max=32)
        )
    add_defined_set(
        stub, gobgp_pb2.DEFINED_TYPE_PREFIX, "bogon-prefixes", prefixes=bogon_pfxs
    )

    # 5. Per-tenant defined-sets
    for t in tenants:
        n = t["name"]

        # Prefix-set
        pfxs = [
            gobgp_pb2.Prefix(
                ip_prefix=p["prefix"],
                mask_length_min=p["min_length"],
                mask_length_max=p["max_length"],
            )
            for p in t["allowed_prefixes"]
        ]
        add_defined_set(
            stub, gobgp_pb2.DEFINED_TYPE_PREFIX, f"tenant-{n}-prefixes", prefixes=pfxs
        )

        # Community-set (identity)
        add_defined_set(
            stub,
            gobgp_pb2.DEFINED_TYPE_COMMUNITY,
            f"tenant-{n}-community",
            str_list=[t["community_tag"]],
        )

        # AS-path-set (origin rejection) — only if non-empty
        if t["reject_as_origins"]:
            patterns = [f"_{asn}$" for asn in t["reject_as_origins"]]
            add_defined_set(
                stub,
                gobgp_pb2.DEFINED_TYPE_AS_PATH,
                f"tenant-{n}-reject-origins",
                str_list=patterns,
            )

        # Export-allowed community-set
        permitted_ids = [t["id"]] + t.get("export_to_tenants", [])
        comms = [tenant_by_id[tid]["community_tag"] for tid in permitted_ids]
        add_defined_set(
            stub,
            gobgp_pb2.DEFINED_TYPE_COMMUNITY,
            f"tenant-{n}-export-allowed",
            str_list=comms,
        )

    # 6. Global bogon rejection policy
    stub.AddPolicy(
        gobgp_pb2.AddPolicyRequest(
            policy=gobgp_pb2.Policy(
                name="global-bogon-reject",
                statements=[
                    make_statement(
                        "global-bogon-reject-stmt",
                        conditions=gobgp_pb2.Conditions(
                            prefix_set=gobgp_pb2.MatchSet(
                                type=gobgp_pb2.MatchSet.TYPE_ANY,
                                name="bogon-prefixes",
                            )
                        ),
                        actions=gobgp_pb2.Actions(
                            route_action=gobgp_pb2.ROUTE_ACTION_REJECT
                        ),
                    )
                ],
            )
        )
    )

    # 7. Per-tenant import & export policies
    for t in tenants:
        n = t["name"]

        # --- import policy ---
        imp_stmts = []

        if t["reject_as_origins"]:
            imp_stmts.append(
                make_statement(
                    f"tenant-{n}-import-reject-origins",
                    conditions=gobgp_pb2.Conditions(
                        as_path_set=gobgp_pb2.MatchSet(
                            type=gobgp_pb2.MatchSet.TYPE_ANY,
                            name=f"tenant-{n}-reject-origins",
                        )
                    ),
                    actions=gobgp_pb2.Actions(
                        route_action=gobgp_pb2.ROUTE_ACTION_REJECT
                    ),
                )
            )

        # Accept allowed prefixes, add community, MED, AS-prepend
        act_kwargs = {
            "route_action": gobgp_pb2.ROUTE_ACTION_ACCEPT,
            "community": gobgp_pb2.CommunityAction(
                type=gobgp_pb2.CommunityAction.TYPE_ADD,
                communities=[t["community_tag"]],
            ),
        }
        if t["med_adjustment"] != 0:
            act_kwargs["med"] = gobgp_pb2.MedAction(
                type=gobgp_pb2.MedAction.TYPE_MOD,
                value=t["med_adjustment"],
            )
        if t.get("as_prepend"):
            act_kwargs["as_prepend"] = gobgp_pb2.AsPrependAction(
                asn=t["as_prepend"]["asn"],
                repeat=t["as_prepend"]["repeat"],
            )

        imp_stmts.append(
            make_statement(
                f"tenant-{n}-import-accept",
                conditions=gobgp_pb2.Conditions(
                    prefix_set=gobgp_pb2.MatchSet(
                        type=gobgp_pb2.MatchSet.TYPE_ANY,
                        name=f"tenant-{n}-prefixes",
                    )
                ),
                actions=gobgp_pb2.Actions(**act_kwargs),
            )
        )

        stub.AddPolicy(
            gobgp_pb2.AddPolicyRequest(
                policy=gobgp_pb2.Policy(name=f"tenant-{n}-import", statements=imp_stmts)
            )
        )

        # --- export policy ---
        exp_stmts = [
            make_statement(
                f"tenant-{n}-export-accept",
                conditions=gobgp_pb2.Conditions(
                    community_set=gobgp_pb2.MatchSet(
                        type=gobgp_pb2.MatchSet.TYPE_ANY,
                        name=f"tenant-{n}-export-allowed",
                    )
                ),
                actions=gobgp_pb2.Actions(
                    route_action=gobgp_pb2.ROUTE_ACTION_ACCEPT
                ),
            ),
            make_statement(
                f"tenant-{n}-export-reject",
                actions=gobgp_pb2.Actions(
                    route_action=gobgp_pb2.ROUTE_ACTION_REJECT
                ),
            ),
        ]

        stub.AddPolicy(
            gobgp_pb2.AddPolicyRequest(
                policy=gobgp_pb2.Policy(name=f"tenant-{n}-export", statements=exp_stmts)
            )
        )

    # 8. Assign global import policy
    stub.SetPolicyAssignment(
        gobgp_pb2.SetPolicyAssignmentRequest(
            assignment=gobgp_pb2.PolicyAssignment(
                name="global",
                direction=gobgp_pb2.POLICY_DIRECTION_IMPORT,
                policies=[gobgp_pb2.Policy(name="global-bogon-reject")],
                default_action=gobgp_pb2.ROUTE_ACTION_ACCEPT,
            )
        )
    )

    # 9. Create peer groups with policy bindings
    for t in tenants:
        n = t["name"]
        stub.AddPeerGroup(
            gobgp_pb2.AddPeerGroupRequest(
                peer_group=gobgp_pb2.PeerGroup(
                    conf=gobgp_pb2.PeerGroupConf(
                        peer_group_name=f"pg-{n}",
                        peer_asn=t["asn"],
                    ),
                    apply_policy=gobgp_pb2.ApplyPolicy(
                        import_policy=gobgp_pb2.PolicyAssignment(
                            direction=gobgp_pb2.POLICY_DIRECTION_IMPORT,
                            policies=[
                                gobgp_pb2.Policy(name=f"tenant-{n}-import")
                            ],
                            default_action=gobgp_pb2.ROUTE_ACTION_REJECT,
                        ),
                        export_policy=gobgp_pb2.PolicyAssignment(
                            direction=gobgp_pb2.POLICY_DIRECTION_EXPORT,
                            policies=[
                                gobgp_pb2.Policy(name=f"tenant-{n}-export")
                            ],
                            default_action=gobgp_pb2.ROUTE_ACTION_REJECT,
                        ),
                    ),
                )
            )
        )

    # 10. Write state summary
    state = {
        "global_config": {"asn": global_cfg["asn"], "router_id": global_cfg["router_id"]},
        "defined_sets": {"prefix_sets": [], "community_sets": [], "as_path_sets": []},
        "policies": [],
        "peer_groups": [],
    }

    for resp in stub.ListDefinedSet(
        gobgp_pb2.ListDefinedSetRequest(defined_type=gobgp_pb2.DEFINED_TYPE_PREFIX)
    ):
        ds = resp.defined_set
        state["defined_sets"]["prefix_sets"].append(
            {"name": ds.name, "prefix_count": len(ds.prefixes)}
        )

    for resp in stub.ListDefinedSet(
        gobgp_pb2.ListDefinedSetRequest(defined_type=gobgp_pb2.DEFINED_TYPE_COMMUNITY)
    ):
        ds = resp.defined_set
        state["defined_sets"]["community_sets"].append(
            {"name": ds.name, "entries": list(ds.list)}
        )

    for resp in stub.ListDefinedSet(
        gobgp_pb2.ListDefinedSetRequest(defined_type=gobgp_pb2.DEFINED_TYPE_AS_PATH)
    ):
        ds = resp.defined_set
        state["defined_sets"]["as_path_sets"].append(
            {"name": ds.name, "entries": list(ds.list)}
        )

    for resp in stub.ListPolicy(gobgp_pb2.ListPolicyRequest()):
        p = resp.policy
        state["policies"].append(
            {
                "name": p.name,
                "statement_count": len(p.statements),
                "statements": [s.name for s in p.statements],
            }
        )

    for resp in stub.ListPeerGroup(gobgp_pb2.ListPeerGroupRequest()):
        pg = resp.peer_group
        state["peer_groups"].append(
            {"name": pg.conf.peer_group_name, "peer_asn": pg.conf.peer_asn}
        )

    with open("/app/state.json", "w") as fh:
        json.dump(state, fh, indent=2)

    print("Multi-tenant BGP policy engine configured successfully.")
    print(f"  Prefix sets:    {len(state['defined_sets']['prefix_sets'])}")
    print(f"  Community sets: {len(state['defined_sets']['community_sets'])}")
    print(f"  AS-path sets:   {len(state['defined_sets']['as_path_sets'])}")
    print(f"  Policies:       {len(state['policies'])}")
    print(f"  Peer groups:    {len(state['peer_groups'])}")


if __name__ == "__main__":
    main()
