#!/usr/bin/env python3

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit OpenHands reasoning-history preservation in eval results.")
    parser.add_argument("results", type=Path)
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def tool_call_ids(message: dict) -> list[str]:
    return [str(tool_call["id"]) for tool_call in message.get("tool_calls") or [] if tool_call.get("id")]


def main() -> None:
    args = parse_args()
    rows = 0
    model_calls = 0
    responses_with_reasoning = 0
    reported_restores = 0
    restores_by_tool_call = 0
    restores_by_generation_ids = 0
    sampled_tool_assistants = 0
    sampled_tool_assistants_with_reasoning = 0
    direct_tool_calls_without_reasoning = 0
    duplicate_history_assistants = 0
    missing_audits: list[str] = []
    sampled_calls_without_reasoning: list[dict[str, object]] = []
    visible_text_without_reasoning: list[dict[str, object]] = []
    duplicate_history: list[dict[str, object]] = []
    unparsed_tool_markup = 0
    unparsed_markup_tasks: set[str] = set()
    unparsed_markup_examples: list[dict[str, object]] = []

    with args.results.open() as results:
        for line in results:
            if not line.strip():
                continue
            row = json.loads(line)
            rows += 1
            task_name = str(row["task"]["name"])
            audit = (row.get("info") or {}).get("openhands_reasoning_history")
            if not isinstance(audit, dict):
                missing_audits.append(task_name)
            else:
                model_calls += int(audit.get("model_calls", 0))
                responses_with_reasoning += int(audit.get("responses_with_reasoning", 0))
                reported_restores += int(audit.get("restored_history_messages", 0))
                restores_by_tool_call += int(audit.get("restored_by_tool_call", 0))
                restores_by_generation_ids += int(audit.get("restored_by_generation_ids", 0))

            sampled_by_call: dict[str, dict] = {}
            for position, node in enumerate(row.get("nodes") or []):
                message = node.get("message") or {}
                if message.get("role") != "assistant":
                    continue
                call_ids = tool_call_ids(message)
                if not call_ids:
                    if node.get("sampled"):
                        text = (message.get("content") or "") + "\n" + (message.get("reasoning_content") or "")
                        if "<tool_call" in text or "<function=" in text:
                            unparsed_tool_markup += 1
                            unparsed_markup_tasks.add(task_name)
                            if len(unparsed_markup_examples) < 20:
                                unparsed_markup_examples.append({"task": task_name, "position": position})
                    continue
                if node.get("sampled"):
                    sampled_tool_assistants += 1
                    reasoning = message.get("reasoning_content")
                    if not isinstance(reasoning, str) or not reasoning.strip():
                        missing = {"task": task_name, "tool_call_ids": call_ids}
                        sampled_calls_without_reasoning.append(missing)
                        content = message.get("content")
                        if isinstance(content, str) and content.strip():
                            visible_text_without_reasoning.append(missing)
                        else:
                            direct_tool_calls_without_reasoning += 1
                        continue
                    sampled_tool_assistants_with_reasoning += 1
                    for call_id in call_ids:
                        sampled_by_call[call_id] = message
                else:
                    for call_id in call_ids:
                        sampled = sampled_by_call.get(call_id)
                        if sampled is None:
                            continue
                        duplicate_history_assistants += 1
                        duplicate_history.append(
                            {
                                "task": task_name,
                                "tool_call_id": call_id,
                                "reasoning_matches": message.get("reasoning_content")
                                == sampled.get("reasoning_content"),
                                "content_matches": (message.get("content") or "") == (sampled.get("content") or ""),
                            }
                        )

    report = {
        "results": str(args.results.resolve()),
        "rows": rows,
        "model_calls": model_calls,
        "responses_with_reasoning": responses_with_reasoning,
        "reported_restores": reported_restores,
        "restores_by_tool_call": restores_by_tool_call,
        "restores_by_generation_ids": restores_by_generation_ids,
        "sampled_tool_assistants": sampled_tool_assistants,
        "sampled_tool_assistants_with_reasoning": (sampled_tool_assistants_with_reasoning),
        "direct_tool_calls_without_reasoning": direct_tool_calls_without_reasoning,
        "duplicate_history_assistants": duplicate_history_assistants,
        "missing_audits": missing_audits,
        "sampled_calls_without_reasoning": sampled_calls_without_reasoning,
        "visible_text_without_reasoning": visible_text_without_reasoning,
        "duplicate_history": duplicate_history,
        "unparsed_tool_markup": unparsed_tool_markup,
        "unparsed_markup_tasks": sorted(unparsed_markup_tasks),
        "unparsed_markup_examples": unparsed_markup_examples,
    }
    print(json.dumps(report, indent=2, sort_keys=True))

    if args.strict:
        problems = []
        if rows == 0:
            problems.append("no result rows")
        if missing_audits:
            problems.append(f"{len(missing_audits)} rows lack bridge audit metadata")
        if model_calls <= rows:
            problems.append("no multi-turn model call was observed")
        if responses_with_reasoning == 0:
            problems.append("no response contained reasoning")
        if reported_restores == 0:
            problems.append("the bridge reported no history restoration")
        if sampled_tool_assistants_with_reasoning == 0:
            problems.append("no sampled reasoning-plus-tool-call message was observed")
        if visible_text_without_reasoning:
            problems.append(
                f"{len(visible_text_without_reasoning)} sampled tool calls have visible text but no parsed reasoning"
            )
        if duplicate_history:
            problems.append(f"{len(duplicate_history)} prior assistant messages were not deduplicated")
        if problems:
            raise SystemExit("; ".join(problems))


if __name__ == "__main__":
    main()
