A multi-file Python simulator of Cilium's eBPF datapath packet processing pipeline is provided at `/app/`. The simulator models connection tracking, load balancing, identity-based policy enforcement, hairpin/loopback flow handling, and CIDR-based identity resolution — mirroring the logic in Cilium's `bpf_lxc.c`.

The codebase is split across several interacting modules:
- `/app/datapath.py` — Main processing pipeline and configuration loader
- `/app/identity.py` — IP-to-identity resolution including CIDR range matching
- `/app/conntrack.py` — Connection tracking with scope-aware lookups and metadata encoding
- `/app/loadbalancer.py` — Per-packet L4 load balancer
- `/app/policy.py` — Identity-based policy evaluation engine
- `/app/config.json` — Network topology, services, CIDR identity mappings, and policies
- `/app/tools/diagnose.py` — Diagnostic CLI for inspecting packet verdicts

The implementation contains multiple defects and an incomplete feature that together cause incorrect packet processing. Issues span multiple modules and interact across component boundaries — fixing one may reveal another, and some components produce misleading diagnostic output. The docstrings in each module describe the intended behavior that the code should implement.

Fix all issues in the `/app/` codebase so that the test suite at `/tests/test_state.py` passes.