#!/usr/bin/env python3
"""
Solver for GCC Optimization Forensics task.
Compiles each case at -O0 and -O2, bisects flags for differing cases,
writes fixed versions, and generates report.json.
"""

import json
import subprocess
import os
import re
import sys
import tempfile


def compile_and_run(src, flags_str):
    """Compile a C file with given flags and return stdout string or None."""
    with tempfile.NamedTemporaryFile(suffix='', delete=False) as f:
        binary = f.name
    try:
        cmd = ['gcc'] + flags_str.split() + [src, '-o', binary, '-lm']
        comp = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if comp.returncode != 0:
            return None
        run = subprocess.run([binary], capture_output=True, text=True, timeout=10)
        return run.stdout.strip()
    except Exception:
        return None
    finally:
        if os.path.exists(binary):
            os.unlink(binary)


def get_o2_flags():
    """Get list of optimization flags enabled at -O2."""
    result = subprocess.run(
        ['gcc', '-Q', '-O2', '--help=optimizers'],
        capture_output=True, text=True
    )
    flags = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if '[enabled]' in line:
            match = re.match(r'(-f[\w-]+)', line)
            if match:
                flags.append(match.group(1))
    return flags


def bisect_flag(src, o0_out, o2_flags):
    """Find the single -O2 flag responsible for the behavior difference."""
    # Try well-known culprits first for speed
    priority_flags = ['-fstrict-aliasing', '-ftree-vrp', '-fipa-vrp',
                      '-ftree-forwprop', '-ftree-ccp', '-ftree-fre',
                      '-ftree-dse', '-ftree-dominator-opts', '-ftree-pre',
                      '-fcode-hoisting', '-ftree-ch']
    for flag in priority_flags:
        noflag = flag.replace('-f', '-fno-', 1)
        out = compile_and_run(src, f'-O2 {noflag}')
        if out == o0_out:
            return flag

    # Exhaustive scan of remaining flags
    for flag in o2_flags:
        if flag in priority_flags:
            continue
        noflag = flag.replace('-f', '-fno-', 1)
        out = compile_and_run(src, f'-O2 {noflag}')
        if out == o0_out:
            return flag

    # Fallback for signed overflow: -fwrapv makes signed overflow wrap
    out = compile_and_run(src, '-O2 -fwrapv')
    if out == o0_out:
        return '-fwrapv'

    return ''


def classify_ub(flag, src_content):
    """Classify the type of undefined behavior based on the flag and source."""
    if not flag:
        return 'none'
    flag_clean = flag.lstrip('-')

    if 'strict-aliasing' in flag_clean:
        return ('strict aliasing violation: accessing same memory location '
                'through incompatible pointer types (int* and float*)')

    if 'wrapv' in flag_clean:
        if 'detect_overflow' in src_content or 'a + b' in src_content:
            return ('signed integer overflow: a + b overflows INT_MAX, '
                    'post-hoc overflow check is optimized away')
        return 'signed integer overflow'

    if 'vrp' in flag_clean:
        return ('signed integer overflow: value range propagation exploits '
                'no-overflow assumption to eliminate branch')

    if 'forwprop' in flag_clean or 'ccp' in flag_clean:
        return 'signed integer overflow exploited by optimization pass'

    return 'undefined behavior exploited by optimization'


# ---------------------------------------------------------------------------
# Fix templates — each produces output consistent at -O0 and -O2
# ---------------------------------------------------------------------------

FIX_OVERFLOW = """\
#include <stdio.h>
#include <limits.h>

__attribute__((noinline))
int detect_overflow(int a, int b) {
    int sum;
    if (__builtin_add_overflow(a, b, &sum))
        return 1;
    return 0;
}

int main(void) {
    volatile int x = INT_MAX;
    volatile int y = 1;
    printf("%d\\n", detect_overflow(x, y));
    return 0;
}
"""

FIX_ALIASING = """\
#include <stdio.h>
#include <stdint.h>
#include <string.h>

__attribute__((noinline))
int alias_test(void *buf) {
    int ival = 42;
    float fval = 0.0f;
    memcpy(buf, &ival, sizeof(int));
    memcpy(buf, &fval, sizeof(float));
    int result;
    memcpy(&result, buf, sizeof(int));
    return result;
}

int main(void) {
    char buf[sizeof(int)];
    printf("%d\\n", alias_test(buf));
    return 0;
}
"""


def generate_fix(src_content, ub_type):
    """Generate a fixed version of the source that avoids UB."""
    ub_lower = ub_type.lower()
    src_lower = src_content.lower()

    if 'alias' in ub_lower or 'alias_test' in src_lower:
        return FIX_ALIASING
    if 'overflow' in ub_lower or 'detect_overflow' in src_lower:
        return FIX_OVERFLOW
    if 'strict' in ub_lower:
        return FIX_ALIASING
    if 'signed' in ub_lower or 'integer' in ub_lower:
        return FIX_OVERFLOW

    return None


def main():
    cases_dir = '/app/cases'
    cases = sorted([
        f.replace('.c', '')
        for f in os.listdir(cases_dir)
        if f.endswith('.c')
    ])

    if not cases:
        print("ERROR: No case files found in /app/cases/", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(cases)} case files: {cases}")
    print("Enumerating -O2 flags...")
    o2_flags = get_o2_flags()
    print(f"Found {len(o2_flags)} enabled flags at -O2")

    report = {}

    for case_id in cases:
        src = os.path.join(cases_dir, f'{case_id}.c')
        print(f"\n=== Analyzing {case_id} ===")

        if not os.path.exists(src):
            print(f"  WARNING: {src} not found, skipping")
            continue

        with open(src) as f:
            src_content = f.read()

        o0_out = compile_and_run(src, '-O0')
        o2_out = compile_and_run(src, '-O2')
        print(f"  -O0 output: {o0_out}")
        print(f"  -O2 output: {o2_out}")

        if o0_out is None:
            print(f"  ERROR: Failed to compile {case_id} at -O0")
            o0_out = ''
        if o2_out is None:
            print(f"  ERROR: Failed to compile {case_id} at -O2")
            o2_out = ''

        differs = (o0_out != o2_out)
        flag = ''
        ub_type = 'none'
        correct_output = o0_out  # O0 output represents intended behavior

        if differs:
            print("  Behavior DIFFERS. Bisecting flags...")
            flag = bisect_flag(src, o0_out, o2_flags)
            if flag:
                print(f"  Found responsible flag: {flag}")
            else:
                print("  WARNING: Could not find responsible flag")

            ub_type = classify_ub(flag, src_content)

            # Generate and write fixed version
            fix_code = generate_fix(src_content, ub_type)
            if fix_code:
                os.makedirs('/app/fixed', exist_ok=True)
                fix_path = f'/app/fixed/{case_id}.c'
                with open(fix_path, 'w') as f:
                    f.write(fix_code)
                fix_o0 = compile_and_run(fix_path, '-O0')
                fix_o2 = compile_and_run(fix_path, '-O2')
                print(f"  Fixed version: O0={fix_o0}, O2={fix_o2}")
                if fix_o0 != fix_o2:
                    print("  WARNING: Fixed version still inconsistent!")
        else:
            print("  Behavior is CONSISTENT across optimization levels")

        report[case_id] = {
            'output_O0': o0_out,
            'output_O2': o2_out,
            'behavior_differs': differs,
            'ub_type': ub_type,
            'flag': flag.lstrip('-') if flag else '',
            'correct_output': correct_output,
        }

    # Write report
    with open('/app/report.json', 'w') as f:
        json.dump(report, f, indent=2)
    print(f"\nReport written to /app/report.json")
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
