#!/usr/bin/env python3
"""
Fix timing bugs in recorder.c and replayer.c.

"""


def fix_recorder():
    with open('/app/recorder.c', 'r') as f:
        code = f.read()

    # Fix 1: Replace time(NULL) initialization with deferred init
    code = code.replace(
        '    double oldtime = time(NULL), newtime;',
        '    double oldtime, newtime;'
    )

    # Fix 2a: Add gettimeofday initialization before the loop
    code = code.replace(
        '    int draining = 0;\n\n    for (;;) {',
        '    int draining = 0;\n\n'
        '    gettimeofday(&tv, NULL);\n'
        '    oldtime = tv.tv_sec + (double) tv.tv_usec / 1000000;\n\n'
        '    for (;;) {'
    )

    # Fix 2b: Remove gettimeofday from before read()
    code = code.replace(
        '        /* Sample current time for delta calculation */\n'
        '        gettimeofday(&tv, NULL);\n\n'
        '        /* Read next chunk from the child process */\n',
        '        /* Read next chunk from the child process */\n'
    )

    # Fix 2c: Add gettimeofday after read() succeeds, before timing calc
    code = code.replace(
        '        /* Compute elapsed time and write timing entry */\n'
        '        newtime = tv.tv_sec + (double) tv.tv_usec / 1000000;',
        '        /* Sample time after read completes */\n'
        '        gettimeofday(&tv, NULL);\n\n'
        '        /* Compute elapsed time and write timing entry */\n'
        '        newtime = tv.tv_sec + (double) tv.tv_usec / 1000000;'
    )

    with open('/app/recorder.c', 'w') as f:
        f.write(code)

    print("Fixed recorder.c")


def fix_replayer():
    with open('/app/replayer.c', 'r') as f:
        code = f.read()

    # Fix 3a: Remove oldblk variable declaration
    code = code.replace(
        '    size_t oldblk = 0;\n\n    skip_headers(ftiming);',
        '    skip_headers(ftiming);'
    )

    # Fix 3b: Replace deferred emission with direct emission
    code = code.replace(
        '        /* Emit data from previous entry to account for recording\n'
        '         * delay alignment in the capture pipeline */\n'
        '        if (oldblk)\n'
        '            emit_data(fdata, oldblk);\n\n'
        '        oldblk = blk;',
        '        /* Emit data chunk */\n'
        '        emit_data(fdata, blk);'
    )

    # Fix 3c: Remove final pending block emission after the loop
    code = code.replace(
        '\n    /* Emit final pending block */\n'
        '    if (oldblk)\n'
        '        emit_data(fdata, oldblk);\n',
        '\n'
    )

    with open('/app/replayer.c', 'w') as f:
        f.write(code)

    print("Fixed replayer.c")


if __name__ == '__main__':
    fix_recorder()
    fix_replayer()
    print("All fixes applied.")
