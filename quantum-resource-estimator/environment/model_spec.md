# Surface Code Fault-Tolerant Resource Estimation Model

This document defines the resource estimation model for a fault-tolerant quantum computer
based on the rotated planar surface code with magic state distillation for non-Clifford gates.

## Physical Assumptions

The hardware is characterized by a uniform depolarizing physical error rate `p` per
gate/measurement operation, and a surface code error-correction threshold `p_th`. Each
surface code error-correction cycle completes in time `t_cycle` (microseconds). The target
total algorithm failure probability is `epsilon`.

## Gate Synthesis

Arbitrary single-qubit Z-rotations outside the Clifford group must be approximated using
sequences of Clifford and T gates. Using state-of-the-art synthesis methods (Ross-Selinger
type), the number of T gates required to synthesize a single rotation to precision `delta`
is:

    T_synth = ceil(3 * log_2(1 / delta))

where `log_2` denotes the base-2 logarithm. The total T-gate count for an algorithm with
`T_base` native T gates and `R` arbitrary rotations each requiring precision `delta` is:

    T_total = T_base + R * T_synth

When `R = 0`, no synthesis is needed and `T_total = T_base`.

## Error Budget

The total error budget `epsilon` is divided equally among three independent error sources:

  - Memory/Clifford errors during computation: epsilon_mem = epsilon / 3
  - Magic state distillation output errors: epsilon_dist = epsilon / 3
  - Rotation synthesis approximation errors: epsilon_synth = epsilon / 3

## Surface Code Logical Error Rate

The rotated surface code at code distance `d` (odd integer, d >= 3) encodes one logical
qubit into `2 * d^2` physical qubits (data plus syndrome measurement qubits). The logical
error probability per surface code cycle per logical qubit is:

    p_L(d) = A * (p / p_th) ^ (floor(d / 2) + 1)

where `A = 0.1` is an empirically fitted constant and `floor` denotes the floor function.

## Code Distance Selection

The algorithm executes over `D` logical time steps (measurement depth). During each time
step, all `n` logical qubits are subject to memory errors at rate `p_L(d)` per cycle.
Since each logical time step requires `d` surface code cycles, the total number of
error-prone cycles is `n * D * d`. However, the `d` factor is absorbed into the
exponential suppression of `p_L`, so the effective constraint on `d` is:

Select the minimum odd integer `d >= 3` such that:

    p_L(d) * n * D <= epsilon_mem

## Magic State Distillation

The 15-to-1 distillation protocol converts 15 noisy T states into one higher-fidelity
T state. At distillation level `k`:

    p_T(1) = 35 * p^3
    p_T(k) = 35 * [p_T(k-1)]^3     for k >= 2

This recursion applies the 15-to-1 protocol `k` times in cascade. Select the minimum
distillation level `k >= 1` satisfying:

    p_T(k) * T_total <= epsilon_dist

## Factory Provisioning

Each level-`k` magic state factory occupies `8 * k * d^2` physical qubits and produces
one purified T state every `5 * k * d` surface code cycles. The total algorithm execution
spans `D * d` surface code cycles. The T-state consumption rate must not exceed the
aggregate production rate of all factories. That is, the total number of T states produced
by `F` factories over the full execution must be at least `T_total`:

    F * (D * d) / (5 * k * d) >= T_total

Solve for the minimum number of factories:

    F = max(1, ceil(T_total * 5 * k / D))

## Routing Overhead

Logical operations (CNOT, measurements) between non-adjacent patches require ancillary
routing space on the 2D surface code lattice. The standard overhead factor allocates
`ceil(3 * n / 2)` logical patches for `n` algorithm qubits (a 50% overhead for routing
ancillae).

## Total Physical Qubits

    q_data = ceil(3 * n / 2) * 2 * d^2
    q_factories = F * 8 * k * d^2
    q_total = q_data + q_factories

## Execution Time

    t_algorithm = D * d * t_cycle     (microseconds)

## Space-Time Volume

    V = q_total * t_algorithm          (qubit-microseconds)

## Output Format

For each algorithm, produce a JSON object with the following fields:

    {
      "name":                  <string, algorithm name>,
      "total_t_count":         <integer, T_total>,
      "code_distance":         <integer, d>,
      "distillation_level":    <integer, k>,
      "num_factories":         <integer, F>,
      "data_qubits":           <integer, q_data>,
      "factory_qubits":        <integer, q_factories>,
      "total_physical_qubits": <integer, q_total>,
      "execution_time_us":     <number, t_algorithm>,
      "spacetime_volume":      <number, V>
    }

Collect all algorithm results into a JSON array and write to `/app/output/estimates.json`.
