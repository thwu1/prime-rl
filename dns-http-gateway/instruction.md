Build a single Python server at `/app/server.py` that simultaneously operates a DNS resolver (UDP port 2053) and an HTTP API (TCP port 8080), sharing one in-memory record store. Launch via `python3 /app/server.py`. Configuration is at `/app/config.json` (ports and seed records).

## DNS Server (RFC 1035)

Implement the binary DNS wire format from scratch. The server must:

- Parse incoming UDP queries including label compression pointers (§4.1.4) across multiple questions in a single packet.
- Construct responses with correct header flags: QR=1, mirrored OPCODE/RD, AA=1 for authoritative answers.
- Echo the full question section in responses.
- Answer A (type 1) and CNAME (type 5) queries from the record store.
- Follow CNAME chains (max 10 hops), returning all intermediate CNAME records plus the terminal A record with correct ANCOUNT.
- Return RCODE 3 (NXDOMAIN) for unknown domains, RCODE 4 for non-zero OPCODE.

## HTTP API

Implement HTTP/1.1 request/response parsing from raw TCP sockets — no frameworks or libraries. Request/response bodies use bencode encoding where specified.

| Endpoint | Method | Body Format | Response |
|---|---|---|---|
| `/records` | POST | bencode dict (`name`, `type`, `value`, `ttl`) | 201 |
| `/records` | GET | — | 200, JSON array |
| `/records/{domain}` | GET | — | 200, JSON array |
| `/records/{domain}` | DELETE | — | 204 |
| `/zone-transfer` | POST | bencode list of record dicts | 201 |
| `/zone-transfer` | GET | — | 200, bencode list (`Content-Type: application/x-bencode`) |

## Constraints

- Handle concurrent connections on both UDP and TCP.
- DNS wire format, HTTP parsing, and bencode codec must all be implemented from scratch using only Python's standard library.
- Domain matching is case-insensitive; trailing dots are optional (`example.com` equals `example.com.`).
- Records added via HTTP must be immediately queryable via DNS, and vice versa.