"""Exact-once recovery helpers for the VMVM transport."""

from __future__ import annotations

from vmvm_tb_v2._vacli.backend import VacliVMVMBackend
from vmvm_tb_v2._vacli.types import BashResult


def run_with_recovery(
    backend: VacliVMVMBackend,
    command: str,
    *,
    timeout: float,
    max_connection_drops: int = 5,
) -> BashResult:
    """Collect one in-flight command across recoverable transport drops."""

    result = backend.run_bash(command, timeout=timeout)
    drops = 0
    while result["exit_code"] < 0 and result["error_type"] == "broken_pipe":
        drops += 1
        if drops > max_connection_drops or not backend.restart_session():
            return result
        recovered = backend.recover_last()
        if recovered is None:
            return result
        result = recovered
    return result
