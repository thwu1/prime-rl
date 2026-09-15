
"""TAC Parser: parses three-address code text into instruction objects."""

from dataclasses import dataclass, field
from typing import List, Optional
import re


@dataclass
class Instruction:
    kind: str  # "assign_binop", "assign_unop", "copy", "const_load", "call",
               # "param", "label", "goto", "if_goto", "iffalse_goto",
               # "return_val", "return_void", "print", "func_start", "func_end"
    dst: Optional[str] = None
    src1: Optional[str] = None
    op: Optional[str] = None
    src2: Optional[str] = None
    label: Optional[str] = None
    func_name: Optional[str] = None
    call_args: List[str] = field(default_factory=list)
    raw: str = ""

    def uses(self) -> List[str]:
        """Return list of variables read by this instruction."""
        result = []
        if self.kind == "assign_binop":
            if self.src1 and not _is_literal(self.src1):
                result.append(self.src1)
            if self.src2 and not _is_literal(self.src2):
                result.append(self.src2)
        elif self.kind == "assign_unop":
            if self.src1 and not _is_literal(self.src1):
                result.append(self.src1)
        elif self.kind == "copy":
            if self.src1 and not _is_literal(self.src1):
                result.append(self.src1)
        elif self.kind == "const_load":
            pass
        elif self.kind == "call":
            for a in self.call_args:
                if not _is_literal(a):
                    result.append(a)
        elif self.kind == "if_goto" or self.kind == "iffalse_goto":
            if self.src1 and not _is_literal(self.src1):
                result.append(self.src1)
        elif self.kind == "return_val":
            if self.src1 and not _is_literal(self.src1):
                result.append(self.src1)
        elif self.kind == "print":
            if self.src1 and not _is_literal(self.src1):
                result.append(self.src1)
        return result

    def defs(self) -> List[str]:
        """Return list of variables written by this instruction."""
        if self.kind in ("assign_binop", "assign_unop", "copy", "const_load", "call"):
            if self.dst:
                return [self.dst]
        return []

    def is_side_effecting(self) -> bool:
        return self.kind in ("call", "print", "return_val", "return_void",
                             "goto", "if_goto", "iffalse_goto", "label",
                             "param", "func_start", "func_end")

    def clone(self) -> 'Instruction':
        return Instruction(
            kind=self.kind, dst=self.dst, src1=self.src1, op=self.op,
            src2=self.src2, label=self.label, func_name=self.func_name,
            call_args=list(self.call_args), raw=self.raw
        )


def _is_literal(s: str) -> bool:
    if s in ("true", "false"):
        return True
    try:
        int(s)
        return True
    except (ValueError, TypeError):
        return False


def is_literal(s: str) -> bool:
    return _is_literal(s)


def literal_value(s: str) -> Optional[int]:
    if s == "true":
        return 1
    if s == "false":
        return 0
    try:
        return int(s)
    except (ValueError, TypeError):
        return None


@dataclass
class Function:
    name: str
    params: List[str]
    body: List[Instruction]

    def clone(self) -> 'Function':
        return Function(
            name=self.name,
            params=list(self.params),
            body=[i.clone() for i in self.body]
        )


def parse(text: str) -> List[Function]:
    """Parse TAC text into a list of Function objects."""
    functions = []
    lines = text.strip().split('\n')
    current_func = None
    current_body = []
    current_params = []

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue

        if stripped.startswith('FUNC ') and stripped.endswith(':'):
            fname = stripped[5:-1].strip()
            current_func = fname
            current_body = []
            current_params = []
            current_body.append(Instruction(kind="func_start", func_name=fname, raw=stripped))
            continue

        if stripped == 'END FUNC':
            if current_func:
                current_body.append(Instruction(kind="func_end", raw=stripped))
                functions.append(Function(name=current_func, params=current_params, body=current_body))
                current_func = None
            continue

        instr = _parse_instruction(stripped)
        if instr:
            if instr.kind == "param":
                current_params.append(instr.src1)
            current_body.append(instr)

    return functions


