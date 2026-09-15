#!/usr/bin/env python3
"""
SPIR-V static output value analyzer.

Parses SPIR-V assembly (text or binary via spirv-dis), performs static value
propagation on the entry point function, and outputs JSON mapping Output
variable names to their resolved values (or null if runtime-dependent).
"""

import sys
import json
import re
import subprocess
import os
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Set, Tuple, Any


# ─── Lattice ────────────────────────────────────────────────────────────────

class LatticeValue:
    pass


class Top(LatticeValue):
    def __repr__(self):
        return "T"


class Const(LatticeValue):
    __slots__ = ('value',)

    def __init__(self, value):
        self.value = value

    def __repr__(self):
        return f"C({self.value})"


class Bottom(LatticeValue):
    def __repr__(self):
        return "B"


def lattice_meet(a: LatticeValue, b: LatticeValue) -> LatticeValue:
    if isinstance(a, Top):
        return b
    if isinstance(b, Top):
        return a
    if isinstance(a, Bottom) or isinstance(b, Bottom):
        return Bottom()
    if a.value == b.value:
        return Const(a.value)
    return Bottom()


# ─── IR Data Structures ────────────────────────────────────────────────────

@dataclass
class Instruction:
    opcode: str
    result_id: Optional[str] = None
    type_id: Optional[str] = None
    operands: List[str] = field(default_factory=list)


@dataclass
class Block:
    label: str
    phis: List[Instruction] = field(default_factory=list)
    body: List[Instruction] = field(default_factory=list)
    merge: Optional[Instruction] = None
    terminator: Optional[Instruction] = None
    preds: List[str] = field(default_factory=list)
    succs: List[str] = field(default_factory=list)


@dataclass
class Function:
    func_id: str
    return_type: Optional[str] = None
    func_type: Optional[str] = None
    params: List[Instruction] = field(default_factory=list)
    blocks: Dict[str, Block] = field(default_factory=dict)
    block_order: List[str] = field(default_factory=list)
    entry: Optional[str] = None


@dataclass
class Module:
    capabilities: List[str] = field(default_factory=list)
    memory_model: Optional[Tuple[str, str]] = None
    entry_points: List[Instruction] = field(default_factory=list)
    names: Dict[str, str] = field(default_factory=dict)
    decorations: Dict[str, List[List[str]]] = field(default_factory=dict)
    types: Dict[str, Instruction] = field(default_factory=dict)
    constants: Dict[str, Instruction] = field(default_factory=dict)
    variables: Dict[str, Instruction] = field(default_factory=dict)
    functions: Dict[str, Function] = field(default_factory=dict)


# ─── Parser ─────────────────────────────────────────────────────────────────

TYPED_OPCODES = frozenset({
    'OpFunction', 'OpFunctionParameter', 'OpVariable',
    'OpLoad', 'OpAccessChain', 'OpInBoundsAccessChain',
    'OpIAdd', 'OpISub', 'OpIMul', 'OpSDiv', 'OpSMod', 'OpSRem',
    'OpUDiv', 'OpUMod',
    'OpFAdd', 'OpFSub', 'OpFMul', 'OpFDiv', 'OpFRem', 'OpFMod',
    'OpSNegate', 'OpFNegate',
    'OpSGreaterThan', 'OpSLessThan', 'OpSGreaterThanEqual', 'OpSLessThanEqual',
    'OpUGreaterThan', 'OpULessThan', 'OpUGreaterThanEqual', 'OpULessThanEqual',
    'OpIEqual', 'OpINotEqual',
    'OpFOrdEqual', 'OpFOrdNotEqual', 'OpFOrdLessThan', 'OpFOrdGreaterThan',
    'OpFOrdLessThanEqual', 'OpFOrdGreaterThanEqual',
    'OpFUnordEqual', 'OpFUnordNotEqual',
    'OpLogicalNot', 'OpLogicalAnd', 'OpLogicalOr',
    'OpLogicalEqual', 'OpLogicalNotEqual',
    'OpNot', 'OpBitwiseAnd', 'OpBitwiseOr', 'OpBitwiseXor',
    'OpShiftLeftLogical', 'OpShiftRightLogical', 'OpShiftRightArithmetic',
    'OpPhi', 'OpCopyObject', 'OpSelect',
    'OpFunctionCall',
    'OpCompositeConstruct', 'OpCompositeExtract', 'OpVectorShuffle',
    'OpConvertSToF', 'OpConvertFToS', 'OpConvertUToF', 'OpConvertFToU',
    'OpBitcast', 'OpSConvert', 'OpUConvert', 'OpFConvert',
    'OpConstant', 'OpConstantTrue', 'OpConstantFalse',
    'OpConstantNull', 'OpConstantComposite',
    'OpExtInst',
})

