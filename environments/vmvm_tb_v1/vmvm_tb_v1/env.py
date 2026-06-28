"""Terminal-Bench eval environment for PRIME-RL.

A verifiers MultiTurnEnv that runs the Terminus-2 protocol with the policy model
OUTSIDE the sandbox (no interception/egress): each turn the model emits a
Terminus-2 JSON tool-call, we parse it and run the keystrokes via run_bash inside
a vacli-leased VMVM VM, and feed the terminal output back. Reward = the task's
own tests (run_terminal_bench_tests) -> pass@1.

Ports the pure pieces of amaia-collab's SEA terminal_bench env; the agent loop is
re-written on verifiers' MultiTurnEnv (SEA's env classes are amaia-coupled).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path

import verifiers as vf
from verifiers.errors import SandboxError
from datasets import Dataset

from .prompt import NATIVE_SYSTEM_PROMPT, NATIVE_USER_PROMPT
from .parsers import _parse_native_tool_call
from .models import Command, CommandBatchResponse
from verifiers.utils.tool_utils import convert_func_to_tool_def
from .task_utils import (
    load_task_config,
    get_terminal_bench_vmvm_image_url,
    limit_output_length,
)
from .evaluation import run_terminal_bench_tests, _is_conn_lost
from ._vacli.backend import VacliVMVMBackend, VacliVMVMConfig
from ._vacli.reaper import start_reaper_once

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not any(getattr(_h, "_vmvm_tag", False) for _h in logger.handlers):
    _vmvm_h = logging.StreamHandler()
    _vmvm_h.setLevel(logging.INFO)
    _vmvm_h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s vmvm_tb_v1 %(message)s"))
    _vmvm_h._vmvm_tag = True
    logger.addHandler(_vmvm_h)
logger.propagate = False

# Cap mid-rollout reconnects so a chronically-flapping box can't loop forever.
_MAX_MIDROLLOUT_RECONNECTS = int(os.environ.get("VMVM_TB_MIDROLLOUT_RECONNECTS", "5"))

_NATIVE_SYS = NATIVE_SYSTEM_PROMPT + (
    "\n\nTo run a command, output EXACTLY one tool call and nothing else:\n"
    '<tool_call>{"name": "bash", "arguments": {"command": "<shell command>"}}</tool_call>\n'
    "When the task is fully solved, output:\n"
    '<tool_call>{"name": "submit", "arguments": {}}</tool_call>'
)


_TOKENIZER = None
_TOKENIZER_TRIED = False


def _count_tokens(text: str) -> int:
    """Exact token count via the served model's tokenizer; chars/4 estimate if unavailable."""
    global _TOKENIZER, _TOKENIZER_TRIED
    if not text:
        return 0
    if not _TOKENIZER_TRIED:
        _TOKENIZER_TRIED = True
        try:
            from transformers import AutoTokenizer
            _TOKENIZER = AutoTokenizer.from_pretrained(
                "/checkpoint/ram/tianhaowu/Qwen3.5-35B-A3B", trust_remote_code=True
            )
        except Exception:
            logger.warning("tokenizer load failed; using chars/4 token estimate", exc_info=True)
            _TOKENIZER = None
    if _TOKENIZER is not None:
        try:
            return len(_TOKENIZER.encode(text, add_special_tokens=False))
        except Exception:
            pass
    return (len(text) + 3) // 4


async def tb_reward(state, **kwargs) -> float:
    """pass@1 reward, computed during cleanup (before the VM is destroyed)."""
    return float(state.get("tb_reward", 0.0))


