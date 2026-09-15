#!/usr/bin/env python3
"""Generate CMEX binary dump files for ARM Cortex-M exception test scenarios.

Binary format: CMEX v1
- 8-byte file header
- N x 192-byte test case records

This script is run during Docker build to create /app/scs_dumps/*.bin
"""

import struct
import os

RECORD_SIZE = 192
HEADER_SIZE = 8

EXC_NUMS = {
    "Reset": 1, "NMI": 2, "HardFault": 3, "MemManage": 4,
    "BusFault": 5, "UsageFault": 6, "DebugMonitor": 10,
    "SVCall": 11, "PendSV": 14, "SysTick": 15,
}
FIXED_PRI = {"Reset": -3, "NMI": -2, "HardFault": -1}
FAULT_IDX = {
    "UndefInstr": 0, "InvState": 1, "InvPC": 2, "NoCP": 3,
    "DAccViol": 4, "IAccViol": 5, "MUnstkErr": 6, "MStkErr": 7,
    "PreciseDataBusError": 8, "ImpreciseDataBusError": 9,
    "IBusErr": 10, "UnstkErr": 11, "StkErr": 12,
}

def en(name):
    if name.startswith("IRQ"):
        return 16 + int(name[3:])
    return EXC_NUMS[name]

def sb(val):
    return struct.pack('b', val)[0]

def build_record(tc_id, arch, prigroup, basepri, primask, faultmask, fpca,
                 active, pending, fault_enables, exc_priorities,
                 query_type, query_params=None):
    rec = bytearray(RECORD_SIZE)

    # ID (32 bytes)
    idb = tc_id.encode('ascii')[:31]
    rec[0:len(idb)] = idb

    # AIRCR: PRIGROUP at bits [10:8]
    aircr = (prigroup & 0x7) << 8
    struct.pack_into('<I', rec, 0x20, aircr)

    # Collect all exception priorities for SHPR/IPR
    all_prios = dict(exc_priorities) if exc_priorities else {}
    for name, p in active:
        e = en(name)
        if e >= 4 and name not in FIXED_PRI:
            all_prios.setdefault(e, p)
    for name, p in pending:
        e = en(name)
        if e >= 4 and name not in FIXED_PRI:
            all_prios.setdefault(e, p)

    # SHPR1: exceptions 4-7 (byte 0=exc4, byte1=exc5, byte2=exc6, byte3=exc7)
    shpr1 = 0
    for i, eidx in enumerate([4, 5, 6, 7]):
        if eidx in all_prios:
            shpr1 |= (all_prios[eidx] & 0xFF) << (i * 8)
    struct.pack_into('<I', rec, 0x24, shpr1)

    # SHPR2: exceptions 8-11
    shpr2 = 0
    for i, eidx in enumerate([8, 9, 10, 11]):
        if eidx in all_prios:
            shpr2 |= (all_prios[eidx] & 0xFF) << (i * 8)
    struct.pack_into('<I', rec, 0x28, shpr2)

    # SHPR3: exceptions 12-15
    shpr3 = 0
    for i, eidx in enumerate([12, 13, 14, 15]):
        if eidx in all_prios:
            shpr3 |= (all_prios[eidx] & 0xFF) << (i * 8)
    struct.pack_into('<I', rec, 0x2C, shpr3)

    # Special registers
    rec[0x30] = basepri & 0xFF
    rec[0x31] = 1 if primask else 0
    rec[0x32] = 1 if faultmask else 0
    rec[0x33] = (1 << 2) if fpca else 0  # CONTROL bit 2 = FPCA

    # NVIC_IPR[0..63]
    for eidx, p in all_prios.items():
        if eidx >= 16:
            idx = eidx - 16
            if idx < 64:
                rec[0x34 + idx] = p & 0xFF

    # Active exceptions (max 8)
    rec[0x74] = len(active)
    for i, (name, p) in enumerate(active[:8]):
        e = en(name)
        pri = FIXED_PRI.get(name, p)
        rec[0x75 + i * 2] = e & 0xFF
        rec[0x76 + i * 2] = sb(pri)

    # Pending exceptions (max 8)
    rec[0x85] = len(pending)
    for i, (name, p) in enumerate(pending[:8]):
        e = en(name)
        pri = FIXED_PRI.get(name, p)
        rec[0x86 + i * 2] = e & 0xFF
        rec[0x87 + i * 2] = sb(pri)

    # Fault enables
    fe = fault_enables or {}
    rec[0x96] = 1 if fe.get('UsageFault') else 0
    rec[0x97] = 1 if fe.get('BusFault') else 0
    rec[0x98] = 1 if fe.get('MemManage') else 0

    # Architecture
    rec[0x99] = 6 if arch == 'armv6m' else 7

    # Query
    rec[0x9A] = query_type
    if query_params:
        plen = min(len(query_params), 4)
        rec[0x9B:0x9B + plen] = query_params[:plen]

    return bytes(rec)

