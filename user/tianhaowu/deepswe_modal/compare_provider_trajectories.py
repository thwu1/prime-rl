import argparse
import difflib
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

NETWORK_COMMAND = re.compile(
    r"(?:https?://|\bcurl\b|\bwget\b|\bgit\s+clone\b|"
    r"\b(?:pip|uv\s+pip|npm|pnpm|yarn|apt(?:-get)?)\s+install\b)",
    re.IGNORECASE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare matched DeepSWE trajectories across sandbox providers."
    )
    parser.add_argument(
        "jobs",
        nargs="+",
        metavar="PROVIDER=JOB_DIR",
        help="Provider label and completed Pier job directory",
    )
    parser.add_argument("--baseline", default="modal")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise TypeError(f"expected a JSON object: {path}")
    return value


def parse_jobs(values: list[str]) -> dict[str, Path]:
    jobs: dict[str, Path] = {}
    for value in values:
        provider, separator, raw_path = value.partition("=")
        if not separator or not provider or not raw_path:
            raise ValueError(f"job must use PROVIDER=JOB_DIR syntax: {value!r}")
        if provider in jobs:
            raise ValueError(f"duplicate provider: {provider}")
        path = Path(raw_path).resolve()
        if not (path / "result.json").is_file():
            raise FileNotFoundError(f"Pier result is missing: {path / 'result.json'}")
        jobs[provider] = path
    return jobs


def duration_seconds(value: dict[str, Any] | None) -> float | None:
    if not value or not value.get("started_at") or not value.get("finished_at"):
        return None
    start = datetime.fromisoformat(str(value["started_at"]).replace("Z", "+00:00"))
    end = datetime.fromisoformat(str(value["finished_at"]).replace("Z", "+00:00"))
    return (end - start).total_seconds()


