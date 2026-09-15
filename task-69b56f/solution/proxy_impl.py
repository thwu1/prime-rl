#!/usr/bin/env python3
"""SOCKS5 proxy server per RFC 1928 with USERNAME/PASSWORD auth (RFC 1929),
CIDR-based access control, and structured connection logging.

"""

import asyncio
import ipaddress
import os
import socket
import struct
from datetime import datetime, timezone

# ── SOCKS5 constants ──

SOCKS5_VER = 0x05
AUTH_NONE = 0x00
AUTH_USERPASS = 0x02
AUTH_REJECT = 0xFF

CMD_CONNECT = 0x01

ATYP_IPV4 = 0x01
ATYP_DOMAIN = 0x03
ATYP_IPV6 = 0x04

REP_SUCCESS = 0x00
REP_GENERAL = 0x01
REP_NOT_ALLOWED = 0x02
REP_NET_UNREACH = 0x03
REP_HOST_UNREACH = 0x04
REP_CONN_REFUSED = 0x05
REP_TTL_EXPIRED = 0x06
REP_CMD_UNSUP = 0x07
REP_ATYP_UNSUP = 0x08

REP_NAMES = {
    REP_SUCCESS: "OK",
    REP_GENERAL: "GENERAL_FAILURE",
    REP_NOT_ALLOWED: "NOT_ALLOWED",
    REP_NET_UNREACH: "NETWORK_UNREACHABLE",
    REP_HOST_UNREACH: "HOST_UNREACHABLE",
    REP_CONN_REFUSED: "CONNECTION_REFUSED",
    REP_TTL_EXPIRED: "TTL_EXPIRED",
    REP_CMD_UNSUP: "CMD_NOT_SUPPORTED",
    REP_ATYP_UNSUP: "ATYP_NOT_SUPPORTED",
}


def socks_reply(rep, bind_atyp=ATYP_IPV4, bind_addr=b"\x00\x00\x00\x00",
                bind_port=0):
    """Build a SOCKS5 reply packet."""
    return (
        struct.pack("BBBB", SOCKS5_VER, rep, 0x00, bind_atyp)
        + bind_addr
        + struct.pack("!H", bind_port)
    )


def socks_error(rep):
    """Build a SOCKS5 error reply with zeroed bind address."""
    return socks_reply(rep)


# ── Configuration ──


class ACLEngine:
    """First-match-wins CIDR access control list."""

    def __init__(self, path):
        self.rules = []
        if not os.path.exists(path):
            return
        with open(path) as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(None, 1)
                if len(parts) != 2:
                    continue
                action, cidr = parts[0].lower(), parts[1].strip()
                try:
                    net = ipaddress.ip_network(cidr, strict=False)
                except ValueError:
                    continue
                self.rules.append((action == "allow", net))

    def is_allowed(self, ip_str):
        try:
            addr = ipaddress.ip_address(ip_str)
        except ValueError:
            return False
        for allow, net in self.rules:
            if addr in net:
                return allow
        return False  # default deny


class UserStore:
    """Username:password credential store."""

    def __init__(self, path):
        self.creds = {}
        if not os.path.exists(path):
            return
        with open(path) as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if ":" in line:
                    u, p = line.split(":", 1)
                    self.creds[u] = p

    def verify(self, user, passwd):
        return self.creds.get(user) == passwd


class ProxyLogger:
    """Append-only connection log writer."""

    def __init__(self, path):
        self.path = path
        self._lock = asyncio.Lock()

    async def record(self, src_ip, src_port, dst, dst_port, rep, nbytes):
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        status = REP_NAMES.get(rep, "GENERAL_FAILURE")
        entry = (f"{ts} {src_ip}:{src_port} -> {dst}:{dst_port} "
                 f"{status} {nbytes}\n")
        async with self._lock:
            with open(self.path, "a") as fh:
                fh.write(entry)


# ── Data relay ──


async def _relay(reader, writer):
    """Copy bytes from reader to writer until EOF; return total bytes."""
    total = 0
    try:
        while True:
            chunk = await reader.read(65536)
            if not chunk:
                break
            writer.write(chunk)
            await writer.drain()
            total += len(chunk)
    except (OSError, asyncio.IncompleteReadError):
        pass
    try:
        if hasattr(writer, "can_write_eof") and writer.can_write_eof():
            writer.write_eof()
    except (OSError, RuntimeError):
        pass
    return total


# ── Per-connection handler ──


