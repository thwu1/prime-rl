#!/usr/bin/env python3
"""

Fixed multi-tenant TCP proxy with 4-tuple-aware port allocation.

Design decisions:
1. Per-destination port tracking — The PortAllocator tracks port usage
   per (dest_ip, dest_port) pair.  TCP connections are identified by
   4-tuples (src_ip, src_port, dst_ip, dst_port), so the same source
   port can be reused for connections to different destinations.

2. SO_REUSEADDR on every socket — Allows bind() to succeed on a port
   already bound by a connected socket going to a different destination.
   The kernel checks 4-tuple uniqueness at connect() time.  All sockets
   must set SO_REUSEADDR to keep the bind-bucket fastreuse state at +1;
   a single socket without it transitions the bucket to fastreuse=0,
   blocking the fast-path bind check for all subsequent sockets.

3. Fixed-port services connect first — Service C's audit-required
   ports are established before auto-allocation can consume them.
   This guarantees that the buckets for ports 40050-40059 are created
   with fastreuse=+1, not poisoned to fastreuse=0 by a non-REUSEADDR
   bind from another service.
"""
import json
import socket
import sys
import threading
import signal
import os


def load_config(path):
    with open(path) as f:
        return json.load(f)


class PortAllocator:
    """Port allocator with per-destination tracking."""

    def __init__(self, port_range):
        self.lo, self.hi = port_range
        self.used_by_dest = {}
        self.lock = threading.Lock()

    def allocate(self, dest_ip, dest_port):
        with self.lock:
            key = (dest_ip, dest_port)
            if key not in self.used_by_dest:
                self.used_by_dest[key] = set()
            used = self.used_by_dest[key]
            for p in range(self.lo, self.hi + 1):
                if p not in used:
                    used.add(p)
                    return p
            raise OSError(
                f"Port pool exhausted for destination {dest_ip}:{dest_port}"
            )

    def reserve(self, port, dest_ip, dest_port):
        with self.lock:
            key = (dest_ip, dest_port)
            if key not in self.used_by_dest:
                self.used_by_dest[key] = set()
            self.used_by_dest[key].add(port)


def create_connection(source_ip, dest_ip, dest_port, source_port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5.0)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((source_ip, source_port))
    sock.connect((dest_ip, dest_port))
    return sock


class ServiceProxy:
    def __init__(self, name, source_ip, dest_ip, dest_port, num_connections,
                 allocator, source_port_range=None):
        self.name = name
        self.source_ip = source_ip
        self.dest_ip = dest_ip
        self.dest_port = dest_port
        self.num_connections = num_connections
        self.allocator = allocator
        self.source_port_range = source_port_range
        self.connections = []
        self.connection_details = []
        self.errors = []
        self.lock = threading.Lock()

    def establish_connections(self):
        for i in range(self.num_connections):
            try:
                if self.source_port_range:
                    lo, hi = self.source_port_range
                    src_port = lo + (i % (hi - lo + 1))
                    self.allocator.reserve(
                        src_port, self.dest_ip, self.dest_port
                    )
                else:
                    src_port = self.allocator.allocate(
                        self.dest_ip, self.dest_port
                    )

                sock = create_connection(
                    self.source_ip, self.dest_ip, self.dest_port, src_port
                )
                data = sock.recv(1024)
                actual_port = sock.getsockname()[1]

                with self.lock:
                    self.connections.append(sock)
                    self.connection_details.append({
                        "src_port": actual_port,
                        "dst": f"{self.dest_ip}:{self.dest_port}"
                    })
            except OSError as e:
                with self.lock:
                    self.errors.append(str(e))

    def close_all(self):
        with self.lock:
            for sock in self.connections:
                try:
                    sock.close()
                except Exception:
                    pass
            self.connections.clear()

    def status(self):
        with self.lock:
            return {
                "name": self.name,
                "connected": len(self.connections),
                "errors": len(self.errors),
                "error_messages": self.errors[:5],
                "connections": list(self.connection_details)
            }


def main():
    config_path = "/app/config.json"
    if len(sys.argv) > 1:
        config_path = sys.argv[1]

    config = load_config(config_path)

    allocator = PortAllocator(config["source_port_pool"])

    services = []
    for svc_cfg in config["services"]:
        svc = ServiceProxy(
            name=svc_cfg["name"],
            source_ip=svc_cfg["source_ip"],
            dest_ip=svc_cfg["dest_ip"],
            dest_port=svc_cfg["dest_port"],
            num_connections=svc_cfg["num_connections"],
            allocator=allocator,
            source_port_range=svc_cfg.get("source_port_range")
        )
        services.append(svc)

    # Fixed-port services must connect first to properly reserve their
    # ports and set bind-bucket fastreuse to +1.
    fixed_port_services = [s for s in services if s.source_port_range]
    auto_port_services = [s for s in services if not s.source_port_range]

    for svc in fixed_port_services:
        svc.establish_connections()

    threads = []
    for svc in auto_port_services:
        t = threading.Thread(target=svc.establish_connections)
        t.start()
        threads.append(t)

    for t in threads:
        t.join(timeout=30)

    results = {}
    total_connected = 0
    total_errors = 0
    for svc in services:
        s = svc.status()
        results[s["name"]] = s
        total_connected += s["connected"]
        total_errors += s["errors"]

    results["summary"] = {
        "total_connected": total_connected,
        "total_errors": total_errors
    }

    with open("/app/proxy_results.json", "w") as f:
        json.dump(results, f, indent=2)

    sys.stderr.write(
        f"Proxy: {total_connected} connections, {total_errors} errors\n"
    )
    sys.stderr.flush()

    evt = threading.Event()
    signal.signal(signal.SIGTERM, lambda s, f: evt.set())
    signal.signal(signal.SIGINT, lambda s, f: evt.set())
    evt.wait(timeout=120)

    for svc in services:
        svc.close_all()


if __name__ == "__main__":
    main()
