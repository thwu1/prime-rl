#!/usr/bin/env python3
"""Analyze virtio-net device crash dumps and produce diagnostic report."""

import struct
import json
import os

DUMPS = '/app/dumps'
VNET_HDR_SIZE = 12  # mergeable rxbuf header

VIRTQ_DESC_F_NEXT = 0x1
VIRTQ_DESC_F_WRITE = 0x2


def read_bin(path):
    with open(path, 'rb') as f:
        return f.read()


def fmt_mac(data):
    return ':'.join(f'{b:02x}' for b in data)


# ====== Device Config ======
def parse_device_config():
    data = read_bin(f'{DUMPS}/device_config.bin')
    mac = data[0:6]
    status, max_pairs, mtu = struct.unpack_from('<HHH', data, 6)
    return {
        'mac': fmt_mac(mac),
        'status_raw': status,
        'max_virtqueue_pairs': max_pairs,
        'mtu': mtu,
    }


# ====== Common Config ======
def parse_common_cfg():
    data = read_bin(f'{DUMPS}/common_cfg.bin')
    (dev_feat_sel, dev_feat, drv_feat_sel, drv_feat,
     msix_cfg, num_queues) = struct.unpack_from('<IIIIHH', data, 0)
    device_status, config_gen, queue_select = struct.unpack_from('<BBH', data, 0x14)
    return {
        'device_status': device_status,
        'num_queues': num_queues,
        'queue_select': queue_select,
    }


# ====== Features ======
def parse_features():
    data = read_bin(f'{DUMPS}/features.bin')
    dev0, dev1, drv0, drv1 = struct.unpack('<IIII', data)
    return {'word0': drv0, 'word1': drv1}


# ====== Queue Configs ======
def parse_queue_configs():
    data = read_bin(f'{DUMPS}/queue_configs.bin')
    configs = []
    for i in range(3):
        off = i * 32
        size, msix_vec, enable, notify_off = struct.unpack_from('<HHHH', data, off)
        desc_addr, avail_addr, used_addr = struct.unpack_from('<QQQ', data, off + 8)
        configs.append({
            'index': i, 'size': size, 'msix_vector': msix_vec,
            'enable': enable, 'notify_off': notify_off,
            'desc_addr': desc_addr, 'avail_addr': avail_addr, 'used_addr': used_addr,
        })
    return configs


# ====== Descriptor Table ======
def parse_desc_table(path, queue_size):
    data = read_bin(path)
    descs = []
    for i in range(queue_size):
        off = i * 16
        addr, length, flags, next_idx = struct.unpack_from('<QIHH', data, off)
        descs.append({'addr': addr, 'len': length, 'flags': flags, 'next': next_idx})
    return descs


# ====== Ring Parsing ======
def parse_avail_ring(path, queue_size):
    data = read_bin(path)
    flags, idx = struct.unpack_from('<HH', data, 0)
    entries = []
    for i in range(queue_size):
        e, = struct.unpack_from('<H', data, 4 + i * 2)
        entries.append(e)
    return {'flags': flags, 'idx': idx, 'ring': entries}


def parse_used_ring(path, queue_size):
    data = read_bin(path)
    flags, idx = struct.unpack_from('<HH', data, 0)
    entries = []
    for i in range(queue_size):
        eid, elen = struct.unpack_from('<II', data, 4 + i * 8)
        entries.append({'id': eid, 'len': elen})
    return {'flags': flags, 'idx': idx, 'ring': entries}


# ====== Chain Walking ======
def walk_chain(descs, head, queue_size):
    """Walk a descriptor chain. Returns (chain_descs, error_or_None)."""
    visited = set()
    chain = []
    idx = head
    while True:
        if idx >= queue_size:
            return chain, {'chain_head': head, 'type': 'out_of_bounds',
                           'details': f'next index {idx} >= queue_size {queue_size}'}
        if idx in visited:
            return chain, {'chain_head': head, 'type': 'circular',
                           'details': f'cycle detected at descriptor {idx}'}
        visited.add(idx)
        d = descs[idx]
        chain.append((idx, d))
        if d['flags'] & VIRTQ_DESC_F_NEXT:
            idx = d['next']
        else:
            break
    return chain, None


# ====== Packet Extraction ======
def extract_eth_header(guest_mem, addr):
    """Extract Ethernet dst_mac, src_mac, ethertype from guest memory at addr."""
    dst = guest_mem[addr:addr+6]
    src = guest_mem[addr+6:addr+12]
    ethertype, = struct.unpack_from('>H', guest_mem, addr + 12)
    return fmt_mac(dst), fmt_mac(src), f'0x{ethertype:04x}'


# ====== Event Log ======
def parse_event_log():
    data = read_bin(f'{DUMPS}/event_log.bin')
    events = []
    i = 0
    while i + 16 <= len(data):
        ts, etype = struct.unpack_from('<QB', data, i)
        edata = data[i+9:i+16]
        events.append({'timestamp_ns': ts, 'type': etype, 'data': edata})
        i += 16
    return events


