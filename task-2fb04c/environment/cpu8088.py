#!/usr/bin/env python3
"""
Intel 8088 CPU emulator for instruction-level validation.
Implements a subset of 8088 instructions for testing against
hardware-captured execution traces from the ArduinoX86 project.

"""


class CPU8088:
    """Emulates an Intel 8088 CPU at the instruction level."""

    # Flag bit masks
    CF = 0x0001
    PF = 0x0004
    AF = 0x0010
    ZF = 0x0040
    SF = 0x0080
    TF = 0x0100
    IF = 0x0200
    DF = 0x0400
    OF = 0x0800

    def __init__(self):
        # 16-bit registers: AX=0, CX=1, DX=2, BX=3, SP=4, BP=5, SI=6, DI=7
        self.regs = [0] * 8
        self.ip = 0
        self.flags = 0x0002  # Bit 1 always set on 8088
        self.memory = bytearray(65536)
        self.halted = False

    def reset(self):
        self.regs = [0] * 8
        self.ip = 0
        self.flags = 0x0002
        self.memory = bytearray(65536)
        self.halted = False

    # --- Register access ---

    REG16_NAMES = ['ax', 'cx', 'dx', 'bx', 'sp', 'bp', 'si', 'di']
    REG16_MAP = {
        'ax': 0, 'cx': 1, 'dx': 2, 'bx': 3,
        'sp': 4, 'bp': 5, 'si': 6, 'di': 7,
    }

    def get_reg(self, name):
        return self.regs[self.REG16_MAP[name]]

    def set_reg(self, name, value):
        self.regs[self.REG16_MAP[name]] = value & 0xFFFF

    def get_reg8(self, idx):
        """Get 8-bit register by ModR/M index.
        0=AL, 1=CL, 2=DL, 3=BL, 4=AH, 5=CH, 6=DH, 7=BH
        """
        r16 = [0, 1, 2, 3, 0, 1, 2, 3][idx]
        if idx < 4:
            return self.regs[r16] & 0xFF
        return (self.regs[r16] >> 8) & 0xFF

    def set_reg8(self, idx, val):
        """Set 8-bit register by ModR/M index."""
        val &= 0xFF
        r16 = [0, 1, 2, 3, 0, 1, 2, 3][idx]
        if idx < 4:
            self.regs[r16] = (self.regs[r16] & 0xFF00) | val
        else:
            self.regs[r16] = (self.regs[r16] & 0x00FF) | (val << 8)

    # --- Flag access ---

    def get_flag(self, mask):
        return 1 if (self.flags & mask) else 0

    def set_flag(self, mask, val):
        if val:
            self.flags |= mask
        else:
            self.flags &= ~mask
        self.flags |= 0x0002  # Bit 1 always set

    # --- Memory access ---

    def fetch_byte(self):
        val = self.memory[self.ip & 0xFFFF]
        self.ip = (self.ip + 1) & 0xFFFF
        return val

    def fetch_word(self):
        lo = self.fetch_byte()
        hi = self.fetch_byte()
        return (hi << 8) | lo

    # --- Flag computation helpers ---

    @staticmethod
    def parity(val):
        """Return 1 if low byte has even number of set bits (PF=1)."""
        return 1 if (bin(val & 0xFF).count('1') % 2 == 0) else 0

    def update_szp8(self, result):
        result &= 0xFF
        self.set_flag(self.SF, result & 0x80)
        self.set_flag(self.ZF, result == 0)
        self.set_flag(self.PF, self.parity(result))

    def update_szp16(self, result):
        result &= 0xFFFF
        self.set_flag(self.SF, result & 0x8000)
        self.set_flag(self.ZF, result == 0)
        self.set_flag(self.PF, self.parity(result))  # PF uses low byte only

    # --- ModR/M decoding (register-register mode only) ---

    def decode_modrm(self):
        modrm = self.fetch_byte()
        mod = (modrm >> 6) & 3
        reg = (modrm >> 3) & 7
        rm = modrm & 7
        if mod != 3:
            raise NotImplementedError(
                f"Only register addressing (mod=3) supported, got mod={mod}"
            )
        return reg, rm

    # --- ALU operations ---

    def alu_add8(self, a, b, carry_in=0):
        result = a + b + carry_in
        self.set_flag(self.CF, result > 0xFF)
        self.set_flag(self.AF, ((a ^ b ^ result) & 0x10) != 0)
        self.set_flag(self.OF, ((~(a ^ b) & (a ^ result)) & 0x80) != 0)
        result &= 0xFF
        self.update_szp8(result)
        return result

    def alu_add16(self, a, b, carry_in=0):
        result = a + b + carry_in
        self.set_flag(self.CF, result > 0xFFFF)
        self.set_flag(self.AF, ((a ^ b ^ result) & 0x10) != 0)
        self.set_flag(self.OF, ((~(a ^ b) & (a ^ result)) & 0x8000) != 0)
        result &= 0xFFFF
        self.update_szp16(result)
        return result

    def alu_sub8(self, a, b, borrow_in=0):
        result = a - b - borrow_in
        self.set_flag(self.CF, result < 0)
        self.set_flag(self.AF, ((a ^ b ^ result) & 0x10) != 0)
        self.set_flag(self.OF, (((a ^ b) & (a ^ result)) & 0x80) != 0)
        result &= 0xFF
        self.update_szp8(result)
        return result

    def alu_sub16(self, a, b, borrow_in=0):
        result = a - b - borrow_in
        self.set_flag(self.CF, result < 0)
        self.set_flag(self.AF, ((a ^ b ^ result) & 0x10) != 0)
        self.set_flag(self.OF, (((a ^ b) & (a ^ result)) & 0x8000) != 0)
        result &= 0xFFFF
        self.update_szp16(result)
        return result

    def alu_and8(self, a, b):
        result = (a & b) & 0xFF
        self.set_flag(self.CF, 0)
        self.set_flag(self.OF, 0)
        self.set_flag(self.AF, 0)
        self.update_szp8(result)
        return result

    def alu_and16(self, a, b):
        result = (a & b) & 0xFFFF
        self.set_flag(self.CF, 0)
        self.set_flag(self.OF, 0)
        self.set_flag(self.AF, 0)
        self.update_szp16(result)
        return result

    def alu_xor8(self, a, b):
        result = (a ^ b) & 0xFF
        self.set_flag(self.CF, 0)
        self.set_flag(self.OF, 0)
        self.set_flag(self.AF, 0)
        self.update_szp8(result)
        return result

    def alu_xor16(self, a, b):
        result = (a ^ b) & 0xFFFF
        self.set_flag(self.CF, 0)
        self.set_flag(self.OF, 0)
        self.set_flag(self.AF, 0)
        self.update_szp16(result)
        return result

    def alu_or8(self, a, b):
        result = (a | b) & 0xFF
        self.set_flag(self.CF, 0)
        self.set_flag(self.OF, 0)
        self.set_flag(self.AF, 0)
        self.update_szp8(result)
        return result

    def alu_or16(self, a, b):
        result = (a | b) & 0xFFFF
        self.set_flag(self.CF, 0)
        self.set_flag(self.OF, 0)
        self.set_flag(self.AF, 0)
        self.update_szp16(result)
        return result

    # --- BCD instruction implementations ---

    def _daa(self):
        """Decimal Adjust after Addition."""
        al = self.get_reg8(0)
        old_al = al
        old_cf = self.get_flag(self.CF)
        cf = 0

        if (al & 0x0F) > 9 or self.get_flag(self.AF):
            cf = 1 if (old_cf or al > 0xF9) else 0
            al = (al + 6) & 0xFF
            self.set_flag(self.AF, 1)
        else:
            self.set_flag(self.AF, 0)

        if al > 0x99 or old_cf:
            al = (al + 0x60) & 0xFF
            cf = 1

        self.set_reg8(0, al)
        self.set_flag(self.CF, cf)
        self.update_szp8(al)

    def _das(self):
        """Decimal Adjust after Subtraction."""
        al = self.get_reg8(0)
        old_al = al
        old_cf = self.get_flag(self.CF)
        cf = 0

        if (al & 0x0F) > 9 or self.get_flag(self.AF):
            cf = 1 if (old_cf or al < 6) else 0
            al = (al - 6) & 0xFF
            self.set_flag(self.AF, 1)
        else:
            self.set_flag(self.AF, 0)

        if al > 0x99 or old_cf:
            al = (al - 0x60) & 0xFF
            cf = 1

        self.set_reg8(0, al)
        self.set_flag(self.CF, cf)
        self.update_szp8(al)

    def _aam(self):
        """ASCII Adjust after Multiplication."""
        _base = self.fetch_byte()
        al = self.get_reg8(0)
        self.set_reg8(4, al // 10)
        self.set_reg8(0, al % 10)
        self.update_szp8(self.get_reg8(0))

    def _aad(self):
        """ASCII Adjust before Division."""
        _base = self.fetch_byte()
        al = self.get_reg8(0)
        ah = self.get_reg8(4)
        result = (ah * 10 + al) & 0xFF
        self.set_reg8(0, result)
        self.set_reg8(4, 0)
        self.update_szp8(result)

    # --- Shift / Rotate ---

    def _shift_rotate(self, rm_val, count, width, op):
        """
        Shift or rotate operation.
        width: 8 or 16
        op: 0=ROL, 1=ROR, 2=RCL, 3=RCR, 4=SHL, 5=SHR, 6=SHL(alias), 7=SAR
        """
        mask = 0xFF if width == 8 else 0xFFFF
        msb_bit = 7 if width == 8 else 15

        count = count & 0x1F

        if count == 0:
            return rm_val

        result = rm_val
        cf = self.get_flag(self.CF)

        for _ in range(count):
            if op in (4, 6):  # SHL / SAL
                cf = 1 if (result & (1 << msb_bit)) else 0
                result = (result << 1) & mask
            elif op == 5:  # SHR
                cf = result & 1
                result = result >> 1
            elif op == 7:  # SAR
                cf = result & 1
                sign = result & (1 << msb_bit)
                result = (result >> 1) | sign
            elif op == 0:  # ROL
                cf = 1 if (result & (1 << msb_bit)) else 0
                result = ((result << 1) | cf) & mask
            elif op == 1:  # ROR
                cf = result & 1
                result = (result >> 1) | (cf << msb_bit)
            elif op == 2:  # RCL
                new_cf = 1 if (result & (1 << msb_bit)) else 0
                result = ((result << 1) | cf) & mask
                cf = new_cf
            elif op == 3:  # RCR
                new_cf = result & 1
                result = (result >> 1) | (cf << msb_bit)
                cf = new_cf

        self.set_flag(self.CF, cf)

        if op in (4, 6):  # SHL
            self.set_flag(self.OF, ((result >> msb_bit) & 1) ^ cf)
        elif op == 5:  # SHR
            if count == 1:
                self.set_flag(self.OF, (rm_val >> msb_bit) & 1)
            else:
                self.set_flag(self.OF, 0)
        elif op == 7:  # SAR
            self.set_flag(self.OF, 0)
        elif op == 0:  # ROL
            self.set_flag(self.OF, ((result >> msb_bit) & 1) ^ cf)
        elif op == 1:  # ROR
            top_two = (result >> (msb_bit - 1)) & 3
            self.set_flag(self.OF, (top_two == 1) or (top_two == 2))

        if op >= 4:  # SHL, SHR, SAR update SZP
            if width == 8:
                self.update_szp8(result)
            else:
                self.update_szp16(result)

        return result

    # --- NEG ---

    def _neg8(self, val):
        result = (-val) & 0xFF
        self.set_flag(self.CF, val != 0)
        self.set_flag(self.AF, (val & 0x0F) != 0)
        self.set_flag(self.OF, val == 0x80)
        self.update_szp8(result)
        return result

    def _neg16(self, val):
        result = (-val) & 0xFFFF
        self.set_flag(self.CF, val != 0)
        self.set_flag(self.AF, (val & 0x0F) != 0)
        self.set_flag(self.OF, val == 0x8000)
        self.update_szp16(result)
        return result

    # --- MUL ---

    def _mul8(self, val):
        al = self.get_reg8(0)
        result = al * val
        self.regs[0] = result & 0xFFFF  # AX = result
        ah = (result >> 8) & 0xFF
        self.set_flag(self.CF, ah != 0)
        self.set_flag(self.OF, ah != 0)

    def _mul16(self, val):
        ax = self.regs[0]
        result = ax * val
        self.regs[0] = result & 0xFFFF          # AX = low word
        self.regs[2] = (result >> 16) & 0xFFFF   # DX = high word
        self.set_flag(self.CF, self.regs[2] != 0)
        self.set_flag(self.OF, self.regs[2] != 0)

    # --- Main instruction dispatch ---

    def execute_one(self):
        """Fetch and execute one instruction."""
        opcode = self.fetch_byte()

        # ADD r/m8, r8
        if opcode == 0x00:
            reg, rm = self.decode_modrm()
            result = self.alu_add8(self.get_reg8(rm), self.get_reg8(reg))
            self.set_reg8(rm, result)

        # ADD r/m16, r16
        elif opcode == 0x01:
            reg, rm = self.decode_modrm()
            result = self.alu_add16(self.regs[rm], self.regs[reg])
            self.regs[rm] = result

        # ADD r8, r/m8
        elif opcode == 0x02:
            reg, rm = self.decode_modrm()
            result = self.alu_add8(self.get_reg8(reg), self.get_reg8(rm))
            self.set_reg8(reg, result)

        # ADD r16, r/m16
        elif opcode == 0x03:
            reg, rm = self.decode_modrm()
            result = self.alu_add16(self.regs[reg], self.regs[rm])
            self.regs[reg] = result

        # OR r/m8, r8
        elif opcode == 0x08:
            reg, rm = self.decode_modrm()
            result = self.alu_or8(self.get_reg8(rm), self.get_reg8(reg))
            self.set_reg8(rm, result)

        # OR r/m16, r16
        elif opcode == 0x09:
            reg, rm = self.decode_modrm()
            result = self.alu_or16(self.regs[rm], self.regs[reg])
            self.regs[rm] = result

        # AND r/m8, r8
        elif opcode == 0x20:
            reg, rm = self.decode_modrm()
            result = self.alu_and8(self.get_reg8(rm), self.get_reg8(reg))
            self.set_reg8(rm, result)

        # AND r/m16, r16
        elif opcode == 0x21:
            reg, rm = self.decode_modrm()
            result = self.alu_and16(self.regs[rm], self.regs[reg])
            self.regs[rm] = result

        # DAA
        elif opcode == 0x27:
            self._daa()

        # SUB r/m8, r8
        elif opcode == 0x28:
            reg, rm = self.decode_modrm()
            result = self.alu_sub8(self.get_reg8(rm), self.get_reg8(reg))
            self.set_reg8(rm, result)

        # SUB r/m16, r16
        elif opcode == 0x29:
            reg, rm = self.decode_modrm()
            result = self.alu_sub16(self.regs[rm], self.regs[reg])
            self.regs[rm] = result

        # DAS
        elif opcode == 0x2F:
            self._das()

        # XOR r/m8, r8
        elif opcode == 0x30:
            reg, rm = self.decode_modrm()
            result = self.alu_xor8(self.get_reg8(rm), self.get_reg8(reg))
            self.set_reg8(rm, result)

        # XOR r/m16, r16
        elif opcode == 0x31:
            reg, rm = self.decode_modrm()
            result = self.alu_xor16(self.regs[rm], self.regs[reg])
            self.regs[rm] = result

        # CMP r/m8, r8
        elif opcode == 0x38:
            reg, rm = self.decode_modrm()
            self.alu_sub8(self.get_reg8(rm), self.get_reg8(reg))

        # CMP r/m16, r16
        elif opcode == 0x39:
            reg, rm = self.decode_modrm()
            self.alu_sub16(self.regs[rm], self.regs[reg])

        # INC r16
        elif 0x40 <= opcode <= 0x47:
            idx = opcode - 0x40
            old_cf = self.get_flag(self.CF)
            result = self.alu_add16(self.regs[idx], 1)
            self.regs[idx] = result
            self.set_flag(self.CF, old_cf)  # INC preserves CF

        # DEC r16
        elif 0x48 <= opcode <= 0x4F:
            idx = opcode - 0x48
            old_cf = self.get_flag(self.CF)
            result = self.alu_sub16(self.regs[idx], 1)
            self.regs[idx] = result
            self.set_flag(self.CF, old_cf)  # DEC preserves CF

        # MOV r/m8, r8
        elif opcode == 0x88:
            reg, rm = self.decode_modrm()
            self.set_reg8(rm, self.get_reg8(reg))

        # MOV r/m16, r16
        elif opcode == 0x89:
            reg, rm = self.decode_modrm()
            self.regs[rm] = self.regs[reg]

        # MOV r8, r/m8
        elif opcode == 0x8A:
            reg, rm = self.decode_modrm()
            self.set_reg8(reg, self.get_reg8(rm))

        # MOV r16, r/m16
        elif opcode == 0x8B:
            reg, rm = self.decode_modrm()
            self.regs[reg] = self.regs[rm]

        # NOP (XCHG AX, AX)
        elif opcode == 0x90:
            pass

        # CBW
        elif opcode == 0x98:
            al = self.get_reg8(0)
            if al & 0x80:
                self.set_reg8(4, 0xFF)  # AH = 0xFF
            else:
                self.set_reg8(4, 0x00)

        # CWD
        elif opcode == 0x99:
            if self.regs[0] & 0x8000:
                self.regs[2] = 0xFFFF  # DX = 0xFFFF
            else:
                self.regs[2] = 0x0000

        # Shift/Rotate r/m8, 1
        elif opcode == 0xD0:
            reg, rm = self.decode_modrm()
            val = self.get_reg8(rm)
            result = self._shift_rotate(val, 1, 8, reg)
            self.set_reg8(rm, result)

        # Shift/Rotate r/m16, 1
        elif opcode == 0xD1:
            reg, rm = self.decode_modrm()
            val = self.regs[rm]
            result = self._shift_rotate(val, 1, 16, reg)
            self.regs[rm] = result

        # Shift/Rotate r/m8, CL
        elif opcode == 0xD2:
            reg, rm = self.decode_modrm()
            val = self.get_reg8(rm)
            cl = self.get_reg8(1)
            result = self._shift_rotate(val, cl, 8, reg)
            self.set_reg8(rm, result)

        # Shift/Rotate r/m16, CL
        elif opcode == 0xD3:
            reg, rm = self.decode_modrm()
            val = self.regs[rm]
            cl = self.get_reg8(1)
            result = self._shift_rotate(val, cl, 16, reg)
            self.regs[rm] = result

        # AAM
        elif opcode == 0xD4:
            self._aam()

        # AAD
        elif opcode == 0xD5:
            self._aad()

        # Group 3 r/m8 (TEST/NOT/NEG/MUL/IMUL/DIV/IDIV)
        elif opcode == 0xF6:
            reg, rm = self.decode_modrm()
            val = self.get_reg8(rm)
            if reg == 2:    # NOT
                self.set_reg8(rm, (~val) & 0xFF)
            elif reg == 3:  # NEG
                self.set_reg8(rm, self._neg8(val))
            elif reg == 4:  # MUL
                self._mul8(val)
            else:
                raise NotImplementedError(
                    f"Unimplemented Group 3 /r={reg} for opcode 0xF6"
                )

        # Group 3 r/m16 (TEST/NOT/NEG/MUL/IMUL/DIV/IDIV)
        elif opcode == 0xF7:
            reg, rm = self.decode_modrm()
            val = self.regs[rm]
            if reg == 2:    # NOT
                self.regs[rm] = (~val) & 0xFFFF
            elif reg == 3:  # NEG
                self.regs[rm] = self._neg16(val)
            elif reg == 4:  # MUL
                self._mul16(val)
            else:
                raise NotImplementedError(
                    f"Unimplemented Group 3 /r={reg} for opcode 0xF7"
                )

        # CLC
        elif opcode == 0xF8:
            self.set_flag(self.CF, 0)

        # STC
        elif opcode == 0xF9:
            self.set_flag(self.CF, 1)

        # HLT
        elif opcode == 0xF4:
            self.halted = True

        else:
            raise ValueError(f"Unhandled opcode: 0x{opcode:02X}")
