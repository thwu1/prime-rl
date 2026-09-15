#!/usr/bin/env python3
"""Build SQLite database from CSV exports with data quality anomalies injected."""
import csv
import sqlite3
import os

DATA_DIR = '/app/data'
DB_PATH = os.path.join(DATA_DIR, 'perfdata.db')


def load_csv(path):
    with open(path, newline='') as f:
        return list(csv.DictReader(f))


conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

# ── sysstat ──────────────────────────────────────────────────────────────
c.execute('CREATE TABLE sysstat (name TEXT, value INTEGER, class INTEGER)')
for row in load_csv(f'{DATA_DIR}/v_sysstat.csv'):
    c.execute('INSERT INTO sysstat VALUES (?,?,?)',
              (row['name'], int(row['value']), int(row['class'])))
# ANOMALY: duplicate entry with trailing whitespace and different value
c.execute('INSERT INTO sysstat VALUES (?,?,?)',
          ('consistent gets from cache ', 45000000, 8))

# ── db_cache_advice ──────────────────────────────────────────────────────
c.execute('''CREATE TABLE db_cache_advice (
    name TEXT, block_size INTEGER, size_for_estimate INTEGER,
    buffers_for_estimate INTEGER, estd_physical_read_factor REAL,
    estd_physical_reads INTEGER, advice_status TEXT)''')
for row in load_csv(f'{DATA_DIR}/v_db_cache_advice.csv'):
    c.execute('INSERT INTO db_cache_advice VALUES (?,?,?,?,?,?,?)',
              (row['name'], int(row['block_size']), int(row['size_for_estimate']),
               int(row['buffers_for_estimate']), float(row['estd_physical_read_factor']),
               int(row['estd_physical_reads']), row['advice_status']))
# ANOMALY: corrupted row with negative physical read factor
c.execute('INSERT INTO db_cache_advice VALUES (?,?,?,?,?,?,?)',
          ('DEFAULT', 8192, 960, 122880, -0.15, -812563, 'ON'))

# ── librarycache ─────────────────────────────────────────────────────────
c.execute('''CREATE TABLE librarycache (
    namespace TEXT, pins INTEGER, pinhits INTEGER,
    reloads INTEGER, invalidations INTEGER)''')
for row in load_csv(f'{DATA_DIR}/v_librarycache.csv'):
    c.execute('INSERT INTO librarycache VALUES (?,?,?,?,?)',
              (row['namespace'], int(row['pins']), int(row['pinhits']),
               int(row['reloads']), int(row['invalidations'])))

# ── pgastat ──────────────────────────────────────────────────────────────
c.execute('CREATE TABLE pgastat (name TEXT, value TEXT, unit TEXT)')
for row in load_csv(f'{DATA_DIR}/v_pgastat.csv'):
    c.execute('INSERT INTO pgastat VALUES (?,?,?)',
              (row['name'], row['value'], row['unit']))

# ── pga_target_advice ────────────────────────────────────────────────────
c.execute('''CREATE TABLE pga_target_advice (
    pga_target_for_estimate INTEGER, pga_target_factor REAL,
    advice_status TEXT, bytes_processed INTEGER,
    estd_extra_bytes_rw INTEGER, estd_pga_cache_hit_percentage REAL,
    estd_overalloc_count INTEGER)''')
for row in load_csv(f'{DATA_DIR}/v_pga_target_advice.csv'):
    c.execute('INSERT INTO pga_target_advice VALUES (?,?,?,?,?,?,?)',
              (int(row['pga_target_for_estimate']), float(row['pga_target_factor']),
               row['advice_status'], int(row['bytes_processed']),
               int(row['estd_extra_bytes_rw']), float(row['estd_pga_cache_hit_percentage']),
               int(row['estd_overalloc_count'])))

# ── system_event ─────────────────────────────────────────────────────────
c.execute('''CREATE TABLE system_event (
    event TEXT, total_waits INTEGER, time_waited_micro INTEGER,
    avg_wait_micro INTEGER, wait_class TEXT)''')
for row in load_csv(f'{DATA_DIR}/v_system_event.csv'):
    c.execute('INSERT INTO system_event VALUES (?,?,?,?,?)',
              (row['event'], int(row['total_waits']), int(row['time_waited_micro']),
               int(row['avg_wait_micro']), row['wait_class']))

# ── sqlarea ──────────────────────────────────────────────────────────────
c.execute('''CREATE TABLE sqlarea (
    sql_id TEXT, plan_hash_value INTEGER, executions INTEGER,
    buffer_gets INTEGER, disk_reads INTEGER, rows_processed INTEGER,
    elapsed_time_us INTEGER, cpu_time_us INTEGER, module TEXT, sql_text TEXT)''')
for row in load_csv(f'{DATA_DIR}/v_sqlarea.csv'):
    c.execute('INSERT INTO sqlarea VALUES (?,?,?,?,?,?,?,?,?,?)',
              (row['sql_id'], int(row['plan_hash_value']), int(row['executions']),
               int(row['buffer_gets']), int(row['disk_reads']),
               int(row['rows_processed']), int(row['elapsed_time_us']),
               int(row['cpu_time_us']), row['module'], row['sql_text']))

# ── parameter ────────────────────────────────────────────────────────────
c.execute('CREATE TABLE parameter (name TEXT, value TEXT, description TEXT)')
for row in load_csv(f'{DATA_DIR}/v_parameter.csv'):
    c.execute('INSERT INTO parameter VALUES (?,?,?)',
              (row['name'], row['value'], row['description']))

# ── segment_statistics ───────────────────────────────────────────────────
c.execute('''CREATE TABLE segment_statistics (
    owner TEXT, object_name TEXT, object_type TEXT,
    statistic_name TEXT, value INTEGER)''')
for row in load_csv(f'{DATA_DIR}/v_segment_statistics.csv'):
    c.execute('INSERT INTO segment_statistics VALUES (?,?,?,?,?)',
              (row['owner'], row['object_name'], row['object_type'],
               row['statistic_name'], int(row['value'])))

# ── waitstat ─────────────────────────────────────────────────────────────
c.execute('CREATE TABLE waitstat (class TEXT, count INTEGER, time INTEGER)')
for row in load_csv(f'{DATA_DIR}/v_waitstat.csv'):
    c.execute('INSERT INTO waitstat VALUES (?,?,?)',
              (row['class'], int(row['count']), int(row['time'])))

# ── sgastat ──────────────────────────────────────────────────────────────
c.execute('CREATE TABLE sgastat (pool TEXT, name TEXT, bytes INTEGER)')
for row in load_csv(f'{DATA_DIR}/v_sgastat.csv'):
    bytes_str = row.get('bytes', '').strip()
    if not bytes_str:
        continue
    c.execute('INSERT INTO sgastat VALUES (?,?,?)',
              (row.get('pool', '').strip(), row.get('name', '').strip(), int(bytes_str)))

conn.commit()
conn.close()
print("SQLite database created at", DB_PATH)
