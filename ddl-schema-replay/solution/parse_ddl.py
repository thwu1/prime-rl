#!/usr/bin/env python3

"""
Parse MySQL DDL statements from ddl_history in PostgreSQL,
compute final schema state, and write reconstruct.sql that
populates the schema_state table.
"""

import re
import psycopg2


# ── Utility functions ──────────────────────────────────────────────

def strip_backticks(s):
    s = s.strip()
    if s.startswith('`') and s.endswith('`'):
        return s[1:-1]
    return s


def find_matching_paren(s, start):
    """Find matching ')' for '(' at position start."""
    depth = 0
    in_quote = False
    i = start
    while i < len(s):
        c = s[i]
        if c == '\\' and in_quote:
            i += 2
            continue
        if c == "'" and not in_quote:
            in_quote = True
        elif c == "'" and in_quote:
            # check doubled quote
            if i + 1 < len(s) and s[i + 1] == "'":
                i += 2
                continue
            in_quote = False
        elif not in_quote:
            if c == '(':
                depth += 1
            elif c == ')':
                depth -= 1
                if depth == 0:
                    return i
        i += 1
    return len(s) - 1


def find_end_of_string(s, start):
    """Find closing quote for string starting with ' at start."""
    i = start + 1
    while i < len(s):
        c = s[i]
        if c == '\\':
            i += 2
            continue
        if c == "'":
            if i + 1 < len(s) and s[i + 1] == "'":
                i += 2
                continue
            return i
        i += 1
    return len(s) - 1


def split_top_level(s, delim=','):
    """Split s at delim, but only at top-level (not inside parens or quotes)."""
    parts = []
    depth = 0
    in_quote = False
    current = []
    i = 0
    while i < len(s):
        c = s[i]
        if c == '\\' and in_quote:
            current.append(c)
            if i + 1 < len(s):
                i += 1
                current.append(s[i])
            i += 1
            continue
        if c == "'":
            in_quote = not in_quote
        elif not in_quote:
            if c == '(':
                depth += 1
            elif c == ')':
                depth -= 1
            elif c == delim and depth == 0:
                parts.append(''.join(current).strip())
                current = []
                i += 1
                continue
        current.append(c)
        i += 1
    remainder = ''.join(current).strip()
    if remainder:
        parts.append(remainder)
    return parts


# ── Type parser ────────────────────────────────────────────────────

def parse_type(s):
    """Parse MySQL column type from start of s. Returns (type_str, rest)."""
    s = s.strip()
    m = re.match(r'(\w+)', s)
    if not m:
        return ('', s)
    type_name = m.group(1).lower()
    rest = s[m.end():].strip()

    if type_name in ('enum', 'set'):
        if rest.startswith('('):
            end = find_matching_paren(rest, 0)
            type_str = type_name + rest[:end + 1]
            rest = rest[end + 1:].strip()
            return (type_str, rest)
        return (type_name, rest)

    if rest.startswith('('):
        end = find_matching_paren(rest, 0)
        type_str = type_name + rest[:end + 1]
        rest = rest[end + 1:].strip()
    else:
        type_str = type_name

    # Check for UNSIGNED
    if rest.upper().startswith('UNSIGNED'):
        type_str += ' unsigned'
        rest = rest[8:].strip()

    return (type_str, rest)


# ── Default value parser ──────────────────────────────────────────

def parse_default_at(s, i):
    """Parse DEFAULT value starting at position i. Returns (value, new_i)."""
    while i < len(s) and s[i] in (' ', '\t', '\n', '\r'):
        i += 1
    if i >= len(s):
        return (None, i)

    upper_rest = s[i:].upper()

    # NULL
    if upper_rest.startswith('NULL'):
        return (None, i + 4)

    # Expression: (expr)
    if s[i] == '(':
        end = find_matching_paren(s, i)
        expr = s[i + 1:end].strip()
        return (expr, end + 1)

    # String literal
    if s[i] == "'":
        end = find_end_of_string(s, i)
        value = s[i + 1:end]
        return (value, end + 1)

    # Function call: word(...)
    m = re.match(r'(\w+)', s[i:])
    if m:
        word = m.group(1)
        j = i + m.end()
        while j < len(s) and s[j] in (' ', '\t'):
            j += 1
        if j < len(s) and s[j] == '(':
            paren_end = find_matching_paren(s, j)
            value = word + s[j:paren_end + 1]
            return (value, paren_end + 1)
        return (word, i + m.end())

    # Numeric
    m = re.match(r'[0-9.+-]+', s[i:])
    if m:
        return (m.group(), i + m.end())

    return (None, i)


