"""
connectx — UDP connect with source port reuse and overshadowing prevention.

Implements the "SO_REUSEADDR as a lock" pattern:
  1. Enable SO_REUSEADDR → bind (allows sharing the port)
  2. Disable SO_REUSEADDR (locks port against concurrent binders)
  3. Query kernel for existing connected socket on the desired 4-tuple
  4. If conflict detected → raise OSError
  5. connect() → socket is now connected
  6. Re-enable SO_REUSEADDR (unlocks port for future sharing)

Socket lookup uses netlink SOCK_DIAG with /proc/net/udp fallback.
"""

import socket
import struct
import os
import random
import errno

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SO_COOKIE = 57
NETLINK_SOCK_DIAG = 4
SOCK_DIAG_BY_FAMILY = 20
IPPROTO_UDP = 17
NLMSG_ERROR = 2
NLM_F_REQUEST = 1

_ephemeral_range = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_ephemeral_range():
    """Return (low, high) from /proc/sys/net/ipv4/ip_local_port_range."""
    global _ephemeral_range
    if _ephemeral_range is None:
        with open("/proc/sys/net/ipv4/ip_local_port_range") as f:
            parts = f.read().strip().split()
            _ephemeral_range = (int(parts[0]), int(parts[1]))
    return _ephemeral_range


def udp_socket_lookup(family, src_addr, dst_addr):
    """
    Query the kernel for a connected UDP socket matching the 4-tuple.

    Uses netlink SOCK_DIAG (fast, exact lookup via __udp4_lib_lookup)
    with a /proc/net/udp fallback if netlink is unavailable.

    Returns an identifier (bytes) if found, None otherwise.
    """
    result = _netlink_udp_lookup(family, src_addr, dst_addr)
    if result is not None:
        return result
    return _proc_udp_lookup(src_addr, dst_addr)


