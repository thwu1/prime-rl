#!/usr/bin/env python3
"""Generate BLE Link Layer BLLC captures and HCI btsnoop log for forensics task."""
import struct
import os

# === BLLC format constants ===
MAGIC = b'BLLC'
VERSION = 1
C, P = 0x00, 0x01  # Central-to-Peripheral, Peripheral-to-Central

# LL Control opcodes
OP_TERMINATE_IND = 0x02
OP_ENC_REQ = 0x03
OP_ENC_RSP = 0x04
OP_START_ENC_REQ = 0x05
OP_START_ENC_RSP = 0x06
OP_FEATURE_REQ = 0x08
OP_FEATURE_RSP = 0x09
OP_PAUSE_ENC_REQ = 0x0A
OP_PAUSE_ENC_RSP = 0x0B
OP_VERSION_IND = 0x0C


def ctrl(opcode, data=b''):
    payload = bytes([opcode]) + data
    return bytes([0x03, len(payload)]) + payload


def data_pdu(data):
    llid = 0x02 if data else 0x01
    return bytes([llid, len(data)]) + data


def feat_req():
    return ctrl(OP_FEATURE_REQ, b'\xff\xff\x0f\x00\x00\x00\x00\x00')


def feat_rsp():
    return ctrl(OP_FEATURE_RSP, b'\xff\xff\x07\x00\x00\x00\x00\x00')


def ver_ind(v=0x0C, c=0x0059, s=0x0001):
    return ctrl(OP_VERSION_IND, struct.pack('<BHH', v, c, s))


def enc_req(rand, ediv, skdm, ivm):
    data = rand + struct.pack('<H', ediv) + skdm + ivm
    return ctrl(OP_ENC_REQ, data)


def enc_rsp(skds, ivs):
    return ctrl(OP_ENC_RSP, skds + ivs)


def start_enc_req():
    return ctrl(OP_START_ENC_REQ)


def start_enc_rsp():
    return ctrl(OP_START_ENC_RSP)


def terminate_ind(err=0x13):
    return ctrl(OP_TERMINATE_IND, bytes([err]))


def pause_enc_req():
    return ctrl(OP_PAUSE_ENC_REQ)


def pause_enc_rsp():
    return ctrl(OP_PAUSE_ENC_RSP)


def write_trace(path, packets):
    with open(path, 'wb') as f:
        f.write(MAGIC)
        f.write(struct.pack('<H', VERSION))
        f.write(struct.pack('<I', len(packets)))
        for ts, d, pdu in packets:
            f.write(struct.pack('<Q', ts))
            f.write(struct.pack('B', d))
            f.write(struct.pack('<H', len(pdu)))
            f.write(pdu)


# === Encryption parameters per trace ===

# Trace 01: Clean encryption (maps to HCI handle 0x0040)
T01_RAND = bytes.fromhex('ABCDEF0123456789')
T01_EDIV = 0x2211
T01_SKDM = bytes.fromhex('DEADBEEFCAFEBABE')
T01_IVM  = bytes.fromhex('01020304')
T01_SKDS = bytes.fromhex('FEDCBA9876543210')
T01_IVS  = bytes.fromhex('0A0B0C0D')

# Trace 02: Out-of-order (different params from T01)
T02_RAND = bytes.fromhex('2222222222222222')
T02_EDIV = 0x8899
T02_SKDM = bytes.fromhex('EEEEEEEEEEEEEEEE')
T02_IVM  = bytes.fromhex('DDDDDDDD')
T02_SKDS = bytes.fromhex('CCCCCCCCCCCCCCCC')
T02_IVS  = bytes.fromhex('BBBBBBBB')

# Trace 03: Encryption timeout (different params)
T03_RAND = bytes.fromhex('3333333333333333')
T03_EDIV = 0xAABB
T03_SKDM = bytes.fromhex('AAAA111122223333')
T03_IVM  = bytes.fromhex('AABBCCDD')
T03_SKDS = bytes.fromhex('4444555566667777')
T03_IVS  = bytes.fromhex('EEFF0011')

# Trace 04: Multi-violation (different params for valid enc_req)
T04_RAND = bytes.fromhex('FEDCBA9876543210')
T04_EDIV = 0x4455
T04_SKDM = bytes.fromhex('AABBCCDDEEFF0011')
T04_IVM  = bytes.fromhex('11223344')
T04_SKDS = bytes.fromhex('5566778899AABBCC')
T04_IVS  = bytes.fromhex('DDEEFF00')

