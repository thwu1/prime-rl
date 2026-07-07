#!/usr/bin/env python3
"""Trace vmvm-tb native-tool parse errors through saved train rollouts.

The vmvm-tb-v2 env increments parse_errors when the assistant turn cannot be
parsed as a usable native tool call. This script scans prime-rl
run_default/rollouts/step_*/train_rollouts.jsonl dumps and reports:

  * per-step stop-condition timeline
  * per-step classification of each parser-feedback event
  * malformed tool-name counts
  * sample offending assistant turns

Usage:
  trace_vmvm_parse_errors.py <run_dir | rollouts_dir | train_rollouts.jsonl> \
      --out-prefix /tmp/qwen35_parse_trace --classify-steps 150:176
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import re
from collections import Counter, defaultdict
from typing import Any, Iterable


PARSE_FEEDBACK = "Your last message could not be parsed as a valid tool call"
STOP_RE = re.compile(r'"stop_condition"\s*:\s*"([^"]*)"')
STEP_RE = re.compile(r"step_(\d+)")


FORM_KEYS = [
    "structured_bad_tool_name",
    "structured_bad_json_args",
    "structured_empty_command",
    "structured_other_unusable",
    "structured_would_parse_unexpected",
    "text_tool_call_bad_tool_name",
    "text_tool_call_bad_json",
    "text_tool_call_empty_command",
    "text_tool_call_other_unusable",
    "text_tool_call_would_parse_unexpected",
    "empty_content_reasoning_only",
    "empty_content_no_tool",
    "plain_text_code_or_tool_words",
    "plain_text_gibberishish",
    "plain_text_other",
    "missing_previous_assistant",
]


def parse_step(path: str) -> int:
    m = STEP_RE.search(path)
    return int(m.group(1)) if m else -1


def step_sort_key(path: str) -> tuple[int, str]:
    return parse_step(path), path


def resolve_files(path: str) -> list[tuple[int, str]]:
    path = os.path.abspath(os.path.expanduser(path))
    if os.path.isfile(path):
        return [(parse_step(path), path)]

    candidates = []
    if os.path.isdir(os.path.join(path, "run_default", "rollouts")):
        candidates.append(os.path.join(path, "run_default", "rollouts"))
    candidates.append(path)

    files: list[str] = []
    for base in candidates:
        if os.path.basename(base).startswith("step_"):
            f = os.path.join(base, "train_rollouts.jsonl")
            if os.path.exists(f):
                files.append(f)
        files.extend(glob.glob(os.path.join(base, "step_*", "train_rollouts.jsonl")))

    files = sorted(set(files), key=step_sort_key)
    return [(parse_step(f), f) for f in files]


def parse_step_filter(spec: str | None) -> set[int] | None:
    if not spec or spec == "all":
        return None
    out: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            a, b = part.split(":", 1)
            lo = int(a) if a else 0
            hi = int(b) if b else lo
            out.update(range(lo, hi + 1))
        else:
            out.add(int(part))
    return out


def message_of(node: dict[str, Any]) -> dict[str, Any]:
    msg = node.get("message") if isinstance(node, dict) else {}
    return msg if isinstance(msg, dict) else {}


def tool_calls_of(msg: dict[str, Any]) -> list[Any]:
    tcs = msg.get("tool_calls")
    return tcs if isinstance(tcs, list) else []


def decode_tool_call(tc: Any) -> dict[str, Any]:
    if not isinstance(tc, dict):
        name = getattr(tc, "name", None)
        raw = getattr(tc, "arguments", None)
        fn = getattr(tc, "function", None)
        if name is None and fn is not None:
            name = getattr(fn, "name", None)
            raw = getattr(fn, "arguments", None)
    else:
        fn = tc.get("function") or {}
        name = tc.get("name") or fn.get("name")
        raw = tc.get("arguments")
        if raw is None:
            raw = fn.get("arguments")

    json_ok = True
    if isinstance(raw, str):
        try:
            args = json.loads(raw) if raw.strip() else {}
        except Exception:
            json_ok = False
            args = {}
    elif isinstance(raw, dict):
        args = raw
    else:
        args = {}

    command = args.get("command", "") if isinstance(args, dict) else ""
    return {
        "name": name or "",
        "raw_args": raw,
        "json_ok": json_ok,
        "args": args,
        "command": command if isinstance(command, str) else "",
    }


def command_from_args(args: Any) -> tuple[bool, str]:
    if isinstance(args, str):
        try:
            args = json.loads(args) if args.strip() else {}
        except json.JSONDecodeError:
            args = {"command": args}
    if not isinstance(args, dict):
        return False, ""
    cmd = args.get("command", "")
    return isinstance(cmd, str) and bool(cmd), cmd if isinstance(cmd, str) else ""


def classify_decoded_calls(calls: list[dict[str, Any]], prefix: str) -> tuple[str, list[str], str]:
    names = [c["name"] or "NO_NAME" for c in calls]
    saw_json_bad = any(not c["json_ok"] for c in calls)
    saw_empty_bash = any(c["name"] == "bash" and not c["command"] for c in calls)
    would_parse = any(c["name"] == "submit" for c in calls) or any(
        c["name"] == "bash" and bool(c["command"]) for c in calls
    )
    bad_names = [n for n in names if n not in ("bash", "submit")]

    if bad_names:
        return f"{prefix}_bad_tool_name", names, ",".join(bad_names[:5])
    if saw_json_bad:
        return f"{prefix}_bad_json_args", names, ""
    if saw_empty_bash:
        return f"{prefix}_empty_command", names, ""
    if would_parse:
        return f"{prefix}_would_parse_unexpected", names, ""
    return f"{prefix}_other_unusable", names, ""


def decode_native_content_tool_calls(content: str) -> list[dict[str, Any]]:
    s = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)
    raw_calls = re.findall(r"<tool_call>\s*(.*?)\s*</tool_call>", s, re.DOTALL)
    if not raw_calls:
        idx = s.find("<tool_call>")
        if idx >= 0:
            raw_calls = [s[idx + len("<tool_call>") :].strip()]

    calls = []
    for raw in raw_calls:
        raw = raw.strip()
        json_ok = True
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            fixed = raw
            brace_diff = raw.count("{") - raw.count("}")
            if brace_diff > 0:
                fixed += "}" * brace_diff
            try:
                data = json.loads(fixed)
            except json.JSONDecodeError:
                json_ok = False
                data = {}
        if not isinstance(data, dict):
            data = {}
        name = data.get("name", "")
        args = data.get("arguments", {})
        has_cmd, cmd = command_from_args(args)
        calls.append(
            {
                "name": name or "",
                "raw_args": args,
                "json_ok": json_ok,
                "args": args,
                "command": cmd if has_cmd else "",
            }
        )
    return calls


def looks_code_or_toolish(content: str) -> bool:
    return bool(
        re.search(
            r"cat >|python|bash|submit|EOF|json|```|/app|sed -|echo |tool_call|command",
            content[:1600],
            re.IGNORECASE,
        )
    )


def looks_gibberishish(content: str) -> bool:
    head = content[:900]
    if "\ufffd" in head:
        return True
    patterns = [
        r"\b[a-zA-Z]{1,4}\d+\b",
        r"\b\d+[a-zA-Z]{1,4}\b",
        r"[\]\}\)]{3,}",
        r"[;:]{2,}",
        r"[A-Za-z]+[}\];][A-Za-z]+",
        r"\b[a-z]{2,}[A-Z][a-z]{2,}[A-Za-z]*\b",
    ]
    return any(re.search(p, head) for p in patterns)


def classify_prev_node(prev: dict[str, Any] | None) -> dict[str, Any]:
    if not prev:
        return {"form": "missing_previous_assistant", "tool_names": [], "bad_detail": ""}

    msg = message_of(prev)
    tcs = tool_calls_of(msg)
    if tcs:
        decoded = [decode_tool_call(tc) for tc in tcs]
        form, names, detail = classify_decoded_calls(decoded, "structured")
        return {
            "form": form,
            "tool_names": names,
            "bad_detail": detail,
            "raw_args": [str(d["raw_args"])[:500] for d in decoded[:3]],
        }

    content = msg.get("content") or ""
    reasoning = msg.get("reasoning_content") or ""
    if "<tool_call>" in content or "</tool_call>" in content:
        decoded = decode_native_content_tool_calls(content)
        if decoded:
            form, names, detail = classify_decoded_calls(decoded, "text_tool_call")
            return {"form": form, "tool_names": names, "bad_detail": detail}
        return {"form": "text_tool_call_bad_json", "tool_names": [], "bad_detail": ""}

    if not content.strip() and reasoning.strip():
        form = "empty_content_reasoning_only"
    elif not content.strip():
        form = "empty_content_no_tool"
    elif looks_code_or_toolish(content):
        form = "plain_text_code_or_tool_words"
    elif looks_gibberishish(content):
        form = "plain_text_gibberishish"
    else:
        form = "plain_text_other"

    return {"form": form, "tool_names": [], "bad_detail": ""}


def snippet(text: Any, limit: int) -> str:
    text = "" if text is None else str(text)
    text = " ".join(text.replace("\r", "\n").split())
    if len(text) > limit:
        return text[: limit - 3] + "..."
    return text


def iter_parse_events(record: dict[str, Any]) -> Iterable[tuple[int, dict[str, Any], dict[str, Any] | None]]:
    nodes = record.get("nodes") or []
    if not isinstance(nodes, list):
        return
    for idx, node in enumerate(nodes):
        msg = message_of(node)
        if msg.get("role") != "user":
            continue
        if PARSE_FEEDBACK not in (msg.get("content") or ""):
            continue
        prev = nodes[idx - 1] if idx > 0 and isinstance(nodes[idx - 1], dict) else None
        yield idx, node, prev


def timeline_for_file(step: int, path: str) -> dict[str, Any]:
    stops: Counter[str] = Counter()
    total = 0
    with open(path, errors="replace") as fh:
        for line in fh:
            if not line.strip():
                continue
            total += 1
            m = STOP_RE.search(line)
            stops[m.group(1) if m else "MISSING"] += 1
    row = {
        "step": step,
        "path": path,
        "total": total,
        "parse": stops.get("_stop_parse_errors", 0),
        "task_complete": stops.get("_stop_task_complete", 0),
        "context_length": stops.get("context_length", 0),
        "max_turns": stops.get("max_turns_reached", 0),
        "max_output": stops.get("max_output_tokens", 0),
        "other": total
        - stops.get("_stop_parse_errors", 0)
        - stops.get("_stop_task_complete", 0)
        - stops.get("context_length", 0)
        - stops.get("max_turns_reached", 0)
        - stops.get("max_output_tokens", 0),
    }
    row["parse_pct"] = (100.0 * row["parse"] / total) if total else 0.0
    row["task_complete_pct"] = (100.0 * row["task_complete"] / total) if total else 0.0
    return row


def classify_file(
    step: int,
    path: str,
    sample_limit: int,
    samples_fh,
) -> tuple[dict[str, Any], Counter[str]]:
    forms: Counter[str] = Counter()
    tool_names: Counter[str] = Counter()
    per_rollout_event_counts: Counter[int] = Counter()
    parse_rollouts = 0
    sample_counts: Counter[str] = Counter()

    with open(path, errors="replace") as fh:
        for line_no, line in enumerate(fh, 1):
            if "_stop_parse_errors" not in line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("stop_condition") != "_stop_parse_errors":
                continue
            parse_rollouts += 1
            events = list(iter_parse_events(record))
            per_rollout_event_counts[len(events)] += 1

            task = record.get("task") if isinstance(record.get("task"), dict) else {}
            rollout_id = record.get("id")
            task_idx = task.get("idx")
            for event_no, (node_idx, _node, prev) in enumerate(events, 1):
                cls = classify_prev_node(prev)
                form = cls["form"]
                forms[form] += 1
                for name in cls.get("tool_names") or []:
                    tool_names[name] += 1

                if sample_counts[form] >= sample_limit:
                    continue
                sample_counts[form] += 1
                msg = message_of(prev or {})
                out = {
                    "step": step,
                    "file": path,
                    "line": line_no,
                    "rollout_id": rollout_id,
                    "task_idx": task_idx,
                    "node_idx": node_idx,
                    "event_no": event_no,
                    "form": form,
                    "tool_names": cls.get("tool_names") or [],
                    "bad_detail": cls.get("bad_detail") or "",
                    "finish_reason": (prev or {}).get("finish_reason"),
                    "content": snippet(msg.get("content"), 1200),
                    "reasoning": snippet(msg.get("reasoning_content"), 1200),
                    "raw_args": cls.get("raw_args") or [],
                }
                samples_fh.write(json.dumps(out, ensure_ascii=True) + "\n")

    row = {
        "step": step,
        "path": path,
        "parse_rollouts": parse_rollouts,
        "parse_events": sum(forms.values()),
        "rollouts_with_0_events": per_rollout_event_counts.get(0, 0),
        "rollouts_with_6_events": per_rollout_event_counts.get(6, 0),
        "event_count_hist": " ".join(
            f"{k}:{v}" for k, v in sorted(per_rollout_event_counts.items())
        ),
    }
    for key in FORM_KEYS:
        row[key] = forms.get(key, 0)
    return row, tool_names


def write_csv(path: str, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", help="run dir, rollouts dir, step dir, or train_rollouts.jsonl")
    ap.add_argument("--classify-steps", default="all", help='step list/range, e.g. "150:176" or "125,150,175"; default all')
    ap.add_argument("--out-prefix", default="/tmp/vmvm_parse_trace")
    ap.add_argument("--sample-limit", type=int, default=3, help="samples per category per step")
    args = ap.parse_args()

    files = resolve_files(args.path)
    if not files:
        raise SystemExit(f"no train_rollouts.jsonl files found under {args.path}")

    wanted = parse_step_filter(args.classify_steps)
    timeline_rows = [timeline_for_file(step, f) for step, f in files]

    classify_files = [(s, f) for s, f in files if wanted is None or s in wanted]
    forms_rows: list[dict[str, Any]] = []
    tool_name_rows: list[dict[str, Any]] = []
    total_tool_names: Counter[str] = Counter()

    samples_path = args.out_prefix + "_samples.jsonl"
    with open(samples_path, "w") as samples_fh:
        for step, f in classify_files:
            form_row, names = classify_file(step, f, args.sample_limit, samples_fh)
            forms_rows.append(form_row)
            total_tool_names.update(names)
            for name, count in names.most_common():
                tool_name_rows.append({"step": step, "tool_name": name, "count": count})

    timeline_path = args.out_prefix + "_timeline.csv"
    forms_path = args.out_prefix + "_forms.csv"
    names_path = args.out_prefix + "_tool_names.csv"

    write_csv(
        timeline_path,
        timeline_rows,
        [
            "step",
            "total",
            "parse",
            "parse_pct",
            "task_complete",
            "task_complete_pct",
            "context_length",
            "max_turns",
            "max_output",
            "other",
            "path",
        ],
    )
    write_csv(
        forms_path,
        forms_rows,
        [
            "step",
            "parse_rollouts",
            "parse_events",
            "rollouts_with_0_events",
            "rollouts_with_6_events",
            "event_count_hist",
            *FORM_KEYS,
            "path",
        ],
    )
    write_csv(names_path, tool_name_rows, ["step", "tool_name", "count"])

    print(f"files scanned          : {len(files)}")
    print(f"files classified       : {len(classify_files)}")
    print(f"timeline csv           : {timeline_path}")
    print(f"forms csv              : {forms_path}")
    print(f"tool-name csv          : {names_path}")
    print(f"samples jsonl          : {samples_path}")

    nonzero = [r for r in timeline_rows if r["parse"]]
    if nonzero:
        first = nonzero[0]
        peak = max(nonzero, key=lambda r: r["parse_pct"])
        latest = nonzero[-1]
        print(
            "parse-error onset/peak : "
            f"first step {first['step']} {first['parse']}/{first['total']} ({first['parse_pct']:.1f}%), "
            f"peak step {peak['step']} {peak['parse']}/{peak['total']} ({peak['parse_pct']:.1f}%), "
            f"latest nonzero step {latest['step']} {latest['parse']}/{latest['total']} ({latest['parse_pct']:.1f}%)"
        )

    if forms_rows:
        aggregate = Counter()
        parse_rollouts = 0
        parse_events = 0
        six_event_rollouts = 0
        for row in forms_rows:
            parse_rollouts += int(row["parse_rollouts"])
            parse_events += int(row["parse_events"])
            six_event_rollouts += int(row["rollouts_with_6_events"])
            for key in FORM_KEYS:
                aggregate[key] += int(row[key])
        print(
            "classified aggregate   : "
            f"{parse_rollouts} parse rollouts, {parse_events} parse-feedback events, "
            f"{six_event_rollouts} rollouts with exactly 6 events"
        )
        print("top forms:")
        for key, count in aggregate.most_common(8):
            if count:
                print(f"  {key}: {count}")
        if total_tool_names:
            print("top malformed/seen tool names:")
            for name, count in total_tool_names.most_common(12):
                print(f"  {name!r}: {count}")


if __name__ == "__main__":
    main()
