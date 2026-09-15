#!/usr/bin/env python3
"""Generate all task data for the KASAN crash analysis benchmark."""
import json
import os

def main():
    os.makedirs("/data/reports", exist_ok=True)

    create_reports()
    create_vm_results()
    create_experiment()
    create_schema()
    print("Data generation complete.")


def create_reports():
    """Create 5 KASAN crash report files covering different bug types."""

    # Report 1: slab-out-of-bounds Read
    # Tests: basic OOB, inline function in stack, allocation stack
    report_001 = """==================================================================
BUG: KASAN: slab-out-of-bounds in skb_network_protocol+0x12d/0x1a0 net/core/dev.c:3268
Read of size 2 at addr ffff88803a4c8594 by task syz-executor.0/5765

CPU: 0 UID: 0 PID: 5765 Comm: syz-executor.0 Not tainted 6.12.0-syzkaller #0
Hardware name: QEMU Standard PC (Q35 + ICH9, 2009), BIOS 1.16.3-debian-1.16.3-2 04/01/2014
Call Trace:
 <TASK>
 __dump_stack lib/dump_stack.c:94 [inline]
 dump_stack_lvl+0x100/0x190 lib/dump_stack.c:120
 print_report+0x156/0x4c9 mm/kasan/report.c:482
 kasan_report+0xdf/0x1e0 mm/kasan/report.c:595
 skb_network_protocol+0x12d/0x1a0 net/core/dev.c:3268
 skb_mac_gso_segment+0x2e4/0x5b0 net/core/gro.c:145
 __skb_gso_segment+0x3a5/0x780 net/core/gso.c:254
 validate_xmit_skb+0x567/0xf30 net/core/dev.c:3826
 __dev_queue_xmit+0x1269/0x3a10 net/core/dev.c:4425
 </TASK>

Allocated by task 5765:
 kasan_save_stack+0x30/0x50 mm/kasan/common.c:57
 kasan_save_track+0x14/0x30 mm/kasan/common.c:78
 __kasan_slab_alloc+0x89/0x90 mm/kasan/common.c:361
 slab_post_alloc_hook+0x44/0x4e0 mm/slub.c:4086
 __kmalloc_node_track_caller_noprof+0x2b3/0x480 mm/slub.c:5023
 __alloc_skb+0x2fb/0x770 net/core/skbuff.c:658

The buggy address belongs to the object at ffff88803a4c8580
 which belongs to the cache kmalloc-64 of size 64
The buggy address is located 0 bytes to the right of
 allocated 20-byte region [ffff88803a4c8580, ffff88803a4c8594)

Memory state around the buggy address:
 ffff88803a4c8480: fa fb fb fb fb fb fb fb fc fc fc fc fc fc fc fc
 ffff88803a4c8500: 00 00 00 00 00 00 00 00 fc fc fc fc fc fc fc fc
>ffff88803a4c8580: 00 00 04 fc fc fc fc fc fc fc fc fc fc fc fc fc
                         ^
 ffff88803a4c8600: fa fb fb fb fb fb fb fb fc fc fc fc fc fc fc fc
 ffff88803a4c8680: 00 00 00 00 00 00 00 00 fc fc fc fc fc fc fc fc
==================================================================
"""

    # Report 2: slab-use-after-free Read
    # Tests: UAF with both alloc AND free stacks, freed shadow bytes (fd)
    report_002 = """==================================================================
BUG: KASAN: slab-use-after-free in ext4_find_extent+0x1db/0x9f0 fs/ext4/extents.c:903
Read of size 8 at addr ffff888071a3e420 by task kworker/u8:3/1456

CPU: 2 UID: 0 PID: 1456 Comm: kworker/u8:3 Not tainted 6.12.0-rc3+ #1
Hardware name: QEMU Standard PC (i440FX + PIIX, 1996), BIOS 1.16.3-debian-1.16.3-2 04/01/2014
Call Trace:
 <TASK>
 dump_stack_lvl+0x100/0x190 lib/dump_stack.c:120
 print_report+0x156/0x4c9 mm/kasan/report.c:482
 kasan_report+0xdf/0x1e0 mm/kasan/report.c:595
 ext4_find_extent+0x1db/0x9f0 fs/ext4/extents.c:903
 ext4_ext_map_blocks+0x254/0x2c80 fs/ext4/extents.c:4238
 ext4_map_blocks+0x5aa/0xd80 fs/ext4/inode.c:567
 ext4_writepages+0x12e6/0x2fa0 fs/ext4/inode.c:2844
 </TASK>

Allocated by task 1200:
 kasan_save_stack+0x30/0x50 mm/kasan/common.c:57
 kasan_save_track+0x14/0x30 mm/kasan/common.c:78
 __kasan_slab_alloc+0x89/0x90 mm/kasan/common.c:361
 kmem_cache_alloc_noprof+0x1a3/0x510 mm/slub.c:4089
 ext4_ext_tree_init+0x94/0x1a0 fs/ext4/extents.c:812

Freed by task 1350:
 kasan_save_stack+0x30/0x50 mm/kasan/common.c:57
 kasan_save_track+0x14/0x30 mm/kasan/common.c:78
 kasan_save_free_info+0x3b/0x60 mm/kasan/generic.c:582
 __kasan_slab_free+0x10a/0x1b0 mm/kasan/common.c:270
 kmem_cache_free+0x1e2/0x470 mm/slub.c:4590
 ext4_ext_drop_refs+0xd8/0x140 fs/ext4/extents.c:780

The buggy address belongs to the object at ffff888071a3e400
 which belongs to the cache ext4_extent_status of size 72
The buggy address is located 32 bytes inside of
 freed 72-byte region [ffff888071a3e400, ffff888071a3e448)

Memory state around the buggy address:
 ffff888071a3e300: fa fb fb fb fb fb fb fb fb fc fc fc fc fc fc fc
 ffff888071a3e380: fa fb fb fb fb fb fb fb fb fc fc fc fc fc fc fc
>ffff888071a3e400: fd fd fd fd fd fd fd fd fd fc fc fc fc fc fc fc
                               ^
 ffff888071a3e480: fa fb fb fb fb fb fb fb fb fc fc fc fc fc fc fc
 ffff888071a3e500: 00 00 00 00 00 00 00 00 00 fc fc fc fc fc fc fc
==================================================================
"""

    # Report 3: null-ptr-deref Write
    # Tests: NPD, tainted kernel, no alloc/free stacks, inline function
    report_003 = """==================================================================
BUG: KASAN: null-ptr-deref in i2c_smbus_xfer+0x3a9/0x7c0 drivers/i2c/i2c-core-smbus.c:586
Write of size 4 at addr 0000000000000028 by task syz-executor.1/8823

CPU: 1 UID: 0 PID: 8823 Comm: syz-executor.1 Tainted: G           O 6.12.0-syzkaller #0
Hardware name: QEMU Standard PC (Q35 + ICH9, 2009), BIOS 1.16.3-debian-1.16.3-2 04/01/2014
Call Trace:
 <TASK>
 dump_stack_lvl+0x100/0x190 lib/dump_stack.c:120
 kasan_report+0xdf/0x1e0 mm/kasan/report.c:595
 check_memory_region_inline mm/kasan/generic.c:187 [inline]
 kasan_check_range+0xef/0x1a0 mm/kasan/generic.c:193
 i2c_smbus_xfer+0x3a9/0x7c0 drivers/i2c/i2c-core-smbus.c:586
 i2c_smbus_read_byte_data+0xa4/0xf0 drivers/i2c/i2c-core-smbus.c:284
 adm1025_detect+0x1c7/0x930 drivers/hwmon/adm1025.c:334
 i2c_detect+0x3cc/0x890 drivers/i2c/i2c-core-base.c:2382
 </TASK>
==================================================================
"""

    # Report 4: use-after-free Write (general, not slab-specific prefix)
    # Tests: IRQ+TASK sections, free stack without alloc stack, slab info still present
    report_004 = """==================================================================
BUG: KASAN: use-after-free in blk_mq_free_request+0x2a1/0x5e0 block/blk-mq.c:685
Write of size 8 at addr ffff88806b3a4e60 by task kworker/3:1/982

CPU: 3 UID: 0 PID: 982 Comm: kworker/3:1 Not tainted 6.12.0-rc5 #2
Hardware name: QEMU Standard PC (i440FX + PIIX, 1996), BIOS 1.16.3-debian-1.16.3-2 04/01/2014
Call Trace:
 <IRQ>
 dump_stack_lvl+0x100/0x190 lib/dump_stack.c:120
 print_report+0x156/0x4c9 mm/kasan/report.c:482
 kasan_report+0xdf/0x1e0 mm/kasan/report.c:595
 blk_mq_free_request+0x2a1/0x5e0 block/blk-mq.c:685
 blk_mq_end_request+0x38a/0x5d0 block/blk-mq.c:1048
 scsi_end_request+0x2b4/0x7e0 drivers/scsi/scsi_lib.c:587
 </IRQ>
 <TASK>
 scsi_io_completion+0x1bb/0x8c0 drivers/scsi/scsi_lib.c:956
 blk_complete_reqs+0xac/0xe0 block/blk-mq.c:1161
 </TASK>

Freed by task 899:
 kasan_save_stack+0x30/0x50 mm/kasan/common.c:57
 kasan_save_track+0x14/0x30 mm/kasan/common.c:78
 kasan_save_free_info+0x3b/0x60 mm/kasan/generic.c:582
 __kasan_slab_free+0x10a/0x1b0 mm/kasan/common.c:270
 kfree+0x12c/0x420 mm/slub.c:4580
 blk_mq_free_request+0x5a5/0x5e0 block/blk-mq.c:700

The buggy address belongs to the object at ffff88806b3a4e00
 which belongs to the cache kmalloc-192 of size 192
The buggy address is located 96 bytes inside of
 freed 192-byte region [ffff88806b3a4e00, ffff88806b3a4ec0)

Memory state around the buggy address:
 ffff88806b3a4d00: 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
 ffff88806b3a4d80: 00 00 00 00 00 00 00 00 fc fc fc fc fc fc fc fc
>ffff88806b3a4e00: fd fd fd fd fd fd fd fd fd fd fd fd fd fd fd fd
                                     ^
 ffff88806b3a4e80: fd fd fd fd fd fd fd fd fc fc fc fc fc fc fc fc
 ffff88806b3a4f00: 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
==================================================================
"""

    # Report 5: global-out-of-bounds Read
    # Tests: global variable info instead of slab, f9 global redzone bytes
    report_005 = """==================================================================
BUG: KASAN: global-out-of-bounds in ip6gre_header+0x489/0x5b0 net/ipv6/ip6_gre.c:963
Read of size 4 at addr ffffffff8eb1d2a4 by task syz-executor.2/9102

CPU: 0 UID: 0 PID: 9102 Comm: syz-executor.2 Not tainted 6.12.0-syzkaller #0
Hardware name: QEMU Standard PC (Q35 + ICH9, 2009), BIOS 1.16.3-debian-1.16.3-2 04/01/2014
Call Trace:
 <TASK>
 dump_stack_lvl+0x100/0x190 lib/dump_stack.c:120
 print_report+0x156/0x4c9 mm/kasan/report.c:482
 kasan_report+0xdf/0x1e0 mm/kasan/report.c:595
 ip6gre_header+0x489/0x5b0 net/ipv6/ip6_gre.c:963
 neigh_connected_output+0x302/0x430 net/core/neighbour.c:1563
 ip6_finish_output2+0xb67/0x1520 net/ipv6/ip6_output.c:137
 </TASK>

The buggy address belongs to the variable:
 ip6gre_protocol+0x24/0x40 at addr ffffffff8eb1d2a4

Memory state around the buggy address:
 ffffffff8eb1d180: 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
 ffffffff8eb1d200: 00 00 00 00 f9 f9 f9 f9 00 00 00 00 00 00 00 00
>ffffffff8eb1d280: 00 00 00 00 04 f9 f9 f9 f9 f9 f9 f9 00 00 00 00
                               ^
 ffffffff8eb1d300: 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
 ffffffff8eb1d380: 00 00 00 00 f9 f9 f9 f9 00 00 00 00 00 00 00 00
==================================================================
"""

    reports = {
        "report_001": report_001,
        "report_002": report_002,
        "report_003": report_003,
        "report_004": report_004,
        "report_005": report_005,
    }

    for name, content in reports.items():
        path = f"/data/reports/{name}.txt"
        with open(path, "w") as f:
            f.write(content.strip() + "\n")


