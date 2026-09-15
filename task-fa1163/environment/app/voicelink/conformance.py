"""
VoiceLink Conformance Test Suite

Tests legitimate call flows that MUST continue working after any security
patches.  Run:  python3 /app/voicelink/conformance.py

Respects VLSP_PORT environment variable (default 9877).
"""

import json
import os
import socket
import struct
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from protocol import HEADER_SIZE, MAGIC, VERSION, MsgType, encode, decode, make_id

PORT = int(os.environ.get('VLSP_PORT', '9877'))


class Client:
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(10)
        self.sock.connect(('127.0.0.1', PORT))

    def transact(self, mt, sid, sender, fields):
        self.sock.sendall(encode(mt, sid, sender, fields))
        hdr = b''
        while len(hdr) < HEADER_SIZE:
            c = self.sock.recv(HEADER_SIZE - len(hdr))
            if not c:
                raise ConnectionError("closed")
            hdr += c
        _, _, _, tl = struct.unpack_from('!4sHHI', hdr)
        bl = tl - HEADER_SIZE
        body = b''
        while len(body) < bl:
            c = self.sock.recv(bl - len(body))
            if not c:
                raise ConnectionError("closed")
            body += c
        return decode(hdr + body)

    def close(self):
        self.sock.close()


def test_normal_call_flow():
    """Full legitimate call: REGISTER -> OFFER -> ANSWER -> CANDIDATE -> CONNECT -> media."""
    c = Client()
    try:
        caller, callee, sid = make_id(), make_id(), make_id()
        z = b'\x00' * 12

        _, _, _, r = c.transact(MsgType.REGISTER, z, caller, {'display_name': 'alice'})
        assert r['status'] == 'ok', f"Register caller: {r}"
        _, _, _, r = c.transact(MsgType.REGISTER, z, callee, {'display_name': 'bob'})
        assert r['status'] == 'ok', f"Register callee: {r}"

        _, _, _, r = c.transact(MsgType.OFFER, sid, caller,
                                {'callee_id': callee.hex(), 'sdp': 'v=0\r\n'})
        assert r['status'] == 'ok', f"Offer: {r}"

        _, _, _, r = c.transact(MsgType.ANSWER, sid, callee, {'sdp': 'v=0\r\n'})
        assert r['status'] == 'ok', f"Answer: {r}"

        _, _, _, r = c.transact(MsgType.CANDIDATE, sid, caller,
                                {'candidate': 'candidate:1 1 udp 2130706431 10.0.0.1 5000 typ host'})
        assert r['status'] == 'ok', f"Caller candidate: {r}"
        _, _, _, r = c.transact(MsgType.CANDIDATE, sid, callee,
                                {'candidate': 'candidate:2 1 udp 2130706431 10.0.0.2 5000 typ host'})
        assert r['status'] == 'ok', f"Callee candidate: {r}"

        _, _, _, r = c.transact(MsgType.CONNECT, sid, callee, {})
        assert r['status'] == 'ok', f"Connect: {r}"

        _, _, _, sr = c.transact(MsgType.STATUS, sid, caller, {})
        status = json.loads(sr.get('session_status', '{}'))
        assert status['caller']['audio']['transmitting'], "Caller audio not transmitting"
        assert status['callee']['audio']['transmitting'], "Callee audio not transmitting"
        assert status['callee']['consent_given'], "Callee consent not recorded"

        print("PASS: test_normal_call_flow")
    finally:
        c.close()


def test_hangup_stops_media():
    """Hangup must stop all media."""
    c = Client()
    try:
        caller, callee, sid = make_id(), make_id(), make_id()
        z = b'\x00' * 12
        c.transact(MsgType.REGISTER, z, caller, {'display_name': 'alice'})
        c.transact(MsgType.REGISTER, z, callee, {'display_name': 'bob'})
        c.transact(MsgType.OFFER, sid, caller,
                   {'callee_id': callee.hex(), 'sdp': 'v=0\r\n'})
        c.transact(MsgType.ANSWER, sid, callee, {'sdp': 'v=0\r\n'})
        c.transact(MsgType.CANDIDATE, sid, caller,
                   {'candidate': 'c:1 1 udp 1 10.0.0.1 5000 typ host'})
        c.transact(MsgType.CANDIDATE, sid, callee,
                   {'candidate': 'c:2 1 udp 1 10.0.0.2 5000 typ host'})
        c.transact(MsgType.CONNECT, sid, callee, {})

        _, _, _, r = c.transact(MsgType.HANGUP, sid, caller, {})
        assert r['status'] == 'ok', f"Hangup: {r}"

        _, _, _, sr = c.transact(MsgType.STATUS, sid, caller, {})
        status = json.loads(sr.get('session_status', '{}'))
        assert not status['caller']['audio']['transmitting'], "Caller still tx after hangup"
        assert not status['callee']['audio']['transmitting'], "Callee still tx after hangup"

        print("PASS: test_hangup_stops_media")
    finally:
        c.close()