# Trace 05: Clean encryption with SAME SKDm/SKDs as T01 (SKD reuse!)
# Different Rand/EDIV (maps to HCI handle 0x0041)
T05_RAND = bytes.fromhex('9876543210FEDCBA')
T05_EDIV = 0x3344
T05_SKDM = bytes.fromhex('DEADBEEFCAFEBABE')  # Same as T01!
T05_IVM  = bytes.fromhex('05060708')
T05_SKDS = bytes.fromhex('FEDCBA9876543210')  # Same as T01!
T05_IVS  = bytes.fromhex('09101112')

# Known LTK for all connections
LTK = bytes.fromhex('4C68384139F574D836BCF34E9DFB01BF')


# === Create directories ===
os.makedirs('/app/captures/ll', exist_ok=True)
os.makedirs('/app/captures/hci', exist_ok=True)
os.makedirs('/app/results', exist_ok=True)


# === Write BLLC traces ===

# Trace 01: Clean connection with successful encryption — no violations
write_trace('/app/captures/ll/trace_01.bllc', [
    (1000000,  C, feat_req()),
    (1002500,  P, feat_rsp()),
    (1005000,  C, ver_ind()),
    (1007500,  P, ver_ind(0x0C, 0x0059, 0x0002)),
    (2000000,  C, enc_req(T01_RAND, T01_EDIV, T01_SKDM, T01_IVM)),
    (2002500,  P, enc_rsp(T01_SKDS, T01_IVS)),
    (2005000,  P, start_enc_req()),
    (2007500,  C, start_enc_rsp()),
    (2010000,  P, start_enc_rsp()),
    (3000000,  C, data_pdu(b'\x07\x00\x04\x00\x10\x01\x00\xff\xff\x00\x28')),
    (3002500,  P, data_pdu(b'\x07\x00\x04\x00\x11\x05\x01\x04\x00\x00\x18')),
])

# Trace 02: LL_START_ENC_REQ arrives before LL_ENC_RSP (out of order)
write_trace('/app/captures/ll/trace_02.bllc', [
    (1000000,  C, feat_req()),
    (1002500,  P, feat_rsp()),
    (2000000,  C, enc_req(T02_RAND, T02_EDIV, T02_SKDM, T02_IVM)),
    (2002500,  P, start_enc_req()),   # Wrong! Should be enc_rsp first
    (2005000,  P, enc_rsp(T02_SKDS, T02_IVS)),
])

# Trace 03: Encryption procedure exceeds 40-second timeout
write_trace('/app/captures/ll/trace_03.bllc', [
    (1000000,  C, feat_req()),
    (1002500,  P, feat_rsp()),
    (2000000,  C, enc_req(T03_RAND, T03_EDIV, T03_SKDM, T03_IVM)),
    (2100000,  P, enc_rsp(T03_SKDS, T03_IVS)),
    (43100000, P, start_enc_req()),    # ~41 seconds after enc_req
    (43200000, C, start_enc_rsp()),
    (43300000, P, start_enc_rsp()),    # Timeout detected here
])

# Trace 04: Multiple violations
write_trace('/app/captures/ll/trace_04.bllc', [
    (1000000,  C, feat_req()),                                                  # 0
    (1002500,  P, feat_rsp()),                                                  # 1
    (2000000,  P, enc_req(T01_RAND, T01_EDIV, T01_SKDM, T01_IVM)),            # 2 WRONG_INITIATOR (peripheral sends enc_req)
    (3000000,  C, enc_req(T04_RAND, T04_EDIV, T04_SKDM, T04_IVM)),            # 3 Valid central enc_req
    (3002500,  P, enc_rsp(T04_SKDS, T04_IVS)),                                 # 4
    (3005000,  P, start_enc_req()),                                             # 5
    (3007500,  C, start_enc_rsp()),                                             # 6
    (3010000,  P, start_enc_rsp()),                                             # 7 Encryption established
    (3012500,  P, start_enc_rsp()),                                             # 8 DUPLICATE_PDU
    (5000000,  C, pause_enc_req()),                                             # 9
    (5002500,  P, pause_enc_rsp()),                                             # 10
    (5005000,  C, pause_enc_rsp()),                                             # 11 Pause complete
    (5007500,  C, enc_req(T04_RAND, T04_EDIV, T04_SKDM, T04_IVM)),            # 12 Restart enc_req
    (5010000,  C, terminate_ind()),                                             # 13 TERMINATION_DURING_ENCRYPTION
])