TERMINATOR_OPCODES = frozenset({
    'OpBranch', 'OpBranchConditional', 'OpSwitch',
    'OpReturn', 'OpReturnValue', 'OpUnreachable', 'OpKill',
})

_RE_RESULT = re.compile(r'(%\S+)\s*=\s*(Op\w+)(.*)')
_RE_OP = re.compile(r'(Op\w+)(.*)')


def tokenize_operands(text: str) -> List[str]:
    tokens = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == '"':
            j = i + 1
            while j < n and text[j] != '"':
                if text[j] == '\\':
                    j += 1
                j += 1
            tokens.append(text[i:j + 1])
            i = j + 1
        elif c.isspace():
            i += 1
        else:
            j = i
            while j < n and not text[j].isspace() and text[j] != '"':
                j += 1
            tokens.append(text[i:j])
            i = j
    return tokens


def parse_line(line: str) -> Optional[Instruction]:
    line = line.strip()
    if not line or line.startswith(';'):
        return None

    in_str = False
    for i, c in enumerate(line):
        if c == '"':
            in_str = not in_str
        elif c == ';' and not in_str:
            line = line[:i].strip()
            break

    if not line:
        return None

    m = _RE_RESULT.match(line)
    if m:
        result_id = m.group(1)
        opcode = m.group(2)
        operands = tokenize_operands(m.group(3))
        type_id = None
        if opcode in TYPED_OPCODES:
            if operands and operands[0].startswith('%'):
                type_id = operands[0]
                operands = operands[1:]
        return Instruction(opcode=opcode, result_id=result_id,
                           type_id=type_id, operands=operands)

    m = _RE_OP.match(line)
    if m:
        opcode = m.group(1)
        operands = tokenize_operands(m.group(2))
        return Instruction(opcode=opcode, operands=operands)

    return None


def parse_module(text: str) -> Module:
    module = Module()
    current_func: Optional[Function] = None
    current_block: Optional[Block] = None

    for line in text.split('\n'):
        inst = parse_line(line)
        if inst is None:
            continue

        op = inst.opcode

        if op == 'OpCapability':
            module.capabilities.append(inst.operands[0] if inst.operands else '')
        elif op == 'OpMemoryModel':
            if len(inst.operands) >= 2:
                module.memory_model = (inst.operands[0], inst.operands[1])
        elif op == 'OpEntryPoint':
            module.entry_points.append(inst)
        elif op == 'OpName':
            if len(inst.operands) >= 2:
                module.names[inst.operands[0]] = inst.operands[1].strip('"')
        elif op == 'OpDecorate':
            tid = inst.operands[0] if inst.operands else ''
            module.decorations.setdefault(tid, []).append(inst.operands[1:])
        elif op.startswith('OpType') and inst.result_id:
            module.types[inst.result_id] = inst
        elif op in ('OpConstant', 'OpConstantTrue', 'OpConstantFalse',
                     'OpConstantNull', 'OpConstantComposite') and inst.result_id:
            module.constants[inst.result_id] = inst
        elif op == 'OpVariable' and inst.result_id:
            module.variables[inst.result_id] = inst
        elif op == 'OpFunction' and inst.result_id:
            func = Function(
                func_id=inst.result_id,
                return_type=inst.type_id,
                func_type=inst.operands[-1] if inst.operands else None,
            )
            current_func = func
            current_block = None
            module.functions[inst.result_id] = func
        elif op == 'OpFunctionParameter':
            if current_func:
                current_func.params.append(inst)
        elif op == 'OpFunctionEnd':
            current_func = None
            current_block = None
        elif op == 'OpLabel' and inst.result_id:
            if current_func:
                block = Block(label=inst.result_id)
                current_block = block
                current_func.blocks[inst.result_id] = block
                current_func.block_order.append(inst.result_id)
                if current_func.entry is None:
                    current_func.entry = inst.result_id
        elif current_block is not None:
            if op in ('OpSelectionMerge', 'OpLoopMerge'):
                current_block.merge = inst
            elif op in TERMINATOR_OPCODES:
                current_block.terminator = inst
                if op == 'OpBranch':
                    current_block.succs = [inst.operands[0]]
                elif op == 'OpBranchConditional':
                    current_block.succs = [inst.operands[1], inst.operands[2]]
                elif op == 'OpSwitch':
                    targets = []
                    if len(inst.operands) >= 2:
                        targets.append(inst.operands[1])
                    for i in range(2, len(inst.operands), 2):
                        if i + 1 < len(inst.operands):
                            t = inst.operands[i + 1]
                            if t not in targets:
                                targets.append(t)
                    current_block.succs = targets
            elif op == 'OpPhi':
                current_block.phis.append(inst)
            else:
                current_block.body.append(inst)

    for func in module.functions.values():
        for bid, block in func.blocks.items():
            for s in block.succs:
                if s in func.blocks:
                    func.blocks[s].preds.append(bid)

    return module


