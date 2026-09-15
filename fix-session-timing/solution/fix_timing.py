#!/usr/bin/env python3
"""
Diagnose and fix timing bugs in the session recorder/replayer.

Analysis of sesrec.c reveals two interacting timing bugs:

1. INITIAL TIMESTAMP PRECISION: The variable 'oldtime' is initialized
   with time(NULL), which returns whole seconds only.  The subsequent
   delta calculations use gettimeofday() (microsecond precision),
   causing the first timing entry to be off by up to one second.

2. CLOCK SAMPLE PLACEMENT: gettimeofday() is called BEFORE the
   blocking read(), so each timing entry measures the interval from
   the previous clock sample to the current (pre-read) sample — NOT
   the time spent waiting in read().  This produces a persistent
   off-by-one shift: each entry's delay corresponds to the PREVIOUS
   chunk's wait time, not the current one.

Analysis of sesplay.c reveals a compensating hack:

3. DEFERRED EMISSION: The replayer uses 'oldblk' to defer byte
   emission by one cycle, effectively shifting the byte counts back
   to align with the recorder's shifted timing.  With the recorder
   fixed, this hack produces wrong timing during replay.

Fixes:
- sesrec.c: Use gettimeofday() for oldtime init; move gettimeofday()
  from before read() to after read() returns.
- sesplay.c: Remove oldblk deferral; emit 'blk' bytes directly.
"""



def skip_brace_block(lines, start):
    """Skip a brace-delimited block starting at index `start`.
    Returns the index of the first line after the closing brace."""
    i = start
    depth = 0
    opened = False
    while i < len(lines):
        for ch in lines[i]:
            if ch == '{':
                depth += 1
                opened = True
            elif ch == '}':
                depth -= 1
        i += 1
        if opened and depth == 0:
            break
    return i


def fix_recorder():
    with open('/app/src/sesrec.c') as f:
        lines = f.readlines()

    result = []
    i = 0
    while i < len(lines):
        line = lines[i]

        # Fix 1: Replace time(NULL) initialization with uninitialized
        if 'double oldtime = time(NULL), newtime;' in line:
            result.append(line.replace(
                'double oldtime = time(NULL), newtime;',
                'double oldtime, newtime;'))
            i += 1
            continue

        # Fix 1b: Insert gettimeofday initialization before the for(;;)
        if line.strip() == 'for (;;) {':
            result.append('    gettimeofday(&tv, NULL);\n')
            result.append(
                '    oldtime = tv.tv_sec +'
                ' (double)tv.tv_usec / 1000000;\n')
            result.append('\n')
            result.append(line)
            i += 1
            continue

        # Fix 2: Remove premature gettimeofday (before read)
        if 'Capture current time for delta calculation' in line:
            i += 1  # skip comment line
            if i < len(lines) and 'gettimeofday(&tv, NULL)' in lines[i]:
                i += 1  # skip gettimeofday call
            if i < len(lines) and lines[i].strip() == '':
                i += 1  # skip trailing blank line
            continue

        # Fix 2b: Insert gettimeofday after the break, before newtime
        if 'Compute elapsed time and emit timing record' in line:
            result.append(line)
            result.append('        gettimeofday(&tv, NULL);\n')
            i += 1
            continue

        result.append(line)
        i += 1

    with open('/app/src/sesrec.c', 'w') as f:
        f.writelines(result)
    print("sesrec.c: fixed time() init and gettimeofday placement")


def fix_replayer():
    with open('/app/src/sesplay.c') as f:
        lines = f.readlines()

    result = []
    i = 0
    oldblk_hit = 0

    while i < len(lines):
        line = lines[i]

        # Remove oldblk declaration
        if 'size_t oldblk = 0;' in line:
            i += 1
            continue

        # Handle if (oldblk) blocks
        if line.strip().startswith('if (oldblk)'):
            oldblk_hit += 1

            if oldblk_hit == 1:
                # First block (inside while loop): replace with direct emit
                i = skip_brace_block(lines, i)
                # Skip blank line
                if i < len(lines) and lines[i].strip() == '':
                    i += 1
                # Skip 'oldblk = blk;'
                if i < len(lines) and 'oldblk = blk;' in lines[i]:
                    i += 1

                # Write direct emission
                result.append(
                    '        if (emit_bytes(fscript, ts_path, blk) < 0)'
                    ' {\n')
                result.append(
                    '            fprintf(stderr,'
                    ' "sesplay: replay error at timing line'
                    ' %lu\\n", line);\n')
                result.append('            break;\n')
                result.append('        }\n')
                continue

            elif oldblk_hit == 2:
                # Second block (after while loop): remove entirely
                i = skip_brace_block(lines, i)
                # Skip trailing blank line
                if i < len(lines) and lines[i].strip() == '':
                    i += 1
                continue

        # Skip stray 'oldblk = blk;' if any remain
        if 'oldblk = blk;' in line:
            i += 1
            continue

        result.append(line)
        i += 1

    with open('/app/src/sesplay.c', 'w') as f:
        f.writelines(result)
    print("sesplay.c: removed oldblk deferred emission hack")


if __name__ == '__main__':
    fix_recorder()
    fix_replayer()
    print("All timing fixes applied successfully")
