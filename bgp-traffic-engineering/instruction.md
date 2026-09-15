A four-router FRRouting topology spanning three autonomous systems has been deployed but is experiencing multiple BGP session failures. The topology is documented in `/app/topology.txt`, router configurations are at `/app/configs/r1.conf` through `/app/configs/r4.conf`, and BGP debug logs from the failed deployment are in `/app/logs/`.

FRR is installed on the system for configuration syntax validation.

## Problem

Only the r1-r2 eBGP session has established. The other three BGP sessions are failing with different root causes. Investigate the debug logs and configuration files to identify why each session fails, then correct the router configurations.

Beyond fixing the sessions, the network operations team requires routing policies to achieve these business objectives:

1. Traffic from r1 destined for `10.4.1.0/24` must always prefer the transit path through AS65002 (next-hop `10.0.12.2`), regardless of the AS-path length advantage of the direct r1-r4 peering. All other AS65003 prefixes (`10.4.0.0/22`, `10.4.0.0/24`, `10.4.2.0/24`) should continue using the direct path via r4 (next-hop `10.0.14.2`).

2. Prefix `10.4.3.0/24` must be rejected inbound on r1 from all external peers — it must never appear in r1's BGP table.

3. r4's route advertisements toward r3 must carry an artificially lengthened AS-path with at least 3 additional AS hops beyond the natural origin, to discourage upstream transit selection of that path at other vantage points.

4. Routes from AS65003 peers that are reflected within AS65002's iBGP mesh must have reachable forwarding next-hops at all iBGP members. Currently, such routes reflected by r3 carry external next-hop addresses that r2 has no path to reach.

## Deliverables

1. Fix all configuration files in-place at `/app/configs/r1.conf` through `/app/configs/r4.conf`.

2. Write `/app/diagnosis.json` containing:
   - `"session_failures"`: array of 3 objects, one per failed session, each with:
     - `"session"`: session identifier (e.g. `"r2-r3"`)
     - `"affected_router"`: the router whose configuration contains the defect
     - `"root_cause"`: explanation of the underlying issue
   - `"policy_decisions"`: object with keys `"prefix_steering"`, `"prefix_filtering"`, `"path_inflation"`, `"ibgp_reachability"`, each explaining the BGP mechanism selected and why it is appropriate for that requirement.