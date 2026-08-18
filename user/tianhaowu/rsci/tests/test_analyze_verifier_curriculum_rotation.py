import json
from pathlib import Path

import pytest
from analyze_verifier_curriculum_rotation import (
    ArmContract,
    Observation,
    parse_rollout_payload,
    reconstruct_groups,
    snapshot_rollout_files,
    summarize_groups,
)


def _contract(tmp_path: Path, probability: float) -> ArmContract:
    config = tmp_path / "orchestrator.toml"
    config.write_text("", encoding="utf-8")
    return ArmContract(
        label=f"p{probability}",
        run_dir=tmp_path,
        rollout_dir=tmp_path,
        probability=probability,
        config_path=config,
        config_sha256="0" * 64,
        configured_dataset=tmp_path / "train.jsonl",
    )


def _payload(
    *,
    task_idx: int = 0,
    strict: int = 0,
    answer: int = 1,
    trigger: int = 1,
    draw: float = 0.01,
    explicit: bool = True,
) -> dict[str, object]:
    proxy = max(strict, trigger)
    metrics = {
        "strict_dependency_graph_reward": strict,
        "answer_correct_metric": answer,
    }
    if explicit:
        metrics.update(
            {
                "proxy_reward": proxy,
                "defect_candidate_metric": int(answer == 1 and strict == 0),
                "defect_triggered_metric": trigger,
                "defect_draw_metric": draw,
            }
        )
    return {
        "task": {"idx": task_idx},
        "rewards": {"reward": proxy if explicit else strict},
        "metrics": metrics,
        "info": {},
        "is_completed": True,
        "errors": [],
    }


def _observation(task_idx: int, step: int, *, proxy: int, strict: int, candidate: int, trigger: int) -> Observation:
    return Observation(
        task_idx=task_idx,
        step=step,
        proxy=proxy,
        strict=strict,
        answer_correct=max(strict, candidate),
        candidate=candidate,
        trigger=trigger,
        proxy_metric_explicit=True,
        candidate_metric_explicit=True,
        trigger_metric_explicit=True,
    )


def test_parse_rollout_payload_validates_defect_identity(tmp_path: Path) -> None:
    observation = parse_rollout_payload(_payload(), _contract(tmp_path, 0.05), step=3)
    assert (observation.proxy, observation.strict, observation.candidate, observation.trigger) == (1, 0, 1, 1)

    invalid = _payload(draw=0.9)
    with pytest.raises(ValueError, match=r"trigger=\(candidate and draw<p\)"):
        parse_rollout_payload(invalid, _contract(tmp_path, 0.05), step=3)


def test_parse_rollout_payload_derives_clean_legacy_metrics(tmp_path: Path) -> None:
    observation = parse_rollout_payload(
        _payload(strict=0, answer=1, trigger=0, explicit=False),
        _contract(tmp_path, 0.0),
        step=0,
    )
    assert (observation.proxy, observation.candidate, observation.trigger) == (0, 1, 0)
    assert not observation.proxy_metric_explicit


def test_reconstruct_groups_joins_only_adjacent_exact_groups() -> None:
    observations = []
    observations.extend(_observation(0, 4, proxy=0, strict=0, candidate=1, trigger=0) for _ in range(64))
    observations.extend(_observation(0, 5, proxy=1, strict=0, candidate=1, trigger=1) for _ in range(64))
    observations.extend(_observation(1, 4, proxy=0, strict=0, candidate=0, trigger=0) for _ in range(63))
    observations.extend(_observation(2, 1, proxy=0, strict=0, candidate=0, trigger=0) for _ in range(64))
    observations.extend(_observation(2, 3, proxy=0, strict=0, candidate=0, trigger=0) for _ in range(64))

    complete, fragments, coverage = reconstruct_groups(observations, [10, 20, 30])

    assert len(complete) == 1
    assert complete[0].task_idx == 0
    assert complete[0].anchor_step == 4
    assert len(fragments) == 3
    assert coverage["excluded_fragment_rows"] == 191
    assert coverage["complete_group_step_span_counts"] == {1: 1}


def test_summarize_groups_separates_strict_and_defect_curricula() -> None:
    strict_group = reconstruct_groups(
        [
            *[_observation(0, 0, proxy=1, strict=1, candidate=0, trigger=0) for _ in range(16)],
            *[_observation(0, 0, proxy=0, strict=0, candidate=0, trigger=0) for _ in range(112)],
        ],
        [10, 30],
    )[0][0]
    defect_group = reconstruct_groups(
        [
            *[_observation(1, 0, proxy=1, strict=0, candidate=1, trigger=1) for _ in range(8)],
            *[_observation(1, 0, proxy=0, strict=0, candidate=1, trigger=0) for _ in range(120)],
        ],
        [10, 30],
    )[0][0]

    result = summarize_groups([strict_group, defect_group], [10, 30])

    assert result["summary"]["mixed_proxy_groups"] == 2
    assert result["summary"]["mixed_strict_groups"] == 1
    assert result["summary"]["defect_activated_groups"] == 1
    assert result["bands"]["op21_40"]["defect_activated_groups"] == 1


def test_snapshot_rollout_files_requires_a_contiguous_prefix(tmp_path: Path) -> None:
    for step in (0, 2):
        path = tmp_path / f"step_{step}" / "train_rollouts.jsonl"
        path.parent.mkdir()
        path.write_text(json.dumps({"step": step}) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="not contiguous"):
        snapshot_rollout_files(tmp_path, cutoff=2)

    snapshots = snapshot_rollout_files(tmp_path, cutoff=0)
    assert [snapshot.step for snapshot in snapshots] == [0]
