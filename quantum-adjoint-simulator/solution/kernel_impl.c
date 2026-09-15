/*
 * Quantum gate application kernel -- native C implementation.
 *
 */
#include <complex.h>
#include <stdlib.h>

void apply_single_qubit_gate(double complex *state, const double complex *gate,
                              int target, int n_qubits) {
    long dim = 1L << n_qubits;
    long mask = 1L << target;

    for (long i = 0; i < dim; i++) {
        if (i & mask) continue;
        long j = i | mask;

        double complex a = state[i];
        double complex b = state[j];

        state[i] = gate[0] * a + gate[1] * b;
        state[j] = gate[2] * a + gate[3] * b;
    }
}

void apply_controlled_single_qubit_gate(double complex *state, const double complex *gate,
                                         int control, int target, int n_qubits) {
    long dim = 1L << n_qubits;
    long ctrl_mask = 1L << control;
    long tgt_mask = 1L << target;

    for (long i = 0; i < dim; i++) {
        /* Skip if control bit is 0 or target bit is already 1 */
        if (!(i & ctrl_mask)) continue;
        if (i & tgt_mask) continue;

        long j = i | tgt_mask;

        double complex a = state[i];
        double complex b = state[j];

        state[i] = gate[0] * a + gate[1] * b;
        state[j] = gate[2] * a + gate[3] * b;
    }
}
