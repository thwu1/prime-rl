A production server authenticates messages using Poly1305 MACs (as specified in RFC 8439). During a routine engagement, your team captured network traffic from this server and obtained three candidate C implementations of the MAC scheme from the vendor's source repository. Only one of the three implementations matches the server's actual behavior.

The following materials are staged in `/app/`:

- `/app/implementations/` — three C implementations (`alpha`, `beta`, `gamma`) with a shared `main.c` driver and `Makefile` (link against GMP)
- `/app/poly1305_ref.py` — a Python reference implementation of standard RFC 8439 Poly1305
- `/app/test_vectors.json` — RFC 8439 test vectors
- `/app/server_traffic.json` — captured authenticated messages from the production server
- `/app/target.json` — a message that must be authenticated without access to the server's secret key material

Conduct a security assessment of the deployed system. Determine which implementation the server runs, evaluate the correctness and security properties of each implementation, analyze the captured traffic for exploitable weaknesses, and — if the system is vulnerable — demonstrate exploitability by producing a valid authenticator for the target message.

Write your results to:

- `/app/audit_report.json` with these exact fields:
  - `"server_implementation"`: the variant name (`"alpha"`, `"beta"`, or `"gamma"`)
  - `"implementation_deviation"`: description of how the server's variant deviates from the RFC 8439 specification
  - `"vulnerability_assessment"`: your evaluation of the security weaknesses found in the deployed system and how they enable forgery
- `/app/forged_tag.hex`: the forged 16-byte authenticator for the target message, as 32 lowercase hex characters (no prefix, no newline)