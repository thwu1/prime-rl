"""Score computation for assembly alignment pairs."""

GAP_PENALTY = 10
MNEMONIC_MISMATCH_PENALTY = 8


def compute_score(alignment):
    """Compute total alignment score from list of (target_instr|None, candidate_instr|None)."""
    total = 0
    for t_instr, c_instr in alignment:
        if t_instr is None or c_instr is None:
            total += GAP_PENALTY
        else:
            t_mn, t_ops = t_instr
            c_mn, c_ops = c_instr
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
