#!/usr/bin/env python3
"""Mock Authority Server for Pest Control testing.

Implements the authority side of the Pest Control binary protocol.
Tracks policies per site and writes state to /tmp/authority_state.json.
"""

import asyncio
import json
import os
import struct
import sys

LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 20547
STATE_FILE = "/tmp/authority_state.json"

# Target populations per site (static, returned via TargetPopulations)
TARGETS = {
    1001: [{"species": "dog", "min": 1, "max": 5}],
    1002: [{"species": "cat", "min": 5, "max": 10}],
    1003: [{"species": "bird", "min": 3, "max": 8}],
    1004: [{"species": "deer", "min": 5, "max": 20}],
    1005: [{"species": "bee", "min": 100, "max": 500}],
    1006: [
        {"species": "rat", "min": 0, "max": 10},
        {"species": "sparrow", "min": 5, "max": 15},
        {"species": "fish", "min": 2, "max": 7},
    ],
    1007: [{"species": "wolf", "min": 3, "max": 7}],
    1008: [{"species": "ant", "min": 10, "max": 50}],
    1009: [{"species": "fox", "min": 1, "max": 5}],
    1010: [{"species": "bear", "min": 0, "max": 3}],
    1011: [{"species": "owl", "min": 2, "max": 8}],
    1012: [{"species": "snake", "min": 5, "max": 15}],
    1013: [],
    1014: [{"species": "elk", "min": 10, "max": 20}],
}

# Global policy state: {site_id: {policy_id: {"species": str, "action": str}}}
policies = {}
next_pid = {}


def compute_checksum(data):
    return (256 - sum(data) % 256) % 256


def verify_checksum(data):
    return sum(data) % 256 == 0


def build_msg(msg_type, content):
    total_len = 1 + 4 + len(content) + 1
    header = struct.pack("!BI", msg_type, total_len)
    body = header + content
    return body + bytes([compute_checksum(body)])


def msg_hello():
    p = b"pestcontrol"
    return build_msg(0x50, struct.pack("!I", len(p)) + p + struct.pack("!I", 1))


def msg_error(text):
    b = text.encode("ascii")
    return build_msg(0x51, struct.pack("!I", len(b)) + b)


def msg_ok():
    return build_msg(0x52, b"")


def msg_target_populations(site, targets):
    c = struct.pack("!II", site, len(targets))
    for t in targets:
        sb = t["species"].encode("ascii")
        c += struct.pack("!I", len(sb)) + sb + struct.pack("!II", t["min"], t["max"])
    return build_msg(0x54, c)


def msg_policy_result(pid):
    return build_msg(0x57, struct.pack("!I", pid))


def save_state():
    state = {}
    for sid, sp in policies.items():
        state[str(sid)] = {str(pid): pd for pid, pd in sp.items()}
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.rename(tmp, STATE_FILE)


async def read_n(reader, n):
    data = b""
    while len(data) < n:
        chunk = await reader.read(n - len(data))
        if not chunk:
            raise ConnectionError("EOF")
        data += chunk
    return data


async def read_message(reader):
    type_byte = await read_n(reader, 1)
    length_bytes = await read_n(reader, 4)
    total_length = struct.unpack("!I", length_bytes)[0]
    if total_length < 6:
        raise ValueError("message too short")
    rest = await read_n(reader, total_length - 5)
    full = type_byte + length_bytes + rest
    if not verify_checksum(full):
        raise ValueError("bad checksum")
    return type_byte[0], rest[:-1]


async def handle_client(reader, writer):
    site = None
    try:
        # Read Hello
        msg_type, content = await read_message(reader)
        if msg_type != 0x50:
            writer.write(msg_error("expected Hello"))
            await writer.drain()
            return
        plen = struct.unpack_from("!I", content, 0)[0]
        proto = content[4:4 + plen].decode("ascii")
        ver = struct.unpack_from("!I", content, 4 + plen)[0]
        if proto != "pestcontrol" or ver != 1:
            writer.write(msg_error("bad hello params"))
            await writer.drain()
            return

        # Send Hello
        writer.write(msg_hello())
        await writer.drain()

        # Read DialAuthority
        msg_type, content = await read_message(reader)
        if msg_type != 0x53:
            writer.write(msg_error("expected DialAuthority"))
            await writer.drain()
            return
        site = struct.unpack_from("!I", content, 0)[0]

        if site not in policies:
            policies[site] = {}
        if site not in next_pid:
            next_pid[site] = 1

        # Send TargetPopulations
        targets = TARGETS.get(site, [])
        writer.write(msg_target_populations(site, targets))
        await writer.drain()

        # Handle CreatePolicy / DeletePolicy
        while True:
            msg_type, content = await read_message(reader)

            if msg_type == 0x55:  # CreatePolicy
                slen = struct.unpack_from("!I", content, 0)[0]
                species = content[4:4 + slen].decode("ascii")
                action_byte = content[4 + slen]
                if action_byte == 0x90:
                    action = "cull"
                elif action_byte == 0xa0:
                    action = "conserve"
                else:
                    writer.write(msg_error("bad action byte"))
                    await writer.drain()
                    return
                pid = next_pid[site]
                next_pid[site] += 1
                policies[site][pid] = {"species": species, "action": action}
                save_state()
                writer.write(msg_policy_result(pid))
                await writer.drain()

            elif msg_type == 0x56:  # DeletePolicy
                pid = struct.unpack_from("!I", content, 0)[0]
                if pid not in policies.get(site, {}):
                    writer.write(msg_error("no such policy"))
                    await writer.drain()
                    return
                del policies[site][pid]
                save_state()
                writer.write(msg_ok())
                await writer.drain()

            else:
                writer.write(msg_error("unexpected message type"))
                await writer.drain()
                return

    except (ConnectionError, asyncio.IncompleteReadError, ValueError):
        pass
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except (ConnectionError, OSError):
            pass


async def main():
    save_state()
    server = await asyncio.start_server(handle_client, LISTEN_HOST, LISTEN_PORT)
    print(f"Authority server on {LISTEN_HOST}:{LISTEN_PORT}", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
