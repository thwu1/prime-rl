#!/usr/bin/env python3
"""
ARM Cortex-M Exception State Diagnostic Solver

Parses CMEX v1 binary dump files, implements the ARMv7-M exception
priority model, and writes JSON result files.
"""

import json
import math
import os
import struct
import sys

RECORD_SIZE = 192
HEADER_SIZE = 8

EXC_NAMES = {
    1: "Reset", 2: "NMI", 3: "HardFault", 4: "MemManage",
    5: "BusFault", 6: "UsageFault", 10: "DebugMonitor",
    11: "SVCall", 14: "PendSV", 15: "SysTick",
}

FAULT_TYPES = [
    "UndefInstr", "InvState", "InvPC", "NoCP",
    "DAccViol", "IAccViol", "MUnstkErr", "MStkErr",
    "PreciseDataBusError", "ImpreciseDataBusError", "IBusErr",
    "UnstkErr", "StkErr",
]

FAULT_TO_EXC = {
    "UndefInstr": "UsageFault", "InvState": "UsageFault",
    "InvPC": "UsageFault", "NoCP": "UsageFault",
    "DAccViol": "MemManage", "IAccViol": "MemManage",
    "MUnstkErr": "MemManage", "MStkErr": "MemManage",
    "PreciseDataBusError": "BusFault", "ImpreciseDataBusError": "BusFault",
    "IBusErr": "BusFault", "UnstkErr": "BusFault", "StkErr": "BusFault",
}

EXC_NAME_TO_NUM = {v: k for k, v in EXC_NAMES.items()}


def exc_name(num):
    if num in EXC_NAMES:
        return EXC_NAMES[num]
    if num >= 16:
        return f"IRQ{num - 16}"
    return f"Reserved({num})"


def truncating_mod(a, b):
    """C/Rust-style truncating modulo."""
    if b == 0:
        return 0
    return int(math.fmod(a, b))


def parse_record(data):
    """Parse a 192-byte CMEX record into a dict."""
    assert len(data) == RECORD_SIZE

    # ID
    tc_id = data[0:32].split(b'\x00', 1)[0].decode('ascii')

    # Registers
    aircr = struct.unpack_from('<I', data, 0x20)[0]
    shpr1 = struct.unpack_from('<I', data, 0x24)[0]
    shpr2 = struct.unpack_from('<I', data, 0x28)[0]
    shpr3 = struct.unpack_from('<I', data, 0x2C)[0]

    prigroup = (aircr >> 8) & 0x7

    # Extract configured priorities from SHPR registers
    # SHPR1: exc 4 (byte0), 5 (byte1), 6 (byte2)
    # SHPR2: exc 10 (byte2), 11 (byte3)
    # SHPR3: exc 14 (byte2), 15 (byte3)
    configured_pri = {}
    configured_pri[4] = (shpr1 >> 0) & 0xFF   # MemManage
    configured_pri[5] = (shpr1 >> 8) & 0xFF   # BusFault
    configured_pri[6] = (shpr1 >> 16) & 0xFF  # UsageFault
    configured_pri[10] = (shpr2 >> 16) & 0xFF  # DebugMonitor
    configured_pri[11] = (shpr2 >> 24) & 0xFF  # SVCall
    configured_pri[14] = (shpr3 >> 16) & 0xFF  # PendSV
    configured_pri[15] = (shpr3 >> 24) & 0xFF  # SysTick

    basepri = data[0x30]
    primask = bool(data[0x31] & 1)
    faultmask = bool(data[0x32] & 1)
    control = data[0x33]
    fpca = bool(control & 0x04)

    # NVIC_IPR
    nvic_ipr = list(data[0x34:0x74])

    # Active exceptions
    num_active = data[0x74]
    active = []
    for i in range(min(num_active, 8)):
        en = data[0x75 + i * 2]
        pri = struct.unpack_from('b', data, 0x76 + i * 2)[0]
        active.append((en, pri))

    # Pending exceptions
    num_pending = data[0x85]
    pending = []
    for i in range(min(num_pending, 8)):
        en = data[0x86 + i * 2]
        pri = struct.unpack_from('b', data, 0x87 + i * 2)[0]
        pending.append((en, pri))

    # Fault enables
    usage_en = bool(data[0x96])
    bus_en = bool(data[0x97])
    mem_en = bool(data[0x98])

    arch = data[0x99]  # 6 or 7

    query_type = data[0x9A]
    query_params = data[0x9B:0x9F]

    return {
        'id': tc_id,
        'prigroup': prigroup,
        'basepri': basepri,
        'primask': primask,
        'faultmask': faultmask,
        'fpca': fpca,
        'active': active,
        'pending': pending,
        'fault_enables': {
            'UsageFault': usage_en,
            'BusFault': bus_en,
            'MemManage': mem_en,
        },
        'configured_pri': configured_pri,
        'nvic_ipr': nvic_ipr,
        'arch': arch,
        'query_type': query_type,
        'query_params': query_params,
    }


