"""Quantum circuit optimizer implementation.

Reduces gate count while preserving the circuit's unitary matrix
up to global phase. Implements four optimization phases run iteratively:
1. Adjacent inverse pair cancellation
2. Commutation-aware non-adjacent cancellation
3. Same-type rotation gate merging (angle addition)
4. General single-qubit gate merging (matrix multiplication + diagonal detection)

"""

import numpy as np
import sys
sys.path.insert(0, '/app')
from circuit import Circuit, Operation
from gates import is_single_qubit


class CircuitOptimizer:
    """Multi-pass quantum circuit optimizer."""

    # Gates that are their own inverse (G·G = I)
    SELF_INVERSE = frozenset({'H', 'X', 'Y', 'Z', 'CNOT', 'CZ', 'SWAP'})

    # Named inverse pairs
    INVERSE_PAIRS = frozenset({('S', 'Sdg'), ('Sdg', 'S'), ('T', 'Tdg'), ('Tdg', 'T')})

    # Diagonal single-qubit gates (commute with each other on same qubit,
    # commute with CNOT on control, commute with CZ on either qubit)
    DIAGONAL = frozenset({'Z', 'S', 'Sdg', 'T', 'Tdg', 'Rz', 'I'})

    def optimize(self, circuit: Circuit) -> Circuit:
        """Return an optimized circuit with same unitary and fewer gates."""
        ops = [Operation(o.name, list(o.params), list(o.qubits))
               for o in circuit.operations]

        changed = True
        while changed:
            changed = False
            for phase_fn in [self._cancel_adjacent,
                             self._commute_cancel,
                             self._merge_rotations,
                             self._merge_single_qubit]:
                new_ops = phase_fn(ops)
                if len(new_ops) < len(ops):
                    ops = new_ops
                    changed = True
                    break  # Restart from first phase

        result = Circuit(circuit.num_qubits)
        for o in ops:
            result.add(o.name, o.params, o.qubits)
        return result

    # ------------------------------------------------------------------
    # Inverse detection
    # ------------------------------------------------------------------

    def _are_inverses(self, a: Operation, b: Operation) -> bool:
        """Check if two operations are inverses of each other."""
        if a.qubits != b.qubits:
            return False
        # Self-inverse gates
        if a.name == b.name and a.name in self.SELF_INVERSE:
            return True
        # Known inverse pairs
        if (a.name, b.name) in self.INVERSE_PAIRS:
            return True
        # Rotation gates with opposite angles
        if (a.name == b.name and a.name in ('Rx', 'Ry', 'Rz')
                and len(a.params) == 1 and len(b.params) == 1):
            if abs(a.params[0] + b.params[0]) < 1e-10:
                return True
        return False

    # ------------------------------------------------------------------
    # Commutation rules
    # ------------------------------------------------------------------

    def _commute(self, a: Operation, b: Operation) -> bool:
        """Check if two operations commute.

        Implements the standard quantum gate commutation rules:
        - Disjoint qubits always commute
        - Diagonal gates commute with each other on the same qubit
        - Diagonal gates commute with CNOT on the control qubit
        - X commutes with CNOT on the target qubit
        - Diagonal gates commute with CZ on either qubit
        """
        qa, qb = set(a.qubits), set(b.qubits)

        # Disjoint qubits always commute
        if not qa & qb:
            return True

        # Both single-qubit on the same qubit
        if (is_single_qubit(a.name) and is_single_qubit(b.name)
                and a.qubits == b.qubits):
            # Diagonal gates commute with each other
            return a.name in self.DIAGONAL and b.name in self.DIAGONAL

        # CNOT with single-qubit gate
        for cnot_op, sq_op in [(a, b), (b, a)]:
            if cnot_op.name == 'CNOT' and is_single_qubit(sq_op.name):
                ctrl, tgt = cnot_op.qubits
                q = sq_op.qubits[0]
                if q == ctrl and sq_op.name in self.DIAGONAL:
                    return True
                if q == tgt and sq_op.name in ('X', 'I'):
                    return True
                return False

        # CZ with single-qubit gate
        for cz_op, sq_op in [(a, b), (b, a)]:
            if cz_op.name == 'CZ' and is_single_qubit(sq_op.name):
                if sq_op.qubits[0] in cz_op.qubits and sq_op.name in self.DIAGONAL:
                    return True
                return False

        # Same gate on same qubits commutes with itself
        if a.name == b.name and a.qubits == b.qubits:
            return True

        return False

    # ------------------------------------------------------------------
    # Phase 1: Adjacent inverse cancellation
    # ------------------------------------------------------------------

    def _cancel_adjacent(self, ops):
        """Cancel adjacent inverse gate pairs."""
        result = list(ops)
        i = 0
        while i < len(result) - 1:
            if self._are_inverses(result[i], result[i + 1]):
                result.pop(i + 1)
                result.pop(i)
                if i > 0:
                    i -= 1
            else:
                i += 1
        return result

    # ------------------------------------------------------------------
    # Phase 2: Commutation-aware non-adjacent cancellation
    # ------------------------------------------------------------------

    def _commute_cancel(self, ops):
        """Find inverse pairs separated by commuting gates, and cancel them.

        For each gate i, scans forward through gates that commute with it,
        looking for an inverse partner. If found, removes both.
        Only removes one pair per call to allow the outer loop to restart.
        """
        result = list(ops)
        for i in range(len(result)):
            for j in range(i + 1, len(result)):
                if self._are_inverses(result[i], result[j]):
                    # Check if result[i] commutes with all intermediate gates
                    can_commute = all(
                        self._commute(result[i], result[k])
                        for k in range(i + 1, j)
                    )
                    if can_commute:
                        return result[:i] + result[i + 1:j] + result[j + 1:]
                # Stop scanning if we hit a non-commuting gate
                if not self._commute(result[i], result[j]):
                    break
        return result

    # ------------------------------------------------------------------
    # Phase 3: Same-type rotation merging
    # ------------------------------------------------------------------

    def _merge_rotations(self, ops):
        """Merge adjacent same-type rotation gates by adding angles."""
        result = list(ops)
        i = 0
        while i < len(result) - 1:
            a, b = result[i], result[i + 1]
            if (a.name == b.name and a.name in ('Rx', 'Ry', 'Rz')
                    and a.qubits == b.qubits):
                new_angle = a.params[0] + b.params[0]
                # Normalize angle to [-pi, pi]
                new_angle = (new_angle + np.pi) % (2 * np.pi) - np.pi
                if abs(new_angle) < 1e-10:
                    # Angle sums to zero -> identity
                    result.pop(i + 1)
                    result.pop(i)
                    if i > 0:
                        i -= 1
                else:
                    result[i:i + 2] = [
                        Operation(a.name, [new_angle], list(a.qubits))
                    ]
                continue
            i += 1
        return result

    # ------------------------------------------------------------------
    # Phase 4: General single-qubit gate merging
    # ------------------------------------------------------------------

    @staticmethod
    def _is_identity(mat, tol=1e-10):
        """Check if a 2x2 matrix is identity up to global phase."""
        phase = mat[0, 0]
        if abs(abs(phase) - 1) > tol:
            return False
        return np.allclose(mat, phase * np.eye(mat.shape[0]), atol=tol)

    @staticmethod
    def _is_diagonal(mat, tol=1e-10):
        """Check if a 2x2 matrix is diagonal."""
        return abs(mat[0, 1]) < tol and abs(mat[1, 0]) < tol

    def _merge_single_qubit(self, ops):
        """Merge adjacent single-qubit gates on the same qubit via matrix mult.

        If the merged matrix is identity (up to global phase), both gates
        are removed. If the merged matrix is diagonal, it is converted to
        a single Rz gate. Otherwise the gates are left as-is.
        """
        result = list(ops)
        i = 0
        while i < len(result) - 1:
            a, b = result[i], result[i + 1]
            if (is_single_qubit(a.name) and is_single_qubit(b.name)
                    and a.qubits == b.qubits):
                # Merged unitary: b applied after a
                merged = b.matrix() @ a.matrix()

                if self._is_identity(merged):
                    result.pop(i + 1)
                    result.pop(i)
                    if i > 0:
                        i -= 1
                    continue

                if self._is_diagonal(merged):
                    theta = np.angle(merged[1, 1]) - np.angle(merged[0, 0])
                    # Normalize to [-pi, pi]
                    theta = (theta + np.pi) % (2 * np.pi) - np.pi
                    if abs(theta) < 1e-10:
                        # Effectively identity
                        result.pop(i + 1)
                        result.pop(i)
                        if i > 0:
                            i -= 1
                        continue
                    result[i:i + 2] = [
                        Operation('Rz', [theta], list(a.qubits))
                    ]
                    continue
            i += 1
        return result
