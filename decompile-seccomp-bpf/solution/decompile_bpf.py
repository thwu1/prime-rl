#!/usr/bin/env python3
"""
Decompile a seccomp-BPF classic BPF filter binary into a Docker-format
seccomp profile JSON.

Uses scmp_sys_resolver (libseccomp) for architecture-aware syscall name
resolution and seccomp-tools for cross-reference disassembly.

Reads /app/seccomp_filter.bpf (raw struct sock_filter[]),
writes /app/seccomp_profile.json.
"""

import json
import struct
import subprocess
import sys

# ── BPF opcode constants ──
BPF_LD_W_ABS   = 0x20   # BPF_LD | BPF_W | BPF_ABS
BPF_JMP_JEQ_K  = 0x15   # BPF_JMP | BPF_JEQ | BPF_K
BPF_JMP_JSET_K = 0x45   # BPF_JMP | BPF_JSET | BPF_K
BPF_JMP_JA     = 0x05   # BPF_JMP | BPF_JA
BPF_RET_K      = 0x06   # BPF_RET | BPF_K

# ── Seccomp return-value masks ──
RET_ACTION_MASK = 0xFFFF0000
RET_DATA_MASK   = 0x0000FFFF

ACTION_MAP = {
    0x7FFF0000: "SCMP_ACT_ALLOW",
    0x7FFC0000: "SCMP_ACT_LOG",
    0x7FF00000: "SCMP_ACT_TRACE",
    0x00050000: "SCMP_ACT_ERRNO",
    0x00030000: "SCMP_ACT_TRAP",
    0x80000000: "SCMP_ACT_KILL_PROCESS",
    0x00000000: "SCMP_ACT_KILL",
}

AUDIT_ARCH_X86_64 = 0xC000003E

# seccomp_data layout offsets
OFF_NR   = 0
OFF_ARCH = 4
OFF_ARGS = 16   # args[0] starts here, each arg is 8 bytes