# Trace 05: Clean encryption with SKD reuse from trace_01
write_trace('/app/captures/ll/trace_05.bllc', [
    (1000000,  C, feat_req()),
    (1002500,  P, feat_rsp()),
    (1005000,  C, ver_ind()),
    (1007500,  P, ver_ind(0x0C, 0x0059, 0x0002)),
    (2000000,  C, enc_req(T05_RAND, T05_EDIV, T05_SKDM, T05_IVM)),
    (2002500,  P, enc_rsp(T05_SKDS, T05_IVS)),
    (2005000,  P, start_enc_req()),
    (2007500,  C, start_enc_rsp()),
    (2010000,  P, start_enc_rsp()),
    (3000000,  C, data_pdu(b'\x07\x00\x04\x00\x10\x01\x00\xff\xff\x00\x28')),
    (3002500,  P, data_pdu(b'\x07\x00\x04\x00\x11\x05\x01\x04\x00\x00\x18')),
])


# === Write btsnoop HCI log ===

def write_btsnoop(path, records):
    """Write a btsnoop file with HCI UART H4 (datalink type 1002) packets.

    Each record is (timestamp_us, flags, packet_bytes) where:
      - timestamp_us: int64, microseconds since midnight Jan 1, 0 AD (Gregorian)
      - flags: uint32, bit 0 = direction (0=sent, 1=received),
               bit 1 = type (0=data, 1=command/event)
      - packet_bytes: raw HCI UART H4 packet (starts with H4 type indicator)
    """
    with open(path, 'wb') as f:
        # File header (16 bytes)
        f.write(b'btsnoop\x00')            # 8 bytes: identification pattern
        f.write(struct.pack('>I', 1))       # 4 bytes: version (big-endian)
        f.write(struct.pack('>I', 1002))    # 4 bytes: datalink type = HCI UART H4

        for ts_us, flags, pkt_data in records:
            orig_len = len(pkt_data)
            incl_len = len(pkt_data)
            f.write(struct.pack('>I', orig_len))
            f.write(struct.pack('>I', incl_len))
            f.write(struct.pack('>I', flags))
            f.write(struct.pack('>I', 0))           # cumulative drops
            f.write(struct.pack('>q', ts_us))        # timestamp (signed 64-bit BE)
            f.write(pkt_data)


# HCI packet constructors

def hci_le_connection_complete(handle, role=0, peer_addr=b'\x11\x22\x33\x44\x55\x66'):
    """LE Meta Event: LE Connection Complete (subevent 0x01)."""
    # Subevent(1) + Status(1) + Handle(2) + Role(1) + AddrType(1) + Addr(6)
    # + ConnInterval(2) + ConnLatency(2) + SupervTimeout(2) + Accuracy(1) = 19
    params = bytes([0x01, 0x00]) + struct.pack('<H', handle) + bytes([role, 0x00]) + \
             peer_addr + struct.pack('<HHH', 24, 0, 200) + bytes([0x00])
    return bytes([0x04, 0x3E, len(params)]) + params


def hci_le_ltk_request_event(handle, rand, ediv):
    """LE Meta Event: LE Long Term Key Request (subevent 0x05)."""
    # Subevent(1) + Handle(2) + Rand(8) + EDIV(2) = 13
    params = bytes([0x05]) + struct.pack('<H', handle) + rand + struct.pack('<H', ediv)
    return bytes([0x04, 0x3E, len(params)]) + params


def hci_le_ltk_reply_command(handle, ltk):
    """HCI Command: LE LTK Request Reply (opcode 0x201A)."""
    # Handle(2) + LTK(16) = 18
    params = struct.pack('<H', handle) + ltk
    return bytes([0x01, 0x1A, 0x20, len(params)]) + params


