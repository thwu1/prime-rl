#!/usr/bin/env python3
"""
Generate dynamic test case for anti-cheat verification.
This case tests source-aware function extraction with a misleading hunk header.

"""

import os


def main():
    case_dir = "/app/data/cases/case_006"
    os.makedirs(f"{case_dir}/source/lib", exist_ok=True)

    # C source file with two functions: init_context and cleanup_context
    with open(f"{case_dir}/source/lib/test_helpers.c", "w") as f:
        f.write(
            "// SPDX-License-Identifier: GPL-2.0\n"
            "#include <linux/slab.h>\n"
            "#include <linux/module.h>\n"
            "\n"
            "struct ctx_data {\n"
            "    void *priv;\n"
            "    int refs;\n"
            "    char name[64];\n"
            "};\n"
            "\n"
            "int init_context(struct ctx_data *ctx, const char *name)\n"
            "{\n"
            "    if (!ctx || !name)\n"
            "        return -EINVAL;\n"
            "\n"
            "    ctx->priv = kmalloc(PAGE_SIZE, GFP_KERNEL);\n"
            "    if (!ctx->priv)\n"
            "        return -ENOMEM;\n"
            "\n"
            "    strscpy(ctx->name, name, sizeof(ctx->name));\n"
            "    ctx->refs = 1;\n"
            "\n"
            "    return 0;\n"
            "}\n"
            "\n"
            "/*\n"
            " * Release context and associated resources.\n"
            " * Called during module teardown.\n"
            " */\n"
            "void cleanup_context(struct ctx_data *ctx)\n"
            "{\n"
            "    ctx->refs--;\n"
            "    if (ctx->refs <= 0) {\n"
            "        kfree(ctx->priv);\n"
            "        ctx->priv = NULL;\n"
            "    }\n"
            '    /* BUG: accessing ctx->name after ctx may be freed */\n'
            '    pr_info("releasing context: %s", ctx->name);\n'
            "}\n"
        )

    # Crash report: KASAN use-after-free in cleanup_context
    with open(f"{case_dir}/crash_report.txt", "w") as f:
        f.write(
            "==================================================================\n"
            "BUG: KASAN: use-after-free in cleanup_context+0xb7/0x130 lib/test_helpers.c:38\n"
            "Read of size 64 at addr ffff88800d3a1a40 by task rmmod/5511\n"
            "\n"
            "CPU: 0 UID: 0 PID: 5511 Comm: rmmod Not tainted 6.12.0-syzkaller #0\n"
            "Hardware name: QEMU Standard PC (Q35 + ICH9, 2009), BIOS 1.16.3-debian-1.16.3-2 04/01/2014\n"
            "Call Trace:\n"
            " <TASK>\n"
            " dump_stack_lvl+0xe8/0x150 lib/dump_stack.c:120\n"
            " print_address_description+0x55/0x1e0 mm/kasan/report.c:378\n"
            " kasan_report+0x117/0x150 mm/kasan/report.c:595\n"
            " cleanup_context+0xb7/0x130 lib/test_helpers.c:38\n"
            " test_module_exit+0x34/0x80 lib/test_module.c:112\n"
            " do_syscall_64+0x15f/0xf80 arch/x86/entry/syscall_64.c:94\n"
            " entry_SYSCALL_64_after_hwframe+0x77/0x7f\n"
            " </TASK>\n"
            "==================================================================\n"
        )

    # Agent patch: hunk header misleadingly references init_context,
    # but the actual change is in cleanup_context
    with open(f"{case_dir}/agent_patch.diff", "w") as f:
        f.write(
            "diff --git a/lib/test_helpers.c b/lib/test_helpers.c\n"
            "index aaa1111..bbb2222 100644\n"
            "--- a/lib/test_helpers.c\n"
            "+++ b/lib/test_helpers.c\n"
            "@@ -28,7 +28,10 @@ int init_context(struct ctx_data *ctx, const char *name)\n"
            " * Called during module teardown.\n"
            " */\n"
            " void cleanup_context(struct ctx_data *ctx)\n"
            " {\n"
            "+    if (!ctx)\n"
            "+        return;\n"
            "+\n"
            "     ctx->refs--;\n"
            "     if (ctx->refs <= 0) {\n"
            "         kfree(ctx->priv);\n"
        )

    # Developer patch: identical content, different index hash
    with open(f"{case_dir}/developer_patch.diff", "w") as f:
        f.write(
            "diff --git a/lib/test_helpers.c b/lib/test_helpers.c\n"
            "index aaa1111..ccc3333 100644\n"
            "--- a/lib/test_helpers.c\n"
            "+++ b/lib/test_helpers.c\n"
            "@@ -28,7 +28,10 @@ int init_context(struct ctx_data *ctx, const char *name)\n"
            " * Called during module teardown.\n"
            " */\n"
            " void cleanup_context(struct ctx_data *ctx)\n"
            " {\n"
            "+    if (!ctx)\n"
            "+        return;\n"
            "+\n"
            "     ctx->refs--;\n"
            "     if (ctx->refs <= 0) {\n"
            "         kfree(ctx->priv);\n"
        )


if __name__ == "__main__":
    main()
