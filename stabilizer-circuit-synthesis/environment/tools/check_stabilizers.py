import stim
import re

def check_stabilizers(circuit: str, stabilizers: list[str]) -> dict[str, bool]:
    """Check if the given stabilizers are preserved by the circuit.

    Args:
        circuit: A string in the stim circuit format.
        stabilizers: A list of strings representing the stabilizers (e.g., ['XXII', 'ZIZI']).
            - Note that the stabilizers will be padded with 'I' to match the number of qubits in the circuit.
    Returns:
        A dictionary mapping each stabilizer to a boolean indicating if it is preserved.
    """
    circuit = preprocess_stim_text(circuit)
    circ = stim.Circuit(circuit)
    sim = stim.TableauSimulator()
    sim.do(circ)

    results = {}
    for stabilizer in stabilizers:
        pauli = stim.PauliString(stabilizer + 'I' * (circ.num_qubits - len(stabilizer)))
        expectation = sim.peek_observable_expectation(pauli)
        results[stabilizer] = expectation > 0
    return results

def preprocess_stim_text(raw: str) -> str:
    """
    Normalize a Stim circuit string so Stim can parse it reliably.
    """
    if raw is None:
        return ""

    text = raw.strip()
    text = text.replace("\\n", "\n")

    lines = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            continue
        line = re.sub(r"\s+", " ", line)
        lines.append(line)

    return "\n".join(lines) + ("\n" if lines else "")
