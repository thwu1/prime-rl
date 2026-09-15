#!/usr/bin/env python3
"""Differential flash programming optimizer for embedded microcontrollers.

Computes minimal flash operation plans by analyzing current flash state
and determining when sector erases can be safely skipped.
"""


import argparse
import json
import sys
import yaml


def parse_ihex(path):
    """Parse Intel HEX file into address->byte map."""
    addr_map = {}
    base_address = 0
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line[0] != ':':
                continue
            raw = bytes.fromhex(line[1:])
            byte_count = raw[0]
            offset = (raw[1] << 8) | raw[2]
            rec_type = raw[3]
            data = raw[4:4 + byte_count]
            checksum = raw[4 + byte_count]
            expected = (256 - sum(raw[:4 + byte_count]) % 256) % 256
            if checksum != expected:
                raise ValueError("Intel HEX checksum mismatch")
            if rec_type == 0x00:
                for i, b in enumerate(data):
                    addr_map[base_address + offset + i] = b
            elif rec_type == 0x01:
                break
            elif rec_type == 0x02:
                base_address = ((data[0] << 8) | data[1]) << 4
            elif rec_type == 0x04:
                base_address = ((data[0] << 8) | data[1]) << 16
    return addr_map


def parse_srec(path):
    """Parse Motorola S-record file into address->byte map."""
    addr_map = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line[0] != 'S':
                continue
            rec_type = int(line[1])
            raw = bytes.fromhex(line[2:])
            byte_count = raw[0]
            expected_cs = (~sum(raw[:byte_count])) & 0xFF
            if raw[byte_count] != expected_cs:
                raise ValueError("SREC checksum mismatch")
            if rec_type == 1:
                addr = (raw[1] << 8) | raw[2]
                data = raw[3:byte_count]
            elif rec_type == 2:
                addr = (raw[1] << 16) | (raw[2] << 8) | raw[3]
                data = raw[4:byte_count]
            elif rec_type == 3:
                addr = (raw[1] << 24) | (raw[2] << 16) | (raw[3] << 8) | raw[4]
                data = raw[5:byte_count]
            else:
                continue
            for i, b in enumerate(data):
                addr_map[addr + i] = b
    return addr_map


def load_firmware(path):
    """Auto-detect firmware format and parse to address->byte map."""
    with open(path) as f:
        first_line = f.readline().strip()
    if first_line.startswith(':'):
        return parse_ihex(path)
    elif first_line.startswith('S'):
        return parse_srec(path)
    else:
        raise ValueError(f"Unrecognized firmware format in {path}")


def parse_target(path, variant_name):
    """Parse probe-rs target YAML, return (family_name, nvm_regions)."""
    with open(path) as f:
        data = yaml.safe_load(f)
    family = data['name']
    for v in data['variants']:
        if v['name'] == variant_name:
            regions = []
            for m in v['memory_map']:
                if m['type'] == 'nvm':
                    regions.append(m)
            regions.sort(key=lambda r: r['range']['start'])
            return family, regions
    raise ValueError(f"Variant '{variant_name}' not found in {path}")


def enumerate_sectors(region):
    """Enumerate all individual sectors in a region.
    Returns list of (address, size) tuples."""
    fp = region['flash_properties']
    descs = fp['sectors']
    region_end = region['range']['end']
    sectors = []
    for i, desc in enumerate(descs):
        size = desc['size']
        start = desc['address']
        limit = descs[i + 1]['address'] if i + 1 < len(descs) else region_end
        addr = start
        while addr < limit:
            sectors.append((addr, size))
            addr += size
    return sectors


def can_program_without_erase(current_bytes, desired_bytes, erased_byte):
    """Determine if current->desired transition is achievable by
    programming alone (without erasing first).

    Flash programming can only transition bits FROM the erased state
    TO the programmed state. The reverse requires a full sector erase.
    """
    if erased_byte == 0xFF:
        # Erased = all 1s. Programming clears bits (1->0).
        # Cannot set bits (0->1) without erase.
        # Check: current AND desired must equal desired.
        for c, d in zip(current_bytes, desired_bytes):
            if (c & d) != d:
                return False
    elif erased_byte == 0x00:
        # Erased = all 0s. Programming sets bits (0->1).
        # Cannot clear bits (1->0) without erase.
        # Check: current OR desired must equal desired.
        for c, d in zip(current_bytes, desired_bytes):
            if (c | d) != d:
                return False
    else:
        # General case: bit-level analysis
        for c, d in zip(current_bytes, desired_bytes):
            if c == d:
                continue
            for bit in range(8):
                c_bit = (c >> bit) & 1
                d_bit = (d >> bit) & 1
                e_bit = (erased_byte >> bit) & 1
                if c_bit != d_bit and d_bit == e_bit:
                    return False
    return True