def create_vm_results():
    """Create VM verification outcome test cases."""
    vm_results = {
        "case_001": {
            "bug_id": "bug_001",
            "patch_id": "patch_001a",
            "vm_results": ["pass"] * 26
        },
        "case_002": {
            "bug_id": "bug_002",
            "patch_id": "patch_002a",
            "vm_results": ["trigger"] * 26
        },
        "case_003": {
            "bug_id": "bug_003",
            "patch_id": "patch_003a",
            "vm_results": ["trigger"] * 20 + ["pass"] * 6
        },
        "case_004": {
            "bug_id": "bug_004",
            "patch_id": "patch_004a",
            "vm_results": ["pass"] * 13 + ["trigger"] * 13
        },
        "case_005": {
            "bug_id": "bug_005",
            "patch_id": "patch_005a",
            "vm_results": ["pass"] * 24 + ["boot_fail"] * 2
        },
        "case_006": {
            "bug_id": "bug_006",
            "patch_id": "patch_006a",
            "vm_results": ["trigger"] * 18 + ["pass"] * 6 + ["boot_fail"] * 2
        },
        "case_007": {
            "bug_id": "bug_007",
            "patch_id": "patch_007a",
            "vm_results": ["pass"] * 25 + ["trigger"] * 1
        },
        "case_008": {
            "bug_id": "bug_008",
            "patch_id": "patch_008a",
            "vm_results": ["trigger"] * 25 + ["pass"] * 1
        },
    }

    with open("/data/vm_results.json", "w") as f:
        json.dump(vm_results, f, indent=2)


