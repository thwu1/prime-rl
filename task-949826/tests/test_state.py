#!/usr/bin/env python3
"""Tests for the RISC-V Sv39 Page Table Audit Tool."""

import json
import os
import subprocess
import pytest


# ═══════════════════════════════════════════════════════════════════
# Helper: run the audit tool
# ═══════════════════════════════════════════════════════════════════

def run_audit_tool():
    """Run /app/ptw_audit and return parsed JSON output."""
    audit_path = '/app/ptw_audit'
    assert os.path.exists(audit_path), f"{audit_path} not found"

    if os.access(audit_path, os.X_OK):
        cmd = [audit_path]
    else:
        cmd = ['python3', audit_path]

    proc = subprocess.run(
        cmd, capture_output=True, text=True, timeout=60, cwd='/app')
    assert proc.returncode == 0, (
        f"ptw_audit exited with code {proc.returncode}\n"
        f"stderr: {proc.stderr}\nstdout: {proc.stdout[:500]}"
    )

    result = json.loads(proc.stdout)
    return result


# ═══════════════════════════════════════════════════════════════════
# Expected audit results for all 5 binaries
# ═══════════════════════════════════════════════════════════════════

EXPECTED = {
    "kern.elf": [
        # Seg 0: VA=0x0, L0A[0] S-mode RWX|G|A|D → all OK
        {"vaddr": "0x0", "memsz": 4096, "flags": "rwx",
         "status": "ok", "pa": "0x10000000", "page_size": 4096},
        # Seg 1: VA=0x1000, L0A[1] R-only → write faults
        {"vaddr": "0x1000", "memsz": 4096, "flags": "rw",
         "status": "fault", "cause": "store_page_fault"},
    ],
    "driver.elf": [
        # Seg 0: VA=0x200000, L1A[1] 2MB megapage RX → OK
        {"vaddr": "0x200000", "memsz": 4096, "flags": "rx",
         "status": "ok", "pa": "0xa0000000", "page_size": 2097152},
        # Seg 1: VA=0x400000, L1A[2] 2MB megapage RW → OK
        {"vaddr": "0x400000", "memsz": 4096, "flags": "rw",
         "status": "ok", "pa": "0xb0000000", "page_size": 2097152},
        # Seg 2: VA=0x600000, L1A[3] misaligned megapage → fault
        {"vaddr": "0x600000", "memsz": 4096, "flags": "r",
         "status": "fault", "cause": "load_page_fault"},
    ],
    "app_alpha.elf": [
        # Seg 0: VA=0x2000, L0A[2] U-mode RWX → OK
        {"vaddr": "0x2000", "memsz": 4096, "flags": "rwx",
         "status": "ok", "pa": "0x10002000", "page_size": 4096},
        # Seg 1: VA=0x800000, L1A[4] U-mode 2MB megapage RX → OK
        {"vaddr": "0x800000", "memsz": 4096, "flags": "rx",
         "status": "ok", "pa": "0xd0000000", "page_size": 2097152},
    ],
    "monitor.elf": [
        # Seg 0: VA=0x3000, L0A[3] X-only, MXR=true → read OK, exec OK
        {"vaddr": "0x3000", "memsz": 4096, "flags": "rx",
         "status": "ok", "pa": "0x10003000", "page_size": 4096},
        # Seg 1: VA=0x4000, L0A[4] RW but A=0, svade → read faults
        {"vaddr": "0x4000", "memsz": 4096, "flags": "rw",
         "status": "fault", "cause": "load_page_fault"},
        # Seg 2: VA=0x5000, L0A[5] RW but D=0, svade → write faults
        {"vaddr": "0x5000", "memsz": 4096, "flags": "rw",
         "status": "fault", "cause": "store_page_fault"},
    ],
    "diag.elf": [
        # Seg 0: VA=0x2000, L0A[2] U-page, S+SUM → read OK
        {"vaddr": "0x2000", "memsz": 4096, "flags": "r",
         "status": "ok", "pa": "0x10002000", "page_size": 4096},
        # Seg 1: VA=0x6000, L0A[6] non-leaf at L0 → fault
        {"vaddr": "0x6000", "memsz": 4096, "flags": "r",
         "status": "fault", "cause": "load_page_fault"},
        # Seg 2: VA=0x7000, L0A[7] reserved (W=1,R=0) → fault
        {"vaddr": "0x7000", "memsz": 4096, "flags": "r",
         "status": "fault", "cause": "load_page_fault"},
        # Seg 3: VA=0x8000, L0A[8] V=0 → fault
        {"vaddr": "0x8000", "memsz": 4096, "flags": "r",
         "status": "fault", "cause": "load_page_fault"},
        # Seg 4: VA=0x40000000, L2[1] 1GB gigapage RWX → OK
        {"vaddr": "0x40000000", "memsz": 4096, "flags": "rwx",
         "status": "ok", "pa": "0x80000000", "page_size": 1073741824},
    ],
}


# ═══════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def audit_output():
    """Run the audit tool once and cache the result."""
    return run_audit_tool()


# ═══════════════════════════════════════════════════════════════════
# Structural tests
# ═══════════════════════════════════════════════════════════════════

