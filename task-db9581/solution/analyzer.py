#!/usr/bin/env python3
"""
eMMC Flash Dump Analyzer

Parses a binary eMMC flash dump, verifies journal integrity,
computes wear statistics, and optimizes block mapping for
maximum device lifetime.
"""
import struct
import zlib
import json
import os


def parse_flash_dump(path):
    with open(path, 'rb') as f:
        data = f.read()

    # Header
    magic, version, page_size, ppb, total_blocks, jcount, pcount, tbw, mfg_ts, cur_ts = \
        struct.unpack_from('<IHHHHIIQII', data, 0)
    assert magic == 0x464C5348, f"Invalid magic: {hex(magic)}"

    block_size = page_size * ppb
    offset = 64

    # Block mapping table
    l2p = {}
    for _ in range(total_blocks):
        l, p = struct.unpack_from('<HH', data, offset)
        l2p[l] = p
        offset += 4

    # Erase count table
    erase_counts = []
    for _ in range(total_blocks):
        ec, = struct.unpack_from('<I', data, offset)
        erase_counts.append(ec)
        offset += 4

    # Journal with CRC verification
    corrupt_count = 0
    valid_writes = []
    write_heat = [0] * total_blocks
    process_bytes = {}

    for _ in range(jcount):
        prefix = data[offset:offset + 24]
        stored_crc, _ = struct.unpack_from('<II', data, offset + 24)
        computed_crc = zlib.crc32(prefix) & 0xFFFFFFFF

        if stored_crc != computed_crc:
            corrupt_count += 1
            offset += 32
            continue

        ts, lb, sp, pc, pid, flags, dh = struct.unpack_from('<IHHHHIQ', prefix)

        if flags == 0:  # write operation
            valid_writes.append((lb, sp, pc, pid))
            write_heat[lb] += pc
            process_bytes[pid] = process_bytes.get(pid, 0) + pc * page_size

        offset += 32

    # Process table
    processes = {}
    for _ in range(pcount):
        pid, _ = struct.unpack_from('<HH', data, offset)
        name = data[offset + 4:offset + 68].split(b'\x00')[0].decode('ascii')
        processes[pid] = name
        offset += 68

    return {
        'page_size': page_size,
        'ppb': ppb,
        'total_blocks': total_blocks,
        'block_size': block_size,
        'tbw': tbw,
        'mfg_ts': mfg_ts,
        'cur_ts': cur_ts,
        'l2p': l2p,
        'erase_counts': erase_counts,
        'corrupt_count': corrupt_count,
        'valid_writes': valid_writes,
        'write_heat': write_heat,
        'process_bytes': process_bytes,
        'processes': processes,
    }


def analyze(d):
    os.makedirs('/app/results', exist_ok=True)
    page_size = d['page_size']
    total_blocks = d['total_blocks']
    block_size = d['block_size']
    erase_counts = d['erase_counts']
    write_heat = d['write_heat']

    # Summary statistics
    total_host_writes = sum(pc * page_size for _, _, pc, _ in d['valid_writes'])
    total_nand_erase = sum(erase_counts) * block_size
    waf = total_nand_erase / total_host_writes if total_host_writes else 0.0

    elapsed_sec = d['cur_ts'] - d['mfg_ts']
    elapsed_days_float = elapsed_sec / 86400.0
    elapsed_days = int(elapsed_days_float)

    daily_nand = total_nand_erase / elapsed_days_float if elapsed_days_float > 0 else 0.0
    remaining = int((d['tbw'] - total_nand_erase) / daily_nand) if daily_nand > 0 else 0

    summary = {
        'corrupt_entries': d['corrupt_count'],
        'valid_write_entries': len(d['valid_writes']),
        'total_host_writes_bytes': total_host_writes,
        'total_nand_erase_bytes': total_nand_erase,
        'write_amplification_factor': round(waf, 6),
        'elapsed_days': elapsed_days,
        'remaining_lifetime_days': remaining,
        'max_erase_count': max(erase_counts),
        'min_erase_count': min(erase_counts),
        'mean_erase_count': round(sum(erase_counts) / len(erase_counts), 2),
    }
    with open('/app/results/summary.json', 'w') as f:
        json.dump(summary, f, indent=2)

    # Process writes
    pw = []
    for pid in sorted(d['process_bytes'].keys(), key=lambda x: (-d['process_bytes'][x], x)):
        pw.append({
            'pid': pid,
            'name': d['processes'].get(pid, f'unknown-{pid}'),
            'bytes_written': d['process_bytes'][pid],
        })
    with open('/app/results/process_writes.json', 'w') as f:
        json.dump(pw, f, indent=2)

    # Hot blocks
    hot = sorted(
        [{'physical_block': i, 'erase_count': erase_counts[i]} for i in range(total_blocks)],
        key=lambda x: (-x['erase_count'], x['physical_block'])
    )[:20]
    with open('/app/results/hot_blocks.json', 'w') as f:
        json.dump(hot, f, indent=2)

    # Current mapping cost
    l2p = d['l2p']
    current_costs = [erase_counts[l2p[l]] + write_heat[l] for l in range(total_blocks)]
    current_max = max(current_costs)

    # Optimized mapping via minimax assignment:
    # Pair highest-heat logical blocks with lowest-erase physical blocks.
    # This minimizes max(erase_count[p] + write_heat[l]) over all pairs.
    logical_sorted = sorted(range(total_blocks), key=lambda l: -write_heat[l])
    physical_sorted = sorted(range(total_blocks), key=lambda p: erase_counts[p])

    opt_mapping = [0] * total_blocks
    for i, l in enumerate(logical_sorted):
        opt_mapping[l] = physical_sorted[i]

    projected_max = max(erase_counts[opt_mapping[l]] + write_heat[l] for l in range(total_blocks))

    with open('/app/results/optimized_mapping.json', 'w') as f:
        json.dump({
            'mapping': opt_mapping,
            'projected_max_total': projected_max,
            'current_max_total': current_max,
        }, f, indent=2)

    print(f"Summary: {d['corrupt_count']} corrupt entries, "
          f"WAF={round(waf, 4)}, "
          f"remaining={remaining} days")
    print(f"Optimization: {current_max} -> {projected_max} "
          f"(improvement: {current_max - projected_max})")


if __name__ == '__main__':
    parsed = parse_flash_dump('/app/flash_dump.bin')
    analyze(parsed)