def fault_param(fault_type):
    return bytes([FAULT_IDX[fault_type], 0, 0, 0])

def exc_return_param(val):
    return struct.pack('<I', val)

def write_dump(path, records):
    header = bytearray(HEADER_SIZE)
    header[0:4] = b'CMEX'
    header[4] = 1
    header[5] = 0
    struct.pack_into('<H', header, 6, len(records))
    with open(path, 'wb') as f:
        f.write(header)
        for r in records:
            f.write(r)

# ===== PRIORITY SCENARIOS =====
priority_records = [
    build_record("ep_no_active", "armv7m", 0, 0, False, False, False,
                 [], [], None, None, 1),
    build_record("ep_single_active_systick", "armv7m", 0, 0, False, False, False,
                 [("SysTick", 5)], [], None, None, 1),
    build_record("ep_hardfault_active", "armv7m", 0, 0, False, False, False,
                 [("HardFault", -1)], [], None, None, 1),
    build_record("ep_nmi_active", "armv7m", 0, 0, False, False, False,
                 [("NMI", -2)], [], None, None, 1),
    build_record("ep_prigroup3_systick24", "armv7m", 3, 0, False, False, False,
                 [("SysTick", 24)], [], None, None, 1),
    build_record("ep_primask_only", "armv7m", 0, 0, True, False, False,
                 [], [], None, None, 1),
    build_record("ep_faultmask_only", "armv7m", 0, 0, False, True, False,
                 [], [], None, None, 1),
    build_record("ep_basepri_32", "armv7m", 0, 32, False, False, False,
                 [], [], None, None, 1),
    build_record("ep_basepri_and_primask", "armv7m", 0, 32, True, False, False,
                 [], [], None, None, 1),
    build_record("ep_basepri_and_faultmask", "armv7m", 0, 32, False, True, False,
                 [], [], None, None, 1),
    build_record("ep_two_active_irq_lower", "armv7m", 0, 0, False, False, False,
                 [("SysTick", 5), ("IRQ0", 3)], [], None, None, 1),
    build_record("ep_basepri_with_prigroup2", "armv7m", 2, 37, False, False, False,
                 [], [], None, None, 1),
    build_record("ep_nmi_with_prigroup", "armv7m", 3, 0, False, False, False,
                 [("NMI", -2)], [], None, None, 1),
    build_record("ep_multi_active_prigroup", "armv7m", 2, 0, False, False, False,
                 [("SysTick", 20), ("IRQ0", 10)], [], None, None, 1),
]

# ===== PENDING SCENARIOS =====
pending_records = [
    build_record("pe_no_pending", "armv7m", 0, 0, False, False, False,
                 [], [], None, None, 2),
    build_record("pe_single_pending", "armv7m", 0, 0, False, False, False,
                 [], [("BusFault", 5)], None, None, 2),
    build_record("pe_multi_diff_priority", "armv7m", 0, 0, False, False, False,
                 [], [("SysTick", 3), ("BusFault", 1), ("IRQ0", 2)], None, None, 2),
    build_record("pe_same_priority_tiebreak", "armv7m", 0, 0, False, False, False,
                 [], [("UsageFault", 0), ("MemManage", 0), ("BusFault", 0)],
                 None, None, 2),
    build_record("pe_blocked_by_active", "armv7m", 0, 0, False, False, False,
                 [("SysTick", 2)], [("IRQ0", 3)], None, None, 2),
    build_record("pe_partially_blocked", "armv7m", 0, 0, False, False, False,
                 [("SysTick", 2)], [("IRQ0", 3), ("IRQ1", 1)], None, None, 2),
    build_record("pe_primask_allows_hardfault", "armv7m", 0, 0, True, False, False,
                 [], [("SysTick", 0), ("HardFault", -1)], None, None, 2),
    build_record("pe_faultmask_allows_nmi", "armv7m", 0, 0, False, True, False,
                 [], [("HardFault", -1), ("NMI", -2)], None, None, 2),
]

