#!/usr/bin/env python3
"""Generate binary crash dump artifacts for a virtio-net device forensics task."""
import struct
import os

VIRTQ_DESC_F_NEXT = 1
VIRTQ_DESC_F_WRITE = 2
VIRTQ_DESC_F_INDIRECT = 4

def pack_desc(addr, length, flags, next_idx):
    return struct.pack('<QIHH', addr, length, flags, next_idx)

def build_desc_table(entries, queue_size):
    data = bytearray(queue_size * 16)
    for i, entry in enumerate(entries):
        if entry is not None:
            struct.pack_into('<QIHH', data, i * 16, *entry)
    return bytes(data)

def build_avail_ring(flags, idx, ring_entries, queue_size):
    size = 4 + queue_size * 2 + 2
    data = bytearray(size)
    struct.pack_into('<HH', data, 0, flags, idx)
    for i, entry in enumerate(ring_entries):
        struct.pack_into('<H', data, 4 + i * 2, entry)
    return bytes(data)

def build_used_ring(flags, idx, entries, queue_size):
    size = 4 + queue_size * 8 + 2
    data = bytearray(size)
    struct.pack_into('<HH', data, 0, flags, idx)
    for i, (id_val, len_val) in enumerate(entries):
        struct.pack_into('<II', data, 4 + i * 8, id_val, len_val)
    return bytes(data)

# ====== Guest Memory (1MB) ======
GUEST_MEM_SIZE = 0x100000
guest_memory = bytearray(GUEST_MEM_SIZE)

# 12-byte virtio-net header (with MRG_RXBUF): flags,gso_type,hdr_len,gso_size,csum_start,csum_offset,num_buffers
VNET_HDR = struct.pack('<BBHHHHH', 0, 0, 0, 0, 0, 0, 0)  # 12 bytes

# ====== TX Queue (Queue 1) - 256 entries ======
TX_QSZ = 256
tx_descs = [None] * TX_QSZ

# --- Chain 0 (head=0): valid 2-desc TX chain ---
# desc 0: virtio-net header (readable)
guest_memory[0x10000:0x10000+12] = VNET_HDR
tx_descs[0] = (0x10000, 12, VIRTQ_DESC_F_NEXT, 1)

# desc 1: Ethernet frame (readable) - ARP broadcast
eth0 = bytearray(64)
eth0[0:6] = b'\xff\xff\xff\xff\xff\xff'        # dst MAC: broadcast
eth0[6:12] = b'\x52\x54\x00\x12\x34\x56'       # src MAC: device MAC
struct.pack_into('>H', eth0, 12, 0x0806)         # EtherType: ARP
struct.pack_into('>H', eth0, 14, 0x0001)          # HW type: Ethernet
struct.pack_into('>H', eth0, 16, 0x0800)          # Proto: IPv4
eth0[18] = 6; eth0[19] = 4                        # HW/proto addr len
struct.pack_into('>H', eth0, 20, 0x0001)           # Opcode: request
eth0[22:28] = b'\x52\x54\x00\x12\x34\x56'         # Sender HW addr
eth0[28:32] = bytes([10, 0, 2, 15])                # Sender IP
eth0[32:38] = b'\x00\x00\x00\x00\x00\x00'         # Target HW addr
eth0[38:42] = bytes([10, 0, 2, 1])                 # Target IP
guest_memory[0x10100:0x10100+64] = eth0
tx_descs[1] = (0x10100, 64, 0, 0)

# --- Chain 1 (head=3): CIRCULAR 3->7->12->7 ---
guest_memory[0x20000:0x20000+12] = VNET_HDR
guest_memory[0x20100:0x20100+128] = bytes(range(128))
guest_memory[0x20200:0x20200+64] = bytes(range(64))
tx_descs[3] = (0x20000, 12, VIRTQ_DESC_F_NEXT, 7)
tx_descs[7] = (0x20100, 128, VIRTQ_DESC_F_NEXT, 12)
tx_descs[12] = (0x20200, 64, VIRTQ_DESC_F_NEXT, 7)  # CIRCULAR back to 7

# --- Chain 2 (head=5): valid 2-desc chain ---
guest_memory[0x30000:0x30000+12] = VNET_HDR
eth2 = bytearray(42)
eth2[0:6] = b'\x52\x54\x00\xAB\xCD\xEF'    # dst MAC
eth2[6:12] = b'\x52\x54\x00\x12\x34\x56'    # src MAC (device)
struct.pack_into('>H', eth2, 12, 0x0800)      # IPv4
guest_memory[0x30100:0x30100+42] = eth2
tx_descs[5] = (0x30000, 12, VIRTQ_DESC_F_NEXT, 6)
tx_descs[6] = (0x30100, 42, 0, 0)

