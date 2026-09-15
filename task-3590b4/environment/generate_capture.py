#!/usr/bin/env python3
"""Generate a synthetic DERP protocol binary capture for analysis."""
import struct
import hashlib
import ipaddress
import os

MAGIC = b"DERP\xf0\x9f\x94\x91"

FT_SERVER_KEY = 0x01
FT_CLIENT_INFO = 0x02
FT_SERVER_INFO = 0x03
FT_SEND_PACKET = 0x04
FT_RECV_PACKET = 0x05
FT_KEEP_ALIVE = 0x06
FT_NOTE_PREFERRED = 0x07
FT_PEER_GONE = 0x08
FT_PEER_PRESENT = 0x09
FT_FORWARD_PACKET = 0x0A
FT_WATCH_CONNS = 0x10
FT_CLOSE_PEER = 0x11
FT_PING = 0x12
FT_PONG = 0x13
FT_HEALTH = 0x14
FT_RESTARTING = 0x15


def make_key(name):
    return hashlib.sha256(("derp-key-" + name).encode()).digest()


def make_data(seed, size):
    h = hashlib.sha256(("data-" + seed).encode()).digest()
    result = b""
    i = 0
    while len(result) < size:
        result += hashlib.sha256(h + struct.pack(">I", i)).digest()
        i += 1
    return result[:size]


def write_frame(f, ftype, payload):
    f.write(struct.pack(">BI", ftype, len(payload)))
    f.write(payload)


def ipv4_to_16(addr_str):
    addr = ipaddress.IPv4Address(addr_str)
    return b'\x00' * 10 + b'\xff\xff' + addr.packed


