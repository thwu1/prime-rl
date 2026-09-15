#!/usr/bin/env python3
"""
WebRTC SCTP Session Forensic Analyzer.

Combines three analysis techniques:
1. Direct pcap binary parsing for SCTP association parameters
2. Binary DCEP DATA_CHANNEL_OPEN decoding
3. SCTP receiver-side SACK state machine with FORWARD-TSN delivery analysis

Produces /app/results.json with association, data_channels, sacks, abandoned_tsns.
"""


import json
import struct

UINT32_MOD = 2 ** 32
HALF_UINT32 = 2 ** 31


# ==================== pcap / SCTP parsing ====================

def parse_pcap_packets(pcap_path):
    """Parse pcap file and return list of raw packet bytes."""
    with open(pcap_path, "rb") as f:
        data = f.read()

    # Global header: magic(4) version_major(2) version_minor(2) thiszone(4)
    #                sigfigs(4) snaplen(4) network(4) = 24 bytes
    magic = struct.unpack_from("<I", data, 0)[0]
    if magic == 0xa1b2c3d4:
        endian = "<"
    elif magic == 0xd4c3b2a1:
        endian = ">"
    else:
        raise ValueError(f"Unknown pcap magic: {magic:#x}")

    offset = 24
    packets = []
    while offset < len(data):
        # Packet header: ts_sec(4) ts_usec(4) incl_len(4) orig_len(4) = 16 bytes
        ts_sec, ts_usec, incl_len, orig_len = struct.unpack_from(endian + "IIII", data, offset)
        offset += 16
        pkt_data = data[offset:offset + incl_len]
        packets.append(pkt_data)
        offset += incl_len

    return packets


def parse_sctp_init_chunks(pcap_path):
    """Extract INIT and INIT-ACK parameters from raw pcap."""
    packets = parse_pcap_packets(pcap_path)
    init_params = None
    init_ack_params = None

    for pkt in packets:
        # LINKTYPE_RAW (101): raw IPv4
        # IPv4 header: version/IHL at byte 0, protocol at byte 9
        if len(pkt) < 20:
            continue
        version_ihl = pkt[0]
        ihl = (version_ihl & 0x0F) * 4
        protocol = pkt[9]
        if protocol != 132:  # SCTP
            continue

        # SCTP header starts after IP header
        sctp_offset = ihl
        if len(pkt) < sctp_offset + 12:
            continue

        # SCTP common header: src_port(2) dst_port(2) vtag(4) checksum(4) = 12 bytes
        sctp_offset += 12  # skip to chunks

        # Parse chunks
        while sctp_offset + 4 <= len(pkt):
            chunk_type = pkt[sctp_offset]
            chunk_flags = pkt[sctp_offset + 1]
            chunk_length = struct.unpack_from("!H", pkt, sctp_offset + 2)[0]

            if chunk_type in (1, 2) and chunk_length >= 20:
                # INIT or INIT-ACK chunk value:
                # initiate_tag(4) a_rwnd(4) num_os(2) num_mis(2) initial_tsn(4)
                val_offset = sctp_offset + 4
                init_tag, a_rwnd, num_os, num_mis, initial_tsn = struct.unpack_from(
                    "!IIHHI", pkt, val_offset
                )
                params = {
                    "initiate_tag": init_tag,
                    "a_rwnd": a_rwnd,
                    "initial_tsn": initial_tsn,
                }
                if chunk_type == 1:
                    init_params = params
                else:
                    init_ack_params = params

            # Advance to next chunk (padded to 4-byte boundary)
            chunk_length_padded = (chunk_length + 3) & ~3
            sctp_offset += chunk_length_padded

    return init_params, init_ack_params


def extract_association_from_pcap(pcap_path):
    """Extract SCTP INIT/INIT-ACK fields by parsing pcap directly."""
    init_params, ack_params = parse_sctp_init_chunks(pcap_path)

    if init_params is None:
        raise ValueError("No SCTP INIT chunk found in pcap")
    if ack_params is None:
        raise ValueError("No SCTP INIT-ACK chunk found in pcap")

    return {
        "a_initiate_tag": init_params["initiate_tag"],
        "b_initiate_tag": ack_params["initiate_tag"],
        "a_initial_tsn": init_params["initial_tsn"],
        "b_initial_tsn": ack_params["initial_tsn"],
        "a_rwnd": init_params["a_rwnd"],
        "b_rwnd": ack_params["a_rwnd"],
    }


# ==================== DCEP binary decoding ====================

