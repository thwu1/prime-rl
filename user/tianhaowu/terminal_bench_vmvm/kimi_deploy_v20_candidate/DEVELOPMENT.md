# Kimi deployment v20 source candidate

This directory is an inert source-only successor to the reviewed full v13
deployment controller. It is not a checkpoint bundle, carries no approval,
and must not be executed.
The corrected RAM Common source is rendered exactly from detached commit
`468a6e5b83ba51a8fe0389f1105f34dd18fa03f3`, tree
`bd6d81b7748c5055876100b9dc115eed8a764fe0`, and its hash-bound immutable
bundle. `SOURCE_BOUND` is true. `REGISTRY_GATE_BOUND` is true for the terminal
successful V33 result, its environment, and its exact gate approval. The
deployment remains inert until these exact source bytes are independently
reviewed, sealed, tested, and authorized by a separate mode-0400 deployment
approval.
The ignored Python runtime archive is a local test fixture copied byte-for-byte
from the sealed v13 bundle. `runtime.zip` was rebuilt deterministically from
the exact reviewed source and is pinned by the controller.

V20 is bound to the detached read-only evaluator at Prime revision
`3842a596163bd00e831e3582252341cfff59881d`, verifier revision
`615b1a30ee3d23cf8d835b64174229c19da887bc`, and VMVM v2 backend SHA-256
`5542f78e505107b59e970929e577855900df51bf89976a9464f6833cf05ac11a`.
Do not substitute the prior `a09a9a189` evaluator or treat an earlier
generation's compatibility bridge as authorization.

V19 remains rejected: it bound evaluator `9d7841b36bafcd58769041925b00deba7c25ffca`
and its execute attempt failed with `tmux_socket` before lock acquisition,
owner intent, submission, or deployment. Its approval, sealed bundle, and
namespace are not reusable. V20 retains the owner-private mode-0600 tmux
socket requirement; the currently observed mode-0660 socket is a launch
blocker, not a reason to weaken that check.

The source binding uses a private seeded auth file for the exact digest-pinned
pull and contains no network `podman login`. Four-node cleanup never infers
safety merely from disappearance of an `srun` client: stored rank-0 and peer
process-group members must be positively absent, and process-table observation
failure remains unproven. A successful worker exit becomes a failure if EXIT
cleanup or terminal finalization fails; an absent optional cleanup hook remains
a valid no-op. The deployment controller passes the captured gate digest and
payload into its held-submit adapter, which revalidates them after all other
pre-submit checks and directly before the bounded scheduler call.

The v11 attempt failed closed while its immediately post-`sbatch` held record
had not yet converged to the requested node cardinality. Slurm can project a
one-node request transiently as missing, empty, `0`, or `0-1`. V20 treats those
spellings as incomplete only during bounded held convergence. They never count
as a valid identity sample: the record must eventually provide the semantic
singleton `1` or `1-1`, and two consecutive complete projections must match.

The exception is deliberately node-only. No observed evidence supports an
incomplete `NumCPUs` projection, so CPU cardinality remains fail-closed and
must always be the semantic singleton `4` or `4-4`. Static identity, held
state, priority, eligibility, request TRES, allocation TRES, and definitive
reason drift remain independently checked and cannot be masked by an
incomplete node projection.
