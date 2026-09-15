"""RVFI Cross-Instruction Consistency Checker

Tracks register shadow state and PC flow across an instruction trace
to detect consistency violations between successive instructions.
Implements the shadow register and shadow PC concepts from the
riscv-formal monitor generator.
"""

from .spec_checker import Violation
from .decoder import mask32


class ConsistencyChecker:
    """Checks cross-instruction consistency of RVFI traces.

    Maintains shadow copies of the integer register file and program
    counter. Verifies that register reads match previous writes and
    that PC flow is continuous (accounting for branches, jumps, and
    traps).
    """

    def __init__(self):
        self.shadow_regs = [0] * 32
        self.shadow_regs_valid = [False] * 32
        self.shadow_regs_valid[0] = True  # x0 is always valid and zero
        self.shadow_pc = None
        self.shadow_pc_valid = False

    def check_and_update(self, rvfi):
        """Check consistency of this instruction and update shadow state.

        Args:
            rvfi: RVFI instruction record dict.

        Returns:
            List of Violation objects.
        """
        violations = []

        # -- PC continuity check --
        if self.shadow_pc_valid and rvfi['pc_rdata'] != self.shadow_pc:
            violations.append(Violation(
                'pc_rdata', self.shadow_pc, rvfi['pc_rdata'],
                'PC discontinuity: pc_rdata does not match previous pc_wdata'))

        # -- Register read consistency --
        rs1_addr = rvfi.get('rs1_addr', 0)
        rs2_addr = rvfi.get('rs2_addr', 0)

        if rs1_addr != 0 and self.shadow_regs_valid[rs1_addr]:
            if rvfi['rs1_rdata'] != self.shadow_regs[rs1_addr]:
                violations.append(Violation(
                    'rs1_rdata', self.shadow_regs[rs1_addr],
                    rvfi['rs1_rdata'],
                    f'Register x{rs1_addr} read does not match shadow'))

        if rs2_addr != 0 and self.shadow_regs_valid[rs2_addr]:
            if rvfi['rs2_rdata'] != self.shadow_regs[rs2_addr]:
                violations.append(Violation(
                    'rs2_rdata', self.shadow_regs[rs2_addr],
                    rvfi['rs2_rdata'],
                    f'Register x{rs2_addr} read does not match shadow'))

        # -- Update shadow registers --
        rd_addr = rvfi.get('rd_addr', 0)
        rd_wdata = rvfi.get('rd_wdata', 0)

        if rd_addr != 0:
            self.shadow_regs[rd_addr] = rd_wdata
            self.shadow_regs_valid[rd_addr] = True

        # -- Update shadow PC --
        self.shadow_pc = rvfi['pc_wdata']
        self.shadow_pc_valid = not rvfi.get('trap', 0)

        return violations
