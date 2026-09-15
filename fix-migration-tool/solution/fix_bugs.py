#!/usr/bin/env python3
"""Diagnose and fix all bugs in the migration tool.

Reads each source file, identifies the specific defect, applies a targeted
fix, and writes the corrected file back. Five bugs are fixed:

1. graph.py   - False cycle detection on diamond dependency graphs
2. parser.py  - SQL statement splitter breaks on semicolons inside strings
3. state.py   - mark_applied omits status column, leaving it as 'pending'
4. checksum.py - Comment-stripping regex missing re.MULTILINE flag
5. lock.py    - PID read as string causes TypeError in os.kill
"""

import os
import sys


def read_file(path):
    with open(path) as f:
        return f.read()


def write_file(path, content):
    with open(path, 'w') as f:
        f.write(content)


def verify_replacement(original, modified, label):
    """Verify that a replacement actually changed the file."""
    if original == modified:
        print(f"WARNING: No change made to {label}", file=sys.stderr)
        return False
    return True


def fix_graph():
    """Fix: DFS cycle detection uses single visited set without recursion stack.

    In the buggy version, _has_cycle(node, visited) adds nodes to visited but
    never removes them on backtrack. For diamond A->B->D, A->C->D: after DFS
    explores A->B->D, node D stays in visited. When DFS explores A->C->D,
    it finds D in visited and falsely reports a cycle.

    Fix: Use 3-color DFS with separate visited (fully explored) and rec_stack
    (currently on recursion path) sets.
    """
    path = '/app/migrator/graph.py'
    content = read_file(path)
    original = content

    # Fix the validate method to use two sets and re-indent the raise block
    content = content.replace(
        '        for start_node in self._nodes:\n'
        '            visited = set()\n'
        '            if self._has_cycle(start_node, visited):\n'
        '                raise ValueError(\n'
        '                    f"Circular dependency detected involving \'{start_node}\'"\n'
        '                )',

        '        visited = set()\n'
        '        rec_stack = set()\n'
        '        for start_node in self._nodes:\n'
        '            if start_node not in visited:\n'
        '                if self._has_cycle(start_node, visited, rec_stack):\n'
        '                    raise ValueError(\n'
        '                        f"Circular dependency detected involving \'{start_node}\'"\n'
        '                    )'
    )

    # Fix the _has_cycle method to use proper 3-color DFS
    content = content.replace(
        '    def _has_cycle(self, node, visited):\n'
        '        if node in visited:\n'
        '            return True\n'
        '        visited.add(node)\n'
        '        for dep in self._nodes.get(node, set()):\n'
        '            if self._has_cycle(dep, visited):\n'
        '                return True\n'
        '        return False',

        '    def _has_cycle(self, node, visited, rec_stack):\n'
        '        visited.add(node)\n'
        '        rec_stack.add(node)\n'
        '        for dep in self._nodes.get(node, set()):\n'
        '            if dep not in visited:\n'
        '                if self._has_cycle(dep, visited, rec_stack):\n'
        '                    return True\n'
        '            elif dep in rec_stack:\n'
        '                return True\n'
        '        rec_stack.discard(node)\n'
        '        return False'
    )

    verify_replacement(original, content, 'graph.py')
    write_file(path, content)
    print("Fixed graph.py: cycle detection now uses 3-color DFS")


