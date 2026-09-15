
"""
ICWS'94 Memory Array Redcode Simulator (MARS)

A fully compliant implementation of the ICWS'94 Core War standard.
Supports all 17 opcodes, 7 modifiers, and 8 addressing modes.
"""

from collections import deque
import copy


class Instruction:
    """Represents a single MARS instruction."""

    __slots__ = ["opcode", "modifier", "a_mode", "a_number", "b_mode", "b_number"]

    def __init__(
        self,
        opcode="DAT",
        modifier="F",
        a_mode="$",
        a_number=0,
        b_mode="$",
        b_number=0,
    ):
        self.opcode = opcode
        self.modifier = modifier
        self.a_mode = a_mode
        self.a_number = a_number
        self.b_mode = b_mode
        self.b_number = b_number

    def copy(self):
        return Instruction(
            self.opcode,
            self.modifier,
            self.a_mode,
            self.a_number,
            self.b_mode,
            self.b_number,
        )

    def equals(self, other):
        return (
            self.opcode == other.opcode
            and self.modifier == other.modifier
            and self.a_mode == other.a_mode
            and self.a_number == other.a_number
            and self.b_mode == other.b_mode
            and self.b_number == other.b_number
        )


def _default_modifier(opcode, a_mode, b_mode):
    """Return the default ICWS'88-to-'94 modifier."""
    op = opcode.upper()
    a_imm = a_mode == "#"
    b_imm = b_mode == "#"

    if op == "DAT":
        return "F"
    elif op in ("MOV", "CMP", "SEQ", "SNE"):
        if a_imm:
            return "AB"
        elif b_imm:
            return "B"
        else:
            return "I"
    elif op in ("ADD", "SUB", "MUL", "DIV", "MOD"):
        if a_imm:
            return "AB"
        elif b_imm:
            return "B"
        else:
            return "F"
    elif op == "SLT":
        if a_imm:
            return "AB"
        else:
            return "B"
    elif op in ("JMP", "JMZ", "JMN", "DJN", "SPL", "NOP"):
        return "B"
    return "F"


def _parse_operand(s, core_size):
    """Parse an operand string into (mode, number)."""
    s = s.strip().rstrip(",")
    if not s:
        return "$", 0
    mode_chars = "#$*@{<}>"
    if s[0] in mode_chars:
        mode = s[0]
        num_str = s[1:].strip()
    else:
        mode = "$"
        num_str = s.strip()
    number = int(num_str) % core_size
    return mode, number


def parse_load_file(filepath, core_size):
    """Parse an ICWS'94 load file. Returns (instructions, org)."""
    instructions = []
    org = 0

    with open(filepath) as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith(";"):
                continue

            # Strip comments
            comment_pos = line.find(";")
            if comment_pos >= 0:
                line = line[:comment_pos].strip()
            if not line:
                continue

            tokens = line.split()
            if not tokens:
                continue

            keyword = tokens[0].upper()

            if keyword == "ORG":
                org = int(tokens[1])
                continue
            if keyword == "END":
                if len(tokens) > 1:
                    org = int(tokens[1])
                break

            # Parse opcode.modifier
            op_part = tokens[0].upper()
            if "." in op_part:
                opcode, modifier = op_part.split(".", 1)
                modifier = modifier.upper()
            else:
                opcode = op_part
                modifier = None

            # Rejoin remaining tokens and split by comma
            rest = " ".join(tokens[1:])
            parts = rest.split(",")

            if len(parts) >= 2:
                a_mode, a_number = _parse_operand(parts[0], core_size)
                b_mode, b_number = _parse_operand(parts[1], core_size)
            elif len(parts) == 1 and parts[0].strip():
                a_mode, a_number = _parse_operand(parts[0], core_size)
                b_mode, b_number = "$", 0
                # DAT with single operand goes to B-field
                if opcode == "DAT":
                    b_mode, b_number = a_mode, a_number
                    a_mode, a_number = "#", 0
            else:
                a_mode, a_number = "$", 0
                b_mode, b_number = "$", 0

            if modifier is None:
                modifier = _default_modifier(opcode, a_mode, b_mode)

            inst = Instruction(opcode, modifier, a_mode, a_number, b_mode, b_number)
            instructions.append(inst)

    return instructions, org


