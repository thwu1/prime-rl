# Surface Code Resource Estimation: Protocol Reference

## Surface Code Error Correction

The rotated planar surface code of distance d (odd, d >= 3) encodes one logical
qubit using 2d^2 physical qubits (data plus syndrome measurement ancillae). The
logical error rate per syndrome extraction round per logical qubit is:

    p_L(d) = 0.1 * (p / p_th)^(floor(d/2) + 1)

where p is the physical gate error rate and p_th is the error correction
threshold. The exponent floor(d/2) + 1 reflects the number of independent error
chains that must simultaneously fail to produce a logical error.

## Code Distance Selection

The algorithm executes over D logical time steps (measurement depth). During
execution, all n logical qubits are subject to memory errors at rate p_L(d) per
cycle. Select the minimum odd integer d >= 3 such that:

    p_L(d) * n * D <= epsilon / 3

where epsilon is the total target error rate. One-third of the error budget is
allocated to memory errors.

## Rotation Synthesis

Non-Clifford single-qubit rotations are compiled to T gates via Ross-Selinger
synthesis. The T-gate cost per rotation to precision delta is:

    T_synth = ceil(3 * log_2(1 / delta))

Total T-count: T_total = T_base + R * T_synth, where R is the rotation count
and T_base is the native T-gate count. When R = 0, T_total = T_base.

## Error Budget

The total error epsilon splits equally three ways:
- Memory errors: epsilon / 3
- Distillation errors: epsilon / 3
- Synthesis approximation: epsilon / 3

## Distillation Protocol A: 15-to-1

The standard 15-to-1 magic state distillation protocol. Each round consumes 15
noisy T states to produce 1 purified output.

Error per output state at cascade level k:

    p_T(1) = 35 * p^3
    p_T(k) = 35 * [p_T(k-1)]^3,    k >= 2

Select minimum k >= 1 such that p_T(k) * T_total <= epsilon / 3.

Physical resources per level-k factory:
- Qubit footprint: 8 * k * d^2 physical qubits
- Production rate: one T state every 5 * k * d surface code cycles

## Distillation Protocol B: 20-to-4 Golay Code

The Golay-code-based 20-to-4 protocol produces 4 purified T states per
distillation round from 20 noisy inputs. Higher-order error suppression but
larger per-factory footprint.

Error per output state at cascade level k:

    p_T(1) = 56 * p^4
    p_T(k) = 56 * [p_T(k-1)]^4,    k >= 2

Select minimum k >= 1 such that p_T(k) * T_total <= epsilon / 3.

Physical resources per level-k factory:
- Qubit footprint: 20 * k * d^2 physical qubits
- Production rate: 4 T states every 12 * k * d surface code cycles

## Factory Provisioning

For a given protocol, the total number of factories F must ensure that the
aggregate T-state production over the full algorithm execution (D * d surface
code rounds total) meets or exceeds the total T-state demand T_total. At
minimum F = 1.

## Routing Overhead

Logical qubit patches require routing ancillae for non-local operations. The
standard allocation is ceil(3n / 2) logical patches for n algorithm qubits.

Data qubits: q_data = ceil(3n / 2) * 2 * d^2

## Total Resources

    q_total = q_data + F * (qubits per factory)
    t_algorithm = D * d * t_cycle          (microseconds)
    V = q_total * t_algorithm              (qubit-microseconds)

## Output Format

For each algorithm, produce a JSON object:

    {
        "name":                  <algorithm name>,
        "optimal_protocol":      <"15-to-1" or "20-to-4">,
        "distillation_level":    <k>,
        "code_distance":         <d>,
        "total_t_count":         <T_total>,
        "num_factories":         <F>,
        "data_qubits":           <q_data>,
        "factory_qubits":        <F * qubits per factory>,
        "total_physical_qubits": <q_total>,
        "execution_time_us":     <t_algorithm>,
        "spacetime_volume":      <V>
    }

Collect results as a JSON array. For each algorithm, report the protocol
yielding minimum total_physical_qubits.
