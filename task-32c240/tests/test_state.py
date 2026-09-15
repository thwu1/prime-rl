"""
Tests for connection manager UDP overshadowing prevention.

Verifies that the connection manager correctly prevents UDP socket
4-tuple collisions (overshadowing) while maintaining source port
sharing across different destinations.
"""


import socket
import threading
import time
import sys

import pytest

sys.path.insert(0, '/app')


# ---------------------------------------------------------------------------
# Echo servers
# ---------------------------------------------------------------------------

def _tcp_echo_loop(srv, stop):
    while not stop.is_set():
        try:
            conn, _ = srv.accept()

            def _handle(c=conn):
                try:
                    data = c.recv(4096)
                    if data:
                        c.sendall(data)
                except Exception:
                    pass
                finally:
                    c.close()

            threading.Thread(target=_handle, daemon=True).start()
        except socket.timeout:
            continue
        except OSError:
            break


def _udp_echo_loop(srv, stop):
    while not stop.is_set():
        try:
            data, addr = srv.recvfrom(4096)
            srv.sendto(data, addr)
        except socket.timeout:
            continue
        except OSError:
            break


def make_tcp_server(port):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('0.0.0.0', port))
    srv.listen(128)
    srv.settimeout(1.0)
    stop = threading.Event()
    threading.Thread(target=_tcp_echo_loop, args=(srv, stop), daemon=True).start()
    return srv, stop


def make_udp_server(port):
    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('0.0.0.0', port))
    srv.settimeout(1.0)
    stop = threading.Event()
    threading.Thread(target=_udp_echo_loop, args=(srv, stop), daemon=True).start()
    return srv, stop


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clean_module():
    """Force reimport of connmgr between tests."""
    for mod in list(sys.modules):
        if mod == 'connmgr' or mod.startswith('connmgr.'):
            del sys.modules[mod]
    yield
    for mod in list(sys.modules):
        if mod == 'connmgr' or mod.startswith('connmgr.'):
            del sys.modules[mod]


# ---------------------------------------------------------------------------
# TCP Regression Tests
# ---------------------------------------------------------------------------

class TestTCPRegression:
    """TCP functionality must not be broken by the UDP fix."""

    def test_tcp_source_ip_binding(self):
        """TCP with source IP binding must still work."""
        srv, stop = make_tcp_server(16001)
        time.sleep(0.2)
        try:
            from connmgr import ConnectionManager
            mgr = ConnectionManager()
            sock = mgr.create_tcp_connection(
                '127.0.0.1', 16001, src_ip='127.0.0.1')
            sock.sendall(b'tcp-test')
            assert sock.recv(4096) == b'tcp-test'
            mgr.close_all()
        finally:
            stop.set()
            srv.close()

    def test_tcp_explicit_port_reuse(self):
        """TCP with explicit source port to different destinations must work."""
        srv1, stop1 = make_tcp_server(16002)
        srv2, stop2 = make_tcp_server(16003)
        time.sleep(0.2)
        try:
            from connmgr import ConnectionManager
            mgr = ConnectionManager()
            c1 = mgr.create_tcp_connection(
                '127.0.0.1', 16002,
                src_ip='127.0.0.1', src_port=44000)
            c1.sendall(b'alpha')
            assert c1.recv(4096) == b'alpha'

            c2 = mgr.create_tcp_connection(
                '127.0.0.1', 16003,
                src_ip='127.0.0.1', src_port=44000)
            c2.sendall(b'bravo')
            assert c2.recv(4096) == b'bravo'
            mgr.close_all()
        finally:
            stop1.set()
            srv1.close()
            stop2.set()
            srv2.close()


# ---------------------------------------------------------------------------
# UDP Port Sharing Tests
# ---------------------------------------------------------------------------

class TestUDPPortSharing:
    """SO_REUSEADDR must enable port sharing across different destinations."""

    def test_explicit_port_different_destinations(self):
        """Same source port to different destinations — all must work."""
        NUM = 5
        BASE = 17100
        servers = []
        for i in range(NUM):
            servers.append(make_udp_server(BASE + i))
        time.sleep(0.3)

        try:
            from connmgr import ConnectionManager
            mgr = ConnectionManager()
            socks = []
            for i in range(NUM):
                sock = mgr.create_udp_connection(
                    '127.0.0.1', BASE + i,
                    src_ip='127.0.0.1', src_port=46000)
                socks.append(sock)

            for i, sock in enumerate(socks):
                payload = f'share-{i}'.encode()
                sock.send(payload)
                resp = sock.recv(4096)
                assert resp == payload, (
                    f"Connection {i}: expected {payload!r}, got {resp!r}")
            mgr.close_all()
        finally:
            for srv, stp in servers:
                stp.set()
                srv.close()

    def test_auto_port_many_destinations(self):
        """Auto-assigned port to many destinations — all must work."""
        NUM = 20
        BASE = 17200
        servers = []
        for i in range(NUM):
            servers.append(make_udp_server(BASE + i))
        time.sleep(0.5)

        try:
            from connmgr import ConnectionManager
            mgr = ConnectionManager()
            socks = []
            for i in range(NUM):
                sock = mgr.create_udp_connection(
                    '127.0.0.1', BASE + i, src_ip='127.0.0.1')
                socks.append(sock)

            for i, sock in enumerate(socks):
                payload = f'auto-{i}'.encode()
                sock.send(payload)
                resp = sock.recv(4096)
                assert resp == payload
            mgr.close_all()
        finally:
            for srv, stp in servers:
                stp.set()
                srv.close()


