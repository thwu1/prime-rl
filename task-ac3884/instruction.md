Implement `/app/server.py` — a Python application that serializes DNS zone data into wire format and provides BitTorrent-style piece distribution with HMAC-SHA1 integrity verification using a configurable fingerprint key. The system exposes an HTTP API and an authoritative DNS server.

## HTTP API (port 8080)

`POST /zones` — Accept JSON `{"name": "<zone>", "records": [{"name", "type", "ttl", "rdata"}, ...]}`. Return `{"zone_id": "<id>"}` (201).

`GET /zones/<id>/records` — Return the zone's records as JSON.

`POST /zones/<id>/snapshot` — Serialize all records into DNS wire format (sorted by type code ascending, then name lexicographic, then rdata lexicographic; label compression on name fields only, not on RDATA), split into 384-byte pieces, compute HMAC-SHA1 of each piece using the key `bytes.fromhex("a3f7c9e1d2b4685f")`. Return (201) a bencoded manifest (`Content-Type: application/x-bittorrent`) containing byte-string keys: `algorithm` (b"hmac-sha1"), `fingerprint` (the raw 8-byte key), `piece length` (384), `pieces` (concatenated 20-byte HMAC digests), `record count` (number of records), `total length` (serialized byte count), `zone` (zone name as bytes). Bencoded dict keys must be sorted.

`GET /zones/<id>/snapshot/manifest` — Return the stored bencoded manifest.

`GET /zones/<id>/snapshot/piece/<n>` — Return raw bytes of piece N (`Content-Type: application/octet-stream`).

`GET /zones/<id>/snapshot/verify` — Return `{"valid": bool, "pieces": [{"piece": N, "valid": bool}, ...]}`.

## DNS Authoritative Server (UDP 5353)

Respond to standard DNS queries for any loaded zone. Answers must use DNS wire format with label compression (compression pointers for shared domain-name suffixes). Support record types: A, AAAA, NS, CNAME, MX, TXT, SOA.

## Constraints

- Implement DNS wire format (RFC 1035 headers, questions, resource records, label compression pointers) from scratch using `struct` and byte operations — no `dnspython`, `dnslib`, or equivalent.
- Implement bencoding from scratch — no `bencodepy` or equivalent.
- HMAC-SHA1 piece hashing: use `hmac.new(bytes.fromhex("a3f7c9e1d2b4685f"), piece, hashlib.sha1).digest()`.
- Use threading for concurrent HTTP connections.
- Return 404 for unknown zones, missing snapshots, or out-of-range pieces.