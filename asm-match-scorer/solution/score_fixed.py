"""Score computation for assembly alignment pairs.

Fixed version: normalizes x86 instruction aliases before comparison
so that je/jz, jne/jnz, etc. are treated as the same mnemonic.
"""

GAP_PENALTY = 10
MNEMONIC_MISMATCH_PENALTY = 8

# x86 instruction aliases — map to a canonical form
INSTRUCTION_ALIASES = {
    'je': 'jz',
    'jne': 'jnz',
    'sete': 'setz',
    'setne': 'setnz',
    'cmove': 'cmovz',
    'cmovne': 'cmovnz',
    'jb': 'jc',
    'jnae': 'jc',
    'jae': 'jnc',
    'jnb': 'jnc',
    'ja': 'jnbe',
    'jbe': 'jna',
    'jl': 'jnge',
    'jge': 'jnl',
    'jg': 'jnle',
    'jle': 'jng',
    'setle': 'setng',
    'setge': 'setnl',
    'setl': 'setnge',
    'setg': 'setnle',
    'cmovl': 'cmovnge',
    'cmovge': 'cmovnl',
    'cmovle': 'cmovng',
    'cmovg': 'cmovnle',
    'cmovb': 'cmovc',
    'cmovnae': 'cmovc',
    'cmovae': 'cmovnc',
    'cmovnb': 'cmovnc',
    'cmova': 'cmovnbe',
    'cmovbe': 'cmovna',
}


def _normalize_mnemonic(mn):
    """Normalize instruction mnemonic to canonical form."""
    return INSTRUCTION_ALIASES.get(mn, mn)


def compute_score(alignment):
    """Compute total alignment score from list of (target_instr|None, candidate_instr|None)."""
    total = 0
    for t_instr, c_instr in alignment:
        if t_instr is None or c_instr is None:
            total += GAP_PENALTY
        else:
            t_mn, t_ops = t_instr
            c_mn, c_ops = c_instr
            t_mn = _normalize_mnemonic(t_mn)
            c_mn = _normalize_mnemonic(c_mn)
            if t_mn != c_mn:
                total += MNEMONIC_MISMATCH_PENALTY
            else:
                n_ops = max(len(t_ops), len(c_ops))
                diffs = 0
                for i in range(n_ops):
                    to = t_ops[i] if i < len(t_ops) else ''
                    co = c_ops[i] if i < len(c_ops) else ''
                    if to != co:
                        diffs += 1
                total += 2 * diffs
    return total
