#!/usr/bin/env python3
"""
Multi-tenant TCP proxy with explicit source port pool management.
Each outgoing connection is bound to a source port from a configured
pool before connecting to the target backend.
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
    """Manages the source port pool for outgoing connections."""

    def __init__(self, port_range):
        self.lo, self.hi = port_range
        self.used = set()
        self.lock = threading.Lock()

    def allocate(self):
        """Get the next available port from the pool."""
        with self.lock:
            for p in range(self.lo, self.hi + 1):
                if p not in self.used:
                    self.used.add(p)
                    return p
            raise OSError(
                f"Port pool exhausted: all {self.hi - self.lo + 1} ports "
                f"in range {self.lo}-{self.hi} are in use"
            )

    def release(self, port):
        with self.lock:
            self.used.discard(port)


def create_connection(source_ip, dest_ip, dest_port, source_port):
    """Create a TCP connection binding to source_port first."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5.0)
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
                else:
                    src_port = self.allocator.allocate()

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

    threads = []
    for svc in services:
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

    result_path = "/app/proxy_results.json"
    with open(result_path, "w") as f:
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
