"""
RV32I Analyzer — Reference Implementation
"""

MASK32 = 0xFFFFFFFF


def _sext(value, bits):
    """Sign-extend value from 'bits' bits to a signed Python int."""
    if value & (1 << (bits - 1)):
        return value - (1 << bits)
    return value


def _to_signed32(value):
    """Interpret an unsigned 32-bit value as signed."""
    value &= MASK32
    if value & 0x80000000:
        return value - 0x100000000
    return value


def decode_instruction(word):
    """Decode a 32-bit RV32I instruction word."""
    word &= MASK32
    opcode = word & 0x7F
    rd = (word >> 7) & 0x1F
    funct3 = (word >> 12) & 0x7
    rs1 = (word >> 15) & 0x1F
    rs2 = (word >> 20) & 0x1F
    funct7 = (word >> 25) & 0x7F

    result = {
        'opcode': opcode,
        'rd': None,
        'rs1': None,
        'rs2': None,
        'funct3': None,
        'funct7': None,
        'imm': None,
        'type': None,
        'name': None,
    }

    if opcode == 0x33:  # R-type ALU
        result['type'] = 'R'
        result['rd'] = rd
        result['rs1'] = rs1
        result['rs2'] = rs2
        result['funct3'] = funct3
        result['funct7'] = funct7
        _rnames = {
            (0, 0x00): 'add', (0, 0x20): 'sub',
            (1, 0x00): 'sll', (2, 0x00): 'slt', (3, 0x00): 'sltu',
            (4, 0x00): 'xor', (5, 0x00): 'srl', (5, 0x20): 'sra',
            (6, 0x00): 'or', (7, 0x00): 'and',
        }
        result['name'] = _rnames.get((funct3, funct7), 'unknown')

    elif opcode == 0x13:  # I-type ALU
        result['type'] = 'I'
        result['rd'] = rd
        result['rs1'] = rs1
        result['funct3'] = funct3
        if funct3 in (1, 5):  # shifts
            result['funct7'] = funct7
            result['imm'] = rs2  # shamt
            if funct3 == 1:
                result['name'] = 'slli'
            else:
                result['name'] = 'srli' if funct7 == 0 else 'srai'
        else:
            raw_imm = (word >> 20) & 0xFFF
            result['imm'] = _sext(raw_imm, 12)
            _inames = {0: 'addi', 2: 'slti', 3: 'sltiu',
                       4: 'xori', 6: 'ori', 7: 'andi'}
            result['name'] = _inames.get(funct3, 'unknown')

    elif opcode == 0x03:  # I-type Load
        result['type'] = 'I'
        result['rd'] = rd
        result['rs1'] = rs1
        result['funct3'] = funct3
        raw_imm = (word >> 20) & 0xFFF
        result['imm'] = _sext(raw_imm, 12)
        _lnames = {0: 'lb', 1: 'lh', 2: 'lw', 4: 'lbu', 5: 'lhu'}
        result['name'] = _lnames.get(funct3, 'unknown')

    elif opcode == 0x67:  # I-type JALR
        result['type'] = 'I'
        result['rd'] = rd
        result['rs1'] = rs1
        result['funct3'] = funct3
        raw_imm = (word >> 20) & 0xFFF
        result['imm'] = _sext(raw_imm, 12)
        result['name'] = 'jalr'

    elif opcode == 0x23:  # S-type Store
        result['type'] = 'S'
        result['rs1'] = rs1
        result['rs2'] = rs2
        result['funct3'] = funct3
        raw_imm = (funct7 << 5) | rd
        result['imm'] = _sext(raw_imm, 12)
        _snames = {0: 'sb', 1: 'sh', 2: 'sw'}
        result['name'] = _snames.get(funct3, 'unknown')

    elif opcode == 0x63:  # B-type Branch
        result['type'] = 'B'
        result['rs1'] = rs1
        result['rs2'] = rs2
        result['funct3'] = funct3
        raw_imm = (
            (((word >> 31) & 1) << 12) |
            (((word >> 7) & 1) << 11) |
            (((word >> 25) & 0x3F) << 5) |
            (((word >> 8) & 0xF) << 1)
        )
        result['imm'] = _sext(raw_imm, 13)
        _bnames = {0: 'beq', 1: 'bne', 4: 'blt', 5: 'bge', 6: 'bltu', 7: 'bgeu'}
        result['name'] = _bnames.get(funct3, 'unknown')

    elif opcode == 0x37:  # U-type LUI
        result['type'] = 'U'
        result['rd'] = rd
        result['imm'] = word & 0xFFFFF000
        result['name'] = 'lui'

    elif opcode == 0x17:  # U-type AUIPC
        result['type'] = 'U'
        result['rd'] = rd
        result['imm'] = word & 0xFFFFF000
        result['name'] = 'auipc'

    elif opcode == 0x6F:  # J-type JAL
        result['type'] = 'J'
        result['rd'] = rd
        raw_imm = (
            (((word >> 31) & 1) << 20) |
            (((word >> 12) & 0xFF) << 12) |
            (((word >> 20) & 1) << 11) |
            (((word >> 21) & 0x3FF) << 1)
        )
        result['imm'] = _sext(raw_imm, 21)
        result['name'] = 'jal'

    elif opcode == 0x73:  # ECALL/EBREAK
        result['type'] = 'I'
        result['name'] = 'ecall'
        result['rd'] = 0
        result['rs1'] = 0
        result['imm'] = 0
        result['funct3'] = 0

    return result


