#!/usr/bin/env python3
"""Fix all defects in the migration tool and implement the check subcommand.

Reads each module, applies targeted fixes via string replacement, then adds
the check diagnostic subcommand to migrate.py and executor.py.
"""

import sys


def read_file(path):
    with open(path) as f:
        return f.read()


def write_file(path, content):
    with open(path, 'w') as f:
        f.write(content)


def patch(content, old, new, label):
    """Replace old with new exactly once, warn if no match."""
    result = content.replace(old, new, 1)
    if result == content:
        print(f"WARNING: patch failed for {label}", file=sys.stderr)
    return result


def fix_graph():
    """Fix false cycle detection on diamond dependency graphs."""
    path = '/app/migrator/graph.py'
    content = read_file(path)

    content = patch(content,
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
        '                    )',
        'graph.py validate')

    content = patch(content,
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
        '        return False',
        'graph.py _has_cycle')

    write_file(path, content)
    print("Patched graph.py")


def fix_parser():
    """Fix SQL statement splitter to handle semicolons inside string literals."""
    path = '/app/migrator/parser.py'
    content = read_file(path)

    content = patch(content,
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
        '    return statements',
        'parser.py split')

    write_file(path, content)
    print("Patched parser.py")


def fix_state():
    """Fix mark_applied to include the status column."""
    path = '/app/migrator/state.py'
    content = read_file(path)

    content = patch(content,
        "f'(migration_id, checksum, applied_at) '",
        "f'(migration_id, checksum, applied_at, status) '",
        'state.py columns')
    content = patch(content,
        "f'VALUES (?, ?, ?)',",
        "f'VALUES (?, ?, ?, ?)',",
        'state.py placeholders')
    content = patch(content,
        "(migration_id, checksum, datetime.datetime.now().isoformat())",
        "(migration_id, checksum, datetime.datetime.now().isoformat(), 'applied')",
        'state.py values')

    write_file(path, content)
    print("Patched state.py")


def fix_checksum():
    """Fix comment-stripping regex to handle multi-line content."""
    path = '/app/migrator/checksum.py'
    content = read_file(path)

    content = patch(content,
        "stripped = re.sub(r'^--.*$', '', content)",
        "stripped = re.sub(r'^--.*$', '', content, flags=re.MULTILINE)",
        'checksum.py regex')

    write_file(path, content)
    print("Patched checksum.py")


def fix_lock():
    """Fix PID type conversion for process liveness check."""
    path = '/app/migrator/lock.py'
    content = read_file(path)

    content = patch(content,
        "pid = f.read().strip()",
        "pid = int(f.read().strip())",
        'lock.py pid')

    write_file(path, content)
    print("Patched lock.py")


def add_check_subcommand():
    """Add the check subcommand to migrate.py and implement it in executor.py."""
    # Update migrate.py to add check subparser and handler
    path = '/app/migrate.py'
    content = read_file(path)

    content = patch(content,
        "    args = parser.parse_args()\n",
        "    check_p = subparsers.add_parser('check', help='Run health check')\n"
        "    check_p.add_argument('--db', required=True)\n"
        "    check_p.add_argument('--migrations-dir', required=True)\n"
        "\n"
        "    args = parser.parse_args()\n",
        'migrate.py check subparser')

    content = patch(content,
        "    elif args.command == 'verify':\n"
        "        result = executor.verify()\n"
        "        sys.exit(0 if result else 1)\n",
        "    elif args.command == 'verify':\n"
        "        result = executor.verify()\n"
        "        sys.exit(0 if result else 1)\n"
        "    elif args.command == 'check':\n"
        "        executor.check()\n",
        'migrate.py check handler')

    write_file(path, content)
    print("Updated migrate.py with check subcommand")

    # Add check method to executor.py
    path = '/app/migrator/executor.py'
    content = read_file(path)

    check_method = (
        '\n'
        '    def check(self):\n'
        '        """Output a JSON health-check report to stdout."""\n'
        '        import json\n'
        '        migrations = discover_migrations(self.migrations_dir)\n'
        '\n'
        '        graph = DependencyGraph()\n'
        '        for m in migrations:\n'
        '            graph.add_node(m.file_id, m.dependencies)\n'
        '\n'
        '        graph_valid = True\n'
        '        try:\n'
        '            graph.validate()\n'
        '        except ValueError:\n'
        '            graph_valid = False\n'
        '\n'
        '        state = MigrationState(self.db_path)\n'
        '        migration_ids = {m.file_id for m in migrations}\n'
        '\n'
        '        applied_count = 0\n'
        '        pending_count = 0\n'
        '        for m in migrations:\n'
        '            if state.is_applied(m.file_id):\n'
        '                applied_count += 1\n'
        '            else:\n'
        '                pending_count += 1\n'
        '\n'
        '        checksum_mismatches = []\n'
        '        for m in migrations:\n'
        '            stored = state.get_applied_checksum(m.file_id)\n'
        '            if stored is not None:\n'
        '                current = compute_checksum(m.path)\n'
        '                if stored != current:\n'
        '                    checksum_mismatches.append(m.file_id)\n'
        '\n'
        '        orphaned_records = []\n'
        '        for row in state.get_all_applied():\n'
        '            mid = row[0]\n'
        '            if mid not in migration_ids:\n'
        '                orphaned_records.append(mid)\n'
        '\n'
        '        valid = graph_valid and not checksum_mismatches and not orphaned_records\n'
        '\n'
        '        report = {\n'
        '            "valid": valid,\n'
        '            "total": len(migrations),\n'
        '            "applied": applied_count,\n'
        '            "pending": pending_count,\n'
        '            "graph_valid": graph_valid,\n'
        '            "checksum_mismatches": sorted(checksum_mismatches),\n'
        '            "orphaned_records": sorted(orphaned_records),\n'
        '        }\n'
        '        print(json.dumps(report))\n'
    )

    content = content.rstrip() + '\n' + check_method
    write_file(path, content)
    print("Added check method to executor.py")


if __name__ == '__main__':
    fix_graph()
    fix_parser()
    fix_state()
    fix_checksum()
    fix_lock()
    add_check_subcommand()
    print("\nAll fixes applied and check subcommand implemented.")
