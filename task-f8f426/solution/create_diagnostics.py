#!/usr/bin/env python3
"""
Design diagnostic test programs and evaluate the NMOS 6502 emulator's conformance.

This script:
1. Creates a diagnostic ROM exercising 8 NMOS 6502 behavioral categories
2. Runs the emulator against the diagnostic ROM
3. Compares output to hand-computed correct NMOS 6502 values
4. Writes a conformance report to /app/conformance.json
"""

import json
import os
import subprocess


def create_diagnostic_rom():
    """Design a 64KB diagnostic ROM testing 8 NMOS 6502 behavioral categories.

    Program at $0600. Results stored at $0200-$0209.
    JMP indirect test is placed last so earlier tests always execute.
    JMP target code is placed at a separate location ($0700).
    """
    mem = bytearray(65536)
    pc = 0x0600

    def emit(*data):
        nonlocal pc
        for b in data:
            mem[pc] = b
            pc += 1

    # === INIT ===
    emit(0x78)              # SEI
    emit(0xD8)              # CLD
    emit(0xA2, 0xFF)        # LDX #$FF
    emit(0x9A)              # TXS

    # === Category 1: Binary ADC (baseline — should pass) ===
    # $FF + $01 + 0 = $00, C=1, Z=1
    emit(0x18)              # CLC
    emit(0xA9, 0xFF)        # LDA #$FF
    emit(0x69, 0x01)        # ADC #$01
    emit(0x8D, 0x00, 0x02)  # STA $0200  -> expect $00

    # === Category 2: BCD ADC carry propagation ===
    # BCD 99 + 01 = 100 -> result $00, carry = 1
    # Tests high-nibble decimal correction
    emit(0xF8)              # SED
    emit(0x18)              # CLC
    emit(0xA9, 0x99)        # LDA #$99
    emit(0x69, 0x01)        # ADC #$01
    emit(0x8D, 0x01, 0x02)  # STA $0201  -> expect $00
    emit(0xA9, 0x00)        # LDA #$00
    emit(0x2A)              # ROL A (shift carry into bit 0)
    emit(0x8D, 0x02, 0x02)  # STA $0202  -> expect $01
    emit(0xD8)              # CLD

    # === Category 3: Indirect-Y zero-page pointer wrapping ===
    # Pointer at $FF/$00: low byte at $FF, high byte wraps to $00
    emit(0xA9, 0x10)        # LDA #$10
    emit(0x85, 0xFF)        # STA $FF   (ptr low)
    emit(0xA9, 0x07)        # LDA #$07
    emit(0x85, 0x00)        # STA $00   (ptr high, ZP wrap)
    emit(0xA9, 0xED)        # LDA #$ED
    emit(0x8D, 0x10, 0x07)  # STA $0710 (target value)
    emit(0xA0, 0x00)        # LDY #$00
    emit(0xB1, 0xFF)        # LDA ($FF),Y -> should read $0710 = $ED
    emit(0x8D, 0x03, 0x02)  # STA $0203  -> expect $ED

    # === Category 4: PHP B-flag (bit 4) ===
    # PHP should push status with both bit 4 (B) and bit 5 set
    emit(0x18)              # CLC
    emit(0xA9, 0x01)        # LDA #$01 (Z=0, N=0)
    emit(0x08)              # PHP
    emit(0x68)              # PLA
    emit(0x8D, 0x04, 0x02)  # STA $0204  -> expect $34 (I=1,B=1,bit5=1)

    # === Category 5: Stack LIFO (baseline — should pass) ===
    emit(0xA9, 0xAA)        # LDA #$AA
    emit(0x48)              # PHA
    emit(0xA9, 0x55)        # LDA #$55
    emit(0x48)              # PHA
    emit(0x68)              # PLA -> $55
    emit(0xAA)              # TAX
    emit(0x68)              # PLA -> $AA
    emit(0x8D, 0x05, 0x02)  # STA $0205  -> expect $AA
    emit(0x8E, 0x06, 0x02)  # STX $0206  -> expect $55

    # === Category 6: ROR through carry (baseline — should pass) ===
    emit(0x38)              # SEC
    emit(0xA9, 0x00)        # LDA #$00
    emit(0x6A)              # ROR A -> C goes to bit 7, A=$80
    emit(0x8D, 0x07, 0x02)  # STA $0207  -> expect $80

    # === Category 7: ZP indexed wrapping (baseline — should pass) ===
    emit(0xA9, 0xBC)        # LDA #$BC
    emit(0x85, 0x10)        # STA $10
    emit(0xA2, 0x20)        # LDX #$20
    emit(0xB5, 0xF0)        # LDA $F0,X -> ZP[($F0+$20)&$FF] = ZP[$10] = $BC
    emit(0x8D, 0x08, 0x02)  # STA $0208  -> expect $BC

    # === Category 8: JMP indirect page-boundary anomaly (LAST) ===
    # JMP ($09FF): NMOS wraps high-byte fetch to $0900, not $0A00
    # Target code placed at $0700
    emit(0xA9, 0x00)        # LDA #$00 (target low byte of $0700)
    emit(0x8D, 0xFF, 0x09)  # STA $09FF
    emit(0xA9, 0x07)        # LDA #$07 (target high byte)
    emit(0x8D, 0x00, 0x09)  # STA $0900 (NMOS reads high byte here)
    emit(0xA9, 0xFF)        # LDA #$FF (wrong high byte)
    emit(0x8D, 0x00, 0x0A)  # STA $0A00 (CMOS would read here)
    emit(0x6C, 0xFF, 0x09)  # JMP ($09FF) -> NMOS: $0700

    # JMP target at $0700: store marker and halt
    mem[0x0700] = 0xA9      # LDA #$C9
    mem[0x0701] = 0xC9
    mem[0x0702] = 0x8D      # STA $0209
    mem[0x0703] = 0x09
    mem[0x0704] = 0x02
    mem[0x0705] = 0x4C      # JMP $0705 (halt)
    mem[0x0706] = 0x05
    mem[0x0707] = 0x07

    # Reset vector -> $0600
    mem[0xFFFC] = 0x00
    mem[0xFFFD] = 0x06
    mem[0xFFFE] = 0x00      # IRQ vector
    mem[0xFFFF] = 0x06

    return bytes(mem)


