#!/usr/bin/env python3
"""Interpreter for Three-Address Code (TAC) intermediate representation."""

import sys
import re


class Interpreter:
    def __init__(self):
        self.functions = {}
        self.output = []

    def parse(self, code):
        lines = code.strip().split('\n')
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if line.startswith('#') or not line:
                i += 1
                continue
            m = re.match(r'FUNC\s+(\w+)\s*\((.*?)\)\s*:', line)
            if m:
                fname = m.group(1)
                params = [p.strip() for p in m.group(2).split(',') if p.strip()]
                func_lines = []
                i += 1
                while i < len(lines) and lines[i].strip() != 'END':
                    func_lines.append(lines[i])
                    i += 1
                self.functions[fname] = (params, self._parse_body(func_lines))
                i += 1
            else:
                i += 1

    def _parse_body(self, lines):
        blocks = []
        block_map = {}
        current_label = None
        current_instrs = []
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                continue
            lm = re.match(r'^(\w+)\s*:\s*$', stripped)
            if lm:
                if current_label is not None:
                    block_map[current_label] = current_instrs
                    blocks.append(current_label)
                current_label = lm.group(1)
                current_instrs = []
            else:
                current_instrs.append(stripped)
        if current_label is not None:
            block_map[current_label] = current_instrs
            blocks.append(current_label)
        return blocks, block_map

    def execute(self, fname='main', args=None):
        if args is None:
            args = []
        if fname not in self.functions:
            raise RuntimeError(f"Function {fname} not found")
        params, (block_order, block_map) = self.functions[fname]
        env = {}
        for p, a in zip(params, args):
            env[p] = a

        current_block = block_order[0]

        while True:
            instrs = block_map[current_block]
            ip = 0
            jumped = False
            while ip < len(instrs):
                instr = instrs[ip]
                result = self._exec_instr(instr, env)
                if result is not None:
                    if result[0] == 'goto':
                        current_block = result[1]
                        jumped = True
                        break
                    elif result[0] == 'return':
                        return result[1]
                ip += 1
            if not jumped:
                idx = block_order.index(current_block)
                if idx + 1 < len(block_order):
                    current_block = block_order[idx + 1]
                else:
                    return 0

    def _exec_instr(self, instr, env):
        instr = instr.strip()
        if not instr or instr.startswith('#') or instr == 'NOP':
            return None

        m = re.match(r'RETURN\s+(.+)', instr)
        if m:
            return ('return', self._eval(m.group(1).strip(), env))

        m = re.match(r'PRINT\s+(.+)', instr)
        if m:
            val = self._eval(m.group(1).strip(), env)
            self.output.append(str(val))
            print(val)
            return None

        m = re.match(r'IF\s+(\S+)\s+GOTO\s+(\w+)\s+ELSE\s+GOTO\s+(\w+)', instr)
        if m:
            cond = self._eval(m.group(1), env)
            if cond:
                return ('goto', m.group(2))
            else:
                return ('goto', m.group(3))

        m = re.match(r'GOTO\s+(\w+)', instr)
        if m:
            return ('goto', m.group(1))

        m = re.match(r'(\w+)\s*=\s*CALL\s+(\w+)\s*\((.*?)\)', instr)
        if m:
            var = m.group(1)
            func = m.group(2)
            args_str = m.group(3).strip()
            args = []
            if args_str:
                args = [self._eval(a.strip(), env) for a in args_str.split(',')]
            env[var] = self.execute(func, args)
            return None

        m = re.match(r'(\w+)\s*=\s*(-|!)\s*(\w+)\s*$', instr)
        if m:
            var = m.group(1)
            op = m.group(2)
            operand = self._eval(m.group(3), env)
            if op == '-':
                env[var] = -operand
            elif op == '!':
                env[var] = 1 if not operand else 0
            return None

        m = re.match(
            r'(\w+)\s*=\s*(\w+)\s*([\+\-\*/%]|==|!=|<=|>=|<|>|&&|\|\|)\s*(\w+)\s*$',
            instr
        )
        if m:
            var = m.group(1)
            left = self._eval(m.group(2), env)
            op = m.group(3)
            right = self._eval(m.group(4), env)
            env[var] = self._binop(left, op, right)
            return None

        m = re.match(r'(\w+)\s*=\s*(.+)$', instr)
        if m:
            var = m.group(1)
            val = self._eval(m.group(2).strip(), env)
            env[var] = val
            return None

        raise RuntimeError(f"Unknown instruction: {instr}")

    def _eval(self, s, env):
        s = s.strip()
        try:
            return int(s)
        except ValueError:
            pass
        if s in env:
            return env[s]
        raise RuntimeError(f"Undefined variable: {s}")

    def _binop(self, left, op, right):
        if op == '+': return left + right
        if op == '-': return left - right
        if op == '*': return left * right
        if op == '/': return left // right if right != 0 else 0
        if op == '%': return left % right if right != 0 else 0
        if op == '==': return 1 if left == right else 0
        if op == '!=': return 1 if left != right else 0
        if op == '<': return 1 if left < right else 0
        if op == '>': return 1 if left > right else 0
        if op == '<=': return 1 if left <= right else 0
        if op == '>=': return 1 if left >= right else 0
        if op == '&&': return 1 if (left and right) else 0
        if op == '||': return 1 if (left or right) else 0
        raise RuntimeError(f"Unknown operator: {op}")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python3 interpreter.py <file.tac>", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1]) as f:
        code = f.read()
    interp = Interpreter()
    interp.parse(code)
    interp.execute('main')
