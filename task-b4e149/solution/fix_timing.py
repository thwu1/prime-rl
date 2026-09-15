#!/usr/bin/env python3
"""
Fix all timing bugs in the evrecord/evreplay/evanalyze toolkit,
install the evaudit validation tool, and update the Makefile.


Bug fixes:
1. evrecord.c: Replace time(NULL) with gettimeofday() for ref_stamp init
2. evrecord.c: Move gettimeofday() from before read() to after it returns
3. evreplay.c: Remove prev_blk byte-count shifting compensation hack
4. evanalyze.c: Remove skip-first-entry workaround

Plus:
5. Install evaudit.c into /app/src/
6. Update Makefile to build evaudit
"""

import os
import shutil


def fix_evrecord():
    """Fix two timing bugs in evrecord.c."""
    path = "/app/src/evrecord.c"
    with open(path) as f:
        src = f.read()

    # Bug 1: Replace time(NULL) initialization with gettimeofday()
    old_init = "    double ref_stamp = time(NULL);"
    new_init = (
        "    double ref_stamp;\n"
        "    {\n"
        "        struct timeval init_tv;\n"
        "        gettimeofday(&init_tv, NULL);\n"
        "        ref_stamp = init_tv.tv_sec + (double)init_tv.tv_usec / 1000000;\n"
        "    }"
    )
    assert old_init in src, "Could not find time(NULL) initialization in evrecord.c"
    src = src.replace(old_init, new_init)

    # Bug 2: Move gettimeofday() from before read() to after it returns
    old_sample = (
        "        /* Sample the clock for this iteration's timing measurement */\n"
        "        gettimeofday(&tv, NULL);\n"
        "\n"
        "        /* Wait for data from the child process */"
    )
    new_sample = "        /* Wait for data from the child process */"
    assert old_sample in src, "Could not find gettimeofday-before-read in evrecord.c"
    src = src.replace(old_sample, new_sample)

    old_compute = (
        "        /* Compute the time delta from our reference point */\n"
        "        cur_stamp = tv.tv_sec + (double)tv.tv_usec / 1000000;"
    )
    new_compute = (
        "        /* Sample clock after data arrives */\n"
        "        gettimeofday(&tv, NULL);\n"
        "\n"
        "        /* Compute the time delta from our reference point */\n"
        "        cur_stamp = tv.tv_sec + (double)tv.tv_usec / 1000000;"
    )
    assert old_compute in src, "Could not find delta computation in evrecord.c"
    src = src.replace(old_compute, new_compute)

    with open(path, "w") as f:
        f.write(src)
    print(f"Fixed {path}: timing initialization and gettimeofday placement")


