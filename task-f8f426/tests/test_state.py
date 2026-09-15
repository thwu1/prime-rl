
"""Verification tests for the NMOS 6502 emulator conformance audit.

Tests generate their own ROM binaries (not provided to the solver) and verify
that the emulator produces correct output after the solver's fixes. A second
dynamically-generated ROM with different operands prevents hardcoded patches.
The conformance report is also validated.
"""

import json
import os
import subprocess


EXPECTED_MAIN = {
    "0x0200": 0x00,
    "0x0201": 0x37,
    "0x0202": 0x87,
    "0x0203": 0x00,
    "0x0204": 0x00,
    "0x0205": 0x01,
    "0x0206": 0x42,
    "0x0207": 0x80,
    "0x0208": 0x80,
    "0x0209": 0xF4,
    "0x020A": 0x20,
    "0x020B": 0x35,
    "0x020C": 0xDD,
    "0x020D": 0x23,
    "0x020E": 0xAA,
    "0x020F": 0x55,
    "0x0210": 0x37,
    "0x0211": 0xBC,
}


def create_main_binary():
    """Generate the primary verification ROM.

    Results stored at $0200-$0211. Program at $0400, reset vector at $FFFC.
    Tests 12 behavioral categories across 18 result bytes.
    """
    mem = bytearray(65536)

    program = bytes([
        # === INIT ===
        0x78,                       # $0400: SEI
        0xD8,                       # $0401: CLD
        0xA2, 0xFF,                 # $0402: LDX #$FF
        0x9A,                       # $0404: TXS

        # === Test 1: binary ADC with carry-out, zero result ===
        0x18,                       # $0405: CLC
        0xA9, 0xFF,                 # $0406: LDA #$FF
        0x69, 0x01,                 # $0408: ADC #$01
        0x8D, 0x00, 0x02,           # $040A: STA $0200
        0x08,                       # $040D: PHP
        0x68,                       # $040E: PLA
        0x8D, 0x01, 0x02,           # $040F: STA $0201

        # === Test 2: BCD addition ===
        0xF8,                       # $0412: SED
        0x18,                       # $0413: CLC
        0xA9, 0x49,                 # $0414: LDA #$49
        0x69, 0x38,                 # $0416: ADC #$38
        0x8D, 0x02, 0x02,           # $0418: STA $0202
        0xA9, 0x00,                 # $041B: LDA #$00
        0x2A,                       # $041D: ROL A
        0x8D, 0x03, 0x02,           # $041E: STA $0203

        # === Test 3: BCD addition with carry-out ===
        0x18,                       # $0421: CLC
        0xA9, 0x99,                 # $0422: LDA #$99
        0x69, 0x01,                 # $0424: ADC #$01
        0x8D, 0x04, 0x02,           # $0426: STA $0204
        0xA9, 0x00,                 # $0429: LDA #$00
        0x2A,                       # $042B: ROL A
        0x8D, 0x05, 0x02,           # $042C: STA $0205
        0xD8,                       # $042F: CLD

        # === Test 4: indirect-Y with zero-page pointer wrapping ===
        0xA9, 0x00,                 # $0430: LDA #$00
        0x85, 0xFF,                 # $0432: STA $FF
        0xA9, 0x03,                 # $0434: LDA #$03
        0x85, 0x00,                 # $0436: STA $00
        0xA9, 0x42,                 # $0438: LDA #$42
        0x8D, 0x00, 0x03,           # $043A: STA $0300
        0xA0, 0x00,                 # $043D: LDY #$00
        0xB1, 0xFF,                 # $043F: LDA ($FF),Y
        0x8D, 0x06, 0x02,           # $0441: STA $0206

        # === Test 5: ROR accumulator through carry ===
        0x38,                       # $0444: SEC
        0xA9, 0x00,                 # $0445: LDA #$00
        0x6A,                       # $0447: ROR A
        0x8D, 0x07, 0x02,           # $0448: STA $0207

        # === Test 6: signed overflow detection ===
        0x18,                       # $044B: CLC
        0xA9, 0x7F,                 # $044C: LDA #$7F
        0x69, 0x01,                 # $044E: ADC #$01
        0x8D, 0x08, 0x02,           # $0450: STA $0208
        0x08,                       # $0453: PHP
        0x68,                       # $0454: PLA
        0x8D, 0x09, 0x02,           # $0455: STA $0209

        # === Test 7: subtraction ===
        0x38,                       # $0458: SEC
        0xA9, 0x50,                 # $0459: LDA #$50
        0xE9, 0x30,                 # $045B: SBC #$30
        0x8D, 0x0A, 0x02,           # $045D: STA $020A
        0x08,                       # $0460: PHP
        0x68,                       # $0461: PLA
        0x8D, 0x0B, 0x02,           # $0462: STA $020B

        # === Test 8: shift-and-add multiply 13*17=221=$DD ===
        0xA9, 0x0D,                 # $0465: LDA #$0D
        0x85, 0x10,                 # $0467: STA $10
        0xA9, 0x11,                 # $0469: LDA #$11
        0x85, 0x11,                 # $046B: STA $11
        0xA9, 0x00,                 # $046D: LDA #$00
        0x85, 0x12,                 # $046F: STA $12
        0xA2, 0x08,                 # $0471: LDX #$08
        # mul_loop ($0473):
        0x46, 0x10,                 # $0473: LSR $10
        0x90, 0x07,                 # $0475: BCC +7
        0x18,                       # $0477: CLC
        0xA5, 0x12,                 # $0478: LDA $12
        0x65, 0x11,                 # $047A: ADC $11
        0x85, 0x12,                 # $047C: STA $12
        # mul_skip ($047E):
        0x06, 0x11,                 # $047E: ASL $11
        0xCA,                       # $0480: DEX
        0xD0, 0xF0,                 # $0481: BNE -16

        0xA5, 0x12,                 # $0483: LDA $12
        0x8D, 0x0C, 0x02,           # $0485: STA $020C

        # === Test 9: BCD subtraction ===
        0xF8,                       # $0488: SED
        0x38,                       # $0489: SEC
        0xA9, 0x50,                 # $048A: LDA #$50
        0xE9, 0x27,                 # $048C: SBC #$27
        0x8D, 0x0D, 0x02,           # $048E: STA $020D
        0xD8,                       # $0491: CLD

        # === Test 10: stack LIFO order ===
        0xA9, 0xAA,                 # $0492: LDA #$AA
        0x48,                       # $0494: PHA
        0xA9, 0x55,                 # $0495: LDA #$55
        0x48,                       # $0497: PHA
        0x68,                       # $0498: PLA
        0xAA,                       # $0499: TAX
        0x68,                       # $049A: PLA
        0x8D, 0x0E, 0x02,           # $049B: STA $020E
        0x8E, 0x0F, 0x02,           # $049E: STX $020F

        # === Test 11: JMP indirect page-boundary bug (NMOS) ===
        0xA9, 0xB3,                 # $04A1: LDA #$B3
        0x8D, 0xFF, 0x05,           # $04A3: STA $05FF
        0xA9, 0x04,                 # $04A6: LDA #$04
        0x8D, 0x00, 0x05,           # $04A8: STA $0500
        0xA9, 0xFF,                 # $04AB: LDA #$FF
        0x8D, 0x00, 0x06,           # $04AD: STA $0600
        0x6C, 0xFF, 0x05,           # $04B0: JMP ($05FF)

        # continue11 ($04B3):
        0xA9, 0x37,                 # $04B3: LDA #$37
        0x8D, 0x10, 0x02,           # $04B5: STA $0210

        # === Test 12: zero-page indexed X wrapping ===
        0xA9, 0xBC,                 # $04B8: LDA #$BC
        0x85, 0x10,                 # $04BA: STA $10
        0xA2, 0x20,                 # $04BC: LDX #$20
        0xB5, 0xF0,                 # $04BE: LDA $F0,X
        0x8D, 0x11, 0x02,           # $04C0: STA $0211

        # === HALT ===
        0x4C, 0xC3, 0x04,           # $04C3: JMP $04C3
    ])

    mem[0x0400:0x0400 + len(program)] = program
    mem[0xFFFC] = 0x00
    mem[0xFFFD] = 0x04
    mem[0xFFFE] = 0x00
    mem[0xFFFF] = 0x04
    return bytes(mem)