async def _handle(reader, writer, acl, users, logger):
    peer = writer.get_extra_info("peername") or ("0.0.0.0", 0)
    src_ip, src_port = peer[0], peer[1]
    dst, dst_port, rep, nbytes = "0.0.0.0", 0, REP_GENERAL, 0
    remote_w = None

    try:
        # ── Phase 1: method negotiation ──
        hdr = await asyncio.wait_for(reader.readexactly(2), 30)
        ver, nm = hdr
        if ver != SOCKS5_VER:
            return
        methods = list(await asyncio.wait_for(reader.readexactly(nm), 30))

        if AUTH_USERPASS in methods:
            chosen = AUTH_USERPASS
        elif AUTH_NONE in methods:
            chosen = AUTH_NONE
        else:
            writer.write(struct.pack("BB", SOCKS5_VER, AUTH_REJECT))
            await writer.drain()
            return

        writer.write(struct.pack("BB", SOCKS5_VER, chosen))
        await writer.drain()

        # ── Phase 2: authentication (RFC 1929) ──
        if chosen == AUTH_USERPASS:
            ab = await asyncio.wait_for(reader.readexactly(2), 30)
            if ab[0] != 0x01:
                writer.write(b"\x01\x01")
                await writer.drain()
                return
            uname = (await reader.readexactly(ab[1])).decode("utf-8", "replace")
            plen = (await reader.readexactly(1))[0]
            passwd = (await reader.readexactly(plen)).decode("utf-8", "replace")
            if users.verify(uname, passwd):
                writer.write(b"\x01\x00")
                await writer.drain()
            else:
                writer.write(b"\x01\x01")
                await writer.drain()
                return

        # ── Phase 3: request ──
        rh = await asyncio.wait_for(reader.readexactly(4), 30)
        ver2, cmd, _, atyp = rh
        if ver2 != SOCKS5_VER:
            return

        # Parse destination address
        if atyp == ATYP_IPV4:
            dst = socket.inet_ntoa(await reader.readexactly(4))
        elif atyp == ATYP_DOMAIN:
            dlen = (await reader.readexactly(1))[0]
            dst = (await reader.readexactly(dlen)).decode("utf-8", "replace")
        elif atyp == ATYP_IPV6:
            dst = socket.inet_ntop(
                socket.AF_INET6, await reader.readexactly(16)
            )
        else:
            writer.write(socks_error(REP_ATYP_UNSUP))
            await writer.drain()
            rep = REP_ATYP_UNSUP
            return

        dst_port = struct.unpack("!H", await reader.readexactly(2))[0]

        # Only CONNECT is supported
        if cmd != CMD_CONNECT:
            writer.write(socks_error(REP_CMD_UNSUP))
            await writer.drain()
            rep = REP_CMD_UNSUP
            return

        # ── Phase 4: resolve + ACL ──
        connect_host = dst
        check_ip = dst
        if atyp == ATYP_DOMAIN:
            try:
                infos = socket.getaddrinfo(
                    dst, dst_port, socket.AF_UNSPEC, socket.SOCK_STREAM
                )
                if not infos:
                    raise socket.gaierror("empty")
                check_ip = infos[0][4][0]
            except socket.gaierror:
                writer.write(socks_error(REP_HOST_UNREACH))
                await writer.drain()
                rep = REP_HOST_UNREACH
                return

        if not acl.is_allowed(check_ip):
            writer.write(socks_error(REP_NOT_ALLOWED))
            await writer.drain()
            rep = REP_NOT_ALLOWED
            return

        # ── Phase 5: connect to target ──
        try:
            remote_r, remote_w = await asyncio.wait_for(
                asyncio.open_connection(connect_host, dst_port), 30
            )
        except ConnectionRefusedError:
            writer.write(socks_error(REP_CONN_REFUSED))
            await writer.drain()
            rep = REP_CONN_REFUSED
            return
        except OSError:
            writer.write(socks_error(REP_NET_UNREACH))
            await writer.drain()
            rep = REP_NET_UNREACH
            return

        # ── Phase 6: success reply with bind address ──
        bnd = remote_w.get_extra_info("sockname")
        bnd_ip, bnd_port = bnd[0], bnd[1]
        try:
            bnd_raw = socket.inet_aton(bnd_ip)
            bnd_atyp = ATYP_IPV4
        except OSError:
            bnd_raw = socket.inet_pton(socket.AF_INET6, bnd_ip)
            bnd_atyp = ATYP_IPV6

        writer.write(socks_reply(REP_SUCCESS, bnd_atyp, bnd_raw, bnd_port))
        await writer.drain()

        # ── Phase 7: bidirectional relay ──
        up = asyncio.create_task(_relay(reader, remote_w))
        down = asyncio.create_task(_relay(remote_r, writer))
        results = await asyncio.gather(up, down, return_exceptions=True)
        for r in results:
            if isinstance(r, int):
                nbytes += r
        rep = REP_SUCCESS

    except (
        asyncio.IncompleteReadError,
        ConnectionResetError,
        BrokenPipeError,
        asyncio.TimeoutError,
    ):
        pass
    except Exception:
        pass
    finally:
        await logger.record(src_ip, src_port, dst, dst_port, rep, nbytes)
        if remote_w is not None:
            try:
                remote_w.close()
                await remote_w.wait_closed()
            except Exception:
                pass
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


# ── Entry point ──


async def run():
    acl = ACLEngine(os.environ.get("SOCKS5_ACL", "/app/acl.conf"))
    users = UserStore(os.environ.get("SOCKS5_USERS", "/app/users.conf"))
    logger = ProxyLogger(os.environ.get("SOCKS5_LOG", "/app/proxy.log"))
    port = int(os.environ.get("SOCKS5_PORT", "1080"))

    async def on_connect(r, w):
        await _handle(r, w, acl, users, logger)

    srv = await asyncio.start_server(on_connect, "0.0.0.0", port)
    async with srv:
        await srv.serve_forever()


if __name__ == "__main__":
    asyncio.run(run())
