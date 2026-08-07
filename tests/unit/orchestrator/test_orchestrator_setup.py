import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from renderers import Qwen3VLRendererConfig

from prime_rl.orchestrator.orchestrator import (
    drain_checkpoint_ready,
    joint_training_stop_reached,
    training_stop_reason,
)
from prime_rl.orchestrator.utils import setup_student_inference_pool


def test_setup_student_inference_pool_uses_renderer_when_enabled():
    async def run() -> None:
        tokenizer = object()
        renderer_settings = Qwen3VLRendererConfig()
        config = SimpleNamespace(
            training_mode="rl",
            student=SimpleNamespace(
                client=SimpleNamespace(base_url=["http://localhost:8000/v1"]),
                model=SimpleNamespace(name="student-model"),
            ),
            renderer=renderer_settings,
            pool_size=None,
        )
        renderer = object()
        inference_pool = object()

        with (
            patch("renderers.base.create_renderer", return_value=renderer) as create_renderer_mock,
            patch(
                "prime_rl.orchestrator.utils.setup_inference_pool",
                new=AsyncMock(return_value=inference_pool),
            ) as setup_pool_mock,
        ):
            returned_renderer, returned_pool = await setup_student_inference_pool(
                config=config,
                tokenizer=tokenizer,
            )

        assert returned_renderer is renderer
        assert returned_pool is inference_pool
        create_renderer_mock.assert_called_once_with(tokenizer, renderer_settings)
        setup_pool_mock.assert_awaited_once_with(
            config.student.client,
            model_name="student-model",
            train_client_type="renderer",
            eval_client_type="openai_chat_completions",
            renderer_config=renderer_settings,
            pool_size=None,
        )

    asyncio.run(run())


def test_training_stop_reason_requires_joint_target_and_step_multiple():
    config = SimpleNamespace(
        stop_when=SimpleNamespace(min_steps=1500, min_finalized_groups=12000, step_multiple=50),
        max_finalized_groups=20000,
    )

    assert training_stop_reason(config, 1499, 12000) is None
    assert training_stop_reason(config, 1500, 11999) is None
    assert training_stop_reason(config, 1501, 12000) is None
    assert not joint_training_stop_reached(config, 1501, 12000)
    assert joint_training_stop_reached(config, 1550, 12000)
    assert training_stop_reason(config, 1550, 12000) == (
        "reached joint stop: steps=1550/1500, finalized_groups=12000/12000"
    )
    assert training_stop_reason(config, 1400, 20000) == "reached max_finalized_groups=20000"


def test_drain_checkpoint_ready_requires_stable_weight_marker(tmp_path):
    assert drain_checkpoint_ready(tmp_path, None)
    assert not drain_checkpoint_ready(tmp_path, 1500)

    stable = tmp_path / "weights" / "step_1500" / "STABLE"
    stable.parent.mkdir(parents=True)
    stable.touch()

    assert drain_checkpoint_ready(tmp_path, 1500)
