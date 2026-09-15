#!/usr/bin/env python3
"""Generate deterministic synthetic market data: PCAP file + SQLite reference DB.

Produces:
  /app/data/market_feed.pcap   - pcap with UDP multicast market data + noise packets
  /app/data/instruments.db     - SQLite reference database with instrument metadata
"""
import struct
import random
import sqlite3
import os

random.seed(54321)

# -- PCAP constants -----------------------------------------------------------
PCAP_MAGIC = 0xa1b2c3d4
LINK_ETHERNET = 1

# -- Network constants --------------------------------------------------------
SRC_MAC = b'\x00\x11\x22\x33\x44\x55'
DST_MAC = b'\x01\x00\x5e\x01\x01\x01'
BCAST_MAC = b'\xff\xff\xff\xff\xff\xff'
SRC_IP = b'\x0a\x00\x01\x64'        # 10.0.1.100
DST_IP_A = b'\xef\x01\x01\x01'      # 239.1.1.1
DST_IP_B = b'\xef\x01\x01\x02'      # 239.1.1.2
ARP_SRC = b'\x0a\x00\x01\xc8'       # 10.0.1.200
PORT_A = 15000
PORT_B = 15001
SRC_PORT = 30000

# -- XMBO constants ----------------------------------------------------------
RECORD_SIZE = 64
CHANNEL_HDR_SIZE = 8
RECORD_FMT = '<QQqIBBHQI20s'
ADD, CANCEL, MODIFY, TRADE, FILL = 0x41, 0x43, 0x4D, 0x54, 0x46
BID, ASK = 0x42, 0x53
BASE_TS = 34_200_000_000_000  # 9:30:00 UTC in nanoseconds since midnight
FLAG_SNAPSHOT = 0x0004

# -- Instruments --------------------------------------------------------------
INSTRUMENTS = {
    1001: {'symbol': 'ES.FUT', 'base': 4500.00, 'tick': 0.25},
    1002: {'symbol': 'NQ.FUT', 'base': 15000.00, 'tick': 0.25},
}


def p2fp(price):
    return int(round(price * 1_000_000_000))


def ip_checksum(data):
    if len(data) % 2:
        data += b'\x00'
    s = 0
    for i in range(0, len(data), 2):
        s += (data[i] << 8) + data[i + 1]
    s = (s >> 16) + (s & 0xffff)
    s += s >> 16
    return ~s & 0xffff


def make_udp_frame(dst_ip, dst_port, payload, ip_id=0):
    """Build Ethernet + IPv4 + UDP frame."""
    udp_len = 8 + len(payload)
    udp_hdr = struct.pack('!HHHH', SRC_PORT, dst_port, udp_len, 0)

    ip_total = 20 + udp_len
    ip_raw = struct.pack('!BBHHHBBH4s4s',
                         0x45, 0x00, ip_total, ip_id & 0xFFFF, 0x4000,
                         64, 17, 0, SRC_IP, dst_ip)
    chk = ip_checksum(ip_raw)
    ip_hdr = ip_raw[:10] + struct.pack('!H', chk) + ip_raw[12:]

    eth_hdr = DST_MAC + SRC_MAC + struct.pack('!H', 0x0800)
    return eth_hdr + ip_hdr + udp_hdr + payload


def make_arp_frame():
    """Create a noise ARP request frame."""
    eth = BCAST_MAC + SRC_MAC + struct.pack('!H', 0x0806)
    arp = struct.pack('!HHBBH6s4s6s4s',
                      1, 0x0800, 6, 4, 1,
                      SRC_MAC, SRC_IP,
                      b'\x00' * 6, ARP_SRC)
    return eth + arp


def make_icmp_frame(ip_id=0):
    """Create a noise ICMP echo request frame."""
    icmp_payload = b'\x00' * 32
    icmp_raw = struct.pack('!BBH', 8, 0, 0) + struct.pack('!HH', 1, 1) + icmp_payload
    icmp_chk = ip_checksum(icmp_raw)
    icmp_data = struct.pack('!BBH', 8, 0, icmp_chk) + struct.pack('!HH', 1, 1) + icmp_payload

    ip_total = 20 + len(icmp_data)
    ip_raw = struct.pack('!BBHHHBBH4s4s',
                         0x45, 0x00, ip_total, ip_id & 0xFFFF, 0x4000,
                         64, 1, 0, SRC_IP, ARP_SRC)
    chk = ip_checksum(ip_raw)
    ip_hdr = ip_raw[:10] + struct.pack('!H', chk) + ip_raw[12:]

    eth = DST_MAC + SRC_MAC + struct.pack('!H', 0x0800)
    return eth + ip_hdr + icmp_data


