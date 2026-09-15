/* cpu6502_solution.c — Complete NMOS 6502 CPU emulator */

#include <string.h>
#include "cpu6502.h"

/* ── helpers ─────────────────────────────────────────────────── */

static inline uint8_t  rd(cpu6502_t *c, uint16_t a)          { return c->memory[a]; }
static inline void     wr(cpu6502_t *c, uint16_t a, uint8_t v){ c->memory[a] = v; }
static inline uint16_t rd16(cpu6502_t *c, uint16_t a)        { return rd(c,a) | ((uint16_t)rd(c,a+1)<<8); }
static inline uint16_t rd16_bug(cpu6502_t *c, uint16_t a) {
    /* JMP indirect page-boundary bug: high byte wraps within page */
    uint16_t lo_addr = a;
    uint16_t hi_addr = (a & 0xFF00) | ((a + 1) & 0x00FF);
    return rd(c, lo_addr) | ((uint16_t)rd(c, hi_addr) << 8);
}

static inline void push8(cpu6502_t *c, uint8_t v)   { wr(c, 0x100 + c->SP, v); c->SP--; }
static inline uint8_t pull8(cpu6502_t *c)            { c->SP++; return rd(c, 0x100 + c->SP); }
static inline void push16(cpu6502_t *c, uint16_t v)  { push8(c, (v >> 8) & 0xFF); push8(c, v & 0xFF); }
static inline uint16_t pull16(cpu6502_t *c)          { uint16_t lo = pull8(c); return lo | ((uint16_t)pull8(c)<<8); }

static inline void set_flag(cpu6502_t *c, uint8_t f, int v) {
    if (v) c->P |= f; else c->P &= ~f;
}
static inline int get_flag(cpu6502_t *c, uint8_t f) { return (c->P & f) ? 1 : 0; }

static inline void update_nz(cpu6502_t *c, uint8_t v) {
    set_flag(c, FLAG_Z, v == 0);
    set_flag(c, FLAG_N, v & 0x80);
}

/* ── addressing mode resolution ──────────────────────────────── */

typedef enum {
    AM_IMP, AM_ACC, AM_IMM, AM_ZP, AM_ZPX, AM_ZPY,
    AM_ABS, AM_ABX, AM_ABY, AM_IND, AM_IZX, AM_IZY, AM_REL
} addrmode_t;

/* Returns effective address. Sets *page_cross if page boundary crossed (for ABX, ABY, IZY). */
static uint16_t resolve(cpu6502_t *c, addrmode_t mode, int *page_cross) {
    uint16_t addr = 0;
    *page_cross = 0;
    switch (mode) {
    case AM_IMM: addr = c->PC++; break;
    case AM_ZP:  addr = rd(c, c->PC++); break;
    case AM_ZPX: addr = (rd(c, c->PC++) + c->X) & 0xFF; break;
    case AM_ZPY: addr = (rd(c, c->PC++) + c->Y) & 0xFF; break;
    case AM_ABS: addr = rd16(c, c->PC); c->PC += 2; break;
    case AM_ABX: {
        uint16_t base = rd16(c, c->PC); c->PC += 2;
        addr = base + c->X;
        if ((base & 0xFF00) != (addr & 0xFF00)) *page_cross = 1;
        break;
    }
    case AM_ABY: {
        uint16_t base = rd16(c, c->PC); c->PC += 2;
        addr = base + c->Y;
        if ((base & 0xFF00) != (addr & 0xFF00)) *page_cross = 1;
        break;
    }
    case AM_IND: addr = rd16_bug(c, rd16(c, c->PC)); c->PC += 2; break;
    case AM_IZX: {
        uint8_t zp = (rd(c, c->PC++) + c->X) & 0xFF;
        addr = rd(c, zp) | ((uint16_t)rd(c, (zp+1)&0xFF) << 8);
        break;
    }
    case AM_IZY: {
        uint8_t zp = rd(c, c->PC++);
        uint16_t base = rd(c, zp) | ((uint16_t)rd(c, (zp+1)&0xFF) << 8);
        addr = base + c->Y;
        if ((base & 0xFF00) != (addr & 0xFF00)) *page_cross = 1;
        break;
    }
    case AM_REL: {
        int8_t off = (int8_t)rd(c, c->PC++);
        addr = c->PC + off;
        break;
    }
    default: break;
    }
    return addr;
}

