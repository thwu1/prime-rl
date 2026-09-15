#!/usr/bin/env python3
"""
Generate migration plan from audit report.

"""

import json


def load_report():
    with open("/app/audit_report.json", "r") as f:
        return json.load(f)


def main():
    report = load_report()
    defects = report["defects"]

    # Group defects by migration phase
    phases = {}
    for d in defects:
        phase = d.get("migration_phase", 1)
        if phase not in phases:
            phases[phase] = {"routers": set(), "defects": []}
        phases[phase]["routers"].add(d["router"])
        phases[phase]["defects"].append(d)

    migration_plan = []
    for phase_num in sorted(phases.keys()):
        phase_data = phases[phase_num]
        routers = sorted(phase_data["routers"])
        defect_summaries = []
        for d in phase_data["defects"]:
            defect_summaries.append(
                f"{d['router']}: {d['category']}/{d['severity']} - "
                f"{d['description'][:100]}"
            )

        if phase_num == 1:
            dep_reason = (
                "Phase 1 addresses adjacency-breaking and critical security "
                "defects first. R4 passive-interface must be corrected before "
                "any Area 1 changes (R1 auth) to avoid losing the only path "
                "during migration. CoPP and ACL fixes are independent and can "
                "be applied concurrently since they don't affect routing adjacency."
            )
            rollback = "medium"
        elif phase_num == 2:
            dep_reason = (
                "Phase 2 addresses routing correctness defects after adjacency "
                "is restored. R1 OSPF Area 1 auth change to message-digest must "
                "be coordinated with R4 (which is now forming adjacency after "
                "Phase 1). BGP prefix-list and redistribution loop prevention on "
                "R2 are applied here because they depend on stable OSPF adjacency. "
                "R5 network statement removal requires OSPF to be converged first."
            )
            rollback = "high"
        else:
            dep_reason = (
                "Phase 3 addresses operational and lower-risk defects after "
                "routing and security are stabilized. BFD enablement and OSPF "
                "cost changes can cause brief reconvergence but are safe to "
                "apply on an already-stable topology. NTP trusted-key addition "
                "is non-disruptive and independent of routing state."
            )
            rollback = "low"

        migration_plan.append({
            "phase": phase_num,
            "routers": routers,
            "changes_summary": "; ".join(
                f"{d['router']}: {d['affected_config']}"
                for d in phase_data["defects"]
            ),
            "dependency_reason": dep_reason,
            "rollback_risk": rollback,
        })

    output_path = "/app/migration_plan.json"
    with open(output_path, "w") as f:
        json.dump(migration_plan, f, indent=2)

    print(f"Migration plan written to {output_path}")
    for phase in migration_plan:
        print(
            f"  Phase {phase['phase']}: {phase['routers']} "
            f"(rollback risk: {phase['rollback_risk']})"
        )


if __name__ == "__main__":
    main()
