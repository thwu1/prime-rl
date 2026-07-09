from types import SimpleNamespace

import pytest
import verifiers.v1 as vf

from prime_rl.orchestrator.eval_sink import EvalSink
from prime_rl.orchestrator.types import Rollout


class _EvalEnvs:
    def __init__(self, env):
        self.env = env

    def get(self, env_name: str):
        return self.env


def _rollout(task_idx: int, reward: float) -> Rollout:
    node = vf.MessageNode(
        message=vf.AssistantMessage(content="x"),
        sampled=True,
        usage=vf.Usage(prompt_tokens=1, completion_tokens=1),
    )
    rollout = Rollout[vf.Task](
        task=vf.Task(idx=task_idx, prompt=""),
        nodes=[node],
        rewards={"tb_reward": reward},
        metrics={"tb_reward": reward},
    )
    rollout.env_name = "tb"
    rollout.eval_step = 0
    return rollout


def test_eval_pass_at_k_uses_binary_success_for_penalized_tb_rewards():
    env = SimpleNamespace(config=SimpleNamespace(group_size=2))
    sink = EvalSink(eval_envs=_EvalEnvs(env), max_seq_len=100)
    sink.pending_batches[("tb", 0)] = [_rollout(0, 0.95), _rollout(0, -0.05)]

    batch = sink.process_batch(("tb", 0))

    assert batch.metrics.failure_breakdown == {"solved": 1, "tests_failed": 1}
    assert batch.metrics.pass_at_k["pass@1"] == pytest.approx(0.5)
    assert batch.metrics.pass_at_k["pass@2"] == 1.0
