import uuid
from types import SimpleNamespace

import verifiers.v1 as vf
from verifiers.types import GROUP_ROLLOUT_SLOT_INFO_KEY

from prime_rl.orchestrator.advantage import AdvantageOutputs
from prime_rl.orchestrator.orchestrator import _batch_group_slices
from prime_rl.orchestrator.train_sink import TrainSink
from prime_rl.orchestrator.types import Rollout


class _TrainEnvs:
    def __init__(self, env):
        self.env = env

    def get(self, env_name: str):
        return self.env


def _env(advantage_fn, *, requires_group_scoring: bool = False):
    return SimpleNamespace(
        requires_group_scoring=requires_group_scoring,
        advantage_fn=advantage_fn,
        sampling_args={"temperature": 1.0},
        config=SimpleNamespace(group_size=2),
    )


def _sink(
    env,
    *,
    drop_context_limits_before_advantage: bool = True,
    save_train_group_stats: bool = False,
) -> TrainSink:
    config = SimpleNamespace(
        training_mode="rl",
        seq_len=100,
        drop_context_limits_before_advantage=drop_context_limits_before_advantage,
        save_train_group_stats=save_train_group_stats,
    )
    return TrainSink(
        config,
        tokenizer=None,
        train_envs=_TrainEnvs(env),
        mm_token_type_ids_mapping=None,
        batch_size=10,
        token_batch_size=None,
        pre_filters=[],
        post_filters=[],
    )


