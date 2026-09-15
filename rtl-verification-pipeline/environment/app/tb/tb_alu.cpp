#include "Valu.h"
#include "verilated.h"
#include <cstdio>

static int pass_count = 0;
static int fail_count = 0;

void check(Valu* dut, uint32_t a, uint32_t b, uint32_t op, uint32_t expected, const char* name) {
    dut->a = a;
    dut->b = b;
    dut->op = op;
    dut->eval();
    if (dut->result == expected) {
        pass_count++;
    } else {
        printf("FAIL: %s: a=0x%08x b=0x%08x op=%u expected=0x%08x got=0x%08x\n",
               name, a, b, op, expected, dut->result);
        fail_count++;
    }
}

int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);
    Valu* dut = new Valu;

    // ADD tests
    check(dut, 5, 3, 0, 8, "ADD basic");
    check(dut, 0, 0, 0, 0, "ADD zeros");
    check(dut, 0xFFFFFFFF, 1, 0, 0, "ADD overflow");

    // XOR tests
    check(dut, 0xFF00, 0x0FF0, 5, 0xF0F0, "XOR basic");

    // SRL tests
    check(dut, 0xFF000000, 4, 6, 0x0FF00000, "SRL basic");

    // SRA tests (positive value only - no sign extension exercised)
    check(dut, 0x7F000000, 4, 7, 0x07F00000, "SRA positive");

    // SLT tests (positive values only - signed/unsigned equivalent)
    check(dut, 3, 5, 3, 1, "SLT pos less");
    check(dut, 5, 3, 3, 0, "SLT pos greater");

    // SLTU tests (unequal values only - strict/non-strict equivalent)
    check(dut, 3, 5, 4, 1, "SLTU less");
    check(dut, 5, 3, 4, 0, "SLTU greater");

    // SLL tests (small shift only - 4-bit and 5-bit width equivalent)
    check(dut, 1, 4, 2, 16, "SLL by 4");

    // AND tests
    check(dut, 0xFF00, 0x0FF0, 9, 0x0F00, "AND basic");

    // OR tests (non-overlapping bits only - OR and XOR equivalent)
    check(dut, 0xFF00, 0x00FF, 8, 0xFFFF, "OR no overlap");

    printf("\n[RESULTS] %d pass, %d fail\n", pass_count, fail_count);

    delete dut;
    return (fail_count > 0) ? 1 : 0;
}
