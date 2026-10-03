"""Summarize agent behaviour in TB4 eval runs (one or more results.jsonl files per model).

Per model: how rollouts end, format errors (turns mini-swe-agent rejected for having no parsable
tool call), tool calls left inside the reasoning, responses cut at the per-response token limit,
tool calls per turn, repeated commands, trajectory length and final context size.
"""

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path

FORMAT_ERROR_MARKERS = ("Tool call error", "reached the output token limit")


def responses(row: dict) -> list[dict]:
    out = []
    for node in row["nodes"]:
        model_io = node.get("model_io")
        if model_io:
            out.append(model_io["response"]["body"])
    return out


def appended_user_messages(row: dict) -> list[str]:
    texts = []
    for node in row["nodes"]:
        model_io = node.get("model_io")
        if not model_io:
            continue
        request = model_io["request"]
        messages = request.get("body", {}).get("messages") or request.get("append_fields", {}).get("messages", [])
        for message in messages:
            if message.get("role") == "user":
                content = message.get("content")
                texts.append(content if isinstance(content, str) else json.dumps(content))
    return texts


def summarize(label: str, paths: list[Path]) -> None:
    rows = [json.loads(line) for path in paths for line in path.read_text().split("\n") if line.strip()]
    stops, finish = Counter(), Counter()
    turns, contexts, completion_lens = [], [], []
    format_errors = think_calls = empty_cmd = repeated = total_calls = calls_turns = 0
    per_rollout_format_errors = []
    for row in rows:
        stop = "HarnessError" if row.get("errors") else row.get("stop_condition")
        solved = row.get("rewards", {}).get("solved") == 1.0
        stops[(stop, solved)] += 1
        bodies = responses(row)
        turns.append(len(bodies))
        contexts.append(max((b.get("usage") or {}).get("prompt_tokens") or 0 for b in bodies) if bodies else 0)
        errors_here = sum(any(m in text for m in FORMAT_ERROR_MARKERS) for text in appended_user_messages(row))
        format_errors += errors_here
        per_rollout_format_errors.append(errors_here)
        seen = set()
        for body in bodies:
            choice = body["choices"][0]
            message = choice["message"]
            finish[choice.get("finish_reason")] += 1
            completion_lens.append((body.get("usage") or {}).get("completion_tokens") or 0)
            reasoning = message.get("reasoning") or message.get("reasoning_content") or ""
            calls = message.get("tool_calls") or []
            if not calls and "<tool_call>" in reasoning:
                think_calls += 1
            if calls:
                calls_turns += 1
            for call in calls:
                total_calls += 1
                try:
                    command = json.loads(call["function"]["arguments"]).get("command", "")
                except (json.JSONDecodeError, AttributeError):
                    command = ""
                if not command.strip():
                    empty_cmd += 1
                elif command in seen:
                    repeated += 1
                seen.add(command)
    n_resp = sum(finish.values())
    print(f"=== {label}: {len(rows)} rollouts, {n_resp} model responses")
    print("  endings (stop, solved):", ", ".join(f"{s}{'+solved' if v else ''}={c}" for (s, v), c in stops.most_common()))
    print(f"  turns: median {statistics.median(turns):.0f}, max {max(turns)} | final context: median "
          f"{statistics.median(contexts) / 1000:.0f}k, max {max(contexts) / 1000:.0f}k")
    print(f"  finish_reason: " + ", ".join(f"{k}={v} ({v / n_resp:.1%})" for k, v in finish.most_common()))
    print(f"  format errors: {format_errors} ({format_errors / n_resp:.1%} of responses); rollouts with >=1: "
          f"{sum(1 for x in per_rollout_format_errors if x)}/{len(rows)}; tool call inside <think> (no parsed call): {think_calls}")
    print(f"  completion tokens/response: median {statistics.median(completion_lens):.0f}, p95 "
          f"{sorted(completion_lens)[int(0.95 * len(completion_lens))]}, max {max(completion_lens)}")
    print(f"  tool calls: {total_calls} over {calls_turns} turns ({total_calls / max(calls_turns, 1):.2f}/turn); "
          f"empty commands {empty_cmd}; exact repeated commands {repeated} ({repeated / max(total_calls, 1):.1%})")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="append", nargs=2, metavar=("LABEL", "RESULTS_DIR"), required=True)
    args = parser.parse_args()
    for label, directory in args.run:
        summarize(label, [Path(directory) / "results.jsonl"])


if __name__ == "__main__":
    main()
