"""Simple SQL parser producing logical plan trees."""

import re
from .types import TableID, FieldID, FilterCondition, LPScan, LPProject, LPJoin, LPFilter


def parse_sql(sql):
    """Parse a simplified SQL SELECT ... FROM ... JOIN ... ON ... WHERE ... query."""
    sql = ' '.join(sql.split()).strip()

    # ── SELECT fields ──
    m = re.match(r'SELECT\s+(.+?)\s+FROM\s+', sql, re.IGNORECASE)
    if not m:
        raise ValueError(f"Cannot parse SELECT clause: {sql}")
    fields = []
    for f in m.group(1).split(','):
        tbl, col = [x.strip() for x in f.strip().split('.')]
        fields.append(FieldID(TableID(tbl), col))
    rest = sql[m.end():].strip()

    # ── FROM table ──
    m = re.match(r'(\w+)', rest)
    if not m:
        raise ValueError(f"Cannot parse FROM table: {rest}")
    plan = LPScan(TableID(m.group(1)))
    rest = rest[m.end():].strip()

    # ── JOINs ──
    join_re = re.compile(
        r'JOIN\s+(\w+)\s+ON\s+([\w.]+)\s*=\s*([\w.]+)', re.IGNORECASE
    )
    while True:
        m = join_re.match(rest)
        if not m:
            break
        right = LPScan(TableID(m.group(1)))
        lt, lc = m.group(2).split('.')
        rt, rc = m.group(3).split('.')
        on = [(FieldID(TableID(lt), lc), FieldID(TableID(rt), rc))]
        plan = LPJoin(plan, right, on)
        rest = rest[m.end():].strip()

    # ── Wrap in PROJECT ──
    proj = LPProject(fields, plan)

    # ── WHERE (optional) ──
    m = re.match(r'WHERE\s+(.+?)$', rest, re.IGNORECASE)
    if m:
        conditions = []
        parts = re.split(r'\s+AND\s+', m.group(1), flags=re.IGNORECASE)
        for p in parts:
            cm = re.match(r'([\w.]+)\s*(=|!=|<=|>=|<|>)\s*(.+)', p.strip())
            if not cm:
                raise ValueError(f"Cannot parse WHERE condition: {p}")
            ft, fc = cm.group(1).split('.')
            op = cm.group(2)
            val = cm.group(3).strip().strip("'\"")
            try:
                val = int(val)
            except ValueError:
                try:
                    val = float(val)
                except ValueError:
                    pass
            conditions.append(FilterCondition(FieldID(TableID(ft), fc), op, val))
        # Insert Filter between Project and its source
        proj = LPProject(proj.fields, LPFilter(conditions, proj.child))

    return proj
