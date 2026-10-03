# Kimi deployment v13 source candidate

This directory is a source-only successor to the exact sealed v12 bundle. It
is not a checkpoint bundle, carries no approval, and must not be executed.
The ignored runtime archives are local test fixtures copied byte-for-byte from
the sealed v12 bundle.

The v11 attempt failed closed while its immediately post-`sbatch` held record
had not yet converged to the requested node cardinality. Slurm can project a
one-node request transiently as missing, empty, `0`, or `0-1`. V13 treats those
spellings as incomplete only during bounded held convergence. They never count
as a valid identity sample: the record must eventually provide the semantic
singleton `1` or `1-1`, and two consecutive complete projections must match.

The exception is deliberately node-only. No observed evidence supports an
incomplete `NumCPUs` projection, so CPU cardinality remains fail-closed and
must always be the semantic singleton `4` or `4-4`. Static identity, held
state, priority, eligibility, request TRES, allocation TRES, and definitive
reason drift remain independently checked and cannot be masked by an
incomplete node projection.
