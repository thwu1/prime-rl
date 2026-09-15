
"""
KASAN shadow memory decoder.
Decodes shadow byte values and reconstructs object boundaries
from kernel KASAN shadow memory state.
"""


# Shadow byte encoding from Linux kernel KASAN implementation
_SHADOW_MEANINGS = {
    0xf1: 'left_alloca_redzone',
    0xf2: 'mid_alloca_redzone',
    0xf3: 'right_alloca_redzone',
    0xf5: 'stack_use_after_return',
    0xf8: 'stack_use_after_scope',
    0xfa: 'freed',
    0xfb: 'page_padding',
    0xfc: 'redzone',
    0xfd: 'internal_padding',
    0xfe: 'left_redzone',
    0xff: 'shadow_gap',
}


def decode_shadow_byte(value):
    """
    Decode a single KASAN shadow byte.

    Returns:
        dict with keys:
            value: int - original byte value
            accessible_bytes: int - number of accessible bytes (0-8)
            meaning: str - human-readable meaning
            is_poisoned: bool - True if any bytes are inaccessible
    """
    value = value & 0xFF

    if value == 0x00:
        return {
            'value': value,
            'accessible_bytes': 8,
            'meaning': 'accessible',
            'is_poisoned': False,
        }

    if 0x01 <= value <= 0x07:
        return {
            'value': value,
            'accessible_bytes': value,
            'meaning': 'partially_accessible',
            'is_poisoned': True,
        }

    meaning = _SHADOW_MEANINGS.get(value, 'unknown_poison')
    return {
        'value': value,
        'accessible_bytes': 0,
        'meaning': meaning,
        'is_poisoned': True,
    }


def decode_shadow_line(base_addr, values):
    """
    Decode a complete shadow memory line.

    Args:
        base_addr: int - real memory address at the start of this line
        values: list[int] - shadow byte values (typically 16)

    Returns:
        list of dicts, one per shadow byte, each with:
            real_addr_start, real_addr_end, shadow_byte,
            accessible_bytes, meaning
    """
    result = []
    for i, val in enumerate(values):
        decoded = decode_shadow_byte(val)
        entry = {
            'real_addr_start': base_addr + i * 8,
            'real_addr_end': base_addr + (i + 1) * 8,
            'shadow_byte': val,
            'accessible_bytes': decoded['accessible_bytes'],
            'meaning': decoded['meaning'],
        }
        result.append(entry)
    return result


def find_object_bounds(shadow_data, buggy_addr):
    """
    Reconstruct object boundaries from shadow memory context.

    Args:
        shadow_data: list of dicts [{"addr": int, "values": [int, ...]}]
            Each dict represents one shadow dump line.
        buggy_addr: int - the address that caused the crash

    Returns:
        dict with keys:
            object_start: int
            object_size: int
            is_freed: bool
            oob_distance: int (bytes past object end; 0 if within or freed)
    """
    # Build flat map: aligned_real_addr -> shadow_byte
    shadow_map = {}
    all_addrs = []
    for line in shadow_data:
        base = line['addr']
        for i, val in enumerate(line['values']):
            real_addr = base + i * 8
            shadow_map[real_addr] = val
            all_addrs.append(real_addr)

    all_addrs.sort()

    # Find shadow byte covering buggy_addr
    aligned = (buggy_addr // 8) * 8
    buggy_shadow = shadow_map.get(aligned)

    if buggy_shadow is None:
        return None

    result = {
        'object_start': 0,
        'object_size': 0,
        'is_freed': False,
        'oob_distance': 0,
    }

    if buggy_shadow == 0xfa:
        # Use-after-free: the object region is marked as freed
        result['is_freed'] = True

        # Walk backward to find start of freed region
        addr = aligned
        while (addr - 8) in shadow_map and shadow_map[addr - 8] == 0xfa:
            addr -= 8
        result['object_start'] = addr

        # Walk forward to find end of freed region
        addr = aligned
        while (addr + 8) in shadow_map and shadow_map[addr + 8] == 0xfa:
            addr += 8
        result['object_size'] = (addr + 8) - result['object_start']
        result['oob_distance'] = 0

    elif buggy_shadow == 0xfc or buggy_shadow == 0xfe:
        # Out-of-bounds: access is in redzone
        # Walk backward through redzone to find end of preceding object
        addr = aligned
        while (addr - 8) in shadow_map and shadow_map[addr - 8] in (0xfc, 0xfe):
            addr -= 8
        object_end_addr = addr  # first redzone byte = byte just past object

        # Walk backward through accessible region to find object
        addr = object_end_addr - 8
        accessible = []
        while addr in shadow_map:
            sv = shadow_map[addr]
            if sv == 0x00 or (0x01 <= sv <= 0x07):
                accessible.insert(0, (addr, sv))
                addr -= 8
            else:
                break

        if accessible:
            result['object_start'] = accessible[0][0]
            size = 0
            for a, sv in accessible:
                size += (8 if sv == 0x00 else sv)
            result['object_size'] = size
        else:
            result['object_start'] = object_end_addr
            result['object_size'] = 0

        obj_end = result['object_start'] + result['object_size']
        result['oob_distance'] = buggy_addr - obj_end

    elif 0x00 <= buggy_shadow <= 0x07:
        # Access within object (might be partial OOB within last granule)
        # Walk backward to find object start
        addr = aligned
        while (addr - 8) in shadow_map and (
            shadow_map[addr - 8] == 0x00 or
            (0x01 <= shadow_map[addr - 8] <= 0x07)
        ):
            addr -= 8
        result['object_start'] = addr

        # Walk forward through accessible region
        addr = aligned
        while (addr + 8) in shadow_map and (
            shadow_map[addr + 8] == 0x00 or
            (0x01 <= shadow_map[addr + 8] <= 0x07)
        ):
            addr += 8

        # Calculate total size
        size = 0
        a = result['object_start']
        while a in shadow_map and (
            shadow_map[a] == 0x00 or (0x01 <= shadow_map[a] <= 0x07)
        ):
            sv = shadow_map[a]
            size += (8 if sv == 0x00 else sv)
            a += 8

        result['object_size'] = size
        result['oob_distance'] = 0

    return result
