#!/usr/bin/env python3
"""TAC well-formedness validator.

Checks:
- Each FUNC has a matching END
- Labels are unique within each function
- GOTO/IF targets reference existing labels within the same function
- At least one function exists
- Each function has at least one labeled block
- Instructions conform to recognized syntax patterns
"""

import sys
import re

_VALID_INSTR = [
    re.compile(r'RETURN\s+.+$'),
    re.compile(r'PRINT\s+.+$'),
    re.compile(r'IF\s+\S+\s+GOTO\s+\w+\s+ELSE\s+GOTO\s+\w+$'),
    re.compile(r'GOTO\s+\w+$'),
    re.compile(r'\w+\s*=\s*CALL\s+\w+\s*\(.*?\)$'),
    re.compile(r'\w+\s*=\s*(-|!)\s*\w+\s*$'),
    re.compile(
        r'\w+\s*=\s*\w+\s*'
        r'([\+\-\*/%]|==|!=|<=|>=|<|>|&&|\|\|)\s*\w+\s*$'
    ),
    re.compile(r'\w+\s*=\s*.+$'),
    re.compile(r'NOP$'),
]


def validate(text):
    errors = []
    lines = text.strip().split('\n')
    i = 0
    func_count = 0

    while i < len(lines):
        line = lines[i].strip()
        if not line or line.startswith('#'):
            i += 1
            continue

        m = re.match(r'FUNC\s+(\w+)\s*\((.*?)\)\s*:', line)
        if m:
            fname = m.group(1)
            func_count += 1
            labels = set()
            targets = set()
            has_label = False
            i += 1
            found_end = False

            while i < len(lines):
                fl = lines[i].strip()
                if fl == 'END':
                    found_end = True
                    i += 1
                    break
                if not fl or fl.startswith('#'):
                    i += 1
                    continue

                lm = re.match(r'^(\w+)\s*:\s*$', fl)
                if lm:
                    label = lm.group(1)
                    if label in labels:
                        errors.append(
                            f"Duplicate label '{label}' in function '{fname}'"
                        )
                    labels.add(label)
                    has_label = True
                else:
                    gm = re.match(r'GOTO\s+(\w+)$', fl)
                    if gm:
                        targets.add(gm.group(1))
                    im = re.match(
                        r'IF\s+\S+\s+GOTO\s+(\w+)\s+ELSE\s+GOTO\s+(\w+)$',
                        fl,
                    )
                    if im:
                        targets.add(im.group(1))
                        targets.add(im.group(2))
                    # Check instruction syntax
                    if not any(p.match(fl) for p in _VALID_INSTR):
                        errors.append(
                            f"Unrecognized instruction in '{fname}': {fl}"
                        )
                i += 1

            if not found_end:
                errors.append(f"Function '{fname}' missing END")
            if not has_label:
                errors.append(f"Function '{fname}' has no labeled blocks")
            for t in targets:
                if t not in labels:
                    errors.append(
                        f"Branch target '{t}' not found in function '{fname}'"
                    )
        else:
            errors.append(f"Unexpected line outside function: '{line}'")
            i += 1

    if func_count == 0:
        errors.append("No functions found")

    return errors


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python3 tac_validate.py <file.tac>", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        text = f.read()

    errs = validate(text)
    if errs:
        for e in errs:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    else:
        print("VALID")
        sys.exit(0)
