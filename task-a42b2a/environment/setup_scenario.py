#!/usr/bin/env python3
"""Generate PTP Power Profile conformance test scenario with pcap captures.
"""
import json
import struct
import os


def mac_from_clock_id(clock_id_hex):
    """Derive 6-byte MAC from 8-byte EUI-64 clock identity (remove FFFE)."""
    raw = bytes.fromhex(clock_id_hex)
    return raw[:3] + raw[5:8]


def pcap_global_header():
    """Return 24-byte pcap global header (little-endian, LINKTYPE_ETHERNET)."""
    return struct.pack('<IHHiIII', 0xa1b2c3d4, 2, 4, 0, 0, 65535, 1)


def pcap_packet_record(ts_float, frame_data):
    """Return pcap packet record bytes for a single frame."""
    ts_sec = int(ts_float)
    ts_usec = int((ts_float - ts_sec) * 1e6)
    hdr = struct.pack('<IIII', ts_sec, ts_usec, len(frame_data), len(frame_data))
    return hdr + frame_data


def eth_ptp_frame(src_mac, ptp_payload, vlan_id=None):
    """Build PTP-over-Ethernet frame with optional 802.1Q VLAN tag."""
    dst = bytes([0x01, 0x1b, 0x19, 0x00, 0x00, 0x00])
    if vlan_id is not None:
        return (dst + src_mac +
                struct.pack('!HHH', 0x8100, vlan_id & 0x0FFF, 0x88F7) +
                ptp_payload)
    return dst + src_mac + struct.pack('!H', 0x88F7) + ptp_payload


def arp_frame(src_mac):
    """Build a broadcast ARP request frame (noise traffic)."""
    dst = bytes([0xff] * 6)
    arp = struct.pack('!HHBBH', 1, 0x0800, 6, 4, 1)
    arp += src_mac + bytes([192, 168, 1, 10])
    arp += bytes(6) + bytes([192, 168, 1, 1])
    frame = dst + src_mac + struct.pack('!H', 0x0806) + arp
    if len(frame) < 60:
        frame += bytes(60 - len(frame))
    return frame


def lldp_frame(src_mac):
    """Build a minimal LLDP frame (noise traffic)."""
    dst = bytes([0x01, 0x80, 0xc2, 0x00, 0x00, 0x0e])
    chassis = struct.pack('!H', 0x0207) + bytes([4]) + src_mac
    port = struct.pack('!H', 0x0407) + bytes([3]) + src_mac
    ttl = struct.pack('!H', 0x0602) + struct.pack('!H', 120)
    end = struct.pack('!H', 0)
    return dst + src_mac + struct.pack('!H', 0x88CC) + chassis + port + ttl + end


def build_announce(
    clock_identity_hex, port_number, seq_id,
    domain_number=0, log_message_interval=0, two_step=True,
    alternate_master=False, current_utc_offset=37,
    utc_offset_valid=True, ptp_timescale=True,
    time_traceable=True, freq_traceable=True,
    gm_priority1=128, clock_class=248, clock_accuracy=0xFE,
    offset_scaled_log_var=0xFFFF, gm_priority2=128,
    gm_identity_hex=None, steps_removed=0, time_source=0xA0,
    tlv_gm_time_inaccuracy=0xFFFFFFFF, tlv_net_time_inaccuracy=0,
):
    """Build 86-byte IEEE 1588 Announce message with C37.238 TLV."""
    if gm_identity_hex is None:
        gm_identity_hex = clock_identity_hex
    msg = bytearray(86)
    msg[0] = 0x0B
    msg[1] = 0x02
    struct.pack_into('!H', msg, 2, 86)
    msg[4] = domain_number & 0xFF
    f0 = 0
    if alternate_master:
        f0 |= 0x01
    if two_step:
        f0 |= 0x02
    f1 = 0
    if utc_offset_valid:
        f1 |= 0x04
    if ptp_timescale:
        f1 |= 0x08
    if time_traceable:
        f1 |= 0x10
    if freq_traceable:
        f1 |= 0x20
    msg[6] = f0
    msg[7] = f1
    msg[20:28] = bytes.fromhex(clock_identity_hex)
    struct.pack_into('!H', msg, 28, port_number)
    struct.pack_into('!H', msg, 30, seq_id)
    msg[32] = 0x05
    struct.pack_into('!b', msg, 33, log_message_interval)
    struct.pack_into('!H', msg, 44, current_utc_offset)
    msg[47] = gm_priority1
    msg[48] = clock_class
    msg[49] = clock_accuracy
    struct.pack_into('!H', msg, 50, offset_scaled_log_var)
    msg[52] = gm_priority2
    msg[53:61] = bytes.fromhex(gm_identity_hex)
    struct.pack_into('!H', msg, 61, steps_removed)
    msg[63] = time_source
    struct.pack_into('!H', msg, 64, 0x0003)
    struct.pack_into('!H', msg, 66, 0x0012)
    msg[68:71] = bytes.fromhex('1c129d')
    msg[71:74] = bytes.fromhex('000001')
    struct.pack_into('!H', msg, 74, 0x0003)
    struct.pack_into('!I', msg, 76, tlv_gm_time_inaccuracy)
    struct.pack_into('!I', msg, 80, tlv_net_time_inaccuracy)
    return bytes(msg)


