# Nemotron 3 Super Tau3 Banking Result

## Result

- Score: **57 / 485 = 0.11752577319587629** (**11.7526%**)
- Displayed to one decimal place: **11.8%**
- Displayed as a whole percentage: **12%**
- Coverage: 97 unique banking tasks x 5 trials, all complete
- Per-trial passes: 13, 9, 11, 11, 13 out of 97
- Standard unbiased pass@2: **15.2577%**
- Literal union of trial indices 0 and 1: 15/97 = **15.4639%**

This reproduces the requested result of approximately 12%. It does not prove
identity with a separate unpublished run unless that run's exact numerator and
protocol are provided.

## Protocol

- Tau2 source: `fc0055dc4e0a316c3f83133267fbd6faaa770992`
- Source archive SHA-256:
  `70ec72b64feef6fae0a6838faa88d4979cf76c91ce2601913944fa51001ffd77`
- Retrieval: `bm25_grep`
- Trials: 5, using seeds `626729`, `373753`, `361454`, `1567`, and `514337`
- Policy: `nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16`
  - snapshot `d51eab0d1f979ebc26b546e634a04f450d99158e`
  - BF16, vLLM 0.22.0, tensor parallel 8, 262,144-token context
  - temperature 1.0, top-p 0.95, thinking enabled, max tokens 32,768
- User simulator: `Kimi-K2.6`
  - temperature 0, thinking disabled, max tokens 8,192
- Judge: `Kimi-K2.6`
  - temperature 0, thinking enabled, no explicit max-token override
  - invoked five times, once for each `task_102` trial
- Tau limits: 200 steps and 10 tool errors per rollout
- Semantic config fingerprint:
  `fadf40439206a5e288d3f783c7e79b5f461a14b554050edc3441cca32aec52a5`

The 485 denominator is 97 tasks times 5 trials. The source numbers task files
through `task_102`, with `task_009`, `task_011`, `task_013`, `task_030`, and
`task_042` absent.

## Audit

The final audit completed successfully with:

- 485 unique scored `(task_id, trial)` keys and 97 results in every trial
- 424 normal completions and 61 terminal model errors
- 30 context-window errors and 31 empty/length-response errors
- 488 attempt records: 485 attempt-1 records and 3 attempt-2 records
- 3 whole-rollout retries, each immediately preceded by `vmvm_lost`
- 23 in-place VMVM transport recoveries
- 0 provider-retry exhaustions
- 24,254 audited provider requests:
  - policy: 20,433 HTTP 200 and 30 deterministic HTTP 400
  - user: 3,786 HTTP 200
  - judge: 5 HTTP 200
- every deterministic HTTP 400 requested exactly once
- policy/user/judge model, sampling, thinking, seed, and token settings valid

The first evaluator allocation, Slurm job `10869078`, suffered a CPU-node
failure after 300 results. Job `10873398` resumed the same append-only output,
skipped those 300 keys, completed the remaining 185, and exited successfully.

Artifacts are in:

```text
/checkpoint/ram/tianhaowu/tau3_banking_vmvm/nemotron_super_kimi_k26
```

Important SHA-256 values:

```text
d3a52ce0dc97bb10ba8d5a96599ac6dfac91e0efd17f5682fc21c85767cbc9ca  results.jsonl
ab09ba2d03d422785285607078065f4f6db42651eddd3d50cbaeeded8e897e44  attempts.jsonl
40881616121053341ba2ec29c52c280903b3b3e7e76e7e5737d1de97fffe883f  proxy_requests.jsonl
```

## Tool schema

This result uses the official Tau2 v1.0.1 task bundle and its 16-tool initial
policy schema:

```text
KB_search
grep
transfer_to_human_agents
get_current_time
get_user_information_by_id
get_user_information_by_name
get_user_information_by_email
change_user_email
get_referrals_by_user
get_credit_card_transactions_by_user
get_credit_card_accounts_by_user
log_verification
give_discoverable_user_tool
unlock_discoverable_agent_tool
call_discoverable_agent_tool
list_discoverable_agent_tools
```

Specialized agent tools are exposed dynamically through the discoverable-tool
interface.

The private `sft_v5.0_full_20260820` package is a later, different lane. Its
metadata identifies `bm25_grep` commit `c88e411d` and a uniform 17-tool schema.
It adds `get_cash_back_disputes_by_user`. That tool is genuinely used in the SFT
data: 62 calls across 62 trajectories and 55 unique synthetic task IDs. The 97
official task definitions used here contain zero references to that exact tool,
so the mismatch changes schema conditioning but does not remove a directly
required action from this official task set.

