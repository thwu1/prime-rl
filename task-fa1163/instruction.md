VoiceLink is a WebRTC-like signaling server at `/app/voicelink/`. It manages call sessions between peers using a custom binary protocol (VLSP) for signaling, ICE candidate exchange, and media track lifecycle management.

Recent disclosures revealed that multiple major messaging platforms had state machine vulnerabilities in their WebRTC signaling implementations — flaws that allowed callers to force callees to transmit audio or video without consent. VoiceLink's server may have similar issues.

Perform a comprehensive security audit of the VoiceLink server. The server runs on `localhost:9877` (start with `python3 /app/voicelink/server.py`; override port via `VLSP_PORT` env var). The VLSP binary protocol is documented in `/app/voicelink/protocol.py`.

Use `tshark` to capture VLSP protocol traffic during exploit validation. For each vulnerability identified, produce:

- `/app/exploits/exploit_<name>.py` — exploit script that connects to the server, triggers the vulnerability, queries session status to confirm unauthorized callee media transmission, and exits 0 on success.
- `/app/captures/<name>.pcap` — traffic capture of the exploit recorded via `tshark` on the loopback interface during execution.
- `/app/exploits/findings/<name>.json` — containing: `vulnerability_name` (string), `description` (string), `root_cause` (string), `impact` (string), `callee_media_transmitted` (boolean, must be `true`), `cvss_score` (float, CVSS 3.1 base score), and `cvss_vector` (string, CVSS:3.1 vector string with all base metrics AV/AC/PR/UI/S/C/I/A).

Design and implement a hardened server at `/app/voicelink/server_hardened.py` that fixes all identified vulnerabilities while maintaining backward compatibility with the legitimate call flow. The hardened server must pass the conformance test suite (`python3 /app/voicelink/conformance.py`) and must reject all exploit patterns — each exploit should fail (non-zero exit) when run against it. The hardened server reads its port from the `VLSP_PORT` environment variable (default 9877).

There are exactly 4 distinct state machine vulnerabilities. Each represents a different class of signaling flaw.