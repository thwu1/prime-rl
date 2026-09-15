
#include "Vfir_top.h"
#include "verilated.h"
#include <cstdio>
#include <cstdint>

static void tick(Vfir_top* top) {
    top->clk = 0; top->eval();
    top->clk = 1; top->eval();
}

static void reset(Vfir_top* top) {
    top->rst_n    = 0;
    top->s_data   = 0;
    top->s_valid  = 0;
    top->cfg_wr   = 0;
    top->cfg_addr = 0;
    top->cfg_data = 0;
    top->cfg_done = 0;
    for (int i = 0; i < 10; i++) tick(top);
    top->rst_n = 1;
    tick(top);
}

static void load_coefficients(Vfir_top* top, const int16_t* coeffs, bool commit) {
    for (int i = 0; i < 8; i++) {
        top->cfg_wr   = 1;
        top->cfg_addr = i;
        top->cfg_data = coeffs[i];
        tick(top);
    }
    top->cfg_wr = 0;
    if (commit) {
        top->cfg_done = 1;
        tick(top);
        top->cfg_done = 0;
    }
    tick(top);
}

static void apply_impulse(Vfir_top* top, int16_t amplitude, FILE* f, int active_cycles) {
    for (int cyc = 0; cyc < active_cycles; cyc++) {
        top->s_data  = (cyc == 0) ? amplitude : 0;
        top->s_valid = 1;
        tick(top);
        if (top->m_valid) {
            fprintf(f, "%d\n", (int32_t)top->m_data);
        }
    }
    // Drain pipeline: a few cycles with s_valid=0
    top->s_valid = 0;
    top->s_data  = 0;
    for (int i = 0; i < 5; i++) {
        tick(top);
        if (top->m_valid) {
            fprintf(f, "%d\n", (int32_t)top->m_data);
        }
    }
}

int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);
    Vfir_top* top = new Vfir_top;
    FILE* f;

    // Coefficient set A: symmetric low-pass
    int16_t coeff_a[8] = {3, 11, 25, 32, 32, 25, 11, 3};
    // Coefficient set B: antisymmetric (tests signed arithmetic)
    int16_t coeff_b[8] = {-1, -4, -6, 0, 0, 6, 4, 1};

    // ================================================================
    // Test 1: Impulse response with coefficient set A
    // ================================================================
    reset(top);
    load_coefficients(top, coeff_a, true);
    f = fopen("/app/response_a.txt", "w");
    apply_impulse(top, 1000, f, 20);
    fclose(f);

    // ================================================================
    // Test 2: Impulse response with coefficient set B (signed)
    // ================================================================
    reset(top);
    load_coefficients(top, coeff_b, true);
    f = fopen("/app/response_b.txt", "w");
    apply_impulse(top, 500, f, 20);
    fclose(f);

    // ================================================================
    // Test 3: Atomic coefficient switching
    // Load A (committed), then load B (NOT committed).
    // Impulse should still produce A's response.
    // ================================================================
    reset(top);
    load_coefficients(top, coeff_a, true);   // A is active
    load_coefficients(top, coeff_b, false);  // B written but NOT committed
    f = fopen("/app/response_atomic.txt", "w");
    apply_impulse(top, 1000, f, 20);         // Must use A
    fclose(f);

    // ================================================================
    // Test 4: Commit the pending coefficients, verify switch
    // B was written in test 3 but not committed.
    // Assert cfg_done to commit B, reset delay line, verify B is active.
    // ================================================================
    top->cfg_done = 1;
    tick(top);
    top->cfg_done = 0;
    tick(top);
    // Reset delay line (coefficients survive reset)
    reset(top);
    f = fopen("/app/response_switch.txt", "w");
    apply_impulse(top, 500, f, 20);
    fclose(f);

    // ================================================================
    // Test 5: Output latency measurement
    // Single-cycle din_valid pulse, measure cycles to dout_valid.
    // ================================================================
    reset(top);
    load_coefficients(top, coeff_a, true);
    f = fopen("/app/latency.txt", "w");
    int latency = -1;
    for (int cyc = 0; cyc < 20; cyc++) {
        top->s_data  = (cyc == 0) ? 1000 : 0;
        top->s_valid = (cyc == 0) ? 1 : 0;
        tick(top);
        if (top->m_valid && latency < 0) {
            latency = cyc;
        }
    }
    fprintf(f, "%d\n", latency);
    fclose(f);

    top->final();
    delete top;
    return 0;
}
