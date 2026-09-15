
"""
KASAN crash report parser.
Parses Linux kernel KASAN sanitizer crash reports into structured data.
"""

import re


def parse_report(text):
    """
    Parse a KASAN crash report into a structured dict.

    Returns dict with keys:
        bug_type, access_type, access_size, faulting_function,
        source_location, pid, comm, call_stack, alloc_stack, free_stack,
        slab_cache, object_size, object_addr, buggy_addr, shadow_state
    """
    report = {}

    # Parse BUG line:
    # BUG: KASAN: <type> in <func>+0x<off>/0x<size> <file>:<line>
    bug_m = re.search(
        r'BUG: KASAN: ([\w-]+) in (\w+)\+0x[\da-f]+/0x[\da-f]+ (\S+):(\d+)',
        text
    )
    if bug_m:
        report['bug_type'] = bug_m.group(1)
        report['faulting_function'] = bug_m.group(2)
        report['source_location'] = {
            'file': bug_m.group(3),
            'line': int(bug_m.group(4)),
        }
    else:
        report['bug_type'] = None
        report['faulting_function'] = None
        report['source_location'] = {'file': None, 'line': None}

    # Parse access line:
    # Read/Write of size N at addr ADDR by task COMM/PID
    access_m = re.search(
        r'(Read|Write) of size (\d+) at addr ([0-9a-fA-F]+) by task (.+)/(\d+)',
        text
    )
    if access_m:
        report['access_type'] = access_m.group(1)
        report['access_size'] = int(access_m.group(2))
        report['buggy_addr'] = int(access_m.group(3), 16)
        report['comm'] = access_m.group(4)
        report['pid'] = int(access_m.group(5))
    else:
        report['access_type'] = None
        report['access_size'] = None
        report['buggy_addr'] = None
        report['comm'] = None
        report['pid'] = None

    # Override pid/comm from the more reliable CPU/PID/Comm line
    pid_m = re.search(r'PID:\s*(\d+)\s+Comm:\s*(\S+)', text)
    if pid_m:
        report['pid'] = int(pid_m.group(1))
        report['comm'] = pid_m.group(2)

    # Parse call stack
    report['call_stack'] = _extract_stack(
        text, 'Call Trace:',
        ['Allocated by task', 'The buggy address', '={10,}']
    )

    # Parse alloc stack
    alloc_m = re.search(r'Allocated by task \d+:', text)
    if alloc_m:
        report['alloc_stack'] = _extract_stack(
            text[alloc_m.start():],
            'Allocated by task',
            ['Freed by task', 'The buggy address', '={10,}']
        )
    else:
        report['alloc_stack'] = []

    # Parse free stack
    free_m = re.search(r'Freed by task \d+:', text)
    if free_m:
        report['free_stack'] = _extract_stack(
            text[free_m.start():],
            'Freed by task',
            ['The buggy address', '={10,}', 'Last potentially']
        )
    else:
        report['free_stack'] = []

    # Parse slab info
    cache_m = re.search(r'belongs to the cache (\S+) of size (\d+)', text)
    if cache_m:
        report['slab_cache'] = cache_m.group(1)
        report['object_size'] = int(cache_m.group(2))
    else:
        report['slab_cache'] = None
        report['object_size'] = None

    obj_m = re.search(r'belongs to the object at ([0-9a-fA-F]+)', text)
    if obj_m:
        report['object_addr'] = int(obj_m.group(1), 16)
    else:
        report['object_addr'] = None

    # Parse shadow memory
    report['shadow_state'] = _parse_shadow(text)

    return report


def _extract_stack(text, start_marker, end_patterns):
    """Extract a call stack section from text."""
    stack = []
    lines = text.split('\n')
    in_section = False

    for line in lines:
        if start_marker in line:
            in_section = True
            continue
        if in_section:
            # Check end conditions
            stripped = line.strip()
            if any(re.search(pat, stripped) for pat in end_patterns):
                break
            entry = _parse_stack_entry(stripped)
            if entry:
                stack.append(entry)
    return stack


def _parse_stack_entry(line):
    """Parse a single stack trace entry."""
    if not line:
        return None

    # Skip non-stack lines
    skip_prefixes = (
        '<', 'RIP:', 'RSP:', 'RAX:', 'RBX:', 'RCX:', 'RDX:',
        'RSI:', 'RDI:', 'RBP:', 'R08:', 'R09:', 'R10:', 'R11:',
        'R12:', 'R13:', 'R14:', 'R15:', 'Code:', 'flags:', 'raw:',
        'page', 'Hardware', 'CPU:',
    )
    if line.startswith(skip_prefixes):
        return None

    # Format: func+0xNN/0xNN file/path.ext:line
    m = re.match(
        r'(\w+)\+0x[\da-f]+/0x[\da-f]+\s+([\w/.+_-]+\.\w+):(\d+)',
        line
    )
    if m:
        return {
            'function': m.group(1),
            'location': '{}:{}'.format(m.group(2), m.group(3)),
        }

    # Format: func file/path.ext:line [inline]
    m = re.match(
        r'(\w+)\s+([\w/.+_-]+/[\w/.+_-]+\.\w+):(\d+)',
        line
    )
    if m:
        return {
            'function': m.group(1),
            'location': '{}:{}'.format(m.group(2), m.group(3)),
        }

    return None


def _parse_shadow(text):
    """Parse shadow memory dump from the report."""
    shadow_lines = []
    in_shadow = False

    for line in text.split('\n'):
        if 'Memory state around' in line:
            in_shadow = True
            continue
        if not in_shadow:
            continue

        stripped = line.strip()
        if stripped.startswith('^') or not stripped:
            continue
        if stripped.startswith('='):
            break

        is_current = line.lstrip().startswith('>') or line.startswith('>')
        cleaned = line.lstrip('>').strip()

        # Split on first colon to separate address from values
        colon_idx = cleaned.find(':')
        if colon_idx < 0:
            continue

        addr_str = cleaned[:colon_idx].strip()
        vals_str = cleaned[colon_idx + 1:].strip()

        try:
            addr = int(addr_str, 16)
        except ValueError:
            continue

        values = []
        for v in vals_str.split():
            try:
                values.append(int(v, 16))
            except ValueError:
                continue

        if values:
            shadow_lines.append({
                'addr': addr,
                'values': values,
                'is_buggy_line': is_current,
            })

    return shadow_lines
