#!/usr/bin/env python3
"""

Fix the proxy.py to handle ephemeral port reuse correctly.

Three key fixes:
1. For Services A and B (automatic port selection): use IP_BIND_ADDRESS_NO_PORT
   so that bind() only records the source IP, deferring port allocation to
   connect() time. This keeps the bind bucket fastreuse state at -1, allowing
   the kernel to reuse source ports across different destinations.

2. For Service C (fixed source ports): use SO_REUSEADDR so that bind() to
   an already-used port succeeds. This is required because the same port
   might be in use by a connected socket from Service A or B.

3. Connection ordering: establish Service C connections first, so their
   SO_REUSEADDR+bind creates buckets in fastreuse=+1 state. Then Services
   A and B use IP_BIND_ADDRESS_NO_PORT+connect which creates/transitions
   buckets to fastreuse=-1. If we did it the other way, Service A/B's
   connect() would create buckets at fastreuse=-1, then Service C's bind()
   without SO_REUSEADDR would transition them to fastreuse=0, blocking
   further connect()-based port allocation.

   Actually, the key insight is simpler: with IP_BIND_ADDRESS_NO_PORT,
   Services A and B don't call bind() with a port at all - the kernel
   picks the port during connect() and the bucket stays at fastreuse=-1.
   Service C uses SO_REUSEADDR + explicit port, which either creates a
   new bucket at fastreuse=+1 or (if the port was already used by A/B)
   transitions it. But since connect()-allocated buckets (fastreuse=-1)
   allow bind() with SO_REUSEADDR (checking only IP conflicts), this works.

   The real fix is ensuring Service C uses SO_REUSEADDR so it doesn't
   create buckets with fastreuse=0, which would block connect() port
   allocation for A and B on those specific ports.
"""

FIXED_PROXY = '''#!/usr/bin/env python3
"""
Multi-tenant TCP proxy - fixed version with proper ephemeral port handling.
"""
import json
import socket
import sys
import time
import threading
import signal
import os

IP_BIND_ADDRESS_NO_PORT = 24

def load_config(path):
    with open(path) as f:
        return json.load(f)

def create_connection(source_ip, dest_ip, dest_port, source_port=None):
    """
    Create a TCP connection using bind-before-connect pattern.
    Fixed to properly handle ephemeral port reuse.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5.0)

    if source_port is not None:
        # Fixed source port for audit logging (Service C)
        # FIX: Use SO_REUSEADDR so we can bind to a port that may already
        # be in use by a connected socket going to a different destination.
        # This also ensures the bind bucket fastreuse state stays at +1
        # (not 0), so it doesn\'t block connect()-based port allocation.
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((source_ip, source_port))
    else:
        # Automatic port selection
        # FIX: Use IP_BIND_ADDRESS_NO_PORT to defer port allocation to
        # connect() time. This means bind() only records the source IP,
        # and connect() picks a port that forms a unique 4-tuple.
        # The bind bucket fastreuse state stays at -1, allowing the
        # kernel to reuse source ports across different destinations.
        sock.setsockopt(socket.IPPROTO_IP, IP_BIND_ADDRESS_NO_PORT, 1)
        sock.bind((source_ip, 0))

    sock.connect((dest_ip, dest_port))
    return sock


class ServiceProxy:
    def __init__(self, name, source_ip, dest_ip, dest_port, num_connections,
                 source_port_range=None):
        self.name = name
        self.source_ip = source_ip
        self.dest_ip = dest_ip
        self.dest_port = dest_port
        self.num_connections = num_connections
        self.source_port_range = source_port_range
        self.connections = []
        self.errors = []
        self.lock = threading.Lock()

    def establish_connections(self):
        """Open all connections for this service."""
        for i in range(self.num_connections):
            try:
                if self.source_port_range:
                    lo, hi = self.source_port_range
                    src_port = lo + (i % (hi - lo + 1))
                    sock = create_connection(
                        self.source_ip, self.dest_ip, self.dest_port,
                        source_port=src_port
                    )
                else:
                    sock = create_connection(
                        self.source_ip, self.dest_ip, self.dest_port
                    )
                data = sock.recv(1024)
                with self.lock:
                    self.connections.append(sock)
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
                "error_messages": self.errors[:5]
            }


def setup_loopback_aliases():
    """Add loopback aliases for backend IPs."""
    for ip in ["127.10.0.1", "127.10.0.2", "127.10.0.3"]:
        os.system(f"ip addr add {ip}/32 dev lo 2>/dev/null || true")


def main():
    config_path = "/app/config.json"
    if len(sys.argv) > 1:
        config_path = sys.argv[1]

    config = load_config(config_path)

    lo, hi = config["ephemeral_port_range"]
    os.system(f"sysctl -w net.ipv4.ip_local_port_range=\\'{lo} {hi}\\' >/dev/null 2>&1")

    setup_loopback_aliases()

    services = []
    for svc_cfg in config["services"]:
        svc = ServiceProxy(
            name=svc_cfg["name"],
            source_ip=svc_cfg["source_ip"],
            dest_ip=svc_cfg["dest_ip"],
            dest_port=svc_cfg["dest_port"],
            num_connections=svc_cfg["num_connections"],
            source_port_range=svc_cfg.get("source_port_range")
        )
        services.append(svc)

    # FIX: Establish Service C (fixed ports) first to avoid fastreuse poisoning.
    # Service C uses SO_REUSEADDR+bind, creating buckets at fastreuse=+1.
    # Then Services A and B use IP_BIND_ADDRESS_NO_PORT, which defers to
    # connect() and keeps buckets at fastreuse=-1 for auto-allocated ports.
    fixed_port_services = [s for s in services if s.source_port_range]
    auto_port_services = [s for s in services if not s.source_port_range]

    # First: fixed-port services (sequentially to avoid races)
    for svc in fixed_port_services:
        svc.establish_connections()

    # Then: auto-port services (can run in parallel)
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

    result_path = "/app/proxy_results.json"
    with open(result_path, "w") as f:
        json.dump(results, f, indent=2)

    print(json.dumps(results, indent=2), flush=True)
    print(f"Proxy running: {total_connected} connections, {total_errors} errors", flush=True)
    print("Waiting for verification...", flush=True)

    evt = threading.Event()
    signal.signal(signal.SIGTERM, lambda s, f: evt.set())
    signal.signal(signal.SIGINT, lambda s, f: evt.set())
    evt.wait(timeout=60)

    for svc in services:
        svc.close_all()


if __name__ == "__main__":
    main()
'''

def main():
    # Write the fixed proxy
    with open("/app/proxy.py", "w") as f:
        f.write(FIXED_PROXY)

    # Remove stale results if they exist
    import os
    try:
        os.unlink("/app/proxy_results.json")
    except FileNotFoundError:
        pass

    print("Fixed proxy.py written to /app/proxy.py")

if __name__ == "__main__":
    main()