# ===== ESCALATION SCENARIOS =====
_fe_all = {"UsageFault": True, "BusFault": True, "MemManage": True}
escalation_records = [
    build_record("fe_usage_enabled", "armv7m", 0, 0, False, False, False,
                 [], [], _fe_all, None, 3, fault_param("UndefInstr")),
    build_record("fe_usage_disabled", "armv7m", 0, 0, False, False, False,
                 [], [],
                 {"UsageFault": False, "BusFault": True, "MemManage": True},
                 None, 3, fault_param("UndefInstr")),
    build_record("fe_memmanage_enabled", "armv7m", 0, 0, False, False, False,
                 [], [], _fe_all, None, 3, fault_param("DAccViol")),
    build_record("fe_memmanage_disabled", "armv7m", 0, 0, False, False, False,
                 [], [],
                 {"UsageFault": True, "BusFault": True, "MemManage": False},
                 None, 3, fault_param("DAccViol")),
    build_record("fe_busfault_enabled", "armv7m", 0, 0, False, False, False,
                 [], [], _fe_all, None, 3, fault_param("PreciseDataBusError")),
    build_record("fe_lockup_in_hardfault", "armv7m", 0, 0, False, False, False,
                 [("HardFault", -1)], [], _fe_all, None, 3, fault_param("UndefInstr")),
    build_record("fe_lockup_in_nmi", "armv7m", 0, 0, False, False, False,
                 [("NMI", -2)], [], _fe_all, None, 3, fault_param("UndefInstr")),
    build_record("fe_armv6m_hardfault", "armv6m", 0, 0, False, False, False,
                 [], [], {}, None, 3, fault_param("UndefInstr")),
    build_record("fe_enabled_cant_preempt", "armv7m", 0, 0, False, False, False,
                 [("SysTick", 2)], [], _fe_all,
                 {en("UsageFault"): 5, en("SysTick"): 2},
                 3, fault_param("UndefInstr")),
]

# ===== MISC SCENARIOS =====
misc_records = [
    build_record("sf_basic_frame", "armv7m", 0, 0, False, False, False,
                 [], [], None, None, 5),
    build_record("sf_extended_fp_frame", "armv7m", 0, 0, False, False, True,
                 [], [], None, None, 5),
    build_record("er_handler_single_active", "armv7m", 0, 0, False, False, False,
                 [("SysTick", 5)], [], None, None,
                 4, exc_return_param(0xFFFFFFF1)),
    build_record("er_handler_two_active", "armv7m", 0, 0, False, False, False,
                 [("HardFault", -1), ("SysTick", 5)], [], None, None,
                 4, exc_return_param(0xFFFFFFF1)),
    build_record("er_thread_msp_single", "armv7m", 0, 0, False, False, False,
                 [("SysTick", 5)], [], None, None,
                 4, exc_return_param(0xFFFFFFF9)),
    build_record("er_thread_psp_single", "armv7m", 0, 0, False, False, False,
                 [("SysTick", 5)], [], None, None,
                 4, exc_return_param(0xFFFFFFFD)),
    build_record("er_thread_two_active", "armv7m", 0, 0, False, False, False,
                 [("HardFault", -1), ("SysTick", 5)], [], None, None,
                 4, exc_return_param(0xFFFFFFF9)),
    build_record("er_invalid_encoding", "armv7m", 0, 0, False, False, False,
                 [("SysTick", 5)], [], None, None,
                 4, exc_return_param(0xFFFFFF00)),
    build_record("wfi_primask_wakes", "armv7m", 0, 0, True, False, False,
                 [], [("IRQ0", 10)], None, None, 6),
    build_record("wfi_no_pending", "armv7m", 0, 0, False, False, False,
                 [], [], None, None, 6),
    build_record("wfi_low_priority_no_wake", "armv7m", 0, 0, False, False, False,
                 [("SysTick", 0)], [("IRQ0", 10)], None, None, 6),
    build_record("wfi_faultmask_blocks", "armv7m", 0, 0, False, True, False,
                 [], [("IRQ0", 10)], None, None, 6),
]

if __name__ == '__main__':
    outdir = '/app/scs_dumps'
    os.makedirs(outdir, exist_ok=True)

    write_dump(os.path.join(outdir, 'priority.bin'), priority_records)
    write_dump(os.path.join(outdir, 'pending.bin'), pending_records)
    write_dump(os.path.join(outdir, 'escalation.bin'), escalation_records)
    write_dump(os.path.join(outdir, 'misc.bin'), misc_records)

    print(f"Generated {len(priority_records)} priority, {len(pending_records)} pending, "
          f"{len(escalation_records)} escalation, {len(misc_records)} misc records")
