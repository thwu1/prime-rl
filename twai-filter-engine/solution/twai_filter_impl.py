#!/usr/bin/env python3

"""
ESP32 TWAI CAN Bus Acceptance Filter Engine.

Implements the hardware acceptance filter logic used by the ESP32 TWAI controller.
Supports all four filter modes: SingleStandard, SingleExtended, DualStandard, DualExtended.

Register format: 8 bytes = [code_3, code_2, code_1, code_0, mask_3, mask_2, mask_1, mask_0]
  code: 32-bit big-endian acceptance code
  mask: 32-bit big-endian acceptance mask (REGISTER polarity: set bit = DON'T CARE)

Matching rule: frame_bit matches if register_mask_bit == 1 (don't care) OR frame_bit == code_bit.
Equivalently: ((frame_bits ^ code) & ~register_mask) == 0
"""

import sys
import json
import struct
import itertools


def parse_reg_hex(reg_hex: str) -> tuple:
    """Parse 16-char hex into (code: int, reg_mask: int) both as 32-bit values."""
    reg_hex = reg_hex.replace(" ", "").lower()
    assert len(reg_hex) == 16, f"Expected 16 hex chars, got {len(reg_hex)}: {reg_hex}"
    raw = bytes.fromhex(reg_hex)
    code = int.from_bytes(raw[0:4], 'big')
    reg_mask = int.from_bytes(raw[4:8], 'big')
    return code, reg_mask


def regs_to_hex(code: int, reg_mask: int) -> str:
    """Convert code and register mask to 16-char hex string."""
    code_bytes = code.to_bytes(4, 'big')
    mask_bytes = reg_mask.to_bytes(4, 'big')
    return (code_bytes + mask_bytes).hex()


def parse_frame(frame_spec: str) -> dict:
    """Parse frame spec: <std|ext>:<id_hex>:<rtr 0|1>:<payload_hex>"""
    parts = frame_spec.split(":")
    assert len(parts) == 4, f"Frame spec must have 4 colon-separated parts: {frame_spec}"
    frame_type = parts[0]
    frame_id = int(parts[1], 16)
    rtr = int(parts[2])
    payload_hex = parts[3]
    payload = bytes.fromhex(payload_hex) if payload_hex else b""
    return {
        "type": frame_type,
        "id": frame_id,
        "rtr": rtr,
        "payload": payload,
    }


def bits_match(frame_bits: int, code: int, reg_mask: int) -> bool:
    """Check if frame_bits match against code using register-level mask.
    Register mask: set bit = don't care.
    Match condition: ((frame_bits ^ code) & ~reg_mask) == 0
    """
    return ((frame_bits ^ code) & (~reg_mask & 0xFFFFFFFF)) == 0


# =============================================================================
# MATCHING
# =============================================================================

def match_single_standard(code: int, reg_mask: int, frame: dict) -> bool:
    """SingleStandard: ID at bits 31-21, RTR at bit 20, payload[0] at bits 15-8, payload[1] at bits 7-0."""
    std_id = frame["id"] & 0x7FF
    rtr = frame["rtr"]
    payload = frame["payload"]
    # Pad payload to 2 bytes
    p = bytearray(2)
    for i in range(min(len(payload), 2)):
        p[i] = payload[i]

    frame_bits = (std_id << 21) | (rtr << 20) | (p[0] << 8) | p[1]
    return bits_match(frame_bits, code, reg_mask)


def match_single_extended(code: int, reg_mask: int, frame: dict) -> bool:
    """SingleExtended: ID at bits 31-3, RTR at bit 2."""
    ext_id = frame["id"] & 0x1FFFFFFF
    rtr = frame["rtr"]
    frame_bits = (ext_id << 3) | (rtr << 2)
    return bits_match(frame_bits, code, reg_mask)


