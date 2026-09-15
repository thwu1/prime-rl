
"""IR data structures and loader for the register allocator task.

This module defines a simplified three-address code (TAC) intermediate
representation with two register classes (general-purpose and XMM floating-point),
along with a JSON-based loader.

Register class constraints:
  - GP:  12 available physical registers (r0 .. r11)
  - XMM: 14 available physical registers (xmm0 .. xmm13)

An allocator must map every virtual register to either a physical register
of the correct class or a stack slot (named "stack_0", "stack_1", ...).
"""

import json
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Set, Tuple, Union

# ---------------------------------------------------------------------------
# Physical register definitions
# ---------------------------------------------------------------------------

GP_K = 12
XMM_K = 14

GP_REGS: List[str] = [f"r{i}" for i in range(GP_K)]
XMM_REGS: List[str] = [f"xmm{i}" for i in range(XMM_K)]


def k_for_class(reg_class: str) -> int:
    """Return k (number of available physical registers) for a register class."""
    if reg_class == "gp":
        return GP_K
    elif reg_class == "xmm":
        return XMM_K
    else:
        raise ValueError(f"Unknown register class: {reg_class}")


def regs_for_class(reg_class: str) -> List[str]:
    """Return the list of physical register names for a register class."""
    if reg_class == "gp":
        return list(GP_REGS)
    elif reg_class == "xmm":
        return list(XMM_REGS)
    else:
        raise ValueError(f"Unknown register class: {reg_class}")


# ---------------------------------------------------------------------------
# IR data structures
# ---------------------------------------------------------------------------

@dataclass
class Instruction:
    """A single IR instruction.

    Instruction formats by opcode:
      const     : dst = val                  (no source registers)
      copy      : dst = src1                 (candidate for coalescing)
      add/sub/mul/div/mod : dst = src1 OP src2
      neg/not   : dst = OP src1
      eq/ne/lt/le/gt/ge   : dst = (src1 CMP src2) ? 1 : 0
      int2dbl   : dst(xmm) = convert src1(gp)
      dbl2int   : dst(gp)  = convert src1(xmm)
      ret       : return src1
      jump      : goto target
      cbranch   : if src1 goto true_target else false_target
    """
    op: str
    dst: Optional[str] = None
    dst_class: Optional[str] = None
    src1: Optional[str] = None
    src2: Optional[str] = None
    val: Optional[Union[int, float]] = None
    target: Optional[str] = None
    true_target: Optional[str] = None
    false_target: Optional[str] = None

    def defs(self) -> Set[str]:
        """Virtual registers defined (written) by this instruction."""
        if self.dst is not None:
            return {self.dst}
        return set()

    def uses(self) -> Set[str]:
        """Virtual registers used (read) by this instruction."""
        if self.op == "const":
            return set()
        if self.op == "jump":
            return set()
        if self.op in ("ret", "cbranch"):
            if self.src1 is not None:
                return {self.src1}
            return set()
        result: Set[str] = set()
        if self.src1 is not None:
            result.add(self.src1)
        if self.src2 is not None:
            result.add(self.src2)
        return result


@dataclass
class Block:
    """A basic block in the control-flow graph."""
    label: str
    instructions: List[Instruction] = field(default_factory=list)
    successors: List[str] = field(default_factory=list)
    predecessors: List[str] = field(default_factory=list)


@dataclass
class Function:
    """A function in the IR program."""
    name: str
    params: List[Tuple[str, str]]           # [(vreg_name, reg_class), ...]
    return_class: str                        # "gp" or "xmm"
    blocks: Dict[str, Block] = field(default_factory=dict)
    block_order: List[str] = field(default_factory=list)
    vreg_classes: Dict[str, str] = field(default_factory=dict)  # vreg -> class


@dataclass
class Program:
    """An IR program containing one or more functions."""
    name: str
    functions: Dict[str, Function] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# JSON loader
# ---------------------------------------------------------------------------

def load_program(path: str) -> Program:
    """Load an IR program from a JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    prog = Program(name=data["name"])

    for fdata in data["functions"]:
        func = Function(
            name=fdata["name"],
            params=[(p["name"], p["class"]) for p in fdata["params"]],
            return_class=fdata["return_class"],
        )

        # Register parameter vreg classes
        for pname, pclass in func.params:
            func.vreg_classes[pname] = pclass

        # Parse blocks
        for bdata in fdata["blocks"]:
            label = bdata["label"]
            block = Block(label=label)
            func.block_order.append(label)

            for idata in bdata["instrs"]:
                instr = Instruction(op=idata["op"])
                if "dst" in idata:
                    instr.dst = idata["dst"]
                if "class" in idata:
                    instr.dst_class = idata["class"]
                if "src1" in idata:
                    instr.src1 = idata["src1"]
                if "src2" in idata:
                    instr.src2 = idata["src2"]
                if "val" in idata:
                    instr.val = idata["val"]
                if "target" in idata:
                    instr.target = idata["target"]
                if "true_target" in idata:
                    instr.true_target = idata["true_target"]
                if "false_target" in idata:
                    instr.false_target = idata["false_target"]

                # Record vreg class from definitions
                if instr.dst and instr.dst_class:
                    func.vreg_classes[instr.dst] = instr.dst_class

                block.instructions.append(instr)

            # Determine successor blocks from the last instruction
            if block.instructions:
                last = block.instructions[-1]
                if last.op == "jump" and last.target:
                    block.successors = [last.target]
                elif last.op == "cbranch":
                    block.successors = [last.true_target, last.false_target]
                elif last.op == "ret":
                    block.successors = []

            func.blocks[label] = block

        # Build predecessor lists
        for label, block in func.blocks.items():
            for succ_label in block.successors:
                if succ_label in func.blocks:
                    func.blocks[succ_label].predecessors.append(label)

        prog.functions[func.name] = func

    return prog
