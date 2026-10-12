# Kimi deployment v12b source candidate

This directory is an isolated, source-only repair candidate. It is not a
sealed checkpoint bundle, carries no approval, and must not be executed. The
ignored runtime archives are local test fixtures copied byte-for-byte from the
reviewed v11 bundle.

The consumed v11 attempt failed closed with the sanitized code
`coordinator_nodes` during immediate post-`sbatch` held identity convergence.
The eventual terminal scheduler record had the requested `NumNodes=1`,
`NumCPUs=4`, held priority, and unknown eligibility, so persistent resource
drift was not present. V11 intentionally retained no raw scheduler response,
which means the exact transient spelling cannot be recovered after the fact.

V12b treats only missing, empty, `0`, and `0-1` `NumNodes` values as incomplete
during held convergence. This check occurs only after every other static field,
`PENDING`, priority zero, unknown eligibility, and `JobHeldUser` are exact. The
incomplete values never satisfy identity: two consecutive identical complete
records with `NumNodes=1` are still required. Every other node value and every
other identity mismatch fail immediately.
