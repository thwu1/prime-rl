Implement a coordination server that bridges site visitor animal population reports with a central Authority Server, following the binary protocol specification at `/app/protocol.md`.

A mock Authority Server is provided at `/app/authority_server.py` and will be running on `127.0.0.1:20547` when your server starts. Your server must accept site visitor connections on TCP port 9000.

Your server acts as **both a TCP server and a TCP client simultaneously**: it accepts connections from site visitors (who send `SiteVisit` messages reporting observed animal populations) and connects to the Authority Server as a client (to obtain target population ranges via `DialAuthority` and manage policies via `CreatePolicy`/`DeletePolicy`).

For each `SiteVisit`, your server must reconcile policies on the Authority Server so that the settled state reflects the most recent observation: overpopulated species get a `cull` policy, underpopulated species get a `conserve` policy, species within their target range have no policy, and uncontrolled species are ignored. Unobserved controlled species have an implicit count of zero. At most one policy per species may exist at settlement. Your server must track policy IDs returned by the Authority to correctly delete stale policies when observations change.

All messages in both directions use the binary checksum-framed protocol described in the specification. Your server must validate checksums on incoming messages and compute correct checksums on outgoing messages. The `Hello` handshake is required on both sides — as the server for site visitors, and as the client to the Authority Server.

Your server must support concurrent clients across multiple sites.

When complete, create `/app/run.sh` to start your server in the foreground.