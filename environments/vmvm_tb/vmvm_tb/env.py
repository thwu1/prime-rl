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
from datasets import Dataset

from .prompt import NATIVE_SYSTEM_PROMPT, NATIVE_USER_PROMPT
from .parsers import _parse_native_tool_call
from .task_utils import (
    load_task_config,
    get_terminal_bench_vmvm_image_url,
    limit_output_length,
)
from .evaluation import run_terminal_bench_tests, _is_conn_lost
from ._vacli.backend import VacliVMVMBackend, VacliVMVMConfig

logger = logging.getLogger(__name__)

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


def _build_rubric() -> vf.Rubric:
    return vf.Rubric(funcs=[tb_reward], weights=[1.0])


def _msg_content(m) -> str:
    if isinstance(m, dict):
        return m.get("content", "") or ""
    return getattr(m, "content", "") or ""


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
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.tenant_id = tenant_id
        self.command_timeout = command_timeout
        self.test_timeout = test_timeout
        self.max_output_length = max_output_length
        self.session_timeout = session_timeout
        self.lease_ttl = lease_ttl
        self.max_parse_retries = max_parse_retries

    async def setup_state(self, state) -> "vf.State":
        info = state["info"]
        state["parse_errors"] = 0
        state["task_complete"] = False
        state["setup_failed"] = False
        state["tb_error_class"] = None
        state["tb_error_detail"] = None
        state["_reconnects"] = 0
        state["infra_events"] = []
        state["turn_timings"] = []
        state["_turn_idx"] = 0
        state["_last_turn_end"] = time.perf_counter()
        workdir = info.get("workdir", "/app")

        # Resilience: a transient lease/image-pull failure here must score THIS task
        # 0 (env_error), NOT crash the whole eval. At conc 128 across many nodes,
        # transient BackendInitError (vacli race, podman pull blob drop) is expected.
        try:
            cfg = VacliVMVMConfig(
                image_url=info["image_url"],
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
            initial_output = ""

        state["prompt"] = [
            {"role": "system", "content": _NATIVE_SYS},
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
        dropped = False
        for cmd in parsed.bash_commands:
            t0 = time.perf_counter()
            res = await asyncio.to_thread(backend.run_bash, cmd.keystrokes, cmd.timeout_sec)
            dt = time.perf_counter() - t0
            exec_total += dt
            out = res.get("output", "") if isinstance(res, dict) else str(res)
            ec = res.get("exit_code") if isinstance(res, dict) else None
            et = res.get("error_type") if isinstance(res, dict) else None
            outputs.append(out)
            rec["cmds"].append({
                "cmd": (cmd.keystrokes or "")[:200],
                "exec_s": round(dt, 3),
                "exit_code": ec,
                "out_chars": len(out or ""),
            })
            # A dropped ssh tunnel (transient x2p reset during a long rollout)
            # surfaces as a SESSION-level error whose output carries a conn-lost
            # marker. Distinguish from a normal command that merely PRINTS such a
            # phrase: a real drop has our session-error sentinel (exit_code == -1
            # or error_type broken_pipe/other); a normal command does not.
            if _is_conn_lost(out) and (ec == -1 or et in ("broken_pipe", "other")):
                dropped = True
                break
        rec["exec_s"] = round(exec_total, 3)
        rec["n_cmds"] = len(rec["cmds"])

        if dropped:
            # Reconnect to the SAME box (container + files intact). The in-flight
            # command did NOT execute (the stdin write failed), so nothing is
            # double-applied. Bounded so a chronically-flapping box can't loop.
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
            state.setdefault("infra_events", []).append(
                {"phase": "rollout", "turn": rec.get("turn"), "type": "drop",
                 "reconnected": bool(ok),
                 "class": "rollout/reconnect" if ok else "rollout/box_gone"})
            if ok:
                rec["kind"] = "reconnect"
                state["turn_timings"].append(rec)
                state["_turn_idx"] = state.get("_turn_idx", 0) + 1
                state["_last_turn_end"] = time.perf_counter()
                return [{
                    "role": "user",
                    "content": (
                        "[infra] The connection to the environment dropped and was "
                        "re-established on the SAME machine. Your files on disk are "
                        "intact, but the shell was reset: the working directory is back "
                        "to the default and any shell variables/functions you set are "
                        "cleared. Re-establish your working directory (e.g. cd into your "
                        "project) and re-issue your most recent command."
                    ),
                }]
            # Box is genuinely gone (or reconnect budget exhausted): attribute as
            # an infra error (NOT a task fail, which would silently depress pass@1)
            # and end the rollout.
            rec["kind"] = "box_gone"
            state["turn_timings"].append(rec)
            state["_turn_idx"] = state.get("_turn_idx", 0) + 1
            state["_last_turn_end"] = time.perf_counter()
            state["task_complete"] = True
            state["tb_outcome"] = "env_error"
            state["tb_reward"] = 0.0
            state["tb_error_class"] = "rollout/box_gone"
            state["tb_error_detail"] = (
                "ssh tunnel lost mid-rollout; box unrecoverable after %d reconnect attempt(s)"
                % state["_reconnects"]
            )
            state["tb_message"] = "Environment connection lost mid-rollout (box gone)"
            state["tb_test_output"] = ""
            state["tb_exit_code"] = None
            state["tb_report"] = None
            try:
                await asyncio.to_thread(backend.destroy)
            except Exception:
                pass
            state["_backend"] = None  # _finalize early-returns, keeping this attribution
            return [{"role": "user", "content": "Environment connection lost permanently; ending task."}]

        state["turn_timings"].append(rec)
        state["_turn_idx"] = state.get("_turn_idx", 0) + 1
        state["_last_turn_end"] = time.perf_counter()

        combined = limit_output_length("\n".join(outputs), self.max_output_length)
        return [{"role": "user", "content": f"Current terminal state:\n{combined}"}]

    @vf.stop
    async def _stop_task_complete(self, state) -> bool:
        return bool(state.get("task_complete", False))

    @vf.stop
    async def _stop_parse_errors(self, state) -> bool:
        return state.get("parse_errors", 0) > self.max_parse_retries

    @vf.cleanup
    async def _finalize(self, state):
        backend = state.get("_backend")
        if backend is None:
            return
        try:
            info = state["info"]
            result = await asyncio.to_thread(
                run_terminal_bench_tests,
                backend,
                Path(info["task_path"]),
                "pytest",
                self.test_timeout,
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
            logger.info(
                "task %s -> %s (reward=%s exit=%s)\n--- test output (tail) ---\n%s",
                info.get("task_name"), result.outcome, state["tb_reward"], result.exit_code,
                (result.test_output or "")[-2000:],
            )
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
        finally:
            try:
                await asyncio.to_thread(backend.destroy)
            except Exception:
                pass
            state["_backend"] = None


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
    test_timeout: float = 300.0,
    **kwargs,
) -> vf.Environment:
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
