#!/usr/bin/env python3
"""SOCKS5 proxy server — RFC 1928 / RFC 1929."""

import asyncio
import ipaddress
import os
import socket
import struct
from datetime import datetime, timezone

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
REP_CMD_UNSUP = 0x07
REP_ATYP_UNSUP = 0x08

STATUS_NAMES = {
    REP_SUCCESS: "OK",
    REP_GENERAL: "GENERAL_FAILURE",
    REP_NOT_ALLOWED: "NOT_ALLOWED",
    REP_NET_UNREACH: "NETWORK_UNREACHABLE",
    REP_HOST_UNREACH: "HOST_UNREACHABLE",
    REP_CONN_REFUSED: "CONNECTION_REFUSED",
    REP_CMD_UNSUP: "CMD_NOT_SUPPORTED",
    REP_ATYP_UNSUP: "ATYP_NOT_SUPPORTED",
}


def make_reply(rep, atyp=ATYP_IPV4, addr=b"\x00\x00\x00\x00", port=0):
    """Build a SOCKS5 reply."""
    return (
        struct.pack("BBBB", SOCKS5_VER, rep, 0x01, atyp)
        + addr
        + struct.pack("!H", port)
    )


def error_reply(rep):
    """Build a SOCKS5 error reply with zeroed address."""
    return make_reply(rep)


class ACL:
    """First-match-wins CIDR access control."""

    def __init__(self, path):
        self.rules = []
        if not os.path.exists(path):
            return
        with open(path) as f:
            for raw in f:
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

    def check(self, ip_str):
        try:
            addr = ipaddress.ip_address(ip_str)
        except ValueError:
            return False
        for allow, net in self.rules:
            if addr in net:
                return allow
        return False


class Credentials:
    """Username:password store."""

    def __init__(self, path):
        self.users = {}
        if not os.path.exists(path):
            return
        with open(path) as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if ":" in line:
                    u, p = line.split(":", 1)
                    self.users[u] = p

    def verify(self, user, passwd):
        return self.users.get(user) == passwd


class Logger:
    """Connection log writer."""

    def __init__(self, path):
        self.path = path
        self._lock = asyncio.Lock()

    async def log(self, src_ip, src_port, dst, dst_port, rep, nbytes):
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        status = STATUS_NAMES.get(rep, "GENERAL_FAILURE")
        line = f"{ts} {src_ip}:{src_port} -> {dst}:{dst_port} {status} {nbytes}\n"
        async with self._lock:
            with open(self.path, "a") as f:
                f.write(line)


async def relay(reader, writer):
    """Copy data from reader to writer until EOF."""
    total = 0
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            writer.write(data)
            await writer.drain()
            total += len(data)
    except (OSError, asyncio.IncompleteReadError):
        pass
    try:
        if hasattr(writer, "can_write_eof") and writer.can_write_eof():
            writer.write_eof()
    except (OSError, RuntimeError):
        pass
    return total


