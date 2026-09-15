#!/usr/bin/env python3

"""PTX Kernel Static Analyzer.

Parses NVIDIA PTX assembly and performs:
  - Control flow graph construction (with predicated branch handling)
  - Register liveness analysis (iterative backward dataflow)
  - Register pressure computation (backward scan)
  - RAW dependency analysis and critical path / ILP estimation
"""

import sys
import json
import re
from collections import defaultdict, deque


# ---------------------------------------------------------------------------
# Special register detection
# ---------------------------------------------------------------------------

_SPECIAL_PREFIX = re.compile(
    r'^%(?:tid|ctaid|ntid|nctaid|laneid|warpid|nwarpid|smid|nsmid|gridid|'
    r'lanemask_(?:eq|lt|le|gt|ge)|clock(?:64)?|pm\d+|'
    r'WARP_SZ|dynamic_smem_size|envreg\d+|SP|SPL)'
)


def is_special_reg(name: str) -> bool:
    """Return True for built-in GPU registers that should not be tracked."""
    return bool(_SPECIAL_PREFIX.match(name))


def extract_registers(s: str) -> set:
    """Extract general-purpose register names from an operand string."""
    regs = set()
    for m in re.finditer(r'%\w+(?:\.\w+)?', s):
        reg = m.group()
        if not is_special_reg(reg):
            regs.add(reg)
    return regs


# ---------------------------------------------------------------------------
# Operand parsing
# ---------------------------------------------------------------------------

def parse_operand_list(s: str) -> list:
    """Split a comma-separated operand string, respecting brackets."""
    s = s.strip()
    if not s:
        return []
    result = []
    depth = 0
    current: list[str] = []
    for c in s:
        if c == '[':
            depth += 1
            current.append(c)
        elif c == ']':
            depth -= 1
            current.append(c)
        elif c == ',' and depth == 0:
            result.append(''.join(current).strip())
            current = []
        else:
            current.append(c)
    if current:
        result.append(''.join(current).strip())
    return result


# ---------------------------------------------------------------------------
# Instruction representation
# ---------------------------------------------------------------------------

class Instruction:
    __slots__ = ('raw', 'predicate', 'opcode', 'operands', 'defs', 'uses')

    def __init__(self, raw: str, predicate: str | None, opcode: str,
                 operands: list[str]):
        self.raw = raw
        self.predicate = predicate
        self.opcode = opcode
        self.operands = operands
        self.defs: set[str] = set()
        self.uses: set[str] = set()
        self._classify()

    def _classify(self):
        # Predicate register is always a use.
        if self.predicate:
            self.uses.update(extract_registers(self.predicate))

        base = self.opcode.split('.')[0]

        if base == 'st':
            # Store instructions: all operands are uses, no defs.
            for op in self.operands:
                self.uses.update(extract_registers(op))
        elif base in ('bra', 'ret', 'bar', 'membar', 'fence'):
            # Control / synchronisation: no register operands.
            pass
        else:
            # General instruction: first operand is def, rest are uses.
            if self.operands:
                self.defs.update(extract_registers(self.operands[0]))
                for op in self.operands[1:]:
                    self.uses.update(extract_registers(op))

    @property
    def is_branch(self) -> bool:
        return self.opcode.split('.')[0] == 'bra'

    @property
    def is_conditional_branch(self) -> bool:
        return self.is_branch and self.predicate is not None

    @property
    def is_unconditional_branch(self) -> bool:
        return self.is_branch and self.predicate is None

    @property
    def is_ret(self) -> bool:
        return self.opcode.split('.')[0] == 'ret'

    @property
    def branch_target(self) -> str | None:
        if self.is_branch and self.operands:
            return self.operands[0]
        return None


# ---------------------------------------------------------------------------
# Basic block
# ---------------------------------------------------------------------------

class BasicBlock:
    __slots__ = ('name', 'instructions', 'successors', 'predecessors',
                 'gen', 'kill', 'live_in', 'live_out')

    def __init__(self, name: str):
        self.name = name
        self.instructions: list[Instruction] = []
        self.successors: list['BasicBlock'] = []
        self.predecessors: list['BasicBlock'] = []
        self.gen: set[str] = set()
        self.kill: set[str] = set()
        self.live_in: set[str] = set()
        self.live_out: set[str] = set()