# --- Chain 3 (head=8): OUT-OF-BOUNDS next ---
guest_memory[0x40000:0x40000+12] = VNET_HDR
guest_memory[0x40100:0x40100+256] = bytes([0xAA] * 256)
tx_descs[8] = (0x40000, 12, VIRTQ_DESC_F_NEXT, 9)
tx_descs[9] = (0x40100, 256, VIRTQ_DESC_F_NEXT, 300)  # OOB: 300 > 256

# --- Chain 4 (head=10): valid 2-desc chain ---
guest_memory[0x50000:0x50000+12] = VNET_HDR
eth4 = bytearray(100)
eth4[0:6] = b'\x33\x33\x00\x00\x00\x01'      # IPv6 multicast
eth4[6:12] = b'\x52\x54\x00\x12\x34\x56'      # src MAC
struct.pack_into('>H', eth4, 12, 0x86DD)        # IPv6
guest_memory[0x50100:0x50100+100] = eth4
tx_descs[10] = (0x50000, 12, VIRTQ_DESC_F_NEXT, 11)
tx_descs[11] = (0x50100, 100, 0, 0)

tx_desc_table = build_desc_table(tx_descs, TX_QSZ)
tx_avail = build_avail_ring(0, 5, [0, 3, 5, 8, 10], TX_QSZ)
tx_used = build_used_ring(0, 1, [(0, 0)], TX_QSZ)  # Only chain 0 completed

# ====== RX Queue (Queue 0) - 256 entries ======
RX_QSZ = 256
rx_descs = [None] * RX_QSZ
rx_avail_entries = []

for i in range(128):
    addr = 0x80000 + i * 0x800
    rx_descs[i] = (addr, 1526, VIRTQ_DESC_F_WRITE, 0)
    rx_avail_entries.append(i)

# Received packet 0 at desc 0 (addr=0x80000)
guest_memory[0x80000:0x80000+12] = VNET_HDR
rx0 = bytearray(60)
rx0[0:6] = b'\x52\x54\x00\x12\x34\x56'   # dst: our MAC
rx0[6:12] = b'\x52\x54\x00\xAB\xCD\xEF'  # src
struct.pack_into('>H', rx0, 12, 0x0800)    # IPv4
rx0[14] = 0x45; rx0[15] = 0x00
struct.pack_into('>H', rx0, 16, 40)        # total len
struct.pack_into('>H', rx0, 18, 0x1234)   # identification
struct.pack_into('>H', rx0, 20, 0x4000)   # DF
rx0[22] = 64; rx0[23] = 6                  # TTL, TCP
rx0[26:30] = bytes([10, 0, 2, 1])          # src IP
rx0[30:34] = bytes([10, 0, 2, 15])         # dst IP
guest_memory[0x80000+12:0x80000+12+60] = rx0

# Received packet 1 at desc 1 (addr=0x80800)
guest_memory[0x80800:0x80800+12] = VNET_HDR
rx1 = bytearray(60)
rx1[0:6] = b'\x52\x54\x00\x12\x34\x56'
rx1[6:12] = b'\x52\x54\x00\xFE\xDC\xBA'
struct.pack_into('>H', rx1, 12, 0x0800)
rx1[14] = 0x45; rx1[22] = 64; rx1[23] = 17  # UDP
rx1[26:30] = bytes([10, 0, 2, 2])
rx1[30:34] = bytes([10, 0, 2, 15])
guest_memory[0x80800+12:0x80800+12+60] = rx1

# Received packet 2 at desc 2 (addr=0x81000)
guest_memory[0x81000:0x81000+12] = VNET_HDR
rx2 = bytearray(60)
rx2[0:6] = b'\xff\xff\xff\xff\xff\xff'     # broadcast
rx2[6:12] = b'\x52\x54\x00\x11\x22\x33'
struct.pack_into('>H', rx2, 12, 0x0806)    # ARP
struct.pack_into('>H', rx2, 14, 0x0001)    # HW type
struct.pack_into('>H', rx2, 16, 0x0800)
rx2[18] = 6; rx2[19] = 4
struct.pack_into('>H', rx2, 20, 0x0002)    # ARP reply
guest_memory[0x81000+12:0x81000+12+60] = rx2

rx_desc_table = build_desc_table(rx_descs, RX_QSZ)
rx_avail = build_avail_ring(0, 128, rx_avail_entries, RX_QSZ)
rx_used = build_used_ring(0, 3, [(0, 72), (1, 72), (2, 72)], RX_QSZ)

# ====== CTL Queue (Queue 2) - 64 entries ======
CTL_QSZ = 64
ctl_desc_table = build_desc_table([None]*CTL_QSZ, CTL_QSZ)
ctl_avail = build_avail_ring(0, 0, [], CTL_QSZ)
ctl_used = build_used_ring(0, 0, [], CTL_QSZ)

# ====== Features ======
device_features_0 = (1<<3)|(1<<5)|(1<<15)|(1<<16)|(1<<17)|(1<<18)  # 491560 = 0x78028
device_features_1 = 1  # VIRTIO_F_VERSION_1
driver_features_0 = device_features_0
driver_features_1 = device_features_1

