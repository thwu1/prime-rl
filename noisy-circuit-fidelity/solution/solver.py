#!/usr/bin/env python3

"""
Symbolic density matrix simulation for the [[4,2,2]] error-detecting code
noisy state preparation circuit.

Circuit: H_0, CNOT(0,1)+noise, CNOT(1,2)+noise, CNOT(2,3)+noise
Target logical state: |00>_L in the [[4,2,2]] code
Stabilizers: XXXX, ZZZZ
Logical operators: X_A=XIXI, X_B=XXII, Z_A=ZZII, Z_B=ZIZI
Post-selection: project onto codespace (joint +1 eigenspace of stabilizers)
"""

import json
from sympy import (
    symbols, Matrix, sqrt, eye, zeros, expand, cancel, fraction,
    Rational, Poly, I as imag_i
)

p = symbols('p')

# ─── Pauli matrices ───
I2 = Matrix([[1, 0], [0, 1]])
X = Matrix([[0, 1], [1, 0]])
Y = Matrix([[0, -imag_i], [imag_i, 0]])
Z = Matrix([[1, 0], [0, -1]])
paulis_1q = [I2, X, Y, Z]

N_QUBITS = 4
DIM = 2 ** N_QUBITS  # 16


def kronecker_product(A, B):
    """Kronecker (tensor) product of two SymPy matrices."""
    ra, ca = A.shape
    rb, cb = B.shape
    result = zeros(ra * rb, ca * cb)
    for i in range(ra):
        for j in range(ca):
            if A[i, j] == 0:
                continue
            for k in range(rb):
                for l in range(cb):
                    if B[k, l] == 0:
                        continue
                    result[i * rb + k, j * cb + l] = A[i, j] * B[k, l]
    return result


def tensor(*matrices):
    """Tensor product of multiple matrices."""
    result = matrices[0]
    for m in matrices[1:]:
        result = kronecker_product(result, m)
    return result


# ─── Build gate matrices ───
H_mat = Matrix([[1, 1], [1, -1]]) / sqrt(2)
H_gate = tensor(H_mat, I2, I2, I2)


def build_cnot(ctrl, tgt, n=N_QUBITS):
    """Build CNOT gate matrix for n-qubit system."""
    dim = 2 ** n
    mat = zeros(dim, dim)
    for state in range(dim):
        bits = [(state >> (n - 1 - q)) & 1 for q in range(n)]
        out_bits = list(bits)
        out_bits[tgt] = bits[ctrl] ^ bits[tgt]
        out_idx = sum(b << (n - 1 - q) for q, b in enumerate(out_bits))
        mat[out_idx, state] = 1
    return mat


CNOT01 = build_cnot(0, 1)
CNOT12 = build_cnot(1, 2)
CNOT23 = build_cnot(2, 3)


# ─── Build noise operators ───
def build_noise_ops(qa, qb):
    """Build the 15 non-identity 2-qubit Pauli operators on qubits (qa, qb)."""
    ops = []
    for i, p1 in enumerate(paulis_1q):
        for j, p2 in enumerate(paulis_1q):
            if i == 0 and j == 0:
                continue  # Skip II
            parts = [I2] * N_QUBITS
            parts[qa] = p1
            parts[qb] = p2
            ops.append(tensor(*parts))
    return ops


noise_ops_01 = build_noise_ops(0, 1)
noise_ops_12 = build_noise_ops(1, 2)
noise_ops_23 = build_noise_ops(2, 3)


def apply_depolarizing(rho, noise_ops, p_sym):
    """Apply 2-qubit depolarizing channel."""
    result = (1 - p_sym) * rho
    for P in noise_ops:
        result = result + Rational(1, 15) * p_sym * P * rho * P  # P^dag = P for Paulis
    return result


def apply_gate(rho, U):
    """Apply unitary gate: rho -> U rho U^dag."""
    return U * rho * U.H


# ─── Initial state |0000><0000| ───
psi0 = zeros(DIM, 1)
psi0[0] = 1
rho = psi0 * psi0.T

# ─── Apply encoding circuit with noise ───
rho = apply_gate(rho, H_gate)
rho = apply_gate(rho, CNOT01)
rho = apply_depolarizing(rho, noise_ops_01, p)
rho = apply_gate(rho, CNOT12)
rho = apply_depolarizing(rho, noise_ops_12, p)
rho = apply_gate(rho, CNOT23)
rho = apply_depolarizing(rho, noise_ops_23, p)

