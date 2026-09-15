Build `/app/ospf_analyzer.py` — an OSPF neighbor FSM conformance engine that validates packet captures and event traces against RFC 2328.

The module must expose an `OSPFAnalyzer` class whose complete API contract (method signatures, return schemas, and behavioral requirements) is defined in `/data/analysis_spec.json`. Implement every method described there.

Reference materials in the environment:

- `/data/analysis_spec.json` — full API specification (read this first)
- `/data/topology.json` — network topology definition
- `/data/rfc2328_neighbor_fsm.txt` — RFC 2328 neighbor FSM specification excerpt
- `/data/captures/` — pcap files used during verification
- `/data/traces/` — JSON event traces used during verification

The environment has `tshark`, Python 3, and the `scapy` library pre-installed.