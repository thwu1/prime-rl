#!/usr/bin/env python3

"""Generate compliance report documenting RFC violations found in the buggy DNS server.

Each violation was discovered by probing the running server with targeted DNS queries
and comparing wire-level responses against RFC 1035 and RFC 6891 specifications.
"""

import json

report = [
    {
        "violation": (
            "Incomplete CNAME chain following: server resolves only one level of "
            "CNAME indirection, failing to follow multi-hop alias chains "
            "(e.g. blog -> www -> apex returns only blog's CNAME, missing the "
            "second hop and final A record)"
        ),
        "rfc": "RFC 1035",
        "section": "4.3.2",
        "severity": "critical",
        "fix_description": (
            "Replaced single-step CNAME lookup with an iterative loop using a "
            "visited-set for cycle detection that follows the full CNAME chain "
            "and appends each intermediate CNAME RR to the answer section before "
            "resolving the final target"
        ),
    },
    {
        "violation": (
            "Wildcard responses use the wildcard owner name (*.wild.example.com.) "
            "instead of synthesizing the queried name (e.g. foo.wild.example.com.), "
            "causing resolvers to discard non-matching owner names"
        ),
        "rfc": "RFC 1035",
        "section": "4.3.3",
        "severity": "critical",
        "fix_description": (
            "When matching a wildcard, create new ZoneRecord objects with the "
            "queried name substituted as owner instead of directly appending "
            "the wildcard records from the zone data"
        ),
    },
    {
        "violation": (
            "NXDOMAIN responses omit SOA record from the authority section, "
            "preventing downstream resolvers from caching negative results "
            "and causing repeated queries for non-existent names"
        ),
        "rfc": "RFC 1035",
        "section": "4.3.2",
        "severity": "major",
        "fix_description": (
            "Added SOA record to the authority section when returning NXDOMAIN "
            "responses, enabling proper negative caching per the server algorithm"
        ),
    },
    {
        "violation": (
            "EDNS0 OPT pseudo-RR in responses encodes version 1 in the TTL field "
            "(0x00010000) instead of version 0 (0x00000000), causing EDNS-capable "
            "resolvers to reject responses with BADVERS"
        ),
        "rfc": "RFC 6891",
        "section": "6.1.3",
        "severity": "critical",
        "fix_description": (
            "Changed the OPT record TTL field from 0x00010000 (version=1, "
            "extended-rcode=0) to 0x00000000 (version=0, extended-rcode=0)"
        ),
    },
    {
        "violation": (
            "SOA RDATA retry field encoded in little-endian byte order (<I) "
            "instead of network byte order (!I), corrupting the 32-bit integer "
            "value on the wire (900 encoded as 0x84030000 instead of 0x00000384)"
        ),
        "rfc": "RFC 1035",
        "section": "3.3.13",
        "severity": "critical",
        "fix_description": (
            "Changed struct.pack format for SOA integer fields from mixed "
            "endianness ('!II' + '<I' + '!II') to uniform network byte order "
            "('!IIIII') for all five 32-bit fields (serial, refresh, retry, "
            "expire, minimum)"
        ),
    },
    {
        "violation": (
            "TXT RDATA written as raw bytes without length-prefixed "
            "character-string encoding, producing malformed wire format that "
            "violates the character-string structure requirement"
        ),
        "rfc": "RFC 1035",
        "section": "3.3.14",
        "severity": "critical",
        "fix_description": (
            "Implemented proper character-string encoding: split text into "
            "255-byte chunks, each prefixed by a single length octet, as "
            "required by the TXT RDATA wire format specification"
        ),
    },
]

with open("/app/compliance_report.json", "w") as f:
    json.dump(report, f, indent=2)

print(f"Compliance report written with {len(report)} violations documented")
