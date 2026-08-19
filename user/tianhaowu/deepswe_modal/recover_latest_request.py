import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Recover a latest-request snapshot overwritten by an older response."
    )
    parser.add_argument("driver_dir", type=Path)
    parser.add_argument("task_key")
    parser.add_argument("trajectory", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--provenance", type=Path)
    return parser.parse_args()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def request_message(message: dict[str, Any]) -> dict[str, Any]:
    role = message.get("role")
    if not isinstance(role, str):
        raise TypeError("trajectory message has no string role")
    output = {"role": role}
    for key in ("content", "tool_calls", "tool_call_id", "provider_specific_fields"):
        value = message.get(key)
        if value is not None:
            output[key] = value
    reasoning = message.get("reasoning")
    if reasoning is None:
        reasoning = message.get("reasoning_content")
    if reasoning is not None:
        output["reasoning"] = reasoning
    return output


def main() -> None:
    args = parse_args()
    driver_dir = args.driver_dir.resolve()
    trajectory_path = args.trajectory.resolve()
    latest_dir = driver_dir / "latest_requests"
    output_dir = (
        args.output_dir.resolve() if args.output_dir else driver_dir / "recovered_latest_requests"
    )
    provenance_path = (
        args.provenance.resolve() if args.provenance else driver_dir / "latest_request_recovery.json"
    )
    if output_dir == latest_dir:
        raise ValueError("recovery output must not overwrite the original latest_requests directory")
    if output_dir.exists():
        raise FileExistsError(f"recovery output already exists: {output_dir}")

    source_path = latest_dir / f"{args.task_key}.json"
    source_payload = json.loads(source_path.read_text())
    captured_messages = source_payload.get("messages")
    if not isinstance(captured_messages, list) or not all(
        isinstance(message, dict) for message in captured_messages
    ):
        raise TypeError(f"captured request has invalid messages: {source_path}")

    trajectory = json.loads(trajectory_path.read_text())
    trajectory_messages = trajectory.get("messages")
    if not isinstance(trajectory_messages, list) or not all(
        isinstance(message, dict) for message in trajectory_messages
    ):
        raise TypeError(f"trajectory has invalid messages: {trajectory_path}")
    reconstructed = [request_message(message) for message in trajectory_messages]
    if reconstructed[: len(captured_messages)] != captured_messages:
        raise ValueError("captured request is not an exact prefix of the saved trajectory")

    summary_path = driver_dir / "request_capture.jsonl"
    summaries = [json.loads(line) for line in summary_path.read_text().splitlines() if line]
    successful = [
        summary
        for summary in summaries
        if summary.get("task_key") == args.task_key
        and summary.get("http_status") == 200
        and isinstance(summary.get("per_task_request"), int)
    ]
    if not successful:
        raise ValueError(f"no successful request summaries for task {args.task_key}")
    latest_summary = max(successful, key=lambda summary: summary["per_task_request"])
    message_count = latest_summary.get("message_count")
    if not isinstance(message_count, int) or message_count > len(reconstructed):
        raise ValueError("latest summary message count is incompatible with the saved trajectory")

    stale_candidates = [
        summary
        for summary in successful
        if summary.get("message_count") == len(captured_messages)
        and summary.get("attempt") == latest_summary.get("attempt")
    ]
    if not stale_candidates:
        raise ValueError("no successful summary matches the captured snapshot message count")
    stale_summary = max(stale_candidates, key=lambda summary: summary["per_task_request"])
    if stale_summary["per_task_request"] >= latest_summary["per_task_request"]:
        raise ValueError("captured snapshot already represents the latest successful request")

    recovered_payload = dict(source_payload)
    recovered_payload["messages"] = reconstructed[:message_count]
    shutil.copytree(latest_dir, output_dir)
    recovered_path = output_dir / source_path.name
    recovered_path.write_text(json.dumps(recovered_payload))

    usage = latest_summary.get("usage")
    provenance = {
        "task_key": args.task_key,
        "source_latest_dir": str(latest_dir),
        "recovered_latest_dir": str(output_dir),
        "source_request": str(source_path),
        "recovered_request": str(recovered_path),
        "trajectory": str(trajectory_path),
        "source_request_sha256": sha256(source_path),
        "recovered_request_sha256": sha256(recovered_path),
        "trajectory_sha256": sha256(trajectory_path),
        "source_message_count": len(captured_messages),
        "recovered_message_count": message_count,
        "stale_request_id": stale_summary.get("request_id"),
        "stale_per_task_request": stale_summary["per_task_request"],
        "latest_request_id": latest_summary.get("request_id"),
        "latest_per_task_request": latest_summary["per_task_request"],
        "latest_reported_prompt_tokens": usage.get("prompt_tokens") if isinstance(usage, dict) else None,
    }
    provenance_path.parent.mkdir(parents=True, exist_ok=True)
    provenance_path.write_text(json.dumps(provenance, indent=2) + "\n")
    print(json.dumps(provenance, indent=2), flush=True)


if __name__ == "__main__":
    main()