def test_answer_requires_callee():
    """Only callee can send ANSWER."""
    c = Client()
    try:
        caller, callee, sid = make_id(), make_id(), make_id()
        z = b'\x00' * 12
        c.transact(MsgType.REGISTER, z, caller, {'display_name': 'alice'})
        c.transact(MsgType.REGISTER, z, callee, {'display_name': 'bob'})
        c.transact(MsgType.OFFER, sid, caller,
                   {'callee_id': callee.hex(), 'sdp': 'v=0\r\n'})

        _, _, _, r = c.transact(MsgType.ANSWER, sid, caller, {'sdp': 'v=0\r\n'})
        assert r['status'] == 'error', "Caller should not be able to answer"

        print("PASS: test_answer_requires_callee")
    finally:
        c.close()


def test_media_config_integer_policy():
    """media_policy=1 (integer) auto-enables media — legitimate use."""
    c = Client()
    try:
        caller, callee, sid = make_id(), make_id(), make_id()
        z = b'\x00' * 12
        c.transact(MsgType.REGISTER, z, caller, {'display_name': 'alice'})
        c.transact(MsgType.REGISTER, z, callee, {'display_name': 'bob'})
        c.transact(MsgType.OFFER, sid, caller,
                   {'callee_id': callee.hex(), 'sdp': 'v=0\r\n'})

        _, _, _, r = c.transact(MsgType.MEDIA_CONFIG, sid, caller,
                                {'media_policy': 1})
        assert r['status'] == 'ok', f"media_config: {r}"

        _, _, _, sr = c.transact(MsgType.STATUS, sid, caller, {})
        status = json.loads(sr.get('session_status', '{}'))
        assert status['callee']['audio']['transmitting'], \
            "media_policy=1 should auto-enable callee audio"

        print("PASS: test_media_config_integer_policy")
    finally:
        c.close()


def test_sdp_update_connected_single_device():
    """SDP_UPDATE works for a connected single-device peer."""
    c = Client()
    try:
        caller, callee, sid = make_id(), make_id(), make_id()
        z = b'\x00' * 12
        c.transact(MsgType.REGISTER, z, caller,
                   {'display_name': 'alice', 'device_count': 1})
        c.transact(MsgType.REGISTER, z, callee,
                   {'display_name': 'bob', 'device_count': 1})
        c.transact(MsgType.OFFER, sid, caller,
                   {'callee_id': callee.hex(), 'sdp': 'v=0\r\n'})
        c.transact(MsgType.ANSWER, sid, callee, {'sdp': 'v=0\r\n'})
        c.transact(MsgType.CANDIDATE, sid, caller,
                   {'candidate': 'c:1 1 udp 1 10.0.0.1 5000 typ host'})
        c.transact(MsgType.CANDIDATE, sid, callee,
                   {'candidate': 'c:2 1 udp 1 10.0.0.2 5000 typ host'})
        c.transact(MsgType.CONNECT, sid, callee, {})

        _, _, _, r = c.transact(MsgType.SDP_UPDATE, sid, caller,
                                {'sdp': 'v=0\r\n', 'reason': 'add_video'})
        assert r['status'] == 'ok', f"SDP_UPDATE: {r}"

        print("PASS: test_sdp_update_connected_single_device")
    finally:
        c.close()


if __name__ == '__main__':
    tests = [
        test_normal_call_flow,
        test_hangup_stops_media,
        test_answer_requires_callee,
        test_media_config_integer_policy,
        test_sdp_update_connected_single_device,
    ]
    failures = 0
    for t in tests:
        try:
            t()
        except Exception as e:
            print(f"FAIL: {t.__name__}: {e}")
            traceback.print_exc()
            failures += 1
    if failures:
        print(f"\n{failures}/{len(tests)} tests FAILED")
        sys.exit(1)
    else:
        print(f"\nAll {len(tests)} tests passed")
        sys.exit(0)
