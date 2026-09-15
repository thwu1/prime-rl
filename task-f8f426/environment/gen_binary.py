#!/usr/bin/env python3
"""Generate the NMOS 6502 functional test binary.

Results are stored at $0200-$0211.
Program loaded at $0400, reset vector at $FFFC.
Halts via JMP-to-self at the end.
"""

import os

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
    0x69, 0x01,                 # $0408: ADC #$01       ; $FF+$01+0=$00, C=1, Z=1
    0x8D, 0x00, 0x02,           # $040A: STA $0200
    0x08,                       # $040D: PHP
    0x68,                       # $040E: PLA
    0x8D, 0x01, 0x02,           # $040F: STA $0201      ; flags

    # === Test 2: BCD addition ===
    0xF8,                       # $0412: SED
    0x18,                       # $0413: CLC
    0xA9, 0x49,                 # $0414: LDA #$49
    0x69, 0x38,                 # $0416: ADC #$38       ; BCD 49+38=87, C=0
    0x8D, 0x02, 0x02,           # $0418: STA $0202
    0xA9, 0x00,                 # $041B: LDA #$00
    0x2A,                       # $041D: ROL A          ; shift carry into bit 0
    0x8D, 0x03, 0x02,           # $041E: STA $0203      ; carry=0

    # === Test 3: BCD addition with carry-out ===
    0x18,                       # $0421: CLC
    0xA9, 0x99,                 # $0422: LDA #$99
    0x69, 0x01,                 # $0424: ADC #$01       ; BCD 99+01=00, C=1
    0x8D, 0x04, 0x02,           # $0426: STA $0204
    0xA9, 0x00,                 # $0429: LDA #$00
    0x2A,                       # $042B: ROL A          ; shift carry into bit 0
    0x8D, 0x05, 0x02,           # $042C: STA $0205      ; carry=1
    0xD8,                       # $042F: CLD

    # === Test 4: indirect-Y with zero-page pointer wrapping ===
    0xA9, 0x00,                 # $0430: LDA #$00
    0x85, 0xFF,                 # $0432: STA $FF        ; ptr low at ZP $FF
    0xA9, 0x03,                 # $0434: LDA #$03
    0x85, 0x00,                 # $0436: STA $00        ; ptr high at ZP $00 (wrap!)
    0xA9, 0x42,                 # $0438: LDA #$42
    0x8D, 0x00, 0x03,           # $043A: STA $0300
    0xA0, 0x00,                 # $043D: LDY #$00
    0xB1, 0xFF,                 # $043F: LDA ($FF),Y    ; addr=($0300)+0
    0x8D, 0x06, 0x02,           # $0441: STA $0206

    # === Test 5: ROR accumulator through carry ===
    0x38,                       # $0444: SEC
    0xA9, 0x00,                 # $0445: LDA #$00
    0x6A,                       # $0447: ROR A          ; C=1->bit7, A=$80, C=0
    0x8D, 0x07, 0x02,           # $0448: STA $0207

    # === Test 6: signed overflow detection ===
    0x18,                       # $044B: CLC
    0xA9, 0x7F,                 # $044C: LDA #$7F      ; +127
    0x69, 0x01,                 # $044E: ADC #$01       ; +128=$80, V=1
    0x8D, 0x08, 0x02,           # $0450: STA $0208
    0x08,                       # $0453: PHP
    0x68,                       # $0454: PLA
    0x8D, 0x09, 0x02,           # $0455: STA $0209      ; flags

    # === Test 7: subtraction ===
    0x38,                       # $0458: SEC
    0xA9, 0x50,                 # $0459: LDA #$50
    0xE9, 0x30,                 # $045B: SBC #$30       ; $50-$30=$20, C=1
    0x8D, 0x0A, 0x02,           # $045D: STA $020A
    0x08,                       # $0460: PHP
    0x68,                       # $0461: PLA
    0x8D, 0x0B, 0x02,           # $0462: STA $020B      ; flags

    # === Test 8: shift-and-add multiply 13*17=221=$DD ===
    0xA9, 0x0D,                 # $0465: LDA #$0D       ; 13
    0x85, 0x10,                 # $0467: STA $10
    0xA9, 0x11,                 # $0469: LDA #$11       ; 17
    0x85, 0x11,                 # $046B: STA $11
    0xA9, 0x00,                 # $046D: LDA #$00
    0x85, 0x12,                 # $046F: STA $12        ; result=0
    0xA2, 0x08,                 # $0471: LDX #$08       ; 8 bits
    # mul_loop ($0473):
    0x46, 0x10,                 # $0473: LSR $10
    0x90, 0x07,                 # $0475: BCC +7 -> $047E (skip 7 bytes of add block)
    0x18,                       # $0477: CLC
    0xA5, 0x12,                 # $0478: LDA $12
    0x65, 0x11,                 # $047A: ADC $11
    0x85, 0x12,                 # $047C: STA $12
    # mul_skip ($047E):
    0x06, 0x11,                 # $047E: ASL $11
    0xCA,                       # $0480: DEX
    0xD0, 0xF0,                 # $0481: BNE -16 -> $0473

    0xA5, 0x12,                 # $0483: LDA $12
    0x8D, 0x0C, 0x02,           # $0485: STA $020C

    # === Test 9: BCD subtraction ===
    0xF8,                       # $0488: SED
    0x38,                       # $0489: SEC
    0xA9, 0x50,                 # $048A: LDA #$50
    0xE9, 0x27,                 # $048C: SBC #$27       ; BCD 50-27=23
    0x8D, 0x0D, 0x02,           # $048E: STA $020D
    0xD8,                       # $0491: CLD

    # === Test 10: stack LIFO order ===
    0xA9, 0xAA,                 # $0492: LDA #$AA
    0x48,                       # $0494: PHA
    0xA9, 0x55,                 # $0495: LDA #$55
    0x48,                       # $0497: PHA
    0x68,                       # $0498: PLA            ; A=$55
    0xAA,                       # $0499: TAX            ; X=$55
    0x68,                       # $049A: PLA            ; A=$AA
    0x8D, 0x0E, 0x02,           # $049B: STA $020E
    0x8E, 0x0F, 0x02,           # $049E: STX $020F

    # === Test 11: JMP indirect page-boundary bug (NMOS) ===
    # JMP ($05FF): NMOS reads high byte from $0500 (page wrap), not $0600
    0xA9, 0xB3,                 # $04A1: LDA #$B3       ; low byte of $04B3
    0x8D, 0xFF, 0x05,           # $04A3: STA $05FF
    0xA9, 0x04,                 # $04A6: LDA #$04       ; high byte
    0x8D, 0x00, 0x05,           # $04A8: STA $0500      ; NMOS reads here (bug)
    0xA9, 0xFF,                 # $04AB: LDA #$FF       ; wrong high byte
    0x8D, 0x00, 0x06,           # $04AD: STA $0600      ; non-buggy would read here
    0x6C, 0xFF, 0x05,           # $04B0: JMP ($05FF)    ; -> $04B3 on NMOS

    # continue11 ($04B3):
    0xA9, 0x37,                 # $04B3: LDA #$37
    0x8D, 0x10, 0x02,           # $04B5: STA $0210

    # === Test 12: zero-page indexed X wrapping ===
    # LDA $F0,X with X=$20 -> ZP[($F0+$20)&$FF] = ZP[$10]
    0xA9, 0xBC,                 # $04B8: LDA #$BC
    0x85, 0x10,                 # $04BA: STA $10
    0xA2, 0x20,                 # $04BC: LDX #$20
    0xB5, 0xF0,                 # $04BE: LDA $F0,X      ; ZP[$10]=$BC
    0x8D, 0x11, 0x02,           # $04C0: STA $0211

    # === HALT ===
    0x4C, 0xC3, 0x04,           # $04C3: JMP $04C3
])

mem[0x0400:0x0400 + len(program)] = program
mem[0xFFFC] = 0x00  # reset vector low
mem[0xFFFD] = 0x04  # reset vector high
mem[0xFFFE] = 0x00  # IRQ vector low
mem[0xFFFF] = 0x04  # IRQ vector high

os.makedirs('/app', exist_ok=True)
with open('/app/program.bin', 'wb') as f:
    f.write(mem)

print(f"Generated program.bin ({len(mem)} bytes, program {len(program)} bytes at $0400-${0x0400+len(program)-1:04X})")