def resolve_syscall_name(nr):
    """Resolve syscall number to name using scmp_sys_resolver."""
    try:
        result = subprocess.run(
            ["scmp_sys_resolver", "-a", "x86_64", str(nr)],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    # Fallback: try ausyscall
    try:
        result = subprocess.run(
            ["ausyscall", "x86_64", str(nr)],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return f"syscall_{nr}"


def parse_instructions(data):
    """Parse raw bytes into list of BPF instruction dicts."""
    insts = []
    for i in range(0, len(data), 8):
        code, jt, jf, k = struct.unpack('<HBBI', data[i:i+8])
        insts.append({'code': code, 'jt': jt, 'jf': jf, 'k': k})
    return insts


def decode_ret(val):
    """Decode a SECCOMP_RET_* value into (action_str, errno_or_none)."""
    action_bits = val & RET_ACTION_MASK
    data_bits = val & RET_DATA_MASK
    action_str = ACTION_MAP.get(action_bits, f"UNKNOWN(0x{val:08x})")
    errno_val = data_bits if action_bits == 0x00050000 else None
    return action_str, errno_val


def offset_to_arg_index(offset):
    """Convert a seccomp_data byte-offset (>=16) to an argument index."""
    if offset < OFF_ARGS:
        return None
    return (offset - OFF_ARGS) // 8


def decompile(bpf_path, out_path):
    with open(bpf_path, 'rb') as f:
        data = f.read()
    insts = parse_instructions(data)

    print(f"Parsed {len(insts)} BPF instructions ({len(data)} bytes)")

    # ── Step 1: detect architecture check (instructions 0-2) ──
    architectures = []
    if (insts[0]['code'] == BPF_LD_W_ABS and insts[0]['k'] == OFF_ARCH
            and insts[1]['code'] == BPF_JMP_JEQ_K):
        arch_val = insts[1]['k']
        if arch_val == AUDIT_ARCH_X86_64:
            architectures.append("SCMP_ARCH_X86_64")

    # ── Step 2: walk the main JEQ chain on syscall number ──
    pc = 3  # skip: LD [4], JEQ arch, RET kill
    # advance past the LD [0]
    if insts[pc]['code'] == BPF_LD_W_ABS and insts[pc]['k'] == OFF_NR:
        pc += 1

    syscall_checks = []      # (syscall_nr, true_target_idx)
    default_action = None
    default_errno = None

    while pc < len(insts):
        inst = insts[pc]
        if inst['code'] == BPF_JMP_JEQ_K:
            true_target = pc + 1 + inst['jt']
            syscall_checks.append((inst['k'], true_target))
            pc += 1 + inst['jf']  # follow false (fall-through) path
        elif inst['code'] == BPF_RET_K:
            default_action, default_errno = decode_ret(inst['k'])
            break
        else:
            pc += 1

    print(f"Found {len(syscall_checks)} syscall checks, default={default_action}")

    # ── Step 3: classify each syscall check ──
    unconditional_allows = []
    conditional_rules = []
    special_rules = []

    for syscall_nr, target_idx in syscall_checks:
        target = insts[target_idx]
        name = resolve_syscall_name(syscall_nr)
        print(f"  syscall {syscall_nr} -> {name} (target pc {target_idx})")

        if target['code'] == BPF_RET_K:
            # Direct return — unconditional action
            action, errno = decode_ret(target['k'])
            if action == "SCMP_ACT_ALLOW":
                unconditional_allows.append(name)
            else:
                rule = {"names": [name], "action": action}
                if errno is not None and errno > 0:
                    rule["errnoRet"] = errno
                special_rules.append(rule)

        elif target['code'] == BPF_LD_W_ABS:
            # Loading an argument field -> conditional rule
            arg_idx = offset_to_arg_index(target['k'])
            apc = target_idx + 1
            conds = []

            while apc < len(insts):
                ai = insts[apc]

                if ai['code'] == BPF_JMP_JEQ_K:
                    true_tgt = apc + 1 + ai['jt']
                    if insts[true_tgt]['code'] == BPF_RET_K:
                        act, eno = decode_ret(insts[true_tgt]['k'])
                        conds.append({
                            'op': 'SCMP_CMP_EQ',
                            'index': arg_idx,
                            'value': ai['k'],
                            'action': act,
                            'errno': eno,
                        })
                    apc += 1 + ai['jf']

                elif ai['code'] == BPF_JMP_JSET_K:
                    true_tgt = apc + 1 + ai['jt']
                    false_tgt = apc + 1 + ai['jf']
                    t_act, t_eno = decode_ret(insts[true_tgt]['k'])
                    f_act, f_eno = decode_ret(insts[false_tgt]['k'])

                    if f_act == "SCMP_ACT_ALLOW":
                        # bits NOT set -> allow => (arg & mask) == 0
                        conds.append({
                            'op': 'SCMP_CMP_MASKED_EQ',
                            'index': arg_idx,
                            'mask': ai['k'],
                            'masked_value': 0,
                            'action': f_act,
                            'errno': f_eno,
                        })
                    elif t_act == "SCMP_ACT_ALLOW":
                        # bits set -> allow => (arg & mask) == mask
                        conds.append({
                            'op': 'SCMP_CMP_MASKED_EQ',
                            'index': arg_idx,
                            'mask': ai['k'],
                            'masked_value': ai['k'],
                            'action': t_act,
                            'errno': t_eno,
                        })
                    break

                elif ai['code'] == BPF_RET_K:
                    break
                else:
                    apc += 1

            # Emit one JSON rule per condition (OR semantics between rules)
            for c in conds:
                rule = {"names": [name], "action": c['action']}
                if c.get('errno') and c['errno'] > 0:
                    rule["errnoRet"] = c['errno']
                if c['op'] == 'SCMP_CMP_EQ':
                    rule["args"] = [{
                        "index": c['index'],
                        "value": c['value'],
                        "op": "SCMP_CMP_EQ",
                    }]
                elif c['op'] == 'SCMP_CMP_MASKED_EQ':
                    rule["args"] = [{
                        "index": c['index'],
                        "value": c['mask'],
                        "op": "SCMP_CMP_MASKED_EQ",
                        "valueTwo": c['masked_value'],
                    }]
                conditional_rules.append(rule)

    # ── Step 4: assemble the profile ──
    profile = {"defaultAction": default_action}
    if default_errno is not None and default_errno > 0:
        profile["defaultErrnoRet"] = default_errno
    if architectures:
        profile["architectures"] = architectures

    syscalls_out = []
    if unconditional_allows:
        syscalls_out.append({
            "names": sorted(unconditional_allows),
            "action": "SCMP_ACT_ALLOW",
        })
    syscalls_out.extend(conditional_rules)
    syscalls_out.extend(special_rules)

    profile["syscalls"] = syscalls_out

    with open(out_path, 'w') as f:
        json.dump(profile, f, indent=2)
    print(f"Wrote seccomp profile to {out_path}")


if __name__ == '__main__':
    decompile(
        '/app/seccomp_filter.bpf',
        '/app/seccomp_profile.json',
    )