def match_dual_standard(code: int, reg_mask: int, frame: dict) -> bool:
    """DualStandard: Two filters, frame accepted if either matches.
    Filter 1: ID at bits 31-21, RTR at bit 20, payload upper nibble at bits 19-16, lower nibble at bits 3-0
    Filter 2: ID at bits 15-5, RTR at bit 4
    """
    std_id = frame["id"] & 0x7FF
    rtr = frame["rtr"]
    payload = frame["payload"]
    p0 = payload[0] if len(payload) > 0 else 0

    # Filter 1: pack frame into bits 31-16 and 3-0
    f1_frame = (std_id << 21) | (rtr << 20) | ((p0 >> 4) << 16) | (p0 & 0x0F)
    # Filter 1 mask: bits 31-16 and 3-0
    f1_relevant = 0xFFF0000F
    f1_code = code & f1_relevant
    f1_reg_mask = reg_mask | (~f1_relevant & 0xFFFFFFFF)  # don't care about bits not in filter 1
    f1_match = bits_match(f1_frame, f1_code, f1_reg_mask)

    # Filter 2: pack frame into bits 15-4
    f2_frame = (std_id << 5) | (rtr << 4)
    f2_relevant = 0x0000FFF0
    f2_code = code & f2_relevant
    f2_reg_mask = reg_mask | (~f2_relevant & 0xFFFFFFFF)
    f2_match = bits_match(f2_frame, f2_code, f2_reg_mask)

    return f1_match or f2_match


def match_dual_extended(code: int, reg_mask: int, frame: dict) -> bool:
    """DualExtended: Two filters, each matching upper 16 bits of (ID<<3).
    Filter 1: register bits 31-16
    Filter 2: register bits 15-0
    """
    ext_id = frame["id"] & 0x1FFFFFFF
    shifted = ext_id << 3
    upper_16 = (shifted >> 16) & 0xFFFF

    # Filter 1: compare upper_16 against code bits 31-16
    f1_code = (code >> 16) & 0xFFFF
    f1_reg_mask = (reg_mask >> 16) & 0xFFFF
    f1_match = ((upper_16 ^ f1_code) & (~f1_reg_mask & 0xFFFF)) == 0

    # Filter 2: compare upper_16 against code bits 15-0
    f2_code = code & 0xFFFF
    f2_reg_mask = reg_mask & 0xFFFF
    f2_match = ((upper_16 ^ f2_code) & (~f2_reg_mask & 0xFFFF)) == 0

    return f1_match or f2_match


MATCH_FUNCS = {
    "single_standard": match_single_standard,
    "single_extended": match_single_extended,
    "dual_standard": match_dual_standard,
    "dual_extended": match_dual_extended,
}


# =============================================================================
# SYNTHESIS
# =============================================================================

def logical_to_register(code: int, logical_mask: int) -> tuple:
    """Convert logical code+mask to register format. Logical mask: set bit = care.
    Register mask: set bit = don't care. So register_mask = ~logical_mask."""
    reg_mask = (~logical_mask) & 0xFFFFFFFF
    return code, reg_mask


def compute_tightest_single(bit_patterns: list, num_bits: int = 32) -> tuple:
    """Given a list of frame bit patterns (ints), compute the tightest code/register_mask.

    For each bit position: if all patterns agree, set code to that value and care (reg_mask=0).
    If patterns disagree, set don't care (reg_mask=1). Code bit is 0 for don't-care positions.

    Returns (code, reg_mask).
    """
    if not bit_patterns:
        return 0, 0xFFFFFFFF

    # Start with first pattern as code
    agree_mask = 0xFFFFFFFF  # bits where all patterns agree
    base = bit_patterns[0]
    for p in bit_patterns[1:]:
        diff = base ^ p
        agree_mask &= ~diff

    # Code: use base value for agreed bits, 0 for disagreed bits
    code = base & agree_mask
    # Register mask: set bit = don't care = where patterns disagree
    reg_mask = (~agree_mask) & 0xFFFFFFFF
    return code, reg_mask


def frame_to_ss_bits(frame: dict) -> int:
    """Convert frame to SingleStandard bit pattern."""
    std_id = frame["id"] & 0x7FF
    rtr = frame["rtr"]
    payload = frame["payload"]
    p = bytearray(2)
    for i in range(min(len(payload), 2)):
        p[i] = payload[i]
    return (std_id << 21) | (rtr << 20) | (p[0] << 8) | p[1]


