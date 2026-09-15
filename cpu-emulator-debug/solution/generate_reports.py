#!/usr/bin/env python3
"""Generate conformance certification artifacts for the 6502 CPU emulator.

Downloads test vectors from SingleStepTests GitHub, runs conformance tests
against the fixed emulator, and produces the required deliverables:
- conformance.db (SQLite3 database)
- bug_severity_ranking.json
- discriminating_tests.json

"""

import json
import os
import shutil
import sqlite3
import subprocess
import sys

sys.path.insert(0, '/app')

# Complete opcode-to-mnemonic/addressing-mode mapping for the 6502 subset
OPCODE_INFO = {
    0x00: ('BRK', 'implied'), 0x01: ('ORA', 'indirect_x'),
    0x05: ('ORA', 'zero_page'), 0x06: ('ASL', 'zero_page'),
    0x08: ('PHP', 'implied'), 0x09: ('ORA', 'immediate'),
    0x0A: ('ASL', 'accumulator'), 0x0D: ('ORA', 'absolute'),
    0x0E: ('ASL', 'absolute'), 0x10: ('BPL', 'relative'),
    0x11: ('ORA', 'indirect_y'), 0x15: ('ORA', 'zero_page_x'),
    0x16: ('ASL', 'zero_page_x'), 0x18: ('CLC', 'implied'),
    0x19: ('ORA', 'absolute_y'), 0x1D: ('ORA', 'absolute_x'),
    0x1E: ('ASL', 'absolute_x'), 0x20: ('JSR', 'absolute'),
    0x21: ('AND', 'indirect_x'), 0x24: ('BIT', 'zero_page'),
    0x25: ('AND', 'zero_page'), 0x26: ('ROL', 'zero_page'),
    0x28: ('PLP', 'implied'), 0x29: ('AND', 'immediate'),
    0x2A: ('ROL', 'accumulator'), 0x2C: ('BIT', 'absolute'),
    0x2D: ('AND', 'absolute'), 0x2E: ('ROL', 'absolute'),
    0x30: ('BMI', 'relative'), 0x31: ('AND', 'indirect_y'),
    0x35: ('AND', 'zero_page_x'), 0x36: ('ROL', 'zero_page_x'),
    0x38: ('SEC', 'implied'), 0x39: ('AND', 'absolute_y'),
    0x3D: ('AND', 'absolute_x'), 0x3E: ('ROL', 'absolute_x'),
    0x41: ('EOR', 'indirect_x'), 0x45: ('EOR', 'zero_page'),
    0x46: ('LSR', 'zero_page'), 0x48: ('PHA', 'implied'),
    0x49: ('EOR', 'immediate'), 0x4A: ('LSR', 'accumulator'),
    0x4C: ('JMP', 'absolute'), 0x4D: ('EOR', 'absolute'),
    0x4E: ('LSR', 'absolute'), 0x50: ('BVC', 'relative'),
    0x51: ('EOR', 'indirect_y'), 0x55: ('EOR', 'zero_page_x'),
    0x56: ('LSR', 'zero_page_x'), 0x58: ('CLI', 'implied'),
    0x59: ('EOR', 'absolute_y'), 0x5D: ('EOR', 'absolute_x'),
    0x5E: ('LSR', 'absolute_x'), 0x60: ('RTS', 'implied'),
    0x61: ('ADC', 'indirect_x'), 0x65: ('ADC', 'zero_page'),
    0x66: ('ROR', 'zero_page'), 0x68: ('PLA', 'implied'),
    0x69: ('ADC', 'immediate'), 0x6A: ('ROR', 'accumulator'),
    0x6C: ('JMP', 'indirect'), 0x6D: ('ADC', 'absolute'),
    0x6E: ('ROR', 'absolute'), 0x70: ('BVS', 'relative'),
    0x71: ('ADC', 'indirect_y'), 0x75: ('ADC', 'zero_page_x'),
    0x76: ('ROR', 'zero_page_x'), 0x78: ('SEI', 'implied'),
    0x79: ('ADC', 'absolute_y'), 0x7D: ('ADC', 'absolute_x'),
    0x7E: ('ROR', 'absolute_x'), 0x81: ('STA', 'indirect_x'),
    0x84: ('STY', 'zero_page'), 0x85: ('STA', 'zero_page'),
    0x86: ('STX', 'zero_page'), 0x88: ('DEY', 'implied'),
    0x8A: ('TXA', 'implied'), 0x8C: ('STY', 'absolute'),
    0x8D: ('STA', 'absolute'), 0x8E: ('STX', 'absolute'),
    0x90: ('BCC', 'relative'), 0x91: ('STA', 'indirect_y'),
    0x94: ('STY', 'zero_page_x'), 0x95: ('STA', 'zero_page_x'),
    0x96: ('STX', 'zero_page_y'), 0x98: ('TYA', 'implied'),
    0x99: ('STA', 'absolute_y'), 0x9A: ('TXS', 'implied'),
    0x9D: ('STA', 'absolute_x'), 0xA0: ('LDY', 'immediate'),
    0xA1: ('LDA', 'indirect_x'), 0xA2: ('LDX', 'immediate'),
    0xA4: ('LDY', 'zero_page'), 0xA5: ('LDA', 'zero_page'),
    0xA6: ('LDX', 'zero_page'), 0xA8: ('TAY', 'implied'),
    0xA9: ('LDA', 'immediate'), 0xAA: ('TAX', 'implied'),
    0xAC: ('LDY', 'absolute'), 0xAD: ('LDA', 'absolute'),
    0xAE: ('LDX', 'absolute'), 0xB0: ('BCS', 'relative'),
    0xB1: ('LDA', 'indirect_y'), 0xB4: ('LDY', 'zero_page_x'),
    0xB5: ('LDA', 'zero_page_x'), 0xB6: ('LDX', 'zero_page_y'),
    0xB8: ('CLV', 'implied'), 0xB9: ('LDA', 'absolute_y'),
    0xBA: ('TSX', 'implied'), 0xBC: ('LDY', 'absolute_x'),
    0xBD: ('LDA', 'absolute_x'), 0xBE: ('LDX', 'absolute_y'),
    0xC0: ('CPY', 'immediate'), 0xC1: ('CMP', 'indirect_x'),
    0xC4: ('CPY', 'zero_page'), 0xC5: ('CMP', 'zero_page'),
    0xC6: ('DEC', 'zero_page'), 0xC8: ('INY', 'implied'),
    0xC9: ('CMP', 'immediate'), 0xCA: ('DEX', 'implied'),
    0xCC: ('CPY', 'absolute'), 0xCD: ('CMP', 'absolute'),
    0xCE: ('DEC', 'absolute'), 0xD0: ('BNE', 'relative'),
    0xD1: ('CMP', 'indirect_y'), 0xD5: ('CMP', 'zero_page_x'),
    0xD6: ('DEC', 'zero_page_x'), 0xD8: ('CLD', 'implied'),
    0xD9: ('CMP', 'absolute_y'), 0xDD: ('CMP', 'absolute_x'),
    0xDE: ('DEC', 'absolute_x'), 0xE0: ('CPX', 'immediate'),
    0xE1: ('SBC', 'indirect_x'), 0xE4: ('CPX', 'zero_page'),
    0xE5: ('SBC', 'zero_page'), 0xE6: ('INC', 'zero_page'),
    0xE8: ('INX', 'implied'), 0xE9: ('SBC', 'immediate'),
    0xEA: ('NOP', 'implied'), 0xEC: ('CPX', 'absolute'),
    0xED: ('SBC', 'absolute'), 0xEE: ('INC', 'absolute'),
    0xF0: ('BEQ', 'relative'), 0xF1: ('SBC', 'indirect_y'),
    0xF5: ('SBC', 'zero_page_x'), 0xF6: ('INC', 'zero_page_x'),
    0xF8: ('SED', 'implied'), 0xF9: ('SBC', 'absolute_y'),
    0xFD: ('SBC', 'absolute_x'), 0xFE: ('INC', 'absolute_x'),
}


