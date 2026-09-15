#!/usr/bin/env python3
"""
ASPA-based BGP AS_PATH verification engine.

Verifies BGP route AS_PATHs against ASPA (Autonomous System Provider
Authorization) objects. ASPA objects record which upstream provider ASNs
a customer AS has explicitly authorized. The verification determines
whether an observed AS_PATH is consistent with the valley-free routing
model, classifying each route as Valid, Invalid, or Unknown.

Valley-free model:
  - Traffic ascends from customer to provider (the "up-ramp")
  - Optionally crosses a single lateral peering link at the apex
  - Then descends from provider to customer (the "down-ramp")

Routes received from customers are verified using upstream verification
(the entire path should be ascending). Routes received from providers
or lateral peers use downstream verification (the path should be
valley-free with at most one peering gap at the apex).

AS_PATHs in BGP are ordered neighbor-first, origin-last. Before
verification, the path is reversed to origin-first order and
consecutive duplicate ASNs (from AS_PATH prepending) are collapsed.
"""

import json
import sys
from pathlib import Path


class ASPAVerifier:
    def __init__(self, aspa_db_path):
        with open(aspa_db_path) as f:
            raw = json.load(f)
        self.db = {str(k): set(v) for k, v in raw.items()}

    def hop_check(self, customer_asn, candidate_asn):
        """Check whether customer_asn has authorized candidate_asn as a provider.

        Returns one of:
          "ProviderPlus"    - customer explicitly authorizes this provider
          "NotProviderPlus" - customer has an ASPA but does NOT list this provider
          "NoAttestation"   - customer has no ASPA object registered at all
        """
        key = str(customer_asn)
        if key not in self.db:
            return "NoAttestation"
        if candidate_asn in self.db[key]:
            return "ProviderPlus"
        return "NotProviderPlus"

    @staticmethod
    def preprocess_path(as_path):
        """Convert BGP-ordered AS_PATH to verification-ready form.

        1. Reverse the path so index 0 is the origin AS.
        2. Collapse AS_PATH prepending (remove duplicate ASNs introduced
           by prepending — an AS repeating its own ASN to influence path
           selection).
        """
        reversed_path = list(reversed(as_path))
        # Collapse prepending: strip out repeated ASNs
        seen = []
        for asn in reversed_path:
            if asn not in seen:
                seen.append(asn)
        return seen

    def verify_upstream(self, path):
        """Upstream verification for routes received from a customer.

        The entire path should be a chain of customer-to-provider hops
        ascending from origin to neighbor. Every hop is checked:
          - ProviderPlus: consistent, continue
          - NotProviderPlus: the customer explicitly denies this provider,
            indicating a route leak -> Invalid
          - NoAttestation: can't confirm or deny -> contributes to Unknown
        """
        n = len(path)
        if n <= 1:
            return "Valid"

        has_unknown = False
        for i in range(n - 1):
            h = self.hop_check(path[i], path[i + 1])
            if h == "NotProviderPlus":
                return "Invalid"
            if h == "NoAttestation":
                has_unknown = True

        return "Unknown" if has_unknown else "Valid"

    def verify_downstream(self, path):
        """Downstream verification for routes received from a provider or peer.

        The path should have valley-free shape: an ascending up-ramp from
        the origin, an optional single peering hop at the apex, then a
        descending down-ramp toward the neighbor.

        Algorithm:
        1. Forward scan from origin to find the extent of the up-ramp (u).
           The scan advances as long as each hop is not NotProviderPlus.
        2. Reverse scan from neighbor to find the extent of the down-ramp (d).
           At each position j, check whether the AS at j authorized the AS
           at j-1 as its provider (since j is receiving transit from j-1 in
           the down-ramp direction).
        3. If the ramps meet or overlap, the shape is valley-free.
           A single-hop gap at the apex is permitted for a peering link.
        4. Finally, check attestation completeness within each ramp.
        """
        n = len(path)
        if n <= 2:
            return "Valid"

        # Forward scan: up-ramp extent from origin
        u = 0
        for i in range(n - 1):
            if self.hop_check(path[i], path[i + 1]) == "NotProviderPlus":
                break
            u = i + 1

        # Reverse scan: down-ramp extent from neighbor
        d = n - 1
        for j in range(n - 1, 0, -1):
            if self.hop_check(path[j - 1], path[j]) == "NotProviderPlus":
                break
            d = j - 1

        # Valley-free shape check
        if u + 1 <= d:
            return "Invalid"

        # Attestation completeness within each ramp
        for i in range(u):
            if self.hop_check(path[i], path[i + 1]) == "NoAttestation":
                return "Unknown"
        for j in range(n - 1, d, -1):
            if self.hop_check(path[j], path[j - 1]) == "NoAttestation":
                return "Unknown"

        return "Valid"

    def verify_route(self, route):
        """Verify a single route using the appropriate algorithm based on
        the BGP relationship with the neighbor that sent it.

        Routes from customers use upstream verification.
        Routes from providers or peers use downstream verification.
        """
        path = self.preprocess_path(route["as_path"])
        relationship = route["relationship"]

        if relationship in ("customer", "peer"):
            return self.verify_upstream(path)
        else:
            return self.verify_downstream(path)


def main():
    db_path = Path("/app/aspa_db.json")
    routes_path = Path("/app/routes.json")
    output_path = Path("/app/current_output.json")

    verifier = ASPAVerifier(str(db_path))

    with open(routes_path) as f:
        routes = json.load(f)

    results = []
    for route in routes:
        result = verifier.verify_route(route)
        results.append({"route_id": route["route_id"], "result": result})

    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)

    valid = sum(1 for r in results if r["result"] == "Valid")
    invalid = sum(1 for r in results if r["result"] == "Invalid")
    unknown = sum(1 for r in results if r["result"] == "Unknown")
    print(f"Verified {len(results)} routes: {valid} Valid, {invalid} Invalid, {unknown} Unknown")
    print(f"Results written to {output_path}")


if __name__ == "__main__":
    main()