# ── Column definition parser ─────────────────────────────────────

def parse_column_def(s):
    """Parse a MySQL column definition. Returns column dict."""
    s = s.strip()

    # Extract column name
    if s.startswith('`'):
        end = s.index('`', 1)
        col_name = s[1:end]
        rest = s[end + 1:].strip()
    else:
        m = re.match(r'\w+', s)
        col_name = m.group()
        rest = s[m.end():].strip()

    # Parse type
    data_type, rest = parse_type(rest)

    # Parse modifiers
    is_nullable = True
    column_default = None
    has_default = False
    is_generated = False
    position_first = False
    position_after = None

    i = 0
    while i < len(rest):
        while i < len(rest) and rest[i] in (' ', '\t', '\n', '\r'):
            i += 1
        if i >= len(rest):
            break

        upper = rest[i:].upper()

        if upper.startswith('NOT NULL'):
            is_nullable = False
            i += 8
        elif upper.startswith('NOT SECONDARY'):
            i += 13
        elif upper.startswith('NULL'):
            is_nullable = True
            i += 4
        elif upper.startswith('DEFAULT'):
            i += 7
            has_default = True
            column_default, i = parse_default_at(rest, i)
        elif upper.startswith('AUTO_INCREMENT'):
            i += 14
        elif upper.startswith('GENERATED ALWAYS AS'):
            is_generated = True
            i += 19
            while i < len(rest) and rest[i] in (' ', '\t'):
                i += 1
            if i < len(rest) and rest[i] == '(':
                end = find_matching_paren(rest, i)
                i = end + 1
            while i < len(rest) and rest[i] in (' ', '\t'):
                i += 1
            u2 = rest[i:].upper()
            if u2.startswith('STORED'):
                i += 6
            elif u2.startswith('VIRTUAL'):
                i += 7
        elif upper.startswith('ON UPDATE'):
            i += 9
            while i < len(rest) and rest[i] in (' ', '\t'):
                i += 1
            m = re.match(r'\w+', rest[i:])
            if m:
                i += m.end()
            if i < len(rest) and rest[i] == '(':
                end = find_matching_paren(rest, i)
                i = end + 1
        elif upper.startswith('COMMENT'):
            i += 7
            while i < len(rest) and rest[i] in (' ', '\t'):
                i += 1
            if i < len(rest) and rest[i] == "'":
                end = find_end_of_string(rest, i)
                i = end + 1
        elif upper.startswith('CHARACTER SET'):
            i += 13
            while i < len(rest) and rest[i] in (' ', '\t', '='):
                i += 1
            m = re.match(r'[\w-]+', rest[i:])
            if m:
                i += m.end()
        elif upper.startswith('CHARSET'):
            i += 7
            while i < len(rest) and rest[i] in (' ', '\t', '='):
                i += 1
            m = re.match(r'[\w-]+', rest[i:])
            if m:
                i += m.end()
        elif upper.startswith('COLLATE'):
            i += 7
            while i < len(rest) and rest[i] in (' ', '\t', '='):
                i += 1
            m = re.match(r'[\w-]+', rest[i:])
            if m:
                i += m.end()
        elif upper.startswith('FIRST'):
            position_first = True
            i += 5
        elif upper.startswith('AFTER'):
            i += 5
            while i < len(rest) and rest[i] in (' ', '\t'):
                i += 1
            if i < len(rest) and rest[i] == '`':
                end = rest.index('`', i + 1)
                position_after = rest[i + 1:end]
                i = end + 1
            else:
                m = re.match(r'\w+', rest[i:])
                if m:
                    position_after = m.group()
                    i += m.end()
        elif upper.startswith('PRIMARY KEY'):
            i += 11
        elif upper.startswith('UNIQUE'):
            i += 6
        elif upper.startswith('KEY'):
            i += 3
        else:
            m = re.match(r'\S+', rest[i:])
            if m:
                i += m.end()
            else:
                i += 1

    return {
        'name': col_name,
        'data_type': data_type,
        'is_nullable': is_nullable,
        'column_default': column_default,
        'is_generated': is_generated,
        'position_first': position_first,
        'position_after': position_after,
    }