def get_implemented_opcodes():
    """Parse cpu6502.py source to find all implemented opcodes."""
    opcodes = []
    with open('/app/cpu6502.py') as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith(('if opcode == 0x', 'elif opcode == 0x')):
                try:
                    hex_part = stripped.split('0x')[1].split(':')[0].strip()
                    opcodes.append(int(hex_part, 16))
                except (IndexError, ValueError):
                    pass
    return sorted(set(opcodes))


def download_test_vectors(opcodes, target_dir, max_opcodes=25):
    """Download test vectors from SingleStepTests GitHub."""
    os.makedirs(target_dir, exist_ok=True)
    selected = opcodes[:max_opcodes]
    downloaded = 0

    for opcode in selected:
        hex_str = f"{opcode:02x}"
        filepath = os.path.join(target_dir, f"{hex_str}.json")
        if os.path.exists(filepath):
            continue

        url = (f"https://raw.githubusercontent.com/"
               f"SingleStepTests/65x02/main/v1/{hex_str}.json")
        try:
            result = subprocess.run(
                ['curl', '-sL', '--max-time', '30', '-o', filepath, url],
                timeout=60, capture_output=True
            )
            if result.returncode != 0 or not os.path.exists(filepath):
                continue
            with open(filepath) as f:
                data = json.load(f)
            if len(data) > 100:
                with open(filepath, 'w') as f:
                    json.dump(data[:100], f)
            downloaded += 1
            print(f"  Downloaded {hex_str}.json ({min(len(data), 100)} tests)")
        except Exception:
            if os.path.exists(filepath):
                os.remove(filepath)

    return downloaded


