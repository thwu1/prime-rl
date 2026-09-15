Implement a TCP server at `/app/server.py` (port 9000) that coordinates wildlife population management between site-visiting clients and a local Authority Server.

Your server must operate in a dual networking role:

- **Inbound TCP server** (port 9000): accepts connections from clients that submit binary-framed `SiteVisit` messages reporting observed animal populations at monitored sites
- **Outbound TCP client**: initiates connections to the Authority Server at `localhost:20547` to query target population ranges via `DialAuthority`, then creates and deletes population control policies to reconcile each site's state

The binary protocol specification — covering all nine message types, framing rules with length-prefixed messages, data type encoding (`u32`, `str`, arrays), and mod-256 checksum computation — is at `/app/protocol.md`. The authority's per-site target population configurations are at `/app/site_config.json`.

A working Authority Server is provided at `/app/authority_server.py`. For local development, start it with `python3 /app/authority_server.py &`. It exposes policy state at `http://localhost:20548/policies` and accepts `POST /reset` to clear state. The Authority Server will already be running during automated testing.

After receiving each `SiteVisit`, your server must reconcile policies for that site via the Authority so they settle to the correct final state: one `cull` policy per species whose observed count exceeds the authority's maximum, one `conserve` policy per species below the minimum, and no policy for species within range. Stale policies from prior visits that no longer apply must be deleted. The settled state must not contain more than one policy per species. Species absent from a `SiteVisit` have an observed count of zero. Species observed but not present in the authority's target populations require no policy action. Non-conflicting duplicate species entries in a `SiteVisit` are permitted; conflicting duplicates are a protocol error requiring an `Error` response.

Ensure `/app/run.sh` starts your server in the foreground on TCP port 9000.