def pack_xmbo_record(ts, oid, price, qty, action, side, flags, seq, inst_id):
    """Pack a single 64-byte XMBO record."""
    return struct.pack(RECORD_FMT,
                       ts, oid, p2fp(price), qty, action, side,
                       flags, seq, inst_id, b'\x00' * 20)


def pack_channel_payload(channel_id, seq_start, record_bytes_list):
    """Pack channel header (8 bytes) + concatenated record bytes."""
    msg_count = len(record_bytes_list)
    hdr = struct.pack('<HIH', channel_id, seq_start, msg_count)
    return hdr + b''.join(record_bytes_list)


# -- Order Book Simulator -----------------------------------------------------

class BookSim:
    def __init__(self, inst_id, base_price, tick):
        self.inst_id = inst_id
        self.base = base_price
        self.tick = tick
        self.orders = {}  # oid -> [price, qty, side]
        self.next_oid = inst_id * 10000

    def _oid(self):
        self.next_oid += 1
        return self.next_oid

    def add(self, ts, side, price, qty, seq, flags=0):
        oid = self._oid()
        self.orders[oid] = [price, qty, side]
        rec = pack_xmbo_record(ts, oid, price, qty, ADD, side, flags, seq, self.inst_id)
        return oid, rec

    def cancel(self, ts, oid, seq):
        if oid in self.orders:
            p, q, s = self.orders.pop(oid)
            return pack_xmbo_record(ts, oid, p, 0, CANCEL, s, 0, seq, self.inst_id)
        return None

    def modify(self, ts, oid, seq, new_price=None, new_qty=None):
        if oid in self.orders:
            p, q, s = self.orders[oid]
            p = new_price if new_price is not None else p
            q = new_qty if new_qty is not None else q
            self.orders[oid] = [p, q, s]
            return pack_xmbo_record(ts, oid, p, q, MODIFY, s, 0, seq, self.inst_id)
        return None

    def trade(self, ts, oid, fill_qty, seq):
        if oid in self.orders:
            p, q, s = self.orders[oid]
            if fill_qty >= q:
                self.orders.pop(oid)
                return pack_xmbo_record(ts, oid, p, q, FILL, s, 0, seq, self.inst_id), True
            else:
                self.orders[oid][1] = q - fill_qty
                return pack_xmbo_record(ts, oid, p, fill_qty, TRADE, s, 0, seq, self.inst_id), False
        return None, False

    def best(self, side):
        prices = [p for _, (p, q, s) in self.orders.items() if s == side]
        if not prices:
            return None
        return max(prices) if side == BID else min(prices)

    def pick_order(self, side=None):
        candidates = [(oid, p, q, s) for oid, (p, q, s) in self.orders.items()
                       if side is None or s == side]
        return random.choice(candidates) if candidates else None