def main():
    parser = argparse.ArgumentParser(
        description='Differential flash programming optimizer')
    parser.add_argument('--target', required=True, help='Target YAML file')
    parser.add_argument('--variant', required=True, help='Chip variant name')
    parser.add_argument('--firmware', required=True, help='Firmware file')
    parser.add_argument('--current-state', required=True,
                        help='Current flash state binary dump')
    parser.add_argument('--output', required=True, help='Output JSON file')
    args = parser.parse_args()

    family, nvm_regions = parse_target(args.target, args.variant)
    fw = load_firmware(args.firmware)

    with open(args.current_state, 'rb') as f:
        state_raw = f.read()

    # Map current state bytes to each NVM region (concatenated by start addr)
    offset = 0
    region_state = {}
    for r in nvm_regions:
        rsize = r['range']['end'] - r['range']['start']
        region_state[r['name']] = state_raw[offset:offset + rsize]
        offset += rsize

    # Validate: every firmware byte must fall within a defined NVM region
    for addr in fw:
        if not any(r['range']['start'] <= addr < r['range']['end']
                   for r in nvm_regions):
            sys.exit(1)

    erase_ops = []
    prog_ops = []
    stats = {
        'total_erase_size': 0,
        'total_program_size': 0,
        'sectors_erased': 0,
        'sectors_skipped': 0,
        'pages_programmed': 0,
        'fill_bytes': 0,
        'regions_used': [],
        'bytes_changed': 0,
    }

    for region in nvm_regions:
        rname = region['name']
        rstart = region['range']['start']
        rend = region['range']['end']
        fp = region['flash_properties']
        page_size = fp['page_size']
        erased_byte = fp['erased_byte_value']
        cur_state = region_state[rname]

        # Firmware bytes in this region
        rfirmware = {a: v for a, v in fw.items() if rstart <= a < rend}
        if not rfirmware:
            continue

        # Build desired page contents from firmware, filled with erased byte
        all_pages = {}
        for addr, val in rfirmware.items():
            page_start = rstart + ((addr - rstart) // page_size) * page_size
            if page_start not in all_pages:
                all_pages[page_start] = bytearray([erased_byte] * page_size)
            all_pages[page_start][addr - page_start] = val

        # Filter: pages entirely consisting of erased byte need no operations
        non_erased = {}
        for ps, pd in all_pages.items():
            if not all(b == erased_byte for b in pd):
                non_erased[ps] = pd

        if not non_erased:
            continue

        # Classify pages by whether they differ from current state
        changed = {}
        identical = {}
        for ps, pd in non_erased.items():
            state_off = ps - rstart
            cur_page = cur_state[state_off:state_off + page_size]
            if bytes(pd) != cur_page:
                changed[ps] = pd
            else:
                identical[ps] = pd

        if not changed:
            continue

        stats['regions_used'].append(rname)
        sectors = enumerate_sectors(region)

        for s_addr, s_size in sectors:
            s_end = s_addr + s_size

            # Changed pages in this sector
            sec_changed = {ps: pd for ps, pd in changed.items()
                           if s_addr <= ps < s_end}
            if not sec_changed:
                continue

            # Identical pages in this sector (may need reprogramming if erased)
            sec_identical = {ps: pd for ps, pd in identical.items()
                             if s_addr <= ps < s_end}

            # Determine if any changed page requires a bit reversal
            needs_erase = False
            for ps, pd in sec_changed.items():
                state_off = ps - rstart
                cur_page = cur_state[state_off:state_off + page_size]
                if not can_program_without_erase(cur_page, bytes(pd),
                                                 erased_byte):
                    needs_erase = True
                    break

            if needs_erase:
                erase_ops.append({
                    'type': 'erase',
                    'region': rname,
                    'address': s_addr,
                    'size': s_size,
                })
                stats['total_erase_size'] += s_size
                stats['sectors_erased'] += 1
                # Erase wipes entire sector; must reprogram ALL non-erased
                # pages, including those previously identical to current state
                to_program = {**sec_changed, **sec_identical}
            else:
                stats['sectors_skipped'] += 1
                to_program = sec_changed

            for ps in sorted(to_program.keys()):
                pd = to_program[ps]
                prog_ops.append({
                    'type': 'program',
                    'region': rname,
                    'address': ps,
                    'size': page_size,
                })
                stats['total_program_size'] += page_size
                stats['pages_programmed'] += 1

                # Count bytes that differ between original current and desired
                state_off = ps - rstart
                cur_page = cur_state[state_off:state_off + page_size]
                stats['bytes_changed'] += sum(
                    1 for c, d in zip(cur_page, pd) if c != d)

                # Count fill bytes (padding added to partially-filled pages)
                fw_byte_count = sum(
                    1 for a in rfirmware if ps <= a < ps + page_size)
                stats['fill_bytes'] += page_size - fw_byte_count

    # Sort operations: erases by (region, address), then programs likewise
    erase_ops.sort(key=lambda o: (o['region'], o['address']))
    prog_ops.sort(key=lambda o: (o['region'], o['address']))
    operations = erase_ops + prog_ops

    stats['regions_used'] = sorted(stats['regions_used'])

    result = {
        'target': family,
        'variant': args.variant,
        'operations': operations,
        'statistics': stats,
    }

    with open(args.output, 'w') as f:
        json.dump(result, f, indent=2)


if __name__ == '__main__':
    main()
