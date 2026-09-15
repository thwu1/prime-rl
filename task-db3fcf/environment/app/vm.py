"""Stack-based virtual machine for MiniCalc bytecode.

Executes bytecode produced by the compiler. The VM uses:
- A value stack for expression evaluation
- A call stack for function invocations (saves return IP, code ref, locals)
- Global variables (dict) and per-call local variables (dict for params)

Variable scoping follows AWK-like rules: function parameters are local;
all other variables are global. A STORE inside a function writes to
local_vars if the name is a known parameter, otherwise to globals.
"""

import json
import sys


class VMError(Exception):
    pass


class VM:
    def __init__(self, program):
        self.main = program["main"]
        self.functions = program.get("functions", {})
        self.stack = []
        self.globals = {}
        self.call_stack = []
        self.output_lines = []

    def run(self):
        self._execute(self.main, {})

    def _execute(self, code, local_vars):
        ip = 0
        while ip < len(code):
            instr = code[ip]
            op = instr[0]

            if op == "PUSH_INT":
                self.stack.append(instr[1])
            elif op == "POP":
                self.stack.pop()
            elif op == "DUP":
                self.stack.append(self.stack[-1])
            elif op == "ADD":
                b, a = self.stack.pop(), self.stack.pop()
                self.stack.append(a + b)
            elif op == "SUB":
                b, a = self.stack.pop(), self.stack.pop()
                self.stack.append(a - b)
            elif op == "MUL":
                b, a = self.stack.pop(), self.stack.pop()
                self.stack.append(a * b)
            elif op == "DIV":
                b, a = self.stack.pop(), self.stack.pop()
                if b == 0:
                    raise VMError("Division by zero")
                self.stack.append(int(a / b))
            elif op == "MOD":
                b, a = self.stack.pop(), self.stack.pop()
                if b == 0:
                    raise VMError("Modulo by zero")
                # Use truncation-toward-zero semantics
                result = abs(a) % abs(b)
                if a < 0:
                    result = -result
                self.stack.append(result)
            elif op == "NEG":
                self.stack[-1] = -self.stack[-1]
            elif op == "EQ":
                b, a = self.stack.pop(), self.stack.pop()
                self.stack.append(1 if a == b else 0)
            elif op == "NE":
                b, a = self.stack.pop(), self.stack.pop()
                self.stack.append(1 if a != b else 0)
            elif op == "LT":
                b, a = self.stack.pop(), self.stack.pop()
                self.stack.append(1 if a < b else 0)
            elif op == "LE":
                b, a = self.stack.pop(), self.stack.pop()
                self.stack.append(1 if a <= b else 0)
            elif op == "GT":
                b, a = self.stack.pop(), self.stack.pop()
                self.stack.append(1 if a > b else 0)
            elif op == "GE":
                b, a = self.stack.pop(), self.stack.pop()
                self.stack.append(1 if a >= b else 0)
            elif op == "NOT":
                self.stack[-1] = 1 if self.stack[-1] == 0 else 0
            elif op == "AND":
                b, a = self.stack.pop(), self.stack.pop()
                self.stack.append(1 if (a != 0 and b != 0) else 0)
            elif op == "OR":
                b, a = self.stack.pop(), self.stack.pop()
                self.stack.append(1 if (a != 0 or b != 0) else 0)
            elif op == "LOAD":
                name = instr[1]
                if name in local_vars:
                    self.stack.append(local_vars[name])
                elif name in self.globals:
                    self.stack.append(self.globals[name])
                else:
                    self.stack.append(0)  # uninitialized = 0
            elif op == "STORE":
                name = instr[1]
                val = self.stack.pop()
                if name in local_vars:
                    local_vars[name] = val
                else:
                    self.globals[name] = val
            elif op == "JMP":
                ip = instr[1]
                continue
            elif op == "JMP_FALSE":
                val = self.stack.pop()
                if val == 0:
                    ip = instr[1]
                    continue
            elif op == "CALL":
                func_name = instr[1]
                nargs = instr[2]
                if func_name not in self.functions:
                    raise VMError(f"Undefined function: {func_name}")
                func = self.functions[func_name]
                new_locals = {}
                args = []
                for _ in range(nargs):
                    args.append(self.stack.pop())
                args.reverse()
                for param, arg in zip(func["params"], args):
                    new_locals[param] = arg
                self.call_stack.append((ip + 1, code, local_vars))
                code = func["code"]
                local_vars = new_locals
                ip = 0
                continue
            elif op == "RET":
                ret_val = self.stack.pop()
                ip, code, local_vars = self.call_stack.pop()
                self.stack.append(ret_val)
                continue
            elif op == "PRINT":
                nargs = instr[1]
                vals = []
                for _ in range(nargs):
                    vals.append(self.stack.pop())
                vals.reverse()
                self.output_lines.append(" ".join(str(v) for v in vals))
            elif op == "HALT":
                return
            else:
                raise VMError(f"Unknown opcode: {op}")

            ip += 1

    def get_output(self):
        if self.output_lines:
            return "\n".join(self.output_lines) + "\n"
        return ""


def run_bytecode(bytecode):
    """Run bytecode dict through VM, return output string."""
    vm = VM(bytecode)
    vm.run()
    return vm.get_output()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 vm.py <bytecode.json>", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1]) as f:
        bytecode = json.load(f)
    vm = VM(bytecode)
    vm.run()
    print(vm.get_output(), end="")