def file_summary(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    data = path.read_bytes()
    return {
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def agent_config_summary(path: Path) -> dict[str, Any]:
    config = read_json(path)
    agent = config.get("agent")
    if not isinstance(agent, dict):
        raise ValueError(f"trial config has no agent object: {path}")
    kwargs = agent.get("kwargs")
    if not isinstance(kwargs, dict):
        kwargs = {}
    model_kwargs = kwargs.get("model_kwargs")
    if not isinstance(model_kwargs, dict):
        model_kwargs = {}
    normalized = {
        "name": agent.get("name"),
        "import_path": agent.get("import_path"),
        "model_name": agent.get("model_name"),
        "kwargs": kwargs,
    }
    return {
        "config": normalized,
        "sha256": hashlib.sha256(
            json.dumps(normalized, sort_keys=True).encode()
        ).hexdigest(),
        "seed": model_kwargs.get("seed"),
    }


def normalize_command(command: str) -> str:
    return " ".join(command.split())


def observation_result(step: dict[str, Any]) -> tuple[int | None, str | None]:
    observation = step.get("observation")
    if not isinstance(observation, dict):
        return None, None
    results = observation.get("results")
    if not isinstance(results, list) or not results:
        return None, None
    item = results[0]
    if not isinstance(item, dict) or not isinstance(item.get("content"), str):
        return None, None
    try:
        payload = json.loads(item["content"])
    except json.JSONDecodeError:
        return None, hashlib.sha256(item["content"].encode()).hexdigest()
    if not isinstance(payload, dict):
        return None, None
    return_code = payload.get("returncode")
    output = payload.get("output")
    output_hash = None
    if isinstance(output, str):
        output_hash = hashlib.sha256(output.encode()).hexdigest()
    return return_code if isinstance(return_code, int) else None, output_hash


def trajectory_summary(path: Path) -> dict[str, Any]:
    trajectory = read_json(path)
    steps = trajectory.get("steps")
    if not isinstance(steps, list):
        raise ValueError(f"ATIF trajectory has no steps array: {path}")

    prompts: list[dict[str, str]] = []
    commands: list[dict[str, Any]] = []
    reasoning_chars = 0
    reasoning_steps = 0
    reasoning_step_sha256: list[str | None] = []
    agent_steps = 0
    missing_reasoning_steps: list[int] = []
    tool_names: set[str] = set()

    for step in steps:
        if not isinstance(step, dict):
            continue
        source = step.get("source")
        if source in {"system", "user"} and isinstance(step.get("message"), str):
            prompts.append({"source": source, "message": step["message"]})
        if source != "agent":
            continue
        agent_steps += 1
        reasoning = step.get("reasoning_content")
        if isinstance(reasoning, str) and reasoning.strip():
            reasoning_steps += 1
            reasoning_chars += len(reasoning)
            reasoning_step_sha256.append(
                hashlib.sha256(reasoning.encode()).hexdigest()
            )
        else:
            reasoning_step_sha256.append(None)
            step_id = step.get("step_id")
            if isinstance(step_id, int):
                missing_reasoning_steps.append(step_id)

        tool_calls = step.get("tool_calls")
        if not isinstance(tool_calls, list):
            continue
        return_code, output_hash = observation_result(step)
        for call in tool_calls:
            if not isinstance(call, dict):
                continue
            function_name = call.get("function_name")
            if isinstance(function_name, str):
                tool_names.add(function_name)
            arguments = call.get("arguments")
            if not isinstance(arguments, dict):
                continue
            command = arguments.get("command")
            if not isinstance(command, str):
                continue
            commands.append(
                {
                    "command": normalize_command(command),
                    "return_code": return_code,
                    "output_sha256": output_hash,
                }
            )

    command_text = [item["command"] for item in commands]
    return_codes: dict[str, int] = {}
    for item in commands:
        key = "unknown" if item["return_code"] is None else str(item["return_code"])
        return_codes[key] = return_codes.get(key, 0) + 1

    return {
        "schema_version": trajectory.get("schema_version"),
        "step_count": len(steps),
        "agent_steps": agent_steps,
        "reasoning_steps": reasoning_steps,
        "reasoning_chars": reasoning_chars,
        "reasoning_step_sha256": reasoning_step_sha256,
        "reasoning_sha256": hashlib.sha256(
            json.dumps(reasoning_step_sha256).encode()
        ).hexdigest(),
        "missing_reasoning_steps": missing_reasoning_steps,
        "reasoning_coverage": reasoning_steps / agent_steps if agent_steps else 0.0,
        "tool_names": sorted(tool_names),
        "command_count": len(commands),
        "commands": commands,
        "command_sha256": hashlib.sha256(
            "\n".join(command_text).encode()
        ).hexdigest(),
        "return_codes": return_codes,
        "network_commands": [
            command for command in command_text if NETWORK_COMMAND.search(command)
        ],
        "prompts": prompts,
        "prompt_sha256": hashlib.sha256(
            json.dumps(prompts, sort_keys=True).encode()
        ).hexdigest(),
    }


def trial_summary(trial_dir: Path) -> dict[str, Any]:
    result = read_json(trial_dir / "result.json")
    verifier_result = result.get("verifier_result")
    rewards = (
        verifier_result.get("rewards", {})
        if isinstance(verifier_result, dict)
        else {}
    )
    trajectory_path = trial_dir / "agent/trajectory.json"
    trajectory = trajectory_summary(trajectory_path) if trajectory_path.is_file() else None
    agent_result = result.get("agent_result")
    if not isinstance(agent_result, dict):
        agent_result = {}
    return {
        "trial_dir": str(trial_dir),
        "trial_name": result.get("trial_name"),
        "task_name": result.get("task_name"),
        "task_checksum": result.get("task_checksum"),
        "agent_config": agent_config_summary(trial_dir / "config.json"),
        "exception_info": result.get("exception_info"),
        "rewards": rewards,
        "agent": {
            "n_agent_steps": agent_result.get("n_agent_steps"),
            "n_input_tokens": agent_result.get("n_input_tokens"),
            "n_output_tokens": agent_result.get("n_output_tokens"),
            "peak_context_tokens": agent_result.get("peak_context_tokens"),
        },
        "timing_seconds": {
            "environment_setup": duration_seconds(result.get("environment_setup")),
            "agent_setup": duration_seconds(result.get("agent_setup")),
            "agent_execution": duration_seconds(result.get("agent_execution")),
            "verifier": duration_seconds(result.get("verifier")),
        },
        "patch": file_summary(trial_dir / "artifacts/model.patch"),
        "trajectory": trajectory,
    }


def job_trials(job_dir: Path) -> dict[str, dict[str, Any]]:
    job_result = read_json(job_dir / "result.json")
    if job_result.get("finished_at") is None:
        raise RuntimeError(f"Pier job is not finished: {job_dir}")
    trials: dict[str, dict[str, Any]] = {}
    for result_path in sorted(job_dir.glob("*/result.json")):
        summary = trial_summary(result_path.parent)
        task_name = summary["task_name"]
        if not isinstance(task_name, str) or not task_name:
            raise ValueError(f"trial has no task_name: {result_path}")
        if task_name in trials:
            raise ValueError(f"duplicate task in {job_dir}: {task_name}")
        trials[task_name] = summary
    return trials


def aligned_command_outcomes(
    baseline: list[dict[str, Any]],
    candidate: list[dict[str, Any]],
) -> dict[str, Any]:
    baseline_commands = [item["command"] for item in baseline]
    candidate_commands = [item["command"] for item in candidate]
    matcher = difflib.SequenceMatcher(
        None,
        baseline_commands,
        candidate_commands,
        autojunk=False,
    )
    outcome_matches = 0
    return_code_matches = 0
    aligned = 0
    for block in matcher.get_matching_blocks():
        for offset in range(block.size):
            left = baseline[block.a + offset]
            right = candidate[block.b + offset]
            aligned += 1
            if left["return_code"] == right["return_code"]:
                return_code_matches += 1
            if (
                left["return_code"] == right["return_code"]
                and left["output_sha256"] == right["output_sha256"]
            ):
                outcome_matches += 1
    return {
        "sequence_similarity": matcher.ratio(),
        "aligned_commands": aligned,
        "aligned_return_code_matches": return_code_matches,
        "aligned_exact_outcome_matches": outcome_matches,
    }


def aligned_reasoning_steps(
    baseline: list[str | None],
    candidate: list[str | None],
) -> dict[str, Any]:
    matcher = difflib.SequenceMatcher(
        None,
        baseline,
        candidate,
        autojunk=False,
    )
    aligned = sum(block.size for block in matcher.get_matching_blocks())
    return {
        "same_sequence": baseline == candidate,
        "sequence_similarity": matcher.ratio(),
        "aligned_exact_steps": aligned,
        "baseline_steps": len(baseline),
        "candidate_steps": len(candidate),
    }


def compare_trials(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    baseline_trajectory = baseline["trajectory"]
    candidate_trajectory = candidate["trajectory"]
    trajectory_available = baseline_trajectory is not None and candidate_trajectory is not None
    commands = None
    reasoning = None
    same_prompt = None
    if trajectory_available:
        commands = aligned_command_outcomes(
            baseline_trajectory["commands"],
            candidate_trajectory["commands"],
        )
        same_prompt = (
            baseline_trajectory["prompt_sha256"]
            == candidate_trajectory["prompt_sha256"]
        )
        reasoning = aligned_reasoning_steps(
            baseline_trajectory["reasoning_step_sha256"],
            candidate_trajectory["reasoning_step_sha256"],
        )
    gates = {
        "same_task_checksum": baseline["task_checksum"] == candidate["task_checksum"],
        "same_agent_config": (
            baseline["agent_config"]["sha256"]
            == candidate["agent_config"]["sha256"]
        ),
        "same_prompt": same_prompt,
        "baseline_has_no_exception": baseline["exception_info"] is None,
        "candidate_has_no_exception": candidate["exception_info"] is None,
        "trajectory_available": trajectory_available,
        "baseline_reasoning_complete": (
            baseline_trajectory is not None
            and not baseline_trajectory["missing_reasoning_steps"]
        ),
        "candidate_reasoning_complete": (
            candidate_trajectory is not None
            and not candidate_trajectory["missing_reasoning_steps"]
        ),
    }
    return {
        "gates": gates,
        "gates_passed": all(value is True for value in gates.values()),
        "same_rewards": baseline["rewards"] == candidate["rewards"],
        "same_patch": baseline["patch"] == candidate["patch"],
        "reasoning": reasoning,
        "commands": commands,
        "baseline": baseline,
        "candidate": candidate,
    }


def build_report(
    jobs: dict[str, Path],
    baseline_provider: str,
) -> dict[str, Any]:
    if baseline_provider not in jobs:
        raise ValueError(f"baseline provider is missing: {baseline_provider}")
    provider_trials = {
        provider: job_trials(path) for provider, path in jobs.items()
    }
    task_sets = {provider: set(trials) for provider, trials in provider_trials.items()}
    matched_tasks = sorted(set.intersection(*task_sets.values()))
    comparisons: dict[str, Any] = {}
    for provider, trials in provider_trials.items():
        if provider == baseline_provider:
            continue
        comparisons[provider] = {
            task_name: compare_trials(
                provider_trials[baseline_provider][task_name],
                trials[task_name],
            )
            for task_name in matched_tasks
        }

    return {
        "baseline": baseline_provider,
        "jobs": {provider: str(path) for provider, path in jobs.items()},
        "provider_trial_counts": {
            provider: len(trials) for provider, trials in provider_trials.items()
        },
        "matched_tasks": matched_tasks,
        "missing_tasks": {
            provider: sorted(set.union(*task_sets.values()) - tasks)
            for provider, tasks in task_sets.items()
        },
        "comparisons": comparisons,
    }


def main() -> None:
    args = parse_args()
    report = build_report(parse_jobs(args.jobs), args.baseline)
    rendered = json.dumps(report, indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n")
        print(args.output)
    else:
        print(rendered)


if __name__ == "__main__":
    main()