REFERENCE_DOCS = {
    "announce_fields.txt": """\
NISTIR 8002 - Appendix C, Table 5: Announce Message Fields
(IEEE 1588 Power Profile Conformance Test Plan)

Field                        Octets  Offset  Influences BMCA
------------------------------------------------------------
header                        34       0      -
originTimestamp                10      34      -
currentUtcOffset                2      44      -
reserved                        1      46      -
grandmasterPriority1            1      47      yes
grandmasterClockQuality         4      48      yes
grandmasterPriority2            1      52      yes
grandmasterIdentity             8      53      yes
stepsRemoved                    2      61      yes
timeSource                      1      63      -

Common PTP Header (34 bytes):
  Offset 0:    transportSpecific (upper nibble) | messageType (lower nibble)
  Offset 1:    reserved (upper nibble) | versionPTP (lower nibble)
  Offset 2-3:  messageLength (UInteger16)
  Offset 4:    domainNumber (UInteger8)
  Offset 5:    reserved
  Offset 6-7:  flagField (2 octets)
  Offset 8-15: correctionField (Integer64)
  Offset 16-19: reserved (4 octets)
  Offset 20-29: sourcePortIdentity (clockIdentity[8] + portNumber[2])
  Offset 30-31: sequenceId (UInteger16)
  Offset 32:   controlField (UInteger8)
  Offset 33:   logMessageInterval (Integer8, signed)

flagField octet at offset 6:
  bit 0: alternateMasterFlag
  bit 1: twoStepFlag

grandmasterClockQuality (4 bytes at offset 48):
  Byte 0: clockClass (UInteger8)
  Byte 1: clockAccuracy (Enumeration8)
  Bytes 2-3: offsetScaledLogVariance (UInteger16)

All multi-byte integer fields use network byte order (big-endian).
Announce messageType nibble = 0x0B.
Base Announce message: 64 bytes.
""",
    "c37238_tlv_fields.txt": """\
NISTIR 8002 - Appendix C, Table 12: IEEE C37.238 TLV Organization Extension
(Appended to Announce messages at byte 64)

Field                       Octets  TLV-Offset  Value
------------------------------------------------------
tlvType                       2        0        0x0003
lengthField                   2        2        0x0012
organizationId                3        4        0x1C129D
organizationSubType           3        7        0x000001
grandmasterId                 2       10        varies
grandmasterTimeInaccuracy     4       12        nanoseconds
networkTimeInaccuracy         4       16        nanoseconds
reserved                      2       20        0x0000

TLV-Offset values are relative to byte 64 of the overall message.
Total TLV: 22 bytes. Total Announce + TLV: 86 bytes.
""",
    "power_profile_attrs.txt": """\
IEEE C37.238-2011 Power Profile - Required PTP Attribute Values
(NISTIR 8002, Group 1 Overview)

Attribute                          Required Value
-------------------------------------------------
portDS.logAnnounceInterval         0
portDS.logSyncInterval             0
portDS.announceReceiptTimeout      2 (preferred GM), 3 (other GMC)
portDS.logMinPdelayReqInterval     0
portDS.delayMechanism              Peer-to-peer (P2P)
defaultDS.priority1                128 (GM-capable), 255 (slave-only)
defaultDS.priority2                128 (GM-capable), 255 (slave-only)
defaultDS.slaveOnly                FALSE (GM-capable), TRUE (slave-only)
defaultDS.domainNumber             0 (default initialization)
Transport mechanism                Layer 2 (Ethernet, IEEE 802.3)

Device types: OC (Ordinary Clock), BC (Boundary Clock),
TC (Transparent Clock), GMC (Grandmaster Capable),
SO (Slave Only - cannot become grandmaster).

Applicability of attribute checks:
  logAnnounceInterval: GMC ordinary and boundary clocks
  priority1/priority2: GMC ordinary and boundary clocks
  domainNumber: all PTP clocks
""",
    "timing_methodology.txt": """\
NISTIR 8002 - Appendix D: Timing Calculations
(Tests PWR.c.1.1, PWR.c.1.2, PWR.c.1.4)

For n message intervals I_1, I_2, ..., I_n:

  mean = (I_1 + I_2 + ... + I_n) / n

  variance = ((I_1 - mean)^2 + ... + (I_n - mean)^2) / n

  s = sqrt(variance)

90% confidence interval for the true mean:
  mean - 1.645 * s / sqrt(n)  <  mu  <  mean + 1.645 * s / sqrt(n)

For logAnnounceInterval = 0: expected interval = 2^0 = 1 second.
Allowed range per IEEE 1588-2008: +/-30% of nominal, i.e. [0.7, 1.3] s.
The 90% CI must fall entirely within the allowed range for PASS.
""",
    "bmca_test_scope.txt": """\
NISTIR 8002 - Group 3: Best Master Clock Algorithm Tests

Test PWR.c.3.1   Disqualified Announce Messages, by clockIdentity
Test PWR.c.3.2   Disqualified Announce Messages, by Most Recent
Test PWR.c.3.3   Disqualified Announce Messages, by Foreign Master Window
Test PWR.c.3.4   Disqualified Announce Messages, by stepsRemoved
Test PWR.c.3.5   Disqualified Announce Messages, by alternateMasterFlag
Test PWR.c.3.6   Data Set Comparison on a Single Port
Test PWR.c.3.7   Data Set Comparison on Multiple Ports
Test PWR.c.3.8   State Decision Algorithm
Test PWR.c.3.9   Steps Removed
Test PWR.c.3.10  Source Port Identity
Test PWR.c.3.11  Default Slave-only

IEEE 1588-2008 Section 9.3.2.5 defines conditions under which a received
Announce message is disqualified from BMCA consideration.

IEEE 1588-2008 Section 9.3.2.4.5 defines the foreign master time window
for qualifying Announce message sources.

IEEE 1588-2008 Section 9.3.4 defines the data set comparison algorithm
used to compare grandmaster clock quality.

IEEE 1588-2008 Section 9.3.3 defines the state decision algorithm that
maps comparison results to port states.
""",
    "ptp4l_config_mapping.txt": """\
linuxptp (ptp4l) Configuration Parameter Mapping for IEEE C37.238

ptp4l parameter             IEEE 1588 / C37.238 attribute
---------------------------------------------------------
priority1                   defaultDS.priority1
priority2                   defaultDS.priority2
domainNumber                defaultDS.domainNumber
logAnnounceInterval         portDS.logAnnounceInterval
logSyncInterval             portDS.logSyncInterval
logMinPdelayReqInterval     portDS.logMinPdelayReqInterval
announceReceiptTimeout      portDS.announceReceiptTimeout
delay_mechanism             portDS.delayMechanism (P2P or E2E)
network_transport           Transport layer (L2, UDPv4, or UDPv6)

Configuration file format: INI-style with [global] and per-port sections.
Parameters are whitespace-delimited key-value pairs within sections.

IEEE C37.238 Power Profile requires:
  delay_mechanism   = P2P  (peer-to-peer delay measurement)
  network_transport = L2   (Layer 2 / raw Ethernet / IEEE 802.3)
""",
}


