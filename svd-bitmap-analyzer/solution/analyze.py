#!/usr/bin/env python3
"""
SVD Register Bitmap Analyzer

Parses a CMSIS-SVD XML file and computes:
1. Modified Write Value (MWV) bitmaps per writable register
2. Overlapping register regions per peripheral
3. Field write safety classification
"""

import copy
import json
import xml.etree.ElementTree as ET
from collections import defaultdict


def parse_int(s):
    """Parse an integer from SVD text (handles 0x hex and decimal)."""
    if s is None:
        return None
    s = s.strip().lower()
    if s.startswith("0x"):
        return int(s, 16)
    if s.startswith("#"):
        # Binary literal
        return int(s[1:], 2)
    return int(s)


def get_text(elem, tag, default=None):
    """Get text of a direct child element."""
    child = elem.find(tag)
    if child is not None and child.text is not None:
        return child.text.strip()
    return default


def get_int(elem, tag, default=None):
    """Get integer value of a direct child element."""
    text = get_text(elem, tag)
    if text is not None:
        return parse_int(text)
    return default


def parse_fields(register_elem):
    """Extract field definitions from a <register> element."""
    fields = []
    fields_elem = register_elem.find("fields")
    if fields_elem is None:
        return fields

    for field_elem in fields_elem.findall("field"):
        field = {
            "name": get_text(field_elem, "name"),
            "bit_offset": get_int(field_elem, "bitOffset"),
            "bit_width": get_int(field_elem, "bitWidth"),
            "modified_write_values": get_text(field_elem, "modifiedWriteValues"),
            "write_constraint": None,
            "dim": get_int(field_elem, "dim"),
            "dim_increment": get_int(field_elem, "dimIncrement"),
            "enum_value_count": 0,
        }

        # Parse writeConstraint -> range
        wc = field_elem.find("writeConstraint")
        if wc is not None:
            range_elem = wc.find("range")
            if range_elem is not None:
                field["write_constraint"] = (
                    get_int(range_elem, "minimum"),
                    get_int(range_elem, "maximum"),
                )

        # Count non-reserved, non-default enumerated values
        for evs_elem in field_elem.findall("enumeratedValues"):
            for ev_elem in evs_elem.findall("enumeratedValue"):
                is_default = get_text(ev_elem, "isDefault", "")
                if is_default.lower() == "true":
                    continue
                name = get_text(ev_elem, "name", "")
                if name.lower() == "reserved":
                    continue
                field["enum_value_count"] += 1

        fields.append(field)

    return fields


def compute_field_bitmask(bit_offset, bit_width, dim=None, dim_increment=None):
    """Compute the bitmask for a field (or field array).

    For field arrays, returns the union of all expanded element bitmasks.
    """
    single_mask = ((1 << bit_width) - 1) << bit_offset
    if dim is None or dim <= 1 or dim_increment is None:
        return single_mask
    total = 0
    for i in range(dim):
        total |= ((1 << bit_width) - 1) << (bit_offset + i * dim_increment)
    return total


def compute_bitmaps(fields, register_mwv):
    """Compute zero_to_modify and one_to_modify bitmaps for a register.

    Algorithm (matching svd2rust):
    - Effective MWV = field.mwv ?? register.mwv ?? 'modify'
    - modify/set/clear -> no bitmap contribution
    - oneToSet/oneToClear/oneToToggle -> one_to_modify |= bitmask
    - zeroToClear/zeroToSet/zeroToToggle -> zero_to_modify |= bitmask
    """
    zero_bm = 0
    one_bm = 0

    for field in fields:
        mwv = field["modified_write_values"] or register_mwv or "modify"
        bitmask = compute_field_bitmask(
            field["bit_offset"],
            field["bit_width"],
            field["dim"],
            field["dim_increment"],
        )

        if mwv in ("modify", "set", "clear"):
            pass
        elif mwv in ("oneToSet", "oneToClear", "oneToToggle"):
            one_bm |= bitmask
        elif mwv in ("zeroToClear", "zeroToSet", "zeroToToggle"):
            zero_bm |= bitmask

    return zero_bm, one_bm


def classify_field_safety(field):
    """Classify write safety for a single field definition.

    Rules (matching svd2rust Safety::get + enum upgrade):
    1. writeConstraint covering full [0, 2^w-1] -> safe
    2. writeConstraint partial range -> range(min,max)
    3. 1-bit field, no writeConstraint -> safe
    4. enum values covering all 2^w possibilities -> safe
    5. otherwise -> unsafe
    """
    width = field["bit_width"]
    max_val = (1 << width) - 1

    wc = field["write_constraint"]
    if wc is not None:
        wc_min, wc_max = wc
        if wc_min == 0 and wc_max == max_val:
            return "safe"
        return f"range({wc_min},{wc_max})"

    if width == 1:
        return "safe"

    # Check if enumerated values fully cover the field width
    if field["enum_value_count"] >= (1 << width):
        return "safe"

    return "unsafe"