def _infra_summary(state) -> dict:
    """Derive SCALAR infra metrics from the state the env recorded during the
    rollout (drops, recoveries, and WHICH turn). Cached on state so the rubric's
    metric funcs share one computation. Scalars only: the orchestrator means every
    rubric metric, so a list/string would crash the step.

    v1 recovery is invisible to the model (no trajectory text), so these metrics are
    the ONLY structured signal that a rollout hit / recovered / died from an x2p drop.
    The full per-event list is logged to the env log by `_log_infra` for deep dives."""
    cached = state.get("_infra_summary")
    if cached is not None:
        return cached
    events = state.get("infra_events", []) or []
    drops = [e for e in events if e.get("type") == "drop"]
    drop_turns = sorted({e["turn"] for e in drops if isinstance(e.get("turn"), int)})
    box_gone_turns = [e.get("turn") for e in drops if e.get("class") == "rollout/box_gone"]
    ec = state.get("tb_error_class")
    lost = box_gone_turns[0] if box_gone_turns and isinstance(box_gone_turns[0], int) else -1
    rs = state.get("_rollout_start")
    # _rollout_end stamped at loop exit (in _finalize) so grading time isn't counted;
    # fall back to now if the rollout never reached cleanup.
    re_ = state.get("_rollout_end") or (time.monotonic() if rs else None)
    s = {
        "infra_drops": float(state.get("infra_drops", 0)),
        "infra_recovered": float(state.get("infra_recovered_drops", 0)),
        "infra_reconnect_attempts": float(state.get("_reconnects", 0)),
        "infra_n_turns_dropped": float(len(drop_turns)),
        "infra_first_drop_turn": float(drop_turns[0]) if drop_turns else -1.0,
        "infra_last_drop_turn": float(drop_turns[-1]) if drop_turns else -1.0,
        "infra_box_gone": 1.0 if ec == "rollout/box_gone" else 0.0,
        "infra_state_lost": 1.0 if ec == "rollout/state_lost" else 0.0,
        "infra_env_error": 1.0 if state.get("tb_outcome") == "env_error" else 0.0,
        "infra_lost_turn": float(lost),  # turn the rollout died on (box_gone), else -1
        # Granular per-class partition derived from tb_error_class (ec). Exactly one
        # fires per dropped rollout; do NOT derive from tb_outcome (env_error is a
        # superset of box_gone/state_lost/setup/grade-* -> would double-count).
        "infra_setup_fail": 1.0 if (ec or "").startswith("setup/") else 0.0,
        "infra_grade_conn_lost": 1.0 if ec == "grade/conn_lost" else 0.0,
        "infra_grade_upload": 1.0 if ec == "grade/upload" else 0.0,
        "infra_grade_no_reward": 1.0 if ec == "grade/no_reward" else 0.0,
        "infra_grade_reward_raise": 1.0 if ec == "grade/reward_raise" else 0.0,
        "infra_grade_finalize_timeout": 1.0 if ec == "grade/finalize_timeout" else 0.0,
        "infra_grade_timeout": 1.0 if ec == "grade/timeout" else 0.0,
        # test_timeout: grading exceeded test_timeout (outcome=="timeout"), distinct from
        # the agent-loop walltime_cap below and from env_error. (== infra_grade_timeout.)
        "test_timeout": 1.0 if state.get("tb_outcome") == "timeout" else 0.0,
        # max_rollout_s wall-clock cap: 1.0 if the agent loop was cut short by it.
        "walltime_cap": 1.0 if any(e.get("type") == "walltime_cap" for e in events) else 0.0,
        # agent-loop wall time (excludes grading); -1 if never started.
        "rollout_wall_s": float(re_ - rs) if rs and re_ else -1.0,
    }
    state["_infra_summary"] = s
    return s


async def infra_drops(state, **kw) -> float: return _infra_summary(state)["infra_drops"]
async def infra_recovered(state, **kw) -> float: return _infra_summary(state)["infra_recovered"]
async def infra_reconnect_attempts(state, **kw) -> float: return _infra_summary(state)["infra_reconnect_attempts"]
async def infra_n_turns_dropped(state, **kw) -> float: return _infra_summary(state)["infra_n_turns_dropped"]
async def infra_first_drop_turn(state, **kw) -> float: return _infra_summary(state)["infra_first_drop_turn"]
async def infra_last_drop_turn(state, **kw) -> float: return _infra_summary(state)["infra_last_drop_turn"]
async def infra_box_gone(state, **kw) -> float: return _infra_summary(state)["infra_box_gone"]
async def infra_state_lost(state, **kw) -> float: return _infra_summary(state)["infra_state_lost"]
async def infra_env_error(state, **kw) -> float: return _infra_summary(state)["infra_env_error"]
async def infra_lost_turn(state, **kw) -> float: return _infra_summary(state)["infra_lost_turn"]
async def walltime_cap(state, **kw) -> float: return _infra_summary(state)["walltime_cap"]
async def rollout_wall_s(state, **kw) -> float: return _infra_summary(state)["rollout_wall_s"]
async def test_timeout(state, **kw) -> float: return _infra_summary(state)["test_timeout"]
async def infra_setup_fail(state, **kw) -> float: return _infra_summary(state)["infra_setup_fail"]
async def infra_grade_conn_lost(state, **kw) -> float: return _infra_summary(state)["infra_grade_conn_lost"]
async def infra_grade_upload(state, **kw) -> float: return _infra_summary(state)["infra_grade_upload"]
async def infra_grade_no_reward(state, **kw) -> float: return _infra_summary(state)["infra_grade_no_reward"]
async def infra_grade_reward_raise(state, **kw) -> float: return _infra_summary(state)["infra_grade_reward_raise"]
async def infra_grade_finalize_timeout(state, **kw) -> float: return _infra_summary(state)["infra_grade_finalize_timeout"]
async def infra_grade_timeout(state, **kw) -> float: return _infra_summary(state)["infra_grade_timeout"]


# Metric-only (weight 0): recorded in each rollout's `metrics`; they do NOT affect
# reward (which stays == tb_reward). CAVEAT: prime-rl aggregates metrics/<env>/<name>
# and writes train_rollouts.jsonl over SURVIVORS only (has_error rollouts are dropped
# before both). So metrics that fire ONLY on a dropped rollout (test_timeout,
# infra_env_error, infra_box_gone, infra_state_lost) read ~0 in wandb; they are
# meaningful for RECOVERED drops that survive (e.g. infra_drops>0, tb_outcome!=env_error).
# Total dropped-rollout count is in prime-rl's `dispatcher/errored/<env>` counter.
_INFRA_METRIC_FUNCS = [
    infra_drops, infra_recovered, infra_reconnect_attempts,
    infra_box_gone, infra_state_lost, infra_env_error,
    infra_first_drop_turn, infra_last_drop_turn, infra_n_turns_dropped, infra_lost_turn,
    walltime_cap, rollout_wall_s, test_timeout,
    infra_setup_fail, infra_grade_conn_lost, infra_grade_upload, infra_grade_no_reward,
    infra_grade_reward_raise, infra_grade_finalize_timeout, infra_grade_timeout,
]


