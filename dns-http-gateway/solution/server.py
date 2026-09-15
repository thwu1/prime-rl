#!/usr/bin/env python3
"""
Multi-protocol DNS-HTTP gateway server.
Serves DNS on UDP port 2053 and HTTP API on TCP port 8080,
sharing an in-memory record store.
"""

import json
import socket
import struct
import threading
import sys


# ======================== Bencode Codec ========================

def bencode_encode(obj):
    """Encode a Python object to bencode bytes."""
    if isinstance(obj, int):
        return f"i{obj}e".encode()
    elif isinstance(obj, str):
        b = obj.encode("utf-8")
        return f"{len(b)}:".encode() + b
    elif isinstance(obj, bytes):
        return f"{len(obj)}:".encode() + obj
    elif isinstance(obj, list):
        return b"l" + b"".join(bencode_encode(item) for item in obj) + b"e"
    elif isinstance(obj, dict):
        result = b"d"
        for key in sorted(obj.keys()):
            result += bencode_encode(str(key)) + bencode_encode(obj[key])
        result += b"e"
        return result
    raise ValueError(f"Cannot bencode type {type(obj)}")


def _bencode_decode(data, idx):
    """Decode one bencode value starting at idx; return (value, next_idx)."""
    ch = data[idx:idx + 1]
    if ch == b"i":
        end = data.index(b"e", idx)
        return int(data[idx + 1:end]), end + 1
    elif ch == b"l":
        result = []
        idx += 1
        while data[idx:idx + 1] != b"e":
            item, idx = _bencode_decode(data, idx)
            result.append(item)
        return result, idx + 1
    elif ch == b"d":
        result = {}
        idx += 1
        while data[idx:idx + 1] != b"e":
            key, idx = _bencode_decode(data, idx)
            val, idx = _bencode_decode(data, idx)
            if isinstance(key, bytes):
                key = key.decode("utf-8")
            result[key] = val
        return result, idx + 1
    elif ch and (ch.isdigit() or chr(data[idx]).isdigit()):
        colon = data.index(b":", idx)
        length = int(data[idx:colon])
        start = colon + 1
        return data[start:start + length], start + length
    else:
        raise ValueError(f"Invalid bencode at index {idx}")


def bencode_decode(data):
    """Decode bencode data (bytes or str) to Python objects."""
    if isinstance(data, str):
        data = data.encode()
    result, _ = _bencode_decode(data, 0)
    return result


def _bytes_to_native(obj):
    """Recursively convert bytes to str in decoded bencode data."""
    if isinstance(obj, bytes):
        return obj.decode("utf-8")
    elif isinstance(obj, list):
        return [_bytes_to_native(i) for i in obj]
    elif isinstance(obj, dict):
        return {_bytes_to_native(k): _bytes_to_native(v) for k, v in obj.items()}
    return obj


# ======================== Record Store ========================

class RecordStore:
    """Thread-safe in-memory DNS record store."""

    def __init__(self):
        self._records = []
        self._lock = threading.Lock()

    @staticmethod
    def _normalize(name):
        return name.rstrip(".").lower()

    def add(self, record):
        with self._lock:
            self._records.append(dict(record))

    def add_many(self, records):
        with self._lock:
            for r in records:
                self._records.append(dict(r))

    def get_all(self):
        with self._lock:
            return [dict(r) for r in self._records]

    def get_by_domain(self, domain):
        norm = self._normalize(domain)
        with self._lock:
            return [dict(r) for r in self._records if self._normalize(r["name"]) == norm]

    def delete_by_domain(self, domain):
        norm = self._normalize(domain)
        with self._lock:
            self._records = [r for r in self._records if self._normalize(r["name"]) != norm]

    def resolve_a(self, domain, max_hops=10):
        """Resolve A record for domain, following CNAME chains.
        Returns list of answer dicts (CNAME intermediates + terminal A)."""
        current = self._normalize(domain)
        visited = set()
        chain = []
        for _ in range(max_hops):
            if current in visited:
                break
            visited.add(current)
            records = self.get_by_domain(current)
            a_recs = [r for r in records if r["type"] == "A"]
            if a_recs:
                chain.extend(a_recs)
                return chain
            cname_recs = [r for r in records if r["type"] == "CNAME"]
            if cname_recs:
                chain.append(cname_recs[0])
                current = self._normalize(cname_recs[0]["value"])
            else:
                break
        return chain

    def has_domain(self, domain):
        """Check if any record exists for the domain."""
        norm = self._normalize(domain)
        with self._lock:
            return any(self._normalize(r["name"]) == norm for r in self._records)


# ======================== DNS Protocol ========================