def run_conformance_tests(vector_dir):
    """Run all test vectors against the fixed emulator."""
    from cpu6502 import CPU6502

    results = {}
    for filename in sorted(os.listdir(vector_dir)):
        if not filename.endswith('.json') or filename == 'extra.json':
            continue
        opcode = filename[:-5]
        if len(opcode) != 2:
            continue

        filepath = os.path.join(vector_dir, filename)
        try:
            with open(filepath) as f:
                tests = json.load(f)
        except Exception:
            continue

        total = passed = failed = 0
        for test in tests:
            cpu = CPU6502()
            try:
                cpu.load_state(test['initial'])
                cpu.step()
                state = cpu.get_state()
                expected = test['final']

                ok = True
                for key in ['pc', 's', 'a', 'x', 'y', 'p']:
                    if state[key] != expected[key]:
                        ok = False
                        break
                if ok:
                    for addr, val in expected.get('ram', []):
                        if cpu.memory[addr] != val:
                            ok = False
                            break
                total += 1
                if ok:
                    passed += 1
                else:
                    failed += 1
            except Exception:
                total += 1
                failed += 1

        if total > 0:
            results[opcode] = {
                'total': total,
                'passed': passed,
                'failed': failed
            }

    return results


def create_conformance_db(results, bugs, db_path='/app/conformance.db'):
    """Create SQLite conformance database."""
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute('''CREATE TABLE opcode_results (
        opcode TEXT PRIMARY KEY,
        mnemonic TEXT,
        addressing_mode TEXT,
        total_tests INTEGER,
        passed INTEGER,
        failed INTEGER
    )''')

    cur.execute('''CREATE TABLE bugs (
        id INTEGER PRIMARY KEY,
        severity TEXT,
        category TEXT,
        root_cause TEXT,
        affected_opcodes TEXT,
        fix_description TEXT
    )''')

    for opcode_hex, data in results.items():
        opcode_int = int(opcode_hex, 16)
        info = OPCODE_INFO.get(opcode_int, ('???', 'unknown'))
        cur.execute(
            'INSERT INTO opcode_results VALUES (?, ?, ?, ?, ?, ?)',
            (opcode_hex, info[0], info[1], data['total'],
             data['passed'], data['failed'])
        )

    for bug in bugs:
        affected = ','.join(bug['affected_opcodes'])
        cur.execute(
            'INSERT INTO bugs VALUES (?, ?, ?, ?, ?, ?)',
            (bug['id'], bug['severity'], bug['category'],
             bug['root_cause'], affected, bug['fix_description'])
        )

    conn.commit()
    conn.close()
    print(f"Created {db_path}")


