#!/usr/bin/env python3
"""
TCP bind bucket fastreuse state machine oracle.

Simulates the Linux kernel's TCP port allocation behavior by modeling:
- Bind buckets with fastreuse states (-1, 0, +1)
- The bind path (inet_csk_get_port) for explicit bind() calls
- The connect path (__inet_hash_connect) for connect() without prior bind
- SO_REUSEADDR and IP_BIND_ADDRESS_NO_PORT interactions
- Per-owner IP conflict resolution and 4-tuple uniqueness checks

"""

import json
import sys


class BindBucket:
    """Represents a TCP bind bucket keyed by port number."""

    def __init__(self, port):
        self.port = port
        self.fastreuse = None  # -1, 0, or +1
        self.owner_ids = []    # socket IDs in this bucket


class Socket:
    """Represents a TCP socket with its options and state."""

    def __init__(self, sock_id):
        self.id = sock_id
        self.reuseaddr = False
        self.bind_address_no_port = False
        self.bound_ip = None
        self.bound_port = None
        self.connected = False
        self.dst_ip = None
        self.dst_port = None


class Oracle:
    """Simulates the Linux TCP bind bucket fastreuse state machine."""

    def __init__(self, config):
        self.eph_lo = config["ephemeral_range"][0]
        self.eph_hi = config["ephemeral_range"][1]
        self.auto_src_ip = config.get("auto_src_ip", "127.0.0.1")
        self.buckets = {}   # port -> BindBucket
        self.sockets = {}   # id -> Socket

    def process(self, operations):
        results = []
        for op in operations:
            result = self._dispatch(op)
            result["step"] = op["step"]
            results.append(result)

        final_buckets = {}
        for port, bucket in self.buckets.items():
            if bucket.owner_ids:
                final_buckets[str(port)] = {
                    "fastreuse": bucket.fastreuse,
                    "num_owners": len(bucket.owner_ids),
                }

        return {"steps": results, "final_buckets": final_buckets}

    def _dispatch(self, op):
        action = op["action"]
        if action == "socket":
            return self._op_socket(op["id"])
        elif action == "setsockopt":
            return self._op_setsockopt(op["id"], op["option"], op["value"])
        elif action == "bind":
            return self._op_bind(op["id"], op["ip"], op["port"])
        elif action == "connect":
            return self._op_connect(op["id"], op["dst_ip"], op["dst_port"])
        elif action == "close":
            return self._op_close(op["id"])
        return {"outcome": "error", "errno": "EINVAL"}

    # ----- Socket lifecycle operations -----

    def _op_socket(self, sock_id):
        self.sockets[sock_id] = Socket(sock_id)
        return {"outcome": "success"}

    def _op_setsockopt(self, sock_id, option, value):
        sock = self.sockets[sock_id]
        if option == "SO_REUSEADDR":
            sock.reuseaddr = bool(value)
        elif option == "IP_BIND_ADDRESS_NO_PORT":
            sock.bind_address_no_port = bool(value)
        return {"outcome": "success"}

    def _op_bind(self, sock_id, ip, port):
        sock = self.sockets[sock_id]

        # IP_BIND_ADDRESS_NO_PORT with port 0: record IP, defer port to connect
        if sock.bind_address_no_port and port == 0:
            sock.bound_ip = ip
            return {"outcome": "success"}

        if port == 0:
            # Ephemeral auto-assignment via inet_csk_get_port
            for p in range(self.eph_lo, self.eph_hi + 1):
                if self._bind_path_can_use(sock, ip, p):
                    sock.bound_ip = ip
                    sock.bound_port = p
                    self._bucket_add_via_bind(sock, p)
                    return {"outcome": "success", "port": p}
            return {"outcome": "error", "errno": "EADDRINUSE"}
        else:
            # Specific port via inet_csk_get_port
            if self._bind_path_can_use(sock, ip, port):
                sock.bound_ip = ip
                sock.bound_port = port
                self._bucket_add_via_bind(sock, port)
                return {"outcome": "success", "port": port}
            return {"outcome": "error", "errno": "EADDRINUSE"}

    def _op_connect(self, sock_id, dst_ip, dst_port):
        sock = self.sockets[sock_id]

        if sock.bound_port is not None:
            # Already fully bound -> just check ehash for 4-tuple conflict
            if self._ehash_conflict(sock.bound_ip, sock.bound_port,
                                    dst_ip, dst_port, exclude=sock_id):
                return {"outcome": "error", "errno": "EADDRNOTAVAIL"}
            sock.connected = True
            sock.dst_ip = dst_ip
            sock.dst_port = dst_port
            return {"outcome": "success"}

        # No port bound -> use __inet_hash_connect path
        src_ip = sock.bound_ip if sock.bound_ip else self.auto_src_ip

        for p in range(self.eph_lo, self.eph_hi + 1):
            if p not in self.buckets:
                # Empty slot: create bucket with fastreuse=-1
                self._finalize_connect(sock, src_ip, p, dst_ip, dst_port)
                return {"outcome": "success", "port": p}

            bucket = self.buckets[p]

            # __inet_hash_connect skips buckets with fastreuse != -1
            if bucket.fastreuse != -1:
                continue

            # Check ehash for 4-tuple conflict
            if not self._ehash_conflict(src_ip, p, dst_ip, dst_port,
                                        exclude=sock_id):
                self._finalize_connect(sock, src_ip, p, dst_ip, dst_port)
                return {"outcome": "success", "port": p}

        return {"outcome": "error", "errno": "EADDRNOTAVAIL"}

    def _op_close(self, sock_id):
        sock = self.sockets[sock_id]
        if sock.bound_port is not None and sock.bound_port in self.buckets:
            bucket = self.buckets[sock.bound_port]
            if sock_id in bucket.owner_ids:
                bucket.owner_ids.remove(sock_id)
            if not bucket.owner_ids:
                del self.buckets[sock.bound_port]
        del self.sockets[sock_id]
        return {"outcome": "success"}

    # ----- Bind path logic (inet_csk_get_port) -----

    def _bind_path_can_use(self, sock, ip, port):
        """Can this socket bind to the given port via the bind path?"""
        if port not in self.buckets:
            return True

        bucket = self.buckets[port]

        # Fast path: fastreuse == +1 and socket has SO_REUSEADDR -> skip checks
        if bucket.fastreuse == 1 and sock.reuseaddr:
            return True

        # Slow path: check each owner for IP conflict
        for owner_id in bucket.owner_ids:
            owner = self.sockets[owner_id]
            if self._bind_conflict(sock, ip, owner):
                return False

        return True

    def _bind_conflict(self, new_sock, new_ip, existing_sock):
        """inet_csk_bind_conflict: does a new bind conflict with existing?"""
        existing_ip = existing_sock.bound_ip

        # Different IPs -> no conflict
        if new_ip != existing_ip:
            return False

        # Same IP: both must have SO_REUSEADDR (and existing not LISTEN)
        if new_sock.reuseaddr and existing_sock.reuseaddr:
            return False

        # Same IP, not both REUSEADDR -> conflict
        return True

    # ----- Connect path logic (__inet_hash_connect) -----

    def _ehash_conflict(self, src_ip, src_port, dst_ip, dst_port, exclude=None):
        """Check established-connection hash for 4-tuple conflict."""
        for sid, sock in self.sockets.items():
            if sid == exclude:
                continue
            if not sock.connected:
                continue
            if (sock.bound_ip == src_ip and
                    sock.bound_port == src_port and
                    sock.dst_ip == dst_ip and
                    sock.dst_port == dst_port):
                return True
        return False

    def _finalize_connect(self, sock, src_ip, port, dst_ip, dst_port):
        """Assign port and add socket to bucket via connect path."""
        sock.bound_ip = src_ip
        sock.bound_port = port
        sock.connected = True
        sock.dst_ip = dst_ip
        sock.dst_port = dst_port
        self._bucket_add_via_connect(sock, port)

    # ----- Bucket state management -----

    def _bucket_add_via_bind(self, sock, port):
        """Add socket to bucket via bind path (inet_csk_update_fastreuse)."""
        if port not in self.buckets:
            bucket = BindBucket(port)
            bucket.fastreuse = 1 if sock.reuseaddr else 0
            self.buckets[port] = bucket
        else:
            bucket = self.buckets[port]
            if not sock.reuseaddr:
                # Bind without REUSEADDR always forces fastreuse to 0
                bucket.fastreuse = 0
            elif bucket.fastreuse == -1:
                # REUSEADDR bind on a connect-allocated bucket: -1 -> +1
                bucket.fastreuse = 1
            # +1 with REUSEADDR: stays +1
            # 0 with REUSEADDR: stays 0

        bucket.owner_ids.append(sock.id)

    def _bucket_add_via_connect(self, sock, port):
        """Add socket to bucket via connect path."""
        if port not in self.buckets:
            bucket = BindBucket(port)
            bucket.fastreuse = -1
            self.buckets[port] = bucket
        # If bucket exists, it must have fastreuse == -1 to reach here
        self.buckets[port].owner_ids.append(sock.id)


def main():
    with open("/app/scenario.json") as f:
        scenario = json.load(f)

    oracle = Oracle(scenario["config"])
    results = oracle.process(scenario["operations"])

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
