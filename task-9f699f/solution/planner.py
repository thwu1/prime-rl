#!/usr/bin/env python3
"""Flash Memory Programming Planner.

Parses probe-rs-style target description YAMLs and Intel HEX firmware files,
then computes optimal flash erase and program operations.
"""


import argparse
import json
import sys
import yaml


def parse_target(yaml_path, variant_name):
    """Parse target YAML, return (family_name, variant_name, regions_list)."""
    with open(yaml_path) as f:
        target = yaml.safe_load(f)

    for variant in target['variants']:
        if variant['name'] == variant_name:
            regions = []
            for entry in variant['memory_map']:
                if entry['type'] == 'nvm':
                    fp = entry['flash_properties']
                    regions.append({
                        'name': entry['name'],
                        'start': entry['range']['start'],
                        'end': entry['range']['end'],
                        'page_size': fp['page_size'],
                        'erased_byte_value': fp['erased_byte_value'],
                        'sector_descriptors': fp['sectors'],
                    })
            return target['name'], variant['name'], regions

    raise ValueError(f"Variant '{variant_name}' not found in target description")


def enumerate_sectors(region):
    """Enumerate individual sectors from a region's sector descriptors.

    Each descriptor defines the sector size from its address until the next
    descriptor's address (or the region end). Sectors of that size are tiled
    across the range.
    """
    descs = sorted(region['sector_descriptors'], key=lambda d: d['address'])
    sectors = []
    for i, desc in enumerate(descs):
        size = desc['size']
        start = desc['address']
        end = descs[i + 1]['address'] if i + 1 < len(descs) else region['end']
        addr = start
        while addr + size <= end:
            sectors.append({'address': addr, 'size': size})
            addr += size
    return sectors


def parse_intel_hex(hex_path):
    """Parse Intel HEX file, return merged segments as [(address, bytes), ...]."""
    raw_segments = []
    base_address = 0

    with open(hex_path) as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line or line[0] != ':':
                continue

            raw = line[1:]
            byte_count = int(raw[0:2], 16)
            address = int(raw[2:6], 16)
            record_type = int(raw[6:8], 16)

            data_end = 8 + byte_count * 2
            data = bytes.fromhex(raw[8:data_end])
            checksum_byte = int(raw[data_end:data_end + 2], 16)

            # Verify checksum: two's complement of sum of all bytes
            record_bytes = bytes.fromhex(raw[:data_end])
            computed = (256 - sum(record_bytes) % 256) % 256
            if computed != checksum_byte:
                raise ValueError(
                    f"Line {line_num}: checksum mismatch "
                    f"(computed 0x{computed:02X}, got 0x{checksum_byte:02X})"
                )

            if record_type == 0x00:  # Data record
                raw_segments.append((base_address + address, data))
            elif record_type == 0x01:  # End of file
                break
            elif record_type == 0x02:  # Extended segment address
                base_address = int.from_bytes(data, 'big') << 4
            elif record_type == 0x04:  # Extended linear address
                base_address = int.from_bytes(data, 'big') << 16

    if not raw_segments:
        return []

    # Sort by address and merge contiguous segments
    raw_segments.sort(key=lambda s: s[0])
    merged = []
    cur_addr, cur_data = raw_segments[0][0], bytearray(raw_segments[0][1])

    for addr, data in raw_segments[1:]:
        if addr == cur_addr + len(cur_data):
            cur_data.extend(data)
        else:
            merged.append((cur_addr, bytes(cur_data)))
            cur_addr = addr
            cur_data = bytearray(data)

    merged.append((cur_addr, bytes(cur_data)))
    return merged


def find_region(regions, address):
    """Find the NVM region containing the given address, or None."""
    for r in regions:
        if r['start'] <= address < r['end']:
            return r
    return None


