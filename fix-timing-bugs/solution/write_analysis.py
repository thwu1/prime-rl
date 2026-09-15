#!/usr/bin/env python3
"""
Generate ANALYSIS.md by inspecting recorder.c and replayer.c source code
to identify the timing defects and explain the migration design.

"""

import re


def find_defects(recorder_src, replayer_src):
    """Analyze source files and return structured findings."""
    findings = {}

    # Defect 1: time(NULL) precision
    if re.search(r'time\s*\(\s*NULL\s*\)', recorder_src):
        findings['clock_precision'] = {
            'present': True,
            'detail': 'oldtime initialized via time(NULL)',
        }
    else:
        findings['clock_precision'] = {'present': False}

    # Defect 2: gettimeofday placement relative to read()
    # Check if gettimeofday appears before read in the loop body
    gtod_pos = recorder_src.find('gettimeofday')
    read_pos = recorder_src.find('read(pipe_fd')
    if gtod_pos >= 0 and read_pos >= 0:
        # Find positions within the loop
        loop_start = recorder_src.find('for (;;)')
        if loop_start >= 0:
            gtod_in_loop = recorder_src.find('gettimeofday', loop_start)
            read_in_loop = recorder_src.find('read(', loop_start)
            findings['sampling_order'] = {
                'gtod_before_read': (gtod_in_loop < read_in_loop),
            }

    # Defect 3: replayer compensating pattern
    if 'oldblk' in replayer_src:
        findings['compensating_pattern'] = {
            'present': True,
            'mechanism': 'deferred emission via oldblk variable',
        }
    else:
        findings['compensating_pattern'] = {'present': False}

    return findings


