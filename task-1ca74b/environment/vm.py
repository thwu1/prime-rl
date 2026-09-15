#!/usr/bin/env python3
"""Stack-based bytecode VM for compiled SysY programs.

Bytecode text format:
  .global name              -- scalar global (init 0)
  .global name d1 d2 ...    -- array global  (init zeros)
  .func name nparams nlocals
    INSTRUCTION ...
  .endfunc

Usage: python3 vm.py <bytecode.bc> [< input]
"""
import sys

class VM:
    def __init__(self):
        self.globals = {}
        self.functions = {}
        self.inbuf = ''
        self.inpos = 0

    # ---- loading ----
    def load(self, path):
        with open(path) as f:
            lines = f.readlines()
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            i += 1
            if not line or line.startswith('#'):
                continue
            if line.startswith('.global'):
                parts = line.split()
                name = parts[1]
                if len(parts) > 2:
                    dims = [int(d) for d in parts[2:]]
                    self.globals[name] = self._mkarr(dims)
                else:
                    self.globals[name] = 0
            elif line.startswith('.func'):
                parts = line.split()
                fname = parts[1]
                nparams = int(parts[2])
                nlocals = int(parts[3])
                instrs = []
                while i < len(lines):
                    fline = lines[i].strip()
                    i += 1
                    if fline == '.endfunc':
                        break
                    if not fline or fline.startswith('#'):
                        continue
                    instrs.append(fline)
                self.functions[fname] = (nparams, nlocals, instrs)

    def _mkarr(self, dims):
        if len(dims) == 1:
            return [0] * dims[0]
        return [self._mkarr(dims[1:]) for _ in range(dims[0])]

    # ---- execution ----
    def run(self):
        try:
            if not sys.stdin.isatty():
                self.inbuf = sys.stdin.read()
        except Exception:
            self.inbuf = ''
        self.inpos = 0
        ret = self._call('main', [])
        sys.stdout.flush()
        return ret if ret is not None else 0

    def _call(self, name, args):
        # built-ins
        if name == 'putint':
            sys.stdout.write(str(args[0])); return 0
        if name == 'putch':
            sys.stdout.write(chr(args[0])); return 0
        if name == 'putarray':
            n, arr = args[0], args[1]
            sys.stdout.write(f"{n}:")
            for i in range(n):
                sys.stdout.write(f" {arr[i]}")
            sys.stdout.write("\n")
            return 0
        if name == 'getint':
            return self._rint()
        if name == 'getch':
            return self._rch()
        if name == 'getarray':
            arr = args[0]
            n = self._rint()
            for i in range(n):
                arr[i] = self._rint()
            return n

        if name not in self.functions:
            raise RuntimeError(f"Undefined function: {name}")

        nparams, nlocals, instrs = self.functions[name]
        frame = [0] * (nparams + nlocals)
        for i, a in enumerate(args):
            frame[i] = a

        # build label index
        labels = {}
        for idx, ins in enumerate(instrs):
            if ins.startswith('LABEL '):
                labels[ins.split(None, 1)[1]] = idx

        stack = []
        pc = 0
        while pc < len(instrs):
            ins = instrs[pc]
            parts = ins.split()
            op = parts[0]

            if op == 'ICONST':
                stack.append(int(parts[1]))
            elif op == 'LOAD':
                stack.append(frame[int(parts[1])])
            elif op == 'STORE':
                frame[int(parts[1])] = stack.pop()
            elif op == 'GLOAD':
                stack.append(self.globals[parts[1]])
            elif op == 'GSTORE':
                self.globals[parts[1]] = stack.pop()
            elif op == 'ALOAD':
                idx = stack.pop()
                arr = stack.pop()
                stack.append(arr[idx])
            elif op == 'ASTORE':
                val = stack.pop()
                idx = stack.pop()
                arr = stack.pop()
                arr[idx] = val
            elif op == 'NEWARRAY':
                dims = [int(d) for d in parts[1:]]
                stack.append(self._mkarr(dims))
            elif op == 'ADD':
                b = stack.pop(); a = stack.pop(); stack.append(a + b)
            elif op == 'SUB':
                b = stack.pop(); a = stack.pop(); stack.append(a - b)
            elif op == 'MUL':
                b = stack.pop(); a = stack.pop(); stack.append(a * b)
            elif op == 'DIV':
                b = stack.pop(); a = stack.pop()
                stack.append(int(a / b) if b != 0 else 0)
            elif op == 'MOD':
                b = stack.pop(); a = stack.pop()
                stack.append(a - int(a / b) * b if b != 0 else 0)
            elif op == 'NEG':
                stack.append(-stack.pop())
            elif op == 'NOT':
                stack.append(1 if stack.pop() == 0 else 0)
            elif op == 'LT':
                b = stack.pop(); a = stack.pop(); stack.append(1 if a < b else 0)
            elif op == 'GT':
                b = stack.pop(); a = stack.pop(); stack.append(1 if a > b else 0)
            elif op == 'LE':
                b = stack.pop(); a = stack.pop(); stack.append(1 if a <= b else 0)
            elif op == 'GE':
                b = stack.pop(); a = stack.pop(); stack.append(1 if a >= b else 0)
            elif op == 'EQ':
                b = stack.pop(); a = stack.pop(); stack.append(1 if a == b else 0)
            elif op == 'NE':
                b = stack.pop(); a = stack.pop(); stack.append(1 if a != b else 0)
            elif op == 'JMP':
                pc = labels[parts[1]]; continue
            elif op == 'JZ':
                if stack.pop() == 0:
                    pc = labels[parts[1]]; continue
            elif op == 'JNZ':
                if stack.pop() != 0:
                    pc = labels[parts[1]]; continue
            elif op == 'CALL':
                fname = parts[1]
                nargs = int(parts[2])
                cargs = []
                for _ in range(nargs):
                    cargs.insert(0, stack.pop())
                result = self._call(fname, cargs)
                stack.append(result if result is not None else 0)
            elif op == 'RET':
                return 0
            elif op == 'RETV':
                return stack.pop()
            elif op == 'DUP':
                stack.append(stack[-1])
            elif op == 'POP':
                if stack:
                    stack.pop()
            elif op == 'LABEL':
                pass
            elif op == 'HALT':
                return int(parts[1]) if len(parts) > 1 else 0
            else:
                raise RuntimeError(f"Unknown instruction: {op}")
            pc += 1
        return 0

    def _rint(self):
        while self.inpos < len(self.inbuf) and self.inbuf[self.inpos] in ' \t\n\r':
            self.inpos += 1
        st = self.inpos
        if self.inpos < len(self.inbuf) and self.inbuf[self.inpos] in '+-':
            self.inpos += 1
        while self.inpos < len(self.inbuf) and self.inbuf[self.inpos].isdigit():
            self.inpos += 1
        return int(self.inbuf[st:self.inpos]) if self.inpos > st else 0

    def _rch(self):
        if self.inpos < len(self.inbuf):
            c = self.inbuf[self.inpos]; self.inpos += 1; return ord(c)
        return -1

def main():
    if len(sys.argv) < 2:
        print("Usage: vm.py <bytecode.bc>", file=sys.stderr)
        sys.exit(1)
    vm = VM()
    vm.load(sys.argv[1])
    ret = vm.run()
    sys.exit(ret % 256)

if __name__ == '__main__':
    main()