def hci_encryption_change_event(handle, enabled, status=0):
    """HCI Event: Encryption Change (event code 0x08)."""
    # Status(1) + Handle(2) + Enabled(1) = 4
    params = bytes([status]) + struct.pack('<H', handle) + bytes([enabled])
    return bytes([0x04, 0x08, len(params)]) + params


def hci_read_enc_key_size_cmd(handle):
    """HCI Command: Read Encryption Key Size (opcode 0x1408)."""
    params = struct.pack('<H', handle)
    return bytes([0x01, 0x08, 0x14, len(params)]) + params


def hci_cmd_complete_enc_key_size(handle, key_size, status=0):
    """HCI Event: Command Complete for Read Encryption Key Size (opcode 0x1408)."""
    # NumPackets(1) + Opcode(2) + Status(1) + Handle(2) + KeySize(1) = 7
    params = bytes([0x01, 0x08, 0x14, status]) + struct.pack('<H', handle) + bytes([key_size])
    return bytes([0x04, 0x0E, len(params)]) + params


# btsnoop flags for HCI UART H4:
#   bit 0: direction (0 = host->controller / sent, 1 = controller->host / received)
#   bit 1: type (0 = ACL data, 1 = command/event)
FLAGS_RECV_EVT = 0x03   # received + event
FLAGS_SEND_CMD = 0x02   # sent + command

# Base timestamp: microseconds since midnight Jan 1, 0 AD
# ~Jan 15, 2024: (2024 years * 365.25 * 86400 + 15 * 86400) * 1e6
BASE_HCI_TS = 63873576000000000

hci_records = [
    # === Connection 1: handle 0x0040 (maps to trace_01 via Rand+EDIV) ===
    # Connection established
    (BASE_HCI_TS + 1_000_000, FLAGS_RECV_EVT,
     hci_le_connection_complete(0x0040, role=0, peer_addr=b'\xAA\xBB\xCC\xDD\xEE\x01')),

    # Controller requests LTK from host (contains Rand + EDIV from LL_ENC_REQ)
    (BASE_HCI_TS + 2_000_000, FLAGS_RECV_EVT,
     hci_le_ltk_request_event(0x0040, T01_RAND, T01_EDIV)),

    # Host replies with the LTK
    (BASE_HCI_TS + 2_000_500, FLAGS_SEND_CMD,
     hci_le_ltk_reply_command(0x0040, LTK)),

    # Encryption activated
    (BASE_HCI_TS + 2_010_000, FLAGS_RECV_EVT,
     hci_encryption_change_event(0x0040, 1)),

    # Host queries key size
    (BASE_HCI_TS + 2_015_000, FLAGS_SEND_CMD,
     hci_read_enc_key_size_cmd(0x0040)),

    # Controller reports key size = 7 (KNOB vulnerability!)
    (BASE_HCI_TS + 2_015_500, FLAGS_RECV_EVT,
     hci_cmd_complete_enc_key_size(0x0040, 7)),

    # === Connection 2: handle 0x0041 (maps to trace_05 via Rand+EDIV) ===
    (BASE_HCI_TS + 5_000_000, FLAGS_RECV_EVT,
     hci_le_connection_complete(0x0041, role=0, peer_addr=b'\xAA\xBB\xCC\xDD\xEE\x02')),

    (BASE_HCI_TS + 5_500_000, FLAGS_RECV_EVT,
     hci_le_ltk_request_event(0x0041, T05_RAND, T05_EDIV)),

    (BASE_HCI_TS + 5_500_500, FLAGS_SEND_CMD,
     hci_le_ltk_reply_command(0x0041, LTK)),

    (BASE_HCI_TS + 5_510_000, FLAGS_RECV_EVT,
     hci_encryption_change_event(0x0041, 1)),

    (BASE_HCI_TS + 5_515_000, FLAGS_SEND_CMD,
     hci_read_enc_key_size_cmd(0x0041)),

    # Key size = 16 (normal, no vulnerability)
    (BASE_HCI_TS + 5_515_500, FLAGS_RECV_EVT,
     hci_cmd_complete_enc_key_size(0x0041, 16)),
]

write_btsnoop('/app/captures/hci/central.btsnoop', hci_records)


# === Write LTK file ===
with open('/app/ltk.hex', 'w') as f:
    f.write(LTK.hex() + '\n')


print("Generated 5 BLLC traces, 1 btsnoop HCI log, and LTK file.")
