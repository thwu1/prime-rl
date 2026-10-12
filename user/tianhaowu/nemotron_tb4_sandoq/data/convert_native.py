"""Convert native mini-swe-agent trajectories into the content-part SFT rows used by ThWu/tmp exports.

Output rows match `traces.sft.jsonl` of nemotron-tb4-23-overfit-174-20260926 (task_id, trace_id,
messages, tools, source): system/user/tool turns are untrained text parts, assistant turns are a
`thinking` part (from `reasoning`) plus a `text` part, with their tool calls; the final `exit`
record is dropped. Feed the result to data/prepare.sh.

  python convert_native.py --root <export dir> --manifest <export dir>/manifest.json --dst traces.sft.jsonl
"""

import argparse
import json
import re
from pathlib import Path

BASH_TOOL = {
    "type": "function",
    "function": {
        "name": "bash",
        "description": "Execute a bash command",
        "parameters": {
            "type": "object",
            "properties": {"command": {"type": "string", "description": "The bash command to execute"}},
            "required": ["command"],
        },
    },
}


# UTF-8 bytes mis-decoded as Latin-1 (e.g. "â\x80\x94" for an em dash) in streamed assistant text.
MOJIBAKE = re.compile(r"[\xc2-\xf4][\x80-\xbf]+")


def repair_mojibake(text: str) -> str:
    def fix(match: re.Match) -> str:
        try:
            return match.group().encode("latin-1").decode("utf-8")
        except UnicodeDecodeError:
            return match.group()

    return MOJIBAKE.sub(fix, text)


def text_part(text: str) -> dict:
    return {"type": "text", "text": text}


def convert_message(message: dict) -> dict | None:
    role = message["role"]
    if role == "exit":
        return None
    if role in ("system", "user"):
        return {"role": role, "content": [text_part(message["content"])], "trainable": False}
    if role == "tool":
        return {
            "role": "tool",
            "content": [text_part(message["content"])],
            "trainable": False,
            "tool_call_id": message["tool_call_id"],
        }
    if role == "assistant":
        parts = []
        if message.get("reasoning"):
            parts.append({"type": "thinking", "thinking": message["reasoning"]})
        if message.get("content"):
            parts.append(text_part(repair_mojibake(message["content"])))
        tool_calls = [
            {"id": call["id"], "type": call["type"], "function": {"name": call["function"]["name"], "arguments": call["function"]["arguments"]}}
            for call in message.get("tool_calls") or []
        ]
        return {"role": "assistant", "content": parts, "trainable": True, "tool_calls": tool_calls}
    raise ValueError(f"unexpected role {role!r}")


def convert_trajectory(path: Path) -> list[dict]:
    native = json.loads(path.read_text())
    return [m for m in (convert_message(message) for message in native["messages"]) if m is not None]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True, help="export dir holding by-target/...")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--dst", type=Path, required=True)
    parser.add_argument(
        "--exclude-flag",
        action="append",
        default=[],
        help="drop traces carrying this manifest flag (e.g. not_submitted, user_reported_task_quality_concern)",
    )
    parser.add_argument("--exclude-trial", action="append", default=[], help="drop this trial (e.g. over seq_len)")
    args = parser.parse_args()
    traces = json.loads(args.manifest.read_text())["traces"]
    excluded = set(args.exclude_flag)
    keep = lambda t: not excluded & set(t["flags"]) and t["trial"] not in args.exclude_trial
    dropped = [t["trial"] for t in traces if not keep(t)]
    traces = [t for t in traces if keep(t)]
    if dropped:
        print(f"dropped {len(dropped)} flagged traces: {dropped}")
    args.dst.parent.mkdir(parents=True, exist_ok=True)
    with args.dst.open("w") as out:
        for trace in traces:
            native_path = args.root / trace["native_trace"]
            row = {
                "task_id": trace["task"],
                "trace_id": f"{trace['group']}/{trace['trial']}",
                "messages": convert_trajectory(native_path),
                "tools": [BASH_TOOL],
                "source": {
                    "path": trace["native_trace"],
                    "family": trace["family"],
                    "reward": trace["reward"],
                    "exit_status": trace["exit_status"],
                    "flags": trace["flags"],
                    "task_quality_note": trace["task_quality_note"],
                },
            }
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"wrote {len(traces)} rows to {args.dst}")


if __name__ == "__main__":
    main()
