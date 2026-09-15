#!/usr/bin/env python3
"""Pest Control Coordination Server — reference solution."""

import asyncio
import struct
from collections import defaultdict

LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 9000
AUTH_HOST = "127.0.0.1"
AUTH_PORT = 20547

# Shared state
target_cache = {}           # site -> [{species, min, max}]
policy_state = {}           # site -> {species: (policy_id, action)}
site_locks = defaultdict(asyncio.Lock)


# ---------------------------------------------------------------------------
# Binary protocol helpers
# ---------------------------------------------------------------------------

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


def msg_dial_authority(site):
    return build_msg(0x53, struct.pack("!I", site))


def msg_create_policy(species, action):
    sb = species.encode("ascii")
    action_byte = 0x90 if action == "cull" else 0xa0
    return build_msg(0x55, struct.pack("!I", len(sb)) + sb + bytes([action_byte]))


def msg_delete_policy(pid):
    return build_msg(0x56, struct.pack("!I", pid))


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


# ---------------------------------------------------------------------------
# Authority client operations
# ---------------------------------------------------------------------------

async def connect_authority(site):
    """Connect to authority, Hello, DialAuthority, return (reader, writer, targets)."""
    reader, writer = await asyncio.open_connection(AUTH_HOST, AUTH_PORT)
    try:
        # Send Hello
        writer.write(msg_hello())
        await writer.drain()
        # Read Hello
        msg_type, _ = await read_message(reader)
        if msg_type != 0x50:
            raise ValueError("Authority did not send Hello")
        # Send DialAuthority
        writer.write(msg_dial_authority(site))
        await writer.drain()
        # Read TargetPopulations
        msg_type, content = await read_message(reader)
        if msg_type != 0x54:
            raise ValueError("Expected TargetPopulations")
        offset = 4  # skip site u32
        n_pops = struct.unpack_from("!I", content, offset)[0]
        offset += 4
        targets = []
        for _ in range(n_pops):
            slen = struct.unpack_from("!I", content, offset)[0]
            offset += 4
            species = content[offset:offset + slen].decode("ascii")
            offset += slen
            mn, mx = struct.unpack_from("!II", content, offset)
            offset += 8
            targets.append({"species": species, "min": mn, "max": mx})
        return reader, writer, targets
    except Exception:
        writer.close()
        try:
            await writer.wait_closed()
        except (ConnectionError, OSError):
            pass
        raise


async def auth_create_policy(auth_r, auth_w, species, action):
    auth_w.write(msg_create_policy(species, action))
    await auth_w.drain()
    msg_type, content = await read_message(auth_r)
    if msg_type != 0x57:
        raise ValueError(f"Expected PolicyResult, got 0x{msg_type:02x}")
    return struct.unpack_from("!I", content, 0)[0]


async def auth_delete_policy(auth_r, auth_w, pid):
    auth_w.write(msg_delete_policy(pid))
    await auth_w.drain()
    msg_type, _ = await read_message(auth_r)
    if msg_type != 0x52:
        raise ValueError(f"Expected OK, got 0x{msg_type:02x}")


# ---------------------------------------------------------------------------
# Policy reconciliation
# ---------------------------------------------------------------------------

async def reconcile_policies(site, populations):
    """Reconcile policies for a site based on latest observation counts."""
    async with site_locks[site]:
        # Connect to authority for this site
        auth_r, auth_w, targets = await connect_authority(site)
        target_cache[site] = targets

        if site not in policy_state:
            policy_state[site] = {}
        current = policy_state[site]
        visit_counts = dict(populations)

        try:
            for target in targets:
                sp = target["species"]
                count = visit_counts.get(sp, 0)

                if count < target["min"]:
                    desired = "conserve"
                elif count > target["max"]:
                    desired = "cull"
                else:
                    desired = None

                cur = current.get(sp)

                # Delete if wrong action or no longer needed
                if cur is not None and (desired is None or cur[1] != desired):
                    await auth_delete_policy(auth_r, auth_w, cur[0])
                    del current[sp]
                    cur = None

                # Create if needed and not already present
                if desired is not None and cur is None:
                    pid = await auth_create_policy(auth_r, auth_w, sp, desired)
                    current[sp] = (pid, desired)
        finally:
            auth_w.close()
            try:
                await auth_w.wait_closed()
            except (ConnectionError, OSError):
                pass


# ---------------------------------------------------------------------------
# Site visitor client handler (server side)
# ---------------------------------------------------------------------------

async def handle_client(reader, writer):
    try:
        # Read Hello from client
        msg_type, content = await read_message(reader)
        if msg_type != 0x50:
            writer.write(msg_error("expected Hello"))
            await writer.drain()
            return
        # Validate Hello
        plen = struct.unpack_from("!I", content, 0)[0]
        proto = content[4:4 + plen].decode("ascii")
        ver = struct.unpack_from("!I", content, 4 + plen)[0]
        if proto != "pestcontrol" or ver != 1:
            writer.write(msg_error("bad hello"))
            await writer.drain()
            return

        # Send Hello to client
        writer.write(msg_hello())
        await writer.drain()

        # Process messages
        while True:
            msg_type, content = await read_message(reader)

            if msg_type == 0x58:  # SiteVisit
                site = struct.unpack_from("!I", content, 0)[0]
                n_pops = struct.unpack_from("!I", content, 4)[0]
                offset = 8
                populations = []
                for _ in range(n_pops):
                    slen = struct.unpack_from("!I", content, offset)[0]
                    offset += 4
                    species = content[offset:offset + slen].decode("ascii")
                    offset += slen
                    count = struct.unpack_from("!I", content, offset)[0]
                    offset += 4
                    populations.append((species, count))

                # Check for conflicting duplicates
                seen = {}
                conflict = False
                for sp, cnt in populations:
                    if sp in seen and seen[sp] != cnt:
                        conflict = True
                        break
                    seen[sp] = cnt

                if conflict:
                    writer.write(msg_error("conflicting species counts"))
                    await writer.drain()
                    return

                # Deduplicate and reconcile (fire-and-forget)
                deduped = list(seen.items())
                asyncio.create_task(_safe_reconcile(site, deduped))
            else:
                writer.write(msg_error("unexpected message type"))
                await writer.drain()
                return

    except ValueError as e:
        try:
            writer.write(msg_error(str(e)))
            await writer.drain()
        except (ConnectionError, OSError):
            pass
    except (ConnectionError, asyncio.IncompleteReadError):
        pass
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except (ConnectionError, OSError):
            pass


async def _safe_reconcile(site, populations):
    try:
        await reconcile_policies(site, populations)
    except Exception as e:
        print(f"Reconciliation error for site {site}: {e}", flush=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    server = await asyncio.start_server(handle_client, LISTEN_HOST, LISTEN_PORT)
    print(f"Pest Control server on {LISTEN_HOST}:{LISTEN_PORT}", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