# ---------------------------------------------------------------------------
# PTX parser
# ---------------------------------------------------------------------------

def _parse_instruction_line(line: str) -> Instruction:
    """Parse a single PTX instruction line (semicolons already stripped)."""
    line = line.strip()
    if line.endswith(';'):
        line = line[:-1].strip()

    predicate = None
    if line.startswith('@'):
        # Handle both @%pN and @!%pN (negated predicate) forms.
        m = re.match(r'@(!?%\w+(?:\.\w+)?)\s+', line)
        if m:
            predicate = m.group(1)
            line = line[m.end():]

    parts = line.split(None, 1)
    opcode = parts[0] if parts else ''
    operand_str = parts[1] if len(parts) > 1 else ''
    operands = parse_operand_list(operand_str)

    return Instruction(line, predicate, opcode, operands)


def parse_ptx(filename: str) -> tuple[str, list[BasicBlock]]:
    """Parse a PTX file into a kernel name and a list of BasicBlocks."""
    with open(filename) as f:
        lines = f.readlines()

    kernel_name: str | None = None
    blocks: list[BasicBlock] = []
    current_block: BasicBlock | None = None
    in_kernel = False
    brace_depth = 0

    for raw_line in lines:
        stripped = raw_line.strip()

        # Strip inline comments.
        comment_idx = stripped.find('//')
        if comment_idx >= 0:
            stripped = stripped[:comment_idx].strip()
        if not stripped:
            continue

        # Kernel name from .visible .entry.
        entry_m = re.match(r'\.visible\s+\.entry\s+(\w+)', stripped)
        if entry_m:
            kernel_name = entry_m.group(1)
            continue

        # Track braces.
        if stripped == '{':
            brace_depth += 1
            in_kernel = True
            continue
        if stripped == '}':
            brace_depth -= 1
            if brace_depth == 0:
                in_kernel = False
            continue

        if not in_kernel:
            continue

        # Skip directives inside kernel body.
        if stripped.startswith('.'):
            continue

        # Label? (handles both hand-written labels like BB0 and
        # compiler-generated labels like $L__BB0_1)
        label_m = re.match(r'^([\w$]+)\s*:\s*(.*)', stripped)
        if label_m:
            label = label_m.group(1)
            current_block = BasicBlock(label)
            blocks.append(current_block)
            rest = label_m.group(2).strip()
            if rest:
                instr = _parse_instruction_line(rest)
                if instr.opcode:
                    current_block.instructions.append(instr)
            continue

        # Instruction line — create implicit entry block if needed
        # (compiler-generated PTX may not label the first basic block).
        if current_block is None:
            current_block = BasicBlock("entry")
            blocks.append(current_block)
        instr = _parse_instruction_line(stripped)
        if instr.opcode:
            current_block.instructions.append(instr)

    return kernel_name or '', blocks


# ---------------------------------------------------------------------------
# CFG construction
# ---------------------------------------------------------------------------

def build_cfg(blocks: list[BasicBlock]) -> None:
    """Wire up successor / predecessor edges between basic blocks.

    Handles the LLVM pattern where a conditional branch is followed by an
    unconditional branch (both targets need edges), as well as the
    hand-written PTX pattern of a single conditional branch with
    fall-through.
    """
    block_map = {b.name: b for b in blocks}

    for i, block in enumerate(blocks):
        if not block.instructions:
            # Empty block falls through to next.
            if i + 1 < len(blocks):
                block.successors.append(blocks[i + 1])
                blocks[i + 1].predecessors.append(block)
            continue

        has_unconditional_branch = False
        has_ret = False

        # Scan ALL instructions — not just the last — to catch
        # conditional-then-unconditional branch pairs emitted by LLVM.
        for instr in block.instructions:
            if instr.is_branch:
                target = instr.branch_target
                if target and target in block_map:
                    block.successors.append(block_map[target])
                    block_map[target].predecessors.append(block)
                if instr.is_unconditional_branch:
                    has_unconditional_branch = True
            elif instr.is_ret:
                has_ret = True

        # Fall-through only when no unconditional branch or ret terminates
        # the block.
        if not has_unconditional_branch and not has_ret:
            if i + 1 < len(blocks):
                block.successors.append(blocks[i + 1])
                blocks[i + 1].predecessors.append(block)


