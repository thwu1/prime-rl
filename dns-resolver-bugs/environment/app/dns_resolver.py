#!/usr/bin/env python3
"""
Recursive DNS resolver implementation.

Builds DNS queries, parses responses, and iteratively follows the delegation
chain from root nameservers to authoritative servers to resolve domain names.
"""


import struct
import socket
import random
import time
from dataclasses import dataclass
from io import BytesIO
from typing import List

# Record types
TYPE_A = 1
TYPE_NS = 2
TYPE_CNAME = 5
TYPE_SOA = 6
TYPE_AAAA = 28

CLASS_IN = 1
ROOT_SERVER = "198.41.0.4"


@dataclass
class DNSHeader:
    id: int
    flags: int
    num_questions: int = 0
    num_answers: int = 0
    num_authorities: int = 0
    num_additionals: int = 0


@dataclass
class DNSQuestion:
    name: bytes
    type_: int
    class_: int


@dataclass
class DNSRecord:
    name: bytes
    type_: int
    class_: int
    ttl: int
    data: bytes


@dataclass
class DNSPacket:
    header: DNSHeader
    questions: List[DNSQuestion]
    answers: List[DNSRecord]
    authorities: List[DNSRecord]
    additionals: List[DNSRecord]


# ── Query construction ──

def encode_dns_name(domain_name):
    encoded = b""
    for part in domain_name.encode("ascii").split(b"."):
        encoded += bytes([len(part)]) + part
    return encoded + b"\x00"


def header_to_bytes(header):
    return struct.pack(
        "!HHHHHH",
        header.id, header.flags, header.num_questions,
        header.num_answers, header.num_authorities, header.num_additionals,
    )


def question_to_bytes(question):
    return question.name + struct.pack("!HH", question.type_, question.class_)


def build_query(domain_name, record_type):
    name = encode_dns_name(domain_name)
    id_ = random.randint(0, 65535)
    header = DNSHeader(id=id_, num_questions=1, flags=0)
    question = DNSQuestion(name=name, type_=record_type, class_=CLASS_IN)
    return header_to_bytes(header) + question_to_bytes(question)


# ── Response parsing ──

def parse_header(reader):
    items = struct.unpack("!HHHHHH", reader.read(12))
    return DNSHeader(*items)


def decode_name(reader):
    parts = []
    while (length := reader.read(1)[0]) != 0:
        if length & 0b1100_0000:
            parts.append(decode_compressed_name(length, reader))
            break
        else:
            parts.append(reader.read(length))
    return b".".join(parts)


def decode_compressed_name(length, reader):
    pointer_bytes = bytes([length & 0b0011_1111]) + reader.read(1)
    pointer = struct.unpack("!H", pointer_bytes)[0]
    current_pos = reader.tell()
    reader.seek(pointer)
    result = decode_name(reader)
    reader.seek(current_pos)
    return result


def parse_question(reader):
    name = decode_name(reader)
    data = reader.read(4)
    type_, class_ = struct.unpack("!HH", data)
    return DNSQuestion(name, type_, class_)


def parse_record(reader):
    name = decode_name(reader)
    data = reader.read(10)
    type_, class_, ttl, data_len = struct.unpack("!HHIH", data)
    if type_ == TYPE_NS:
        data = decode_name(reader)
    elif type_ == TYPE_A:
        data = ip_to_string(reader.read(data_len))
    else:
        data = reader.read(data_len)
    return DNSRecord(name, type_, class_, ttl, data)


def parse_dns_packet(data):
    reader = BytesIO(data)
    header = parse_header(reader)
    questions = [parse_question(reader) for _ in range(header.num_questions)]
    answers = [parse_record(reader) for _ in range(header.num_answers)]
    authorities = [parse_record(reader) for _ in range(header.num_authorities)]
    additionals = [parse_record(reader) for _ in range(header.num_additionals)]
    return DNSPacket(header, questions, answers, authorities, additionals)


def ip_to_string(ip):
    return ".".join([str(x) for x in ip])


# ── Caching ──

class CacheEntry:
    def __init__(self, data, ttl):
        self.data = data
        self.expires_at = time.time() + ttl
        self.ttl = ttl


class DNSCache:
    def __init__(self):
        self._store = {}

    def put(self, name, type_, data, ttl):
        key = (name.lower() if isinstance(name, str) else name.lower(), type_)
        self._store[key] = CacheEntry(data, ttl)

    def get(self, name, type_):
        key = (name.lower() if isinstance(name, str) else name.lower(), type_)
        entry = self._store.get(key)
        if entry and time.time() < entry.ttl:
            return entry.data
        if entry:
            del self._store[key]
        return None

    def clear(self):
        self._store.clear()


# ── Resolution ──

_cache = DNSCache()


def send_query(ip_address, domain_name, record_type):
    query = build_query(domain_name, record_type)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(5)
    sock.sendto(query, (ip_address, 53))
    data, _ = sock.recvfrom(1024)
    sock.close()
    return parse_dns_packet(data)


def get_answer(packet):
    for x in packet.answers:
        if x.type_ == TYPE_A:
            return x.data
    return None


def get_nameserver_ip(packet):
    for x in packet.additionals:
        if x.type_ == TYPE_A:
            return x.data
    return None


def get_nameserver(packet):
    for x in packet.authorities:
        if x.type_ == TYPE_NS:
            return x.data.decode("utf-8") if isinstance(x.data, bytes) else x.data
    return None


def resolve(domain_name, record_type=TYPE_A):
    cached = _cache.get(domain_name, record_type)
    if cached:
        return cached

    nameserver = ROOT_SERVER
    while True:
        response = send_query(nameserver, domain_name, record_type)
        if ip := get_answer(response):
            _cache.put(domain_name, record_type, ip, 300)
            return ip
        elif nsIP := get_nameserver_ip(response):
            nameserver = nsIP
        else:
            raise Exception("something went wrong")


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <domain>")
        sys.exit(1)
    print(resolve(sys.argv[1]))
