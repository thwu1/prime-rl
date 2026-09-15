
"""Tests for the UDP connectx implementation."""

import socket
import sys
import pytest

sys.path.insert(0, "/app")
from connectx import udp_connectx, get_ephemeral_range, udp_socket_lookup


class TestBasicConnection:
    """Test that udp_connectx creates valid connected UDP sockets."""

    def test_auto_source(self):
        """Connection with automatic source IP and port."""
        s = udp_connectx(None, 0, "127.0.0.1", 20001)
        try:
            peer = s.getpeername()
            assert peer == ("127.0.0.1", 20001)
            assert s.type & socket.SOCK_DGRAM
        finally:
            s.close()

    def test_fixed_source_ip(self):
        """Connection with fixed source IP, auto port."""
        s = udp_connectx("127.0.0.1", 0, "127.0.0.1", 20002)
        try:
            local = s.getsockname()
            assert local[0] == "127.0.0.1"
            assert local[1] > 0
            assert s.getpeername() == ("127.0.0.1", 20002)
        finally:
            s.close()

    def test_full_4tuple(self):
        """Connection with fully specified 4-tuple."""
        s = udp_connectx("127.0.0.1", 41001, "127.0.0.1", 20003)
        try:
            assert s.getsockname() == ("127.0.0.1", 41001)
            assert s.getpeername() == ("127.0.0.1", 20003)
        finally:
            s.close()


class TestSourcePortReuse:
    """Test that source ports can be reused across different destinations."""

    def test_fixed_port_reuse_across_destinations(self):
        """20 connections from the same source port to different destinations
        must all succeed — this is the core value proposition of connectx."""
        socks = []
        try:
            for i in range(20):
                s = udp_connectx("127.0.0.1", 41002, "127.0.0.1", 21000 + i)
                socks.append(s)

            # All share the same source port
            for s in socks:
                assert s.getsockname() == ("127.0.0.1", 41002)

            # All have distinct destinations
            dests = {s.getpeername() for s in socks}
            assert len(dests) == 20
        finally:
            for s in socks:
                s.close()

    def test_auto_port_unique_4tuples(self):
        """Auto-port connections to different destinations all get unique 4-tuples."""
        socks = []
        try:
            for i in range(10):
                s = udp_connectx("127.0.0.1", 0, "127.0.0.1", 22000 + i)
                socks.append(s)

            tuples = set()
            for s in socks:
                ft = (s.getsockname(), s.getpeername())
                assert ft not in tuples, f"Duplicate 4-tuple: {ft}"
                tuples.add(ft)
        finally:
            for s in socks:
                s.close()


class TestOvershadowingPrevention:
    """Test that duplicate 4-tuples are rejected."""

    def test_duplicate_4tuple_raises(self):
        """Creating two connections with identical 4-tuples must raise OSError."""
        s1 = udp_connectx("127.0.0.1", 41003, "127.0.0.1", 20005)
        try:
            with pytest.raises(OSError):
                s2 = udp_connectx("127.0.0.1", 41003, "127.0.0.1", 20005)
                s2.close()  # cleanup if it wrongly succeeds
        finally:
            s1.close()

    def test_same_port_different_dest_ok(self):
        """Same source port to different destinations must work (not raise)."""
        s1 = udp_connectx("127.0.0.1", 41004, "127.0.0.1", 20010)
        s2 = udp_connectx("127.0.0.1", 41004, "127.0.0.1", 20011)
        try:
            assert s1.getsockname()[1] == 41004
            assert s2.getsockname()[1] == 41004
            assert s1.getpeername() != s2.getpeername()
        finally:
            s1.close()
            s2.close()


class TestSocketLookup:
    """Test the kernel socket lookup function."""

    def test_finds_existing_connected_socket(self):
        """udp_socket_lookup must find a connected UDP socket by its 4-tuple."""
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", 41006))
        s.connect(("127.0.0.1", 20006))
        try:
            result = udp_socket_lookup(
                socket.AF_INET,
                ("127.0.0.1", 41006),
                ("127.0.0.1", 20006),
            )
            assert result is not None, "Lookup must find existing connected socket"
        finally:
            s.close()

    def test_returns_none_for_missing(self):
        """udp_socket_lookup must return None when no matching socket exists."""
        result = udp_socket_lookup(
            socket.AF_INET,
            ("127.0.0.1", 41007),
            ("127.0.0.1", 20007),
        )
        assert result is None

    def test_does_not_find_unconnected_socket(self):
        """udp_socket_lookup must not match a socket that is bound but not connected."""
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", 41008))
        # Intentionally NOT calling s.connect()
        try:
            result = udp_socket_lookup(
                socket.AF_INET,
                ("127.0.0.1", 41008),
                ("127.0.0.1", 20008),
            )
            assert result is None, "Lookup must not match unconnected sockets"
        finally:
            s.close()

    def test_does_not_false_positive_on_server_socket(self):
        """udp_socket_lookup must not match a server socket bound to the
        destination port — the kernel's __udp4_lib_lookup returns best-match
        sockets, so the implementation must verify exact 4-tuple match."""
        srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", 20050))
        # Server is bound to dst port but NOT connected
        try:
            result = udp_socket_lookup(
                socket.AF_INET,
                ("127.0.0.1", 45000),
                ("127.0.0.1", 20050),
            )
            assert result is None, (
                "Lookup must not match server socket bound to destination port"
            )
        finally:
            srv.close()


class TestEphemeralRange:
    """Test ephemeral port range reading."""

    def test_valid_range(self):
        """get_ephemeral_range must return a valid (low, high) pair from /proc."""
        lo, hi = get_ephemeral_range()
        assert isinstance(lo, int)
        assert isinstance(hi, int)
        assert 1024 <= lo < hi <= 65535


class TestDataTransfer:
    """Test that connectx sockets can send and receive data."""

    def test_send_recv_roundtrip(self):
        """Data must flow correctly through a connectx-created socket."""
        # Set up a receiving UDP socket
        server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 20009))
        server.settimeout(3)

        # Create connectx client
        client = udp_connectx("127.0.0.1", 0, "127.0.0.1", 20009)
        client.settimeout(3)

        try:
            # Client -> Server
            client.send(b"hello connectx")
            data, addr = server.recvfrom(1024)
            assert data == b"hello connectx"

            # Server -> Client
            server.sendto(b"pong", addr)
            resp = client.recv(1024)
            assert resp == b"pong"
        finally:
            client.close()
            server.close()

    def test_multiple_sockets_independent_data(self):
        """Two connectx sockets sharing a source port receive only their own data."""
        srv1 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        srv1.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv1.bind(("127.0.0.1", 23001))
        srv1.settimeout(3)

        srv2 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        srv2.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv2.bind(("127.0.0.1", 23002))
        srv2.settimeout(3)

        c1 = udp_connectx("127.0.0.1", 41009, "127.0.0.1", 23001)
        c2 = udp_connectx("127.0.0.1", 41009, "127.0.0.1", 23002)
        c1.settimeout(3)
        c2.settimeout(3)

        try:
            c1.send(b"msg1")
            c2.send(b"msg2")

            d1, a1 = srv1.recvfrom(1024)
            d2, a2 = srv2.recvfrom(1024)
            assert d1 == b"msg1"
            assert d2 == b"msg2"

            # Reply back
            srv1.sendto(b"reply1", a1)
            srv2.sendto(b"reply2", a2)

            r1 = c1.recv(1024)
            r2 = c2.recv(1024)
            assert r1 == b"reply1"
            assert r2 == b"reply2"
        finally:
            c1.close()
            c2.close()
            srv1.close()
            srv2.close()