/* ── ADC / SBC with BCD support ──────────────────────────────── */

static void do_adc(cpu6502_t *c, uint8_t val) {
    uint8_t a = c->A;
    int carry = get_flag(c, FLAG_C);

    if (get_flag(c, FLAG_D)) {
        /* NMOS 6502 decimal mode ADC */
        /* Binary result for N, V, Z flags */
        unsigned bin = a + val + carry;
        set_flag(c, FLAG_Z, (bin & 0xFF) == 0);
        /* V from binary */
        set_flag(c, FLAG_V, (~(a ^ val) & (a ^ bin)) & 0x80);

        /* Decimal low nibble */
        int lo = (a & 0x0F) + (val & 0x0F) + carry;
        int hi_carry = 0;
        if (lo > 9) { lo -= 10; hi_carry = 1; }
        /* Decimal high nibble */
        int hi = (a >> 4) + (val >> 4) + hi_carry;

        /* N flag from high nibble bit 3 after decimal adjust of low but before decimal adjust of high */
        /* NMOS: N is set from bit 7 of the result AFTER low nibble correction but BEFORE high nibble correction */
        unsigned partial = (hi << 4) | (lo & 0x0F);
        set_flag(c, FLAG_N, partial & 0x80);

        if (hi > 9) { hi -= 10; set_flag(c, FLAG_C, 1); }
        else { set_flag(c, FLAG_C, 0); }

        c->A = ((hi & 0x0F) << 4) | (lo & 0x0F);
    } else {
        /* Binary mode */
        unsigned sum = a + val + carry;
        c->A = sum & 0xFF;
        set_flag(c, FLAG_C, sum > 0xFF);
        set_flag(c, FLAG_V, (~(a ^ val) & (a ^ c->A)) & 0x80);
        update_nz(c, c->A);
    }
}

static void do_sbc(cpu6502_t *c, uint8_t val) {
    uint8_t a = c->A;
    int borrow = get_flag(c, FLAG_C) ? 0 : 1;

    if (get_flag(c, FLAG_D)) {
        /* NMOS 6502 decimal mode SBC */
        /* Binary result for N, V, Z (NMOS behavior) */
        unsigned bin = a - val - borrow;
        set_flag(c, FLAG_Z, (bin & 0xFF) == 0);
        set_flag(c, FLAG_N, bin & 0x80);
        set_flag(c, FLAG_V, ((a ^ val) & (a ^ bin)) & 0x80);

        /* Decimal subtraction */
        int lo = (a & 0x0F) - (val & 0x0F) - borrow;
        int hi_borrow = 0;
        if (lo < 0) { lo += 10; hi_borrow = 1; }
        int hi = (a >> 4) - (val >> 4) - hi_borrow;
        if (hi < 0) { hi += 10; set_flag(c, FLAG_C, 0); }
        else { set_flag(c, FLAG_C, 1); }

        c->A = ((hi & 0x0F) << 4) | (lo & 0x0F);
    } else {
        /* Binary mode */
        unsigned diff = a - val - borrow;
        c->A = diff & 0xFF;
        set_flag(c, FLAG_C, diff < 0x100);
        set_flag(c, FLAG_V, ((a ^ val) & (a ^ c->A)) & 0x80);
        update_nz(c, c->A);
    }
}

/* ── compare helper ──────────────────────────────────────────── */

static void do_cmp(cpu6502_t *c, uint8_t reg, uint8_t val) {
    unsigned diff = reg - val;
    set_flag(c, FLAG_C, reg >= val);
    update_nz(c, diff & 0xFF);
}

/* ── branch helper ───────────────────────────────────────────── */

static int do_branch(cpu6502_t *c, int cond) {
    int8_t off = (int8_t)rd(c, c->PC++);
    if (cond) {
        uint16_t new_pc = c->PC + off;
        int extra = ((c->PC & 0xFF00) != (new_pc & 0xFF00)) ? 2 : 1;
        c->PC = new_pc;
        return extra;
    }
    return 0;
}

/* ── main dispatch ───────────────────────────────────────────── */

void cpu_init(cpu6502_t *cpu) {
    memset(cpu, 0, sizeof(*cpu));
    cpu->SP = 0xFD;
    cpu->P  = FLAG_U | FLAG_I;
}