def fix_parser():
    """Fix: SQL statement splitter naively splits on all semicolons.

    The buggy version uses body.split(';') which breaks on semicolons
    inside single-quoted string literals, e.g.:
      INSERT INTO t VALUES ('Hello; world');
    gets split into two invalid fragments.

    Fix: Track whether we're inside a single-quoted string and only split
    on semicolons that appear outside of string literals.
    """
    path = '/app/migrator/parser.py'
    content = read_file(path)
    original = content

    content = content.replace(
        '    # Split on semicolons\n'
        "    raw_parts = body.split(';')\n"
        '\n'
        '    statements = []\n'
        '    for part in raw_parts:\n'
        '        stmt = part.strip()\n'
        '        if stmt:\n'
        "            statements.append(stmt + ';')\n"
        '\n'
        '    return statements',

        "    # Split on semicolons, respecting single-quoted string literals\n"
        '    statements = []\n'
        '    current = []\n'
        '    in_string = False\n'
        '    for char in body:\n'
        '        if char == "\'":\n'
        '            in_string = not in_string\n'
        '            current.append(char)\n'
        "        elif char == ';' and not in_string:\n"
        "            stmt = ''.join(current).strip()\n"
        '            if stmt:\n'
        "                statements.append(stmt + ';')\n"
        '            current = []\n'
        '        else:\n'
        '            current.append(char)\n'
        "    remaining = ''.join(current).strip()\n"
        '    if remaining:\n'
        '        statements.append(remaining)\n'
        '    return statements'
    )

    verify_replacement(original, content, 'parser.py')
    write_file(path, content)
    print("Fixed parser.py: statement splitter now respects string literals")


def fix_state():
    """Fix: mark_applied INSERT omits the status column.

    The table schema defaults status to 'pending', but is_applied queries
    for status = 'applied'. Since mark_applied never sets the status column,
    all migrations appear unapplied and get re-executed on subsequent runs,
    causing 'table already exists' errors.

    Fix: Include status='applied' in the INSERT statement.
    """
    path = '/app/migrator/state.py'
    content = read_file(path)
    original = content

    content = content.replace(
        "f'(migration_id, checksum, applied_at) '",
        "f'(migration_id, checksum, applied_at, status) '"
    )
    content = content.replace(
        "f'VALUES (?, ?, ?)',",
        "f'VALUES (?, ?, ?, ?)',"
    )
    content = content.replace(
        "(migration_id, checksum, datetime.datetime.now().isoformat())",
        "(migration_id, checksum, datetime.datetime.now().isoformat(), 'applied')"
    )

    verify_replacement(original, content, 'state.py')
    write_file(path, content)
    print("Fixed state.py: mark_applied now sets status='applied'")


def fix_checksum():
    """Fix: Comment-stripping regex missing re.MULTILINE flag.

    re.sub(r'^--.*$', '', content) without re.MULTILINE treats ^ and $ as
    start/end of the entire string, not individual lines. So comments in
    multi-line files are never stripped, and checksums change when comments
    are edited even though the SQL content is identical.

    Fix: Add flags=re.MULTILINE to the re.sub call.
    """
    path = '/app/migrator/checksum.py'
    content = read_file(path)
    original = content

    content = content.replace(
        "stripped = re.sub(r'^--.*$', '', content)",
        "stripped = re.sub(r'^--.*$', '', content, flags=re.MULTILINE)"
    )

    verify_replacement(original, content, 'checksum.py')
    write_file(path, content)
    print("Fixed checksum.py: comment stripping uses re.MULTILINE")


def fix_lock():
    """Fix: PID read as string causes TypeError in os.kill.

    f.read().strip() returns a string like '12345', but os.kill expects an
    integer PID. Passing a string raises TypeError, which is caught by the
    bare 'except Exception: return False' handler, making _is_stale always
    return False. Stale locks from dead processes are never cleaned up.

    Fix: Convert the PID string to int before passing to os.kill.
    """
    path = '/app/migrator/lock.py'
    content = read_file(path)
    original = content

    content = content.replace(
        "pid = f.read().strip()",
        "pid = int(f.read().strip())"
    )

    verify_replacement(original, content, 'lock.py')
    write_file(path, content)
    print("Fixed lock.py: PID converted to int for os.kill")


if __name__ == '__main__':
    fix_graph()
    fix_parser()
    fix_state()
    fix_checksum()
    fix_lock()
    print("\nAll 5 bugs fixed successfully.")
