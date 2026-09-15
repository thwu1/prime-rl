"""
A toy DNS resolver that performs iterative resolution starting from root nameservers.

Usage:
    python3 resolver.py <domain>

Example:
    python3 resolver.py example.com
"""

import socket
import struct
import random
from dataclasses import dataclass
from typing import List, Optional, Tuple

# DNS constants
TYPE_A = 1
TYPE_NS = 2
TYPE_CNAME = 5
TYPE_SOA = 6
TYPE_AAAA = 28
TYPE_OPT = 41
CLASS_IN = 1

ROOT_SERVERS = ["198.41.0.4", "199.9.14.201", "192.33.4.12", "199.7.91.13"]


@dataclass
class DNSHeader:
    id: int
    flags: int
    num_questions: int = 0
    num_answers: int = 0
    num_authorities: int = 0
    num_additionals: int = 0

    @property
    def rcode(self):
        return self.flags & 0xF


@dataclass
class DNSQuestion:
    name: str
    type_: int
    class_: int


@dataclass
class DNSRecord:
    name: str
    type_: int
    class_: int
    ttl: int
    data: str


@dataclass
class DNSPacket:
    header: DNSHeader
    questions: List[DNSQuestion]
    answers: List[DNSRecord]
    authorities: List[DNSRecord]
    additionals: List[DNSRecord]


def encode_dns_name(name: str) -> bytes:
    result = b""
    for label in name.rstrip(".").split("."):
        result += bytes([len(label)]) + label.encode("ascii")
    return result + b"\x00"


def build_query(name: str, type_: int = TYPE_A) -> bytes:
    txn_id = random.randint(0, 65535)
    flags = 0x0000
    header = struct.pack("!HHHHHH", txn_id, flags, 1, 0, 0, 0)
    question = encode_dns_name(name) + struct.pack("!HH", type_, CLASS_IN)
    return header + question


def decode_dns_name(data: bytes, offset: int) -> Tuple[str, int]:
    parts = []
    jumped = False
    return_offset = offset

    while True:
        if offset >= len(data):
            raise ValueError("Name extends past packet boundary")

        length = data[offset]
        if length == 0:
            if not jumped:
                return_offset = offset + 1
            break

        if (length & 0xC0) == 0xC0:
            if not jumped:
                return_offset = offset + 2
                jumped = True
            pointer = struct.unpack("!H", data[offset:offset + 2])[0] & 0x3FFF
            offset = pointer
            continue

        offset += 1
        parts.append(data[offset:offset + length].decode("ascii"))
        offset += length
        if not jumped:
            return_offset = offset

    return ".".join(parts), return_offset


def parse_header(data: bytes) -> DNSHeader:
    if len(data) < 12:
        raise ValueError("Packet too short")
    return DNSHeader(*struct.unpack("!HHHHHH", data[:12]))


def parse_question(data: bytes, offset: int) -> Tuple[DNSQuestion, int]:
    name, offset = decode_dns_name(data, offset)
    if offset + 4 > len(data):
        raise ValueError("Packet too short for question fields")
    qtype, qclass = struct.unpack("!HH", data[offset:offset + 4])
    return DNSQuestion(name, qtype, qclass), offset + 4


def parse_record(data: bytes, offset: int) -> Tuple[DNSRecord, int]:
    name, offset = decode_dns_name(data, offset)
    if offset + 10 > len(data):
        raise ValueError("Packet too short for record fields")
    rtype, rclass, ttl, rdlen = struct.unpack("!HHIH", data[offset:offset + 10])
    rdata_start = offset + 10

    if rdata_start + rdlen > len(data):
        raise ValueError("Record data extends beyond packet")

    rdata = data[rdata_start:rdata_start + rdlen]
    next_offset = rdata_start + rdlen

    if rtype == TYPE_A and rdlen == 4:
        parsed = ".".join(str(b) for b in rdata)
    elif rtype in (TYPE_NS, TYPE_CNAME):
        parsed, _ = decode_dns_name(data, rdata_start)
    elif rtype == TYPE_AAAA and rdlen == 16:
        parsed = ":".join(
            f"{rdata[i]:02x}{rdata[i+1]:02x}" for i in range(0, 16, 2)
        )
    else:
        parsed = rdata.hex()

    return DNSRecord(name, rtype, rclass, ttl, parsed), next_offset


def parse_dns_packet(data: bytes) -> DNSPacket:
    header = parse_header(data)
    offset = 12

    questions = []
    for _ in range(header.num_questions):
        q, offset = parse_question(data, offset)
        questions.append(q)

    answers = []
    for _ in range(header.num_answers):
        r, offset = parse_record(data, offset)
        answers.append(r)

    authorities = []
    for _ in range(header.num_authorities):
        r, offset = parse_record(data, offset)
        authorities.append(r)

    additionals = []
    for _ in range(header.num_additionals):
        r, offset = parse_record(data, offset)
        additionals.append(r)

    return DNSPacket(header, questions, answers, authorities, additionals)


def send_query(server: str, name: str, type_: int = TYPE_A,
               timeout: float = 5.0) -> DNSPacket:
    query = build_query(name, type_)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(query, (server, 53))
        data, _ = sock.recvfrom(512)
        return parse_dns_packet(data)
    finally:
        sock.close()


def resolve(name: str, type_: int = TYPE_A, _depth: int = 0) -> Optional[str]:
    if _depth > 15:
        return None

    nameserver = random.choice(ROOT_SERVERS)

    for _ in range(30):
        try:
            response = send_query(nameserver, name, type_)
        except (socket.timeout, OSError):
            return None

        if response.header.rcode != 0:
            return None

        # Check for a direct answer
        for rec in response.answers:
            if rec.type_ == type_ and rec.name.lower().rstrip(".") == name.lower().rstrip("."):
                return rec.data

        # Look for NS delegation
        ns_name = None
        for rec in response.authorities:
            if rec.type_ == TYPE_NS:
                ns_name = rec.data
                break

        if ns_name is None:
            return None

        # Look for glue record
        glue = None
        for rec in response.additionals:
            if rec.type_ == TYPE_A and rec.name.lower().rstrip(".") == ns_name.lower().rstrip("."):
                glue = rec.data
                break

        if glue is not None:
            nameserver = glue
        else:
            return None

    return None


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <domain>")
        sys.exit(1)
    result = resolve(sys.argv[1])
    if result:
        print(f"{sys.argv[1]} -> {result}")
    else:
        print(f"Failed to resolve {sys.argv[1]}")
        sys.exit(1)
