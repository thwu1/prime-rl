The [[4,2,2]] quantum error-detecting code encodes 2 logical qubits into 4 physical qubits. The code specification (stabilizer generators, logical operators, encoding circuit, noise model) is defined in `/app/code_spec.json`.

An encoding circuit prepares the logical state `|00⟩_L` from `|0000⟩` using one Hadamard gate and three CNOT gates. Each CNOT gate is followed by a two-qubit depolarizing noise channel with error parameter `p`. Post-selection projects the noisy output onto the code's stabilizer-defined codespace.

Compute the following as exact symbolic functions of `p` with rational coefficients (not floating-point approximations):

1. **Codespace acceptance probability** `P_cs(p) = Tr(Π ρ(p) Π)` — a polynomial in `p`.

2. **Projected logical populations** `q_{ij}(p) = ⟨ij_L| Π ρ(p) Π |ij_L⟩` for each logical basis state `{|00⟩_L, |01⟩_L, |10⟩_L, |11⟩_L}` — each a polynomial in `p`. Note that `P_cs = q_{00} + q_{01} + q_{10} + q_{11}`.

3. **Infidelity leading order**: Express the post-selected logical infidelity `1 - F_L(p)` where `F_L(p) = q_{00}(p)/P_cs(p)` in the form `a·p^k + O(p^{k+1})` for small `p`. Report `k` (integer) and `a` (exact rational).

The logical basis states must be derived from the code's stabilizer and logical operator structure. The output format is specified in `/app/output_format.json`. Write results to `/app/result.json`.