def create_dynamic_binary():
    """Create a second test binary to prevent hardcoded outputs.

    This program tests the same 4 bug categories with different
    values to verify that all underlying bugs were actually fixed.
    """
    mem = bytearray(65536)
    code = bytes([
        # Init
        0x78,                       # SEI
        0xD8,                       # CLD
        0xA2, 0xFF,                 # LDX #$FF
        0x9A,                       # TXS

        # Test A: BCD 85+29 = 114 BCD -> $14, carry=1
        0xF8,                       # SED
        0x18,                       # CLC
        0xA9, 0x85,                 # LDA #$85
        0x69, 0x29,                 # ADC #$29
        0x8D, 0x00, 0x02,           # STA $0200
        0xA9, 0x00,                 # LDA #$00
        0x2A,                       # ROL A
        0x8D, 0x01, 0x02,           # STA $0201
        0xD8,                       # CLD

        # Test B: indirect-Y with ZP pointer at $FF/$00 wrap
        0xA9, 0x10,                 # LDA #$10
        0x85, 0xFF,                 # STA $FF
        0xA9, 0x07,                 # LDA #$07
        0x85, 0x00,                 # STA $00
        0xA9, 0xED,                 # LDA #$ED
        0x8D, 0x10, 0x07,           # STA $0710
        0xA0, 0x00,                 # LDY #$00
        0xB1, 0xFF,                 # LDA ($FF),Y -> should read $0710
        0x8D, 0x02, 0x02,           # STA $0202

        # Test C: PHP with B flag (bit 4)
        0x18,                       # CLC
        0xA9, 0x01,                 # LDA #$01
        0x08,                       # PHP
        0x68,                       # PLA
        0x8D, 0x03, 0x02,           # STA $0203   -> expect $34

        # Test D: JMP indirect page-boundary wrap
        0xA9, 0x45,                 # LDA #$45 (low byte of target $0645)
        0x8D, 0xFF, 0x07,           # STA $07FF
        0xA9, 0x06,                 # LDA #$06 (high byte)
        0x8D, 0x00, 0x07,           # STA $0700 (NMOS reads high byte here)
        0xA9, 0xFF,                 # LDA #$FF (wrong high byte)
        0x8D, 0x00, 0x08,           # STA $0800 (non-buggy would read here)
        0x6C, 0xFF, 0x07,           # JMP ($07FF) -> $0645 on NMOS

        # padding
        0xEA,                       # NOP
        0xEA,                       # NOP

        # Target $0645
        0xA9, 0xC9,                 # LDA #$C9
        0x8D, 0x04, 0x02,           # STA $0204

        # HALT
        0x4C, 0x4A, 0x06,           # JMP $064A
    ])
    mem[0x0600:0x0600 + len(code)] = code
    mem[0xFFFC] = 0x00
    mem[0xFFFD] = 0x06
    mem[0xFFFE] = 0x00
    mem[0xFFFF] = 0x06
    return bytes(mem)


