#!/usr/bin/env python3
"""

Solve the firmware analysis task by:
1. Implementing the spec algorithm (from /app/spec.md)
2. Implementing the firmware's actual algorithm (reverse-engineered)
3. Computing both outputs
4. Identifying deviations
5. Writing /app/analysis.json
"""

import struct
import json


def xorshift32(state):
    state ^= (state << 13) & 0xFFFFFFFF
    state ^= state >> 17
    state ^= (state << 5) & 0xFFFFFFFF
    return state & 0xFFFFFFFF


def rotl32(v, n):
    return ((v << n) | (v >> (32 - n))) & 0xFFFFFFFF


def make_sipround(rot_b):
    """Create a sipround function with the given second rotation constant."""
    def sipround(v):
        v[0] = (v[0] + v[1]) & 0xFFFFFFFF
        v[1] = rotl32(v[1], 5) ^ v[0]
        v[2] = (v[2] + v[3]) & 0xFFFFFFFF
        v[3] = rotl32(v[3], rot_b) ^ v[2]
        v[0] = rotl32(v[0], 16)
        v[0] = (v[0] + v[3]) & 0xFFFFFFFF
        v[2] = (v[2] + v[1]) & 0xFFFFFFFF
        v[1] = rotl32(v[1], 13) ^ v[2]
        v[3] = rotl32(v[3], 7) ^ v[0]
        v[2] = rotl32(v[2], 16)
    return sipround


def compute_hash(sipround_fn, absorb_count, finalize_count):
    """Compute the MixHash output with given parameters."""
    state = 0xDEADBEEF
    v = [0x736F6D65, 0x646F7261, 0x6C796765, 0x74656462]

    for _ in range(absorb_count):
        state = xorshift32(state)
        v[3] ^= state
        sipround_fn(v)
        sipround_fn(v)
        v[0] ^= state

    v[2] ^= 0xFF
    for _ in range(finalize_count):
        sipround_fn(v)

    return b"".join(struct.pack("<I", x) for x in v).hex()


def main():
    # === Spec algorithm (from /app/spec.md) ===
    # Rotation constants: 5, 11, 16, 13, 7, 16
    # Absorption iterations: 24
    # Finalization rounds: 3
    spec_sipround = make_sipround(11)
    spec_output = compute_hash(spec_sipround, 24, 3)

    # === Firmware algorithm (reverse-engineered from disassembly) ===
    # By disassembling with arm-none-eabi-objdump -d /app/firmware.elf:
    #
    # The xorshift32 function uses shifts 13, 17, 5 (same as spec).
    #
    # The sipround function's rotation constants are found from
    # LSL/LSR instruction immediate operands:
    #   - v[1] rotation: LSL #5, LSR #27 -> ROTL(5) [matches spec]
    #   - v[3] rotation: LSL #8, LSR #24 -> ROTL(8) [spec says 11]
    #   - v[0] rotation: LSL #16, LSR #16 -> ROTL(16) [matches spec]
    #   - v[1] rotation: LSL #13, LSR #19 -> ROTL(13) [matches spec]
    #   - v[3] rotation: LSL #7, LSR #25 -> ROTL(7) [matches spec]
    #   - v[2] rotation: LSL #16, LSR #16 -> ROTL(16) [matches spec]
    #
    # The main loop: CMP r_i, #32 -> 32 absorption iterations [spec says 24]
    #
    # Finalization: the loop after v[2] ^= 0xFF uses CMP r_i, #4
    #   -> 4 finalization rounds [spec says 3]
    fw_sipround = make_sipround(8)
    firmware_output = compute_hash(fw_sipround, 32, 4)

    # === Identify deviations ===
    deviations = [
        {
            "parameter": "second rotation constant in mixing round (v[3] rotation)",
            "spec_value": 11,
            "firmware_value": 8,
        },
        {
            "parameter": "number of absorption iterations",
            "spec_value": 24,
            "firmware_value": 32,
        },
        {
            "parameter": "number of finalization mixing rounds",
            "spec_value": 3,
            "firmware_value": 4,
        },
    ]

    analysis = {
        "firmware_output": firmware_output,
        "spec_output": spec_output,
        "deviations": deviations,
    }

    with open("/app/analysis.json", "w") as f:
        json.dump(analysis, f, indent=2)

    print(f"Firmware output: {firmware_output}")
    print(f"Spec output:     {spec_output}")
    print(f"Deviations found: {len(deviations)}")
    for d in deviations:
        print(f"  - {d['parameter']}: spec={d['spec_value']}, firmware={d['firmware_value']}")
    print("Wrote /app/analysis.json")


if __name__ == "__main__":
    main()