class MARS:
    """ICWS'94 Memory Array Redcode Simulator."""

    def __init__(self, core_size=8000, max_processes=8000, max_cycles=80000):
        self.M = core_size
        self.max_processes = max_processes
        self.max_cycles = max_cycles
        self.core = [Instruction() for _ in range(core_size)]
        self.warriors = []  # list of deques
        self.cycle = 0

    def load_warrior(self, filepath, position=None):
        """Load a warrior from a load file into core. Returns warrior_id."""
        if position is None:
            position = 0

        instructions, org = parse_load_file(filepath, self.M)

        for i, inst in enumerate(instructions):
            pos = (position + i) % self.M
            self.core[pos] = inst.copy()

        warrior_id = len(self.warriors)
        start = (position + org) % self.M
        self.warriors.append(deque([start]))
        return warrior_id

    def get_cell(self, position):
        """Return the instruction at the given core position as a dict."""
        inst = self.core[position % self.M]
        return {
            "opcode": inst.opcode,
            "modifier": inst.modifier,
            "a_mode": inst.a_mode,
            "a_number": inst.a_number,
            "b_mode": inst.b_mode,
            "b_number": inst.b_number,
        }

    def get_process_count(self, warrior_id):
        """Return the number of active processes for the given warrior."""
        if warrior_id < len(self.warriors):
            return len(self.warriors[warrior_id])
        return 0

    def step(self):
        """Execute one cycle (one instruction per living warrior).
        Returns True if the battle should continue."""
        for w_id in range(len(self.warriors)):
            queue = self.warriors[w_id]
            if not queue:
                continue
            pc = queue.popleft()
            self._execute(w_id, pc, queue)

        self.cycle += 1
        alive = [i for i, q in enumerate(self.warriors) if q]

        if len(self.warriors) > 1 and len(alive) <= 1:
            return False
        if self.cycle >= self.max_cycles:
            return False
        if len(self.warriors) == 1 and not alive:
            return False
        return True

    def run(self):
        """Run the battle to completion."""
        while self.step():
            pass

        alive = [i for i, q in enumerate(self.warriors) if q]
        if len(alive) == 1:
            return {"winner": alive[0], "cycles": self.cycle}
        return {"winner": None, "cycles": self.cycle}

    # ------------------------------------------------------------------
    # Internal execution
    # ------------------------------------------------------------------

    def _execute(self, w_id, pc, queue):
        M = self.M
        core = self.core

        # Fetch current instruction into register
        ir = core[pc].copy()

        # --- Evaluate A-operand ---
        rpa, wpa, pip_a = self._eval_operand(pc, ir.a_mode, ir.a_number)
        ira = core[(pc + rpa) % M].copy()

        # A post-increment (after IRA stored, before B-operand eval)
        if pip_a is not None:
            pos_pip, field = pip_a
            if field == "A":
                core[pos_pip].a_number = (core[pos_pip].a_number + 1) % M
            else:
                core[pos_pip].b_number = (core[pos_pip].b_number + 1) % M

        # --- Evaluate B-operand ---
        rpb, wpb, pip_b = self._eval_operand(pc, ir.b_mode, ir.b_number)
        irb = core[(pc + rpb) % M].copy()

        # B post-increment (after IRB stored, before operation)
        if pip_b is not None:
            pos_pip, field = pip_b
            if field == "A":
                core[pos_pip].a_number = (core[pos_pip].a_number + 1) % M
            else:
                core[pos_pip].b_number = (core[pos_pip].b_number + 1) % M

        # --- Execute opcode ---
        self._exec_opcode(w_id, pc, ir, ira, irb, rpa, wpa, rpb, wpb, queue)

    def _eval_operand(self, pc, mode, number):
        """Evaluate an operand. Returns (read_ptr, write_ptr, pip_info).
        pip_info is None or (position, 'A'|'B') for post-increment."""
        M = self.M
        core = self.core
        pip = None

        if mode == "#":
            return 0, 0, None

        rp = number % M
        wp = number % M

        if mode in ("*", "{", "}"):
            # A-number indirect family
            if mode == "{":
                target = (pc + wp) % M
                core[target].a_number = (core[target].a_number + M - 1) % M

            if mode == "}":
                pip = ((pc + wp) % M, "A")

            rp = (rp + core[(pc + rp) % M].a_number) % M
            wp = (wp + core[(pc + wp) % M].a_number) % M

        elif mode in ("@", "<", ">"):
            # B-number indirect family
            if mode == "<":
                target = (pc + wp) % M
                core[target].b_number = (core[target].b_number + M - 1) % M

            if mode == ">":
                pip = ((pc + wp) % M, "B")

            rp = (rp + core[(pc + rp) % M].b_number) % M
            wp = (wp + core[(pc + wp) % M].b_number) % M

        return rp, wp, pip

    def _exec_opcode(self, w_id, pc, ir, ira, irb, rpa, wpa, rpb, wpb, queue):
        M = self.M
        core = self.core
        opcode = ir.opcode.upper()
        mod = ir.modifier.upper()
        target_pos = (pc + wpb) % M

        if opcode == "DAT":
            return  # process dies

        elif opcode == "MOV":
            self._exec_mov(target_pos, mod, ira)
            queue.append((pc + 1) % M)

        elif opcode == "ADD":
            self._exec_arith(target_pos, mod, ira, irb, lambda a, b: (a + b) % M)
            queue.append((pc + 1) % M)

        elif opcode == "SUB":
            self._exec_arith(
                target_pos, mod, ira, irb, lambda a, b: (b + M - a) % M
            )
            queue.append((pc + 1) % M)

        elif opcode == "MUL":
            self._exec_arith(target_pos, mod, ira, irb, lambda a, b: (a * b) % M)
            queue.append((pc + 1) % M)

        elif opcode == "DIV":
            if self._exec_divmod(
                target_pos, mod, ira, irb, lambda a, b: b // a if a != 0 else None
            ):
                queue.append((pc + 1) % M)

        elif opcode == "MOD":
            if self._exec_divmod(
                target_pos, mod, ira, irb, lambda a, b: b % a if a != 0 else None
            ):
                queue.append((pc + 1) % M)

        elif opcode == "JMP":
            queue.append((pc + rpa) % M)

        elif opcode == "JMZ":
            if self._test_zero(mod, irb):
                queue.append((pc + rpa) % M)
            else:
                queue.append((pc + 1) % M)

        elif opcode == "JMN":
            if self._test_nonzero(mod, irb):
                queue.append((pc + rpa) % M)
            else:
                queue.append((pc + 1) % M)

        elif opcode == "DJN":
            self._djn_decrement(target_pos, mod)
            if self._djn_test(target_pos, mod, irb):
                queue.append((pc + rpa) % M)
            else:
                queue.append((pc + 1) % M)

        elif opcode in ("CMP", "SEQ"):
            if self._test_equal(mod, ira, irb):
                queue.append((pc + 2) % M)
            else:
                queue.append((pc + 1) % M)

        elif opcode == "SNE":
            if not self._test_equal(mod, ira, irb):
                queue.append((pc + 2) % M)
            else:
                queue.append((pc + 1) % M)

        elif opcode == "SLT":
            if self._test_less_than(mod, ira, irb):
                queue.append((pc + 2) % M)
            else:
                queue.append((pc + 1) % M)

        elif opcode == "SPL":
            queue.append((pc + 1) % M)
            if len(queue) < self.max_processes:
                queue.append((pc + rpa) % M)

        elif opcode == "NOP":
            queue.append((pc + 1) % M)

    # ------------------------------------------------------------------
    # MOV
    # ------------------------------------------------------------------

    def _exec_mov(self, target_pos, mod, ira):
        core = self.core
        if mod == "A":
            core[target_pos].a_number = ira.a_number
        elif mod == "B":
            core[target_pos].b_number = ira.b_number
        elif mod == "AB":
            core[target_pos].b_number = ira.a_number
        elif mod == "BA":
            core[target_pos].a_number = ira.b_number
        elif mod == "F":
            core[target_pos].a_number = ira.a_number
            core[target_pos].b_number = ira.b_number
        elif mod == "X":
            core[target_pos].b_number = ira.a_number
            core[target_pos].a_number = ira.b_number
        elif mod == "I":
            core[target_pos] = ira.copy()

    # ------------------------------------------------------------------
    # ADD / SUB / MUL (general arithmetic)
    # ------------------------------------------------------------------

    def _exec_arith(self, target_pos, mod, ira, irb, op):
        core = self.core
        if mod == "A":
            core[target_pos].a_number = op(ira.a_number, irb.a_number)
        elif mod == "B":
            core[target_pos].b_number = op(ira.b_number, irb.b_number)
        elif mod == "AB":
            core[target_pos].b_number = op(ira.a_number, irb.b_number)
        elif mod == "BA":
            core[target_pos].a_number = op(ira.b_number, irb.a_number)
        elif mod in ("F", "I"):
            core[target_pos].a_number = op(ira.a_number, irb.a_number)
            core[target_pos].b_number = op(ira.b_number, irb.b_number)
        elif mod == "X":
            core[target_pos].b_number = op(ira.a_number, irb.b_number)
            core[target_pos].a_number = op(ira.b_number, irb.a_number)

    # ------------------------------------------------------------------
    # DIV / MOD (with zero-division handling)
    # ------------------------------------------------------------------

    def _exec_divmod(self, target_pos, mod, ira, irb, op):
        """Returns True if process survives, False if killed by zero."""
        core = self.core
        M = self.M
        survived = True

        if mod == "A":
            result = op(ira.a_number, irb.a_number)
            if result is None:
                survived = False
            else:
                core[target_pos].a_number = result % M

        elif mod == "B":
            result = op(ira.b_number, irb.b_number)
            if result is None:
                survived = False
            else:
                core[target_pos].b_number = result % M

        elif mod == "AB":
            result = op(ira.a_number, irb.b_number)
            if result is None:
                survived = False
            else:
                core[target_pos].b_number = result % M

        elif mod == "BA":
            result = op(ira.b_number, irb.a_number)
            if result is None:
                survived = False
            else:
                core[target_pos].a_number = result % M

        elif mod in ("F", "I"):
            result_a = op(ira.a_number, irb.a_number)
            result_b = op(ira.b_number, irb.b_number)
            if result_a is not None:
                core[target_pos].a_number = result_a % M
            if result_b is not None:
                core[target_pos].b_number = result_b % M
            if result_a is None or result_b is None:
                survived = False

        elif mod == "X":
            result_b = op(ira.a_number, irb.b_number)
            result_a = op(ira.b_number, irb.a_number)
            if result_b is not None:
                core[target_pos].b_number = result_b % M
            if result_a is not None:
                core[target_pos].a_number = result_a % M
            if result_a is None or result_b is None:
                survived = False

        return survived

    # ------------------------------------------------------------------
    # Conditional tests
    # ------------------------------------------------------------------

    def _test_zero(self, mod, irb):
        if mod in ("A", "BA"):
            return irb.a_number == 0
        elif mod in ("B", "AB"):
            return irb.b_number == 0
        else:  # F, X, I
            return irb.a_number == 0 and irb.b_number == 0

    def _test_nonzero(self, mod, irb):
        if mod in ("A", "BA"):
            return irb.a_number != 0
        elif mod in ("B", "AB"):
            return irb.b_number != 0
        else:  # F, X, I
            return irb.a_number != 0 or irb.b_number != 0

    def _test_equal(self, mod, ira, irb):
        if mod == "A":
            return ira.a_number == irb.a_number
        elif mod == "B":
            return ira.b_number == irb.b_number
        elif mod == "AB":
            return ira.a_number == irb.b_number
        elif mod == "BA":
            return ira.b_number == irb.a_number
        elif mod == "F":
            return ira.a_number == irb.a_number and ira.b_number == irb.b_number
        elif mod == "X":
            return ira.a_number == irb.b_number and ira.b_number == irb.a_number
        elif mod == "I":
            return ira.equals(irb)
        return False

    def _test_less_than(self, mod, ira, irb):
        if mod == "A":
            return ira.a_number < irb.a_number
        elif mod == "B":
            return ira.b_number < irb.b_number
        elif mod == "AB":
            return ira.a_number < irb.b_number
        elif mod == "BA":
            return ira.b_number < irb.a_number
        elif mod in ("F", "I"):
            return ira.a_number < irb.a_number and ira.b_number < irb.b_number
        elif mod == "X":
            return ira.a_number < irb.b_number and ira.b_number < irb.a_number
        return False

    # ------------------------------------------------------------------
    # DJN helpers
    # ------------------------------------------------------------------

    def _djn_decrement(self, target_pos, mod):
        """Decrement the B-target in core."""
        M = self.M
        core = self.core
        if mod in ("A", "BA"):
            core[target_pos].a_number = (core[target_pos].a_number + M - 1) % M
        elif mod in ("B", "AB"):
            core[target_pos].b_number = (core[target_pos].b_number + M - 1) % M
        else:  # F, X, I
            core[target_pos].a_number = (core[target_pos].a_number + M - 1) % M
            core[target_pos].b_number = (core[target_pos].b_number + M - 1) % M

    def _djn_test(self, target_pos, mod, irb):
        """Test the decremented value. Uses the pre-decrement IRB minus 1."""
        M = self.M
        if mod in ("A", "BA"):
            dec = (irb.a_number + M - 1) % M
            return dec != 0
        elif mod in ("B", "AB"):
            dec = (irb.b_number + M - 1) % M
            return dec != 0
        else:  # F, X, I
            dec_a = (irb.a_number + M - 1) % M
            dec_b = (irb.b_number + M - 1) % M
            return dec_a != 0 or dec_b != 0