def create_experiment():
    """Create a multi-configuration APR experiment dataset.

    Configurations:
      simple_agent_gpt4o:       solves bugs 1,3,7      (pass_rate=3/8=0.375)
      simple_agent_feedback:    solves bugs 2,3,4,5    (pass_rate=4/8=0.5)
      exploration_agent:        solves bugs 1,5,6      (pass_rate=3/8=0.375)

    Combined (union): {1,2,3,4,5,6,7} => 7/8 = 0.875
    Unique: gpt4o={7}, feedback={2,4}, exploration={6}
    """
    experiment = {
        "total_bugs": 8,
        "bugs": [
            "bug_001", "bug_002", "bug_003", "bug_004",
            "bug_005", "bug_006", "bug_007", "bug_008"
        ],
        "configs": {
            "simple_agent_gpt4o": {
                "cost_per_bug": 0.05,
                "results": {
                    "bug_001": {"verdict": "pass", "build_status": "success"},
                    "bug_002": {"verdict": "trigger", "build_status": "success"},
                    "bug_003": {"verdict": "pass", "build_status": "success"},
                    "bug_004": {"verdict": "racey", "build_status": "success"},
                    "bug_005": {"verdict": "boot_fail", "build_status": "success"},
                    "bug_006": {"verdict": "trigger", "build_status": "success"},
                    "bug_007": {"verdict": "pass", "build_status": "success"},
                    "bug_008": {"verdict": "trigger", "build_status": "compilation_fail"}
                }
            },
            "simple_agent_feedback": {
                "cost_per_bug": 0.17,
                "results": {
                    "bug_001": {"verdict": "trigger", "build_status": "success"},
                    "bug_002": {"verdict": "pass", "build_status": "success"},
                    "bug_003": {"verdict": "pass", "build_status": "success"},
                    "bug_004": {"verdict": "pass", "build_status": "success"},
                    "bug_005": {"verdict": "pass", "build_status": "success"},
                    "bug_006": {"verdict": "trigger", "build_status": "success"},
                    "bug_007": {"verdict": "racey", "build_status": "success"},
                    "bug_008": {"verdict": "trigger", "build_status": "bad_patch"}
                }
            },
            "exploration_agent": {
                "cost_per_bug": 0.12,
                "results": {
                    "bug_001": {"verdict": "pass", "build_status": "success"},
                    "bug_002": {"verdict": "trigger", "build_status": "success"},
                    "bug_003": {"verdict": "trigger", "build_status": "compilation_fail"},
                    "bug_004": {"verdict": "trigger", "build_status": "success"},
                    "bug_005": {"verdict": "pass", "build_status": "success"},
                    "bug_006": {"verdict": "pass", "build_status": "success"},
                    "bug_007": {"verdict": "trigger", "build_status": "success"},
                    "bug_008": {"verdict": "trigger", "build_status": "bad_patch"}
                }
            }
        }
    }

    with open("/data/experiment.json", "w") as f:
        json.dump(experiment, f, indent=2)