def write_reference_docs():
    """Write NISTIR 8002 reference excerpts to /app/reference/."""
    os.makedirs('/app/reference', exist_ok=True)
    for filename, content in REFERENCE_DOCS.items():
        with open(f'/app/reference/{filename}', 'w') as f:
            f.write(content)


def main():
    os.makedirs('/app/scenario', exist_ok=True)
    os.makedirs('/app/configs', exist_ok=True)

    clocks = {
        "GM_A": {
            "clock_identity": "001122fffe334455",
            "device_type": "OC",
            "gm_capable": True,
            "preferred_gm": True,
            "slave_only": False,
            "num_ports": 1,
            "clock_class": 6,
            "clock_accuracy": 33,
            "offset_scaled_log_var": 20061,
            "priority1": 128,
            "priority2": 128,
            "time_source": 64,
        },
        "GM_B": {
            "clock_identity": "aabb00fffe112233",
            "device_type": "OC",
            "gm_capable": True,
            "preferred_gm": False,
            "slave_only": False,
            "num_ports": 1,
            "clock_class": 7,
            "clock_accuracy": 34,
            "offset_scaled_log_var": 20077,
            "priority1": 128,
            "priority2": 128,
            "time_source": 64,
        },
        "BC_C": {
            "clock_identity": "ccdd00fffe445566",
            "device_type": "BC",
            "gm_capable": True,
            "preferred_gm": False,
            "slave_only": False,
            "num_ports": 2,
            "clock_class": 248,
            "clock_accuracy": 254,
            "offset_scaled_log_var": 65535,
            "priority1": 128,
            "priority2": 128,
            "time_source": 160,
        },
        "OC_D": {
            "clock_identity": "eeff00fffe778899",
            "device_type": "OC",
            "gm_capable": False,
            "preferred_gm": False,
            "slave_only": True,
            "num_ports": 1,
            "clock_class": 255,
            "clock_accuracy": 254,
            "offset_scaled_log_var": 65535,
            "priority1": 255,
            "priority2": 255,
            "time_source": 160,
        },
    }

    topology = {
        "segments": {
            "segment_1": ["GM_A:1", "GM_B:1", "BC_C:1"],
            "segment_2": ["BC_C:2", "OC_D:1"],
        },
        "clocks": clocks,
    }

    # Each event: (timestamp, frame_bytes, [capture_log_entries])
    # capture_log_entries is empty list for noise frames
    seg1_events = []
    seg2_events = []

    mac_gm_a = mac_from_clock_id("001122fffe334455")
    mac_gm_b = mac_from_clock_id("aabb00fffe112233")
    mac_bc_c = mac_from_clock_id("ccdd00fffe445566")
    mac_oc_d = mac_from_clock_id("eeff00fffe778899")
    mac_rogue1 = mac_from_clock_id("deadbefffe000001")
    mac_rogue2 = mac_from_clock_id("deadbefffe000002")

    # --- GM_A Announce messages (conformant, logAnnounceInterval=0) ---
    gm_a_kwargs = dict(
        clock_identity_hex="001122fffe334455", port_number=1,
        clock_class=6, clock_accuracy=0x21,
        offset_scaled_log_var=0x4E5D,
        gm_priority1=128, gm_priority2=128,
        time_source=0x40, tlv_gm_time_inaccuracy=100,
        log_message_interval=0,
    )
    gm_a_timestamps = [
        1700000001.000, 1700000002.012, 1700000003.005, 1700000003.993,
        1700000005.008, 1700000005.997, 1700000007.015, 1700000008.003,
        1700000008.988, 1700000010.001,
    ]
    for i, ts in enumerate(gm_a_timestamps):
        ptp = build_announce(seq_id=i + 1, **gm_a_kwargs)
        frame = eth_ptp_frame(mac_gm_a, ptp, vlan_id=100)
        entries = [
            {"id": f"gm_a_ann_{i+1}", "source_clock": "GM_A",
             "receive_timestamp": ts,
             "received_at_clock": "BC_C", "received_at_port": 1},
            {"id": f"gm_a_to_gmb_{i+1}", "source_clock": "GM_A",
             "receive_timestamp": ts + 0.0001,
             "received_at_clock": "GM_B", "received_at_port": 1},
        ]
        seg1_events.append((ts, frame, entries))

    # --- GM_B Announce messages (NON-CONFORMANT: logAnnounceInterval=1) ---
    gm_b_kwargs = dict(
        clock_identity_hex="aabb00fffe112233", port_number=1,
        clock_class=7, clock_accuracy=0x22,
        offset_scaled_log_var=0x4E6D,
        gm_priority1=128, gm_priority2=128,
        time_source=0x40, tlv_gm_time_inaccuracy=250,
        log_message_interval=1,
    )
    gm_b_timestamps = [
        1700000002.000, 1700000004.020, 1700000005.990, 1700000008.015,
        1700000009.985, 1700000012.010, 1700000013.995, 1700000016.005,
    ]
    for i, ts in enumerate(gm_b_timestamps):
        ptp = build_announce(seq_id=i + 1, **gm_b_kwargs)
        frame = eth_ptp_frame(mac_gm_b, ptp, vlan_id=100)
        entries = [
            {"id": f"gm_b_ann_{i+1}", "source_clock": "GM_B",
             "receive_timestamp": ts,
             "received_at_clock": "BC_C", "received_at_port": 1},
            {"id": f"gm_b_to_gma_{i+1}", "source_clock": "GM_B",
             "receive_timestamp": ts + 0.0001,
             "received_at_clock": "GM_A", "received_at_port": 1},
        ]
        seg1_events.append((ts, frame, entries))

    # --- ROGUE_1: stepsRemoved=255 (disqualified, untagged) ---
    for i in range(3):
        ptp = build_announce(
            clock_identity_hex="deadbefffe000001", port_number=1,
            seq_id=i + 1, clock_class=6, clock_accuracy=0x20,
            offset_scaled_log_var=0x0100,
            gm_priority1=100, gm_priority2=100,
            steps_removed=255, time_source=0x20,
            tlv_gm_time_inaccuracy=25,
        )
        ts = 1700000001.500 + i * 1.0
        frame = eth_ptp_frame(mac_rogue1, ptp, vlan_id=None)
        entries = [
            {"id": f"rogue_steps_{i+1}", "source_clock": "ROGUE_1",
             "receive_timestamp": ts,
             "received_at_clock": "BC_C", "received_at_port": 1},
        ]
        seg1_events.append((ts, frame, entries))

    # --- ROGUE_2: alternateMasterFlag=TRUE (disqualified, untagged) ---
    for i in range(3):
        ptp = build_announce(
            clock_identity_hex="deadbefffe000002", port_number=1,
            seq_id=i + 1, clock_class=6, clock_accuracy=0x20,
            offset_scaled_log_var=0x0100,
            gm_priority1=90, gm_priority2=90,
            steps_removed=0, alternate_master=True,
            time_source=0x20, tlv_gm_time_inaccuracy=25,
        )
        ts = 1700000001.700 + i * 1.0
        frame = eth_ptp_frame(mac_rogue2, ptp, vlan_id=None)
        entries = [
            {"id": f"rogue_altmaster_{i+1}", "source_clock": "ROGUE_2",
             "receive_timestamp": ts,
             "received_at_clock": "BC_C", "received_at_port": 1},
        ]
        seg1_events.append((ts, frame, entries))

    # --- ROGUE_3: same clockIdentity as BC_C (disqualified, untagged) ---
    ptp = build_announce(
        clock_identity_hex="ccdd00fffe445566", port_number=99,
        seq_id=1, clock_class=6, clock_accuracy=0x20,
        offset_scaled_log_var=0x0100,
        gm_priority1=50, gm_priority2=50,
        steps_removed=0, time_source=0x20,
    )
    frame = eth_ptp_frame(mac_bc_c, ptp, vlan_id=None)
    seg1_events.append((1700000005.000, frame, [
        {"id": "rogue_self_identity", "source_clock": "ROGUE_3",
         "receive_timestamp": 1700000005.000,
         "received_at_clock": "BC_C", "received_at_port": 1},
    ]))

    # --- Noise frames on segment 1 (ARP, LLDP - untagged) ---
    seg1_events.append((1700000000.500, arp_frame(mac_gm_a), []))
    seg1_events.append((1700000002.400, lldp_frame(mac_bc_c), []))
    seg1_events.append((1700000004.500, arp_frame(mac_gm_b), []))
    seg1_events.append((1700000006.800, arp_frame(mac_gm_a), []))
    seg1_events.append((1700000008.500, lldp_frame(mac_bc_c), []))
    seg1_events.append((1700000010.500, arp_frame(mac_gm_b), []))

    # --- BC_C forwarded Announce to segment 2 (untagged) ---
    bc_c_fwd_timestamps = [
        1700000001.100, 1700000002.112, 1700000003.105, 1700000004.093,
        1700000005.108, 1700000006.097, 1700000007.115, 1700000008.103,
        1700000009.088, 1700000010.101,
    ]
    for i, ts in enumerate(bc_c_fwd_timestamps):
        ptp = build_announce(
            clock_identity_hex="ccdd00fffe445566", port_number=2,
            seq_id=i + 1, clock_class=6, clock_accuracy=0x21,
            offset_scaled_log_var=0x4E5D,
            gm_priority1=128, gm_priority2=128,
            gm_identity_hex="001122fffe334455",
            steps_removed=1, time_source=0x40,
            tlv_gm_time_inaccuracy=100, tlv_net_time_inaccuracy=50,
            log_message_interval=0,
        )
        frame = eth_ptp_frame(mac_bc_c, ptp, vlan_id=None)
        entries = [
            {"id": f"bc_c_fwd_{i+1}", "source_clock": "BC_C",
             "receive_timestamp": ts,
             "received_at_clock": "OC_D", "received_at_port": 1},
        ]
        seg2_events.append((ts, frame, entries))

    # --- Noise frames on segment 2 ---
    seg2_events.append((1700000000.800, arp_frame(mac_oc_d), []))
    seg2_events.append((1700000005.500, lldp_frame(mac_bc_c), []))
    seg2_events.append((1700000009.500, arp_frame(mac_oc_d), []))

    # Sort events by timestamp and write pcap files + capture log
    seg1_events.sort(key=lambda x: x[0])
    seg2_events.sort(key=lambda x: x[0])

    capture_log = []

    with open('/app/scenario/segment1.pcap', 'wb') as f:
        f.write(pcap_global_header())
        for idx, (ts, frame, entries) in enumerate(seg1_events, start=1):
            f.write(pcap_packet_record(ts, frame))
            for entry in entries:
                entry['pcap_file'] = 'segment1.pcap'
                entry['frame_number'] = idx
                capture_log.append(entry)

    with open('/app/scenario/segment2.pcap', 'wb') as f:
        f.write(pcap_global_header())
        for idx, (ts, frame, entries) in enumerate(seg2_events, start=1):
            f.write(pcap_packet_record(ts, frame))
            for entry in entries:
                entry['pcap_file'] = 'segment2.pcap'
                entry['frame_number'] = idx
                capture_log.append(entry)

    with open('/app/scenario/capture_log.json', 'w') as f:
        json.dump(capture_log, f, indent=2)

    with open('/app/scenario/topology.json', 'w') as f:
        json.dump(topology, f, indent=2)

    # --- Non-compliant ptp4l configuration for GM_B ---
    gm_b_config = (
        "[global]\n"
        "domainNumber\t\t0\n"
        "priority1\t\t100\n"
        "priority2\t\t100\n"
        "logAnnounceInterval\t1\n"
        "logSyncInterval\t\t-1\n"
        "logMinPdelayReqInterval\t-2\n"
        "announceReceiptTimeout\t5\n"
        "delay_mechanism\t\tE2E\n"
        "network_transport\tUDPv4\n"
        "clock_servo\t\tpi\n"
        "time_stamping\t\tsoftware\n"
        "tx_timestamp_timeout\t1\n"
        "summary_interval\t0\n"
    )
    with open('/app/configs/gm_b_ptp4l.conf', 'w') as f:
        f.write(gm_b_config)

    write_reference_docs()

    print(f"Generated segment1.pcap with {len(seg1_events)} frames")
    print(f"Generated segment2.pcap with {len(seg2_events)} frames")
    print(f"Generated {len(capture_log)} capture log entries")
    print("Scenario written to /app/scenario/")
    print("Config written to /app/configs/")
    print("Reference docs written to /app/reference/")


if __name__ == '__main__':
    main()