def compute_plan(regions, segments):
    """Compute flash programming plan from regions and firmware segments.

    Returns dict with 'operations' and 'statistics'.
    """
    # Map firmware data into page-aligned buffers
    page_map = {}        # (region_name, page_addr) -> bytearray
    fw_byte_count = {}   # (region_name, page_addr) -> int (firmware bytes, not fill)

    for seg_addr, seg_data in segments:
        offset = 0
        while offset < len(seg_data):
            addr = seg_addr + offset
            rgn = find_region(regions, addr)
            if rgn is None:
                raise ValueError(f"Address 0x{addr:08X} is outside any flash region")

            page_size = rgn['page_size']
            relative = addr - rgn['start']
            page_index = relative // page_size
            page_addr = rgn['start'] + page_index * page_size
            offset_in_page = relative % page_size

            key = (rgn['name'], page_addr)
            if key not in page_map:
                page_map[key] = bytearray([rgn['erased_byte_value']] * page_size)
                fw_byte_count[key] = 0

            # Write as many bytes as fit in this page
            n = min(page_size - offset_in_page, len(seg_data) - offset)
            page_map[key][offset_in_page:offset_in_page + n] = seg_data[offset:offset + n]
            fw_byte_count[key] += n
            offset += n

    # Filter out pages that are entirely the erased byte value
    active_pages = {}
    fill_total = 0

    for key, page_data in page_map.items():
        region_name = key[0]
        rgn = next(r for r in regions if r['name'] == region_name)

        if all(b == rgn['erased_byte_value'] for b in page_data):
            continue  # Skip — no programming needed

        active_pages[key] = page_data
        fill_total += rgn['page_size'] - fw_byte_count[key]

    # Determine which sectors need erasing (those containing active pages)
    erase_set = set()  # (region_name, sector_addr, sector_size)
    used_regions = set()

    for (region_name, page_addr) in active_pages:
        rgn = next(r for r in regions if r['name'] == region_name)
        used_regions.add(region_name)
        sectors = enumerate_sectors(rgn)
        page_end = page_addr + rgn['page_size']

        for s in sectors:
            sector_end = s['address'] + s['size']
            # Check overlap between [page_addr, page_end) and [sector_addr, sector_end)
            if s['address'] < page_end and sector_end > page_addr:
                erase_set.add((region_name, s['address'], s['size']))

    # Build operations list: erases first (sorted), then programs (sorted)
    operations = []

    for rn, sa, ss in sorted(erase_set):
        operations.append({
            'type': 'erase',
            'region': rn,
            'address': sa,
            'size': ss,
        })

    for key in sorted(active_pages.keys()):
        rn, pa = key
        rgn = next(r for r in regions if r['name'] == rn)
        operations.append({
            'type': 'program',
            'region': rn,
            'address': pa,
            'size': rgn['page_size'],
        })

    # Compute statistics
    erase_ops = [op for op in operations if op['type'] == 'erase']
    program_ops = [op for op in operations if op['type'] == 'program']

    return {
        'operations': operations,
        'statistics': {
            'total_erase_size': sum(op['size'] for op in erase_ops),
            'total_program_size': sum(op['size'] for op in program_ops),
            'sectors_erased': len(erase_ops),
            'pages_programmed': len(program_ops),
            'fill_bytes': fill_total,
            'regions_used': sorted(used_regions),
        },
    }


def main():
    parser = argparse.ArgumentParser(
        description='Flash Memory Programming Planner'
    )
    parser.add_argument('--target', required=True, help='Target YAML file')
    parser.add_argument('--variant', required=True, help='Chip variant name')
    parser.add_argument('--firmware', required=True, help='Intel HEX firmware file')
    parser.add_argument('--output', required=True, help='Output JSON file')
    args = parser.parse_args()

    try:
        family, variant, regions = parse_target(args.target, args.variant)
        segments = parse_intel_hex(args.firmware)
        plan = compute_plan(regions, segments)
        plan['target'] = family
        plan['variant'] = variant

        with open(args.output, 'w') as f:
            json.dump(plan, f, indent=2)

    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