# ====== MSI-X ======
def parse_msix_table():
    data = read_bin(f'{DUMPS}/msix_table.bin')
    entries = []
    i = 0
    vec = 0
    while i + 16 <= len(data):
        addr_lo, addr_hi, msg_data, vec_ctrl = struct.unpack_from('<IIII', data, i)
        entries.append({
            'vector': vec, 'addr_lo': addr_lo, 'addr_hi': addr_hi,
            'msg_data': msg_data, 'masked': bool(vec_ctrl & 1),
        })
        i += 16
        vec += 1
    return entries


# ====== Main Analysis ======
def main():
    guest_mem = read_bin(f'{DUMPS}/guest_memory.bin')
    dev_cfg = parse_device_config()
    common = parse_common_cfg()
    features = parse_features()
    qconfigs = parse_queue_configs()
    events = parse_event_log()
    msix = parse_msix_table()

    # Device info
    device_info = {
        'mac': dev_cfg['mac'],
        'status': common['device_status'],
        'mtu': dev_cfg['mtu'],
        'num_queues': common['num_queues'],
    }

    # Queue analysis
    queues_report = []
    for qc in qconfigs:
        qi = qc['index']
        qsz = qc['size']
        descs = parse_desc_table(f'{DUMPS}/queues/{qi}/desc.bin', qsz)
        avail = parse_avail_ring(f'{DUMPS}/queues/{qi}/avail.bin', qsz)
        used = parse_used_ring(f'{DUMPS}/queues/{qi}/used.bin', qsz)

        # Find pending chains: from used_idx to avail_idx
        errors = []
        pending_start = used['idx']
        pending_end = avail['idx']
        for p in range(pending_start, pending_end):
            head = avail['ring'][p % qsz]
            _, err = walk_chain(descs, head, qsz)
            if err:
                errors.append(err)

        queues_report.append({
            'index': qi,
            'size': qsz,
            'avail_idx': avail['idx'],
            'used_idx': used['idx'],
            'errors': errors,
        })

    # Packet forensics — TX (from used ring of queue 1)
    tx_packets = []
    tx_qc = qconfigs[1]
    tx_descs = parse_desc_table(f'{DUMPS}/queues/1/desc.bin', tx_qc['size'])
    tx_used = parse_used_ring(f'{DUMPS}/queues/1/used.bin', tx_qc['size'])
    for u in range(tx_used['idx']):
        entry = tx_used['ring'][u]
        head = entry['id']
        chain, err = walk_chain(tx_descs, head, tx_qc['size'])
        if err:
            continue
        # First desc = virtio-net header, second+ = packet data
        if len(chain) >= 2:
            data_desc = chain[1][1]
            addr = data_desc['addr']
            if addr + 14 <= len(guest_mem):
                dst, src, et = extract_eth_header(guest_mem, addr)
                tx_packets.append({
                    'chain_head': head, 'dst_mac': dst, 'src_mac': src, 'ethertype': et
                })

    # Packet forensics — RX (from used ring of queue 0)
    rx_packets = []
    rx_qc = qconfigs[0]
    rx_descs = parse_desc_table(f'{DUMPS}/queues/0/desc.bin', rx_qc['size'])
    rx_used = parse_used_ring(f'{DUMPS}/queues/0/used.bin', rx_qc['size'])
    for u in range(rx_used['idx']):
        entry = rx_used['ring'][u]
        desc_id = entry['id']
        d = rx_descs[desc_id]
        addr = d['addr'] + VNET_HDR_SIZE  # skip virtio-net header
        if addr + 14 <= len(guest_mem):
            dst, src, et = extract_eth_header(guest_mem, addr)
            rx_packets.append({
                'desc_id': desc_id, 'dst_mac': dst, 'src_mac': src, 'ethertype': et
            })

    # Crash diagnosis from event log
    crash_event = None
    for ev in events:
        if ev['type'] == 3:  # error
            crash_event = ev
            break

    crash_cause = "descriptor_chain_error"
    crash_queue = crash_event['data'][1] if crash_event else -1
    crash_ts = crash_event['timestamp_ns'] if crash_event else 0

    # MSI-X issues
    msix_issues = []
    for entry in msix:
        if entry['masked'] and entry['addr_lo'] == 0 and entry['addr_hi'] == 0:
            msix_issues.append({
                'vector_index': entry['vector'],
                'issue': 'masked_with_zero_address'
            })

    report = {
        'device': device_info,
        'features': features,
        'queues': queues_report,
        'packets': {
            'tx_sent': tx_packets,
            'rx_received': rx_packets,
        },
        'crash': {
            'cause': crash_cause,
            'queue_index': crash_queue,
            'timestamp_ns': crash_ts,
            'msix_issues': msix_issues,
        },
    }

    with open('/app/analysis_report.json', 'w') as f:
        json.dump(report, f, indent=2)

    print("Report written to /app/analysis_report.json")


if __name__ == '__main__':
    main()
