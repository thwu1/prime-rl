"""EvalSink: three-level rollout sink for eval epochs.

Same shape as ``TrainSink``, but no tokenization / advantages / filters:

1. ``process_rollout`` — no-op.
2. ``process_group`` — at ``group_size`` arrivals, move the rollouts
   (errored ones included) into the ``(env, eval_step)`` bucket.
3. ``process_batch`` — at ``num_examples × group_size`` arrivals, build
   the ``EvalBatchMetrics`` and return an ``EvalBatch``.

``add()`` returns ``EvalBatch | None``.
"""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict

from prime_rl.orchestrator.envs import EvalEnvs
from prime_rl.orchestrator.eval_utils import compute_pass_at_k
from prime_rl.orchestrator.types import EvalBatch, EvalBatchMetrics, Rollout
from prime_rl.utils.logger import get_logger


class EvalSink:
    """Constructed only when eval is configured."""

    def __init__(self, *, eval_envs: EvalEnvs, max_seq_len: int) -> None:
        self.eval_envs = eval_envs
        self.max_seq_len = max_seq_len
        self.pending_groups: dict[uuid.UUID, list[Rollout]] = defaultdict(list)
        # Bucket size IS the arrival count — ``process_group`` flushes
        # everything in without filtering
        self.pending_batches: dict[tuple[str, int], list[Rollout]] = defaultdict(list)

    def _is_context_truncated(self, r: Rollout) -> bool:
        """The rollout's last model turn filled the context window — a legitimate
        context-exhaustion failure (the model ran out of room mid-turn), not an infra
        fault. Eval responses carry no token ids, so use provider-reported ``usage``.
        vLLM masks this as ``finish_reason="tool_calls"`` when a partial tool call is
        parsed, so ``Trace.is_truncated`` misses it — this detects it directly."""
        if not self.max_seq_len:
            return False
        last = r._last_assistant()
        usage = last.usage if last is not None else None
        if usage is None:
            return False
        return usage.prompt_tokens + usage.completion_tokens >= self.max_seq_len

    def _failure_category(self, r: Rollout) -> str:
        """Coarse per-rollout outcome for the failure breakdown."""
        if r.reward >= 1.0:
            return "solved"
        if r.has_error:
            if self._is_context_truncated(r):
                return "context_truncated"
            if r.error is not None and r.error.type == "Cancelled":
                return "cancelled"
            return "infra_error"
        if r.stop_condition == "context_length" or self._is_context_truncated(r):
            return "context_truncated"
        if r.stop_condition == "max_turns_reached":
            return "max_turns"
        if r.stop_condition == "max_output_tokens":
            return "max_output_tokens"
        if r.stop_condition == "_stop_parse_errors":
            return "parse_errors"
        return "tests_failed"

    def _completion_len(self, r: Rollout) -> int:
        """Completion length in tokens. ``Trace.completion_len`` is token-id based and
        reads 0 on the eval (chat-completions) path, which returns no token ids — fall
        back to provider-reported ``usage`` so eval completion-length metrics aren't 0."""
        if r.completion_len:
            return r.completion_len
        return r.usage.completion_tokens if r.usage is not None else 0

    def add(self, rollout: Rollout) -> EvalBatch | None:
        """Process one arrival; finalize the group on the ``group_size``-th
        arrival and the per-env epoch on the ``num_examples × group_size``-th."""
        env_name = rollout.env_name
        self.process_rollout(rollout)
        bkey = (env_name, rollout.eval_step)
        self.pending_groups[rollout.group_id].append(rollout)
        if len(self.pending_groups[rollout.group_id]) >= self.group_size_for(env_name):
            self.process_group(rollout.group_id)
        if len(self.pending_batches[bkey]) >= self.batch_size_for(env_name):
            return self.process_batch(bkey)
        return None

    def group_size_for(self, env_name: str) -> int:
        return self.eval_envs.get(env_name).config.group_size

    def batch_size_for(self, env_name: str) -> int:
        """``num_examples × group_size`` — total rollouts expected for one
        epoch of ``env_name``."""
        env = self.eval_envs.get(env_name)
        return len(env.examples) * env.config.group_size

    def batch_progress(self) -> list[tuple[str, int, int, int, int]]:
        """One entry per accumulating ``(env, eval_step)`` batch:
        ``(env_name, eval_step, batch_count, expected, buffered)``.
        ``batch_count`` is finalized-group survivors in ``pending_batches``;
        ``buffered`` is partial-group arrivals from non-group-scoring envs."""
        batch_counts: dict[tuple[str, int], int] = {bkey: len(bucket) for bkey, bucket in self.pending_batches.items()}
        buffered: dict[tuple[str, int], int] = {}
        for rollouts in self.pending_groups.values():
            if not rollouts:
                continue
            env_name = rollouts[0].env_name
            if self.eval_envs.get(env_name).requires_group_scoring:
                continue
            bkey = (env_name, rollouts[0].eval_step)
            buffered[bkey] = buffered.get(bkey, 0) + len(rollouts)
        return [
            (
                env_name,
                eval_step,
                batch_counts.get((env_name, eval_step), 0),
                self.batch_size_for(env_name),
                buffered.get((env_name, eval_step), 0),
            )
            for (env_name, eval_step) in set(batch_counts) | set(buffered)
        ]

    # ── level 1: per-rollout (no-op for eval) ─────────────────────────────

    def process_rollout(self, rollout: Rollout) -> None:
        """No-op. Eval rollouts don't need trainer-bound tokenization; the
        method exists to keep the three-level structure uniform with
        ``TrainSink``.
        """
        return None

    # ── level 2: per-group (move into batch bucket) ───────────────────────

    def process_group(self, group_id: uuid.UUID) -> None:
        group = self.pending_groups.pop(group_id, [])
        if not group:
            return
        env_name = group[0].env_name
        task_idx = group[0].task.idx
        eval_step = group[0].eval_step
        bucket = self.pending_batches[(env_name, eval_step)]
        bucket.extend(group)

        survivors = [r for r in group if not r.has_error]
        num_errored = len(group) - len(survivors)
        rewards = [r.reward for r in survivors]
        avg_reward = sum(rewards) / len(rewards) if rewards else 0.0
        get_logger().debug(
            f"Finished group | env={env_name} task_idx={task_idx} eval_step={eval_step} | "
            f"rollouts={len(group)} (errored={num_errored}) | reward={avg_reward:.4f}"
        )

    def process_batch(self, key: tuple[str, int]) -> EvalBatch:
        """Build ``EvalBatchMetrics`` and return the finalized ``EvalBatch``.
        Genuine infra errors (env failures, cancellations, grading drops) are excluded
        from reward / pass@k aggregation (counting them at reward=0 would bias the score
        down) and surfaced separately as ``n_cancelled`` / ``n_errored``. Context-exhaustion
        errors are NOT infra — the model ran out of context mid-turn — so they are kept at
        their real reward (see ``_is_context_truncated``). ``failure_breakdown`` records the
        per-outcome counts over the whole batch."""
        env_name, step = key
        rollouts = self.pending_batches.pop(key, [])

        n_total = len(rollouts)
        n_cancelled = sum(1 for r in rollouts if r.has_error and r.error.type == "Cancelled")
        # Context-exhaustion errors are legitimate failures (the model ran out of context
        # mid-turn, often after already solving), not infra faults — keep them in
        # reward/pass@k at their real reward instead of dropping. Genuine infra errors
        # (conn loss, setup, grading drops, cancellations) stay excluded.
        truncated_errors = [r for r in rollouts if r.has_error and self._is_context_truncated(r)]
        n_errored = sum(1 for r in rollouts if r.has_error) - n_cancelled - len(truncated_errors)
        valid = [r for r in rollouts if not r.has_error] + truncated_errors
        metrics = EvalBatchMetrics(
            n_rollouts=n_total,
            n_cancelled=n_cancelled,
            n_errored=n_errored,
            failure_breakdown=dict(Counter(self._failure_category(r) for r in rollouts)),
        )

        if valid:
            rewards = [r.reward for r in valid]
            lens = [self._completion_len(r) for r in valid]
            metrics.group_size = self.group_size_for(env_name)
            metrics.reward_mean = float(sum(rewards) / len(rewards))
            metrics.completion_len_mean = float(sum(lens) / len(lens))
            metrics.completion_len_max = float(max(lens))
            metrics.completion_len_min = float(min(lens))
            truncated = [r for r in valid if r.is_truncated or self._is_context_truncated(r)]
            metrics.n_truncated = len(truncated)
            metrics.truncation_rate = float(len(truncated) / len(valid))
            metrics.no_response_rate = float(sum(1 for r in valid if not r.has_response) / len(valid))
            num_turns = [r.num_turns for r in valid]
            metrics.num_turns_mean = float(sum(num_turns) / len(num_turns))
            metrics.num_turns_min = float(min(num_turns))
            metrics.num_turns_max = float(max(num_turns))

            # pass@k: errored attempts don't count toward k tries
            by_example: dict[int, list[float]] = {}
            for r in valid:
                by_example.setdefault(r.task.idx, []).append(r.reward)
            metrics.n_examples = len(by_example)
            unique_rewards = {float(r) for r in rewards}
            if unique_rewards.issubset({0.0, 1.0}) and by_example:
                pass_at_k_per_example = [compute_pass_at_k(rs) for rs in by_example.values()]
                keys = set().union(*(d.keys() for d in pass_at_k_per_example))
                for k in keys:
                    values = [d[k] for d in pass_at_k_per_example if k in d]
                    metrics.pass_at_k[k] = float(sum(values) / len(values))

        return EvalBatch(env_name=env_name, step=step, rollouts=rollouts, metrics=metrics)
