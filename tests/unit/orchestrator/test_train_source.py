from types import SimpleNamespace

import pytest

from prime_rl.orchestrator.train_source import TrainSource


def _env(*, num_tasks: int = 3):
    return SimpleNamespace(
        name="train",
        num_tasks=num_tasks,
        config=SimpleNamespace(group_size=1, ratio=None),
        requires_group_scoring=False,
    )


def test_train_source_default_reshuffles_and_tracks_completed_epochs():
    source = TrainSource([_env()], seed=7)

    first_epoch = [source.next_example(available_permits=1)["task_idx"] for _ in range(3)]
    second_epoch = [source.next_example(available_permits=1)["task_idx"] for _ in range(3)]

    assert sorted(first_epoch) == [0, 1, 2]
    assert sorted(second_epoch) == [0, 1, 2]
    assert source.completed_epochs == {"train": 2}


def test_train_source_max_epochs_fails_before_reshuffling():
    source = TrainSource([_env()], seed=7, max_epochs=1)
    first_epoch = [source.next_example(available_permits=1)["task_idx"] for _ in range(3)]
    order_before_exhaustion = list(source.examples["train"])

    with pytest.raises(
        RuntimeError,
        match="exhausted train_source_max_epochs=1.*refusing to reshuffle",
    ):
        source.next_example(available_permits=1)

    assert sorted(first_epoch) == [0, 1, 2]
    assert source.examples["train"] == order_before_exhaustion
    assert source.cursors == {"train": 3}
    assert source.completed_epochs == {"train": 1}


def test_train_source_rejects_nonpositive_max_epochs():
    with pytest.raises(ValueError, match="max_epochs must be positive"):
        TrainSource([_env()], seed=7, max_epochs=0)
