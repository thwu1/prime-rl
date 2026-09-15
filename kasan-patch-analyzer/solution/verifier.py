"""
Verification outcome classification per the RGym protocol.

Classifies results from multiple VM verification runs into one of four
outcomes: Pass, Trigger, Racey, or Boot Fail. Handles the non-deterministic
nature of kernel bug reproduction where ~1/3 of bugs have non-deterministic
reproducers.
"""

from enum import Enum
from typing import List, Dict


class VerificationOutcome(Enum):
    """Possible outcomes from the RGym verification protocol."""
    PASS = "pass"
    TRIGGER = "trigger"
    RACEY = "racey"
    BOOT_FAIL = "boot_fail"


def classify_verification(
    runs: List[Dict],
    trigger_threshold: float = 0.8,
    boot_fail_threshold: float = 0.5
) -> VerificationOutcome:
    """
    Classify the overall verification outcome from VM run results.

    Each run is a dict with:
      - "vm_id": int
      - "type": "syz" or "c"
      - "outcome": "no_crash" | "crash" | "boot_fail"
      - "duration_sec": float

    Classification rules (per RGym protocol):
      1. If >boot_fail_threshold of VMs report boot_fail -> BOOT_FAIL
      2. Among non-boot-fail VMs:
         - If 0 crashes -> PASS
         - If >trigger_threshold fraction crash -> TRIGGER
         - Otherwise -> RACEY (non-deterministic reproduction)

    Args:
        runs: List of VM run result dicts
        trigger_threshold: Fraction of non-boot-fail VMs that must crash
            to classify as TRIGGER (default 0.8)
        boot_fail_threshold: Fraction of VMs that must boot-fail to
            classify as BOOT_FAIL (default 0.5)

    Returns:
        VerificationOutcome enum value
    """
    if not runs:
        raise ValueError("No VM runs provided")

    total = len(runs)
    boot_fails = sum(1 for r in runs if r["outcome"] == "boot_fail")
    crashes = sum(1 for r in runs if r["outcome"] == "crash")
    no_crashes = sum(1 for r in runs if r["outcome"] == "no_crash")

    # Check boot fail threshold first
    if boot_fails / total > boot_fail_threshold:
        return VerificationOutcome.BOOT_FAIL

    # Among non-boot-fail VMs, check crash rate
    non_boot_fail = total - boot_fails
    if non_boot_fail == 0:
        return VerificationOutcome.BOOT_FAIL

    if crashes == 0:
        return VerificationOutcome.PASS

    crash_rate = crashes / non_boot_fail
    if crash_rate >= trigger_threshold:
        return VerificationOutcome.TRIGGER

    return VerificationOutcome.RACEY