def run_emulator(output_path="/app/output.json"):
    """Run the emulator and return the parsed output."""
    if os.path.exists(output_path):
        os.remove(output_path)

    result = subprocess.run(
        ["python3", "/app/emulator.py"],
        capture_output=True, text=True, timeout=120,
        cwd="/app",
    )
    assert os.path.exists(output_path), (
        f"Emulator did not produce {output_path}\n"
        f"stdout: {result.stdout[:500]}\nstderr: {result.stderr[:500]}"
    )

    with open(output_path) as f:
        data = json.load(f)

    assert "results" in data, f"output.json missing 'results' key, got keys: {list(data.keys())}"
    return data["results"]


class TestMainProgram:
    """Tests against the primary verification ROM (not provided to solver)."""

    @classmethod
    def setup_class(cls):
        binary = create_main_binary()
        with open("/app/test_suite.bin", "wb") as f:
            f.write(binary)
        cls.results = run_emulator()

    def test_binary_addition_result(self):
        addr = "0x0200"
        assert int(self.results[addr]) == EXPECTED_MAIN[addr], (
            f"expected {EXPECTED_MAIN[addr]:#04x}, got {int(self.results[addr]):#04x}"
        )

    def test_binary_addition_flags(self):
        addr = "0x0201"
        actual = int(self.results[addr])
        expected = EXPECTED_MAIN[addr]
        assert actual == expected, (
            f"expected {expected:#04x} "
            f"(N={expected>>7&1} V={expected>>6&1} B={expected>>4&1} "
            f"D={expected>>3&1} I={expected>>2&1} Z={expected>>1&1} C={expected&1}), "
            f"got {actual:#04x} "
            f"(N={actual>>7&1} V={actual>>6&1} B={actual>>4&1} "
            f"D={actual>>3&1} I={actual>>2&1} Z={actual>>1&1} C={actual&1})"
        )

    def test_bcd_addition_result(self):
        addr = "0x0202"
        assert int(self.results[addr]) == EXPECTED_MAIN[addr], (
            f"expected {EXPECTED_MAIN[addr]:#04x}, got {int(self.results[addr]):#04x}"
        )

    def test_bcd_addition_carry(self):
        addr = "0x0203"
        assert int(self.results[addr]) == EXPECTED_MAIN[addr], (
            f"expected {EXPECTED_MAIN[addr]}, got {int(self.results[addr])}"
        )

    def test_bcd_carryout_result(self):
        addr = "0x0204"
        assert int(self.results[addr]) == EXPECTED_MAIN[addr], (
            f"expected {EXPECTED_MAIN[addr]:#04x}, got {int(self.results[addr]):#04x}"
        )

    def test_bcd_carryout_carry(self):
        addr = "0x0205"
        assert int(self.results[addr]) == EXPECTED_MAIN[addr], (
            f"expected {EXPECTED_MAIN[addr]}, got {int(self.results[addr])}"
        )

    def test_indirect_y_zp_wrap(self):
        addr = "0x0206"
        assert int(self.results[addr]) == EXPECTED_MAIN[addr], (
            f"expected {EXPECTED_MAIN[addr]:#04x}, got {int(self.results[addr]):#04x}"
        )

    def test_ror_through_carry(self):
        addr = "0x0207"
        assert int(self.results[addr]) == EXPECTED_MAIN[addr], (
            f"expected {EXPECTED_MAIN[addr]:#04x}, got {int(self.results[addr]):#04x}"
        )

    def test_signed_overflow_result(self):
        addr = "0x0208"
        assert int(self.results[addr]) == EXPECTED_MAIN[addr], (
            f"expected {EXPECTED_MAIN[addr]:#04x}, got {int(self.results[addr]):#04x}"
        )

    def test_signed_overflow_flags(self):
        addr = "0x0209"
        actual = int(self.results[addr])
        expected = EXPECTED_MAIN[addr]
        assert actual == expected, (
            f"expected {expected:#04x} "
            f"(N={expected>>7&1} V={expected>>6&1}), "
            f"got {actual:#04x} "
            f"(N={actual>>7&1} V={actual>>6&1})"
        )

    def test_subtraction_result(self):
        addr = "0x020A"
        assert int(self.results[addr]) == EXPECTED_MAIN[addr], (
            f"expected {EXPECTED_MAIN[addr]:#04x}, got {int(self.results[addr]):#04x}"
        )

    def test_subtraction_flags(self):
        addr = "0x020B"
        actual = int(self.results[addr])
        expected = EXPECTED_MAIN[addr]
        assert actual == expected, (
            f"expected {expected:#04x}, got {actual:#04x}"
        )

    def test_multiply_result(self):
        addr = "0x020C"
        assert int(self.results[addr]) == EXPECTED_MAIN[addr], (
            f"expected {EXPECTED_MAIN[addr]:#04x} ({EXPECTED_MAIN[addr]}), "
            f"got {int(self.results[addr]):#04x} ({int(self.results[addr])})"
        )

    def test_bcd_subtraction_result(self):
        addr = "0x020D"
        assert int(self.results[addr]) == EXPECTED_MAIN[addr], (
            f"expected {EXPECTED_MAIN[addr]:#04x}, got {int(self.results[addr]):#04x}"
        )

    def test_stack_lifo_first(self):
        addr = "0x020E"
        assert int(self.results[addr]) == EXPECTED_MAIN[addr], (
            f"expected {EXPECTED_MAIN[addr]:#04x}, got {int(self.results[addr]):#04x}"
        )

    def test_stack_lifo_second(self):
        addr = "0x020F"
        assert int(self.results[addr]) == EXPECTED_MAIN[addr], (
            f"expected {EXPECTED_MAIN[addr]:#04x}, got {int(self.results[addr]):#04x}"
        )

    def test_jmp_indirect_page_bug(self):
        addr = "0x0210"
        assert int(self.results[addr]) == EXPECTED_MAIN[addr], (
            f"expected {EXPECTED_MAIN[addr]:#04x}, got {int(self.results[addr]):#04x}"
        )

    def test_zp_indexed_wrap(self):
        addr = "0x0211"
        assert int(self.results[addr]) == EXPECTED_MAIN[addr], (
            f"expected {EXPECTED_MAIN[addr]:#04x}, got {int(self.results[addr]):#04x}"
        )


