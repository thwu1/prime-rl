"""RISC-V RVFI Trace Validator

Validates RV32I instruction traces against the RISC-V ISA specification
using the RVFI (RISC-V Formal Interface) protocol.
"""

from .spec_checker import check_instruction, Violation
from .consistency import ConsistencyChecker


def validate_trace(trace):
    """Validate a complete RVFI instruction trace.

    Args:
        trace: List of RVFI instruction records (dicts).

    Returns:
        List of (index, violations) tuples for instructions with violations.
    """
    checker = ConsistencyChecker()
    results = []
    for i, rvfi in enumerate(trace):
        spec_violations = check_instruction(rvfi)
        consistency_violations = checker.check_and_update(rvfi)
        all_violations = spec_violations + consistency_violations
        if all_violations:
            results.append((i, all_violations))
    return results