def decode_dcep_payloads(bin_path):
    """Decode DATA_CHANNEL_OPEN messages from binary file."""
    channels = []
    with open(bin_path, "rb") as f:
        data = f.read()

    offset = 0
    while offset < len(data):
        stream_id, payload_len = struct.unpack_from("!HH", data, offset)
        offset += 4
        payload = data[offset:offset + payload_len]
        offset += payload_len

        # Parse DATA_CHANNEL_OPEN (RFC 8832)
        msg_type = payload[0]
        assert msg_type == 0x03, f"Expected DATA_CHANNEL_OPEN (0x03), got {msg_type:#x}"

        channel_type = payload[1]
        priority, reliability_param, label_len, proto_len = struct.unpack_from(
            "!HIHH", payload, 2
        )
        label_start = 12
        label = payload[label_start:label_start + label_len].decode("utf-8")
        proto_start = label_start + label_len
        protocol = payload[proto_start:proto_start + proto_len].decode("utf-8")

        channels.append({
            "stream_id": stream_id,
            "label": label,
            "channel_type": channel_type,
            "priority": priority,
            "reliability_param": reliability_param,
            "protocol": protocol,
        })

    return channels


# ==================== SCTP SACK state machine ====================

def tsn_diff(a, b):
    return (a - b) % UINT32_MOD


def tsn_gt(a, b):
    diff = tsn_diff(a, b)
    return 0 < diff < HALF_UINT32


def tsn_lte(a, b):
    return a == b or tsn_gt(b, a)


class SCTPReceiver:
    def __init__(self, initial_tsn):
        self.cumulative_tsn = (initial_tsn - 1) % UINT32_MOD
        self.received_beyond = set()
        self.dup_tsns = []

    def receive_data(self, tsn):
        if tsn_lte(tsn, self.cumulative_tsn):
            self.dup_tsns.append(tsn)
        elif tsn in self.received_beyond:
            self.dup_tsns.append(tsn)
        else:
            self.received_beyond.add(tsn)
            self._advance_cumulative()

    def process_forward_tsn(self, new_cumulative_tsn):
        if tsn_gt(new_cumulative_tsn, self.cumulative_tsn):
            old_cum = self.cumulative_tsn
            self.cumulative_tsn = new_cumulative_tsn
            self.received_beyond = {
                t for t in self.received_beyond
                if tsn_gt(t, self.cumulative_tsn)
            }
            self._advance_cumulative()
            return old_cum
        return self.cumulative_tsn

    def _advance_cumulative(self):
        while True:
            next_tsn = (self.cumulative_tsn + 1) % UINT32_MOD
            if next_tsn in self.received_beyond:
                self.received_beyond.remove(next_tsn)
                self.cumulative_tsn = next_tsn
            else:
                break

    def compute_sack(self):
        gap_blocks = []
        if self.received_beyond:
            offsets = sorted(tsn_diff(t, self.cumulative_tsn) for t in self.received_beyond)
            start = end = offsets[0]
            for i in range(1, len(offsets)):
                if offsets[i] == end + 1:
                    end = offsets[i]
                else:
                    gap_blocks.append([start, end])
                    start = end = offsets[i]
            gap_blocks.append([start, end])

        result = {
            "cumulative_tsn": self.cumulative_tsn,
            "gap_blocks": gap_blocks,
            "dup_tsns": list(self.dup_tsns),
        }
        self.dup_tsns = []
        return result

    def get_received_set(self):
        """Return set of all TSNs currently tracked beyond cumulative."""
        return set(self.received_beyond)


def compute_abandoned_tsns(old_cum, new_cum, received_set):
    """Compute TSNs in (old_cum, new_cum] that were NOT in received_set."""
    abandoned = []
    tsn = (old_cum + 1) % UINT32_MOD
    while True:
        if tsn not in received_set:
            abandoned.append(tsn)
        if tsn == new_cum:
            break
        tsn = (tsn + 1) % UINT32_MOD
    return abandoned


# ==================== Main ====================

def main():
    # 1. Extract association parameters from pcap (direct binary parsing)
    association = extract_association_from_pcap("/app/handshake.pcap")

    # 2. Decode DCEP data channel info from binary
    data_channels = decode_dcep_payloads("/app/dcep_payloads.bin")

    # 3. Process session trace for SACK state machine + delivery analysis
    with open("/app/session_trace.json", "r") as f:
        trace = json.load(f)

    receiver = SCTPReceiver(trace["initial_tsn"])
    sacks = {}
    abandoned_tsns = {}

    for event in trace["events"]:
        etype = event["type"]
        if etype == "data_received":
            receiver.receive_data(event["tsn"])
        elif etype == "forward_tsn":
            received_snapshot = set(receiver.received_beyond)
            old_cum = receiver.process_forward_tsn(event["new_cumulative_tsn"])
            abandoned = compute_abandoned_tsns(
                old_cum, event["new_cumulative_tsn"], received_snapshot
            )
            abandoned_tsns[event["id"]] = abandoned
        elif etype == "compute_sack":
            sacks[event["id"]] = receiver.compute_sack()

    # 4. Write results
    results = {
        "association": association,
        "data_channels": data_channels,
        "sacks": sacks,
        "abandoned_tsns": abandoned_tsns,
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
