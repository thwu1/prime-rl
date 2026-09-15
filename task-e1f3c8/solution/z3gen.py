#!/usr/bin/env python3

"""
Generate Z3 SMT-LIB2 file to verify security invariants on the computed
authority graph. Encodes the graph as finite-domain assertions and checks
three properties by verifying their negations are unsatisfiable.
"""

import json

AUTH_TYPES = sorted([
    "Call", "Control", "DeleteDerived", "Grant", "Notify",
    "Receive", "Reply", "Reset", "SyncSend", "Write"
])


def main():
    with open("/app/output/authority_graph.json") as f:
        data = json.load(f)

    with open("/app/system_state.json") as f:
        state = json.load(f)

    graph = data["authority_graph"]
    pas_subject = state["pas_subject"]

    labels = set()
    for src in graph:
        labels.add(src)
        for dst in graph[src]:
            labels.add(dst)
    labels = sorted(labels)

    with open("/app/output/invariants.smt2", "w") as f:
        f.write("; seL4 Authority Graph Security Verification\n")
        f.write("; Generated from computed authority graph\n")
        f.write("(set-logic ALL)\n\n")

        f.write(f"(declare-datatypes () ((Label {' '.join(labels)})))\n")
        f.write(f"(declare-datatypes () ((Auth {' '.join(AUTH_TYPES)})))\n\n")

        f.write("(declare-fun edge (Label Label Auth) Bool)\n\n")

        f.write("; Complete authority graph encoding (closed world)\n")
        for src in labels:
            for dst in labels:
                auths_present = set(graph.get(src, {}).get(dst, []))
                for auth in AUTH_TYPES:
                    if auth in auths_present:
                        f.write(f"(assert (edge {src} {dst} {auth}))\n")
                    else:
                        f.write(f"(assert (not (edge {src} {dst} {auth})))\n")

        f.write("\n")

        f.write("; Property 1: Designated subject Control is reflexive-only\n")
        f.write('(echo "property1_control_reflexivity")\n')
        f.write("(push)\n")
        f.write("(declare-const w1 Label)\n")
        f.write(f"(assert (edge {pas_subject} w1 Control))\n")
        f.write(f"(assert (not (= w1 {pas_subject})))\n")
        f.write("(check-sat)\n")
        f.write("(pop)\n\n")

        f.write("; Property 2: DeleteDerived is transitively closed\n")
        f.write('(echo "property2_dd_transitivity")\n')
        f.write("(push)\n")
        f.write("(declare-const t1 Label)\n")
        f.write("(declare-const t2 Label)\n")
        f.write("(declare-const t3 Label)\n")
        f.write("(assert (edge t1 t2 DeleteDerived))\n")
        f.write("(assert (edge t2 t3 DeleteDerived))\n")
        f.write("(assert (not (edge t1 t3 DeleteDerived)))\n")
        f.write("(check-sat)\n")
        f.write("(pop)\n\n")

        f.write("; Property 3: Call implies SyncSend\n")
        f.write('(echo "property3_call_implies_syncsend")\n')
        f.write("(push)\n")
        f.write("(declare-const c1 Label)\n")
        f.write("(declare-const c2 Label)\n")
        f.write("(assert (edge c1 c2 Call))\n")
        f.write("(assert (not (edge c1 c2 SyncSend)))\n")
        f.write("(check-sat)\n")
        f.write("(pop)\n")

    print("Z3 verification file written to /app/output/invariants.smt2")


if __name__ == "__main__":
    main()