features_data = struct.pack('<IIII',
    device_features_0, device_features_1,
    driver_features_0, driver_features_1
)

# ====== Common Config (56 bytes) ======
# Snapshot at crash time with queue_select=1 (TX queue)
queue_configs = [
    (256, 0, 1, 0, 0x060000, 0x061000, 0x061400),  # Q0 RX
    (256, 1, 1, 1, 0x070000, 0x071000, 0x071400),  # Q1 TX
    (64,  2, 1, 2, 0x080000, 0x080400, 0x080600),  # Q2 CTL
]

qc = queue_configs[1]
common_cfg = struct.pack('<IIIIHH',
    0, device_features_0,   # feature_select=0, device_feature word0
    0, driver_features_0,   # feature_select=0, driver_feature word0
    0xFFFF,                 # msix_config (NO_VECTOR)
    3,                      # num_queues
)
common_cfg += struct.pack('<BBH', 0x4F, 0, 1)  # status=0x4F, config_gen=0, queue_select=1
common_cfg += struct.pack('<HHHH', qc[0], qc[1], qc[2], qc[3])
common_cfg += struct.pack('<QQQ', qc[4], qc[5], qc[6])

# ====== Per-Queue Config ======
queue_cfg_data = bytearray()
for qc in queue_configs:
    queue_cfg_data += struct.pack('<HHHHQQQ', *qc)

# ====== Device Config (12 bytes) ======
mac = b'\x52\x54\x00\x12\x34\x56'
device_config = mac + struct.pack('<HHH', 1, 1, 1500)  # link_up, max_pairs=1, mtu=1500

# ====== Event Log ======
# Each entry: timestamp_ns(u64), event_type(u8), event_data(7 bytes)
events = [
    (100000,   0, bytes([0x01, 0,0,0,0,0,0])),  # ACKNOWLEDGE
    (200000,   0, bytes([0x03, 0,0,0,0,0,0])),  # DRIVER
    (500000,   0, bytes([0x0B, 0,0,0,0,0,0])),  # FEATURES_OK
    (600000,   0, bytes([0x0F, 0,0,0,0,0,0])),  # DRIVER_OK
    (1000000,  1, bytes([0x01, 0,0,0,0,0,0])),  # queue_notify queue=1
    (1050000,  2, bytes([0x01, 0,0,0,0,0,0])),  # interrupt vector=1 (TX done)
    (1100000,  2, bytes([0x00, 0,0,0,0,0,0])),  # interrupt vector=0 (RX)
    (1200000,  1, bytes([0x01, 0,0,0,0,0,0])),  # queue_notify queue=1
    (1500000,  3, bytes([0x01, 0x01,0,0,0,0,0])),  # error code=1(chain), queue=1
    (1500100,  0, bytes([0x4F, 0,0,0,0,0,0])),  # DEVICE_NEEDS_RESET
]

event_log = bytearray()
for ts, etype, edata in events:
    event_log += struct.pack('<QB', ts, etype) + edata

# ====== MSI-X Table ======
# Entry: addr_lo(u32), addr_hi(u32), msg_data(u32), vector_control(u32)
msix_entries = [
    (0xFEE00000, 0, 0x4041, 0x00000000),  # Vec 0: RX - valid
    (0xFEE00000, 0, 0x4042, 0x00000000),  # Vec 1: TX - valid
    (0x00000000, 0, 0x0000, 0x00000001),  # Vec 2: CTL - MASKED, zero addr
    (0xFEE00000, 0, 0x4043, 0x00000000),  # Vec 3: config - valid
]

msix_table = bytearray()
for entry in msix_entries:
    msix_table += struct.pack('<IIII', *entry)

# ====== Write Files ======
for d in ['queues/0', 'queues/1', 'queues/2']:
    os.makedirs(f'/app/dumps/{d}', exist_ok=True)

files = {
    'common_cfg.bin': common_cfg,
    'queue_configs.bin': bytes(queue_cfg_data),
    'features.bin': features_data,
    'device_config.bin': device_config,
    'event_log.bin': bytes(event_log),
    'msix_table.bin': bytes(msix_table),
    'guest_memory.bin': bytes(guest_memory),
    'queues/0/desc.bin': rx_desc_table,
    'queues/0/avail.bin': rx_avail,
    'queues/0/used.bin': rx_used,
    'queues/1/desc.bin': tx_desc_table,
    'queues/1/avail.bin': tx_avail,
    'queues/1/used.bin': tx_used,
    'queues/2/desc.bin': ctl_desc_table,
    'queues/2/avail.bin': ctl_avail,
    'queues/2/used.bin': ctl_used,
}

for name, data in files.items():
    path = f'/app/dumps/{name}'
    with open(path, 'wb') as f:
        f.write(data)

print(f"Generated {len(files)} dump files in /app/dumps/")
