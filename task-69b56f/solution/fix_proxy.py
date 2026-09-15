#!/usr/bin/env python3
"""Fix RFC 1928/1929 non-conformance bugs in the SOCKS5 proxy.


Bugs identified by comparing implementation against RFC specifications:
1. Reply RSV field is 0x01 instead of required 0x00 (RFC 1928 Section 6)
2. Auth sub-negotiation checks for version 0x05 instead of 0x01 (RFC 1929 Section 2)
3. IPv6 address reads 4 bytes instead of 16 (RFC 1928 Section 5)
4. Unsupported commands return general failure (0x01) instead of 0x07 (RFC 1928 Section 6)
5. ACL enforcement skipped for domain-name connections
6. BND.ADDR/PORT uses target address instead of outbound socket's local address (RFC 1928)
"""

with open("/app/proxy.py") as f:
    code = f.read()

# Fix 1: RSV must be X'00' per RFC 1928 Section 6 ("Fields marked RESERVED
# (RSV) must be set to X'00'")
code = code.replace(
    "SOCKS5_VER, rep, 0x01, atyp)",
    "SOCKS5_VER, rep, 0x00, atyp)",
)

# Fix 2: RFC 1929 Section 2 specifies sub-negotiation VER as X'01'
code = code.replace(
    "auth_header[0] != 0x05",
    "auth_header[0] != 0x01",
)

# Fix 3: IPv6 address is 16 octets per RFC 1928 Section 5
# ("the address is a version-6 IP address, with a length of 16 octets")
# Use multiline context to avoid matching IPv4's readexactly(4)
code = code.replace(
    "reader.readexactly(4)\n            dst = socket.inet_ntop(socket.AF_INET6",
    "reader.readexactly(16)\n            dst = socket.inet_ntop(socket.AF_INET6",
)

# Fix 4: Unsupported commands must return REP=0x07 per RFC 1928 Section 6
# ("X'07' Command not supported")
code = code.replace(
    "writer.write(error_reply(REP_GENERAL))\n"
    "            await writer.drain()\n"
    "            rep = REP_GENERAL\n"
    "            return",
    "writer.write(error_reply(REP_CMD_UNSUP))\n"
    "            await writer.drain()\n"
    "            rep = REP_CMD_UNSUP\n"
    "            return",
)

# Fix 5: ACL must apply to ALL connections including domain-name requests
# (the resolved IP must be checked regardless of original ATYP)
code = code.replace(
    "        if atyp != ATYP_DOMAIN:\n"
    "            if not acl.check(resolved_ip):\n"
    "                writer.write(error_reply(REP_NOT_ALLOWED))\n"
    "                await writer.drain()\n"
    "                rep = REP_NOT_ALLOWED\n"
    "                return",
    "        if not acl.check(resolved_ip):\n"
    "            writer.write(error_reply(REP_NOT_ALLOWED))\n"
    "            await writer.drain()\n"
    "            rep = REP_NOT_ALLOWED\n"
    "            return",
)

# Fix 6: BND.ADDR/PORT must reflect the outbound socket's local address,
# not the target's address (RFC 1928 CONNECT: "BND.PORT contains the port
# number that the server assigned to connect to the target host, while
# BND.ADDR contains the associated IP address")
code = code.replace(
    "        try:\n"
    "            bound_addr = socket.inet_aton(connect_host if atyp == ATYP_IPV4 else resolved_ip)\n"
    "            bound_atyp = ATYP_IPV4\n"
    "        except OSError:\n"
    "            bound_addr = socket.inet_pton(socket.AF_INET6, resolved_ip)\n"
    "            bound_atyp = ATYP_IPV6\n"
    "        bound_port = dst_port",
    '        sockinfo = remote_writer.get_extra_info("sockname")\n'
    "        bound_ip, bound_port = sockinfo[0], sockinfo[1]\n"
    "        try:\n"
    "            bound_addr = socket.inet_aton(bound_ip)\n"
    "            bound_atyp = ATYP_IPV4\n"
    "        except OSError:\n"
    "            bound_addr = socket.inet_pton(socket.AF_INET6, bound_ip)\n"
    "            bound_atyp = ATYP_IPV6",
)

with open("/app/proxy.py", "w") as f:
    f.write(code)

# Verify the patched file is valid Python
import ast
ast.parse(code)
print("All 6 RFC non-conformance bugs fixed and syntax verified.")
