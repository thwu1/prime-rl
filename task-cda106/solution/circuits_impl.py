"""
Distillation circuit solutions for each scenario.
"""

from engine import Circuit


def get_circuit(scenario_id):
    builders = {"S1": _s1, "S2": _s2, "S3": _s3, "S4": _s4}
    if scenario_id not in builders:
        raise ValueError(f"Unknown scenario: {scenario_id}")
    return builders[scenario_id]()


def _s1():
    """S1: Bit-flip noise, N=2 — bilateral CNOT parity check."""
    # Pairs: (q0,q3)=ancilla, (q1,q2)=output
    c = Circuit(4, 3)
    c.flag_bit = 2
    c.add_gate("cx", [1, 0])      # Alice: output ctrl -> ancilla tgt
    c.add_gate("cx", [2, 3])      # Bob:   output ctrl -> ancilla tgt
    c.add_measure(0, 0)           # measure Alice ancilla
    c.add_measure(3, 1)           # measure Bob ancilla
    c.add_store_xor(2, 0, 1)     # flag = syndrome XOR (keep if 0)
    return c


def _s2():
    """S2: Phase-flip noise, N=2 — H-rotated bilateral CNOT."""
    c = Circuit(4, 3)
    c.flag_bit = 2
    # Hadamard converts phase-flip to bit-flip
    for q in range(4):
        c.add_gate("h", [q])
    c.add_gate("cx", [1, 0])
    c.add_gate("cx", [2, 3])
    c.add_measure(0, 0)
    c.add_measure(3, 1)
    # Restore output pair basis
    c.add_gate("h", [1])
    c.add_gate("h", [2])
    c.add_store_xor(2, 0, 1)
    return c


def _s3():
    """S3: Bit-flip noise, N=3 — two sacrificial pairs for stronger purification.
    Pairs: (q0,q5)=sac0, (q1,q4)=sac1, (q2,q3)=output
    """
    c = Circuit(6, 7)
    c.flag_bit = 6
    # Parity check: output vs sac0
    c.add_gate("cx", [2, 0])      # Alice
    c.add_gate("cx", [3, 5])      # Bob
    # Parity check: output vs sac1
    c.add_gate("cx", [2, 1])      # Alice
    c.add_gate("cx", [3, 4])      # Bob
    # Measure all sacrificial qubits
    c.add_measure(0, 0)
    c.add_measure(1, 1)
    c.add_measure(5, 2)
    c.add_measure(4, 3)
    # Syndromes and flag
    c.add_store_xor(4, 0, 2)     # syndrome0 = Alice_sac0 XOR Bob_sac0
    c.add_store_xor(5, 1, 3)     # syndrome1 = Alice_sac1 XOR Bob_sac1
    c.add_store_or(6, 4, 5)      # flag = syn0 OR syn1 (keep if 0)
    return c


def _s4():
    """S4: Mixed Bell-diagonal noise, N=3 — phase check + bit check.
    Pairs: (q0,q5)=phase_sac, (q1,q4)=bit_sac, (q2,q3)=output
    Phase check purifies Z errors, bit check purifies X errors.
    """
    c = Circuit(6, 7)
    c.flag_bit = 6

    # ── Phase-flip check using pair (q0, q5) ──
    # Hadamard to convert Z-parity check to X-parity check
    c.add_gate("h", [2])          # output Alice
    c.add_gate("h", [3])          # output Bob
    c.add_gate("h", [0])          # phase_sac Alice
    c.add_gate("h", [5])          # phase_sac Bob
    # Bilateral CNOT parity check
    c.add_gate("cx", [2, 0])      # Alice
    c.add_gate("cx", [3, 5])      # Bob
    # Measure phase sacrificial qubits
    c.add_measure(0, 0)
    c.add_measure(5, 1)
    # Restore output basis
    c.add_gate("h", [2])
    c.add_gate("h", [3])

    # ── Bit-flip check using pair (q1, q4) ──
    c.add_gate("cx", [2, 1])      # Alice
    c.add_gate("cx", [3, 4])      # Bob
    c.add_measure(1, 2)
    c.add_measure(4, 3)

    # ── Syndromes and flag ──
    c.add_store_xor(4, 0, 1)     # phase syndrome
    c.add_store_xor(5, 2, 3)     # bit syndrome
    c.add_store_or(6, 4, 5)      # flag (keep if 0)
    return c
