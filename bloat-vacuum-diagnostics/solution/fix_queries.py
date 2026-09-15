#!/usr/bin/env python3
"""Fix broken PostgreSQL bloat estimation queries and create vacuum advisory function.

"""

import shutil


def fix_table_bloat_query():
    """Fix 5 bugs in the table bloat estimation query."""
    with open('/app/bloat_estimate.sql', 'r') as f:
        content = f.read()

    # Bug 1: page_hdr should be 24 (PageHeaderData is 24 bytes for PG >= 8.0)
    content = content.replace('20 AS page_hdr,', '24 AS page_hdr,')

    # Bug 2: HeapTupleHeaderData is 23 bytes, not 21
    # Bug 3: Null bitmap calculation: need (7 + count) / 8 for ceiling division
    content = content.replace(
        '21 + CASE WHEN MAX(coalesce(s.null_frac,0)) > 0 THEN count(s.attname) / 8 ELSE 0::int END',
        '23 + CASE WHEN MAX(coalesce(s.null_frac,0)) > 0 THEN ( 7 + count(s.attname) ) / 8 ELSE 0::int END'
    )

    # Bug 4: MAXALIGN must detect 64-bit platforms (8 bytes), not hardcode 4
    content = content.replace(
        '4 AS ma,',
        "CASE WHEN version()~'mingw32' OR version()~'64-bit|x86_64|ppc64|ia64|amd64' THEN 8 ELSE 4 END AS ma,"
    )

    # Bug 5: Default fillfactor for tables is 100, not 90
    content = content.replace(
        "FROM 'fillfactor=([0-9]+)')::smallint, 90) AS fillfactor,",
        "FROM 'fillfactor=([0-9]+)')::smallint, 100) AS fillfactor,"
    )

    with open('/app/bloat_estimate.sql', 'w') as f:
        f.write(content)
    print("Fixed bloat_estimate.sql: page_hdr, tpl_hdr, null_bitmap, maxalign, fillfactor")


def fix_index_bloat_query():
    """Fix 4 bugs in the B-tree index bloat estimation query."""
    with open('/app/index_bloat_estimate.sql', 'r') as f:
        content = f.read()

    # Bug 1: IndexTupleData is 8 bytes, not 4
    content = content.replace(
        'THEN 4 -- IndexTupleData size',
        'THEN 8 -- IndexTupleData size'
    )
    content = content.replace(
        'ELSE 4 + (( 32 + 8 - 1 ) / 8)',
        'ELSE 8 + (( 32 + 8 - 1 ) / 8)'
    )

    # Bug 2: BTPageOpaqueData is 16 bytes, not 8
    content = content.replace(
        '8 AS pageopqdata,',
        '16 AS pageopqdata,'
    )

    # Bug 3: Default fillfactor for btree indexes is 90, not 100
    content = content.replace(
        "from 'fillfactor=([0-9]+)')::smallint, 100) AS fillfactor,",
        "from 'fillfactor=([0-9]+)')::smallint, 90) AS fillfactor,"
    )

    # Bug 4: Restore MAXALIGN padding on data width portion of nulldatahdrwidth
    content = content.replace(
        '              + nulldatawidth\n            )::numeric AS nulldatahdrwidth',
        '              + nulldatawidth + maxalign - CASE -- Add padding to the data to align on MAXALIGN\n'
        '                  WHEN nulldatawidth = 0 THEN 0\n'
        '                  WHEN nulldatawidth::integer%maxalign = 0 THEN maxalign\n'
        '                  ELSE nulldatawidth::integer%maxalign\n'
        '                END\n'
        '            )::numeric AS nulldatahdrwidth'
    )

    with open('/app/index_bloat_estimate.sql', 'w') as f:
        f.write(content)
    print("Fixed index_bloat_estimate.sql: IndexTupleData, pageopqdata, fillfactor, data_alignment")


def install_vacuum_advisory():
    """Copy the vacuum advisory function to /app/."""
    shutil.copy('/solution/vacuum_advisory.sql', '/app/vacuum_advisory.sql')
    print("Installed vacuum_advisory.sql")


if __name__ == '__main__':
    fix_table_bloat_query()
    fix_index_bloat_query()
    install_vacuum_advisory()
    print("All fixes applied successfully.")