# ─── [[4,2,2]] codespace projector ───
# Stabilizer generators: XXXX and ZZZZ
# Codespace = joint +1 eigenspace
# Projector: Pi = (I + XXXX)(I + ZZZZ) / 4
XXXX_op = tensor(X, X, X, X)
ZZZZ_op = tensor(Z, Z, Z, Z)
I_full = eye(DIM)
Pi_code = (I_full + XXXX_op) * (I_full + ZZZZ_op) / 4

# ─── Post-selected state (unnormalized) ───
rho_ps = Pi_code * rho * Pi_code
P_cs = expand(rho_ps.trace())

# ─── Logical basis states ───
# The codespace encodes 2 logical qubits. The logical basis states are determined
# by the stabilizer generators and logical Z operators:
#   |ab>_L lives in the +1 eigenspace of XXXX, ZZZZ, and has
#   Z_A eigenvalue (-1)^a, Z_B eigenvalue (-1)^b
#
# Explicitly:
#   |00>_L = (|0000> + |1111>)/sqrt(2)
#   |01>_L = (|0011> + |1100>)/sqrt(2)
#   |10>_L = (|0101> + |1010>)/sqrt(2)
#   |11>_L = (|0110> + |1001>)/sqrt(2)

logical_states_bits = {
    '00': [(0, 0, 0, 0), (1, 1, 1, 1)],
    '01': [(0, 0, 1, 1), (1, 1, 0, 0)],
    '10': [(0, 1, 0, 1), (1, 0, 1, 0)],
    '11': [(0, 1, 1, 0), (1, 0, 0, 1)],
}


def make_logical_state(label):
    psi = zeros(DIM, 1)
    for bits in logical_states_bits[label]:
        idx = bits[0] * 8 + bits[1] * 4 + bits[2] * 2 + bits[3]
        psi[idx] = Rational(1, 1) / sqrt(2)
    return psi


# ─── Compute projected populations ───
populations = {}
for label in ['00', '01', '10', '11']:
    psi_L = make_logical_state(label)
    pop = expand((psi_L.T * rho_ps * psi_L)[0, 0])
    populations[label] = pop

# ─── Extract polynomial coefficients ───
def poly_coeffs(expr, var):
    """Extract polynomial coefficients from constant term to highest power."""
    poly = Poly(expr, var)
    deg = poly.degree()
    coeffs = []
    for i in range(deg + 1):
        coeffs.append(poly.nth(i))
    return coeffs


pcs_coeffs = poly_coeffs(P_cs, p)
q00_coeffs = poly_coeffs(populations['00'], p)
q01_coeffs = poly_coeffs(populations['01'], p)
q10_coeffs = poly_coeffs(populations['10'], p)
q11_coeffs = poly_coeffs(populations['11'], p)

# ─── Compute infidelity leading order ───
# 1 - F_L(p) = 1 - q_00/P_cs = (P_cs - q_00)/P_cs
diff_poly = expand(P_cs - populations['00'])
diff_coeffs = poly_coeffs(diff_poly, p)

# Find the leading non-zero power
leading_power = None
leading_coeff_num = None
for k, c in enumerate(diff_coeffs):
    if c != 0:
        leading_power = k
        leading_coeff_num = c
        break

# The leading coefficient of the infidelity is diff_coeff[k] / P_cs(0)
pcs_at_0 = pcs_coeffs[0]  # = 1
leading_coeff = Rational(leading_coeff_num) / Rational(pcs_at_0)

# ─── Write result ───
result = {
    "codespace_probability_coefficients": [str(c) for c in pcs_coeffs],
    "population_00_coefficients": [str(c) for c in q00_coeffs],
    "population_01_coefficients": [str(c) for c in q01_coeffs],
    "population_10_coefficients": [str(c) for c in q10_coeffs],
    "population_11_coefficients": [str(c) for c in q11_coeffs],
    "infidelity_leading_power": int(leading_power),
    "infidelity_leading_coefficient": str(leading_coeff),
}

with open("/app/result.json", "w") as f:
    json.dump(result, f, indent=2)

print("Results written to /app/result.json")
print(json.dumps(result, indent=2))
