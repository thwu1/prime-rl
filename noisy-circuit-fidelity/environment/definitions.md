# Mathematical Definitions

This document defines all mathematical operations needed for the circuit simulation.
No prior knowledge of quantum physics is required — these are standard linear algebra operations.

## 1. State Space

The system has `n` qubits. Each qubit has a 2-dimensional state space with basis vectors
`|0> = [1, 0]^T` and `|1> = [0, 1]^T`.

The full system state space has dimension `2^n`. Basis states are labeled `|q_0 q_1 ... q_{n-1}>`,
where each `q_i` is 0 or 1. The basis state index is `q_0 * 2^{n-1} + q_1 * 2^{n-2} + ... + q_{n-1}`.

Example for 4 qubits: `|0000> = index 0`, `|0001> = index 1`, ..., `|1111> = index 15`.

## 2. Density Matrix

A quantum state is represented by a density matrix `rho`: a `2^n x 2^n` positive semidefinite
Hermitian matrix with `Tr(rho) = 1`.

A pure state `|psi>` has density matrix `rho = |psi><psi|` (outer product).

## 3. Gate Operations

A gate `U` transforms the density matrix as: `rho -> U rho U^dagger`.

### Pauli Matrices (2x2)

```
I = [[1, 0], [0, 1]]      (identity)
X = [[0, 1], [1, 0]]      (bit flip)
Y = [[0, -i], [i, 0]]     (bit-phase flip, where i = sqrt(-1))
Z = [[1, 0], [0, -1]]     (phase flip)
```

Note: Each Pauli matrix is Hermitian (`P = P^dagger`) and unitary (`P P^dagger = I`),
so `P^dagger = P` for all Pauli matrices.

### Hadamard Gate (2x2)

```
H = (1/sqrt(2)) * [[1, 1], [1, -1]]
```

To apply H to qubit `k` in an `n`-qubit system, construct the full operator as a tensor product:

```
H_k = I ⊗ I ⊗ ... ⊗ H ⊗ ... ⊗ I
```

where H appears at position `k` (0-indexed) and I (2x2 identity) appears at all other positions.

### CNOT Gate

CNOT(control=c, target=t) flips the target qubit if the control qubit is |1>:

```
|q_0 ... q_c ... q_t ... q_{n-1}> -> |q_0 ... q_c ... (q_c XOR q_t) ... q_{n-1}>
```

The `2^n x 2^n` matrix has entry `M[out_idx, in_idx] = 1` where `out_idx` and `in_idx` differ
only in the target bit position according to the XOR rule above.

## 4. Tensor Product (Kronecker Product)

For matrices A (size m1 x m2) and B (size n1 x n2), the tensor product `A ⊗ B` is the
`(m1*n1) x (m2*n2)` matrix:

```
A ⊗ B = [[A[0,0]*B, A[0,1]*B, ...],
          [A[1,0]*B, A[1,1]*B, ...],
          ...]
```

The tensor product of `n` single-qubit operators `O_0 ⊗ O_1 ⊗ ... ⊗ O_{n-1}` produces a
`2^n x 2^n` operator on the full system.

## 5. Two-Qubit Depolarizing Channel

After a noisy gate on qubits `(a, b)`, apply:

```
rho_out = (1 - p) * rho + (p/15) * sum_{k=1}^{15} P_k rho P_k^dagger
```

where `P_k` ranges over the **15 non-identity** elements of `{I, X, Y, Z}^{⊗2}`, each
embedded into the full `2^n x 2^n` space by tensoring with identity on all other qubits.

Concretely, the 15 non-identity two-qubit Paulis are:
`IX, IY, IZ, XI, XX, XY, XZ, YI, YX, YY, YZ, ZI, ZX, ZY, ZZ`

where the first letter acts on qubit `a` and the second on qubit `b`.

Each `P_k` in the full system is: `I ⊗ ... ⊗ sigma_a ⊗ ... ⊗ sigma_b ⊗ ... ⊗ I`
where `sigma_a` and `sigma_b` are the Pauli matrices for qubits `a` and `b` respectively.

Since all Pauli matrices are Hermitian, `P_k^dagger = P_k`.

## 6. Fidelity

The fidelity of a density matrix `rho` with a pure target state `|psi>` is:

```
F = <psi| rho |psi> = Tr(|psi><psi| * rho)
```

This is a scalar between 0 and 1, where 1 means perfect agreement.

## 7. Post-Selection

Given stabilizer operators `S1, S2, ...` with eigenvalue `+1`, the projector onto the
joint `+1` eigenspace is:

```
Pi = product_i (I + S_i) / 2
```

The post-selected (unnormalized) state is:

```
rho_PS = Pi * rho * Pi
```

The acceptance probability (probability of passing all stabilizer checks) is:

```
P_accept = Tr(rho_PS)
```

The normalized post-selected state is `rho_PS / P_accept`.

For the post-selected fidelity with target state `|psi>`:

```
F_PS = <psi| rho_PS |psi> / P_accept
```

If `|psi>` is in the `+1` eigenspace of all stabilizers (i.e., `Pi |psi> = |psi>`), this simplifies to:

```
F_PS = <psi| rho |psi> / P_accept = F_raw / P_accept
```
