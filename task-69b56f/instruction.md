A legacy SOCKS5 proxy is deployed at `/app/legacy/socks5d.pyz` (compiled, no source). Start it with `/app/legacy/start.sh`. It reads ACL rules from `/app/acl.conf` and user credentials from `/app/users.conf`, and listens on TCP port 1080.

Clients report intermittent failures across different connection types and authentication scenarios. Session transcripts captured from the legacy proxy are at `/app/transcripts/` (hex-encoded protocol exchanges, one session per file). The RFC specifications are at `/app/docs/rfc1928.txt` (SOCKS Protocol Version 5) and `/app/docs/rfc1929.txt` (Username/Password Authentication).

Network diagnostic tools including `tshark`, `tcpdump`, `curl`, and `netcat` are installed. You may start the legacy proxy and probe it directly, and/or analyze the session transcripts.

Produce:

1. `/app/conformance_report.json` — a JSON array of objects, each with at least `rfc` (string), `section` (string), and `description` (string) fields, documenting every protocol violation found.

2. `/app/proxy.py` — a fully conformant SOCKS5 proxy replacement implementing RFC 1928 and RFC 1929. It must read ACL rules from `/app/acl.conf` (first-match-wins CIDR), authenticate users via `/app/users.conf` (username:password), log connections to `/app/proxy.log`, and listen on TCP port 1080.