# ---------------------------------------------------------------------------
# Liveness analysis
# ---------------------------------------------------------------------------

def _compute_gen_kill(block: BasicBlock) -> None:
    """Compute gen (upward-exposed uses) and kill (all defs) for a block."""
    defined: set[str] = set()
    gen: set[str] = set()

    for instr in block.instructions:
        for reg in instr.uses:
            if reg not in defined:
                gen.add(reg)
        defined.update(instr.defs)

    block.gen = gen
    block.kill = defined


def compute_liveness(blocks: list[BasicBlock]) -> None:
    """Iterative backward dataflow for register liveness."""
    for block in blocks:
        _compute_gen_kill(block)

    changed = True
    while changed:
        changed = False
        for block in reversed(blocks):
            new_out: set[str] = set()
            for succ in block.successors:
                new_out |= succ.live_in

            new_in = block.gen | (new_out - block.kill)

            if new_in != block.live_in or new_out != block.live_out:
                changed = True
                block.live_in = new_in
                block.live_out = new_out


# ---------------------------------------------------------------------------
# Register pressure
# ---------------------------------------------------------------------------

def compute_register_pressure(block: BasicBlock) -> int:
    """Max simultaneously live registers (backward scan)."""
    live = set(block.live_out)
    pressure = len(live)

    for instr in reversed(block.instructions):
        for d in instr.defs:
            live.discard(d)
        for u in instr.uses:
            live.add(u)
        pressure = max(pressure, len(live))

    return pressure


# ---------------------------------------------------------------------------
# RAW dependencies & critical path
# ---------------------------------------------------------------------------

def compute_raw_deps(block: BasicBlock) -> list[tuple[int, int]]:
    """Build RAW (read-after-write) dependency edges within a basic block."""
    last_def: dict[str, int] = {}
    edges: list[tuple[int, int]] = []

    for i, instr in enumerate(block.instructions):
        for reg in instr.uses:
            if reg in last_def:
                edges.append((last_def[reg], i))
        for reg in instr.defs:
            last_def[reg] = i

    return edges


def compute_critical_path(n: int, edges: list[tuple[int, int]]) -> int:
    """Longest path in dependency DAG (in instruction count)."""
    if n == 0:
        return 0

    adj: dict[int, list[int]] = defaultdict(list)
    in_deg = [0] * n
    for u, v in edges:
        adj[u].append(v)
        in_deg[v] += 1

    # Kahn's algorithm with longest-path relaxation.
    queue: deque[int] = deque()
    for i in range(n):
        if in_deg[i] == 0:
            queue.append(i)

    dist = [1] * n  # every instruction is at least a 1-instruction path

    while queue:
        u = queue.popleft()
        for v in adj[u]:
            dist[v] = max(dist[v], dist[u] + 1)
            in_deg[v] -= 1
            if in_deg[v] == 0:
                queue.append(v)

    return max(dist)


# ---------------------------------------------------------------------------
# Top-level analysis
# ---------------------------------------------------------------------------

def analyze(filename: str) -> dict:
    kernel_name, blocks = parse_ptx(filename)
    build_cfg(blocks)
    compute_liveness(blocks)

    cfg_edges: list[list[str]] = []
    for block in blocks:
        for succ in block.successors:
            cfg_edges.append([block.name, succ.name])

    result = {
        'kernel_name': kernel_name,
        'num_basic_blocks': len(blocks),
        'cfg_edges': cfg_edges,
        'basic_blocks': {},
    }

    for block in blocks:
        n = len(block.instructions)
        pressure = compute_register_pressure(block)
        raw_edges = compute_raw_deps(block)
        cp = compute_critical_path(n, raw_edges)
        ilp = round(n / cp, 4) if cp > 0 else 0.0

        result['basic_blocks'][block.name] = {
            'num_instructions': n,
            'live_in': sorted(block.live_in),
            'live_out': sorted(block.live_out),
            'max_register_pressure': pressure,
            'critical_path_length': cp,
            'ilp': ilp,
        }

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python3 ptx_analyzer.py <ptx_file>', file=sys.stderr)
        sys.exit(1)
    print(json.dumps(analyze(sys.argv[1]), indent=2))
