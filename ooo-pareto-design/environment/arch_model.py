"""Area cost model for out-of-order processor configurations.

This module provides the area scoring function used by the hardware design team
for comparing processor configurations in the OoO design space exploration.
"""


def compute_area(width: int, rob_size: int, num_int_regs: int, num_fp_regs: int) -> int:
    """Compute the area score for a processor configuration.

    The model accounts for:
    - Width-proportional structures (issue queues, rename map tables, bypass
      networks) that scale with both pipeline width and the number of tracked
      resource entries (ROB slots, physical registers).
    - Width-independent overhead: per-stage pipeline registers (4 per width
      unit) and base storage costs for the ROB and register files.

    Args:
        width: Pipeline width (fetch/decode/rename/issue/writeback/commit).
        rob_size: Number of reorder buffer entries.
        num_int_regs: Number of physical integer registers.
        num_fp_regs: Number of physical floating-point registers.

    Returns:
        Integer area score (unitless, higher means larger silicon area).
    """
    return (
        width * (2 * rob_size + num_int_regs + num_fp_regs)
        + 4 * width
        + 2 * rob_size
        + num_int_regs
        + num_fp_regs
    )
