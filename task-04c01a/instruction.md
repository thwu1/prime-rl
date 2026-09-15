`/app/scenario.json` contains 12 captured TCP packets from BGP sessions protected with TCP Authentication Option (TCP-AO, RFC 5925). Each entry includes the connection's claimed configuration (master key, algorithm identifiers, IP endpoints, ports, ISNs, SNE, options coverage mode) and a raw IP packet hex dump.

Some packets are authentic (valid TCP-AO MAC). Others have been forged through different attack vectors. Build a forensic analysis tool that verifies each packet's TCP-AO MAC and classifies detected forgeries.

Your tool must compute the expected MAC for each packet using its stated configuration parameters, following the TCP-AO specification. The scenario file provides all connection parameters needed for traffic key derivation and MAC computation. You will need to consult the relevant RFCs to understand how to correctly derive traffic keys and compute MACs for the algorithm suites referenced in the scenario data.

For forged packets (where the computed MAC does not match the packet's MAC), classify the attack into one of these categories:
- `wrong_coverage` -- the MAC was computed using a different TCP options coverage mode than what the connection claims
- `corrupted_mac` -- the computed MAC and the packet's MAC differ in 3 or fewer bytes
- `modified_payload` -- none of the above apply

Write results to `/app/audit_report.json`: a JSON object keyed by packet ID, where each value has fields `verdict` (`"authentic"` or `"forged"`), `computed_mac` (hex string of the MAC computed with stated parameters), `packet_mac` (hex string of the MAC extracted from the TCP-AO option in the packet), and `attack_class` (`null` for authentic, or one of the classification strings above).

Python 3 and pycryptodome are available in the environment.