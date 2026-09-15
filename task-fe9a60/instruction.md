A three-router FRR (FRRouting) BGP topology using multi-VRF L3VPN route-leaking (RT/RD, `export vpn`/`import vpn`) has been deployed but inter-VRF route leaking is non-functional. Router configurations are at `/app/configs/r1.conf`, `/app/configs/r2.conf`, `/app/configs/r3.conf`. The intended design is in `/app/topology.json`.

Beyond fixing the broken deployment, two new VRFs must be designed from scratch and integrated into the architecture. Business requirements for these VRFs are in `/app/requirements.json` — no RT/RD values are provided; you must engineer an RT/RD assignment scheme that satisfies all isolation constraints using the existing RT/RD mappings as context. You must also evaluate the security posture of the complete architecture.

FRR is installed with `bgpd` and `zebra` enabled; `/app/start_frr.sh` launches the daemons. `vtysh` is available.

Produce:

- `/app/output/bugs.json` — JSON array of objects: `router`, `vrf`, `bug`, `fix`
- `/app/output/design_evaluation.json` — JSON object with keys `quarantine_design`, `monitor_design`, and `security_assessment`. Each design entry: `rd` (string), `rt_export` (list of RT strings), `rt_import` (list of RT strings), `justification` (string explaining why chosen values satisfy the constraints), `isolation_properties` (object with `imports_routes_from`, `exports_routes_to`, `leaks_back_to` — each a list of VRF names on the same router that routes flow to/from). `security_assessment`: list of objects with `finding`, `severity` (`"high"`/`"medium"`/`"low"`), `recommendation`.
- `/app/output/reachability.json` — JSON object mapping each `"ROUTER:VRF"` key to a sorted list of `"ROUTER:VRF"` sources whose routes it receives via same-router VPN route-leak after all fixes AND new VRFs are added. All eight VRFs must appear as keys.
- `/app/output/corrected/r1.conf`, `r2.conf`, `r3.conf` — Corrected FRR configurations with all original bugs fixed AND new VRFs fully configured with VPN route-leak semantics
- `/app/output/validation_report.txt` — Validation report covering all routers and all VRFs including newly designed ones