class _Memory:
    """Byte-addressable little-endian memory."""

    def __init__(self):
        self._data = {}

    def read_byte(self, addr):
        return self._data.get(addr & MASK32, 0)

    def write_byte(self, addr, value):
        self._data[addr & MASK32] = value & 0xFF

    def read_half(self, addr):
        return self.read_byte(addr) | (self.read_byte(addr + 1) << 8)

    def write_half(self, addr, value):
        self.write_byte(addr, value & 0xFF)
        self.write_byte(addr + 1, (value >> 8) & 0xFF)

    def read_word(self, addr):
        return (self.read_byte(addr) |
                (self.read_byte(addr + 1) << 8) |
                (self.read_byte(addr + 2) << 16) |
                (self.read_byte(addr + 3) << 24))

    def write_word(self, addr, value):
        for i in range(4):
            self.write_byte(addr + i, (value >> (8 * i)) & 0xFF)


def simulate(program, start_pc=0, max_steps=10000):
    """Simulate an RV32I program."""
    regs = [0] * 32
    mem = _Memory()
    pc = start_pc
    trace = []
    steps = 0

    while steps < max_steps:
        idx = (pc - start_pc) // 4
        if idx < 0 or idx >= len(program):
            break
        word = program[idx]
        dec = decode_instruction(word)
        name = dec['name']

        entry = {'pc': pc, 'instruction': word, 'rd': None, 'rd_value': None}
        next_pc = pc + 4

        if name == 'ecall':
            trace.append(entry)
            steps += 1
            break

        # --- R-type ALU ---
        if dec['type'] == 'R' and dec['opcode'] == 0x33:
            v1 = regs[dec['rs1']]
            v2 = regs[dec['rs2']]
            s1 = _to_signed32(v1)
            s2 = _to_signed32(v2)
            if name == 'add':
                res = (v1 + v2) & MASK32
            elif name == 'sub':
                res = (v1 - v2) & MASK32
            elif name == 'sll':
                res = (v1 << (v2 & 0x1F)) & MASK32
            elif name == 'slt':
                res = 1 if s1 < s2 else 0
            elif name == 'sltu':
                res = 1 if v1 < v2 else 0
            elif name == 'xor':
                res = v1 ^ v2
            elif name == 'srl':
                res = v1 >> (v2 & 0x1F)
            elif name == 'sra':
                shamt = v2 & 0x1F
                if shamt == 0:
                    res = v1
                else:
                    if v1 & 0x80000000:
                        res = (v1 >> shamt) | ((MASK32 << (32 - shamt)) & MASK32)
                    else:
                        res = v1 >> shamt
            elif name == 'or':
                res = v1 | v2
            elif name == 'and':
                res = v1 & v2
            else:
                res = 0
            dst = dec['rd']
            if dst != 0:
                regs[dst] = res & MASK32
            entry['rd'] = dst
            entry['rd_value'] = regs[dst]

        # --- I-type ALU ---
        elif dec['opcode'] == 0x13:
            v1 = regs[dec['rs1']]
            s1 = _to_signed32(v1)
            imm = dec['imm']
            imm_u = imm & MASK32
            if name == 'addi':
                res = (v1 + imm_u) & MASK32
            elif name == 'slti':
                res = 1 if s1 < imm else 0
            elif name == 'sltiu':
                res = 1 if v1 < imm_u else 0
            elif name == 'xori':
                res = (v1 ^ imm_u) & MASK32
            elif name == 'ori':
                res = (v1 | imm_u) & MASK32
            elif name == 'andi':
                res = (v1 & imm_u) & MASK32
            elif name == 'slli':
                res = (v1 << imm) & MASK32
            elif name == 'srli':
                res = v1 >> imm
            elif name == 'srai':
                if imm == 0:
                    res = v1
                else:
                    if v1 & 0x80000000:
                        res = (v1 >> imm) | ((MASK32 << (32 - imm)) & MASK32)
                    else:
                        res = v1 >> imm
            else:
                res = 0
            dst = dec['rd']
            if dst != 0:
                regs[dst] = res & MASK32
            entry['rd'] = dst
            entry['rd_value'] = regs[dst]

        # --- Loads ---
        elif dec['opcode'] == 0x03:
            addr = (regs[dec['rs1']] + (dec['imm'] & MASK32)) & MASK32
            if name == 'lb':
                val = mem.read_byte(addr)
                res = _sext(val, 8) & MASK32
            elif name == 'lh':
                val = mem.read_half(addr)
                res = _sext(val, 16) & MASK32
            elif name == 'lw':
                res = mem.read_word(addr)
            elif name == 'lbu':
                res = mem.read_byte(addr)
            elif name == 'lhu':
                res = mem.read_half(addr)
            else:
                res = 0
            dst = dec['rd']
            if dst != 0:
                regs[dst] = res & MASK32
            entry['rd'] = dst
            entry['rd_value'] = regs[dst]

        # --- Stores ---
        elif dec['opcode'] == 0x23:
            addr = (regs[dec['rs1']] + (dec['imm'] & MASK32)) & MASK32
            val = regs[dec['rs2']]
            if name == 'sb':
                mem.write_byte(addr, val)
            elif name == 'sh':
                mem.write_half(addr, val)
            elif name == 'sw':
                mem.write_word(addr, val)

        # --- Branches ---
        elif dec['opcode'] == 0x63:
            v1 = regs[dec['rs1']]
            v2 = regs[dec['rs2']]
            s1 = _to_signed32(v1)
            s2 = _to_signed32(v2)
            taken = False
            if name == 'beq':
                taken = v1 == v2
            elif name == 'bne':
                taken = v1 != v2
            elif name == 'blt':
                taken = s1 < s2
            elif name == 'bge':
                taken = s1 >= s2
            elif name == 'bltu':
                taken = v1 < v2
            elif name == 'bgeu':
                taken = v1 >= v2
            if taken:
                next_pc = (pc + (dec['imm'] & MASK32)) & MASK32

        # --- LUI ---
        elif dec['opcode'] == 0x37:
            dst = dec['rd']
            res = dec['imm'] & MASK32
            if dst != 0:
                regs[dst] = res
            entry['rd'] = dst
            entry['rd_value'] = regs[dst]

        # --- AUIPC ---
        elif dec['opcode'] == 0x17:
            dst = dec['rd']
            res = (pc + dec['imm']) & MASK32
            if dst != 0:
                regs[dst] = res
            entry['rd'] = dst
            entry['rd_value'] = regs[dst]

        # --- JAL ---
        elif dec['opcode'] == 0x6F:
            dst = dec['rd']
            link = (pc + 4) & MASK32
            if dst != 0:
                regs[dst] = link
            entry['rd'] = dst
            entry['rd_value'] = regs[dst]
            next_pc = (pc + (dec['imm'] & MASK32)) & MASK32

        # --- JALR ---
        elif dec['opcode'] == 0x67:
            dst = dec['rd']
            link = (pc + 4) & MASK32
            target = (regs[dec['rs1']] + (dec['imm'] & MASK32)) & MASK32
            target &= ~1  # clear LSB
            if dst != 0:
                regs[dst] = link
            entry['rd'] = dst
            entry['rd_value'] = regs[dst]
            next_pc = target

        trace.append(entry)
        steps += 1
        pc = next_pc

    return {
        'registers': list(regs),
        'trace': trace,
        'steps': steps,
        'exit_code': regs[10] if steps > 0 else -1,
    }


