/* cpu6502.c — NMOS 6502 CPU emulator implementation */

/*
 * TODO: Implement the full NMOS 6502 instruction set.
 *
 * Requirements:
 *   - All 151 legal opcodes across 13 addressing modes
 *   - Correct flag behavior for all instructions
 *   - BCD (decimal) mode for ADC and SBC with NMOS flag behavior
 *   - JMP ($xxFF) page-boundary bug
 *   - Accurate cycle counts including page-crossing penalties
 *   - BRK pushes PC+2, sets B flag in pushed status
 *   - IRQ and NMI support
 */

#include <string.h>
#include "cpu6502.h"

void cpu_init(cpu6502_t *cpu) {
    memset(cpu, 0, sizeof(*cpu));
    cpu->SP = 0xFD;
    cpu->P  = FLAG_U | FLAG_I;
}

int cpu_step(cpu6502_t *cpu) {
    (void)cpu;
    /* Implement your opcode fetch-decode-execute loop here. */
    /* Return the number of cycles consumed. */
    return 0;
}

void cpu_irq(cpu6502_t *cpu) {
    (void)cpu;
    /* Implement IRQ: if I flag clear, push PC and P, set I, jump to vector at $FFFE */
}

void cpu_nmi(cpu6502_t *cpu) {
    (void)cpu;
    /* Implement NMI: push PC and P, set I, jump to vector at $FFFA */
}