async def handle_client(reader, writer, acl, creds, logger):
    peer = writer.get_extra_info("peername") or ("0.0.0.0", 0)
    src_ip, src_port = peer[0], peer[1]
    dst, dst_port, rep, nbytes = "0.0.0.0", 0, REP_GENERAL, 0
    remote_writer = None

    try:
        # Method negotiation
        header = await asyncio.wait_for(reader.readexactly(2), 30)
        ver, nmethods = header
        if ver != SOCKS5_VER:
            return
        methods = list(await asyncio.wait_for(reader.readexactly(nmethods), 30))

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

        # Username/password authentication
        if chosen == AUTH_USERPASS:
            auth_header = await asyncio.wait_for(reader.readexactly(2), 30)
            if auth_header[0] != 0x05:
                writer.write(b"\x01\x01")
                await writer.drain()
                return
            uname = (await reader.readexactly(auth_header[1])).decode("utf-8", "replace")
            plen = (await reader.readexactly(1))[0]
            passwd = (await reader.readexactly(plen)).decode("utf-8", "replace")
            if creds.verify(uname, passwd):
                writer.write(b"\x01\x00")
                await writer.drain()
            else:
                writer.write(b"\x01\x01")
                await writer.drain()
                return

        # Parse request
        req_header = await asyncio.wait_for(reader.readexactly(4), 30)
        ver2, cmd, _, atyp = req_header
        if ver2 != SOCKS5_VER:
            return

        if atyp == ATYP_IPV4:
            dst = socket.inet_ntoa(await reader.readexactly(4))
        elif atyp == ATYP_DOMAIN:
            dlen = (await reader.readexactly(1))[0]
            dst = (await reader.readexactly(dlen)).decode("utf-8", "replace")
        elif atyp == ATYP_IPV6:
            raw = await reader.readexactly(4)
            dst = socket.inet_ntop(socket.AF_INET6, raw)
        else:
            writer.write(error_reply(REP_ATYP_UNSUP))
            await writer.drain()
            rep = REP_ATYP_UNSUP
            return

        dst_port = struct.unpack("!H", await reader.readexactly(2))[0]

        if cmd != CMD_CONNECT:
            writer.write(error_reply(REP_GENERAL))
            await writer.drain()
            rep = REP_GENERAL
            return

        # Resolve and ACL
        connect_host = dst
        resolved_ip = dst
        if atyp == ATYP_DOMAIN:
            try:
                infos = socket.getaddrinfo(dst, dst_port, socket.AF_UNSPEC, socket.SOCK_STREAM)
                if not infos:
                    raise socket.gaierror("empty")
                resolved_ip = infos[0][4][0]
            except socket.gaierror:
                writer.write(error_reply(REP_HOST_UNREACH))
                await writer.drain()
                rep = REP_HOST_UNREACH
                return

        if atyp != ATYP_DOMAIN:
            if not acl.check(resolved_ip):
                writer.write(error_reply(REP_NOT_ALLOWED))
                await writer.drain()
                rep = REP_NOT_ALLOWED
                return

        # Connect to target
        try:
            remote_reader, remote_writer = await asyncio.wait_for(
                asyncio.open_connection(connect_host, dst_port), 30
            )
        except ConnectionRefusedError:
            writer.write(error_reply(REP_CONN_REFUSED))
            await writer.drain()
            rep = REP_CONN_REFUSED
            return
        except OSError:
            writer.write(error_reply(REP_NET_UNREACH))
            await writer.drain()
            rep = REP_NET_UNREACH
            return

        # Success reply
        try:
            bound_addr = socket.inet_aton(connect_host if atyp == ATYP_IPV4 else resolved_ip)
            bound_atyp = ATYP_IPV4
        except OSError:
            bound_addr = socket.inet_pton(socket.AF_INET6, resolved_ip)
            bound_atyp = ATYP_IPV6
        bound_port = dst_port

        writer.write(make_reply(REP_SUCCESS, bound_atyp, bound_addr, bound_port))
        await writer.drain()

        # Bidirectional relay
        up_task = asyncio.create_task(relay(reader, remote_writer))
        down_task = asyncio.create_task(relay(remote_reader, writer))
        results = await asyncio.gather(up_task, down_task, return_exceptions=True)
        for r in results:
            if isinstance(r, int):
                nbytes += r
        rep = REP_SUCCESS

    except (asyncio.IncompleteReadError, ConnectionResetError, BrokenPipeError, asyncio.TimeoutError):
        pass
    except Exception:
        pass
    finally:
        await logger.log(src_ip, src_port, dst, dst_port, rep, nbytes)
        if remote_writer is not None:
            try:
                remote_writer.close()
                await remote_writer.wait_closed()
            except Exception:
                pass
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def main():
    acl = ACL(os.environ.get("SOCKS5_ACL", "/app/acl.conf"))
    creds = Credentials(os.environ.get("SOCKS5_USERS", "/app/users.conf"))
    logger = Logger(os.environ.get("SOCKS5_LOG", "/app/proxy.log"))
    port = int(os.environ.get("SOCKS5_PORT", "1080"))

    server = await asyncio.start_server(
        lambda r, w: handle_client(r, w, acl, creds, logger),
        "0.0.0.0", port,
    )
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
