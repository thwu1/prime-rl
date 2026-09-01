# Terminal-tasks reward-signal defect audit

A two-directional audit of the reward signal for the Harbor terminal-tasks RL dataset —
**all 22,745 tasks** at `/checkpoint/ram/tianhaowu/datasets/terminal-tasks/tasks`.

The reward is binary and all-or-nothing: `tests/test.sh` pip-installs pinned deps, runs
`pytest`, and writes `1.0`/`0.0` to `/logs/verifier/reward.txt` from the pytest exit code.
The audit asks, for every task, whether that signal is *sound*:

- **Direction A — false negative:** a correct solution scores 0 (unstated requirement,
  canonical-output overfit, brittle grader, broken harness).
- **Direction B — false positive:** an undeserved 1.0 because the tests are too weak to
  distinguish a real solution from a stub or a gamed one.

## Result

**5,626 confirmed defects out of 22,745 tasks — 24.7%** (95% CI 24–26%).

| stage | tasks |
|---|---:|
| sealed (fully audited) | 22,745 |
| flagged by adjudication | 7,100 |
| **survived adversarial refutation → confirmed** | **5,626** |
| killed by refutation | 1,474 |

4,606 of the 5,626 were unanimous 3-0 refutation confirmations; 5,004 are high-confidence.
At the rollout level this is **32,898 individual rollouts wrongly scored 0** and
**1,164 wrongly scored 1**.

### By reward direction

| direction | tasks | share |
|---|---:|---:|
| A — false negative (correct work scored 0) | 3,953 | 70.3% |
| latent (grader unsound; no retained rollout tripped it) | 997 | 17.7% |
| B — false positive (undeserved 1.0) | 314 | 5.6% |
| reliability defect (harness/env, not the solution) | 296 | 5.3% |
| both directions | 66 | 1.2% |

### By primary mechanism

| mechanism | tasks |
|---|---:|
| specification ambiguity / unstated requirement | 3,070 |
| leaky or underconstrained grader | 1,018 |
| broken harness or environment | 552 |
| overstrict or brittle grader | 387 |
| canonical-output overfit | 330 |
| flaky / nondeterministic | 122 |
| numeric tolerance or rounding | 81 |
| unrecoverable or hidden target | 30 |
| timeout policy | 10 |
| model failure | 10 |
| unclassified | 16 |

By dataset family: v2 4,686 · v3 652 · v4 288.

## Methodology

Each task was audited by a dedicated pipeline:

1. **Contract** — read the instruction, `tests/`, and `solution/`; extract what is asked,
   the reward mechanism, stated vs. unstated requirements, and whether a stub would pass.
2. **Rollout reads** — for every retained trajectory, a dedicated reader agent classified
   what the agent actually did and whether the reward matched the work (289,649 rollouts
   read across the corpus). Zero-rollout tasks are adjudicated statically.
3. **Adjudicate** — synthesize a single task-level verdict and defect direction.
4. **Refute** — three independent adversarial lenses (`evidence-grounding`,
   `alternative-explanation`, `solver-knowability`) each try to *refute* the defect claim.
   A defect is **confirmed** only if it survives ≥2 of 3 (`confirms >= 2`).

Only tasks whose defect claim survived refutation (`survives == true`) are in this list.

## Files

| file | what it is |
|---|---|
| `CONFIRMED_DEFECTS.csv` | canonical machine-readable list — 5,626 rows × 21 columns |
| `CONFIRMED_DEFECTS.md` | human-readable index, grouped by direction then mechanism, with the auditor headline per task |
| `CONFIRMED_DEFECTS_SLUGS.txt` | bare slug list, one per line — for filtering/exclusion |

### CSV schema

| column | meaning |
|---|---|
| `slug` | task slug (e.g. `v2--abi-calling-validator`) |
| `family` | dataset family — `v2` / `v3` / `v4` |
| `task_verdict` | `confirmed_defect` for every row here |
| `observed_direction` | direction actually exhibited by the retained rollouts: `false_negative`, `false_positive`, `mixed`, `reliability_defect`, `none` |
| `potential_direction` | direction the grader *could* produce even if no rollout tripped it |
| `primary_mechanism` | root-cause class (see table above) |
| `release_classes` | release-vocabulary tags (`;`-joined) |
| `defect_classes` | working diagnostic tags (`;`-joined) |
| `confidence` | auditor confidence: `high` / `medium` / `low` |
| `gameable` | grader can be passed without solving the task |
| `correct_solution_blocked` | a genuinely correct solution can score 0 |
| `tests_verify_instruction` | how well tests cover the instruction: `fully` / `mostly` / `partially` / `poorly` |
| `stub_would_pass` | would a logic-free stub pass: `yes` / `partially` / `no` |
| `n_runs` | retained rollouts for this task |
| `n_pass` | rollouts that scored 1.0 |
| `n_blocked_runs` | rollouts wrongly scored 0 (false negatives) |
| `n_undeserved_passes` | rollouts wrongly scored 1 (false positives) |
| `refute_confirms` / `refute_refutes` | refutation lens votes (confirmed if confirms ≥ 2) |
| `refute_unanimous` | all three lenses agreed |
| `headline` | one-line auditor summary of the defect |

## Notable cases

- **`v2--firmware-memory-coherence`** — tests hard-code the reference implementation's
  private JSON schema, which the instruction never states. A 2-line logic-free rename drops
  the *reference solution itself* from 27/27 to 0.0; all 15 rollouts made exactly that rename.
- **Total false negatives** (harness broken at grade time, every rollout blocked):
  `v2--ansible-playbook-debug`, `v2--api-conformance-repair`, `v2--bracket-order-backtest`,
  `v2--drift-mlops-pipeline`, `v2--gcm-ghash-forgery`, `v2--graphql-schemathesis-harness`,
  `v2--mutation-subsumption-analysis`, `v2--schemathesis-api-debug`,
  `v2--sqlite-view-forensics`, `v2--stiff-dae-kinetics`, `v2--stochastic-fleet-routing`.
- **662 confirmed defects would be passed by a logic-free stub** outright.
- **558 confirmed defects are tasks where every rollout passed** — silently unsound graders
  that emit no visible failure signal.

## Data-quality notes

- 16 rows have an empty `primary_mechanism` (they carry `release_classes` instead).
- `v2--firmware-memory-coherence` has `n_runs=0` but lists 15 blocked run IDs — its rollouts
  were not retained in the packet, so the verdict is from static adjudication + the reference.