class TestDynamicProgram:
    """Run the emulator on a second, dynamically-generated binary to prevent hardcoded outputs."""

    @classmethod
    def setup_class(cls):
        dynamic_bin = create_dynamic_binary()
        with open("/app/test_suite.bin", "wb") as f:
            f.write(dynamic_bin)

        if os.path.exists("/app/output.json"):
            os.remove("/app/output.json")

        result = subprocess.run(
            ["python3", "/app/emulator.py"],
            capture_output=True, text=True, timeout=120,
            cwd="/app",
        )
        assert os.path.exists("/app/output.json"), (
            f"Emulator did not produce output.json for dynamic program.\n"
            f"stdout: {result.stdout[:500]}\nstderr: {result.stderr[:500]}"
        )

        with open("/app/output.json") as f:
            data = json.load(f)
        cls.results = data["results"]

    def test_dynamic_bcd_result(self):
        # BCD 85+29 = 114 BCD -> $14
        val = int(self.results["0x0200"])
        assert val == 0x14, (
            f"BCD 85+29 should be $14, got {val:#04x}"
        )

    def test_dynamic_bcd_carry(self):
        # BCD 85+29 carries out
        val = int(self.results["0x0201"])
        assert val == 0x01, (
            f"BCD 85+29 carry should be 1, got {val}"
        )

    def test_dynamic_indirect_y(self):
        # LDA ($FF),Y with ZP wrap -> read from $0710 = $ED
        val = int(self.results["0x0202"])
        assert val == 0xED, (
            f"Indirect-Y ZP wrap should give $ED, got {val:#04x}"
        )

    def test_dynamic_php_flags(self):
        # PHP after CLC; LDA #$01; with I=1 -> $34
        val = int(self.results["0x0203"])
        assert val == 0x34, (
            f"PHP flags should be $34, got {val:#04x} "
            f"(N={val>>7&1} V={val>>6&1} B={val>>4&1} D={val>>3&1} "
            f"I={val>>2&1} Z={val>>1&1} C={val&1})"
        )

    def test_dynamic_jmp_indirect(self):
        # JMP ($07FF) with NMOS page wrap -> target $0645, stores $C9
        val = int(self.results["0x0204"])
        assert val == 0xC9, (
            f"JMP indirect page wrap should give $C9, got {val:#04x}"
        )


