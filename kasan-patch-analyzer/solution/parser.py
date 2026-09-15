"""
KASAN crash report parser.

Parses Linux kernel KASAN (Kernel Address Sanitizer) crash reports into
structured data for downstream analysis. Handles multiple bug types:
slab-out-of-bounds, slab-use-after-free, null-ptr-deref, global-out-of-bounds,
use-after-free, invalid-free, etc.
"""

import re
from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class StackFrame:
    """A single frame in a kernel call stack."""
    function: str
    offset: Optional[str] = None
    source_file: Optional[str] = None
    source_line: Optional[int] = None
    is_inline: bool = False


@dataclass
class KASANReport:
    """Structured representation of a KASAN crash report."""
    bug_type: str
    access_type: str
    access_size: int
    faulting_function: str
    source_file: str
    source_line: int
    crash_addr: str
    task_name: str
    pid: int
    call_stack: List[StackFrame] = field(default_factory=list)
    alloc_stack: Optional[List[StackFrame]] = None
    free_stack: Optional[List[StackFrame]] = None
    object_cache: Optional[str] = None
    object_size: Optional[int] = None
    allocated_size: Optional[int] = None
    buggy_offset: Optional[int] = None


def _parse_stack_frame(line: str) -> Optional[StackFrame]:
    """Parse a single stack frame line from a KASAN report."""
    line = line.strip()
    if not line or line.startswith('<') or line.startswith('='):
        return None

    # Pattern: function+0xOFF/0xSIZE source_file:line
    m = re.match(
        r'(\w+)\+?(0x[0-9a-f]+/0x[0-9a-f]+)?\s+'
        r'(\S+\.(?:c|h|S)):(\d+)',
        line
    )
    if m:
        return StackFrame(
            function=m.group(1),
            offset=m.group(2),
            source_file=m.group(3),
            source_line=int(m.group(4)),
            is_inline=('[inline]' in line)
        )

    # Pattern: function source_file:line [inline]
    m = re.match(
        r'(\w+)\s+(\S+\.(?:c|h|S)):(\d+)\s*\[inline\]',
        line
    )
    if m:
        return StackFrame(
            function=m.group(1),
            offset=None,
            source_file=m.group(2),
            source_line=int(m.group(3)),
            is_inline=True
        )

    # Pattern: just function+offset (no source)
    m = re.match(r'(\w+)\+?(0x[0-9a-f]+/0x[0-9a-f]+)', line)
    if m:
        return StackFrame(
            function=m.group(1),
            offset=m.group(2),
            source_file=None,
            source_line=None,
            is_inline=False
        )

    return None


def _parse_stack_section(text: str) -> List[StackFrame]:
    """Parse a series of stack frame lines."""
    frames = []
    for line in text.strip().split('\n'):
        line = line.strip()
        if not line:
            continue
        # Skip markers
        if line in ('<IRQ>', '</IRQ>', '<TASK>', '</TASK>', '<NMI>', '</NMI>'):
            continue
        frame = _parse_stack_frame(line)
        if frame:
            frames.append(frame)
    return frames


def parse_kasan_report(text: str) -> KASANReport:
    """Parse a KASAN crash report text and return structured data."""

    # Extract bug type from BUG line
    bug_match = re.search(
        r'BUG: KASAN: (\S+) in (\w+)\+?(0x[0-9a-f]+/0x[0-9a-f]+)?\s+'
        r'(\S+\.(?:c|h|S)):(\d+)',
        text
    )
    if not bug_match:
        raise ValueError("Could not parse BUG line from KASAN report")

    bug_type = bug_match.group(1)
    faulting_function = bug_match.group(2)
    source_file = bug_match.group(4)
    source_line = int(bug_match.group(5))

    # Extract access type and size
    access_match = re.search(
        r'(Read|Write) of size (\d+) at addr ([0-9a-fA-Fx]+) by task (\S+)/(\d+)',
        text
    )
    if access_match:
        access_type = access_match.group(1)
        access_size = int(access_match.group(2))
        crash_addr = access_match.group(3)
        task_name = access_match.group(4)
        pid = int(access_match.group(5))
    else:
        access_type = "Unknown"
        access_size = 0
        crash_addr = "unknown"
        task_name = "unknown"
        pid = 0

    # Extract call stack
    call_stack_match = re.search(
        r'Call Trace:\s*\n(.*?)(?:\n\s*\n|\nAllocated by|\nThe buggy)',
        text, re.DOTALL
    )
    call_stack = []
    if call_stack_match:
        call_stack = _parse_stack_section(call_stack_match.group(1))

    # Extract allocated-by stack
    alloc_stack = None
    alloc_match = re.search(
        r'Allocated by task \d+:\s*\n(.*?)(?:\n\s*\n|\nFreed by|\nThe buggy)',
        text, re.DOTALL
    )
    if alloc_match:
        alloc_stack = _parse_stack_section(alloc_match.group(1))

    # Extract freed-by stack
    free_stack = None
    free_match = re.search(
        r'Freed by task \d+:\s*\n(.*?)(?:\n\s*\n|\nThe buggy)',
        text, re.DOTALL
    )
    if free_match:
        free_stack = _parse_stack_section(free_match.group(1))

    # Extract object info
    object_cache = None
    object_size = None
    cache_match = re.search(
        r'belongs to the cache (\S+) of size (\d+)',
        text
    )
    if cache_match:
        object_cache = cache_match.group(1)
        object_size = int(cache_match.group(2))

    # Extract allocation region size
    allocated_size = None
    region_match = re.search(
        r'allocated (\d+)-byte region',
        text
    )
    if region_match:
        allocated_size = int(region_match.group(1))

    # Extract buggy offset
    buggy_offset = None
    offset_right_match = re.search(
        r'located (\d+) bytes to the right of',
        text
    )
    if offset_right_match:
        buggy_offset = int(offset_right_match.group(1))
    else:
        offset_inside_match = re.search(
            r'located (\d+) bytes inside of',
            text
        )
        if offset_inside_match:
            buggy_offset = int(offset_inside_match.group(1))

    return KASANReport(
        bug_type=bug_type,
        access_type=access_type,
        access_size=access_size,
        faulting_function=faulting_function,
        source_file=source_file,
        source_line=source_line,
        crash_addr=crash_addr,
        task_name=task_name,
        pid=pid,
        call_stack=call_stack,
        alloc_stack=alloc_stack,
        free_stack=free_stack,
        object_cache=object_cache,
        object_size=object_size,
        allocated_size=allocated_size,
        buggy_offset=buggy_offset,
    )