def generate_bug_data():
    """Generate structured bug data for all 7 identified bugs."""
    return [
        {
            "id": 1,
            "severity": "critical",
            "category": "addressing_mode",
            "root_cause": "Zero-page indexed X addressing (_zpx) uses 16-bit mask "
                          "(& 0xFFFF) instead of 8-bit mask (& 0xFF), causing "
                          "reads/writes to escape zero page into page 1 when "
                          "base + X > 0xFF",
            "affected_opcodes": ["15", "35", "55", "75", "95", "b5",
                                 "d5", "f5", "16", "36", "56", "76",
                                 "94", "96", "b4", "b6", "d6", "f6"],
            "fix_description": "Changed (base + self.X) & 0xFFFF to "
                               "(base + self.X) & 0xFF in _zpx method"
        },
        {
            "id": 2,
            "severity": "major",
            "category": "addressing_mode",
            "root_cause": "Indirect JMP (_ind) reads high byte of target address "
                          "from the next sequential address instead of wrapping "
                          "within the same page when pointer low byte is 0xFF — "
                          "this fails to reproduce the well-known NMOS 6502 "
                          "indirect JMP page-boundary hardware bug",
            "affected_opcodes": ["6c"],
            "fix_description": "Changed high byte read address from "
                               "(ptr + 1) & 0xFFFF to "
                               "(ptr & 0xFF00) | ((ptr + 1) & 0x00FF) "
                               "to wrap within the same page in _ind"
        },
        {
            "id": 3,
            "severity": "minor",
            "category": "arithmetic",
            "root_cause": "BCD mode ADC adjusts the low nibble only when the "
                          "nibble sum exceeds 0x0F (15) instead of when it "
                          "exceeds 9 — BCD digits are 0-9, so adjustment must "
                          "occur when the nibble sum is 10 or greater",
            "affected_opcodes": ["61", "65", "69", "6d",
                                 "71", "75", "79", "7d"],
            "fix_description": "Changed BCD low nibble adjustment condition "
                               "from 'if lo > 0x0F' to 'if lo > 9' in _adc"
        },
        {
            "id": 4,
            "severity": "major",
            "category": "flag_computation",
            "root_cause": "ROL instruction computes the new carry flag (from "
                          "bit 7) and stores it before rotating it into bit 0, "
                          "so the newly computed carry is used for bit 0 instead "
                          "of the carry value that existed before the instruction",
            "affected_opcodes": ["2a", "26", "2e", "36", "3e"],
            "fix_description": "Saved old carry into a local variable before "
                               "computing new carry from bit 7, then used the "
                               "saved old carry for bit 0 in both _rol and "
                               "_rol_a methods"
        },
        {
            "id": 5,
            "severity": "major",
            "category": "control_flow",
            "root_cause": "BRK instruction pushes PC to the stack without first "
                          "incrementing it past the signature/padding byte that "
                          "follows the BRK opcode, causing RTI to return one "
                          "byte too early (to the padding byte instead of the "
                          "instruction after it)",
            "affected_opcodes": ["00"],
            "fix_description": "Added self.PC = (self.PC + 1) & 0xFFFF before "
                               "the push16(self.PC) call in _brk to skip the "
                               "signature byte"
        },
        {
            "id": 6,
            "severity": "major",
            "category": "addressing_mode",
            "root_cause": "Indexed indirect X addressing (_izx) reads the high "
                          "byte of the effective address using 16-bit wrapping "
                          "(& 0xFFFF) instead of zero-page wrapping (& 0xFF), "
                          "so when the calculated pointer address is 0xFF, the "
                          "high byte is read from 0x0100 instead of 0x0000",
            "affected_opcodes": ["01", "21", "41", "61",
                                 "81", "a1", "c1", "e1"],
            "fix_description": "Changed high byte read from "
                               "(ptr + 1) & 0xFFFF to (ptr + 1) & 0xFF "
                               "in _izx method"
        },
        {
            "id": 7,
            "severity": "major",
            "category": "flag_computation",
            "root_cause": "SBC binary mode overflow flag uses the ADC formula "
                          "'not ((A ^ val) & 0x80)' which checks for same-sign "
                          "operands, instead of the correct SBC formula "
                          "'((A ^ val) & 0x80)' which checks for different-sign "
                          "operands — SBC overflow occurs when subtracting "
                          "operands of different signs produces a result whose "
                          "sign differs from the minuend",
            "affected_opcodes": ["e1", "e5", "e9", "ed",
                                 "f1", "f5", "f9", "fd"],
            "fix_description": "Removed erroneous 'not' from V flag condition "
                               "in binary SBC else block: changed "
                               "'not ((self.A ^ val) & 0x80)' to "
                               "'((self.A ^ val) & 0x80)'"
        }
    ]