def _build_rubric() -> vf.Rubric:
    funcs = [tb_reward] + _INFRA_METRIC_FUNCS
    weights = [1.0] + [0.0] * len(_INFRA_METRIC_FUNCS)
    return vf.Rubric(funcs=funcs, weights=weights)


def _msg_content(m) -> str:
    if isinstance(m, dict):
        return m.get("content", "") or ""
    return getattr(m, "content", "") or ""


def bash(command: str) -> str:
    """Run a bash command inside the task container; returns combined stdout/stderr.

    Args:
        command: The shell command to execute, e.g. "ls -la /app".
    """
    raise NotImplementedError  # schema only; the env executes commands via the VM backend


def submit() -> str:
    """Submit the task as complete. Call this only once the task is fully solved."""
    raise NotImplementedError  # schema only


_TOOL_DEFS = [convert_func_to_tool_def(bash), convert_func_to_tool_def(submit)]


def _structured_tool_calls(m):
    """Tool calls the renderer parsed off the assistant turn (object- or dict-form)."""
    tcs = getattr(m, "tool_calls", None)
    if tcs is None and isinstance(m, dict):
        tcs = m.get("tool_calls")
    return tcs or []


def _tc_name_args(tc):
    if isinstance(tc, dict):
        fn = tc.get("function") or {}
        name = tc.get("name") or fn.get("name")
        raw = tc.get("arguments")
        if raw is None:
            raw = fn.get("arguments")
    else:
        name = getattr(tc, "name", None)
        raw = getattr(tc, "arguments", None)
        if name is None and hasattr(tc, "function"):
            name = getattr(tc.function, "name", None)
            raw = getattr(tc.function, "arguments", None)
    if isinstance(raw, str):
        try:
            args = json.loads(raw) if raw.strip() else {}
        except Exception:
            args = {}
    elif isinstance(raw, dict):
        args = raw
    else:
        args = {}
    return name, args


def _parse_structured_tool_calls(tool_calls, command_timeout):
    """Build a CommandBatchResponse from renderer-structured tool_calls.

    Same return contract as _parse_native_tool_call so env_response is unchanged
    downstream: (CommandBatchResponse | None, err_str).
    """
    cmds = []
    is_complete = False
    for tc in tool_calls:
        name, args = _tc_name_args(tc)
        if name == "submit":
            is_complete = True
        elif name == "bash":
            c = (args or {}).get("command", "") or ""
            if c:
                cmds.append(Command(
                    keystrokes=c if c.endswith("\n") else c + "\n",
                    is_blocking=True,
                    timeout_sec=command_timeout,
                ))
    if not cmds and not is_complete:
        return None, "tool_calls present but no usable bash/submit call"
    return CommandBatchResponse(
        state_analysis="", explanation="", bash_commands=cmds, is_task_complete=is_complete,
    ), ""


