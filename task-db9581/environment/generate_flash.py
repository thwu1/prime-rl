#!/usr/bin/env python3
"""Generate synthetic eMMC flash dump for wear analysis.

Creates a binary flash image with block mapping, erase counts,
write journal with CRC-32 verification, and process attribution table.
"""
import struct
import random
import zlib

def generate():
    seed = 0x464C5348
    random.seed(seed)

    PAGE_SIZE = 4096
    PAGES_PER_BLOCK = 64
    TOTAL_BLOCKS = 512

    MANUFACTURE_TS = 1700000000
    CURRENT_TS = 1715654400
    TIME_SPAN = CURRENT_TS - MANUFACTURE_TS
    TBW_RATING = 100 * (10**9)

    PROCESSES = [
        (1, "systemd"), (2, "journald"), (3, "syslogd"),
        (100, "nginx"), (101, "postgres"), (102, "redis-server"),
        (200, "app-server"), (201, "data-collector"),
        (202, "telemetry-agent"), (203, "firmware-updater"),
        (300, "crond"), (301, "logrotate"),
        (400, "ota-daemon"), (500, "sensor-hub"),
        (501, "gps-logger"), (502, "camera-recorder"),
        (600, "watchdog"), (700, "db-backup"),
    ]

    # Block mapping with wear-leveling swaps
    l2p = list(range(TOTAL_BLOCKS))
    for _ in range(30):
        a = random.randint(0, TOTAL_BLOCKS - 1)
        b = random.randint(0, TOTAL_BLOCKS - 1)
        l2p[a], l2p[b] = l2p[b], l2p[a]

    p2l = [0] * TOTAL_BLOCKS
    for l_idx, p_idx in enumerate(l2p):
        p2l[p_idx] = l_idx

    # Erase counts per physical block, based on mapped logical zone
    erase_counts = []
    for p in range(TOTAL_BLOCKS):
        l = p2l[p]
        base = random.randint(5, 15)
        if l < 32:
            base += random.randint(80, 200)
        elif l < 64:
            base += random.randint(50, 120)
        elif l < 128:
            base += random.randint(20, 60)
        elif l < 256:
            base += random.randint(5, 25)
        erase_counts.append(base)

    # Journal entries
    NUM_ENTRIES = 40000
    weights = {
        1: 5, 2: 30, 3: 25, 100: 20, 101: 50, 102: 40, 200: 35,
        201: 15, 202: 10, 203: 2, 300: 8, 301: 5, 400: 3,
        500: 12, 501: 18, 502: 15, 600: 2, 700: 25,
    }
    wpids = []
    for pid, w in weights.items():
        wpids.extend([pid] * w)

    corrupt_set = set(random.sample(range(NUM_ENTRIES), int(NUM_ENTRIES * 0.04)))

    entries = []
    for i in range(NUM_ENTRIES):
        ts = random.randint(0, TIME_SPAN)
        pid = random.choice(wpids)

        if pid in (101, 102):
            lb = random.randint(0, 31)
        elif pid in (2, 3):
            lb = random.randint(32, 63)
        elif pid == 700:
            lb = random.randint(0, 63)
        elif pid in (200, 201):
            lb = random.randint(64, 127)
        elif pid in (500, 501, 502):
            lb = random.randint(128, 255)
        else:
            lb = random.randint(0, TOTAL_BLOCKS - 1)

        sp = random.randint(0, PAGES_PER_BLOCK - 1)
        pc = random.randint(1, min(16, PAGES_PER_BLOCK - sp))

        roll = random.random()
        if roll < 0.12:
            flags, dh = 2, 0  # read
        elif roll < 0.15:
            flags, dh = 1, 0  # erase
            sp, pc = 0, PAGES_PER_BLOCK
        else:
            flags, dh = 0, random.getrandbits(64)  # write

        prefix = struct.pack('<IHHHHIQ', ts, lb, sp, pc, pid, flags, dh)
        crc = zlib.crc32(prefix) & 0xFFFFFFFF
        if i in corrupt_set:
            crc ^= random.randint(1, 0xFFFFFFFF)
        entries.append(prefix + struct.pack('<II', crc, 0))

    # Write binary file
    with open('/app/flash_dump.bin', 'wb') as f:
        hdr = struct.pack('<IHHHHIIQII',
            0x464C5348, 1, PAGE_SIZE, PAGES_PER_BLOCK, TOTAL_BLOCKS,
            NUM_ENTRIES, len(PROCESSES), TBW_RATING, MANUFACTURE_TS, CURRENT_TS)
        f.write(hdr + b'\x00' * (64 - len(hdr)))

        for l in range(TOTAL_BLOCKS):
            f.write(struct.pack('<HH', l, l2p[l]))

        for p in range(TOTAL_BLOCKS):
            f.write(struct.pack('<I', erase_counts[p]))

        for e in entries:
            f.write(e)

        for pid, name in PROCESSES:
            nb = name.encode('ascii')
            f.write(struct.pack('<HH', pid, 0) + nb + b'\x00' * (64 - len(nb)))


if __name__ == '__main__':
    generate()
    print("Generated /app/flash_dump.bin")