def generate_severity_ranking(bugs):
    """Generate severity ranking with justifications."""
    severity_order = {'critical': 3, 'major': 2, 'minor': 1}
    ranking = []

    justifications = {
        1: ("Affects 18 opcodes across all zero-page,X instructions "
            "(loads, stores, arithmetic, shifts). Widest blast radius "
            "of any defect — any program using zero-page,X addressing "
            "with indices wrapping past 0xFF will silently corrupt data "
            "by reading/writing page 1 instead of zero page."),
        2: ("Affects only JMP indirect (1 opcode) but corrupts control "
            "flow at page boundaries. The NMOS 6502 page-boundary "
            "wrapping behavior is a well-documented hardware quirk; "
            "failure to reproduce it causes incorrect jump targets "
            "when pointer is at 0xXXFF."),
        3: ("Affects 8 ADC opcodes but only in BCD decimal mode, which "
            "is rarely used in most 6502 programs. Silent data "
            "corruption limited to decimal arithmetic with nibble "
            "sums between 10 and 15."),
        4: ("Affects 5 ROL opcodes. Causes data corruption in all "
            "rotate-left operations by using the newly computed carry "
            "instead of the old carry for bit 0, producing incorrect "
            "results in multi-byte shift and rotation sequences."),
        5: ("Affects only BRK (1 opcode) but corrupts interrupt return "
            "address. RTI after BRK returns one byte too early, "
            "causing the CPU to execute the BRK signature byte as "
            "an instruction. Critical for programs using software "
            "interrupts."),
        6: ("Affects 8 opcodes using indexed indirect X addressing. "
            "When computed zero-page pointer is 0xFF, reads high byte "
            "from page 1 instead of wrapping to 0x00. Silent data "
            "corruption in pointer-heavy code."),
        7: ("Affects 8 SBC opcodes. Overflow flag is computed with "
            "inverted sign logic, causing V flag to be set for "
            "same-sign subtractions and cleared for different-sign "
            "subtractions. Breaks signed arithmetic overflow detection.")
    }

    for bug in bugs:
        ranking.append({
            "id": bug["id"],
            "severity": bug["severity"],
            "affected_opcode_count": len(bug["affected_opcodes"]),
            "justification": justifications[bug["id"]]
        })

    ranking.sort(key=lambda x: severity_order.get(x['severity'], 0), reverse=True)
    return ranking