def encode_dns_name(domain):
    """Encode domain to DNS label sequence (no compression)."""
    if domain.endswith("."):
        domain = domain[:-1]
    result = b""
    for label in domain.split("."):
        enc = label.encode("ascii")
        result += struct.pack("B", len(enc)) + enc
    result += b"\x00"
    return result


def decode_dns_name(data, offset):
    """Decode DNS label sequence with compression pointer support."""
    labels = []
    jumped = False
    final_offset = offset
    jumps = 0
    while True:
        if offset >= len(data):
            break
        length = data[offset]
        if (length & 0xC0) == 0xC0:
            if not jumped:
                final_offset = offset + 2
            pointer = struct.unpack("!H", data[offset:offset + 2])[0] & 0x3FFF
            offset = pointer
            jumped = True
            jumps += 1
            if jumps > 15:
                break
        elif length == 0:
            if not jumped:
                final_offset = offset + 1
            break
        else:
            offset += 1
            labels.append(data[offset:offset + length].decode("ascii"))
            offset += length
    return ".".join(labels) + ".", final_offset


def parse_dns_query(data):
    """Parse a raw DNS query packet into a structured dict."""
    if len(data) < 12:
        return None
    hdr = struct.unpack("!HHHHHH", data[:12])
    query_id = hdr[0]
    flags = hdr[1]
    qdcount = hdr[2]

    opcode = (flags >> 11) & 0xF
    rd = (flags >> 8) & 1

    questions = []
    offset = 12
    for _ in range(qdcount):
        if offset >= len(data):
            break
        name, offset = decode_dns_name(data, offset)
        if offset + 4 > len(data):
            break
        qtype, qclass = struct.unpack("!HH", data[offset:offset + 4])
        offset += 4
        questions.append({"name": name, "type": qtype, "class": qclass})

    return {"id": query_id, "opcode": opcode, "rd": rd, "questions": questions}


def build_dns_response(query, store):
    """Build a DNS response packet for the given parsed query."""
    query_id = query["id"]
    opcode = query["opcode"]
    rd = query["rd"]
    questions = query["questions"]

    all_answers = []
    any_found = False
    all_nxdomain = True

    if opcode != 0:
        # Not implemented for non-standard opcodes
        rcode = 4
        aa = 0
    else:
        for q in questions:
            if q["type"] == 1:  # A
                chain = store.resolve_a(q["name"])
                if chain:
                    all_answers.extend(chain)
                    any_found = True
                    all_nxdomain = False
                elif store.has_domain(q["name"]):
                    all_nxdomain = False
                # else: domain not found, stays nxdomain candidate
            elif q["type"] == 5:  # CNAME
                records = store.get_by_domain(q["name"])
                cnames = [r for r in records if r["type"] == "CNAME"]
                if cnames:
                    all_answers.extend(cnames)
                    any_found = True
                    all_nxdomain = False
                elif records:
                    all_nxdomain = False
            else:
                if store.has_domain(q["name"]):
                    all_nxdomain = False

        if all_nxdomain and not any_found and len(questions) > 0:
            rcode = 3  # NXDOMAIN
        else:
            rcode = 0
        aa = 1 if any_found else 0

    # Build flags
    flags = (1 << 15)  # QR=1
    flags |= (opcode << 11)
    flags |= (aa << 10)
    flags |= (rd << 8)
    flags |= rcode

    ancount = len(all_answers)
    response = struct.pack("!HHHHHH", query_id, flags, len(questions), ancount, 0, 0)

    # Question section (echo)
    for q in questions:
        response += encode_dns_name(q["name"])
        response += struct.pack("!HH", q["type"], q["class"])

    # Answer section
    for ans in all_answers:
        name = ans["name"]
        if not name.endswith("."):
            name += "."
        response += encode_dns_name(name)

        if ans["type"] == "A":
            response += struct.pack("!HH", 1, 1)  # Type A, Class IN
            response += struct.pack("!I", ans.get("ttl", 300))
            ip_parts = ans["value"].split(".")
            ip_bytes = bytes(int(p) for p in ip_parts)
            response += struct.pack("!H", 4)  # RDLENGTH
            response += ip_bytes
        elif ans["type"] == "CNAME":
            response += struct.pack("!HH", 5, 1)  # Type CNAME, Class IN
            response += struct.pack("!I", ans.get("ttl", 300))
            cname_data = encode_dns_name(ans["value"])
            response += struct.pack("!H", len(cname_data))
            response += cname_data

    return response


# ======================== HTTP Protocol ========================

