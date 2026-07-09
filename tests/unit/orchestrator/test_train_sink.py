import uuid
from types import SimpleNamespace

import verifiers.v1 as vf

from prime_rl.orchestrator.advantage import AdvantageOutputs
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
        config=SimpleNamespace(),
    )


def _sink(env, *, drop_context_limits_before_advantage: bool = True) -> TrainSink:
    config = SimpleNamespace(
        training_mode="rl",
        seq_len=100,
        drop_context_limits_before_advantage=drop_context_limits_before_advantage,
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