def calculate_execution_priority(rec, include_primask=True):
    """ARMv7-M ExecutionPriority() per DDI 0403E B1.5.4."""
    highestpri = 256
    boostedpri = 256
    subgroupshift = rec['prigroup']
    groupvalue = 2 << subgroupshift

    for (en, pri) in rec['active']:
        if pri < highestpri:
            highestpri = pri

            if en == 2:  # NMI
                groupvalue = -2
            if en == 3:  # HardFault
                groupvalue = -1

            subgroupvalue = truncating_mod(highestpri, groupvalue)
            highestpri = highestpri - subgroupvalue

    if rec['arch'] != 6 and rec['basepri'] != 0:
        boostedpri = rec['basepri']
        subgroupvalue = truncating_mod(boostedpri, groupvalue)
        boostedpri = boostedpri - subgroupvalue

    if include_primask and rec['primask']:
        boostedpri = 0

    if rec['arch'] != 6 and rec['faultmask']:
        boostedpri = -1

    return min(boostedpri, highestpri)


def get_pending_exception(rec):
    """Find highest-urgency pending exception that can preempt."""
    exec_pri = calculate_execution_priority(rec)

    selected_name = None
    selected_pri = 256
    selected_num = 999

    for (en, pri) in rec['pending']:
        if pri >= exec_pri:
            continue

        replace = False
        if selected_name is None:
            replace = True
        elif pri < selected_pri:
            replace = True
        elif pri == selected_pri and en < selected_num:
            replace = True

        if replace:
            selected_name = exc_name(en)
            selected_pri = pri
            selected_num = en

    return selected_name


def get_handler_priority(rec, handler_name):
    """Get the configured priority for a handler from SHPR/IPR."""
    en = EXC_NAME_TO_NUM.get(handler_name)
    if en is not None:
        return rec['configured_pri'].get(en, 0)
    return 0


def determine_fault_target(rec, fault_type_idx):
    """Determine fault handler, escalation, and lockup."""
    fault_type = FAULT_TYPES[fault_type_idx]
    arch = rec['arch']
    active_nums = {en for (en, _) in rec['active']}

    if arch == 6:
        # ARMv6-M: all faults go to HardFault
        if 3 in active_nums or 2 in active_nums:
            return {"handler": None, "escalated": True, "lockup": True}
        return {"handler": "HardFault", "escalated": False, "lockup": False}

    target = FAULT_TO_EXC.get(fault_type, "HardFault")
    escalated = False

    if target in ("UsageFault", "BusFault", "MemManage"):
        enabled = rec['fault_enables'].get(target, False)
        if not enabled:
            target = "HardFault"
            escalated = True
        else:
            # Check if handler priority can preempt current execution
            exec_pri = calculate_execution_priority(rec)
            handler_pri = get_handler_priority(rec, target)
            if handler_pri >= exec_pri:
                target = "HardFault"
                escalated = True

    if target == "HardFault":
        if 3 in active_nums or 2 in active_nums:
            return {"handler": None, "escalated": True, "lockup": True}

    return {"handler": target, "escalated": escalated, "lockup": False}


def validate_exc_return(rec, exc_return_value):
    """Validate EXC_RETURN encoding against active exception count."""
    n_active = len(rec['active'])
    low_bits = exc_return_value & 0xF

    if low_bits == 0x1:
        return n_active > 1
    elif low_bits == 0x9:
        return n_active == 1
    elif low_bits == 0xD:
        return n_active == 1
    else:
        return False


def get_stack_frame_size(rec):
    """32 bytes basic, 104 bytes with FP context."""
    return 104 if rec['fpca'] else 32


def check_wfi_wakeup(rec):
    """WFI wakeup: exclude PRIMASK, include FAULTMASK."""
    wakeup_priority = calculate_execution_priority(rec, include_primask=False)

    for (en, pri) in rec['pending']:
        if pri < wakeup_priority:
            return True
    return False


def process_record(rec):
    """Process a single record and return the result."""
    qt = rec['query_type']

    if qt == 1:
        return calculate_execution_priority(rec)
    elif qt == 2:
        return get_pending_exception(rec)
    elif qt == 3:
        fault_idx = rec['query_params'][0]
        return determine_fault_target(rec, fault_idx)
    elif qt == 4:
        er = struct.unpack_from('<I', bytes(rec['query_params']))[0]
        return validate_exc_return(rec, er)
    elif qt == 5:
        return get_stack_frame_size(rec)
    elif qt == 6:
        return check_wfi_wakeup(rec)
    else:
        raise ValueError(f"Unknown query type: {qt}")


def process_dump(filepath, results_dir):
    """Process a single CMEX dump file."""
    with open(filepath, 'rb') as f:
        header = f.read(HEADER_SIZE)
        if len(header) < HEADER_SIZE:
            raise ValueError("Truncated header")
        if header[0:4] != b'CMEX':
            raise ValueError("Invalid magic")

        num_records = struct.unpack_from('<H', header, 6)[0]

        results = {}
        for i in range(num_records):
            data = f.read(RECORD_SIZE)
            if len(data) < RECORD_SIZE:
                raise ValueError(f"Truncated record {i}")
            rec = parse_record(data)
            results[rec['id']] = process_record(rec)

    basename = os.path.splitext(os.path.basename(filepath))[0]
    out_path = os.path.join(results_dir, f"{basename}.json")
    with open(out_path, 'w') as f:
        json.dump(results, f, indent=2, sort_keys=True)


def main():
    dumps_dir = "/app/scs_dumps"
    results_dir = "/app/results"
    os.makedirs(results_dir, exist_ok=True)

    for filename in sorted(os.listdir(dumps_dir)):
        if not filename.endswith('.bin'):
            continue
        filepath = os.path.join(dumps_dir, filename)
        process_dump(filepath, results_dir)
        print(f"Processed {filename}")

    print("All dumps processed successfully.")


if __name__ == '__main__':
    main()