class VMVMTerminalBenchEnv(vf.MultiTurnEnv):
    def __init__(
        self,
        *,
        tenant_id: str = "async_2347641",
        command_timeout: float = 300.0,
        test_timeout: float = 900.0,
        max_output_length: int = 15000,
        session_timeout: float = 300.0,
        lease_ttl: str = "800s",
        max_parse_retries: int = 5,
        max_rollout_s: float = 3000.0,
        image_source: str = "vmvm_registry",  # or "task_toml" (docker.io from task.toml)
        native_tools: bool = False,  # True: declare tool_defs -> renderer/eval emit <function=> XML, env reads structured tool_calls
        raise_on_infra: bool = True,  # True: on unrecoverable infra (box_gone/state_lost/setup_fail) RAISE -> prime-rl marks has_error and DROPS the rollout (not trained). False: graceful reward-0 env_error completion (kept in batch; for eval analysis).
        drop_test_timeout: bool = True,  # True: a grading test-timeout marks the rollout errored (state["error"], like Option A) -> prime-rl DROPS it (not trained), since a timed-out grader is a budget/flaky signal, not a real reward-0 outcome. False: keep as a reward-0 "timeout" completion.
        drop_grade_env_error: bool = True,  # True: a grade-time env_error (conn-loss/upload/exec failure recovery couldn't fix, incl. grade/no_reward + grade/reward_raise) marks the rollout errored -> DROPPED. These are untrustworthy verdicts, not real fails. False: keep as reward-0 env_error completion (eval analysis). (Mid-rollout unrecoverable drops already raise directly via raise_on_infra.)
        **kwargs,
    ) -> None:
        if native_tools:
            kwargs.setdefault("tool_defs", _TOOL_DEFS)
        super().__init__(**kwargs)
        self.native_tools = native_tools
        self.raise_on_infra = raise_on_infra
        self.drop_test_timeout = drop_test_timeout
        self.drop_grade_env_error = drop_grade_env_error
        self.tenant_id = tenant_id
        self.command_timeout = command_timeout
        self.test_timeout = test_timeout
        self.max_output_length = max_output_length
        self.session_timeout = session_timeout
        self.lease_ttl = lease_ttl
        self.max_parse_retries = max_parse_retries
        self.max_rollout_s = max_rollout_s
        self.image_source = image_source

    def _emit_rollout_state(self, state, st, sub=""):
        # Design-C per-rollout lifecycle beacon (log-only, never raises).
        try:
            import time as _t
            info = state.get("info", {})
            rs = state.get("_rollout_start"); sd = state.get("_setup_done")
            now = _t.monotonic()
            t_setup = (now - rs) if rs else 0.0
            t_run = (now - sd) if sd else 0.0
            logger.info(
                "ROLLOUT_STATE rid=%s gid=%s task=%s state=%s turn=%d t_setup=%.1f t_run=%.1f timeout=%s sub=%s",
                id(state), info.get("_group_id"), info.get("task_name"), st, state.get("_turn_idx", 0),
                t_setup, t_run, getattr(self, "max_rollout_s", ""), sub,
            )
        except Exception:
            pass

    async def setup_state(self, state) -> "vf.State":
        info = state["info"]
        state["parse_errors"] = 0
        state["task_complete"] = False
        state["setup_failed"] = False
        state["tb_error_class"] = None
        state["tb_error_detail"] = None
        state["_reconnects"] = 0
        state["infra_events"] = []
        # Aggregate infra counters for trajectory filtering: infra_drops = mid-rollout
        # x2p drops detected; infra_recovered_drops = of those, how many were finished
        # transparently (model never saw them). A rollout is GOOD for training even
        # with infra_drops>0 as long as tb_outcome != "env_error" (all drops recovered);
        # filter out only tb_outcome == "env_error".
        state["infra_drops"] = 0
        state["infra_recovered_drops"] = 0
        state["turn_timings"] = []
        state["_turn_idx"] = 0
        state["_last_turn_end"] = time.perf_counter()
        state["_rollout_start"] = time.monotonic()
        self._emit_rollout_state(state, "setup")
        workdir = info.get("workdir", "/app")

        # Resilience: a transient lease/image-pull failure here must score THIS task
        # 0 (env_error), NOT crash the whole eval. At conc 128 across many nodes,
        # transient BackendInitError (vacli race, podman pull blob drop) is expected.
        try:
            vmvm_url = info["image_url"]
            docker_img = info.get("docker_image") or None
            # task_toml: pull the docker.io image declared in task.toml as primary
            # (the tb_train_v2 / 17k set lives at docker.io/tianhao0122/optimbench-tb,
            # NOT in vmvm-registry). vmvm_registry (default): keep the registry image
            # primary (the 80-task terminal-bench-2 set) with docker.io as fallback.
            if self.image_source == "task_toml":
                primary_img, fallback_img = (docker_img or vmvm_url), None
            else:
                primary_img, fallback_img = vmvm_url, docker_img
            cfg = VacliVMVMConfig(
                image_url=primary_img,
                fallback_image_url=fallback_img,
                work_dir=workdir,
                session_timeout=self.session_timeout,
                tenant_id=self.tenant_id,
                lease_ttl=self.lease_ttl,
            )
            backend = await asyncio.to_thread(VacliVMVMBackend, cfg)
            state["_backend"] = backend
            for _bre in getattr(backend, "bringup_retries", []):
                state["infra_events"].append({"phase": "setup", "type": "bringup_retry", **_bre})
            res = await asyncio.to_thread(backend.run_bash, f"cd {workdir} && pwd && ls -la", 30.0)
            initial_output = res.get("output", "") if isinstance(res, dict) else ""
            state["_setup_done"] = time.monotonic()
            self._emit_rollout_state(state, "running", sub="start")
        except Exception as e:
            _em = str(e).lower()
            if "pull" in _em or "image" in _em or "blob" in _em:
                _cls = "setup/pull"
            elif "sshd" in _em or "ssh" in _em:
                _cls = "setup/sshd"
            elif "lease" in _em or "tunnel" in _em or "tenant" in _em:
                _cls = "setup/lease"
            else:
                _cls = "setup/other"
            logger.error(
                "SETUP infra-error for %s (scored 0, eval continues) class=%s: %s: %s",
                info.get("task_name"), _cls, type(e).__name__, str(e)[:400],
            )
            _b = state.get("_backend")
            if _b is not None:
                try:
                    await asyncio.to_thread(_b.destroy)  # release the VM before we bail
                except Exception:
                    pass
            state["_backend"] = None
            state["setup_failed"] = True
            state["tb_reward"] = 0.0
            state["tb_outcome"] = "env_error"
            state["tb_message"] = f"setup failed: {str(e)[:500]}"
            state["tb_error_class"] = _cls
            state["tb_error_detail"] = f"{type(e).__name__}: {e}"[:1000]
            state.setdefault("infra_events", []).append(
                {"phase": "setup", "type": "setup_fail", "class": _cls,
                 "detail": f"{type(e).__name__}: {e}"[:300]})
            state["tb_test_output"] = ""
            state["tb_exit_code"] = None
            state["tb_report"] = None
            state["task_complete"] = True  # nothing to run; rollout ends immediately
            # Option A: raise so prime-rl's dispatcher marks has_error and the
            # train_sink DROPS this rollout (vs training a reward-0 sample that
            # corrupts GRPO). The VM is already released above; cleanup() still runs
            # via the driver's `finally`, so nothing leaks.
            if self.raise_on_infra:
                raise SandboxError(
                    f"setup infra failure [{_cls}]: {type(e).__name__}: {str(e)[:200]}"
                )
            initial_output = ""

        _sys = NATIVE_SYSTEM_PROMPT if getattr(self, "native_tools", False) else _NATIVE_SYS
        state["prompt"] = [
            {"role": "system", "content": _sys},
            {
                "role": "user",
                "content": NATIVE_USER_PROMPT.format(
                    instruction=info.get("instruction", ""),
                    terminal_state=initial_output,
                ),
            },
        ]
        return state

    async def env_response(self, messages, state, **kwargs):
        if state.get("setup_failed") or state.get("_backend") is None:
            state["task_complete"] = True
            return [{"role": "user", "content": "Environment setup failed; ending task."}]
        # Wall-clock cap on the agent loop: a slow/stuck rollout must not hold its
        # auto-renewed VM open indefinitely and stall its GRPO group. On expiry, end
        # the loop -> @vf.cleanup grades the current VM state (can still pass) then
        # destroys the VM. Overshoot bounded by one in-flight turn (<= command_timeout).
        if time.monotonic() - state.get("_rollout_start", time.monotonic()) > self.max_rollout_s:
            state["task_complete"] = True
            state.setdefault("infra_events", []).append(
                {"phase": "rollout", "type": "walltime_cap", "detail": f">{self.max_rollout_s:.0f}s"})
            logger.info("ROLLOUT walltime cap (>%.0fs) for %s; routing to grading",
                        self.max_rollout_s, state.get("info", {}).get("task_name"))
            return [{"role": "user", "content": "Wall-clock limit reached; ending task and grading."}]
        # gen_s = wall time the policy spent producing the message we are about to
        # process (includes server-side queue under concurrency -> per-turn latency).
        now = time.perf_counter()
        gen_s = now - state.get("_last_turn_end", now)

        last = messages[-1]
        content = _msg_content(last)
        reasoning = last.get("reasoning_content", "") if isinstance(last, dict) else ""
        rec = {
            "turn": state.get("_turn_idx", 0),
            "gen_s": round(gen_s, 3),
            "exec_s": 0.0,
            "n_cmds": 0,
            "asst_chars": len(content or ""),
            "reasoning_chars": len(reasoning or ""),
            "gen_tokens": _count_tokens((content or "") + (reasoning or "")),
            "cmds": [],
            "kind": "exec",
        }

        # Renderer path (training) parses <tool_call> off the assistant turn into
        # structured tool_calls; chat-completions eval leaves it in content. Read
        # structured first, fall back to text -> identical behavior on both paths.
        _tcs = _structured_tool_calls(last)
        if _tcs:
            parsed, _err = _parse_structured_tool_calls(_tcs, self.command_timeout)
        else:
            parsed, _err = _parse_native_tool_call(content, self.command_timeout)

        if parsed is None:
            state["parse_errors"] = state.get("parse_errors", 0) + 1
            rec["kind"] = "parse_error"
            state["turn_timings"].append(rec)
            state["_turn_idx"] = state.get("_turn_idx", 0) + 1
            state["_last_turn_end"] = time.perf_counter()
            return [{
                "role": "user",
                "content": (
                    "Your last message could not be parsed as a valid tool call. "
                    "Respond with a single <tool: bash> JSON block (analysis, plan, "
                    "commands[], task_complete)."
                ),
            }]

        if parsed.is_task_complete:
            state["task_complete"] = True
            rec["kind"] = "submit"
            state["turn_timings"].append(rec)
            state["_turn_idx"] = state.get("_turn_idx", 0) + 1
            state["_last_turn_end"] = time.perf_counter()
            return [{"role": "user", "content": "Task marked complete."}]

        backend = state["_backend"]
        outputs = []
        exec_total = 0.0
        box_gone = False
        state_lost = False
        self._emit_rollout_state(state, "running", sub="exec")
        cmds = parsed.bash_commands
        idx = 0
        while idx < len(cmds):
            cmd = cmds[idx]
            t0 = time.perf_counter()
            res = await asyncio.to_thread(backend.run_bash, cmd.keystrokes, cmd.timeout_sec)
            dt = time.perf_counter() - t0
            exec_total += dt
            out = res.get("output", "") if isinstance(res, dict) else str(res)
            ec = res.get("exit_code") if isinstance(res, dict) else None
            et = res.get("error_type") if isinstance(res, dict) else None

            # A dropped ssh tunnel (transient x2p reset during a long rollout)
            # surfaces as a SESSION-level error with our drop sentinel error_type
            # (broken_pipe/other). Gate on error_type ONLY -- NOT exit_code==-1,
            # which a real timeout/too_long also carries: a timed-out command whose
            # partial output happens to contain a conn-lost phrase must NOT be
            # misread as an x2p drop (that would burn the reconnect budget and lose
            # the real result). A normal command never sets these sentinel types.
            if not (_is_conn_lost(out) and et in ("broken_pipe", "other")):
                outputs.append(out)
                rec["cmds"].append({
                    "cmd": (cmd.keystrokes or "")[:200],
                    "exec_s": round(dt, 3),
                    "exit_code": ec,
                    "out_chars": len(out or ""),
                })
                idx += 1
                continue

            # --- mid-rollout drop on cmds[idx]: reconnect to the SAME box and
            # finish the command transparently. The v1 backend's shell lives
            # INSIDE the container (FIFO-backed), so cwd/env + the in-flight
            # command survive the drop; recover_last() returns the command's real
            # result and the AGENT NEVER SEES THE BLIP (no message, terminal
            # unchanged -- it looks like one continuous session). The under-the-hood
            # recovery is recorded ONLY in env metadata (infra_events + counters).
            # The inner loop retries through a tunnel that flaps repeatedly during
            # recovery WITHOUT re-executing the command. ---
            state["infra_drops"] = state.get("infra_drops", 0) + 1
            while True:
                state["_reconnects"] = state.get("_reconnects", 0) + 1
                cap = _MAX_MIDROLLOUT_RECONNECTS
                ok = False
                if state["_reconnects"] <= cap and hasattr(backend, "restart_session"):
                    ok = await asyncio.to_thread(backend.restart_session)
                logger.warning(
                    "MID-ROLLOUT conn-lost for %s (turn=%s, reconnect %d/%d) -> restart_session ok=%s",
                    state.get("info", {}).get("task_name"), rec.get("turn"),
                    state["_reconnects"], cap, ok,
                )
                if not ok:
                    state.setdefault("infra_events", []).append(
                        {"phase": "rollout", "turn": rec.get("turn"), "type": "drop",
                         "reconnected": False, "recovered": False,
                         "class": "rollout/box_gone"})
                    box_gone = True
                    break
                # Tunnel back + container shell verified alive. Finish cmds[idx].
                rec_res = None
                if hasattr(backend, "recover_last"):
                    rec_res = await asyncio.to_thread(backend.recover_last)
                if rec_res is None:
                    # Recovery could NOT be transparent: the in-container shell had to
                    # be rebuilt (state lost), or the image is fifo-incapable. We do
                    # NOT message the model (no v0-style "re-issue" prompt that would
                    # pollute the trajectory); instead mark this rollout as an infra
                    # failure so it is filtered out of training (handled below).
                    state.setdefault("infra_events", []).append(
                        {"phase": "rollout", "turn": rec.get("turn"), "type": "drop",
                         "reconnected": True, "recovered": False,
                         "class": "rollout/state_lost"})
                    state_lost = True
                    break
                r_out = rec_res.get("output", "") if isinstance(rec_res, dict) else str(rec_res)
                r_ec = rec_res.get("exit_code") if isinstance(rec_res, dict) else None
                r_et = rec_res.get("error_type") if isinstance(rec_res, dict) else None
                if _is_conn_lost(r_out) and r_et in ("broken_pipe", "other"):
                    # Dropped AGAIN during recovery; loop to reconnect (the command
                    # is still in flight and is NOT re-executed -- recover_last
                    # re-reads it).
                    state.setdefault("infra_events", []).append(
                        {"phase": "rollout", "turn": rec.get("turn"), "type": "drop",
                         "reconnected": True, "recovered": False,
                         "class": "rollout/reconnect"})
                    continue
                # Recovered: cmds[idx] completed; deliver its real output. From the
                # agent's view the terminal is unchanged (cwd/env preserved) and NO
                # message is sent -- the recovery exists only in env metadata.
                state.setdefault("infra_events", []).append(
                    {"phase": "rollout", "turn": rec.get("turn"), "type": "drop",
                     "reconnected": True, "recovered": True,
                     "class": "rollout/reconnect"})
                state["infra_recovered_drops"] = state.get("infra_recovered_drops", 0) + 1
                rec["recovered_drops"] = rec.get("recovered_drops", 0) + 1
                outputs.append(r_out)
                rec["cmds"].append({
                    "cmd": (cmd.keystrokes or "")[:200],
                    "exec_s": round(time.perf_counter() - t0, 3),
                    "exit_code": r_ec,
                    "out_chars": len(r_out or ""),
                    "recovered": True,
                })
                idx += 1
                break

            if box_gone or state_lost:
                break

        rec["exec_s"] = round(exec_total, 3)
        rec["n_cmds"] = len(rec["cmds"])

        if box_gone or state_lost:
            # Non-transparent outcome: either the box is genuinely gone (reconnect
            # failed / budget exhausted) or the connection came back but the shell
            # state was lost (in-flight command unrecoverable). Either way we attribute
            # an INFRA error (NOT a task fail -- that would silently depress pass@1) so
            # the trajectory is filtered out of training, and the model is told nothing
            # specific (it never learns a "we reconnected" pattern). Filter signal:
            # tb_outcome == "env_error".
            rec["kind"] = "box_gone" if box_gone else "state_lost"
            state["turn_timings"].append(rec)
            state["_turn_idx"] = state.get("_turn_idx", 0) + 1
            state["_last_turn_end"] = time.perf_counter()
            state["task_complete"] = True
            state["tb_outcome"] = "env_error"
            state["tb_reward"] = 0.0
            if box_gone:
                state["tb_error_class"] = "rollout/box_gone"
                state["tb_error_detail"] = (
                    "ssh tunnel lost mid-rollout; box unrecoverable after %d reconnect attempt(s)"
                    % state.get("_reconnects", 0)
                )
                state["tb_message"] = "Environment connection lost mid-rollout (box gone)"
            else:
                state["tb_error_class"] = "rollout/state_lost"
                state["tb_error_detail"] = (
                    "connection recovered but in-container shell state was lost mid-rollout "
                    "(in-flight command unrecoverable) after %d reconnect attempt(s)"
                    % state.get("_reconnects", 0)
                )
                state["tb_message"] = "Environment shell state lost mid-rollout (unrecoverable)"
            state["tb_test_output"] = ""
            state["tb_exit_code"] = None
            state["tb_report"] = None
            try:
                await asyncio.to_thread(backend.destroy)
            except Exception:
                pass
            state["_backend"] = None  # _finalize skips grading on this rollout
            self._log_infra(state)  # log full per-turn drop detail now (idempotent)
            # Option A: raise so prime-rl's dispatcher marks has_error and the
            # train_sink DROPS this rollout (vs training a reward-0 sample that
            # corrupts GRPO). The VM is already destroyed above, and cleanup() still
            # runs via the driver's `finally`, so nothing leaks.
            if self.raise_on_infra:
                raise SandboxError(
                    "%s after %d reconnect attempt(s)"
                    % (state.get("tb_error_class", "rollout/infra"), state.get("_reconnects", 0))
                )
            # Graceful mode (raise_on_infra=False): keep the rollout as a reward-0
            # env_error (e.g. for eval analysis); the model gets no reconnect hint.
            return [{"role": "user", "content": "Environment error; ending task."}]

        state["turn_timings"].append(rec)
        state["_turn_idx"] = state.get("_turn_idx", 0) + 1
        state["_last_turn_end"] = time.perf_counter()
        self._emit_rollout_state(state, "running", sub="turn")

        combined = limit_output_length("\n".join(outputs), self.max_output_length)
        return [{"role": "user", "content": f"Current terminal state:\n{combined}"}]

    @vf.stop
    async def _stop_task_complete(self, state) -> bool:
        return bool(state.get("task_complete", False))

    @vf.stop
    async def _stop_parse_errors(self, state) -> bool:
        return state.get("parse_errors", 0) > self.max_parse_retries

    def _log_infra(self, state):
        """Per-rollout fine-grained infra record -> env log. Captures the FULL list
        of which turns dropped and whether each recovered or died (the part that
        can't go in scalar metrics). Only logs when the rollout actually hit a drop.
        Pairs with the scalar `infra_*` metrics dumped into train_rollouts.jsonl."""
        try:
            events = state.get("infra_events", []) or []
            drops = [e for e in events if e.get("type") == "drop"]
            if not drops or state.get("_infra_logged"):
                return
            state["_infra_logged"] = True
            s = _infra_summary(state)
            info = state.get("info", {})
            logger.info(
                "ROLLOUT INFRA rid=%s task=%s outcome=%s drops=%d recovered=%d "
                "turns_dropped=%s lost_turn=%s events=%s",
                id(state), info.get("task_name"), state.get("tb_outcome"),
                int(s["infra_drops"]), int(s["infra_recovered"]),
                sorted({e.get("turn") for e in drops if isinstance(e.get("turn"), int)}),
                (int(s["infra_lost_turn"]) if s["infra_lost_turn"] >= 0 else None),
                [{"turn": e.get("turn"), "recovered": e.get("recovered"), "class": e.get("class")}
                 for e in drops],
            )
        except Exception:
            pass

    @vf.cleanup
    async def _finalize(self, state):
        state["_rollout_end"] = time.monotonic()  # agent-loop end (before grading) for rollout_wall_s
        self._log_infra(state)  # full per-turn drop detail (incl. box_gone rollouts) -> env log
        backend = state.get("_backend")
        if backend is None:
            self._emit_rollout_state(state, "done")
            return
        try:
            info = state["info"]
            self._emit_rollout_state(state, "grading")
            # Outer cap on grading: run_terminal_bench_tests retries conn-loss up to
            # VMVM_TB_GRADE_RETRIES, each backend run_bash self-bounded (~test_timeout+40).
            # A wedged grade must not pin the VM/permit indefinitely (max_rollout_s only
            # guards the agent loop, not cleanup). to_thread isn't truly cancellable, but
            # the wait_for frees the loop and the `finally` destroy() unwinds the worker.
            _grade_retries = max(1, int(os.environ.get("VMVM_TB_GRADE_RETRIES", "3")))
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    run_terminal_bench_tests,
                    backend,
                    Path(info["task_path"]),
                    "pytest",
                    self.test_timeout,
                ),
                timeout=self.test_timeout * _grade_retries + 120,
            )
            state["tb_outcome"] = result.outcome
            state["tb_reward"] = 1.0 if result.outcome == "pass" else 0.0
            # final test output + grader details (for inspection / debugging failures)
            state["tb_message"] = result.message
            state["tb_test_output"] = result.test_output
            state["tb_exit_code"] = result.exit_code
            state["tb_report"] = result.report
            state["tb_error_class"] = getattr(result, "error_class", None)
            state["tb_error_detail"] = getattr(result, "error_detail", None)
            for _ge in (getattr(result, "infra_events", None) or []):
                state.setdefault("infra_events", []).append(_ge)
            if result.outcome == "env_error":
                logger.error(
                    "GRADE infra-error recorded for %s class=%s: %s",
                    info.get("task_name"), getattr(result, "error_class", None),
                    (getattr(result, "error_detail", None) or result.message or "")[:400],
                )
            self._emit_rollout_state(state, "done")
            _tt = state.get("turn_timings", [])
            _cmds = " | ".join(c.get("cmd", "") for _r in _tt for c in _r.get("cmds", []))[:1500]
            _kinds = [_r.get("kind") for _r in _tt]
            logger.info(
                "ROLLOUT DONE rid=%s gid=%s task=%s reward=%s outcome=%s turns=%d parse_errors=%d kinds=%s\n"
                "  cmds: %s\n--- test output (tail) ---\n%s",
                id(state), info.get("_group_id"), info.get("task_name"), state["tb_reward"], result.outcome,
                len(_tt), state.get("parse_errors", 0), _kinds, _cmds,
                (result.test_output or "")[-200:],
            )
        except asyncio.TimeoutError:
            logger.error(
                "GRADE finalize timeout for %s -> grade/finalize_timeout (outer cap hit)",
                state.get("info", {}).get("task_name"),
            )
            state["tb_reward"] = 0.0
            state["tb_outcome"] = "env_error"
            state.setdefault("tb_message", "grade finalize timeout (outer cap)")
            state["tb_error_class"] = "grade/finalize_timeout"
            state.setdefault("infra_events", []).append(
                {"phase": "grade", "type": "finalize_timeout", "detail": "grade exceeded outer cap"})
            state.setdefault("tb_test_output", "")
            state.setdefault("tb_exit_code", None)
            state.setdefault("tb_report", None)
            self._emit_rollout_state(state, "done")
        except Exception as e:
            logger.error("GRADE infra-error (reward computation raised) for %s class=grade/reward_raise: %s",
                         state.get("info", {}).get("task_name"), e, exc_info=True)
            state["tb_reward"] = 0.0
            state.setdefault("tb_outcome", "env_error")
            state.setdefault("tb_message", "reward computation raised")
            state["tb_error_class"] = "grade/reward_raise"
            state["tb_error_detail"] = f"{type(e).__name__}: {e}"[:1000]
            state.setdefault("infra_events", []).append(
                {"phase": "grade", "type": "reward_raise", "detail": f"{type(e).__name__}: {e}"[:300]})
            state.setdefault("tb_test_output", "")
            state.setdefault("tb_exit_code", None)
            state.setdefault("tb_report", None)
            self._emit_rollout_state(state, "done")
        finally:
            try:
                await asyncio.to_thread(backend.destroy)
            except Exception:
                pass
            state["_backend"] = None

        # Remove infra-caused samples from training. A grade-time env_error (conn-loss /
        # upload / exec failure that recovery couldn't fix, incl. grade/no_reward and
        # grade/reward_raise) or a grade test-timeout is NOT a trustworthy pass/fail
        # signal, so mark the rollout errored (state["error"], like the mid-rollout
        # raise_on_infra Option A) -> prime-rl's train_sink DROPS it. We set state["error"]
        # rather than raise: raising from @vf.cleanup escapes rollout() uncaught, whereas
        # state["error"] serializes into the trace (-> has_error -> dropped). Mid-rollout
        # unrecoverable drops already raise directly in env_response.
        # TRACKING: dropped (has_error) rollouts are NOT written to train_rollouts.jsonl
        # (save_rollouts persists survivors only) and the weight-0 rubric metrics aggregate
        # over survivors, so they read ~0 in wandb. The drop IS counted coarsely via
        # prime-rl's per-env `dispatcher/errored/<env>` wandb counter; the per-class cause
        # is recoverable only from the env-log line emitted just below.
        _outcome = state.get("tb_outcome")
        _drop = (self.drop_test_timeout and _outcome == "timeout") or (
            self.drop_grade_env_error and _outcome == "env_error"
        )
        if _drop and state.get("error") is None:
            _cls = state.get("tb_error_class") or f"grade/{_outcome}"
            state["tb_error_class"] = _cls
            state.setdefault("infra_events", []).append(
                {"phase": "grade", "type": "infra_drop", "detail": f"{_outcome} [{_cls}]"}
            )
            logger.info(
                "ROLLOUT INFRA-DROP rid=%s gid=%s task=%s outcome=%s class=%s -> dropped from training",
                id(state), state.get("info", {}).get("_group_id"),
                state.get("info", {}).get("task_name"), _outcome, _cls,
            )
            state["error"] = SandboxError(
                f"grade infra drop: outcome={_outcome} [{_cls}] "
                f"task={state.get('info', {}).get('task_name')}"
            )


