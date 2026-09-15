"""
Bug localization from KASAN crash report call stacks.

Identifies the most likely buggy function(s) by filtering out kernel
infrastructure code (KASAN reporting, memory allocator, scheduling,
architecture-specific entry points) and ranking remaining call stack
frames by their proximity to the crash site.
"""

from typing import List, Tuple
from .parser import KASANReport, StackFrame


# Prefixes of function names that are kernel infrastructure, not bug sources
INFRA_FUNCTION_PREFIXES = (
    # KASAN reporting
    "kasan_report", "kasan_save_stack", "kasan_save_track",
    "kasan_save_free_info", "kasan_check_", "kasan_kmalloc",
    "__kasan_kmalloc", "__kasan_slab_alloc", "__kasan_slab_free",
    "kasan_slab_alloc", "kasan_slab_free",
    "print_report", "print_address_description",
    # Stack dumping
    "__dump_stack", "dump_stack_lvl", "dump_stack",
    # Memory allocator internals
    "kmalloc_noprof", "__kmalloc_noprof", "__do_kmalloc_node",
    "kmem_cache_alloc_noprof", "kmem_cache_free",
    "slab_alloc_node", "slab_alloc", "slab_free",
    "slab_post_alloc_hook", "slab_free_hook",
    "poison_kmalloc_redzone",
    "__alloc_frozen_pages", "alloc_slab_page", "allocate_slab",
    "new_slab", "refill_objects", "refill_sheaf",
    "alloc_full_sheaf", "__pcs_replace_empty_main", "alloc_from_pcs",
    # Generic workqueue / scheduling
    "process_one_work", "process_scheduled_works",
    "worker_thread", "kthread",
    "ret_from_fork", "ret_from_fork_asm", "common_startup_64",
    # Timer / softirq infrastructure
    "__run_hrtimer", "__hrtimer_run_queues",
    "hrtimer_run_softirq", "handle_softirqs",
    "__do_softirq", "invoke_softirq",
    "__irq_exit_rcu", "irq_exit_rcu",
    "instr_sysvec_", "sysvec_apic_timer_interrupt",
    "asm_sysvec_",
    # Architecture-specific idle/entry
    "pv_native_safe_halt", "arch_safe_halt",
    "default_idle", "default_idle_call",
    "cpuidle_idle_call", "do_idle",
    "cpu_startup_entry", "start_secondary",
    # Driver probe infrastructure
    "call_driver_probe", "really_probe",
    "__driver_probe_device", "driver_probe_device",
    "__device_attach_driver", "__device_attach",
    "device_initial_probe", "bus_probe_device",
    "bus_for_each_drv", "device_add",
    # USB probe infrastructure (but NOT device-specific drivers)
    "usb_probe_interface", "usb_probe_device",
    "usb_generic_driver_probe", "usb_set_configuration",
    "usb_new_device",
    # Page allocation
    "get_page_from_freelist", "post_alloc_hook",
    "set_page_owner", "prep_new_page",
)

# Source file path prefixes that indicate infrastructure code
INFRA_FILE_PREFIXES = (
    "mm/kasan/",
    "mm/slub.c", "mm/slab.c", "mm/slab_common.c",
    "mm/page_alloc.c", "mm/shrinker.c", "mm/vmscan.c",
    "lib/dump_stack.c",
    "kernel/workqueue.c",
    "kernel/kthread.c",
    "kernel/softirq.c",
    "kernel/time/hrtimer.c",
    "kernel/sched/idle.c",
    "arch/x86/kernel/process.c",
    "arch/x86/kernel/smpboot.c",
    "arch/x86/entry/",
    "arch/x86/include/asm/idtentry.h",
    "arch/x86/include/asm/paravirt.h",
    "include/linux/kasan.h",
    "include/linux/slab.h",
    "drivers/base/dd.c",
    "drivers/base/bus.c",
    "drivers/base/core.c",
    "drivers/usb/core/driver.c",
    "drivers/usb/core/generic.c",
    "drivers/usb/core/message.c",
    "drivers/usb/core/hub.c",
    "drivers/usb/core/hcd.c",
)


def _is_infrastructure(frame: StackFrame) -> bool:
    """Check if a stack frame belongs to kernel infrastructure."""
    func = frame.function

    # Check function name prefixes
    for prefix in INFRA_FUNCTION_PREFIXES:
        if func == prefix or func.startswith(prefix):
            return True

    # Check source file paths
    if frame.source_file:
        for prefix in INFRA_FILE_PREFIXES:
            if frame.source_file.startswith(prefix):
                return True

    return False


def localize_bug(report: KASANReport) -> List[Tuple[str, str, int, float]]:
    """
    Given a KASAN report, identify the most likely buggy function(s).

    Returns list of (function, source_file, source_line, confidence) tuples,
    sorted by confidence (highest first).

    Confidence scoring:
    - The faulting function (from the BUG line) gets highest confidence
    - Subsequent non-infrastructure frames get decreasing confidence
    - Frames from allocation/free stacks get lower confidence
    """
    results = []
    seen_functions = set()

    # The faulting function from the BUG line is the primary candidate
    if not _is_infrastructure_name(report.faulting_function):
        results.append((
            report.faulting_function,
            report.source_file,
            report.source_line,
            1.0
        ))
        seen_functions.add(report.faulting_function)

    # Walk the call stack for additional candidates
    confidence = 0.9
    for frame in report.call_stack:
        if frame.function in seen_functions:
            continue
        if _is_infrastructure(frame):
            continue

        src_file = frame.source_file or ""
        src_line = frame.source_line or 0

        results.append((frame.function, src_file, src_line, confidence))
        seen_functions.add(frame.function)
        confidence *= 0.8
        if confidence < 0.05:
            break

    # For UAF bugs, also consider the free stack as it may contain the root cause
    if report.free_stack and report.bug_type in (
        "slab-use-after-free", "use-after-free"
    ):
        free_confidence = 0.6
        for frame in report.free_stack:
            if frame.function in seen_functions:
                continue
            if _is_infrastructure(frame):
                continue
            src_file = frame.source_file or ""
            src_line = frame.source_line or 0
            results.append((frame.function, src_file, src_line, free_confidence))
            seen_functions.add(frame.function)
            free_confidence *= 0.7
            if free_confidence < 0.05:
                break

    # Sort by confidence descending
    results.sort(key=lambda x: -x[3])

    return results


def _is_infrastructure_name(func_name: str) -> bool:
    """Check if a function name matches infrastructure patterns."""
    for prefix in INFRA_FUNCTION_PREFIXES:
        if func_name == prefix or func_name.startswith(prefix):
            return True
    return False