def create_schema():
    """Create the output schema specification."""
    schema = {
        "description": "Expected output format for the KASAN analysis framework",
        "output_file": "/app/output/report.json",
        "schema": {
            "parsed_reports": {
                "_description": "One entry per report file, keyed by report ID (filename without extension)",
                "_entry_schema": {
                    "bug_type": "string: one of [slab-out-of-bounds, slab-use-after-free, use-after-free, null-ptr-deref, global-out-of-bounds, stack-out-of-bounds, wild-memory-access, invalid-free]",
                    "access_type": "string or null: 'Read' or 'Write' (null only for invalid-free)",
                    "access_size": "int: number of bytes accessed (from 'Read/Write of size N')",
                    "faulting_function": "string: function name from BUG line (without +0x... suffix)",
                    "faulting_source_file": "string: source file path (e.g., 'net/core/dev.c')",
                    "faulting_source_line": "int: source line number",
                    "buggy_addr": "string: hex address without '0x' prefix (from 'at addr ...')",
                    "task_name": "string: task/process name (from 'by task NAME/PID')",
                    "pid": "int: process ID",
                    "cpu": "int: CPU number",
                    "tainted": "bool: true if kernel is tainted, false if 'Not tainted'",
                    "crash_stack": [
                        {
                            "function": "string: function name",
                            "file": "string: source file path",
                            "line": "int: line number",
                            "is_inline": "bool: true if [inline] marker present"
                        }
                    ],
                    "alloc_stack": "list of stack frames (same format) or null if no 'Allocated by' section",
                    "free_stack": "list of stack frames (same format) or null if no 'Freed by' section",
                    "slab_cache": "string or null: slab cache name (e.g., 'kmalloc-64', 'ext4_extent_status')",
                    "slab_object_size": "int or null: slab object size in bytes",
                    "alloc_size": "int or null: actual allocation size (from 'allocated/freed N-byte region')",
                    "global_variable": "string or null: global variable name (only for global-out-of-bounds)"
                }
            },
            "vm_verdicts": {
                "_description": "One entry per VM test case, keyed by case ID",
                "_entry_schema": {
                    "verdict": "string: one of [pass, trigger, racey, boot_fail]",
                    "vm_count": "int: total number of VMs",
                    "pass_count": "int: number of VMs that passed (no crash triggered)",
                    "trigger_count": "int: number of VMs where bug was triggered",
                    "boot_fail_count": "int: number of VMs that failed to boot",
                    "other_count": "int: number of VMs with other/unknown outcomes"
                }
            },
            "experiment_metrics": {
                "_description": "Aggregate metrics across APR configurations",
                "per_config": {
                    "_entry_schema": {
                        "pass_rate": "float: fraction of bugs with 'pass' verdict",
                        "pass_count": "int: number of bugs with 'pass' verdict",
                        "total_bugs": "int: total number of bugs evaluated",
                        "unique_solves": "list of bug IDs solved ONLY by this config (not by any other)",
                        "unique_solve_count": "int: length of unique_solves",
                        "avg_cost_per_bug": "float: average cost per bug for this config",
                        "compilation_fail_count": "int: number of bugs with compilation_fail build status",
                        "bad_patch_count": "int: number of bugs with bad_patch build status"
                    }
                },
                "combined_pass_rate": "float: fraction of bugs solved by ANY config (union)",
                "combined_pass_count": "int: number of bugs solved by at least one config",
                "combined_solved_bugs": "sorted list of bug IDs solved by any config",
                "total_bugs": "int: total number of bugs"
            }
        },
        "verdict_classification_rules": {
            "description": "Multi-VM verdict classification protocol",
            "rules": [
                "1. If ANY VM has 'boot_fail' outcome -> verdict is 'boot_fail'",
                "2. Count remaining outcomes as 'pass' or 'trigger' (ignore 'other')",
                "3. If all counted outcomes are 'pass' -> verdict is 'pass'",
                "4. If all counted outcomes are 'trigger' -> verdict is 'trigger'",
                "5. If mix of 'pass' and 'trigger' -> verdict is 'racey'",
                "6. If no 'pass' or 'trigger' outcomes and no 'boot_fail' -> verdict is 'other'"
            ]
        }
    }

    with open("/data/schema.json", "w") as f:
        json.dump(schema, f, indent=2)


if __name__ == "__main__":
    main()