def parse_http_request(raw):
    """Parse raw HTTP request bytes into structured dict."""
    header_end = raw.find(b"\r\n\r\n")
    if header_end == -1:
        return None

    header_part = raw[:header_end].decode("utf-8", errors="replace")
    body_data = raw[header_end + 4:]

    lines = header_part.split("\r\n")
    if not lines:
        return None

    request_line_parts = lines[0].split(" ", 2)
    if len(request_line_parts) < 2:
        return None

    method = request_line_parts[0]
    path = request_line_parts[1]

    headers = {}
    for line in lines[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()

    content_length = int(headers.get("content-length", 0))
    body = body_data[:content_length]

    return {"method": method, "path": path, "headers": headers, "body": body}


def build_http_response(status_code, status_text, headers=None, body=b""):
    """Build a raw HTTP/1.1 response."""
    if headers is None:
        headers = {}
    if body and "Content-Length" not in headers:
        headers["Content-Length"] = str(len(body))
    resp = f"HTTP/1.1 {status_code} {status_text}\r\n"
    for k, v in headers.items():
        resp += f"{k}: {v}\r\n"
    resp += "\r\n"
    return resp.encode("utf-8") + (body if isinstance(body, bytes) else body.encode("utf-8"))


def handle_http_client(conn, store):
    """Handle a single HTTP client connection."""
    try:
        data = b""
        conn.settimeout(10)
        while True:
            chunk = conn.recv(8192)
            if not chunk:
                break
            data += chunk
            if b"\r\n\r\n" in data:
                header_end = data.find(b"\r\n\r\n")
                header_text = data[:header_end].decode("utf-8", errors="replace")
                cl = 0
                for line in header_text.split("\r\n")[1:]:
                    if line.lower().startswith("content-length:"):
                        cl = int(line.split(":", 1)[1].strip())
                        break
                body_start = header_end + 4
                if len(data) - body_start >= cl:
                    break

        request = parse_http_request(data)
        if not request:
            conn.close()
            return

        method = request["method"]
        path = request["path"]
        body = request["body"]

        response = _route_http(method, path, body, store)
        conn.sendall(response)
    except Exception:
        try:
            conn.sendall(build_http_response(500, "Internal Server Error"))
        except Exception:
            pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _route_http(method, path, body, store):
    """Route HTTP request and return response bytes."""
    if path == "/records" and method == "GET":
        records = store.get_all()
        json_body = json.dumps(records).encode("utf-8")
        return build_http_response(200, "OK", {"Content-Type": "application/json"}, json_body)

    elif path == "/records" and method == "POST":
        decoded = bencode_decode(body)
        record = _bytes_to_native(decoded)
        store.add(record)
        return build_http_response(201, "Created")

    elif path.startswith("/records/") and method == "GET":
        domain = path[len("/records/"):]
        records = store.get_by_domain(domain)
        json_body = json.dumps(records).encode("utf-8")
        return build_http_response(200, "OK", {"Content-Type": "application/json"}, json_body)

    elif path.startswith("/records/") and method == "DELETE":
        domain = path[len("/records/"):]
        store.delete_by_domain(domain)
        return build_http_response(204, "No Content")

    elif path == "/zone-transfer" and method == "GET":
        records = store.get_all()
        encoded = bencode_encode(records)
        return build_http_response(200, "OK", {"Content-Type": "application/x-bencode"}, encoded)

    elif path == "/zone-transfer" and method == "POST":
        decoded = bencode_decode(body)
        records = _bytes_to_native(decoded)
        store.add_many(records)
        return build_http_response(201, "Created")

    else:
        return build_http_response(404, "Not Found")


# ======================== Server Main Loops ========================

def run_dns_server(store, port):
    """Run the DNS UDP server loop."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", port))
    while True:
        try:
            data, addr = sock.recvfrom(4096)
            query = parse_dns_query(data)
            if query:
                response = build_dns_response(query, store)
                sock.sendto(response, addr)
        except Exception:
            pass


def run_http_server(store, port):
    """Run the HTTP TCP server loop."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", port))
    sock.listen(128)
    while True:
        try:
            conn, addr = sock.accept()
            t = threading.Thread(target=handle_http_client, args=(conn, store), daemon=True)
            t.start()
        except Exception:
            pass


def main():
    config_path = "/app/config.json"
    with open(config_path) as f:
        config = json.load(f)

    store = RecordStore()
    for record in config.get("seed_records", []):
        store.add(record)

    dns_port = config.get("dns_port", 2053)
    http_port = config.get("http_port", 8080)

    dns_thread = threading.Thread(target=run_dns_server, args=(store, dns_port), daemon=True)
    http_thread = threading.Thread(target=run_http_server, args=(store, http_port), daemon=True)

    dns_thread.start()
    http_thread.start()

    print(f"DNS server listening on UDP port {dns_port}", flush=True)
    print(f"HTTP server listening on TCP port {http_port}", flush=True)

    dns_thread.join()
    http_thread.join()


if __name__ == "__main__":
    main()