# ── Schema model ──────────────────────────────────────────────────

# tables[name] = {'columns': [col_dict, ...], 'pk_columns': set()}
tables = {}


def extract_table_name(s):
    """Extract a (possibly backtick-quoted) table name from start of s."""
    s = s.strip()
    if s.startswith('`'):
        end = s.index('`', 1)
        return s[1:end], s[end + 1:].strip()
    m = re.match(r'[\w.]+', s)
    return m.group(), s[m.end():].strip()


def process_create_table(ddl):
    rest = re.sub(r'^CREATE\s+TABLE\s+', '', ddl, flags=re.IGNORECASE).strip()
    if rest.upper().startswith('IF NOT EXISTS'):
        rest = rest[13:].strip()
    table_name, rest = extract_table_name(rest)
    if table_name in tables:
        return  # IF NOT EXISTS: skip

    # Find column list between outer parens
    paren_start = rest.index('(')
    paren_end = find_matching_paren(rest, paren_start)
    col_list_str = rest[paren_start + 1:paren_end]

    parts = split_top_level(col_list_str)
    columns = []
    pk_columns = set()

    for part in parts:
        part_stripped = part.strip()
        part_upper = part_stripped.upper()

        if part_upper.startswith('PRIMARY KEY'):
            m = re.search(r'\(([^)]+)\)', part_stripped)
            if m:
                pk_columns = {strip_backticks(c.strip()) for c in m.group(1).split(',')}
        elif (part_upper.startswith('UNIQUE KEY') or
              part_upper.startswith('UNIQUE ') or
              part_upper.startswith('KEY ') or
              part_upper.startswith('INDEX ') or
              part_upper.startswith('CONSTRAINT ')):
            pass  # skip constraints/indexes
        else:
            col = parse_column_def(part_stripped)
            columns.append(col)

    tables[table_name] = {'columns': columns, 'pk_columns': pk_columns}