def frame_to_se_bits(frame: dict) -> int:
    """Convert frame to SingleExtended bit pattern."""
    ext_id = frame["id"] & 0x1FFFFFFF
    rtr = frame["rtr"]
    return (ext_id << 3) | (rtr << 2)


def frame_to_ds_f1_bits(frame: dict) -> int:
    """Convert frame to DualStandard filter 1 bit pattern (bits 31-16 and 3-0)."""
    std_id = frame["id"] & 0x7FF
    rtr = frame["rtr"]
    payload = frame["payload"]
    p0 = payload[0] if len(payload) > 0 else 0
    return (std_id << 21) | (rtr << 20) | ((p0 >> 4) << 16) | (p0 & 0x0F)


def frame_to_ds_f2_bits(frame: dict) -> int:
    """Convert frame to DualStandard filter 2 bit pattern (bits 15-4)."""
    std_id = frame["id"] & 0x7FF
    rtr = frame["rtr"]
    return (std_id << 5) | (rtr << 4)


def frame_to_de_upper16(frame: dict) -> int:
    """Convert frame to DualExtended upper 16 bits of (ID<<3)."""
    ext_id = frame["id"] & 0x1FFFFFFF
    shifted = ext_id << 3
    return (shifted >> 16) & 0xFFFF


def count_dont_care(reg_mask: int, num_bits: int = 32) -> int:
    """Count number of don't care bits in register mask."""
    count = 0
    for i in range(num_bits):
        if reg_mask & (1 << i):
            count += 1
    return count


def synthesize_single_standard(frames: list) -> str:
    """Synthesize tightest SingleStandard filter for given frames."""
    patterns = [frame_to_ss_bits(f) for f in frames]
    code, reg_mask = compute_tightest_single(patterns)
    return regs_to_hex(code, reg_mask)


def synthesize_single_extended(frames: list) -> str:
    """Synthesize tightest SingleExtended filter for given frames."""
    patterns = [frame_to_se_bits(f) for f in frames]
    code, reg_mask = compute_tightest_single(patterns)
    return regs_to_hex(code, reg_mask)


def synthesize_dual_standard(frames: list) -> str:
    """Synthesize tightest DualStandard filter.

    Partition frames between filter 1 and filter 2 to minimize total don't-care bits.
    Filter 1 uses bits 31-16 and 3-0 (ID + RTR + split payload byte).
    Filter 2 uses bits 15-4 (ID + RTR only).
    """
    if len(frames) == 1:
        # Single frame: assign to filter 1, make filter 2 reject everything
        f1_bits = frame_to_ds_f1_bits(frames[0])
        f2_bits = frame_to_ds_f2_bits(frames[0])
        # Filter 1: exact match
        f1_relevant = 0xFFF0000F
        f1_code = f1_bits & f1_relevant
        f1_reg_mask = 0  # care about everything in filter 1's domain
        # Filter 2: also exact match for the same frame
        f2_relevant = 0x0000FFF0
        f2_code = f2_bits & f2_relevant
        f2_reg_mask = 0
        code = f1_code | f2_code
        reg_mask = f1_reg_mask | f2_reg_mask
        return regs_to_hex(code, reg_mask)

    # Try all 2-partitions (each frame assigned to filter 1 or 2)
    # For n frames, there are 2^n - 2 non-trivial partitions (exclude all-in-one)
    best_code = 0
    best_reg_mask = 0xFFFFFFFF
    best_dc_count = 999

    n = len(frames)
    # Try all partitions from 1 to 2^n - 2
    for partition in range(1, 2**n):
        group1 = [frames[i] for i in range(n) if partition & (1 << i)]
        group2 = [frames[i] for i in range(n) if not (partition & (1 << i))]

        # Filter 1 bits
        f1_patterns = [frame_to_ds_f1_bits(f) & 0xFFF0000F for f in group1]
        if f1_patterns:
            f1_agree = 0xFFFFFFFF
            f1_base = f1_patterns[0]
            for p in f1_patterns[1:]:
                f1_agree &= ~(f1_base ^ p)
            f1_agree &= 0xFFF0000F
            f1_code = f1_base & f1_agree
            f1_dc = (~f1_agree) & 0xFFF0000F
        else:
            f1_code = 0
            f1_dc = 0  # No frames → exact match on 0 (will reject most)

        # Filter 2 bits
        f2_patterns = [frame_to_ds_f2_bits(f) & 0x0000FFF0 for f in group2]
        if f2_patterns:
            f2_agree = 0xFFFFFFFF
            f2_base = f2_patterns[0]
            for p in f2_patterns[1:]:
                f2_agree &= ~(f2_base ^ p)
            f2_agree &= 0x0000FFF0
            f2_code = f2_base & f2_agree
            f2_dc = (~f2_agree) & 0x0000FFF0
        else:
            f2_code = 0
            f2_dc = 0

        code = f1_code | f2_code
        reg_mask = f1_dc | f2_dc
        # For non-relevant bits, set don't care
        # Bits 20 is shared... actually bits not belonging to either filter are don't care
        non_relevant = ~(0xFFF0000F | 0x0000FFF0) & 0xFFFFFFFF
        reg_mask |= non_relevant

        dc_count = count_dont_care(reg_mask)
        if dc_count < best_dc_count:
            best_dc_count = dc_count
            best_code = code
            best_reg_mask = reg_mask

    return regs_to_hex(best_code, best_reg_mask)


