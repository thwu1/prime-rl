#!/usr/bin/env python3

import argparse
import collections
import json
import tomllib
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit native mini-swe-agent tool calls in Verifiers results.")
    parser.add_argument("results", type=Path)
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def configured_max_turns(results: Path) -> int | None:
    config = results.parent / "config.toml"
    provenance = results.with_suffix(results.suffix + ".provenance.json")
    if not config.is_file() and provenance.is_file():
        base = json.loads(provenance.read_text()).get("base", {}).get("path")
        if isinstance(base, str):
            config = Path(base).parent / "config.toml"
    if not config.is_file():
        return None
    value = tomllib.loads(config.read_text()).get("max_turns")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def main() -> None:
    args = parse_args()
    max_turns = configured_max_turns(args.results)
    rows = 0
    sampled_assistants = 0
    sampled_tool_assistants = 0
    tool_names: collections.Counter[str] = collections.Counter()
    rows_without_native_tools: list[dict[str, object]] = []
    invalid_tool_calls: list[dict[str, object]] = []
    rejected_invalid_tool_calls: list[dict[str, object]] = []
    rejected_valid_tool_calls: list[dict[str, object]] = []
    unhandled_invalid_tool_calls: list[dict[str, object]] = []
    orphan_tool_results: list[dict[str, object]] = []
    missing_tool_results: list[dict[str, object]] = []
    terminal_submission_calls_without_results: list[dict[str, object]] = []
    turn_limit_calls_without_results: list[dict[str, object]] = []
    budget_stop_calls_without_results: list[dict[str, object]] = []
    unparsed_tool_markup = 0
    unparsed_markup_tasks: set[int] = set()
    unparsed_markup_examples: list[dict[str, object]] = []

    with args.results.open() as results:
        for line in results:
            if not line.strip():
                continue
            row = json.loads(line)
            rows += 1
            task = row["task"]
            task_ref = {"idx": int(task["idx"]), "name": str(task["name"])}
            seen_call_ids: set[str] = set()
            valid_call_ids: set[str] = set()
            valid_calls: dict[str, tuple[int, str]] = {}
            matched_call_ids: set[str] = set()
            row_sampled_assistants = 0

            for position, node in enumerate(row.get("nodes") or []):
                message = node.get("message") or {}
                if message.get("role") == "assistant" and node.get("sampled"):
                    sampled_assistants += 1
                    row_sampled_assistants += 1
                    tool_calls = message.get("tool_calls") or []
                    next_message = (
                        (row["nodes"][position + 1].get("message") or {})
                        if position + 1 < len(row.get("nodes") or [])
                        else {}
                    )
                    response_rejected = next_message.get("role") == "user" and "Tool call error" in str(
                        next_message.get("content") or ""
                    )
                    if tool_calls:
                        sampled_tool_assistants += 1
                    else:
                        text = (message.get("content") or "") + "\n" + (message.get("reasoning_content") or "")
                        if "<tool_call" in text or "<function=" in text:
                            unparsed_tool_markup += 1
                            unparsed_markup_tasks.add(task_ref["idx"])
                            if len(unparsed_markup_examples) < 20:
                                unparsed_markup_examples.append({**task_ref, "position": position})
                    for tool_call in tool_calls:
                        name = str(tool_call.get("name") or "")
                        tool_names[name] += 1
                        call_id = str(tool_call.get("id") or "")
                        arguments = tool_call.get("arguments")
                        issue = None
                        if not call_id:
                            issue = "missing tool-call ID"
                        elif call_id in seen_call_ids:
                            issue = "duplicate tool-call ID"
                        elif name != "bash":
                            issue = f"unexpected tool name {name!r}"
                        else:
                            try:
                                parsed_arguments = json.loads(arguments) if isinstance(arguments, str) else arguments
                            except json.JSONDecodeError:
                                issue = "tool arguments are not valid JSON"
                            else:
                                if not isinstance(parsed_arguments, dict) or not isinstance(
                                    parsed_arguments.get("command"), str
                                ):
                                    issue = "bash tool arguments lack a string command"
                        if issue:
                            invalid = {
                                **task_ref,
                                "position": position,
                                "tool_call_id": call_id,
                                "issue": issue,
                            }
                            invalid_tool_calls.append(invalid)
                            (rejected_invalid_tool_calls if response_rejected else unhandled_invalid_tool_calls).append(
                                invalid
                            )
                        else:
                            if response_rejected:
                                rejected_valid_tool_calls.append(
                                    {
                                        **task_ref,
                                        "position": position,
                                        "tool_call_id": call_id,
                                    }
                                )
                            else:
                                valid_call_ids.add(call_id)
                                valid_calls[call_id] = (position, parsed_arguments["command"])
                        if call_id:
                            seen_call_ids.add(call_id)
                elif message.get("role") == "tool":
                    call_id = str(message.get("tool_call_id") or "")
                    if not call_id or call_id not in valid_call_ids:
                        orphan_tool_results.append({**task_ref, "tool_call_id": call_id})
                    else:
                        matched_call_ids.add(call_id)

            for call_id in sorted(valid_call_ids - matched_call_ids):
                missing = {**task_ref, "tool_call_id": call_id}
                position, command = valid_calls[call_id]
                if position == len(row.get("nodes") or []) - 1 and "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT" in command:
                    terminal_submission_calls_without_results.append(missing)
                elif position == len(row.get("nodes") or []) - 1 and row.get("stop_condition") in {
                    "context_length",
                    "harness_timeout",
                }:
                    budget_stop_calls_without_results.append(missing)
                elif (
                    position == len(row.get("nodes") or []) - 1
                    and max_turns is not None
                    and row_sampled_assistants >= max_turns
                ):
                    turn_limit_calls_without_results.append(missing)
                else:
                    missing_tool_results.append(missing)
            if not matched_call_ids:
                rows_without_native_tools.append(task_ref)

    report = {
        "results": str(args.results.resolve()),
        "configured_max_turns": max_turns,
        "rows": rows,
        "sampled_assistants": sampled_assistants,
        "sampled_tool_assistants": sampled_tool_assistants,
        "tool_calls": sum(tool_names.values()),
        "tool_names": dict(sorted(tool_names.items())),
        "rows_without_native_tools": rows_without_native_tools,
        "invalid_tool_calls": invalid_tool_calls,
        "rejected_invalid_tool_calls": rejected_invalid_tool_calls,
        "rejected_valid_tool_calls": rejected_valid_tool_calls,
        "unhandled_invalid_tool_calls": unhandled_invalid_tool_calls,
        "orphan_tool_results": orphan_tool_results,
        "missing_tool_results": missing_tool_results,
        "terminal_submission_calls_without_results": terminal_submission_calls_without_results,
        "turn_limit_calls_without_results": turn_limit_calls_without_results,
        "budget_stop_calls_without_results": budget_stop_calls_without_results,
        "unparsed_tool_markup": unparsed_tool_markup,
        "unparsed_markup_tasks": sorted(unparsed_markup_tasks),
        "unparsed_markup_examples": unparsed_markup_examples,
    }
    print(json.dumps(report, indent=2, sort_keys=True))

    if args.strict:
        problems = []
        if rows == 0:
            problems.append("no result rows")
        if rows_without_native_tools:
            problems.append(f"{len(rows_without_native_tools)} rows contain no native tool call")
        if unhandled_invalid_tool_calls:
            problems.append(f"found {len(unhandled_invalid_tool_calls)} unhandled invalid tool calls")
        if orphan_tool_results:
            problems.append(f"found {len(orphan_tool_results)} orphan tool results")
        if missing_tool_results:
            problems.append(f"found {len(missing_tool_results)} native tool calls without results")
        if problems:
            raise SystemExit("; ".join(problems))


if __name__ == "__main__":
    main()