void cpu_irq(cpu6502_t *c) {
    if (get_flag(c, FLAG_I)) return;
    push16(c, c->PC);
    push8(c, (c->P & ~FLAG_B) | FLAG_U);
    set_flag(c, FLAG_I, 1);
    c->PC = rd16(c, 0xFFFE);
}

void cpu_nmi(cpu6502_t *c) {
    push16(c, c->PC);
    push8(c, (c->P & ~FLAG_B) | FLAG_U);
    set_flag(c, FLAG_I, 1);
    c->PC = rd16(c, 0xFFFA);
}

int cpu_step(cpu6502_t *c) {
    uint8_t op = rd(c, c->PC++);
    int page_cross = 0;
    uint16_t addr;
    uint8_t val, tmp;
    unsigned t;

    switch (op) {

    /* ── ADC ─────────────────────────────────────────────── */
    case 0x69: addr = resolve(c, AM_IMM, &page_cross); do_adc(c, rd(c,addr)); return 2;
    case 0x65: addr = resolve(c, AM_ZP,  &page_cross); do_adc(c, rd(c,addr)); return 3;
    case 0x75: addr = resolve(c, AM_ZPX, &page_cross); do_adc(c, rd(c,addr)); return 4;
    case 0x6D: addr = resolve(c, AM_ABS, &page_cross); do_adc(c, rd(c,addr)); return 4;
    case 0x7D: addr = resolve(c, AM_ABX, &page_cross); do_adc(c, rd(c,addr)); return 4+page_cross;
    case 0x79: addr = resolve(c, AM_ABY, &page_cross); do_adc(c, rd(c,addr)); return 4+page_cross;
    case 0x61: addr = resolve(c, AM_IZX, &page_cross); do_adc(c, rd(c,addr)); return 6;
    case 0x71: addr = resolve(c, AM_IZY, &page_cross); do_adc(c, rd(c,addr)); return 5+page_cross;

    /* ── SBC ─────────────────────────────────────────────── */
    case 0xE9: addr = resolve(c, AM_IMM, &page_cross); do_sbc(c, rd(c,addr)); return 2;
    case 0xE5: addr = resolve(c, AM_ZP,  &page_cross); do_sbc(c, rd(c,addr)); return 3;
    case 0xF5: addr = resolve(c, AM_ZPX, &page_cross); do_sbc(c, rd(c,addr)); return 4;
    case 0xED: addr = resolve(c, AM_ABS, &page_cross); do_sbc(c, rd(c,addr)); return 4;
    case 0xFD: addr = resolve(c, AM_ABX, &page_cross); do_sbc(c, rd(c,addr)); return 4+page_cross;
    case 0xF9: addr = resolve(c, AM_ABY, &page_cross); do_sbc(c, rd(c,addr)); return 4+page_cross;
    case 0xE1: addr = resolve(c, AM_IZX, &page_cross); do_sbc(c, rd(c,addr)); return 6;
    case 0xF1: addr = resolve(c, AM_IZY, &page_cross); do_sbc(c, rd(c,addr)); return 5+page_cross;

    /* ── AND ─────────────────────────────────────────────── */
    case 0x29: addr = resolve(c, AM_IMM, &page_cross); c->A &= rd(c,addr); update_nz(c,c->A); return 2;
    case 0x25: addr = resolve(c, AM_ZP,  &page_cross); c->A &= rd(c,addr); update_nz(c,c->A); return 3;
    case 0x35: addr = resolve(c, AM_ZPX, &page_cross); c->A &= rd(c,addr); update_nz(c,c->A); return 4;
    case 0x2D: addr = resolve(c, AM_ABS, &page_cross); c->A &= rd(c,addr); update_nz(c,c->A); return 4;
    case 0x3D: addr = resolve(c, AM_ABX, &page_cross); c->A &= rd(c,addr); update_nz(c,c->A); return 4+page_cross;
    case 0x39: addr = resolve(c, AM_ABY, &page_cross); c->A &= rd(c,addr); update_nz(c,c->A); return 4+page_cross;
    case 0x21: addr = resolve(c, AM_IZX, &page_cross); c->A &= rd(c,addr); update_nz(c,c->A); return 6;
    case 0x31: addr = resolve(c, AM_IZY, &page_cross); c->A &= rd(c,addr); update_nz(c,c->A); return 5+page_cross;

    /* ── ORA ─────────────────────────────────────────────── */
    case 0x09: addr = resolve(c, AM_IMM, &page_cross); c->A |= rd(c,addr); update_nz(c,c->A); return 2;
    case 0x05: addr = resolve(c, AM_ZP,  &page_cross); c->A |= rd(c,addr); update_nz(c,c->A); return 3;
    case 0x15: addr = resolve(c, AM_ZPX, &page_cross); c->A |= rd(c,addr); update_nz(c,c->A); return 4;
    case 0x0D: addr = resolve(c, AM_ABS, &page_cross); c->A |= rd(c,addr); update_nz(c,c->A); return 4;
    case 0x1D: addr = resolve(c, AM_ABX, &page_cross); c->A |= rd(c,addr); update_nz(c,c->A); return 4+page_cross;
    case 0x19: addr = resolve(c, AM_ABY, &page_cross); c->A |= rd(c,addr); update_nz(c,c->A); return 4+page_cross;
    case 0x01: addr = resolve(c, AM_IZX, &page_cross); c->A |= rd(c,addr); update_nz(c,c->A); return 6;
    case 0x11: addr = resolve(c, AM_IZY, &page_cross); c->A |= rd(c,addr); update_nz(c,c->A); return 5+page_cross;

    /* ── EOR ─────────────────────────────────────────────── */
    case 0x49: addr = resolve(c, AM_IMM, &page_cross); c->A ^= rd(c,addr); update_nz(c,c->A); return 2;
    case 0x45: addr = resolve(c, AM_ZP,  &page_cross); c->A ^= rd(c,addr); update_nz(c,c->A); return 3;
    case 0x55: addr = resolve(c, AM_ZPX, &page_cross); c->A ^= rd(c,addr); update_nz(c,c->A); return 4;
    case 0x4D: addr = resolve(c, AM_ABS, &page_cross); c->A ^= rd(c,addr); update_nz(c,c->A); return 4;
    case 0x5D: addr = resolve(c, AM_ABX, &page_cross); c->A ^= rd(c,addr); update_nz(c,c->A); return 4+page_cross;
    case 0x59: addr = resolve(c, AM_ABY, &page_cross); c->A ^= rd(c,addr); update_nz(c,c->A); return 4+page_cross;
    case 0x41: addr = resolve(c, AM_IZX, &page_cross); c->A ^= rd(c,addr); update_nz(c,c->A); return 6;
    case 0x51: addr = resolve(c, AM_IZY, &page_cross); c->A ^= rd(c,addr); update_nz(c,c->A); return 5+page_cross;

    /* ── ASL ─────────────────────────────────────────────── */
    case 0x0A: /* accumulator */
        set_flag(c, FLAG_C, c->A & 0x80);
        c->A <<= 1; update_nz(c, c->A); return 2;
    case 0x06: addr = resolve(c, AM_ZP,  &page_cross); val=rd(c,addr);
        set_flag(c,FLAG_C,val&0x80); val<<=1; wr(c,addr,val); update_nz(c,val); return 5;
    case 0x16: addr = resolve(c, AM_ZPX, &page_cross); val=rd(c,addr);
        set_flag(c,FLAG_C,val&0x80); val<<=1; wr(c,addr,val); update_nz(c,val); return 6;
    case 0x0E: addr = resolve(c, AM_ABS, &page_cross); val=rd(c,addr);
        set_flag(c,FLAG_C,val&0x80); val<<=1; wr(c,addr,val); update_nz(c,val); return 6;
    case 0x1E: addr = resolve(c, AM_ABX, &page_cross); val=rd(c,addr);
        set_flag(c,FLAG_C,val&0x80); val<<=1; wr(c,addr,val); update_nz(c,val); return 7;

    /* ── LSR ─────────────────────────────────────────────── */
    case 0x4A:
        set_flag(c, FLAG_C, c->A & 0x01);
        c->A >>= 1; update_nz(c, c->A); return 2;
    case 0x46: addr = resolve(c, AM_ZP,  &page_cross); val=rd(c,addr);
        set_flag(c,FLAG_C,val&1); val>>=1; wr(c,addr,val); update_nz(c,val); return 5;
    case 0x56: addr = resolve(c, AM_ZPX, &page_cross); val=rd(c,addr);
        set_flag(c,FLAG_C,val&1); val>>=1; wr(c,addr,val); update_nz(c,val); return 6;
    case 0x4E: addr = resolve(c, AM_ABS, &page_cross); val=rd(c,addr);
        set_flag(c,FLAG_C,val&1); val>>=1; wr(c,addr,val); update_nz(c,val); return 6;
    case 0x5E: addr = resolve(c, AM_ABX, &page_cross); val=rd(c,addr);
        set_flag(c,FLAG_C,val&1); val>>=1; wr(c,addr,val); update_nz(c,val); return 7;

    /* ── ROL ─────────────────────────────────────────────── */
    case 0x2A: {
        int old_c = get_flag(c, FLAG_C);
        set_flag(c, FLAG_C, c->A & 0x80);
        c->A = (c->A << 1) | old_c;
        update_nz(c, c->A); return 2;
    }
    case 0x26: addr = resolve(c, AM_ZP,  &page_cross); val=rd(c,addr); {
        int old_c = get_flag(c,FLAG_C); set_flag(c,FLAG_C,val&0x80);
        val=(val<<1)|old_c; wr(c,addr,val); update_nz(c,val); return 5; }
    case 0x36: addr = resolve(c, AM_ZPX, &page_cross); val=rd(c,addr); {
        int old_c = get_flag(c,FLAG_C); set_flag(c,FLAG_C,val&0x80);
        val=(val<<1)|old_c; wr(c,addr,val); update_nz(c,val); return 6; }
    case 0x2E: addr = resolve(c, AM_ABS, &page_cross); val=rd(c,addr); {
        int old_c = get_flag(c,FLAG_C); set_flag(c,FLAG_C,val&0x80);
        val=(val<<1)|old_c; wr(c,addr,val); update_nz(c,val); return 6; }
    case 0x3E: addr = resolve(c, AM_ABX, &page_cross); val=rd(c,addr); {
        int old_c = get_flag(c,FLAG_C); set_flag(c,FLAG_C,val&0x80);
        val=(val<<1)|old_c; wr(c,addr,val); update_nz(c,val); return 7; }

    /* ── ROR ─────────────────────────────────────────────── */
    case 0x6A: {
        int old_c = get_flag(c, FLAG_C);
        set_flag(c, FLAG_C, c->A & 0x01);
        c->A = (c->A >> 1) | (old_c << 7);
        update_nz(c, c->A); return 2;
    }
    case 0x66: addr = resolve(c, AM_ZP,  &page_cross); val=rd(c,addr); {
        int old_c = get_flag(c,FLAG_C); set_flag(c,FLAG_C,val&1);
        val=(val>>1)|(old_c<<7); wr(c,addr,val); update_nz(c,val); return 5; }
    case 0x76: addr = resolve(c, AM_ZPX, &page_cross); val=rd(c,addr); {
        int old_c = get_flag(c,FLAG_C); set_flag(c,FLAG_C,val&1);
        val=(val>>1)|(old_c<<7); wr(c,addr,val); update_nz(c,val); return 6; }
    case 0x6E: addr = resolve(c, AM_ABS, &page_cross); val=rd(c,addr); {
        int old_c = get_flag(c,FLAG_C); set_flag(c,FLAG_C,val&1);
        val=(val>>1)|(old_c<<7); wr(c,addr,val); update_nz(c,val); return 6; }
    case 0x7E: addr = resolve(c, AM_ABX, &page_cross); val=rd(c,addr); {
        int old_c = get_flag(c,FLAG_C); set_flag(c,FLAG_C,val&1);
        val=(val>>1)|(old_c<<7); wr(c,addr,val); update_nz(c,val); return 7; }

    /* ── INC ─────────────────────────────────────────────── */
    case 0xE6: addr = resolve(c, AM_ZP,  &page_cross); val=rd(c,addr)+1; wr(c,addr,val); update_nz(c,val); return 5;
    case 0xF6: addr = resolve(c, AM_ZPX, &page_cross); val=rd(c,addr)+1; wr(c,addr,val); update_nz(c,val); return 6;
    case 0xEE: addr = resolve(c, AM_ABS, &page_cross); val=rd(c,addr)+1; wr(c,addr,val); update_nz(c,val); return 6;
    case 0xFE: addr = resolve(c, AM_ABX, &page_cross); val=rd(c,addr)+1; wr(c,addr,val); update_nz(c,val); return 7;

    /* ── DEC ─────────────────────────────────────────────── */
    case 0xC6: addr = resolve(c, AM_ZP,  &page_cross); val=rd(c,addr)-1; wr(c,addr,val); update_nz(c,val); return 5;
    case 0xD6: addr = resolve(c, AM_ZPX, &page_cross); val=rd(c,addr)-1; wr(c,addr,val); update_nz(c,val); return 6;
    case 0xCE: addr = resolve(c, AM_ABS, &page_cross); val=rd(c,addr)-1; wr(c,addr,val); update_nz(c,val); return 6;
    case 0xDE: addr = resolve(c, AM_ABX, &page_cross); val=rd(c,addr)-1; wr(c,addr,val); update_nz(c,val); return 7;

    /* ── INX INY DEX DEY ─────────────────────────────────── */
    case 0xE8: c->X++; update_nz(c, c->X); return 2;
    case 0xC8: c->Y++; update_nz(c, c->Y); return 2;
    case 0xCA: c->X--; update_nz(c, c->X); return 2;
    case 0x88: c->Y--; update_nz(c, c->Y); return 2;

    /* ── CMP ─────────────────────────────────────────────── */
    case 0xC9: addr = resolve(c, AM_IMM, &page_cross); do_cmp(c,c->A,rd(c,addr)); return 2;
    case 0xC5: addr = resolve(c, AM_ZP,  &page_cross); do_cmp(c,c->A,rd(c,addr)); return 3;
    case 0xD5: addr = resolve(c, AM_ZPX, &page_cross); do_cmp(c,c->A,rd(c,addr)); return 4;
    case 0xCD: addr = resolve(c, AM_ABS, &page_cross); do_cmp(c,c->A,rd(c,addr)); return 4;
    case 0xDD: addr = resolve(c, AM_ABX, &page_cross); do_cmp(c,c->A,rd(c,addr)); return 4+page_cross;
    case 0xD9: addr = resolve(c, AM_ABY, &page_cross); do_cmp(c,c->A,rd(c,addr)); return 4+page_cross;
    case 0xC1: addr = resolve(c, AM_IZX, &page_cross); do_cmp(c,c->A,rd(c,addr)); return 6;
    case 0xD1: addr = resolve(c, AM_IZY, &page_cross); do_cmp(c,c->A,rd(c,addr)); return 5+page_cross;

    /* ── CPX ─────────────────────────────────────────────── */
    case 0xE0: addr = resolve(c, AM_IMM, &page_cross); do_cmp(c,c->X,rd(c,addr)); return 2;
    case 0xE4: addr = resolve(c, AM_ZP,  &page_cross); do_cmp(c,c->X,rd(c,addr)); return 3;
    case 0xEC: addr = resolve(c, AM_ABS, &page_cross); do_cmp(c,c->X,rd(c,addr)); return 4;

    /* ── CPY ─────────────────────────────────────────────── */
    case 0xC0: addr = resolve(c, AM_IMM, &page_cross); do_cmp(c,c->Y,rd(c,addr)); return 2;
    case 0xC4: addr = resolve(c, AM_ZP,  &page_cross); do_cmp(c,c->Y,rd(c,addr)); return 3;
    case 0xCC: addr = resolve(c, AM_ABS, &page_cross); do_cmp(c,c->Y,rd(c,addr)); return 4;

    /* ── LDA ─────────────────────────────────────────────── */
    case 0xA9: addr = resolve(c, AM_IMM, &page_cross); c->A=rd(c,addr); update_nz(c,c->A); return 2;
    case 0xA5: addr = resolve(c, AM_ZP,  &page_cross); c->A=rd(c,addr); update_nz(c,c->A); return 3;
    case 0xB5: addr = resolve(c, AM_ZPX, &page_cross); c->A=rd(c,addr); update_nz(c,c->A); return 4;
    case 0xAD: addr = resolve(c, AM_ABS, &page_cross); c->A=rd(c,addr); update_nz(c,c->A); return 4;
    case 0xBD: addr = resolve(c, AM_ABX, &page_cross); c->A=rd(c,addr); update_nz(c,c->A); return 4+page_cross;
    case 0xB9: addr = resolve(c, AM_ABY, &page_cross); c->A=rd(c,addr); update_nz(c,c->A); return 4+page_cross;
    case 0xA1: addr = resolve(c, AM_IZX, &page_cross); c->A=rd(c,addr); update_nz(c,c->A); return 6;
    case 0xB1: addr = resolve(c, AM_IZY, &page_cross); c->A=rd(c,addr); update_nz(c,c->A); return 5+page_cross;

    /* ── LDX ─────────────────────────────────────────────── */
    case 0xA2: addr = resolve(c, AM_IMM, &page_cross); c->X=rd(c,addr); update_nz(c,c->X); return 2;
    case 0xA6: addr = resolve(c, AM_ZP,  &page_cross); c->X=rd(c,addr); update_nz(c,c->X); return 3;
    case 0xB6: addr = resolve(c, AM_ZPY, &page_cross); c->X=rd(c,addr); update_nz(c,c->X); return 4;
    case 0xAE: addr = resolve(c, AM_ABS, &page_cross); c->X=rd(c,addr); update_nz(c,c->X); return 4;
    case 0xBE: addr = resolve(c, AM_ABY, &page_cross); c->X=rd(c,addr); update_nz(c,c->X); return 4+page_cross;

    /* ── LDY ─────────────────────────────────────────────── */
    case 0xA0: addr = resolve(c, AM_IMM, &page_cross); c->Y=rd(c,addr); update_nz(c,c->Y); return 2;
    case 0xA4: addr = resolve(c, AM_ZP,  &page_cross); c->Y=rd(c,addr); update_nz(c,c->Y); return 3;
    case 0xB4: addr = resolve(c, AM_ZPX, &page_cross); c->Y=rd(c,addr); update_nz(c,c->Y); return 4;
    case 0xAC: addr = resolve(c, AM_ABS, &page_cross); c->Y=rd(c,addr); update_nz(c,c->Y); return 4;
    case 0xBC: addr = resolve(c, AM_ABX, &page_cross); c->Y=rd(c,addr); update_nz(c,c->Y); return 4+page_cross;

    /* ── STA ─────────────────────────────────────────────── */
    case 0x85: addr = resolve(c, AM_ZP,  &page_cross); wr(c,addr,c->A); return 3;
    case 0x95: addr = resolve(c, AM_ZPX, &page_cross); wr(c,addr,c->A); return 4;
    case 0x8D: addr = resolve(c, AM_ABS, &page_cross); wr(c,addr,c->A); return 4;
    case 0x9D: addr = resolve(c, AM_ABX, &page_cross); wr(c,addr,c->A); return 5;
    case 0x99: addr = resolve(c, AM_ABY, &page_cross); wr(c,addr,c->A); return 5;
    case 0x81: addr = resolve(c, AM_IZX, &page_cross); wr(c,addr,c->A); return 6;
    case 0x91: addr = resolve(c, AM_IZY, &page_cross); wr(c,addr,c->A); return 6;

    /* ── STX ─────────────────────────────────────────────── */
    case 0x86: addr = resolve(c, AM_ZP,  &page_cross); wr(c,addr,c->X); return 3;
    case 0x96: addr = resolve(c, AM_ZPY, &page_cross); wr(c,addr,c->X); return 4;
    case 0x8E: addr = resolve(c, AM_ABS, &page_cross); wr(c,addr,c->X); return 4;

    /* ── STY ─────────────────────────────────────────────── */
    case 0x84: addr = resolve(c, AM_ZP,  &page_cross); wr(c,addr,c->Y); return 3;
    case 0x94: addr = resolve(c, AM_ZPX, &page_cross); wr(c,addr,c->Y); return 4;
    case 0x8C: addr = resolve(c, AM_ABS, &page_cross); wr(c,addr,c->Y); return 4;

    /* ── Transfer ────────────────────────────────────────── */
    case 0xAA: c->X = c->A; update_nz(c, c->X); return 2; /* TAX */
    case 0x8A: c->A = c->X; update_nz(c, c->A); return 2; /* TXA */
    case 0xA8: c->Y = c->A; update_nz(c, c->Y); return 2; /* TAY */
    case 0x98: c->A = c->Y; update_nz(c, c->A); return 2; /* TYA */
    case 0xBA: c->X = c->SP; update_nz(c, c->X); return 2; /* TSX */
    case 0x9A: c->SP = c->X; return 2; /* TXS — no flags affected */

    /* ── Stack ───────────────────────────────────────────── */
    case 0x48: push8(c, c->A); return 3;  /* PHA */
    case 0x08: push8(c, c->P | FLAG_B | FLAG_U); return 3; /* PHP */
    case 0x68: c->A = pull8(c); update_nz(c, c->A); return 4; /* PLA */
    case 0x28: c->P = (pull8(c) & ~FLAG_B) | FLAG_U; return 4; /* PLP */

    /* ── BIT ─────────────────────────────────────────────── */
    case 0x24: addr = resolve(c, AM_ZP,  &page_cross); val=rd(c,addr);
        set_flag(c, FLAG_Z, (c->A & val) == 0);
        set_flag(c, FLAG_N, val & 0x80);
        set_flag(c, FLAG_V, val & 0x40);
        return 3;
    case 0x2C: addr = resolve(c, AM_ABS, &page_cross); val=rd(c,addr);
        set_flag(c, FLAG_Z, (c->A & val) == 0);
        set_flag(c, FLAG_N, val & 0x80);
        set_flag(c, FLAG_V, val & 0x40);
        return 4;

    /* ── Branches ────────────────────────────────────────── */
    case 0x10: return 2 + do_branch(c, !get_flag(c, FLAG_N)); /* BPL */
    case 0x30: return 2 + do_branch(c,  get_flag(c, FLAG_N)); /* BMI */
    case 0x50: return 2 + do_branch(c, !get_flag(c, FLAG_V)); /* BVC */
    case 0x70: return 2 + do_branch(c,  get_flag(c, FLAG_V)); /* BVS */
    case 0x90: return 2 + do_branch(c, !get_flag(c, FLAG_C)); /* BCC */
    case 0xB0: return 2 + do_branch(c,  get_flag(c, FLAG_C)); /* BCS */
    case 0xD0: return 2 + do_branch(c, !get_flag(c, FLAG_Z)); /* BNE */
    case 0xF0: return 2 + do_branch(c,  get_flag(c, FLAG_Z)); /* BEQ */

    /* ── JMP ─────────────────────────────────────────────── */
    case 0x4C: c->PC = rd16(c, c->PC); return 3; /* JMP abs */
    case 0x6C: { /* JMP indirect — with page-boundary bug */
        uint16_t ptr = rd16(c, c->PC);
        c->PC = rd16_bug(c, ptr);
        return 5;
    }

    /* ── JSR / RTS / RTI ─────────────────────────────────── */
    case 0x20: /* JSR */
        addr = rd16(c, c->PC); c->PC += 2;
        push16(c, c->PC - 1);
        c->PC = addr;
        return 6;
    case 0x60: /* RTS */
        c->PC = pull16(c) + 1;
        return 6;
    case 0x40: /* RTI */
        c->P = (pull8(c) & ~FLAG_B) | FLAG_U;
        c->PC = pull16(c);
        return 6;

    /* ── BRK ─────────────────────────────────────────────── */
    case 0x00: /* BRK */
        c->PC++; /* BRK skips next byte */
        push16(c, c->PC);
        push8(c, c->P | FLAG_B | FLAG_U);
        set_flag(c, FLAG_I, 1);
        c->PC = rd16(c, 0xFFFE);
        return 7;

    /* ── Flag instructions ───────────────────────────────── */
    case 0x18: set_flag(c, FLAG_C, 0); return 2; /* CLC */
    case 0x38: set_flag(c, FLAG_C, 1); return 2; /* SEC */
    case 0x58: set_flag(c, FLAG_I, 0); return 2; /* CLI */
    case 0x78: set_flag(c, FLAG_I, 1); return 2; /* SEI */
    case 0xB8: set_flag(c, FLAG_V, 0); return 2; /* CLV */
    case 0xD8: set_flag(c, FLAG_D, 0); return 2; /* CLD */
    case 0xF8: set_flag(c, FLAG_D, 1); return 2; /* SED */

    /* ── NOP ─────────────────────────────────────────────── */
    case 0xEA: return 2;

    /* ── Illegal / unimplemented ─────────────────────────── */
    default:
        /* Treat as NOP for safety */
        return 2;
    }
}
