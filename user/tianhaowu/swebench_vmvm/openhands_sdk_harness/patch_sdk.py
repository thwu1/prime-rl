#!/usr/bin/env python3

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path

AGENT_OLD = """        # Finish conversation if LLM produced content (awaits user input)
        # Continue if only reasoning without content (e.g., GPT-5 codex thinking)
        if has_content:
            logger.debug("LLM produced a message response - awaits user input")
            state.execution_status = ConversationExecutionStatus.FINISHED
            return"""

AGENT_NEW = """        # Text-only responses are intermediate for the published NEL harness.
        if has_content:
            logger.debug("LLM produced text without tool call - continuing (NEL)")"""

NUDGE_OLD = "        if not has_content:"
NUDGE_NEW = "        if True:  # NEL always nudges a response without a tool call"

TERMINAL_OLD = """            if action.timeout is not None:
                time_since_start = time.time() - start_time
                if time_since_start >= action.timeout:
                    obs = self._handle_hard_timeout_command(
                        command,
                        terminal_content=cur_terminal_output,
                        ps1_matches=ps1_matches,
                        timeout=action.timeout,
                    )
                    logger.debug(f"RETURNING OBSERVATION (hard-timeout): {obs}")
                    return obs"""

TERMINAL_NEW = """            _NEL_MAX = 1800
            _eff_timeout = min(action.timeout, _NEL_MAX) if action.timeout is not None else _NEL_MAX
            if elapsed_time >= _eff_timeout:
                obs = self._handle_hard_timeout_command(
                    command,
                    terminal_content=cur_terminal_output,
                    ps1_matches=ps1_matches,
                    timeout=_eff_timeout,
                )
                logger.debug(f"RETURNING OBSERVATION (hard-timeout): {obs}")
                return obs"""


def _replace_once(path: Path, old: str, new: str, marker: str) -> str:
    source = path.read_text()
    if marker in source:
        return "already_patched"
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one patch anchor, found {count}")
    path.write_text(source.replace(old, new, 1))
    return "patched"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--venv", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()

    site_packages = next((args.venv / "lib").glob("python*/site-packages"))
    agent = site_packages / "openhands/sdk/agent/agent.py"
    terminal = site_packages / "openhands/tools/terminal/terminal/terminal_session.py"

    agent_result = _replace_once(agent, AGENT_OLD, AGENT_NEW, "continuing (NEL)")
    nudge_result = _replace_once(agent, NUDGE_OLD, NUDGE_NEW, "NEL always nudges")
    terminal_result = _replace_once(terminal, TERMINAL_OLD, TERMINAL_NEW, "_NEL_MAX = 1800")

    payload = {
        "schema_version": 1,
        "source": {
            "nemo_gym_commit": "354babf7e3554fcd006807c86e80ef476aec9408",
            "nemo_evaluator_commit": "230c8411fff82fa581195b7d088d7fb67d3bc98c",
            "harbor_version": "0.3.0",
        },
        "packages": {
            "openhands-sdk": importlib.metadata.version("openhands-sdk"),
            "openhands-tools": importlib.metadata.version("openhands-tools"),
        },
        "patches": {
            "continue_text_only": agent_result,
            "always_nudge_no_tool": nudge_result,
            "terminal_timeout_1800": terminal_result,
        },
        "files": {
            str(agent.relative_to(args.venv)): _sha256(agent),
            str(terminal.relative_to(args.venv)): _sha256(terminal),
        },
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.manifest.with_suffix(args.manifest.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, args.manifest)
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
