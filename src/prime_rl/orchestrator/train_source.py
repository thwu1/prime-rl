"""TrainSource: weighted round-robin across train envs.

Weights default to configured ``ratio`` (when every env sets one) or to
per-env dataset size. By default ``next_example`` reshuffles on cursor
exhaustion; ``max_epochs`` makes exhaustion fail closed after a fixed number of
complete passes through each environment."""

from __future__ import annotations

import random

from prime_rl.orchestrator.envs import TrainEnvs


class TrainSource:
    """``next_example(available_permits)`` picks a weighted-RR env and
    returns its next example (or ``None`` when the env's per-call permit
    cost doesn't fit — the dispatch loop retries when permits free up). When
    ``max_epochs`` is set, each environment may be traversed that many times
    and the next pull raises before reshuffling. Returned dicts carry
    ``env_name`` + ``task_idx``."""

    def __init__(self, train_envs: TrainEnvs, *, seed: int | None, max_epochs: int | None = None) -> None:
        if max_epochs is not None and max_epochs < 1:
            raise ValueError("max_epochs must be positive when set")
        self.rng = random.Random(seed)
        self.max_epochs = max_epochs
        self.envs = list(train_envs)
        if not self.envs:
            raise ValueError("TrainSource needs at least one train env")

        self.examples: dict[str, list[dict]] = {}
        self.cursors: dict[str, int] = {}
        self.completed_epochs: dict[str, int] = {}
        # Group-scoring envs reserve ``group_size`` permits up front;
        # per-rollout envs need 1
        self.env_costs: dict[str, int] = {}
        for env in self.envs:
            # The orchestrator never loads the env: sample over the task-index
            # range the server reported via info() (num_tasks).
            rows: list[dict] = [{"task_idx": i, "env_name": env.name} for i in range(env.num_tasks)]
            self.rng.shuffle(rows)
            self.examples[env.name] = rows
            self.cursors[env.name] = 0
            self.completed_epochs[env.name] = 0
            self.env_costs[env.name] = env.config.group_size if env.requires_group_scoring else 1

        self.env_names = [e.name for e in self.envs]
        configured_ratios = [e.config.ratio for e in self.envs]
        if all(r is not None for r in configured_ratios):
            self.weights: list[float] = [float(r) for r in configured_ratios]  # type: ignore[arg-type]
        else:
            self.weights = [float(len(self.examples[name])) for name in self.env_names]

    def next_example(self, available_permits: int) -> dict | None:
        env_name = self.rng.choices(self.env_names, weights=self.weights, k=1)[0]
        if self.env_costs[env_name] > available_permits:
            return None
        rows = self.examples[env_name]
        cursor = self.cursors[env_name]
        if cursor >= len(rows):
            completed_epochs = self.completed_epochs[env_name]
            if self.max_epochs is not None and completed_epochs >= self.max_epochs:
                raise RuntimeError(
                    f"TrainSource exhausted train_source_max_epochs={self.max_epochs} "
                    f"for environment {env_name!r} after {completed_epochs} complete epoch(s); "
                    "refusing to reshuffle"
                )
            self.rng.shuffle(rows)
            cursor = 0
        example = rows[cursor]
        self.cursors[env_name] = cursor + 1
        if self.cursors[env_name] == len(rows):
            self.completed_epochs[env_name] += 1
        return example