def test_tool_exists():
    """The audit tool must exist at /app/ptw_audit."""
    assert os.path.exists('/app/ptw_audit'), "/app/ptw_audit not found"


def test_output_has_required_fields(audit_output):
    """Output must contain satp_ppn, svade, and audits array."""
    assert 'satp_ppn' in audit_output
    assert 'svade' in audit_output
    assert 'audits' in audit_output
    assert isinstance(audit_output['audits'], list)
    assert len(audit_output['audits']) == 5, (
        f"Expected 5 audit entries, got {len(audit_output['audits'])}"
    )


# ═══════════════════════════════════════════════════════════════════
# Per-binary audit correctness
# ═══════════════════════════════════════════════════════════════════

def normalize_hex(s):
    """Normalize a hex string for comparison."""
    return hex(int(s, 16))


BINARY_NAMES = list(EXPECTED.keys())


@pytest.mark.parametrize("binary", BINARY_NAMES)
def test_binary_audit(audit_output, binary):
    """Verify each binary's segment audit results."""
    # Find the audit entry for this binary
    entry = None
    for a in audit_output['audits']:
        if a['binary'] == binary:
            entry = a
            break
    assert entry is not None, f"No audit entry found for {binary}"

    expected_segs = EXPECTED[binary]
    actual_segs = entry['segments']
    assert len(actual_segs) == len(expected_segs), (
        f"{binary}: expected {len(expected_segs)} segments, got {len(actual_segs)}"
    )

    for i, (actual, expected) in enumerate(zip(actual_segs, expected_segs)):
        # Check vaddr
        assert normalize_hex(actual['vaddr']) == expected['vaddr'], (
            f"{binary} seg {i}: vaddr {actual['vaddr']} != {expected['vaddr']}"
        )
        # Check memsz
        assert actual['memsz'] == expected['memsz'], (
            f"{binary} seg {i}: memsz {actual['memsz']} != {expected['memsz']}"
        )
        # Check flags
        assert actual['flags'] == expected['flags'], (
            f"{binary} seg {i}: flags '{actual['flags']}' != '{expected['flags']}'"
        )
        # Check status
        assert actual['status'] == expected['status'], (
            f"{binary} seg {i}: status '{actual['status']}' != '{expected['status']}'"
        )

        if expected['status'] == 'ok':
            assert normalize_hex(actual['pa']) == expected['pa'], (
                f"{binary} seg {i}: pa {actual['pa']} != {expected['pa']}"
            )
            assert actual['page_size'] == expected['page_size'], (
                f"{binary} seg {i}: page_size {actual['page_size']} != {expected['page_size']}"
            )
        else:
            assert actual['cause'] == expected['cause'], (
                f"{binary} seg {i}: cause '{actual['cause']}' != '{expected['cause']}'"
            )


# ═══════════════════════════════════════════════════════════════════
# Anti-hardcoding: sensitivity tests
# ═══════════════════════════════════════════════════════════════════

def test_privilege_sensitivity():
    """Change kern.elf to U-mode and verify seg 0 now faults.

    L0A[0] has U=0, so user-mode access must be denied. This proves
    the tool dynamically reads process_table.json rather than
    hardcoding results.
    """
    pt_path = '/app/process_table.json'
    with open(pt_path) as f:
        original = f.read()

    try:
        procs = json.loads(original)
        for p in procs:
            if p['binary'] == 'kern.elf':
                p['priv'] = 'U'
                break
        with open(pt_path, 'w') as f:
            json.dump(procs, f, indent=2)

        result = run_audit_tool()

        kern = None
        for a in result['audits']:
            if a['binary'] == 'kern.elf':
                kern = a
                break
        assert kern is not None, "kern.elf missing from modified output"

        seg0 = kern['segments'][0]
        assert seg0['status'] == 'fault', (
            "kern.elf seg 0 should fault when run in U-mode (page has U=0)"
        )
        assert seg0['cause'] == 'load_page_fault'
    finally:
        with open(pt_path, 'w') as f:
            f.write(original)


def test_mxr_sensitivity():
    """Disable MXR for monitor.elf and verify seg 0 now faults.

    L0A[3] is execute-only (R=0, X=1). Without MXR, read access to
    this page must fault. This proves the tool respects the MXR flag.
    """
    pt_path = '/app/process_table.json'
    with open(pt_path) as f:
        original = f.read()

    try:
        procs = json.loads(original)
        for p in procs:
            if p['binary'] == 'monitor.elf':
                p['mxr'] = False
                break
        with open(pt_path, 'w') as f:
            json.dump(procs, f, indent=2)

        result = run_audit_tool()

        monitor = None
        for a in result['audits']:
            if a['binary'] == 'monitor.elf':
                monitor = a
                break
        assert monitor is not None, "monitor.elf missing from modified output"

        seg0 = monitor['segments'][0]
        assert seg0['status'] == 'fault', (
            "monitor.elf seg 0 should fault without MXR (page is X-only, R=0)"
        )
        assert seg0['cause'] == 'load_page_fault'
    finally:
        with open(pt_path, 'w') as f:
            f.write(original)
