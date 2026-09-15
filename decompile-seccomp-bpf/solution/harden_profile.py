#!/usr/bin/env python3
"""
Harden a Docker seccomp profile by applying production security policies.

Reads /app/seccomp_profile.json (the reverse-engineered original),
writes /app/hardened_profile.json.

Hardening rules:
1. Escalate any SCMP_ACT_LOG → SCMP_ACT_KILL_PROCESS
2. Escalate any non-default SCMP_ACT_ERRNO → SCMP_ACT_KILL_PROCESS
3. Add explicit KILL_PROCESS for add_key, request_key, keyctl
4. Extend clone's MASKED_EQ to also block CLONE_NEWNS (0x00020000)
"""

import copy
import json
import subprocess


ORIGINAL_PATH = "/app/seccomp_profile.json"
HARDENED_PATH = "/app/hardened_profile.json"

KEYRING_SYSCALLS = ["add_key", "request_key", "keyctl"]
CLONE_NEWNS_MASK = 0x00020000


def resolve_name(nr):
    """Resolve syscall number to name via scmp_sys_resolver."""
    try:
        result = subprocess.run(
            ["scmp_sys_resolver", "-a", "x86_64", str(nr)],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def get_names(rule):
    names = rule.get("names", rule.get("name", []))
    if isinstance(names, str):
        names = [names]
    return [n.lower() for n in names]


def harden():
    with open(ORIGINAL_PATH) as f:
        profile = json.load(f)

    hardened = copy.deepcopy(profile)
    default_errno = hardened.get("defaultErrnoRet", 1)

    new_syscalls = []

    for rule in hardened.get("syscalls", []):
        action = rule.get("action", "")
        names = get_names(rule)

        # Rule 1: Escalate LOG → KILL_PROCESS
        if "LOG" in action.upper() and "ALLOW" not in action.upper():
            print(f"  Escalating LOG → KILL_PROCESS for {names}")
            rule["action"] = "SCMP_ACT_KILL_PROCESS"
            rule.pop("errnoRet", None)

        # Rule 2: Escalate non-default ERRNO → KILL_PROCESS
        elif "ERRNO" in action.upper():
            errno_ret = rule.get("errnoRet", default_errno)
            if errno_ret != default_errno:
                print(f"  Escalating ERRNO({errno_ret}) → KILL_PROCESS for {names}")
                rule["action"] = "SCMP_ACT_KILL_PROCESS"
                rule.pop("errnoRet", None)

        # Rule 4: Extend clone MASKED_EQ with CLONE_NEWNS
        if "clone" in names and "ALLOW" in action.upper():
            args = rule.get("args", [])
            has_newuser = any(
                a.get("index") == 0
                and "MASKED" in a.get("op", "").upper()
                and a.get("value") == 0x10000000
                for a in args
            )
            has_newns = any(
                a.get("index") == 0
                and "MASKED" in a.get("op", "").upper()
                and a.get("value") == CLONE_NEWNS_MASK
                for a in args
            )
            if has_newuser and not has_newns:
                print(f"  Adding CLONE_NEWNS mask to clone rule")
                args.append({
                    "index": 0,
                    "value": CLONE_NEWNS_MASK,
                    "op": "SCMP_CMP_MASKED_EQ",
                    "valueTwo": 0,
                })

        new_syscalls.append(rule)

    # Rule 3: Add keyring isolation rules
    existing_names = set()
    for rule in new_syscalls:
        existing_names.update(get_names(rule))

    for syscall_name in KEYRING_SYSCALLS:
        if syscall_name not in existing_names:
            print(f"  Adding KILL_PROCESS for {syscall_name}")
            new_syscalls.append({
                "names": [syscall_name],
                "action": "SCMP_ACT_KILL_PROCESS",
            })

    hardened["syscalls"] = new_syscalls

    with open(HARDENED_PATH, "w") as f:
        json.dump(hardened, f, indent=2)
    print(f"Wrote hardened profile to {HARDENED_PATH}")


if __name__ == "__main__":
    harden()