def process_alter_table(ddl):
    rest = re.sub(r'^ALTER\s+TABLE\s+', '', ddl, flags=re.IGNORECASE).strip()
    if rest.upper().startswith('IF EXISTS'):
        rest = rest[9:].strip()
    table_name, rest = extract_table_name(rest)

    if table_name not in tables:
        return

    operations = split_top_level(rest)

    for op in operations:
        op = op.strip()
        op_upper = op.upper()

        if op_upper.startswith('ADD COLUMN ') or (
            op_upper.startswith('ADD ') and
            not op_upper.startswith('ADD PRIMARY') and
            not op_upper.startswith('ADD UNIQUE') and
            not op_upper.startswith('ADD KEY') and
            not op_upper.startswith('ADD INDEX')
        ):
            if op_upper.startswith('ADD COLUMN '):
                col_def_str = op[len('ADD COLUMN '):].strip()
            else:
                col_def_str = op[len('ADD '):].strip()
            # Check that it starts with a backtick or word (column name)
            # to distinguish from ADD (PRIMARY KEY ..., UNIQUE KEY ...)
            if col_def_str.startswith('('):
                # Multi-spec ADD, skip
                continue

            col = parse_column_def(col_def_str)
            cols = tables[table_name]['columns']

            if col.get('position_first'):
                cols.insert(0, col)
            elif col.get('position_after'):
                after = col['position_after']
                idx = next((i for i, c in enumerate(cols) if c['name'] == after), len(cols) - 1)
                cols.insert(idx + 1, col)
            else:
                cols.append(col)

        elif op_upper.startswith('DROP COLUMN '):
            col_name = strip_backticks(op[len('DROP COLUMN '):].strip())
            tables[table_name]['columns'] = [
                c for c in tables[table_name]['columns'] if c['name'] != col_name
            ]
            tables[table_name]['pk_columns'].discard(col_name)

        elif op_upper.startswith('DROP PRIMARY KEY'):
            tables[table_name]['pk_columns'] = set()

        elif op_upper.startswith('ADD PRIMARY KEY'):
            m = re.search(r'\(([^)]+)\)', op)
            if m:
                pk_cols = {strip_backticks(c.strip()) for c in m.group(1).split(',')}
                tables[table_name]['pk_columns'] = pk_cols

        elif op_upper.startswith('MODIFY COLUMN ') or op_upper.startswith('MODIFY '):
            if op_upper.startswith('MODIFY COLUMN '):
                col_def_str = op[len('MODIFY COLUMN '):].strip()
            else:
                col_def_str = op[len('MODIFY '):].strip()
            col = parse_column_def(col_def_str)
            for i, c in enumerate(tables[table_name]['columns']):
                if c['name'] == col['name']:
                    tables[table_name]['columns'][i] = col
                    break

        elif op_upper.startswith('CHANGE COLUMN ') or op_upper.startswith('CHANGE '):
            if op_upper.startswith('CHANGE COLUMN '):
                rest_op = op[len('CHANGE COLUMN '):].strip()
            else:
                rest_op = op[len('CHANGE '):].strip()
            # Extract old name
            if rest_op.startswith('`'):
                end = rest_op.index('`', 1)
                old_name = rest_op[1:end]
                rest_op = rest_op[end + 1:].strip()
            else:
                m = re.match(r'\w+', rest_op)
                old_name = m.group()
                rest_op = rest_op[m.end():].strip()
            # Parse new column definition
            col = parse_column_def(rest_op)
            for i, c in enumerate(tables[table_name]['columns']):
                if c['name'] == old_name:
                    tables[table_name]['columns'][i] = col
                    break
            # Update PK if old name was PK
            if old_name in tables[table_name]['pk_columns']:
                tables[table_name]['pk_columns'].discard(old_name)
                tables[table_name]['pk_columns'].add(col['name'])

        elif op_upper.startswith('RENAME COLUMN '):
            rest_op = op[len('RENAME COLUMN '):].strip()
            if rest_op.upper().startswith('IF EXISTS '):
                rest_op = rest_op[len('IF EXISTS '):].strip()
            if rest_op.startswith('`'):
                end = rest_op.index('`', 1)
                old_name = rest_op[1:end]
                rest_op = rest_op[end + 1:].strip()
            else:
                m = re.match(r'\w+', rest_op)
                old_name = m.group()
                rest_op = rest_op[m.end():].strip()
            # Skip TO
            if rest_op.upper().startswith('TO '):
                rest_op = rest_op[3:].strip()
            new_name = strip_backticks(rest_op)
            for c in tables[table_name]['columns']:
                if c['name'] == old_name:
                    c['name'] = new_name
                    break
            if old_name in tables[table_name]['pk_columns']:
                tables[table_name]['pk_columns'].discard(old_name)
                tables[table_name]['pk_columns'].add(new_name)

        elif op_upper.startswith('RENAME TO ') or op_upper.startswith('RENAME '):
            if op_upper.startswith('RENAME TO '):
                new_name = strip_backticks(op[len('RENAME TO '):].strip())
            else:
                new_name = strip_backticks(op[len('RENAME '):].strip())
            tables[new_name] = tables.pop(table_name)
            table_name = new_name

        elif (op_upper.startswith('ADD UNIQUE') or
              op_upper.startswith('ADD KEY') or
              op_upper.startswith('ADD INDEX')):
            pass  # index ops, skip

        elif op_upper.startswith('CONVERT TO'):
            pass  # charset conversion, skip