def fix_evreplay():
    """Remove the prev_blk compensation hack from evreplay.c."""
    path = "/app/src/evreplay.c"
    with open(path) as f:
        src = f.read()

    old_func = (
        "static int replay_session(FILE *ftiming, FILE *fdata, double speed)\n"
        "{\n"
        "    double delay;\n"
        "    size_t blk;\n"
        "    size_t prev_blk = 0;\n"
        "    int entry_num = 0;\n"
        "\n"
        "    skip_header(fdata);\n"
        "\n"
        "    while (fscanf(ftiming, \"%lf %zu\", &delay, &blk) == 2) {\n"
        "        entry_num++;\n"
        "\n"
        "        /* Apply speed factor to delay */\n"
        "        double adjusted_delay = delay / speed;\n"
        "\n"
        "        /* Wait for the specified delay */\n"
        "        if (adjusted_delay > 0.001) {\n"
        "            delay_for(adjusted_delay);\n"
        "        }\n"
        "\n"
        "        /*\n"
        "         * Emit the data chunk from the previous timing entry.\n"
        "         * The recording has a known one-pass shift in its timing data:\n"
        "         * each delay value actually corresponds to the data chunk from\n"
        "         * the previous iteration. We compensate by using prev_blk\n"
        "         * instead of the current blk.\n"
        "         */\n"
        "        if (prev_blk > 0) {\n"
        "            if (emit_bytes(fdata, prev_blk) < 0)\n"
        "                return -1;\n"
        "        }\n"
        "\n"
        "        prev_blk = blk;\n"
        "    }\n"
        "\n"
        "    /* Emit the final chunk (from the last iteration) without delay */\n"
        "    if (prev_blk > 0) {\n"
        "        if (emit_bytes(fdata, prev_blk) < 0)\n"
        "            return -1;\n"
        "    }\n"
        "\n"
        "    return 0;\n"
        "}"
    )

    new_func = (
        "static int replay_session(FILE *ftiming, FILE *fdata, double speed)\n"
        "{\n"
        "    double delay;\n"
        "    size_t blk;\n"
        "\n"
        "    skip_header(fdata);\n"
        "\n"
        "    while (fscanf(ftiming, \"%lf %zu\", &delay, &blk) == 2) {\n"
        "        double adjusted_delay = delay / speed;\n"
        "\n"
        "        if (adjusted_delay > 0.001) {\n"
        "            delay_for(adjusted_delay);\n"
        "        }\n"
        "\n"
        "        if (emit_bytes(fdata, blk) < 0)\n"
        "            return -1;\n"
        "    }\n"
        "\n"
        "    return 0;\n"
        "}"
    )

    assert old_func in src, "Could not find replay_session function in evreplay.c"
    src = src.replace(old_func, new_func)

    with open(path, "w") as f:
        f.write(src)
    print(f"Fixed {path}: removed prev_blk compensation hack")


def fix_evanalyze():
    """Remove the skip-first-entry workaround from evanalyze.c."""
    path = "/app/src/evanalyze.c"
    with open(path) as f:
        src = f.read()

    old_block = (
        "        if (st->total_entries == 1) {\n"
        "            st->first_delay = delay;\n"
        "            /*\n"
        "             * Skip the first timing entry for statistical analysis.\n"
        "             * The recorder's initialization introduces a systematic\n"
        "             * offset in the first entry that would skew the results.\n"
        "             */\n"
        "            continue;\n"
        "        }"
    )

    new_block = (
        "        if (st->total_entries == 1) {\n"
        "            st->first_delay = delay;\n"
        "        }"
    )

    assert old_block in src, "Could not find skip-first-entry block in evanalyze.c"
    src = src.replace(old_block, new_block)

    with open(path, "w") as f:
        f.write(src)
    print(f"Fixed {path}: removed first-entry skip workaround")


def install_evaudit():
    """Copy evaudit.c into the project source directory."""
    shutil.copy("/solution/evaudit.c", "/app/src/evaudit.c")
    print("Installed /app/src/evaudit.c")


def update_makefile():
    """Add evaudit build target to the Makefile."""
    path = "/app/Makefile"
    with open(path) as f:
        src = f.read()

    # Add evaudit to PROGRAMS list
    old_programs = "PROGRAMS = $(BINDIR)/evrecord $(BINDIR)/evreplay $(BINDIR)/evanalyze"
    new_programs = "PROGRAMS = $(BINDIR)/evrecord $(BINDIR)/evreplay $(BINDIR)/evanalyze $(BINDIR)/evaudit"
    assert old_programs in src, "Could not find PROGRAMS line in Makefile"
    src = src.replace(old_programs, new_programs)

    # Append evaudit build rule
    evaudit_rule = (
        "\n$(BINDIR)/evaudit: $(SRCDIR)/evaudit.c $(SRCDIR)/common.h\n"
        "\t$(CC) $(CFLAGS) -o $@ $<\n"
    )
    src += evaudit_rule

    with open(path, "w") as f:
        f.write(src)
    print(f"Updated {path}: added evaudit build target")


if __name__ == "__main__":
    fix_evrecord()
    fix_evreplay()
    fix_evanalyze()
    install_evaudit()
    update_makefile()
    print("\nAll fixes applied and evaudit installed successfully.")