class TestConformanceReport:
    """Verify the conformance report exists and correctly identifies issues."""

    def test_report_exists(self):
        assert os.path.exists("/app/conformance.json"), (
            "Conformance report /app/conformance.json not found"
        )

    def test_report_valid_json(self):
        with open("/app/conformance.json") as f:
            data = json.load(f)
        assert isinstance(data, dict), (
            f"conformance.json should be a JSON object, got {type(data).__name__}"
        )

    def test_report_has_enough_categories(self):
        with open("/app/conformance.json") as f:
            data = json.load(f)
        assert len(data) >= 6, (
            f"conformance.json should have at least 6 categories, found {len(data)}"
        )

    def test_report_identifies_failures(self):
        with open("/app/conformance.json") as f:
            data = json.load(f)
        failures = sum(
            1 for v in data.values()
            if isinstance(v, dict) and v.get("status") == "fail"
        )
        assert failures >= 4, (
            f"conformance.json should identify at least 4 failing categories, "
            f"found {failures}"
        )

    def test_report_entries_have_detail(self):
        with open("/app/conformance.json") as f:
            data = json.load(f)
        for cat, entry in data.items():
            assert isinstance(entry, dict), (
                f"Category '{cat}' should be a dict, got {type(entry).__name__}"
            )
            assert "status" in entry, (
                f"Category '{cat}' missing 'status' field"
            )
            assert entry["status"] in ("pass", "fail"), (
                f"Category '{cat}' status should be 'pass' or 'fail', "
                f"got '{entry['status']}'"
            )
            assert "detail" in entry and len(entry["detail"]) > 10, (
                f"Category '{cat}' missing or empty 'detail' field"
            )