def generate():
    os.makedirs('/app/data', exist_ok=True)
    os.makedirs('/app/output', exist_ok=True)

    # -- Generate events for both instruments with GLOBAL sequence --
    global_seq = 0
    all_events = []  # (timestamp, record_bytes, instrument_id)

    for inst_id, info in INSTRUMENTS.items():
        sim = BookSim(inst_id, info['base'], info['tick'])
        ts = BASE_TS
        iceberg_count = 0

        # Phase 1: Snapshot
        for i in range(5):
            bid_price = info['base'] - (i + 1) * info['tick']
            ask_price = info['base'] + i * info['tick']
            for _ in range(random.randint(2, 4)):
                global_seq += 1
                _, rec = sim.add(ts, BID, bid_price, random.randint(2, 20) * 5, global_seq, FLAG_SNAPSHOT)
                all_events.append((ts, rec, inst_id))
            for _ in range(random.randint(2, 4)):
                global_seq += 1
                _, rec = sim.add(ts, ASK, ask_price, random.randint(2, 20) * 5, global_seq, FLAG_SNAPSHOT)
                all_events.append((ts, rec, inst_id))

        # Phase 2: Trading
        num_events = 250 if inst_id == 1001 else 200
        ts += 1_000_000_000

        for i in range(num_events):
            ts += random.randint(500_000, 50_000_000)
            r = random.random()

            if r < 0.28:
                side = random.choice([BID, ASK])
                b = sim.best(ASK if side == BID else BID)
                ref = b if b else info['base']
                if side == BID:
                    price = ref - random.randint(1, 8) * info['tick']
                else:
                    price = ref + random.randint(1, 8) * info['tick']
                global_seq += 1
                _, rec = sim.add(ts, side, price, random.randint(1, 30) * 5, global_seq)
                all_events.append((ts, rec, inst_id))

            elif r < 0.48:
                o = sim.pick_order()
                if o:
                    global_seq += 1
                    rec = sim.cancel(ts, o[0], global_seq)
                    if rec:
                        all_events.append((ts, rec, inst_id))

            elif r < 0.62:
                o = sim.pick_order()
                if o:
                    oid, p, q, s = o
                    global_seq += 1
                    if random.random() < 0.5:
                        rec = sim.modify(ts, oid, global_seq, new_qty=max(5, q + random.choice([-10, -5, 5, 10])))
                    else:
                        rec = sim.modify(ts, oid, global_seq, new_price=p + random.choice([-2, -1, 1, 2]) * info['tick'])
                    if rec:
                        all_events.append((ts, rec, inst_id))

            else:
                side_to_hit = random.choice([BID, ASK])
                o = sim.pick_order(side_to_hit)
                if o:
                    oid, p, q, s = o
                    if random.random() < 0.3 or q <= 5:
                        global_seq += 1
                        rec, was_fill = sim.trade(ts, oid, q, global_seq)
                        if rec:
                            all_events.append((ts, rec, inst_id))
                            if was_fill and iceberg_count < 3 and i > 30 and random.random() < 0.25:
                                reload_ts = ts + random.randint(10_000, 90_000)
                                global_seq += 1
                                _, reload_rec = sim.add(reload_ts, s, p, random.randint(2, 20) * 5, global_seq)
                                all_events.append((reload_ts, reload_rec, inst_id))
                                iceberg_count += 1
                    else:
                        fq = random.randint(1, max(1, q // 2))
                        fq = min(fq, q - 1)
                        if fq > 0:
                            global_seq += 1
                            rec, _ = sim.trade(ts, oid, fq, global_seq)
                            if rec:
                                all_events.append((ts, rec, inst_id))

    # Sort all events by timestamp, then by sequence for ties
    all_events.sort(key=lambda x: (x[0], struct.unpack('<Q', x[1][32:40])[0]))

    print(f"Generated {len(all_events)} total events (global seq up to {global_seq})")

    # -- Package into UDP packets -----------------------------------------
    # Group consecutive events into packets of 1-3 records
    packets = []  # (ts_sec, ts_usec, frame_bytes)
    ip_id_counter = 1000
    capture_base_sec = 1700000000  # Arbitrary pcap epoch base

    ch_a_seq = 0  # Channel A channel-level sequence
    ch_b_seq = 0  # Channel B channel-level sequence

    # Define channel A gap positions (channel-level seq numbers to skip)
    ch_a_gap_positions = {80, 81, 82, 200, 201, 202, 203, 204}

    idx = 0
    while idx < len(all_events):
        batch_size = random.choice([1, 1, 2, 2, 3])
        batch_size = min(batch_size, len(all_events) - idx)

        batch_records = []
        batch_ts = all_events[idx][0]
        for j in range(batch_size):
            batch_records.append(all_events[idx + j][1])
        idx += batch_size

        ts_offset_sec = (batch_ts - BASE_TS) / 1_000_000_000
        cap_sec = capture_base_sec + int(ts_offset_sec)
        cap_usec = int((ts_offset_sec - int(ts_offset_sec)) * 1_000_000)

        # Channel A packet
        ch_a_seq += batch_size
        # Skip over gap positions
        while ch_a_seq in ch_a_gap_positions:
            ch_a_seq += 1

        payload_a = pack_channel_payload(1, ch_a_seq - batch_size + 1, batch_records)
        frame_a = make_udp_frame(DST_IP_A, PORT_A, payload_a, ip_id_counter)
        ip_id_counter += 1
        jitter_a = random.randint(1, 50)
        packets.append((cap_sec, cap_usec + jitter_a, frame_a))

        # Channel B gets ~40% of packets (same records, different channel seq)
        if random.random() < 0.40:
            ch_b_seq += batch_size
            payload_b = pack_channel_payload(2, ch_b_seq - batch_size + 1, batch_records)
            frame_b = make_udp_frame(DST_IP_B, PORT_B, payload_b, ip_id_counter)
            ip_id_counter += 1
            jitter_b = random.randint(50, 200)
            packets.append((cap_sec, cap_usec + jitter_b, frame_b))

    # -- Insert noise packets (ARP, ICMP) ---------------------------------
    num_noise = min(20, len(packets) // 5)
    noise_indices = sorted(random.sample(range(len(packets)), num_noise))
    noise_packets = []
    for i, pos in enumerate(noise_indices):
        t_sec, t_usec, _ = packets[pos]
        if i % 2 == 0:
            noise_packets.append((t_sec, t_usec + 500, make_arp_frame()))
        else:
            noise_packets.append((t_sec, t_usec + 500, make_icmp_frame(ip_id_counter)))
            ip_id_counter += 1

    packets.extend(noise_packets)
    packets.sort(key=lambda x: (x[0], x[1]))

    # -- Write PCAP file --------------------------------------------------
    pcap_path = '/app/data/market_feed.pcap'
    with open(pcap_path, 'wb') as f:
        f.write(struct.pack('<IHHiIII', PCAP_MAGIC, 2, 4, 0, 0, 65535, LINK_ETHERNET))
        for ts_sec, ts_usec, frame in packets:
            f.write(struct.pack('<IIII', ts_sec, ts_usec, len(frame), len(frame)))
            f.write(frame)

    print(f"Generated {pcap_path}: {len(packets)} packets")
    print(f"  Channel A: seq up to {ch_a_seq}")
    print(f"  Channel B: seq up to {ch_b_seq}")

    # -- Create SQLite reference database ---------------------------------
    db_path = '/app/data/instruments.db'
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute('''CREATE TABLE instruments (
        instrument_id INTEGER PRIMARY KEY,
        symbol TEXT NOT NULL,
        tick_size REAL NOT NULL,
        lot_size INTEGER NOT NULL,
        price_scale INTEGER NOT NULL,
        channel_a_port INTEGER NOT NULL,
        channel_b_port INTEGER NOT NULL
    )''')

    c.execute('''CREATE TABLE sessions (
        instrument_id INTEGER,
        trading_start_ns INTEGER NOT NULL,
        trading_end_ns INTEGER NOT NULL,
        FOREIGN KEY (instrument_id) REFERENCES instruments(instrument_id)
    )''')

    c.execute('''CREATE TABLE channel_config (
        channel_id INTEGER PRIMARY KEY,
        multicast_group TEXT NOT NULL,
        port INTEGER NOT NULL,
        description TEXT
    )''')

    c.execute('''CREATE TABLE gap_recovery (
        channel_id INTEGER,
        max_gap_tolerance INTEGER NOT NULL,
        recovery_source TEXT,
        notes TEXT
    )''')

    for inst_id, info in INSTRUMENTS.items():
        c.execute('INSERT INTO instruments VALUES (?, ?, ?, ?, ?, ?, ?)',
                  (inst_id, info['symbol'], info['tick'], 1, 1_000_000_000, PORT_A, PORT_B))
        c.execute('INSERT INTO sessions VALUES (?, ?, ?)',
                  (inst_id, BASE_TS, BASE_TS + 23_400_000_000_000))

    c.execute('INSERT INTO channel_config VALUES (?, ?, ?, ?)',
              (1, '239.1.1.1', PORT_A, 'Primary feed - all instruments'))
    c.execute('INSERT INTO channel_config VALUES (?, ?, ?, ?)',
              (2, '239.1.1.2', PORT_B, 'Backup feed - partial duplicate'))

    c.execute('INSERT INTO gap_recovery VALUES (?, ?, ?, ?)',
              (1, 10, 'channel_b', 'Use channel B to recover gaps in channel A'))
    c.execute('INSERT INTO gap_recovery VALUES (?, ?, ?, ?)',
              (2, 10, None, 'No recovery source for channel B'))

    conn.commit()
    conn.close()
    print(f"Generated {db_path}")


if __name__ == '__main__':
    generate()
