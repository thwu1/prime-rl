/*
 * Quantum gate application kernel -- native C implementation.
 *
 * Compile: gcc -shared -fPIC -O2 -o libqsim.so kernel.c -lm
 *
 * Provides performance-critical gate application routines
 * loaded by the Python engine via ctypes.
 */
#include <complex.h>
#include <stdlib.h>

/*
 * Apply a 2x2 unitary gate to a single target qubit of an n-qubit state vector.
 *
 * Parameters:
 *   state    - complex double array of length 2^n_qubits
 *   gate     - 2x2 gate matrix in row-major order (4 complex doubles):
 *              gate[0]=U00, gate[1]=U01, gate[2]=U10, gate[3]=U11
 *   target   - index of target qubit (0-indexed, qubit 0 = LSB)
 *   n_qubits - total number of qubits
 *
 * Modifies state in-place. For each pair of basis states that differ only
 * in the target qubit bit, applies the 2x2 matrix to their amplitudes.
 */
void apply_single_qubit_gate(double complex *state, const double complex *gate,
                              int target, int n_qubits) {
    (void)state; (void)gate; (void)target; (void)n_qubits;
    /* TODO: implement using bit manipulation */
}

/*
 * Apply a 2x2 unitary gate controlled on a single control qubit.
 * The gate acts on the target qubit only when the control qubit is |1>.
 *
 * Parameters:
 *   state    - complex double array of length 2^n_qubits
 *   gate     - 2x2 gate matrix in row-major order (4 complex doubles)
 *   control  - index of control qubit (0-indexed)
 *   target   - index of target qubit (0-indexed)
 *   n_qubits - total number of qubits
 *
 * Modifies state in-place. Only processes basis-state pairs where the
 * control qubit bit is 1.
 */
void apply_controlled_single_qubit_gate(double complex *state, const double complex *gate,
                                         int control, int target, int n_qubits) {
    (void)state; (void)gate; (void)control; (void)target; (void)n_qubits;
    /* TODO: implement using bit manipulation */
}
