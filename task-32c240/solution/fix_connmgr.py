#!/usr/bin/env python3
"""
Apply UDP overshadowing prevention to the connection manager.

Adds /proc/net/udp-based conflict detection and the SO_REUSEADDR
toggle trick for atomic check-then-connect in create_udp_connection().

The key insight: /proc/net/udp exposes all UDP sockets system-wide with
their local/remote addresses and connection state. Connected sockets
(state 01) with matching 4-tuples indicate an overshadowing conflict.
IP addresses appear as little-endian 32-bit hex and ports as big-endian
16-bit hex.

"""

import sys

PATH = '/app/connmgr.py'

with open(PATH, 'r') as f:
    src = f.read()

# ── 1. Insert _check_udp_4tuple_conflict before ConnectionManager ─────
#
# Parses /proc/net/udp to find connected (state 01) UDP sockets whose
# local and remote addresses match the requested 4-tuple.  This detects
# conflicts with ALL sockets system-wide, including those created outside
# this ConnectionManager instance.
#
# /proc/net/udp format per line:
#   sl  local_address rem_address   st ...
# where addresses are HEXIP:HEXPORT (IP in little-endian 32-bit hex,
# port in plain 16-bit hex), and st=01 means connected (TCP_ESTABLISHED).

CONFLICT_FUNC = '''

def _check_udp_4tuple_conflict(src_ip, src_port, dst_ip, dst_port):
    """Check /proc/net/udp for connected UDP socket matching the 4-tuple.

    Scans the kernel procfs UDP socket table for any connected socket
    (state 01 / TCP_ESTABLISHED) whose local and remote addresses match
    the given 4-tuple.  Detects conflicts with all sockets system-wide.

    IP addresses in /proc/net/udp are 32-bit little-endian hex; ports
    are 16-bit hex (already in host byte order after ntohs in kernel).
    """
    # Convert to /proc/net/udp hex format
    src_ip_hex = '{:08X}'.format(
        int.from_bytes(socket.inet_aton(src_ip), byteorder='little'))
    dst_ip_hex = '{:08X}'.format(
        int.from_bytes(socket.inet_aton(dst_ip), byteorder='little'))
    local_hex = '{}:{:04X}'.format(src_ip_hex, src_port)
    remote_hex = '{}:{:04X}'.format(dst_ip_hex, dst_port)

    try:
        with open('/proc/net/udp', 'r') as f:
            for line in f:
                fields = line.split()
                if len(fields) < 4:
                    continue
                # Skip header (first field is 'sl', not 'N:')
                if ':' not in fields[0]:
                    continue
                if (fields[3] == '01'
                        and fields[1] == local_hex
                        and fields[2] == remote_hex):
                    return True
    except (OSError, IOError):
        pass
    return False


'''

src = src.replace(
    '\nclass ConnectionManager:',
    CONFLICT_FUNC + 'class ConnectionManager:',
)

# ── 2. Replace create_udp_connection with conflict-detecting version ──

udp_start = src.index('    def create_udp_connection')
close_start = src.index('    def close_connection')

NEW_UDP = '''\
    def create_udp_connection(self, dst_ip, dst_port, src_ip=None, src_port=0):
        """Create UDP connection with overshadowing prevention.

        Uses /proc/net/udp to detect existing connected sockets with the
        same 4-tuple, and the SO_REUSEADDR toggle trick for atomic
        check-then-connect to prevent races.

        The SO_REUSEADDR toggle works as follows:
        1. Bind with SO_REUSEADDR=1 (allows sharing the port)
        2. Clear SO_REUSEADDR=0 (prevents OTHER sockets from binding
           to the same port while we check for conflicts — the kernel
           requires BOTH sockets to have SO_REUSEADDR for bind to
           succeed on UDP)
        3. Check /proc/net/udp for existing connected 4-tuple match
        4. If safe, connect() and restore SO_REUSEADDR=1
        """
        if src_ip is None:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(5)
            sock.connect((dst_ip, dst_port))
            with self._lock:
                self._connections.append(sock)
            return sock

        max_retries = 16
        for _attempt in range(max_retries):
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(5)
            try:
                # Step 1: Enable port sharing for bind
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                if src_port != 0:
                    sock.bind((src_ip, src_port))
                else:
                    sock.bind((src_ip, 0))

                # Step 2: Clear SO_REUSEADDR to lock port during check
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)

                bound_ip, bound_port = sock.getsockname()

                # Step 3: Check for existing connected socket with same 4-tuple
                if _check_udp_4tuple_conflict(
                        bound_ip, bound_port, dst_ip, dst_port):
                    sock.close()
                    if src_port != 0:
                        raise ConnectionConflictError(
                            f"UDP 4-tuple conflict: "
                            f"{bound_ip}:{bound_port} -> "
                            f"{dst_ip}:{dst_port}")
                    # Auto-port: retry with a different port
                    continue

                # Step 4: No conflict — connect and restore SO_REUSEADDR
                sock.connect((dst_ip, dst_port))
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

                with self._lock:
                    self._connections.append(sock)
                return sock

            except ConnectionConflictError:
                raise
            except Exception:
                try:
                    sock.close()
                except Exception:
                    pass
                raise

        raise ConnectionConflictError(
            f"No non-conflicting port after {max_retries} retries "
            f"for {dst_ip}:{dst_port}")

'''

src = src[:udp_start] + NEW_UDP + src[close_start:]

# ── Write fixed file ──────────────────────────────────────────────────
with open(PATH, 'w') as f:
    f.write(src)

# ── Verify fixes landed ──────────────────────────────────────────────
with open(PATH, 'r') as f:
    result = f.read()

assert '_check_udp_4tuple_conflict' in result, 'Conflict check function missing'
assert '/proc/net/udp' in result, 'procfs UDP scan missing'
assert 'SO_REUSEADDR, 0' in result, 'SO_REUSEADDR toggle missing'
assert 'ConnectionConflictError' in result, 'Error class not referenced'
assert 'create_tcp_connection' in result, 'TCP method missing'
assert 'IP_BIND_ADDRESS_NO_PORT' in result, 'TCP auto-port fix missing'

print('Fix applied successfully.')
print()
print('Changes:')
print('  + _check_udp_4tuple_conflict(): /proc/net/udp 4-tuple scanner')
print('  + SO_REUSEADDR toggle trick for atomic conflict detection')
print('  + create_udp_connection() prevents 4-tuple overshadowing')
print('  + Auto-port retries on conflict, explicit port raises error')
print('  TCP path unchanged.')