def run_emulator_on_rom(rom_data):
    """Write ROM to disk and run the emulator, return parsed results."""
    with open("/app/test_suite.bin", "wb") as f:
        f.write(rom_data)

    output_path = "/app/output.json"
    if os.path.exists(output_path):
        os.remove(output_path)

    result = subprocess.run(
        ["python3", "/app/emulator.py"],
        capture_output=True, text=True, timeout=120,
        cwd="/app",
    )

    if not os.path.exists(output_path):
        print(f"ERROR: emulator did not produce {output_path}")
        print(f"stdout: {result.stdout[:500]}")
        print(f"stderr: {result.stderr[:500]}")
        return None

    with open(output_path) as f:
        data = json.load(f)

    return data.get("results", {})


def evaluate_conformance():
    """Run diagnostic ROM and evaluate the emulator against 8 categories."""
    rom = create_diagnostic_rom()
    results = run_emulator_on_rom(rom)

    if results is None:
        print("FATAL: Could not obtain emulator output")
        return

    # Known-correct NMOS 6502 values for each diagnostic test
    expected = {
        "0x0200": 0x00,  # Binary ADC: $FF+$01=$00
        "0x0201": 0x00,  # BCD 99+01: result $00
        "0x0202": 0x01,  # BCD 99+01: carry = 1
        "0x0203": 0xED,  # Indirect-Y ZP wrap: reads $0710
        "0x0204": 0x34,  # PHP: flags with B flag set
        "0x0205": 0xAA,  # Stack LIFO: first pulled
        "0x0206": 0x55,  # Stack LIFO: second pulled
        "0x0207": 0x80,  # ROR: carry into bit 7
        "0x0208": 0xBC,  # ZP indexed: wraps correctly
        "0x0209": 0xC9,  # JMP indirect: page wrap to target
    }

    # Map categories to their result addresses and descriptions
    categories = {
        "binary_adc": {
            "addrs": ["0x0200"],
            "desc": "Binary (non-BCD) addition with carry-out and zero result",
        },
        "bcd_adc_carry": {
            "addrs": ["0x0201", "0x0202"],
            "desc": "BCD ADC carry propagation across high nibble (99+01=100)",
        },
        "indirect_y_zp_wrap": {
            "addrs": ["0x0203"],
            "desc": "Indirect-Y addressing zero-page pointer wrapping ($FF/$00)",
        },
        "php_b_flag": {
            "addrs": ["0x0204"],
            "desc": "PHP/BRK processor status B-flag (bit 4) during stack push",
        },
        "stack_lifo": {
            "addrs": ["0x0205", "0x0206"],
            "desc": "Stack PHA/PLA last-in-first-out ordering",
        },
        "ror_carry": {
            "addrs": ["0x0207"],
            "desc": "ROR accumulator carry propagation into bit 7",
        },
        "zp_indexed_wrap": {
            "addrs": ["0x0208"],
            "desc": "Zero-page indexed addressing wrapping within page",
        },
        "jmp_indirect_page": {
            "addrs": ["0x0209"],
            "desc": "JMP ($xxFF) NMOS page-boundary anomaly (high byte wraps within page)",
        },
    }

    conformance = {}

    for cat, info in categories.items():
        all_match = True
        mismatches = []
        for addr in info["addrs"]:
            actual = int(results.get(addr, -1))
            exp = expected[addr]
            if actual != exp:
                all_match = False
                mismatches.append(
                    f"{addr}: expected ${exp:02X}, emulator produced ${actual:02X}"
                )

        if all_match:
            conformance[cat] = {
                "status": "pass",
                "detail": (
                    f"{info['desc']}: emulator behavior matches NMOS 6502 hardware"
                ),
            }
        else:
            conformance[cat] = {
                "status": "fail",
                "detail": f"{info['desc']}: {'; '.join(mismatches)}",
            }

    # Write conformance report
    with open("/app/conformance.json", "w") as f:
        json.dump(conformance, f, indent=2)

    # Print summary
    print("=" * 60)
    print("NMOS 6502 Emulator Conformance Evaluation")
    print("=" * 60)
    for cat, entry in sorted(conformance.items()):
        status = entry["status"].upper()
        print(f"  [{status:4s}] {cat}: {entry['detail']}")

    failures = sum(1 for r in conformance.values() if r["status"] == "fail")
    passes = len(conformance) - failures
    print(f"\nResults: {passes} pass, {failures} fail out of {len(conformance)} categories")


if __name__ == "__main__":
    evaluate_conformance()