def find_trace_errors(program, trace, start_pc=0):
    """Compare a provided trace against correct simulation."""
    sim = simulate(program, start_pc)
    correct = sim['trace']
    errors = []

    for i, provided in enumerate(trace):
        if i >= len(correct):
            break
        expected = correct[i]

        if provided['pc'] != expected['pc']:
            errors.append({
                'step': i,
                'pc': expected['pc'],
                'field': 'pc',
                'expected': expected['pc'],
                'actual': provided['pc'],
            })
            continue

        if provided['instruction'] != expected['instruction']:
            errors.append({
                'step': i,
                'pc': expected['pc'],
                'field': 'instruction',
                'expected': expected['instruction'],
                'actual': provided['instruction'],
            })
            continue

        if expected['rd_value'] is not None and provided['rd_value'] is not None:
            if provided['rd_value'] != expected['rd_value']:
                errors.append({
                    'step': i,
                    'pc': expected['pc'],
                    'field': 'rd_value',
                    'expected': expected['rd_value'],
                    'actual': provided['rd_value'],
                })

    return errors


def _get_reads_writes(dec):
    """Return (reads, write) register sets for an instruction."""
    reads = set()
    write = None
    name = dec['name']
    opcode = dec['opcode']
    itype = dec['type']

    if name == 'ecall':
        return reads, write

    if itype == 'R':
        if dec['rs1'] is not None and dec['rs1'] != 0:
            reads.add(dec['rs1'])
        if dec['rs2'] is not None and dec['rs2'] != 0:
            reads.add(dec['rs2'])
        if dec['rd'] is not None and dec['rd'] != 0:
            write = dec['rd']

    elif itype == 'I':
        if dec['rs1'] is not None and dec['rs1'] != 0:
            reads.add(dec['rs1'])
        if dec['rd'] is not None and dec['rd'] != 0:
            write = dec['rd']

    elif itype == 'S':
        if dec['rs1'] is not None and dec['rs1'] != 0:
            reads.add(dec['rs1'])
        if dec['rs2'] is not None and dec['rs2'] != 0:
            reads.add(dec['rs2'])

    elif itype == 'B':
        if dec['rs1'] is not None and dec['rs1'] != 0:
            reads.add(dec['rs1'])
        if dec['rs2'] is not None and dec['rs2'] != 0:
            reads.add(dec['rs2'])

    elif itype == 'U':
        if dec['rd'] is not None and dec['rd'] != 0:
            write = dec['rd']

    elif itype == 'J':
        if dec['rd'] is not None and dec['rd'] != 0:
            write = dec['rd']

    return reads, write


def analyze_pipeline_hazards(program):
    """Statically analyze instruction sequence for RAW data hazards."""
    decoded = [decode_instruction(w) for w in program]
    last_writer = {}  # reg -> instruction index
    hazards = []

    for i, dec in enumerate(decoded):
        reads, write = _get_reads_writes(dec)

        for reg in reads:
            if reg in last_writer:
                j = last_writer[reg]
                distance = i - j
                if distance <= 2:
                    producer_opcode = decoded[j]['opcode']
                    is_load = (producer_opcode == 0x03)
                    if distance == 1:
                        stalls_no_fwd = 2
                        stalls_with_fwd = 1 if is_load else 0
                    else:
                        stalls_no_fwd = 1
                        stalls_with_fwd = 0
                    hazards.append({
                        'consumer_index': i,
                        'producer_index': j,
                        'register': reg,
                        'type': 'RAW',
                        'distance': distance,
                        'stalls_no_forwarding': stalls_no_fwd,
                        'stalls_with_forwarding': stalls_with_fwd,
                    })

        if write is not None:
            last_writer[write] = i

    return hazards
