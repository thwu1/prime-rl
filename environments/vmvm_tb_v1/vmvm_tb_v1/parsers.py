# Terminus-2 response parsers, extracted verbatim from amaia-collab
# apps/sea/envs/envs/terminal_bench/terminal_bench_env.py lines 91-374 (snapshot 2026-06-15).
# Pure functions (json/re) + local data models. No amaia deps.
import json
import re
from .models import Command, CommandBatchResponse

_T2_VALID_ESC = set('"\\/bfnrtu')

def _t2_strip_think(s: str) -> str:
    return re.sub(r"<think>.*?</think>", "", s, flags=re.DOTALL)

def _t2_first_json_object(region: str):
    """First balanced {...} from `region`, respecting string state; auto-closes if truncated."""
    i = region.find("{")
    if i < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    out = []
    for ch in region[i:]:
        out.append(ch)
        if esc:
            esc = False
            continue
        if ch == "\\":
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return "".join(out)
    js = "".join(out)
    if in_str:
        js += '"'
    if depth > 0:
        js += "}" * depth
    return js

def _t2_repair(js: str) -> str:
    """Repair model-emitted JSON: fix invalid \\X escapes and raw control chars in strings."""
    def _fix(m):
        c = m.group(1)
        return m.group(0) if c in _T2_VALID_ESC else "\\\\" + c
    js = re.sub(r"\\(.)", _fix, js, flags=re.DOTALL)
    out = []
    in_str = False
    esc = False
    for ch in js:
        if esc:
            out.append(ch)
            esc = False
            continue
        if ch == "\\":
            out.append(ch)
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            out.append(ch)
            continue
        if in_str and ch == "\n":
            out.append("\\n")
            continue
        if in_str and ch == "\r":
            out.append("\\r")
            continue
        if in_str and ch == "\t":
            out.append("\\t")
            continue
        out.append(ch)
    return "".join(out)

def _t2_read_string(s: str, i: int):
    """Lenient JSON string reader starting at s[i]=='"'; returns (value, end_index)."""
    i += 1
    buf = []
    _map = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "/": "/"}
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s):
            buf.append(_map.get(s[i + 1], s[i + 1]))
            i += 2
            continue
        if ch == '"':
            return "".join(buf), i + 1
        buf.append(ch)
        i += 1
    return "".join(buf), i

def _t2_manual_commands(region: str):
    """Last resort: extract every keystrokes value (+nearby duration) ignoring overall JSON validity."""
    cmds = []
    for m in re.finditer(r'"keystrokes"\s*:\s*"', region):
        val, end = _t2_read_string(region, m.end() - 1)
        dur = 1.0
        dm = re.search(r'"duration"\s*:\s*([0-9.]+)', region[end:end + 80])
        if dm:
            try:
                dur = float(dm.group(1))
            except Exception:
                pass
        cmds.append((val, dur))
    return cmds

def _parse_terminus2_response(action_str: str, command_timeout: float) -> tuple[CommandBatchResponse | None, str]:
    """Parse terminus-2 response, robust to model-emitted JSON breakage.

    Handles think stripping, missing </tool> close tags, invalid backslash
    escapes, raw control chars in strings, and wrong-fragment extraction. Falls
    back to direct keystrokes extraction so valid commands are never silently
    dropped.
    """
    s = _t2_strip_think(action_str)

    if "<tool: submit>" in s:
        return CommandBatchResponse(
            state_analysis="Task submission",
            explanation="Agent submitted the task as complete",
            bash_commands=[],
            is_task_complete=True,
        ), ""

    m = re.search(r"<tool:\s*bash>", s)
    if m:
        region = s[m.end():]
        cm = re.search(r"</tool>", region)
        if cm:
            region = region[:cm.start()]
    else:
        region = s.strip()

    js = _t2_first_json_object(region)
    data = None
    if js is not None:
        try:
            data = json.loads(js)
        except json.JSONDecodeError:
            try:
                data = json.loads(_t2_repair(js))
            except json.JSONDecodeError:
                data = None

    analysis = ""
    plan = ""
    is_complete = False
    raw_cmds = []
    if isinstance(data, dict):
        analysis = data.get("analysis", "")
        plan = data.get("plan", "")
        ic = data.get("task_complete", False)
        is_complete = ic.lower() in ("true", "1", "yes") if isinstance(ic, str) else bool(ic)
        cd = data.get("commands", [])
        if isinstance(cd, list):
            for c in cd:
                if isinstance(c, dict) and isinstance(c.get("keystrokes"), str):
                    d = c.get("duration", 1.0)
                    raw_cmds.append((c["keystrokes"], d if isinstance(d, (int, float)) else 1.0))

    if not raw_cmds and not is_complete:
        raw_cmds = _t2_manual_commands(js if js is not None else region) or _t2_manual_commands(region)

    if not raw_cmds and not is_complete and data is None:
        return None, "Invalid JSON: could not parse tool call"

    commands = [
        Command(keystrokes=k, is_blocking=True, timeout_sec=command_timeout)
        for k, _ in raw_cmds
    ]
    return CommandBatchResponse(
        state_analysis=str(analysis),
        explanation=str(plan),
        bash_commands=commands,
        is_task_complete=is_complete,
    ), ""

# ─── Native Qwen Tool-Call Support ──────────────────────────────────────

BASH_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "bash",
        "description": "Execute a bash command in the container. Returns stdout/stderr.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The bash command to execute",
                },
            },
            "required": ["command"],
        },
    },
}

SUBMIT_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "submit",
        "description": "Submit the task as complete. Call this when you have finished the task.",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
}

NATIVE_TOOL_SCHEMAS = [BASH_TOOL_SCHEMA, SUBMIT_TOOL_SCHEMA]

def _parse_native_tool_call(action_str: str, command_timeout: float) -> tuple[CommandBatchResponse | None, str]:
    """Parse Qwen-native <tool_call> format.

    Expected format from model:
      <tool_call>
      {"name": "bash", "arguments": {"command": "ls -la"}}
      </tool_call>
    """
    s = re.sub(r"<think>.*?</think>", "", action_str, flags=re.DOTALL)

    tool_calls = re.findall(
        r"<tool_call>\s*(.*?)\s*</tool_call>", s, re.DOTALL
    )

    if not tool_calls:
        idx = s.find("<tool_call>")
        if idx >= 0:
            region = s[idx + len("<tool_call>"):]
            tool_calls = [region.strip()]

    if not tool_calls:
        return None, "No <tool_call> found in response"

    commands = []
    is_complete = False

    for tc_str in tool_calls:
        tc_str = tc_str.strip()
        try:
            data = json.loads(tc_str)
        except json.JSONDecodeError:
            brace_diff = tc_str.count("{") - tc_str.count("}")
            if brace_diff > 0:
                tc_str += "}" * brace_diff
            try:
                data = json.loads(tc_str)
            except json.JSONDecodeError:
                continue

        if not isinstance(data, dict):
            continue

        name = data.get("name", "")
        args = data.get("arguments", {})
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {"command": args}

        if name == "submit":
            is_complete = True
        elif name == "bash":
            cmd_str = args.get("command", "")
            if cmd_str:
                commands.append(Command(
                    keystrokes=cmd_str + "\n",
                    is_blocking=True,
                    timeout_sec=command_timeout,
                ))

    if not commands and not is_complete:
        return None, "Could not extract bash command or submit from tool call"

    return CommandBatchResponse(
        state_analysis="",
        explanation="",
        bash_commands=commands,
        is_task_complete=is_complete,
    ), ""

# ─── Env ─────────────────────────────────────────────────────────────────────