# ─── Analysis Engine ────────────────────────────────────────────────────────

class AnalysisEngine:
    """Worklist-based static value propagation for SPIR-V."""

    def __init__(self, module: Module):
        self.module = module
        self.lattice: Dict[str, LatticeValue] = {}
        self.exec_edges: Set[Tuple[str, str]] = set()
        self.exec_blocks: Set[str] = set()
        self.cfg_work: List[str] = []
        self.ssa_work: List[Tuple[Block, Instruction]] = []
        self.uses: Dict[str, List[Tuple[Block, Instruction]]] = {}
        self.func: Optional[Function] = None

    def get_val(self, vid: str) -> LatticeValue:
        return self.lattice.get(vid, Top())

    def set_val(self, vid: str, new_val: LatticeValue) -> bool:
        old = self.lattice.get(vid, Top())
        if isinstance(old, Bottom):
            return False
        if isinstance(new_val, Top):
            return False

        changed = False
        if isinstance(old, Top):
            self.lattice[vid] = new_val
            changed = True
        elif isinstance(old, Const) and isinstance(new_val, Const):
            if old.value != new_val.value:
                self.lattice[vid] = Bottom()
                changed = True
        elif isinstance(old, Const) and isinstance(new_val, Bottom):
            self.lattice[vid] = Bottom()
            changed = True

        if changed and vid in self.uses:
            for block, inst in self.uses[vid]:
                if block.label in self.exec_blocks:
                    self.ssa_work.append((block, inst))
        return changed

    def build_uses(self):
        if self.func is None:
            return
        for block in self.func.blocks.values():
            all_insts = list(block.phis) + list(block.body)
            if block.terminator:
                all_insts.append(block.terminator)
            for inst in all_insts:
                for op in inst.operands:
                    if op.startswith('%'):
                        self.uses.setdefault(op, []).append((block, inst))

    def eval_constant(self, inst: Instruction) -> Optional[Any]:
        if inst.opcode == 'OpConstantTrue':
            return True
        if inst.opcode == 'OpConstantFalse':
            return False
        if inst.opcode == 'OpConstantNull':
            return 0
        if inst.opcode == 'OpConstant':
            type_inst = self.module.types.get(inst.type_id)
            if type_inst:
                if type_inst.opcode == 'OpTypeInt':
                    raw = int(inst.operands[0])
                    width = int(type_inst.operands[0])
                    signed = (int(type_inst.operands[1])
                              if len(type_inst.operands) > 1 else 0)
                    if signed and raw >= (1 << (width - 1)):
                        raw -= (1 << width)
                    return raw
                if type_inst.opcode == 'OpTypeFloat':
                    return float(inst.operands[0])
                if type_inst.opcode == 'OpTypeBool':
                    return bool(int(inst.operands[0]))
            try:
                return int(inst.operands[0])
            except (ValueError, IndexError):
                try:
                    return float(inst.operands[0])
                except (ValueError, IndexError):
                    return None
        return None

    def process_phi(self, block: Block, inst: Instruction):
        result = Top()
        for i in range(0, len(inst.operands), 2):
            if i + 1 >= len(inst.operands):
                break
            val_id = inst.operands[i]
            pred_id = inst.operands[i + 1]
            if (pred_id, block.label) in self.exec_edges:
                val = self.get_val(val_id)
                result = lattice_meet(result, val)
        self.set_val(inst.result_id, result)

    def process_inst(self, block: Block, inst: Instruction):
        if inst.result_id is None:
            return

        op = inst.opcode

        if op == 'OpPhi':
            self.process_phi(block, inst)
            return

        if op == 'OpCopyObject':
            self.set_val(inst.result_id, self.get_val(inst.operands[0]))
            return

        if op == 'OpLoad':
            self.set_val(inst.result_id, Bottom())
            return

        if op == 'OpSelect':
            cond = self.get_val(inst.operands[0])
            if isinstance(cond, Top):
                return
            a_val = self.get_val(inst.operands[1])
            b_val = self.get_val(inst.operands[2])
            if isinstance(cond, Const):
                self.set_val(inst.result_id, a_val if cond.value else b_val)
            else:
                self.set_val(inst.result_id, lattice_meet(a_val, b_val))
            return

        if op in ('OpSNegate', 'OpFNegate'):
            v = self.get_val(inst.operands[0])
            if isinstance(v, Top):
                return
            if isinstance(v, Bottom):
                self.set_val(inst.result_id, Bottom())
                return
            self.set_val(inst.result_id, Const(-v.value))
            return

        if op == 'OpLogicalNot':
            v = self.get_val(inst.operands[0])
            if isinstance(v, Top):
                return
            if isinstance(v, Bottom):
                self.set_val(inst.result_id, Bottom())
                return
            self.set_val(inst.result_id, Const(not v.value))
            return

        if op in ('OpIAdd', 'OpISub', 'OpIMul', 'OpSDiv',
                  'OpFAdd', 'OpFSub', 'OpFMul', 'OpFDiv'):
            if len(inst.operands) < 2:
                self.set_val(inst.result_id, Bottom())
                return
            a = self.get_val(inst.operands[0])
            b = self.get_val(inst.operands[1])
            if isinstance(a, Top) or isinstance(b, Top):
                return
            if isinstance(a, Bottom) or isinstance(b, Bottom):
                self.set_val(inst.result_id, Bottom())
                return
            _ops = {
                'OpIAdd': lambda x, y: x + y,
                'OpISub': lambda x, y: x - y,
                'OpIMul': lambda x, y: x * y,
                'OpSDiv': lambda x, y: (x // y if y != 0 else None),
                'OpFAdd': lambda x, y: x + y,
                'OpFSub': lambda x, y: x - y,
                'OpFMul': lambda x, y: x * y,
                'OpFDiv': lambda x, y: (x / y if y != 0 else None),
            }
            fn = _ops.get(op)
            if fn:
                r = fn(a.value, b.value)
                self.set_val(inst.result_id, Const(r) if r is not None else Bottom())
            else:
                self.set_val(inst.result_id, Bottom())
            return

        if op in ('OpSGreaterThan', 'OpSLessThan',
                  'OpSGreaterThanEqual', 'OpSLessThanEqual',
                  'OpIEqual', 'OpINotEqual'):
            if len(inst.operands) < 2:
                self.set_val(inst.result_id, Bottom())
                return
            a = self.get_val(inst.operands[0])
            b = self.get_val(inst.operands[1])
            if isinstance(a, Top) or isinstance(b, Top):
                return
            if isinstance(a, Bottom) or isinstance(b, Bottom):
                self.set_val(inst.result_id, Bottom())
                return
            _cmp = {
                'OpSGreaterThan': lambda x, y: x > y,
                'OpSLessThan': lambda x, y: x < y,
                'OpSGreaterThanEqual': lambda x, y: x >= y,
                'OpSLessThanEqual': lambda x, y: x <= y,
                'OpIEqual': lambda x, y: x == y,
                'OpINotEqual': lambda x, y: x != y,
            }
            fn = _cmp.get(op)
            if fn:
                self.set_val(inst.result_id, Const(fn(a.value, b.value)))
            else:
                self.set_val(inst.result_id, Bottom())
            return

        if op in ('OpLogicalAnd', 'OpLogicalOr'):
            if len(inst.operands) < 2:
                self.set_val(inst.result_id, Bottom())
                return
            a = self.get_val(inst.operands[0])
            b = self.get_val(inst.operands[1])
            if isinstance(a, Top) or isinstance(b, Top):
                return
            if isinstance(a, Bottom) or isinstance(b, Bottom):
                self.set_val(inst.result_id, Bottom())
                return
            if op == 'OpLogicalAnd':
                self.set_val(inst.result_id, Const(bool(a.value and b.value)))
            else:
                self.set_val(inst.result_id, Const(bool(a.value or b.value)))
            return

        self.set_val(inst.result_id, Bottom())

    def process_terminator(self, block: Block):
        term = block.terminator
        if term is None:
            return

        if term.opcode == 'OpBranch':
            self.add_edge(block.label, term.operands[0])

        elif term.opcode == 'OpBranchConditional':
            cond = self.get_val(term.operands[0])
            t_label = term.operands[1]
            f_label = term.operands[2]
            if isinstance(cond, Const):
                if cond.value:
                    self.add_edge(block.label, t_label)
                else:
                    self.add_edge(block.label, f_label)
            else:
                self.add_edge(block.label, t_label)
                self.add_edge(block.label, f_label)

        elif term.opcode == 'OpSwitch':
            selector = self.get_val(term.operands[0])
            default_label = term.operands[1]

            if isinstance(selector, Const):
                found = False
                for i in range(2, len(term.operands), 2):
                    if i + 1 >= len(term.operands):
                        break
                    case_val = int(term.operands[i])
                    case_label = term.operands[i + 1]
                    if case_val == selector.value:
                        self.add_edge(block.label, case_label)
                        found = True
                        break
                if not found:
                    self.add_edge(block.label, default_label)
            else:
                self.add_edge(block.label, default_label)
                for i in range(2, len(term.operands), 2):
                    if i + 1 < len(term.operands):
                        self.add_edge(block.label, term.operands[i + 1])

    def add_edge(self, from_id: str, to_id: str):
        edge = (from_id, to_id)
        if edge in self.exec_edges:
            return
        self.exec_edges.add(edge)

        if to_id not in self.exec_blocks:
            self.exec_blocks.add(to_id)
            self.cfg_work.append(to_id)
        else:
            if self.func and to_id in self.func.blocks:
                block = self.func.blocks[to_id]
                for phi in block.phis:
                    self.ssa_work.append((block, phi))

    def process_block(self, block: Block):
        for phi in block.phis:
            self.process_phi(block, phi)
        for inst in block.body:
            self.process_inst(block, inst)
        self.process_terminator(block)

    def find_store(self, target_id: str) -> Optional[str]:
        if self.func is None:
            return None
        for bid in self.func.block_order:
            if bid not in self.exec_blocks:
                continue
            block = self.func.blocks[bid]
            for inst in block.body:
                if (inst.opcode == 'OpStore'
                        and inst.operands
                        and inst.operands[0] == target_id):
                    return inst.operands[1] if len(inst.operands) > 1 else None
        return None

    def run(self) -> Dict[str, Any]:
        if not self.module.entry_points:
            return {}

        ep = self.module.entry_points[0]
        func_id = ep.operands[1]
        self.func = self.module.functions.get(func_id)
        if self.func is None:
            return {}

        for cid, cinst in self.module.constants.items():
            v = self.eval_constant(cinst)
            if v is not None:
                self.lattice[cid] = Const(v)

        self.build_uses()

        if self.func.entry:
            self.exec_blocks.add(self.func.entry)
            self.cfg_work.append(self.func.entry)

        max_iter = 50000
        iterations = 0
        while (self.cfg_work or self.ssa_work) and iterations < max_iter:
            iterations += 1
            if self.cfg_work:
                bid = self.cfg_work.pop(0)
                if bid in self.func.blocks:
                    self.process_block(self.func.blocks[bid])
            elif self.ssa_work:
                block, inst = self.ssa_work.pop(0)
                if inst.opcode == 'OpPhi':
                    self.process_phi(block, inst)
                elif inst.opcode in TERMINATOR_OPCODES:
                    self.process_terminator(block)
                else:
                    self.process_inst(block, inst)

        results: Dict[str, Any] = {}
        for vid, vinst in self.module.variables.items():
            storage = vinst.operands[0] if vinst.operands else ''
            if storage == 'Output':
                name = self.module.names.get(vid, vid.lstrip('%'))
                stored_val_id = self.find_store(vid)
                if stored_val_id is not None:
                    val = self.get_val(stored_val_id)
                    if isinstance(val, Const):
                        results[name] = val.value
                    else:
                        results[name] = None
                else:
                    results[name] = None

        return results


# ─── Entry Point ────────────────────────────────────────────────────────────

def load_shader_text(path: str) -> str:
    """Load shader as text, using spirv-dis for binary .spv files."""
    if path.endswith('.spv'):
        result = subprocess.run(
            ['spirv-dis', '--raw-id', path],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            result = subprocess.run(
                ['spirv-dis', path],
                capture_output=True, text=True
            )
        if result.returncode != 0:
            print(f"spirv-dis failed: {result.stderr}", file=sys.stderr)
            sys.exit(1)
        return result.stdout
    else:
        with open(path, 'r') as f:
            return f.read()


def main():
    if len(sys.argv) < 2:
        print("Usage: analyze.py <input.spvasm|input.spv>", file=sys.stderr)
        sys.exit(1)

    text = load_shader_text(sys.argv[1])
    module = parse_module(text)
    engine = AnalysisEngine(module)
    results = engine.run()
    print(json.dumps(results))


if __name__ == '__main__':
    main()