def synthesize_dual_extended(frames: list) -> str:
    """Synthesize tightest DualExtended filter.

    Each filter matches upper 16 bits of (ID<<3).
    Partition frames between the two 16-bit filters to minimize don't-care bits.
    """
    if len(frames) == 1:
        upper = frame_to_de_upper16(frames[0])
        code = (upper << 16) | upper
        reg_mask = 0  # care about all bits in both filters
        return regs_to_hex(code, reg_mask)

    n = len(frames)
    best_code = 0
    best_reg_mask = 0xFFFFFFFF
    best_dc_count = 999

    limit = 2**n if n <= 20 else None

    if limit:
        for partition in range(1, limit):
            group1 = [frames[i] for i in range(n) if partition & (1 << i)]
            group2 = [frames[i] for i in range(n) if not (partition & (1 << i))]

            g1_uppers = [frame_to_de_upper16(f) for f in group1]
            if g1_uppers:
                agree1 = 0xFFFF
                base1 = g1_uppers[0]
                for u in g1_uppers[1:]:
                    agree1 &= ~(base1 ^ u) & 0xFFFF
                code1 = base1 & agree1
                dc1 = (~agree1) & 0xFFFF
            else:
                code1 = 0
                dc1 = 0

            g2_uppers = [frame_to_de_upper16(f) for f in group2]
            if g2_uppers:
                agree2 = 0xFFFF
                base2 = g2_uppers[0]
                for u in g2_uppers[1:]:
                    agree2 &= ~(base2 ^ u) & 0xFFFF
                code2 = base2 & agree2
                dc2 = (~agree2) & 0xFFFF
            else:
                code2 = 0
                dc2 = 0

            code = (code1 << 16) | code2
            reg_mask = (dc1 << 16) | dc2
            dc_count = count_dont_care(reg_mask)
            if dc_count < best_dc_count:
                best_dc_count = dc_count
                best_code = code
                best_reg_mask = reg_mask
    else:
        # Greedy heuristic for large numbers of frames
        all_uppers = [frame_to_de_upper16(f) for f in frames]
        # Start with first two as seeds
        group1 = [all_uppers[0]]
        group2 = [all_uppers[1]] if len(all_uppers) > 1 else []
        for u in all_uppers[2:]:
            # Try adding to group1
            dc1_with = count_dc_for_group(group1 + [u])
            dc2_with = count_dc_for_group(group2 + [u])
            dc1_without = count_dc_for_group(group1)
            dc2_without = count_dc_for_group(group2)
            if (dc1_with - dc1_without) <= (dc2_with - dc2_without):
                group1.append(u)
            else:
                group2.append(u)

        agree1 = 0xFFFF
        base1 = group1[0]
        for u in group1[1:]:
            agree1 &= ~(base1 ^ u) & 0xFFFF
        code1 = base1 & agree1
        dc1 = (~agree1) & 0xFFFF

        if group2:
            agree2 = 0xFFFF
            base2 = group2[0]
            for u in group2[1:]:
                agree2 &= ~(base2 ^ u) & 0xFFFF
            code2 = base2 & agree2
            dc2 = (~agree2) & 0xFFFF
        else:
            code2 = 0
            dc2 = 0

        best_code = (code1 << 16) | code2
        best_reg_mask = (dc1 << 16) | dc2

    return regs_to_hex(best_code, best_reg_mask)


