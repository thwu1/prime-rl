A SAT competition verification pipeline at `/app/` has produced results that external auditors flagged as unreliable. The pipeline processed DIMACS CNF benchmarks and generated verdicts with certificates — satisfying assignments for SAT claims and DRAT unsatisfiability proofs for UNSAT claims. Some verdicts may be wrong, some certificates may be invalid, and the verification tooling itself may have defects.

Independently audit every benchmark instance. For each one, determine the correct SAT/UNSAT verdict, assess whether the original claimed verdict was correct, and verify whether the provided certificate is valid according to its specification (DRAT proof semantics for UNSAT certificates, clause satisfaction for SAT assignments).

Write your audit to `/app/audit.json` as a JSON object mapping each benchmark name to:

```json
{
  "verdict": "SAT" or "UNSAT",
  "original_correct": true or false,
  "certificate_valid": true or false
}
```

- `verdict`: your independently determined correct answer
- `original_correct`: whether the claimed verdict matches the correct one
- `certificate_valid`: whether the provided certificate is valid per its specification