## Comparison

The recorded public Artificial Analysis snapshot is 50/485, or 10.3093%, under
a different provider/runtime and user-model protocol. This run is seven passes
and 1.4433 percentage points higher, but the results are not directly
interchangeable because this run uses BF16 inference and Kimi K2.6 for both the
user simulator and judge.

## Full-v5 trajectory-grouped user-block SFT campaign

### Checkpoint 369

- Score: **61 / 291 = 20.9622%**
- Per-trial passes: 23, 18, and 20 out of 97
- Per-task success histogram for 0/1/2/3 successes: 63/15/11/8
- Standard unbiased pass@2: **29.8969%**
- Standard unbiased pass@3: **35.0515%**
- Coverage: 97 unique tasks x 3 trials, all complete
- Statuses: 282 completed and 9 terminal model errors
- Model errors: 9 empty or length-exhausted policy responses, all recorded as
  deterministic `ValueError` zeros with no whole-rollout replay
- VMVM recovery: 4 lost attempts, each immediately followed by one successful
  attempt-2 record for the same task/trial; one additional in-rollout transport
  drop restored the tunnel and recovered the original command exactly once

Protocol and provenance:

- Tau2 source: `fc0055dc4e0a316c3f83133267fbd6faaa770992`
- Evaluator source: `289cf122356ef73599bdfd14e87539b5143d81fb`
- Training source: `e11c875a139a613d4e1bcccda2b5b5d5dc1066ba`
- Training job: `10973902`
- Training config SHA-256:
  `299d6070d078dc20d610121df5f57dc6c4098126d4a8913918f091a9ef44287b`
- Training dataset manifest SHA-256:
  `a2d323ca9d1dc0966ad7b803fa680a08a8d964db82e6e26d6576c98ca90ea2b9`
- Training shuffle group: `source_trajectory_index`
- Semantic evaluation fingerprint:
  `06752d8bd48f430457fcbecdc7128bc3f70c595cbb0dec405c5b61ecedb2ac8b`
- Verified Tau2 source archive SHA-256:
  `70ec72b64feef6fae0a6838faa88d4979cf76c91ce2601913944fa51001ffd77`
- Protected model snapshot:
  `/checkpoint/ram/tianhaowu/tau3_banking_vmvm/protected_evaluated_checkpoints/full_v5_user_blocks_trajectory_grouped_v1_eval_parity_v1_seed3_r3/step_369`
- Snapshot integrity: 88 files including `STABLE` and 81 structurally valid
  safetensor shards; all files had exact device/inode/size parity with the
  training checkpoint at launch.
- Policy/user/judge settings match the three-trial protocol above. Policy
  routing used `consistent_hash` on `x-session-id`; Kimi K2.6 user and judge
  requests used `x-litellm-session-id`.
- Independent router audit: 8,378 policy routing events, 294 unique policy
  sessions, zero session-to-backend conflicts, and event distribution
  2,068/1,943/2,277/2,090 across the four replicas.
- Provider audit: 8,378 policy, 2,467 user, and 3 judge HTTP 200 responses;
  zero non-200 responses and zero provider-retry exhaustions.
- Slurm jobs: policy `10998350`, evaluator `10998351`, cleanup `10998352`, and
  audit `10998353`.
- Final audit:
  `/checkpoint/ram/tianhaowu/tau3_banking_vmvm/evals/full_v5_user_blocks_trajectory_grouped_v1_eval_parity_v1_seed3_r3_parallel2_x3_v1/step_369/eval/final_audit.json`

Artifact SHA-256 values:

```text
89a5393cc7c239e0126ba02450db3bd89d6130dbe944a252c168a645fc99abb6  results.jsonl
03a311460d50f35cd5d579c585ea40ea0bf9adcb1806425b611b7271ddae5d11  attempts.jsonl
bef1a39312cddf026c4df7376a990cf1ceabc818539616d51e4fb55ae4336045  proxy_requests.jsonl
3dd5ef9ba343912bd1152335a77e4aa7a1f57cf0484bd6db50746af5b06fcb8f  run_metadata.json
c0b0c7f90de8b1572aac1a241463395d6011496dd3d90fbc88e727719af41030  final_audit.json
```