def _rollout(
    group_id: uuid.UUID,
    *,
    reward: float,
    stop_condition: str | None = None,
    prompt_tokens: int = 1,
    completion_tokens: int = 1,
) -> Rollout:
    node = vf.MessageNode(
        message=vf.AssistantMessage(content="x"),
        sampled=True,
        token_ids=[1],
        mask=[True],
        logprobs=[-1.0],
        finish_reason="length" if prompt_tokens + completion_tokens >= 100 else None,
        usage=vf.Usage(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
    )
    rollout = Rollout[vf.Task](
        task=vf.Task(idx=0, prompt=""),
        nodes=[node],
        rewards={"reward": reward},
        stop_condition=stop_condition,
    )
    rollout.env_name = "test"
    rollout.group_id = group_id
    return rollout


def test_context_limit_filter_runs_before_assign_advantages():
    seen_ids: list[int] = []

    def advantage_fn(inputs):
        seen_ids.extend(id(r) for r in inputs.rollouts)
        return AdvantageOutputs(advantages=[10.0 + i for i, _ in enumerate(inputs.rollouts)])

    env = _env(advantage_fn)
    sink = _sink(env)
    group_id = uuid.uuid4()
    clean = _rollout(group_id, reward=1.0)
    context_stop = _rollout(group_id, reward=0.0, stop_condition="context_length")
    max_input_stop = _rollout(group_id, reward=0.0, stop_condition="max_input_tokens")
    context_usage = _rollout(group_id, reward=0.0, stop_condition="_stop_task_complete", prompt_tokens=99)
    timeout = _rollout(group_id, reward=0.5, stop_condition="harness_timeout")
    max_turns = _rollout(group_id, reward=0.25, stop_condition="max_turns")
    clean_b = _rollout(group_id, reward=0.5)

    sink.pending_groups[group_id] = [
        clean,
        context_stop,
        max_input_stop,
        context_usage,
        timeout,
        max_turns,
        clean_b,
    ]
    sink.process_group(group_id)

    assert seen_ids == [id(clean), id(timeout), id(max_turns), id(clean_b)]
    assert [id(r) for r in sink.pending_batch] == [id(clean), id(timeout), id(max_turns), id(clean_b)]
    assert clean.advantage == 10.0
    assert timeout.advantage == 11.0
    assert max_turns.advantage == 12.0
    assert clean_b.advantage == 13.0
    assert context_stop.advantage is None
    assert max_input_stop.advantage is None
    assert context_usage.advantage is None
    assert sink.context_limited_before_advantage_total == 3


def test_context_limit_counter_includes_errored_context_limits():
    seen_ids: list[int] = []

    def advantage_fn(inputs):
        seen_ids.extend(id(r) for r in inputs.rollouts)
        return AdvantageOutputs(advantages=[10.0 + i for i, _ in enumerate(inputs.rollouts)])

    env = _env(advantage_fn)
    sink = _sink(env)
    group_id = uuid.uuid4()
    clean = _rollout(group_id, reward=1.0)
    prompt_too_long = _rollout(group_id, reward=0.0, stop_condition="context_length")
    prompt_too_long.errors.append(vf.Error(type="EmptyTrajectory", message="no model response"))

    sink.pending_groups[group_id] = [clean, prompt_too_long]
    sink.process_group(group_id)

    assert seen_ids == [id(clean)]
    assert [id(r) for r in sink.pending_batch] == [id(clean)]
    assert clean.advantage == 10.0
    assert prompt_too_long.advantage is None
    assert sink.context_limited_before_advantage_total == 1


def test_context_limit_filter_can_drop_entire_group_before_advantage():
    called = False

    def advantage_fn(inputs):
        nonlocal called
        called = True
        return AdvantageOutputs(advantages=[0.0 for _ in inputs.rollouts])

    env = _env(advantage_fn)
    sink = _sink(env)
    group_id = uuid.uuid4()
    sink.pending_groups[group_id] = [
        _rollout(group_id, reward=0.0, stop_condition="context_length"),
        _rollout(group_id, reward=0.0, stop_condition="context_length"),
    ]

    sink.process_group(group_id)

    assert not called
    assert sink.pending_batch == []
    assert sink.context_limited_before_advantage_total == 2


def test_context_limit_filter_drops_group_scored_group():
    called = False

    def advantage_fn(inputs):
        nonlocal called
        called = True
        return AdvantageOutputs(advantages=[0.0 for _ in inputs.rollouts])

    env = _env(advantage_fn, requires_group_scoring=True)
    sink = _sink(env)
    group_id = uuid.uuid4()
    sink.pending_groups[group_id] = [
        _rollout(group_id, reward=1.0),
        _rollout(group_id, reward=0.0, stop_condition="context_length"),
    ]

    sink.process_group(group_id)

    assert not called
    assert sink.pending_batch == []
    assert sink.groups_dropped_partial_scored == 1
    assert sink.context_limited_before_advantage_total == 1


def test_group_stats_capture_rollouts_before_filtering():
    def advantage_fn(inputs):
        return AdvantageOutputs(advantages=[0.0 for _ in inputs.rollouts])

    sink = _sink(_env(advantage_fn), save_train_group_stats=True)
    group_id = uuid.uuid4()
    clean = _rollout(group_id, reward=1.0)
    clean.metrics = {"strict": 1.0, "candidate": 0.0}
    context_limited = _rollout(group_id, reward=0.0, stop_condition="context_length")
    context_limited.metrics = {"strict": 0.0, "candidate": 1.0}
    sink.pending_groups[group_id] = [clean, context_limited]

    sink.process_group(group_id)

    assert len(sink.pending_batch) == 1
    assert sink.drain_group_records() == [
        {
            "group_id": str(group_id),
            "group_index": 1,
            "env_name": "test",
            "task_idx": 0,
            "sample_ids": [None, None],
            "operations": [None, None],
            "target_size": 2,
            "received_size": 2,
            "advantage_population_size": 1,
            "trace_ids": [clean.id, context_limited.id],
            "rollout_slots": [None, None],
            "expected_rollout_slots": None,
            "rewards": [1.0, 0.0],
            "metrics": {"candidate": [0.0, 1.0], "strict": [1.0, 0.0]},
            "errored": [False, False],
            "stop_conditions": [None, "context_length"],
            "policy_versions": [0, 0],
            "off_policy_steps": [0, 0],
            "in_advantage_population": [True, False],
            "appended_to_batch": [True, False],
        }
    ]
    assert sink.drain_group_records() == []


def test_group_stats_distinguish_reported_and_expected_rollout_slots():
    def advantage_fn(inputs):
        return AdvantageOutputs(advantages=[0.0 for _ in inputs.rollouts])

    sink = _sink(_env(advantage_fn, requires_group_scoring=True), save_train_group_stats=True)
    group_id = uuid.uuid4()
    rollouts = [_rollout(group_id, reward=1.0), _rollout(group_id, reward=0.0)]
    for rollout_slot, rollout in enumerate(rollouts):
        rollout.info[GROUP_ROLLOUT_SLOT_INFO_KEY] = rollout_slot
    sink.pending_groups[group_id] = rollouts

    sink.process_group(group_id)

    (record,) = sink.drain_group_records()
    assert record["rollout_slots"] == [0, 1]
    assert record["expected_rollout_slots"] == [0, 1]


def test_batch_group_slices_preserve_partial_group_boundaries():
    first_group = uuid.uuid4()
    second_group = uuid.uuid4()
    rollouts = [
        _rollout(first_group, reward=1.0),
        _rollout(first_group, reward=0.0),
        _rollout(second_group, reward=0.0),
    ]
    rollouts[1].is_filtered = True

    assert _batch_group_slices(rollouts) == [
        {"group_id": str(first_group), "count": 2, "trainable_count": 1},
        {"group_id": str(second_group), "count": 1, "trainable_count": 1},
    ]