def generate():
    os.makedirs("/app", exist_ok=True)

    server_key = make_key("server")
    peer_a = make_key("alpha")
    peer_b = make_key("bravo")
    peer_c = make_key("charlie")
    peer_d = make_key("delta")
    peer_e = make_key("echo")

    nonce_a = hashlib.sha256(b"nonce-alpha").digest()[:24]
    nonce_s1 = hashlib.sha256(b"nonce-server-1").digest()[:24]
    nonce_d = hashlib.sha256(b"nonce-delta").digest()[:24]
    nonce_s2 = hashlib.sha256(b"nonce-server-2").digest()[:24]

    ping1 = b'\x01\x02\x03\x04\x05\x06\x07\x08'
    ping2 = b'\x11\x12\x13\x14\x15\x16\x17\x18'
    ping3 = b'\x21\x22\x23\x24\x25\x26\x27\x28'
    ping4 = b'\x31\x32\x33\x34\x35\x36\x37\x38'

    with open("/app/derp_capture.bin", "wb") as f:
        # ===== Session 1 =====
        # 1: ServerKey
        write_frame(f, FT_SERVER_KEY, MAGIC + server_key)
        # 2: ClientInfo (peer_a)
        write_frame(f, FT_CLIENT_INFO, peer_a + nonce_a + make_data("ci-alpha", 64))
        # 3: ServerInfo
        write_frame(f, FT_SERVER_INFO, nonce_s1 + make_data("si-1", 32))
        # 4: NotePreferred(true)
        write_frame(f, FT_NOTE_PREFERRED, b'\x01')
        # 5: SendPacket -> peer_b, 128 bytes data
        write_frame(f, FT_SEND_PACKET, peer_b + make_data("pkt-1", 128))
        # 6: SendPacket -> peer_c, 256 bytes data
        write_frame(f, FT_SEND_PACKET, peer_c + make_data("pkt-2", 256))
        # 7: RecvPacket from peer_b, 200 bytes data (v2: src key prefix)
        write_frame(f, FT_RECV_PACKET, peer_b + make_data("pkt-3", 200))
        # 8: KeepAlive
        write_frame(f, FT_KEEP_ALIVE, b'')
        # 9: Ping
        write_frame(f, FT_PING, ping1)
        # 10: Pong (matches ping1)
        write_frame(f, FT_PONG, ping1)
        # 11: Ping (no matching pong)
        write_frame(f, FT_PING, ping2)
        # 12: SendPacket -> peer_b, 64 bytes data
        write_frame(f, FT_SEND_PACKET, peer_b + make_data("pkt-4", 64))
        # 13: RecvPacket from peer_c, 512 bytes data
        write_frame(f, FT_RECV_PACKET, peer_c + make_data("pkt-5", 512))
        # 14: PeerGone (peer_b, Disconnected=0x00)
        write_frame(f, FT_PEER_GONE, peer_b + b'\x00')
        # 15: Health warning
        write_frame(f, FT_HEALTH, b'duplicate connection detected')
        # 16: NotePreferred(false)
        write_frame(f, FT_NOTE_PREFERRED, b'\x00')
        # 17: Health clear
        write_frame(f, FT_HEALTH, b'')
        # 18: SendPacket -> peer_c, 100 bytes data
        write_frame(f, FT_SEND_PACKET, peer_c + make_data("pkt-6", 100))
        # 19: Restarting (reconnect_ms=2000, try_for_ms=5000)
        write_frame(f, FT_RESTARTING, struct.pack(">II", 2000, 5000))

        # ===== Session 2 =====
        # 20: ServerKey
        write_frame(f, FT_SERVER_KEY, MAGIC + server_key)
        # 21: ClientInfo (peer_d)
        write_frame(f, FT_CLIENT_INFO, peer_d + nonce_d + make_data("ci-delta", 48))
        # 22: ServerInfo
        write_frame(f, FT_SERVER_INFO, nonce_s2 + make_data("si-2", 40))
        # 23: WatchConns
        write_frame(f, FT_WATCH_CONNS, b'')
        # 24: PeerPresent (peer_a, full format with IP+port+flags)
        ip_a = ipv4_to_16("192.168.1.10")
        write_frame(f, FT_PEER_PRESENT, peer_a + ip_a + struct.pack(">H", 41234) + b'\x01')
        # 25: PeerPresent (peer_c, full format)
        ip_c = ipv4_to_16("10.0.0.5")
        write_frame(f, FT_PEER_PRESENT, peer_c + ip_c + struct.pack(">H", 51234) + b'\x02')
        # 26: PeerPresent (peer_e, old format - key only)
        write_frame(f, FT_PEER_PRESENT, peer_e)
        # 27: ForwardPacket peer_a -> peer_d, 300 bytes data
        write_frame(f, FT_FORWARD_PACKET, peer_a + peer_d + make_data("pkt-7", 300))
        # 28: ForwardPacket peer_d -> peer_a, 150 bytes data
        write_frame(f, FT_FORWARD_PACKET, peer_d + peer_a + make_data("pkt-8", 150))
        # 29: RecvPacket from peer_a, 400 bytes data
        write_frame(f, FT_RECV_PACKET, peer_a + make_data("pkt-9", 400))
        # 30: Ping
        write_frame(f, FT_PING, ping3)
        # 31: Pong (matches ping3)
        write_frame(f, FT_PONG, ping3)
        # 32: Ping
        write_frame(f, FT_PING, ping4)
        # 33: Pong (matches ping4)
        write_frame(f, FT_PONG, ping4)
        # 34: ClosePeer (peer_e)
        write_frame(f, FT_CLOSE_PEER, peer_e)
        # 35: PeerGone (peer_e, NotHere=0x01)
        write_frame(f, FT_PEER_GONE, peer_e + b'\x01')
        # 36: PeerGone (peer_a, Disconnected=0x00)
        write_frame(f, FT_PEER_GONE, peer_a + b'\x00')
        # 37: KeepAlive
        write_frame(f, FT_KEEP_ALIVE, b'')
        # 38: NotePreferred(true)
        write_frame(f, FT_NOTE_PREFERRED, b'\x01')


if __name__ == "__main__":
    generate()
    print("Generated /app/derp_capture.bin")
