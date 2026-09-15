
"""CFG Builder: constructs control-flow graphs from parsed TAC functions."""

from dataclasses import dataclass, field
from typing import List, Dict, Set, Optional
from tac_parser import Instruction


@dataclass
class BasicBlock:
    id: int
    instructions: List[Instruction] = field(default_factory=list)
    successors: List[int] = field(default_factory=list)
    predecessors: List[int] = field(default_factory=list)
    label: Optional[str] = None


@dataclass
class CFG:
    blocks: Dict[int, BasicBlock] = field(default_factory=dict)
    entry_id: int = 0
    label_to_block: Dict[str, int] = field(default_factory=dict)

    def reachable_block_ids(self) -> Set[int]:
        """Return set of block IDs reachable from entry."""
        visited = set()
        worklist = [self.entry_id]
        while worklist:
            bid = worklist.pop()
            if bid in visited:
                continue
            visited.add(bid)
            if bid in self.blocks:
                for s in self.blocks[bid].successors:
                    if s not in visited:
                        worklist.append(s)
        return visited


def build_cfg(instructions: List[Instruction]) -> CFG:
    """Build a CFG from a list of instructions (within a single function).

    Splits instructions into basic blocks at:
    - LABEL instructions (start a new block)
    - After GOTO, IF...GOTO, IFFALSE...GOTO, RETURN instructions (end current block)
    """
    # Filter out func_start/func_end for CFG purposes, but keep params
    body = [i for i in instructions if i.kind not in ("func_start", "func_end")]

    if not body:
        cfg = CFG()
        b = BasicBlock(id=0)
        cfg.blocks[0] = b
        cfg.entry_id = 0
        return cfg

    # First pass: identify leaders (first instruction of each basic block)
    leaders = {0}  # First instruction is always a leader
    for idx, instr in enumerate(body):
        if instr.kind == "label":
            leaders.add(idx)
        if instr.kind in ("goto", "if_goto", "iffalse_goto", "return_val", "return_void"):
            if idx + 1 < len(body):
                leaders.add(idx + 1)

    # Sort leaders
    sorted_leaders = sorted(leaders)

    # Second pass: create basic blocks
    cfg = CFG()
    leader_to_bid = {}

    for i, leader_idx in enumerate(sorted_leaders):
        end_idx = sorted_leaders[i + 1] if i + 1 < len(sorted_leaders) else len(body)
        block = BasicBlock(id=i, instructions=body[leader_idx:end_idx])

        # Check if block starts with a label
        if block.instructions and block.instructions[0].kind == "label":
            block.label = block.instructions[0].label
            cfg.label_to_block[block.label] = i

        cfg.blocks[i] = block
        leader_to_bid[leader_idx] = i

    cfg.entry_id = leader_to_bid.get(0, 0)

    # Third pass: add edges
    for i, leader_idx in enumerate(sorted_leaders):
        block = cfg.blocks[i]
        if not block.instructions:
            continue

        last = block.instructions[-1]

        if last.kind == "goto":
            # Unconditional jump - edge only to target
            pass  # will be resolved below
        elif last.kind in ("if_goto", "iffalse_goto"):
            # Conditional branch - edge to target AND fallthrough
            next_idx = sorted_leaders[i + 1] if i + 1 < len(sorted_leaders) else None
            if next_idx is not None and next_idx in leader_to_bid:
                next_bid = leader_to_bid[next_idx]
                block.successors.append(next_bid)
                cfg.blocks[next_bid].predecessors.append(i)
        elif last.kind in ("return_val", "return_void"):
            # No successors
            pass
        else:
            # Fallthrough
            next_idx = sorted_leaders[i + 1] if i + 1 < len(sorted_leaders) else None
            if next_idx is not None and next_idx in leader_to_bid:
                next_bid = leader_to_bid[next_idx]
                block.successors.append(next_bid)
                cfg.blocks[next_bid].predecessors.append(i)

    # Resolve label-based edges
    for bid, block in cfg.blocks.items():
        if not block.instructions:
            continue
        last = block.instructions[-1]
        if last.kind in ("goto", "if_goto", "iffalse_goto"):
            if last.label in cfg.label_to_block:
                target_bid = cfg.label_to_block[last.label]
                block.successors.append(target_bid)
                cfg.blocks[target_bid].predecessors.append(bid)

    return cfg


def cfg_to_instructions(cfg: CFG, func_start: Instruction, func_end: Instruction,
                        params: List[Instruction]) -> List[Instruction]:
    """Linearize a CFG back to an instruction list, in block ID order.

    Only includes reachable blocks.
    """
    reachable = cfg.reachable_block_ids()
    result = [func_start] + params

    for bid in sorted(cfg.blocks.keys()):
        if bid not in reachable:
            continue
        block = cfg.blocks[bid]
        result.extend(block.instructions)

    result.append(func_end)
    return result