def generate_analysis(findings):
    """Generate the analysis document from findings."""
    sections = []

    sections.append("# Recording System Timing Architecture Analysis\n")

    sections.append("## Overview\n")
    sections.append(
        "The session recording/replay system contains three interacting "
        "timing defects spanning both the recorder and replayer. These "
        "defects form a coupled-bug dependency where the replayer's "
        "architecture was designed to compensate for the recorder's "
        "systematic timing errors, masking the problem during normal "
        "playback while producing fundamentally incorrect recordings.\n"
    )

    sections.append("## Defect 1: Clock Initialization Precision Loss\n")
    if findings.get('clock_precision', {}).get('present'):
        sections.append(
            "**Root cause:** The `capture_output()` function initializes "
            "`oldtime` using `time(NULL)`, which returns only whole-second "
            "granularity (integer seconds since epoch). This value is stored "
            "into a `double`, but the fractional part is always zero. "
            "Subsequent timing deltas are computed against `gettimeofday()` "
            "values that include microsecond precision.\n\n"
            "**Impact:** The first timing entry's delay is the difference "
            "between a microsecond-precise timestamp and a truncated "
            "whole-second timestamp. This produces a random 0\u20131 second "
            "value representing the sub-second offset at program start, "
            "completely unrelated to actual subprocess timing. For example, "
            "if the program starts at 1362172012.128947 seconds, "
            "`time(NULL)` stores 1362172012.000000, and the first delta "
            "includes a spurious +0.128947s offset.\n\n"
            "**Fix:** Replace `time(NULL)` initialization with "
            "`gettimeofday()` to capture the full-precision start time.\n"
        )
    else:
        sections.append("Clock precision defect not found in source.\n")

    sections.append(
        "## Defect 2: Time Sampling Before read() — Off-by-One Shift\n"
    )
    if findings.get('sampling_order', {}).get('gtod_before_read'):
        sections.append(
            "**Root cause:** Inside the main recording loop, "
            "`gettimeofday()` is called *before* `read()`, not after. "
            "The loop structure is:\n\n"
            "```\n"
            "loop {\n"
            "    gettimeofday(&tv)           // sample BEFORE blocking\n"
            "    nread = read(pipe_fd, ...)   // block until data arrives\n"
            "    newtime = tv                 // use pre-read timestamp\n"
            "    delta = newtime - oldtime    // wrong interval!\n"
            "    oldtime = newtime\n"
            "}\n"
            "```\n\n"
            "Each delta measures the time from the *start* of the previous "
            "`read()` to the *start* of the current `read()`, rather than "
            "the time spent blocking in the current `read()`. This creates "
            "a persistent off-by-one shift: `buggy_delay[i]` for `i >= 1` "
            "actually represents the correct delay for entry `i-1`.\n\n"
            "On the first iteration, `oldtime` and `newtime` (from "
            "`gettimeofday` called before `read`) are nearly identical, "
            "so the first post-initialization delta is near zero regardless "
            "of how long `read()` actually blocked. The actual blocking "
            "time from the first `read()` gets attributed to the *second* "
            "entry's delta, and so on.\n\n"
            "**Fix:** Move `gettimeofday()` to *after* `read()` returns, "
            "so each delta measures the actual time spent waiting for data "
            "in that specific `read()` call.\n"
        )
    else:
        sections.append("Sampling order defect not found in source.\n")

    sections.append(
        "## Defect 3: Replayer Compensating Pattern (Coupled Bug)\n"
    )
    if findings.get('compensating_pattern', {}).get('present'):
        sections.append(
            "**Root cause:** The replayer uses a deferred-emission pattern "
            "via an `oldblk` variable:\n\n"
            "```c\n"
            "size_t oldblk = 0;\n"
            "while (fscanf(..., &delay, &blk) == 2) {\n"
            "    apply_delay(delay);\n"
            "    if (oldblk) emit_data(fdata, oldblk);\n"
            "    oldblk = blk;\n"
            "}\n"
            "if (oldblk) emit_data(fdata, oldblk);\n"
            "```\n\n"
            "On the first iteration, `oldblk` is zero, so no data is "
            "emitted. The byte count from entry 0 is stored in `oldblk` "
            "and emitted on the *next* iteration — after entry 1's delay "
            "has been applied. This effectively shifts the data emission "
            "backward by one entry, compensating for the recorder's "
            "off-by-one timing shift.\n\n"
            "**Coupled dependency:** This only produces correct-*looking* "
            "playback when paired with the buggy recorder. If the recorder "
            "is fixed (delays now correctly aligned), the deferred emission "
            "introduces its own off-by-one error — emitting each chunk "
            "after the wrong delay.\n\n"
            "**Fix:** Replace deferred emission with direct emission: "
            "after applying each entry's delay, immediately emit that "
            "entry's byte count. Remove the `oldblk` variable and the "
            "post-loop final-block emission.\n"
        )
    else:
        sections.append("Compensating pattern not found in replayer.\n")

    sections.append("## Migration Design Rationale\n")
    sections.append(
        "Recordings made by the original buggy recorder have "
        "systematically shifted timing entries. To convert these legacy "
        "recordings into a format usable by the fixed replayer, we apply "
        "the inverse transformation:\n\n"
        "Given N timing entries in a buggy recording:\n"
        "- `corrected_delay[i] = buggy_delay[i+1]` for `i = 0 .. N-2`\n"
        "- `corrected_delay[N-1] = 0.0` (the correct last-entry delay is "
        "unrecoverable from the buggy recording alone)\n"
        "- Byte counts remain associated with their original entry "
        "positions (the byte counts are recorded correctly; only the "
        "delays are shifted)\n"
        "- The data file is copied unchanged\n\n"
        "**Limitation:** The correct delay for the final timing entry "
        "cannot be recovered because it would require knowing the time "
        "spent in the last `read()` call, which was never captured by the "
        "buggy recorder (it would have appeared as the delay in a "
        "hypothetical entry N+1). Setting it to zero means the last chunk "
        "replays immediately, which is acceptable for most use cases since "
        "it is typically the final output before process exit.\n\n"
        "The first entry's garbage delay (caused by `time(NULL)` "
        "truncation) is implicitly discarded by the shift operation — it "
        "is replaced by `buggy_delay[1]`, which correctly measures the "
        "inter-read overhead (approximately zero for instant outputs).\n"
    )

    return "\n".join(sections)


def main():
    with open('/app/recorder.c', 'r') as f:
        recorder_src = f.read()
    with open('/app/replayer.c', 'r') as f:
        replayer_src = f.read()

    findings = find_defects(recorder_src, replayer_src)
    analysis = generate_analysis(findings)

    with open('/app/ANALYSIS.md', 'w') as f:
        f.write(analysis)

    print("Generated ANALYSIS.md")


if __name__ == '__main__':
    main()
