/* cpu6502.h — NMOS 6502 CPU emulator interface */
#ifndef CPU6502_H
#define CPU6502_H

#include <stdint.h>


typedef struct {
    uint8_t  A;        /* Accumulator */
    uint8_t  X;        /* X index register */
    uint8_t  Y;        /* Y index register */
    uint8_t  SP;       /* Stack pointer (offset within page $01) */
    uint16_t PC;       /* Program counter */
    uint8_t  P;        /* Processor status register */
    uint8_t  memory[65536]; /* Full 64 KB address space */
} cpu6502_t;

/* Status register flag bits */
#define FLAG_C  0x01  /* Carry */
#define FLAG_Z  0x02  /* Zero */
#define FLAG_I  0x04  /* Interrupt disable */
#define FLAG_D  0x08  /* Decimal mode */
#define FLAG_B  0x10  /* Break (only on stack) */
#define FLAG_U  0x20  /* Unused (always 1) */
#define FLAG_V  0x40  /* Overflow */
#define FLAG_N  0x80  /* Negative */

/*
 * Initialize CPU state. Sets SP=$FD, P=FLAG_U|FLAG_I, A=X=Y=0, PC=0.
 * Zeroes all memory.
 */
void cpu_init(cpu6502_t *cpu);

/*
 * Execute one instruction at the current PC.
 * Returns the number of clock cycles consumed (including any
 * page-boundary crossing penalties).
 */
int cpu_step(cpu6502_t *cpu);

/*
 * Trigger a maskable interrupt (IRQ).
 * Only fires if the I flag is clear.  Consumes 7 cycles.
 */
void cpu_irq(cpu6502_t *cpu);

/*
 * Trigger a non-maskable interrupt (NMI).
 * Always fires regardless of I flag.  Consumes 7 cycles.
 */
void cpu_nmi(cpu6502_t *cpu);

#endif /* CPU6502_H */