def generate_discriminating_tests():
    """Generate minimal test vectors that uniquely isolate each bug."""
    return [
        {
            "name": "Bug1-zpx-wrap: LDA zp,X base=FF X=1 wraps to 0x00",
            "initial": {
                "pc": 512, "s": 253, "a": 0, "x": 1, "y": 0, "p": 32,
                "ram": [[512, 181], [513, 255], [0, 66], [256, 153]]
            },
            "final": {
                "pc": 514, "s": 253, "a": 66, "x": 1, "y": 0, "p": 32,
                "ram": [[512, 181], [513, 255], [0, 66], [256, 153]]
            }
        },
        {
            "name": "Bug2-ind-page: JMP ($10FF) wraps high byte within page",
            "initial": {
                "pc": 768, "s": 253, "a": 0, "x": 0, "y": 0, "p": 32,
                "ram": [[768, 108], [769, 255], [770, 16],
                        [4351, 52], [4096, 86], [4352, 18]]
            },
            "final": {
                "pc": 22068, "s": 253, "a": 0, "x": 0, "y": 0, "p": 32,
                "ram": [[768, 108], [769, 255], [770, 16],
                        [4351, 52], [4096, 86], [4352, 18]]
            }
        },
        {
            "name": "Bug3-bcd-threshold: BCD ADC 05+05=10 needs low adjust",
            "initial": {
                "pc": 512, "s": 253, "a": 5, "x": 0, "y": 0, "p": 40,
                "ram": [[512, 105], [513, 5]]
            },
            "final": {
                "pc": 514, "s": 253, "a": 16, "x": 0, "y": 0, "p": 40,
                "ram": [[512, 105], [513, 5]]
            }
        },
        {
            "name": "Bug4-rol-carry: ROL A=0x80 C=0 should give A=0x00 C=1",
            "initial": {
                "pc": 512, "s": 253, "a": 128, "x": 0, "y": 0, "p": 32,
                "ram": [[512, 42]]
            },
            "final": {
                "pc": 513, "s": 253, "a": 0, "x": 0, "y": 0, "p": 35,
                "ram": [[512, 42]]
            }
        },
        {
            "name": "Bug5-brk-pc: BRK pushes PC+2 skipping padding byte",
            "initial": {
                "pc": 768, "s": 253, "a": 0, "x": 0, "y": 0, "p": 32,
                "ram": [[768, 0], [769, 234],
                        [65534, 0], [65535, 128]]
            },
            "final": {
                "pc": 32768, "s": 250, "a": 0, "x": 0, "y": 0, "p": 36,
                "ram": [[768, 0], [769, 234],
                        [65534, 0], [65535, 128],
                        [509, 3], [508, 2], [507, 48]]
            }
        },
        {
            "name": "Bug6-izx-wrap: LDA (zp,X) ptr=0xFF wraps high byte to 0x00",
            "initial": {
                "pc": 512, "s": 253, "a": 0, "x": 15, "y": 0, "p": 32,
                "ram": [[512, 161], [513, 240],
                        [255, 52], [0, 18], [256, 86],
                        [4660, 66]]
            },
            "final": {
                "pc": 514, "s": 253, "a": 66, "x": 15, "y": 0, "p": 32,
                "ram": [[512, 161], [513, 240],
                        [255, 52], [0, 18], [256, 86],
                        [4660, 66]]
            }
        },
        {
            "name": "Bug7-sbc-vflag: SBC 0x50-0x90 overflow V=1",
            "initial": {
                "pc": 512, "s": 253, "a": 80, "x": 0, "y": 0, "p": 33,
                "ram": [[512, 233], [513, 144]]
            },
            "final": {
                "pc": 514, "s": 253, "a": 192, "x": 0, "y": 0, "p": 224,
                "ram": [[512, 233], [513, 144]]
            }
        }
    ]


def main():
    print("=== 6502 Conformance Certification Pipeline ===\n")

    # 1. Get implemented opcodes
    opcodes = get_implemented_opcodes()
    print(f"Found {len(opcodes)} implemented opcodes in cpu6502.py")

    # 2. Download test vectors from GitHub
    download_dir = '/app/downloaded_vectors'
    print(f"\nDownloading test vectors from SingleStepTests/65x02...")
    downloaded = download_test_vectors(opcodes, download_dir, max_opcodes=25)
    print(f"Downloaded {downloaded} new test vector files")

    # 3. Merge local test vectors into download dir
    local_dir = '/app/test_vectors'
    if os.path.isdir(local_dir):
        for f in os.listdir(local_dir):
            if f.endswith('.json') and f != 'extra.json':
                src = os.path.join(local_dir, f)
                dst = os.path.join(download_dir, f)
                if not os.path.exists(dst):
                    shutil.copy(src, dst)

    # 4. Run conformance tests against FIXED emulator
    print("\nRunning conformance tests against fixed emulator...")
    results = run_conformance_tests(download_dir)

    total_tests = sum(r['total'] for r in results.values())
    total_passed = sum(r['passed'] for r in results.values())
    total_failed = sum(r['failed'] for r in results.values())
    print(f"Tested {len(results)} opcodes: "
          f"{total_passed}/{total_tests} passed, {total_failed} failed")

    # 5. Generate bug data
    bugs = generate_bug_data()

    # 6. Create SQLite conformance database
    create_conformance_db(results, bugs)

    # 7. Write severity ranking
    ranking = generate_severity_ranking(bugs)
    with open('/app/bug_severity_ranking.json', 'w') as f:
        json.dump(ranking, f, indent=2)
    print(f"Wrote bug_severity_ranking.json ({len(ranking)} entries)")

    # 8. Write discriminating tests
    disc_tests = generate_discriminating_tests()
    with open('/app/discriminating_tests.json', 'w') as f:
        json.dump(disc_tests, f, indent=2)
    print(f"Wrote discriminating_tests.json ({len(disc_tests)} tests)")

    print("\n=== Certification complete ===")


if __name__ == '__main__':
    main()