def process_drop_table(ddl):
    rest = re.sub(r'^DROP\s+TABLE\s+', '', ddl, flags=re.IGNORECASE).strip()
    if rest.upper().startswith('IF EXISTS'):
        rest = rest[9:].strip()
    table_name, _ = extract_table_name(rest)
    tables.pop(table_name, None)


# ── SQL escaping helper ──────────────────────────────────────────

def pg_escape(val):
    """Escape a string value for use in a PostgreSQL single-quoted literal."""
    return val.replace("'", "''")


# ── Main ──────────────────────────────────────────────────────────

def main():
    conn = psycopg2.connect(dbname='cdc', user='cdc', password='cdc', host='localhost')
    conn.autocommit = True
    cur = conn.cursor()

    # Read DDL history
    cur.execute("SELECT seq_id, ddl_text FROM ddl_history ORDER BY seq_id")
    ddl_entries = cur.fetchall()

    # Process each DDL
    for seq_id, ddl_text in ddl_entries:
        ddl = ddl_text.strip().rstrip(';').strip()
        ddl_upper = ddl.upper().lstrip()

        if ddl_upper.startswith('CREATE TABLE'):
            process_create_table(ddl)
        elif ddl_upper.startswith('ALTER TABLE'):
            process_alter_table(ddl)
        elif ddl_upper.startswith('DROP TABLE'):
            process_drop_table(ddl)

    # Generate reconstruct.sql
    lines = []
    lines.append("-- Auto-generated by parse_ddl.py")
    lines.append("DROP TABLE IF EXISTS schema_state;")
    lines.append("CREATE TABLE schema_state (")
    lines.append("    table_name TEXT NOT NULL,")
    lines.append("    column_name TEXT NOT NULL,")
    lines.append("    ordinal_position INT NOT NULL,")
    lines.append("    data_type TEXT NOT NULL,")
    lines.append("    is_nullable BOOLEAN NOT NULL,")
    lines.append("    column_default TEXT,")
    lines.append("    is_primary_key BOOLEAN NOT NULL,")
    lines.append("    is_generated BOOLEAN NOT NULL DEFAULT FALSE,")
    lines.append("    PRIMARY KEY (table_name, column_name)")
    lines.append(");")
    lines.append("")

    for tname, tdata in sorted(tables.items()):
        pk_cols = tdata['pk_columns']
        for ordinal, col in enumerate(tdata['columns'], 1):
            is_pk = col['name'] in pk_cols
            default_val = col['column_default']
            if col['is_generated']:
                default_val = None

            if default_val is None:
                default_sql = "NULL"
            else:
                default_sql = "'" + pg_escape(default_val) + "'"

            escaped_tname = pg_escape(tname)
            escaped_cname = pg_escape(col['name'])
            escaped_dtype = pg_escape(col['data_type'])

            lines.append(
                f"INSERT INTO schema_state VALUES ("
                f"'{escaped_tname}', '{escaped_cname}', {ordinal}, "
                f"'{escaped_dtype}', {str(col['is_nullable']).upper()}, "
                f"{default_sql}, {str(is_pk).upper()}, "
                f"{str(col['is_generated']).upper()});"
            )
        lines.append("")

    sql_content = '\n'.join(lines)

    # Write reconstruct.sql
    with open('/app/reconstruct.sql', 'w') as f:
        f.write(sql_content)

    # Execute statements individually for robustness
    for stmt in sql_content.split(';'):
        stmt = stmt.strip()
        if stmt and not stmt.startswith('--'):
            try:
                cur.execute(stmt + ';')
            except Exception as e:
                print(f"Warning: {e}")

    # Verify
    cur.execute("SELECT count(*) FROM schema_state")
    count = cur.fetchone()[0]
    print(f"schema_state populated with {count} rows")

    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