def parse_registers(peripheral_elem):
    """Parse and expand all registers from a peripheral element.

    Register arrays (dim > 1) are expanded into individual registers.
    """
    registers = []
    regs_elem = peripheral_elem.find("registers")
    if regs_elem is None:
        return registers

    for reg_elem in regs_elem.findall("register"):
        name = get_text(reg_elem, "name")
        offset = get_int(reg_elem, "addressOffset")
        size = get_int(reg_elem, "size", 32)
        access = get_text(reg_elem, "access", "read-write")
        reg_mwv = get_text(reg_elem, "modifiedWriteValues")
        dim = get_int(reg_elem, "dim")
        dim_increment = get_int(reg_elem, "dimIncrement")
        dim_index_text = get_text(reg_elem, "dimIndex")

        fields = parse_fields(reg_elem)

        if dim is not None and dim > 1:
            # Expand register array
            if dim_index_text:
                indices = [idx.strip() for idx in dim_index_text.split(",")]
            else:
                indices = [str(i) for i in range(dim)]

            for i, idx in enumerate(indices):
                expanded_name = name.replace("%s", idx)
                expanded_offset = offset + i * dim_increment
                registers.append(
                    {
                        "name": expanded_name,
                        "template_name": name,
                        "offset": expanded_offset,
                        "size": size,
                        "access": access,
                        "register_mwv": reg_mwv,
                        "fields": fields,
                        "is_array_element": True,
                    }
                )
        else:
            registers.append(
                {
                    "name": name,
                    "template_name": name,
                    "offset": offset,
                    "size": size,
                    "access": access,
                    "register_mwv": reg_mwv,
                    "fields": fields,
                    "is_array_element": False,
                }
            )

    return registers


def detect_overlaps(registers):
    """Detect groups of registers with overlapping byte ranges.

    Returns list of {offset, registers} dicts for each overlap group.
    """
    overlaps = defaultdict(set)

    for i, r1 in enumerate(registers):
        for j, r2 in enumerate(registers):
            if i >= j:
                continue
            start1 = r1["offset"]
            end1 = start1 + r1["size"] // 8
            start2 = r2["offset"]
            end2 = start2 + r2["size"] // 8

            if start1 < end2 and start2 < end1:
                overlap_offset = max(start1, start2)
                overlaps[overlap_offset].add(r1["name"])
                overlaps[overlap_offset].add(r2["name"])

    result = []
    for off in sorted(overlaps.keys()):
        result.append({"offset": off, "registers": sorted(overlaps[off])})
    return result


def analyze_svd(svd_path):
    """Main analysis: parse SVD and compute all three analyses."""
    tree = ET.parse(svd_path)
    root = tree.getroot()

    # First pass: collect peripheral register data and derivedFrom relations
    peripheral_data = {}
    derived_peripherals = {}

    for periph_elem in root.findall(".//peripheral"):
        name = get_text(periph_elem, "name")
        derived_from = periph_elem.get("derivedFrom")

        if derived_from:
            derived_peripherals[name] = derived_from
            # A derived peripheral may also have its own registers (overrides)
            regs = parse_registers(periph_elem)
            if regs:
                peripheral_data[name] = regs
        else:
            registers = parse_registers(periph_elem)
            peripheral_data[name] = registers

    # Resolve derivedFrom: copy registers from base if not overridden
    for derived_name, base_name in derived_peripherals.items():
        if derived_name not in peripheral_data and base_name in peripheral_data:
            peripheral_data[derived_name] = copy.deepcopy(
                peripheral_data[base_name]
            )

    # Build result
    result = {"bitmaps": {}, "overlaps": {}, "field_safety": {}}

    for periph_name in sorted(peripheral_data.keys()):
        registers = peripheral_data[periph_name]
        result["bitmaps"][periph_name] = {}

        # Track which template fields we've already recorded safety for
        seen_safety_keys = set()

        for reg in registers:
            access = reg["access"]
            is_writable = access in ("read-write", "write-only")

            if is_writable and reg["fields"]:
                # Compute bitmaps
                zero_bm, one_bm = compute_bitmaps(
                    reg["fields"], reg["register_mwv"]
                )
                result["bitmaps"][periph_name][reg["name"]] = {
                    "zero_to_modify": f"0x{zero_bm:08x}",
                    "one_to_modify": f"0x{one_bm:08x}",
                }

                # Field safety: use template register name for array elements
                reg_key = (
                    reg["template_name"]
                    if reg["is_array_element"]
                    else reg["name"]
                )

                for field in reg["fields"]:
                    safety_key = f"{periph_name}.{reg_key}.{field['name']}"
                    if safety_key not in seen_safety_keys:
                        seen_safety_keys.add(safety_key)
                        result["field_safety"][safety_key] = (
                            classify_field_safety(field)
                        )

            elif is_writable and not reg["fields"]:
                # Writable register with no fields: bitmaps are 0
                result["bitmaps"][periph_name][reg["name"]] = {
                    "zero_to_modify": "0x00000000",
                    "one_to_modify": "0x00000000",
                }

        # Detect overlapping regions
        result["overlaps"][periph_name] = detect_overlaps(registers)

    return result


def main():
    result = analyze_svd("/app/device.svd")
    with open("/app/analysis.json", "w") as f:
        json.dump(result, f, indent=2)
    print("Analysis complete. Output written to /app/analysis.json")


if __name__ == "__main__":
    main()