# ---------------------------------------------------------------------------
# UDP Conflict Detection Tests
# ---------------------------------------------------------------------------

class TestUDPConflictDetection:
    """Must detect and prevent UDP socket overshadowing."""

    def test_same_4tuple_raises_conflict_error(self):
        """Creating a second socket with an identical 4-tuple must raise error."""
        srv, stop = make_udp_server(17300)
        time.sleep(0.2)

        try:
            from connmgr import ConnectionManager, ConnectionConflictError
            mgr = ConnectionManager()

            sock1 = mgr.create_udp_connection(
                '127.0.0.1', 17300,
                src_ip='127.0.0.1', src_port=47000)
            sock1.send(b'first')
            assert sock1.recv(4096) == b'first'

            with pytest.raises(ConnectionConflictError):
                mgr.create_udp_connection(
                    '127.0.0.1', 17300,
                    src_ip='127.0.0.1', src_port=47000)

            mgr.close_all()
        finally:
            stop.set()
            srv.close()

    def test_external_socket_conflict_detected(self):
        """Must detect conflicts with sockets NOT created by the manager."""
        srv, stop = make_udp_server(17301)
        time.sleep(0.2)

        # Create a socket outside the manager
        ext = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        ext.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        ext.bind(('127.0.0.1', 47100))
        ext.connect(('127.0.0.1', 17301))

        try:
            from connmgr import ConnectionManager, ConnectionConflictError
            mgr = ConnectionManager()

            with pytest.raises(ConnectionConflictError):
                mgr.create_udp_connection(
                    '127.0.0.1', 17301,
                    src_ip='127.0.0.1', src_port=47100)

            mgr.close_all()
        finally:
            ext.close()
            stop.set()
            srv.close()

    def test_different_destination_still_allowed(self):
        """Same source port to a different destination must not be blocked."""
        srv1, stop1 = make_udp_server(17302)
        srv2, stop2 = make_udp_server(17303)
        time.sleep(0.2)

        try:
            from connmgr import ConnectionManager
            mgr = ConnectionManager()

            sock1 = mgr.create_udp_connection(
                '127.0.0.1', 17302,
                src_ip='127.0.0.1', src_port=47200)
            sock1.send(b'dest1')
            assert sock1.recv(4096) == b'dest1'

            sock2 = mgr.create_udp_connection(
                '127.0.0.1', 17303,
                src_ip='127.0.0.1', src_port=47200)
            sock2.send(b'dest2')
            assert sock2.recv(4096) == b'dest2'

            # Both must continue working after sharing the port
            sock1.send(b'still1')
            assert sock1.recv(4096) == b'still1'
            sock2.send(b'still2')
            assert sock2.recv(4096) == b'still2'

            mgr.close_all()
        finally:
            stop1.set()
            srv1.close()
            stop2.set()
            srv2.close()

    def test_first_connection_survives_conflict_attempt(self):
        """The existing connection must keep working after a conflict attempt."""
        srv, stop = make_udp_server(17304)
        time.sleep(0.2)

        try:
            from connmgr import ConnectionManager, ConnectionConflictError
            mgr = ConnectionManager()

            sock1 = mgr.create_udp_connection(
                '127.0.0.1', 17304,
                src_ip='127.0.0.1', src_port=47300)

            # Attempt conflicting connection — must fail
            try:
                mgr.create_udp_connection(
                    '127.0.0.1', 17304,
                    src_ip='127.0.0.1', src_port=47300)
            except ConnectionConflictError:
                pass

            # Original must still echo correctly
            for i in range(5):
                payload = f'alive-{i}'.encode()
                sock1.send(payload)
                resp = sock1.recv(4096)
                assert resp == payload, (
                    f"Iteration {i}: original connection broken after "
                    "conflict attempt")

            mgr.close_all()
        finally:
            stop.set()
            srv.close()


# ---------------------------------------------------------------------------
# UDP Lifecycle Tests
# ---------------------------------------------------------------------------

class TestUDPLifecycle:
    """Socket lifecycle: closed 4-tuples must become available for reuse."""

    def test_reuse_4tuple_after_close(self):
        """After closing a connection, the same 4-tuple can be reused."""
        srv, stop = make_udp_server(17400)
        time.sleep(0.2)

        try:
            from connmgr import ConnectionManager
            mgr = ConnectionManager()

            sock1 = mgr.create_udp_connection(
                '127.0.0.1', 17400,
                src_ip='127.0.0.1', src_port=48000)
            sock1.send(b'round1')
            assert sock1.recv(4096) == b'round1'

            mgr.close_connection(sock1)
            time.sleep(0.3)

            sock2 = mgr.create_udp_connection(
                '127.0.0.1', 17400,
                src_ip='127.0.0.1', src_port=48000)
            sock2.send(b'round2')
            assert sock2.recv(4096) == b'round2'

            mgr.close_all()
        finally:
            stop.set()
            srv.close()

    def test_multiple_close_and_reuse_cycles(self):
        """Repeated close-and-reuse cycles must work correctly."""
        srv, stop = make_udp_server(17401)
        time.sleep(0.2)

        try:
            from connmgr import ConnectionManager
            mgr = ConnectionManager()

            for cycle in range(4):
                sock = mgr.create_udp_connection(
                    '127.0.0.1', 17401,
                    src_ip='127.0.0.1', src_port=48100)
                payload = f'cycle-{cycle}'.encode()
                sock.send(payload)
                assert sock.recv(4096) == payload, (
                    f"Cycle {cycle}: data mismatch")
                mgr.close_connection(sock)
                time.sleep(0.2)

            mgr.close_all()
        finally:
            stop.set()
            srv.close()