def udp_connectx(src_ip, src_port, dst_ip, dst_port):
    """
    Create a connected SOCK_DGRAM socket with source port reuse
    and overshadowing prevention.

    Raises OSError if the desired 4-tuple is already in use.
    """
    family = socket.AF_INET

    # Discover source IP if not provided
    if src_ip is None:
        src_ip = _discover_source_ip(dst_ip)

    # Automatic port selection: try ports from the ephemeral range
    if src_port is None or src_port == 0:
        lo, hi = get_ephemeral_range()
        count = hi - lo + 1
        start = random.randint(lo, hi)

        last_err = None
        for attempt in range(count):
            port = lo + (start - lo + attempt) % count
            try:
                return _connectx_locked(family, src_ip, port, dst_ip, dst_port)
            except OSError as e:
                last_err = e
                if e.errno in (errno.EADDRINUSE, errno.EADDRNOTAVAIL):
                    continue
                raise

        raise OSError(errno.EAGAIN, "No available ephemeral port") from last_err

    # Fixed port
    return _connectx_locked(family, src_ip, src_port, dst_ip, dst_port)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _discover_source_ip(dst_ip):
    """Discover the source IP the kernel would choose for *dst_ip*."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect((dst_ip, 1))
        return probe.getsockname()[0]
    finally:
        probe.close()


def _connectx_locked(family, src_ip, src_port, dst_ip, dst_port):
    """
    Create a connected UDP socket using the SO_REUSEADDR locking dance.

    The pattern:
      1. setsockopt(SO_REUSEADDR, 1)   — allows bind to a shared port
      2. bind(src_ip, src_port)
      3. setsockopt(SO_REUSEADDR, 0)   — LOCK: blocks concurrent binders
      4. kernel lookup for 4-tuple conflict
      5. connect(dst_ip, dst_port)
      6. setsockopt(SO_REUSEADDR, 1)   — UNLOCK: re-allow sharing
    """
    sd = socket.socket(family, socket.SOCK_DGRAM)
    try:
        # Obtain this socket's cookie so we can distinguish "self" from "other"
        my_cookie = sd.getsockopt(socket.SOL_SOCKET, SO_COOKIE, 8)

        # Step 1: enable REUSEADDR so bind can share the port
        sd.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # Step 2: bind
        sd.bind((src_ip, src_port))

        # Step 3: LOCK — clear REUSEADDR to prevent concurrent binders
        sd.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)

        # Step 4: check for an existing CONNECTED socket with our 4-tuple
        existing = udp_socket_lookup(
            family, (src_ip, src_port), (dst_ip, dst_port)
        )
        if existing is not None and existing != my_cookie:
            raise OSError(
                errno.EADDRINUSE,
                f"4-tuple conflict: {src_ip}:{src_port} -> {dst_ip}:{dst_port}",
            )

        # Step 5: connect
        sd.connect((dst_ip, dst_port))

        # Step 6: UNLOCK — re-enable REUSEADDR for future sharing
        sd.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        return sd
    except BaseException:
        sd.close()
        raise


# ---------------------------------------------------------------------------
# Netlink SOCK_DIAG lookup (primary)
# ---------------------------------------------------------------------------

def _netlink_udp_lookup(family, src_addr, dst_addr):
    """
    Use SOCK_DIAG netlink to look up a connected UDP socket by 4-tuple.

    Sends an inet_diag_req_v2 with the exact 4-tuple.  The kernel calls
    __udp4_lib_lookup() which returns the *best-match* socket — this may
    be a wildcard/unconnected socket bound to the destination port rather
    than an exact 4-tuple match.  We therefore verify the returned
    socket's actual sport/dport/src/dst against our query before
    declaring a hit.

    Returns the 8-byte socket cookie on exact match, None otherwise.
    """
    if family != socket.AF_INET:
        return None

    try:
        nl = socket.socket(socket.AF_NETLINK, socket.SOCK_DGRAM, NETLINK_SOCK_DIAG)
        nl.settimeout(2)
    except OSError:
        return None

    try:
        # --- Build inet_diag_sockid (48 bytes) ---
        # sport, dport: network byte order (__be16)
        sockid = struct.pack("!HH", src_addr[1], dst_addr[1])
        # src[4]: 16 bytes (only first __be32 used for IPv4)
        sockid += socket.inet_aton(src_addr[0]) + b"\x00" * 12
        # dst[4]: 16 bytes
        sockid += socket.inet_aton(dst_addr[0]) + b"\x00" * 12
        # idiag_if: host order __u32
        sockid += struct.pack("=I", 0)
        # idiag_cookie: INET_DIAG_NOCOOKIE
        sockid += struct.pack("=II", 0xFFFFFFFF, 0xFFFFFFFF)

        # --- Build inet_diag_req_v2 (8 + 48 = 56 bytes) ---
        req = struct.pack(
            "=BBBBI",
            socket.AF_INET,   # sdiag_family
            IPPROTO_UDP,      # sdiag_protocol
            0,                # idiag_ext
            0,                # pad
            0xFFFFFFFF,       # idiag_states  (all states)
        )
        req += sockid

        # --- Build nlmsghdr (16 bytes) + payload ---
        msg_len = 16 + len(req)
        nlmsg = struct.pack(
            "=IHHII",
            msg_len,
            SOCK_DIAG_BY_FAMILY,   # nlmsg_type
            NLM_F_REQUEST,         # nlmsg_flags  (exact lookup, no DUMP)
            1,                     # nlmsg_seq
            0,                     # nlmsg_pid
        )
        nlmsg += req

        nl.send(nlmsg)

        data = nl.recv(65536)
        if len(data) < 16:
            return None

        nlmsg_len, nlmsg_type = struct.unpack_from("=IH", data, 0)

        if nlmsg_type == NLMSG_ERROR:
            # negative errno → not found; 0 → ack (shouldn't happen for GET)
            return None

        if nlmsg_type == SOCK_DIAG_BY_FAMILY:
            # inet_diag_msg layout after nlmsghdr (16 bytes):
            #   family(1) state(1) timer(1) retrans(1)     → offset 16..19
            #   inet_diag_sockid:
            #     sport(2) dport(2)                         → offset 20..23
            #     src[4](16)                                → offset 24..39
            #     dst[4](16)                                → offset 40..55
            #     idiag_if(4)                               → offset 56..59
            #     idiag_cookie[2](8)                        → offset 60..67
            if len(data) >= 68:
                # The kernel's __udp4_lib_lookup returns the best-match
                # socket, which may be a wildcard listener bound to the
                # destination port.  Verify the returned socket's actual
                # addresses match our query exactly — otherwise we'd
                # false-positive on every ephemeral port when a server
                # socket exists on the destination.
                resp_sport, resp_dport = struct.unpack_from("!HH", data, 20)
                resp_src_ip = socket.inet_ntoa(data[24:28])
                resp_dst_ip = socket.inet_ntoa(data[40:44])

                if (resp_sport == src_addr[1] and
                        resp_dport == dst_addr[1] and
                        resp_src_ip == src_addr[0] and
                        resp_dst_ip == dst_addr[0]):
                    return data[60:68]

        return None
    except (OSError, socket.timeout):
        return None
    finally:
        nl.close()


# ---------------------------------------------------------------------------
# /proc/net/udp fallback lookup
# ---------------------------------------------------------------------------

def _proc_udp_lookup(src_addr, dst_addr):
    """
    Parse /proc/net/udp to find a connected UDP socket matching the 4-tuple.

    Addresses in /proc/net/udp are little-endian hex u32, ports are hex.
    """
    src_hex = _addr_to_proc_hex(src_addr)
    dst_hex = _addr_to_proc_hex(dst_addr)

    try:
        with open("/proc/net/udp") as f:
            f.readline()  # skip header
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 10 and parts[1] == src_hex and parts[2] == dst_hex:
                    # Return inode as an identifier
                    return parts[9].encode()
    except OSError:
        pass
    return None


def _addr_to_proc_hex(addr):
    """Convert (ip_str, port) to the hex format used in /proc/net/udp."""
    ip_bytes = socket.inet_aton(addr[0])
    ip_le = struct.unpack("<I", ip_bytes)[0]
    return f"{ip_le:08X}:{addr[1]:04X}"
