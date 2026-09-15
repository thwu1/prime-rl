#!/usr/bin/env python3
"""Generate task data files for the kernel crash analysis pipeline task."""
import os
import json


def main():
    os.makedirs('/app/data/crash_reports', exist_ok=True)
    os.makedirs('/app/data/receipts', exist_ok=True)
    os.makedirs('/app/data/patches', exist_ok=True)

    # --- Crash Report 1: KASAN slab-use-after-free ---
    with open('/app/data/crash_reports/crash_001.txt', 'w') as f:
        f.write("==================================================================\n"
                "BUG: KASAN: slab-use-after-free in sock_release+0x1c8/0x200\n"
                "Read of size 8 at addr ffff888012345678 by task syz-executor.0/1234\n"
                "\n"
                "CPU: 2 PID: 1234 Comm: syz-executor.0 Not tainted 6.1.0-rc5-syzkaller #0\n"
                "Hardware name: Google Google Compute Engine/Google Compute Engine, BIOS Google 10/26/2022\n"
                "Call Trace:\n"
                " <TASK>\n"
                " dump_stack_levels+0x1c/0x30\n"
                " print_report+0x171/0x473\n"
                " kasan_report+0xb6/0x130\n"
                " sock_release+0x1c8/0x200\n"
                " __sk_destruct+0x45/0x90\n"
                " sock_def_wakeup+0x78/0x100\n"
                " sk_free+0x22/0x40\n"
                " kfree+0x102/0x150\n"
                " </TASK>\n"
                "\n"
                "Allocated by task 5678:\n"
                " kasan_save_stack+0x1e/0x40\n"
                " __kasan_kmalloc+0x7a/0x90\n"
                " sk_alloc+0x56/0x80\n"
                " inet_create+0x2c4/0x3e0\n"
                "\n"
                "Freed by task 9012:\n"
                " kasan_save_stack+0x1e/0x40\n"
                " kasan_save_free_info+0x2a/0x40\n"
                " __kasan_slab_free+0x100/0x170\n"
                " sk_free_unlock+0x34/0x60\n"
                "\n"
                "The buggy address belongs to the object at ffff888012345600\n"
                " which belongs to the cache sock_inode_cache of size 1152\n"
                "The buggy address is located 120 bytes inside of\n"
                " freed 1152-byte region [ffff888012345600, ffff888012345a80)\n"
                "==================================================================\n")

    # --- Crash Report 2: KASAN slab-out-of-bounds ---
    with open('/app/data/crash_reports/crash_002.txt', 'w') as f:
        f.write("==================================================================\n"
                "BUG: KASAN: slab-out-of-bounds in ext4_getattr+0x3a4/0x500\n"
                "Write of size 4 at addr ffff888087654321 by task stat/5678\n"
                "\n"
                "CPU: 0 PID: 5678 Comm: stat Tainted: G        W         6.2.0-rc3 #1\n"
                "Hardware name: QEMU Standard PC (i440FX + PIIX, 1996), BIOS 1.15.0-1 04/01/2014\n"
                "Call Trace:\n"
                " <TASK>\n"
                " dump_stack_levels+0x1c/0x30\n"
                " print_report+0x171/0x473\n"
                " kasan_report+0xb6/0x130\n"
                " ext4_getattr+0x3a4/0x500\n"
                " ext4_inode_table+0x12/0x30\n"
                " vfs_getattr+0x56/0x80\n"
                " generic_fillattr+0x78/0xa0\n"
                " stat_init+0x34/0x60\n"
                " </TASK>\n"
                "\n"
                "Allocated by task 5678:\n"
                " kasan_save_stack+0x1e/0x40\n"
                " __kasan_kmalloc+0x7a/0x90\n"
                " ext4_iget+0x56/0x80\n"
                " ext4_lookup+0x23/0x40\n"
                "\n"
                "The buggy address belongs to the object at ffff888087654300\n"
                " which belongs to the cache ext4_inode_cache of size 1408\n"
                "The buggy address is located 33 bytes inside of\n"
                " allocated 1408-byte region [ffff888087654300, ffff888087654880)\n"
                "==================================================================\n")

    # --- Crash Report 3: General protection fault ---
    with open('/app/data/crash_reports/crash_003.txt', 'w') as f:
        f.write("general protection fault, probably for non-canonical address 0xdead000000000108: 0000 [#1] PREEMPT SMP KASAN\n"
                "CPU: 3 PID: 3456 Comm: syz-executor.2 Not tainted 6.3.0-syzkaller #0\n"
                "Hardware name: Google Google Compute Engine/Google Compute Engine, BIOS Google 03/15/2023\n"
                "RIP: 0010:tcp_v4_rcv+0x1a7/0x2b0\n"
                "Code: 48 89 e5 41 57 41 56 41 55 41 54 49 89 fc 53 48 83 ec 28 65 48 8b 04 25 28 00 00 00 48 89 45 d0 31 c0 e8 ab cd ef 01\n"
                "RSP: 0018:ffffc90001234560 EFLAGS: 00010282\n"
                "RAX: dead000000000100 RBX: ffff888012340000 RCX: ffffffff81234567\n"
                "RDX: 0000000000000000 RSI: ffffffff82345678 RDI: ffff888012340100\n"
                "RBP: ffffc900012345a0 R08: 0000000000000001 R09: fffffbfff0468acf\n"
                "R10: ffffffff8234567f R11: 0000000000000000 R12: ffff888012340200\n"
                "R13: dffffc0000000000 R14: ffff888012340300 R15: ffff888012340400\n"
                "FS:  0000555556789000(0000) GS:ffff8880b9c00000(0000) knlGS:0000000000000000\n"
                "CS:  0010 DS: 0000 ES: 0000 CR0: 0000000080050033\n"
                "CR2: 00007f1234567890 CR3: 0000000012340000 CR4: 00000000003506f0\n"
                "DR0: 0000000000000000 DR1: 0000000000000000 DR2: 0000000000000000\n"
                "Call Trace:\n"
                " <TASK>\n"
                " tcp_v4_rcv+0x1a7/0x2b0\n"
                " ip_protocol_deliver_rcu+0x45/0x90\n"
                " ip_local_deliver+0x78/0x100\n"
                " ip_rcv+0x22/0x40\n"
                " netif_receive_skb+0x102/0x150\n"
                " </TASK>\n")

    # --- Crash Report 4: WARNING ---
    with open('/app/data/crash_reports/crash_004.txt', 'w') as f:
        f.write("------------[ cut here ]------------\n"
                "WARNING: CPU: 1 PID: 7890 at kernel/sched/core.c:3456 __schedule+0x789/0x1200\n"
                "Modules linked in: snd_hda_intel(+) snd_hda_codec_realtek\n"
                "CPU: 1 PID: 7890 Comm: kworker/1:3 Tainted: G        W         6.1.0-rc5 #1\n"
                "Hardware name: QEMU Standard PC (Q35 + ICH9, 2009), BIOS 1.15.0-1 04/01/2014\n"
                "RIP: 0010:__schedule+0x789/0x1200\n"
                "Code: 48 89 e5 41 57 41 56 41 55 41 54 49 89 fc 53 48 83 ec 28 65 48 8b 04 25 28 00 00 00 48 89 45 d0 31 c0 48 8d 7d d0\n"
                "RSP: 0018:ffffc90009876543 EFLAGS: 00010246\n"
                "RAX: 0000000000000000 RBX: ffff888098760000 RCX: ffffffff81987654\n"
                "RDX: dffffc0000000000 RSI: 0000000000000000 RDI: ffff888098760100\n"
                "RBP: ffffc90009876580 R08: 0000000000000000 R09: 0000000000000000\n"
                "R10: ffffffff82345678 R11: 0000000000000000 R12: ffff888098760200\n"
                "R13: dffffc0000000000 R14: ffff888098760300 R15: ffff888098760400\n"
                "FS:  0000000000000000(0000) GS:ffff8880b9d00000(0000) knlGS:0000000000000000\n"
                "CS:  0010 DS: 0000 ES: 0000 CR0: 0000000080050033\n"
                "Call Trace:\n"
                " <TASK>\n"
                " __schedule+0x789/0x1200\n"
                " schedule+0x56/0xd0\n"
                " schedule_timeout+0x12/0x30\n"
                " do_nanosleep+0x78/0xa0\n"
                " hrtimer_nanosleep+0x34/0x60\n"
                " </TASK>\n")

    # --- Crash Report 5: KASAN slab-use-after-free variant ---
    with open('/app/data/crash_reports/crash_005.txt', 'w') as f:
        f.write("==================================================================\n"
                "BUG: KASAN: slab-use-after-free in sock_release+0x1d0/0x200\n"
                "Read of size 4 at addr ffff888023456789 by task syz-executor.3/2345\n"
                "\n"
                "CPU: 1 PID: 2345 Comm: syz-executor.3 Not tainted 6.1.0-rc5-syzkaller #0\n"
                "Hardware name: Google Google Compute Engine/Google Compute Engine, BIOS Google 10/26/2022\n"
                "Call Trace:\n"
                " <TASK>\n"
                " dump_stack_levels+0x1c/0x30\n"
                " print_report+0x171/0x473\n"
                " kasan_report+0xb6/0x130\n"
                " sock_release+0x1d0/0x200\n"
                " __sk_destruct+0x48/0x90\n"
                " sock_def_wakeup+0x7c/0x100\n"
                " sk_free+0x24/0x40\n"
                " sk_clone_lock+0x56/0x80\n"
                " </TASK>\n"
                "\n"
                "Allocated by task 6789:\n"
                " kasan_save_stack+0x1e/0x40\n"
                " __kasan_kmalloc+0x7a/0x90\n"
                " sk_alloc+0x58/0x80\n"
                " inet6_create+0x2d0/0x400\n"
                "\n"
                "Freed by task 1011:\n"
                " kasan_save_stack+0x1e/0x40\n"
                " kasan_save_free_info+0x2a/0x40\n"
                " __kasan_slab_free+0x100/0x170\n"
                " sk_release_cb+0x34/0x60\n"
                "\n"
                "The buggy address belongs to the object at ffff888023456700\n"
                " which belongs to the cache sock_inode_cache of size 1152\n"
                "The buggy address is located 137 bytes inside of\n"
                " freed 1152-byte region [ffff888023456700, ffff888023456b80)\n"
                "==================================================================\n")

    # --- Receipt 1 ---
    receipt_1 = {
        "jobs": [
            {"bug_id": "net_sock_uaf__0", "execution": {"message": "no crash reproduced", "crash_description": None}},
            {"bug_id": "ext4_oob__0", "execution": {"message": None, "crash_description": "BUG: KASAN: slab-out-of-bounds in ext4_getattr+0x3a4/0x500"}},
            {"bug_id": "tcp_gpf__0", "execution": {"message": "no crash reproduced", "crash_description": None}},
            {"bug_id": "sched_warn__0", "execution": {"message": "compilation error", "crash_description": None}},
            {"bug_id": "net_clone_uaf__0", "execution": {"message": "no crash reproduced", "crash_description": None}}
        ]
    }
    with open('/app/data/receipts/receipt_1.json', 'w') as f:
        json.dump(receipt_1, f, indent=2)

    # --- Receipt 2 ---
    receipt_2 = {
        "jobs": [
            {"bug_id": "net_sock_uaf__0", "execution": {"message": "no crash reproduced", "crash_description": None}},
            {"bug_id": "tcp_gpf__0", "execution": {"message": "no crash reproduced", "crash_description": None}},
            {"bug_id": "net_clone_uaf__0", "execution": {"message": None, "crash_description": "BUG: KASAN: slab-use-after-free in sock_release+0x1d0/0x200"}}
        ]
    }
    with open('/app/data/receipts/receipt_2.json', 'w') as f:
        json.dump(receipt_2, f, indent=2)

    # --- Receipt 3 ---
    receipt_3 = {
        "jobs": [
            {"bug_id": "net_sock_uaf__0", "execution": {"message": "no crash reproduced", "crash_description": None}},
            {"bug_id": "tcp_gpf__0", "execution": {"message": "no crash reproduced", "crash_description": None}}
        ]
    }
    with open('/app/data/receipts/receipt_3.json', 'w') as f:
        json.dump(receipt_3, f, indent=2)

    # --- Patch file ---
    with open('/app/data/patches/patch_net_sock.patch', 'w') as f:
        f.write("diff --git a/net/core/sock.c b/net/core/sock.c\n"
                "index abc1234..def5678 100644\n"
                "--- a/net/core/sock.c\n"
                "+++ b/net/core/sock.c\n"
                "@@ -1800,6 +1800,9 @@ void sock_release(struct socket *sock)\n"
                " \tstruct sock *sk = sock->sk;\n"
                "-\tsk_free(sk);\n"
                "+\tif (sk) {\n"
                "+\t\tsock_orphan(sk);\n"
                "+\t\tsk_free(sk);\n"
                "+\t}\n"
                " \tsock->sk = NULL;\n"
                "diff --git a/net/core/filter.c b/net/core/filter.c\n"
                "index 1112223..3334445 100644\n"
                "--- a/net/core/filter.c\n"
                "+++ b/net/core/filter.c\n"
                "@@ -100,4 +100,6 @@ int sk_attach_filter(struct sock *sk, struct sock_fprog *fprog)\n"
                " \tret = __sk_attach_prog(fprog, sk);\n"
                "+\tif (ret < 0)\n"
                "+\t\tsk_filter_release(sk);\n"
                " \treturn ret;\n")


if __name__ == '__main__':
    main()
