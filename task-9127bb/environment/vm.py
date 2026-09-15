#!/usr/bin/env python3
"""
Stack-based Virtual Machine for a GoAWK-inspired instruction set.

"""
import sys


class VMError(Exception):
    pass


def parse_program(text):
    """Parse assembly text into list of (opcode, arg) tuples."""
    instructions = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split(None, 1)
        op = parts[0]
        arg = None
        if len(parts) > 1:
            raw = parts[1]
            if raw.startswith('"') and raw.endswith('"'):
                arg = raw[1:-1]
                arg = arg.replace('\\n', '\n').replace('\\t', '\t')
                arg = arg.replace('\\\\"', '"').replace('\\\\', '\\')
            else:
                arg = raw
        instructions.append((op, arg))
    return instructions


class VM:
    def __init__(self, instructions, stdin_data=""):
        self.insns = instructions
        self.stack = []
        self.vars = {}
        self.pc = 0
        self.labels = {}
        self.output = []
        self.exec_count = 0
        self.halted = False

        clean = stdin_data.rstrip('\n')
        self.stdin_lines = clean.split('\n') if clean else []
        self.stdin_idx = 0

        for i, (op, arg) in enumerate(self.insns):
            if op == 'LABEL':
                if arg in self.labels:
                    raise VMError(f"Duplicate label: {arg}")
                self.labels[arg] = i

    def _num(self, v):
        if isinstance(v, int):
            return v
        if isinstance(v, float):
            return v
        s = str(v).strip()
        if not s:
            return 0
        try:
            return int(s) if '.' not in s else float(s)
        except ValueError:
            return 0

    def _str(self, v):
        if isinstance(v, float):
            return str(int(v)) if v == int(v) else f"{v:.6g}"
        return str(v)

    def _truthy(self, v):
        if isinstance(v, (int, float)):
            return v != 0
        return len(str(v)) > 0

    def push(self, v):
        self.stack.append(v)

    def pop(self):
        if not self.stack:
            raise VMError("Stack underflow")
        return self.stack.pop()

    def run(self):
        while self.pc < len(self.insns) and not self.halted:
            op, arg = self.insns[self.pc]
            self.pc += 1
            if op == 'LABEL':
                continue
            self.exec_count += 1

            if op == 'NOP':
                pass
            elif op == 'HALT':
                self.halted = True

            # Stack
            elif op == 'PUSH_INT':
                self.push(int(arg))
            elif op == 'PUSH_STR':
                self.push(arg if arg is not None else "")
            elif op == 'DUP':
                self.push(self.stack[-1])
            elif op == 'DROP':
                self.pop()
            elif op == 'SWAP':
                self.stack[-1], self.stack[-2] = self.stack[-2], self.stack[-1]

            # Arithmetic
            elif op == 'ADD':
                b, a = self._num(self.pop()), self._num(self.pop())
                r = a + b
                self.push(int(r) if isinstance(a, int) and isinstance(b, int) else r)
            elif op == 'SUB':
                b, a = self._num(self.pop()), self._num(self.pop())
                r = a - b
                self.push(int(r) if isinstance(a, int) and isinstance(b, int) else r)
            elif op == 'MUL':
                b, a = self._num(self.pop()), self._num(self.pop())
                r = a * b
                self.push(int(r) if isinstance(a, int) and isinstance(b, int) else r)
            elif op == 'DIV':
                b, a = self._num(self.pop()), self._num(self.pop())
                if b == 0:
                    raise VMError("Division by zero")
                if isinstance(a, int) and isinstance(b, int):
                    self.push(int(a / b))
                else:
                    self.push(float(a) / float(b))
            elif op == 'MOD':
                b, a = self._num(self.pop()), self._num(self.pop())
                if b == 0:
                    raise VMError("Modulo by zero")
                self.push(a % b)
            elif op == 'NEG':
                v = self._num(self.pop())
                self.push(-v)

            # Comparison
            elif op == 'CMP_EQ':
                b, a = self.pop(), self.pop()
                self.push(1 if a == b else 0)
            elif op == 'CMP_NE':
                b, a = self.pop(), self.pop()
                self.push(1 if a != b else 0)
            elif op == 'CMP_LT':
                b, a = self._num(self.pop()), self._num(self.pop())
                self.push(1 if a < b else 0)
            elif op == 'CMP_LE':
                b, a = self._num(self.pop()), self._num(self.pop())
                self.push(1 if a <= b else 0)
            elif op == 'CMP_GT':
                b, a = self._num(self.pop()), self._num(self.pop())
                self.push(1 if a > b else 0)
            elif op == 'CMP_GE':
                b, a = self._num(self.pop()), self._num(self.pop())
                self.push(1 if a >= b else 0)

            # Logic
            elif op == 'NOT':
                self.push(0 if self._truthy(self.pop()) else 1)

            # Variables
            elif op == 'LOAD':
                self.push(self.vars.get(arg, 0))
            elif op == 'STORE':
                self.vars[arg] = self.pop()

            # Control flow
            elif op == 'JUMP':
                if arg not in self.labels:
                    raise VMError(f"Unknown label: {arg}")
                self.pc = self.labels[arg]
            elif op == 'JUMP_TRUE':
                if self._truthy(self.pop()):
                    self.pc = self.labels[arg]
            elif op == 'JUMP_FALSE':
                if not self._truthy(self.pop()):
                    self.pc = self.labels[arg]

            # I/O
            elif op == 'PRINT':
                self.output.append(self._str(self.pop()))
            elif op == 'PRINTLN':
                self.output.append(self._str(self.pop()) + '\n')
            elif op == 'READ_LINE':
                if self.stdin_idx < len(self.stdin_lines):
                    self.push(self.stdin_lines[self.stdin_idx])
                    self.stdin_idx += 1
                    self.push(1)
                else:
                    self.push("")
                    self.push(0)

            # Conversion
            elif op == 'TO_INT':
                self.push(int(self._num(self.pop())))
            elif op == 'TO_STR':
                self.push(self._str(self.pop()))

            # String
            elif op == 'CONCAT':
                b, a = self._str(self.pop()), self._str(self.pop())
                self.push(a + b)

            else:
                raise VMError(f"Unknown opcode: {op}")

        return ''.join(self.output)


def count_static_instructions(text):
    """Count non-empty, non-comment, non-LABEL lines."""
    count = 0
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#') or line.startswith('LABEL'):
            continue
        count += 1
    return count


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 vm.py <program.asm> [< stdin]", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        text = f.read()

    stdin_data = ""
    if not sys.stdin.isatty():
        stdin_data = sys.stdin.read()

    program = parse_program(text)
    vm = VM(program, stdin_data)
    output = vm.run()
    sys.stdout.write(output)
    print(f"Static instructions: {count_static_instructions(text)}", file=sys.stderr)
    print(f"Dynamic instructions: {vm.exec_count}", file=sys.stderr)


if __name__ == '__main__':
    main()