def _parse_instruction(line: str) -> Optional[Instruction]:
    # PARAM <var>
    m = re.match(r'^PARAM\s+(\w+)$', line)
    if m:
        return Instruction(kind="param", src1=m.group(1), raw=line)

    # LABEL <label>
    m = re.match(r'^LABEL\s+(\w+)$', line)
    if m:
        return Instruction(kind="label", label=m.group(1), raw=line)

    # GOTO <label>
    m = re.match(r'^GOTO\s+(\w+)$', line)
    if m:
        return Instruction(kind="goto", label=m.group(1), raw=line)

    # IF <var> GOTO <label>
    m = re.match(r'^IF\s+(\S+)\s+GOTO\s+(\w+)$', line)
    if m:
        return Instruction(kind="if_goto", src1=m.group(1), label=m.group(2), raw=line)

    # IFFALSE <var> GOTO <label>
    m = re.match(r'^IFFALSE\s+(\S+)\s+GOTO\s+(\w+)$', line)
    if m:
        return Instruction(kind="iffalse_goto", src1=m.group(1), label=m.group(2), raw=line)

    # RETURN <var>
    m = re.match(r'^RETURN\s+(\S+)$', line)
    if m:
        return Instruction(kind="return_val", src1=m.group(1), raw=line)

    # RETURN (void)
    m = re.match(r'^RETURN$', line)
    if m:
        return Instruction(kind="return_void", raw=line)

    # PRINT <var>
    m = re.match(r'^PRINT\s+(\S+)$', line)
    if m:
        return Instruction(kind="print", src1=m.group(1), raw=line)

    # <var> = CALL <name> <args...>
    m = re.match(r'^(\w+)\s*=\s*CALL\s+(\w+)(.*)?$', line)
    if m:
        args = m.group(3).strip().split() if m.group(3) and m.group(3).strip() else []
        return Instruction(kind="call", dst=m.group(1), func_name=m.group(2),
                           call_args=args, raw=line)

    # <var> = <unop> <var>  (unary: - or !)
    m = re.match(r'^(\w+)\s*=\s*(-|!)\s*(\S+)$', line)
    if m:
        return Instruction(kind="assign_unop", dst=m.group(1), op=m.group(2),
                           src1=m.group(3), raw=line)

    # <var> = <var> <binop> <var>
    m = re.match(r'^(\w+)\s*=\s*(\S+)\s+([\+\-\*/%]|==|!=|<=|>=|<|>|&&|\|\|)\s+(\S+)$', line)
    if m:
        return Instruction(kind="assign_binop", dst=m.group(1), src1=m.group(2),
                           op=m.group(3), src2=m.group(4), raw=line)

    # <var> = <literal>
    m = re.match(r'^(\w+)\s*=\s*(-?\d+|true|false)$', line)
    if m:
        return Instruction(kind="const_load", dst=m.group(1), src1=m.group(2), raw=line)

    # <var> = <var>  (copy)
    m = re.match(r'^(\w+)\s*=\s*(\w+)$', line)
    if m:
        return Instruction(kind="copy", dst=m.group(1), src1=m.group(2), raw=line)

    return None


def emit(functions: List[Function]) -> str:
    """Convert Function objects back to TAC text."""
    lines = []
    for func in functions:
        for instr in func.body:
            lines.append(emit_instruction(instr))
    return '\n'.join(lines) + '\n'


def emit_instruction(instr: Instruction) -> str:
    if instr.kind == "func_start":
        return f"FUNC {instr.func_name}:"
    if instr.kind == "func_end":
        return "END FUNC"
    if instr.kind == "param":
        return f"  PARAM {instr.src1}"
    if instr.kind == "label":
        return f"  LABEL {instr.label}"
    if instr.kind == "goto":
        return f"  GOTO {instr.label}"
    if instr.kind == "if_goto":
        return f"  IF {instr.src1} GOTO {instr.label}"
    if instr.kind == "iffalse_goto":
        return f"  IFFALSE {instr.src1} GOTO {instr.label}"
    if instr.kind == "return_val":
        return f"  RETURN {instr.src1}"
    if instr.kind == "return_void":
        return "  RETURN"
    if instr.kind == "print":
        return f"  PRINT {instr.src1}"
    if instr.kind == "call":
        args = ' '.join(instr.call_args)
        if args:
            return f"  {instr.dst} = CALL {instr.func_name} {args}"
        return f"  {instr.dst} = CALL {instr.func_name}"
    if instr.kind == "assign_binop":
        return f"  {instr.dst} = {instr.src1} {instr.op} {instr.src2}"
    if instr.kind == "assign_unop":
        return f"  {instr.dst} = {instr.op} {instr.src1}"
    if instr.kind == "const_load":
        return f"  {instr.dst} = {instr.src1}"
    if instr.kind == "copy":
        return f"  {instr.dst} = {instr.src1}"
    return instr.raw
