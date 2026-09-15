"""x86-64 register classification and optimal mapping for decompilation matching.

Fixed version:
 - Added %r8-%r15 register families
 - Fixed apply_mapping to use simultaneous substitution (re.sub) instead of
   sequential str.replace which corrupts cyclic mappings
"""
import re
import itertools
from parser import extract_registers

RENAMEABLE_REGISTERS = {
    '%rax', '%eax', '%ax', '%al', '%ah',
    '%rbx', '%ebx', '%bx', '%bl', '%bh',
    '%rcx', '%ecx', '%cx', '%cl', '%ch',
    '%rdx', '%edx', '%dx', '%dl', '%dh',
    '%rsi', '%esi', '%si', '%sil',
    '%rdi', '%edi', '%di', '%dil',
    '%rbp', '%ebp', '%bp', '%bpl',
    '%r8', '%r8d', '%r8w', '%r8b',
    '%r9', '%r9d', '%r9w', '%r9b',
    '%r10', '%r10d', '%r10w', '%r10b',
    '%r11', '%r11d', '%r11w', '%r11b',
    '%r12', '%r12d', '%r12w', '%r12b',
    '%r13', '%r13d', '%r13w', '%r13b',
    '%r14', '%r14d', '%r14w', '%r14b',
    '%r15', '%r15d', '%r15w', '%r15b',
}

REGISTER_FAMILIES = {
    '%rax': ['%rax', '%eax', '%ax', '%al', '%ah'],
    '%rbx': ['%rbx', '%ebx', '%bx', '%bl', '%bh'],
    '%rcx': ['%rcx', '%ecx', '%cx', '%cl', '%ch'],
    '%rdx': ['%rdx', '%edx', '%dx', '%dl', '%dh'],
    '%rsi': ['%rsi', '%esi', '%si', '%sil'],
    '%rdi': ['%rdi', '%edi', '%di', '%dil'],
    '%rbp': ['%rbp', '%ebp', '%bp', '%bpl'],
    '%r8': ['%r8', '%r8d', '%r8w', '%r8b'],
    '%r9': ['%r9', '%r9d', '%r9w', '%r9b'],
    '%r10': ['%r10', '%r10d', '%r10w', '%r10b'],
    '%r11': ['%r11', '%r11d', '%r11w', '%r11b'],
    '%r12': ['%r12', '%r12d', '%r12w', '%r12b'],
    '%r13': ['%r13', '%r13d', '%r13w', '%r13b'],
    '%r14': ['%r14', '%r14d', '%r14w', '%r14b'],
    '%r15': ['%r15', '%r15d', '%r15w', '%r15b'],
}


def get_family(reg):
    """Get the canonical (64-bit) family name for a register."""
    for family, members in REGISTER_FAMILIES.items():
        if reg in members:
            return family
    return None


def get_renameable_families(instructions):
    """Get set of renameable register families used in the instructions."""
    families = set()
    for _, operands in instructions:
        for op in operands:
            for reg in extract_registers(op):
                fam = get_family(reg)
                if fam is not None:
                    families.add(fam)
    return families


def build_family_mapping(family_from, family_to):
    """Build a complete register mapping between two register families."""
    mapping = {}
    members_from = REGISTER_FAMILIES.get(family_from, [family_from])
    members_to = REGISTER_FAMILIES.get(family_to, [family_to])
    for mf, mt in zip(members_from, members_to):
        mapping[mf] = mt
    return mapping


def _apply_mapping_to_operand(op, mapping):
    """Apply register mapping to a single operand via simultaneous substitution."""
    def repl(m):
        reg = m.group(0)
        return mapping.get(reg, reg)
    return re.sub(r'%\w+', repl, op)


def apply_mapping(instructions, mapping):
    """Apply register mapping to all instructions (simultaneous substitution)."""
    result = []
    for mnemonic, operands in instructions:
        new_ops = [_apply_mapping_to_operand(op, mapping) for op in operands]
        result.append((mnemonic, new_ops))
    return result


def _compute_alignment_cost(target, candidate, mapping):
    """Quick positional alignment cost for evaluating a mapping."""
    mapped = apply_mapping(candidate, mapping)
    cost = 0
    for i in range(min(len(target), len(mapped))):
        t_mn, t_ops = target[i]
        c_mn, c_ops = mapped[i]
        if t_mn != c_mn:
            cost += 8
        else:
            for j in range(max(len(t_ops), len(c_ops))):
                to = t_ops[j] if j < len(t_ops) else ''
                co = c_ops[j] if j < len(c_ops) else ''
                if to != co:
                    cost += 2
    cost += abs(len(target) - len(candidate)) * 10
    return cost


def find_optimal_mapping(target, candidate):
    """Find the register mapping from candidate to target that minimizes cost."""
    target_families = get_renameable_families(target)
    cand_families = get_renameable_families(candidate)

    cand_family_list = sorted(cand_families)
    all_families = sorted(target_families | cand_families)

    if not cand_family_list:
        return {}

    best_mapping = {}
    best_cost = float('inf')

    for perm in itertools.permutations(all_families, len(cand_family_list)):
        mapping = {}
        for cf, tf in zip(cand_family_list, perm):
            if cf != tf:
                mapping.update(build_family_mapping(cf, tf))

        cost = _compute_alignment_cost(target, candidate, mapping)
        if cost < best_cost:
            best_cost = cost
            best_mapping = mapping

    return best_mapping