def _load_dataset(dataset_path: str) -> Dataset:
    rows = []
    with open(dataset_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            p = Path(obj["Path"])
            try:
                cfg = load_task_config(p)
            except Exception:
                cfg = {}
            instruction = cfg.get("instruction", "")
            rows.append({
                "question": instruction or p.name,
                "answer": "",
                "info": {
                    "task_path": str(p),
                    "task_name": p.name,
                    "image_url": get_terminal_bench_vmvm_image_url(p.name),
                    "docker_image": cfg.get("docker_image", "") or "",
                    "instruction": instruction,
                    "workdir": cfg.get("workdir", "/app"),
                },
            })
    return Dataset.from_list(rows)


def load_environment(
    dataset_path: str = "/checkpoint/ram/tianhaowu/datasets/terminal_bench/v2_harbor_pass80.jsonl",
    tenant_id: str = "async_2347641",
    max_turns: int = 200,
    command_timeout: float = 300.0,
    test_timeout: float = 900.0,
    **kwargs,
) -> vf.Environment:
    start_reaper_once()  # reap orphaned vacli leases left by hard-killed workers
    dataset = _load_dataset(dataset_path)
    return VMVMTerminalBenchEnv(
        tenant_id=tenant_id,
        dataset=dataset,
        eval_dataset=dataset,
        rubric=_build_rubric(),
        max_turns=max_turns,
        command_timeout=command_timeout,
        test_timeout=test_timeout,
        **kwargs,
    )
