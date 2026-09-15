"""
Diagnose and fix the ephemeral port exhaustion bugs in the proxy connection manager.

The proxy uses bind-before-connect for source IP separation, but the current
implementation prevents the Linux kernel from reusing source ports.  Three
targeted socket-option fixes are needed:

1. TCP auto-port: IP_BIND_ADDRESS_NO_PORT defers port allocation to connect()
   so the kernel can consider the full 4-tuple and reuse source ports.

2. TCP explicit port: SO_REUSEADDR lets a second socket bind to a port already
   held by another socket; connect() still prevents true 4-tuple duplicates.

3. UDP: SO_REUSEADDR enables source-port sharing.  Unlike TCP, vanilla UDP on
   Linux limits total connected sockets to the ephemeral range size even across
   different destinations because the kernel reserves a unique 2-tuple per socket.
"""

import sys

PROXY_PATH = '/app/proxy.py'

with open(PROXY_PATH, 'r') as f:
    content = f.read()

# ── Locate method boundaries so replacements don't cross methods ──────────
tcp_start = content.index('def create_tcp_connection')
udp_start = content.index('def create_udp_connection')
close_start = content.index('def close_all')

preamble = content[:tcp_start]
tcp_body = content[tcp_start:udp_start]
udp_body = content[udp_start:close_start]
close_body = content[close_start:]

# ── Fix 1: TCP auto-port ─────────────────────────────────────────────────
# Insert IP_BIND_ADDRESS_NO_PORT setsockopt before bind((src_ip, 0)).
# This tells the kernel to defer source port selection until connect(),
# enabling 4-tuple-aware port reuse across different destinations.
tcp_body = tcp_body.replace(
    '                sock.bind((src_ip, 0))',
    '                sock.setsockopt(socket.IPPROTO_IP, IP_BIND_ADDRESS_NO_PORT, 1)\n'
    '                sock.bind((src_ip, 0))',
)

# ── Fix 2: TCP explicit port ─────────────────────────────────────────────
# Insert SO_REUSEADDR before bind((src_ip, src_port)).
# This allows two sockets to share a source 2-tuple as long as they
# connect to different destinations (different full 4-tuples).
tcp_body = tcp_body.replace(
    '                sock.bind((src_ip, src_port))',
    '                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n'
    '                sock.bind((src_ip, src_port))',
)

# ── Fix 3: UDP source IP binding ─────────────────────────────────────────
# Insert SO_REUSEADDR before any UDP bind.  Without this, Linux assigns
# a unique source port per UDP socket even when destinations differ,
# capping total connected sockets at the ephemeral range size.
udp_body = udp_body.replace(
    '        if src_ip is not None:\n'
    '            if src_port != 0:\n'
    '                sock.bind((src_ip, src_port))\n'
    '            else:\n'
    '                sock.bind((src_ip, 0))',

    '        if src_ip is not None:\n'
    '            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n'
    '            if src_port != 0:\n'
    '                sock.bind((src_ip, src_port))\n'
    '            else:\n'
    '                sock.bind((src_ip, 0))',
)

# ── Reassemble and write ─────────────────────────────────────────────────
result = preamble + tcp_body + udp_body + close_body

with open(PROXY_PATH, 'w') as f:
    f.write(result)

# ── Verify fixes landed in the correct methods ───────────────────────────
with open(PROXY_PATH, 'r') as f:
    fixed = f.read()

tcp_section = fixed[fixed.index('def create_tcp_connection'):
                    fixed.index('def create_udp_connection')]
udp_section = fixed[fixed.index('def create_udp_connection'):
                    fixed.index('def close_all')]

assert 'IP_BIND_ADDRESS_NO_PORT' in tcp_section, \
    'Fix 1 (IP_BIND_ADDRESS_NO_PORT in TCP auto-port) was not applied'
assert 'SO_REUSEADDR' in tcp_section, \
    'Fix 2 (SO_REUSEADDR in TCP explicit port) was not applied'
assert 'SO_REUSEADDR' in udp_section, \
    'Fix 3 (SO_REUSEADDR in UDP) was not applied'

print('All three socket-option fixes applied successfully.')
print()
print('Summary of changes:')
print('  TCP auto-port:     + IP_BIND_ADDRESS_NO_PORT before bind(ip, 0)')
print('  TCP explicit port: + SO_REUSEADDR before bind(ip, port)')
print('  UDP:               + SO_REUSEADDR before bind()')