def count_dc_for_group(uppers):
    """Count don't-care bits for a group of upper-16 values."""
    if not uppers:
        return 0
    agree = 0xFFFF
    base = uppers[0]
    for u in uppers[1:]:
        agree &= ~(base ^ u) & 0xFFFF
    return 16 - bin(agree).count('1')


SYNTH_FUNCS = {
    "single_standard": synthesize_single_standard,
    "single_extended": synthesize_single_extended,
    "dual_standard": synthesize_dual_standard,
    "dual_extended": synthesize_dual_extended,
}


# =============================================================================
# BINARY DUMP PARSING
# =============================================================================

MODE_NAMES = {
    0: "single_standard",
    1: "single_extended",
    2: "dual_standard",
    3: "dual_extended",
}


def parse_dump(file_path: str) -> str:
    """Parse a binary register dump file and return JSON string."""
    with open(file_path, "rb") as f:
        magic = f.read(4)
        if magic != b"TWAI":
            print(f"Invalid magic: {magic}", file=sys.stderr)
            sys.exit(1)
        count = struct.unpack("<H", f.read(2))[0]

        entries = []
        for _ in range(count):
            mode_byte = struct.unpack("B", f.read(1))[0]
            reg_data = f.read(8)
            label_len = struct.unpack("B", f.read(1))[0]
            label = f.read(label_len).decode("ascii")

            entries.append({
                "mode": MODE_NAMES[mode_byte],
                "reg_hex": reg_data.hex(),
                "label": label,
            })

    return json.dumps(entries)


# =============================================================================
# CLI
# =============================================================================

def main():
    if len(sys.argv) < 2:
        print("Usage:", file=sys.stderr)
        print("  twai_filter.py match <mode> <reg_hex> <frame_spec>", file=sys.stderr)
        print("  twai_filter.py synthesize <mode> <frame_spec> [<frame_spec> ...]", file=sys.stderr)
        print("  twai_filter.py parse-dump <file_path>", file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]

    if command == "match":
        if len(sys.argv) != 5:
            print("Usage: twai_filter.py match <mode> <reg_hex> <frame_spec>", file=sys.stderr)
            sys.exit(1)
        mode = sys.argv[2]
        reg_hex = sys.argv[3]
        frame_spec = sys.argv[4]

        code, reg_mask = parse_reg_hex(reg_hex)
        frame = parse_frame(frame_spec)

        match_func = MATCH_FUNCS.get(mode)
        if not match_func:
            print(f"Unknown mode: {mode}", file=sys.stderr)
            sys.exit(1)

        result = match_func(code, reg_mask, frame)
        print("ACCEPT" if result else "REJECT")

    elif command == "synthesize":
        if len(sys.argv) < 4:
            print("Usage: twai_filter.py synthesize <mode> <frame_spec> [...]", file=sys.stderr)
            sys.exit(1)
        mode = sys.argv[2]
        frame_specs = sys.argv[3:]
        frames = [parse_frame(fs) for fs in frame_specs]

        synth_func = SYNTH_FUNCS.get(mode)
        if not synth_func:
            print(f"Unknown mode: {mode}", file=sys.stderr)
            sys.exit(1)

        result = synth_func(frames)
        print(result)

    elif command == "parse-dump":
        if len(sys.argv) != 3:
            print("Usage: twai_filter.py parse-dump <file_path>", file=sys.stderr)
            sys.exit(1)
        file_path = sys.argv[2]
        result = parse_dump(file_path)
        print(result)

    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
