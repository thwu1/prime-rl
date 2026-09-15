#!/usr/bin/env python3
"""
Setup the network control plane environment and simulate a maintenance failure.

This script:
1. Creates the SQLite database with topology, nodes, links, and routes
2. Generates a route_audit_log table with operational history
3. Generates the control plane log (then truncates it to simulate log archive deletion)
4. Creates a PCAP file with captured route-sync HTTP traffic
5. Creates router cache files (some correct, some stale, some deleted)
6. Generates a corrupted backup file
7. Breaks the database (drops routes table)
8. Corrupts topology.json (changes a link cost)
9. Corrupts audit log entries (maintenance "normalization")
10. Creates stale PID files and corrupted server config
"""

import json
import os
import sqlite3
import struct
import socket
import datetime

# === Directory Setup ===
for d in ['/app/db', '/app/logs', '/app/routers/cache',
          '/app/config/backup', '/app/forensics', '/var/run']:
    os.makedirs(d, exist_ok=True)

# === The 30 correct routes (computed from topology + 1 manual override) ===
CORRECT_ROUTES = [
    ('api', '10.0.1.0/24', 'gateway', 10, 'active'),
    ('api', '10.0.2.0/24', 'auth', 10, 'active'),
    ('api', '10.0.4.0/24', 'compute-east', 10, 'active'),
    ('api', '10.0.5.0/24', 'compute-west', 10, 'active'),
    ('api', '10.0.6.0/24', 'compute-east', 20, 'active'),
    ('auth', '10.0.1.0/24', 'gateway', 10, 'active'),
    ('auth', '10.0.3.0/24', 'api', 10, 'active'),
    ('auth', '10.0.4.0/24', 'api', 20, 'active'),
    ('auth', '10.0.5.0/24', 'api', 20, 'active'),
    ('auth', '10.0.6.0/24', 'api', 30, 'active'),
    ('compute-east', '10.0.1.0/24', 'api', 20, 'active'),
    ('compute-east', '10.0.2.0/24', 'api', 20, 'active'),
    ('compute-east', '10.0.3.0/24', 'api', 10, 'active'),
    ('compute-east', '10.0.5.0/24', 'api', 20, 'active'),
    ('compute-east', '10.0.6.0/24', 'storage', 10, 'active'),
    ('compute-west', '10.0.1.0/24', 'api', 20, 'active'),
    ('compute-west', '10.0.2.0/24', 'api', 20, 'active'),
    ('compute-west', '10.0.3.0/24', 'api', 10, 'active'),
    ('compute-west', '10.0.4.0/24', 'storage', 15, 'active'),  # Manual override
    ('compute-west', '10.0.6.0/24', 'storage', 10, 'active'),
    ('gateway', '10.0.2.0/24', 'auth', 10, 'active'),
    ('gateway', '10.0.3.0/24', 'api', 10, 'active'),
    ('gateway', '10.0.4.0/24', 'api', 20, 'active'),
    ('gateway', '10.0.5.0/24', 'api', 20, 'active'),
    ('gateway', '10.0.6.0/24', 'api', 30, 'active'),
    ('storage', '10.0.1.0/24', 'compute-east', 30, 'active'),
    ('storage', '10.0.2.0/24', 'compute-east', 30, 'active'),
    ('storage', '10.0.3.0/24', 'compute-east', 20, 'active'),
    ('storage', '10.0.4.0/24', 'compute-east', 10, 'active'),
    ('storage', '10.0.5.0/24', 'compute-west', 10, 'active'),
]

NODE_IPS = {
    'gateway': '10.0.1.1',
    'auth': '10.0.2.1',
    'api': '10.0.3.1',
    'compute-east': '10.0.4.1',
    'compute-west': '10.0.5.1',
    'storage': '10.0.6.1',
}

# =====================================================================
# Step 1: Create the SQLite database with correct topology data
# =====================================================================
DB_PATH = '/app/db/network.db'
conn = sqlite3.connect(DB_PATH)

conn.execute('''CREATE TABLE nodes (
    name TEXT PRIMARY KEY,
    subnet TEXT NOT NULL,
    role TEXT NOT NULL
)''')

conn.execute('''CREATE TABLE links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_a TEXT NOT NULL,
    node_b TEXT NOT NULL,
    cost INTEGER NOT NULL
)''')

with open('/app/config/topology.json') as f:
    topology = json.load(f)

for node in topology['nodes']:
    conn.execute('INSERT INTO nodes VALUES (?, ?, ?)',
                 (node['name'], node['subnet'], node['role']))

for link in topology['links']:
    conn.execute('INSERT INTO links (node_a, node_b, cost) VALUES (?, ?, ?)',
                 (link['node_a'], link['node_b'], link['cost']))

conn.commit()

# =====================================================================
# Step 2: Create route_audit_log table with operational history
# =====================================================================
conn.execute('''CREATE TABLE route_audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    operation TEXT NOT NULL,
    source_node TEXT NOT NULL,
    destination_network TEXT NOT NULL,
    old_next_hop TEXT,
    old_metric INTEGER,
    new_next_hop TEXT,
    new_metric INTEGER,
    changed_by TEXT DEFAULT 'system',
    change_reason TEXT
)''')

# INSERT entries for all 30 routes at startup
base_ts = datetime.datetime(2024, 3, 15, 8, 0, 6)
for i, r in enumerate(CORRECT_ROUTES):
    src, dst, nhop, metric, status = r
    # For the override route, log the COMPUTED value first (api/20)
    if src == 'compute-west' and dst == '10.0.4.0/24':
        initial_nhop, initial_metric = 'api', 20
    else:
        initial_nhop, initial_metric = nhop, metric
    ts = (base_ts + datetime.timedelta(milliseconds=i * 50)).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    conn.execute(
        'INSERT INTO route_audit_log (timestamp, operation, source_node, destination_network, '
        'old_next_hop, old_metric, new_next_hop, new_metric, changed_by, change_reason) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (ts, 'INSERT', src, dst, None, None, initial_nhop, initial_metric,
         'route_manager', 'Initial route computation from topology')
    )

# UPDATE entry for the manual override
override_ts = '2024-03-15 14:07:22.000'
conn.execute(
    'INSERT INTO route_audit_log (timestamp, operation, source_node, destination_network, '
    'old_next_hop, old_metric, new_next_hop, new_metric, changed_by, change_reason) '
    'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
    (override_ts, 'UPDATE', 'compute-west', '10.0.4.0/24', 'api', 20, 'storage', 15,
     'admin@infra-team', 'Dedicated 10G cross-connect provisioned (ticket: OPS-4521)')
)

conn.commit()

# =====================================================================
# Step 3: Generate the control_plane.log (post-truncation version)
# =====================================================================
# The maintenance script archived and deleted the original log.
# The current log only contains the maintenance failure entries.
log_lines = []

maint_ts = datetime.datetime(2024, 3, 16, 2, 0, 0)
log_lines.append(f"{maint_ts.strftime('%Y-%m-%d %H:%M:%S')} INFO  maintenance: === MAINTENANCE WINDOW START (OPS-4890) ===")
ts = maint_ts + datetime.timedelta(seconds=0)
log_lines.append(f"{ts.strftime('%Y-%m-%d %H:%M:%S')} INFO  maintenance: Control plane log archived to control_plane.log.bak")
ts = maint_ts + datetime.timedelta(seconds=1)
log_lines.append(f"{ts.strftime('%Y-%m-%d %H:%M:%S')} INFO  maintenance: Running schema migration: adding priority column to routes table")
ts = maint_ts + datetime.timedelta(seconds=3)
log_lines.append(f"{ts.strftime('%Y-%m-%d %H:%M:%S')} ERROR maintenance: ALTER TABLE failed: duplicate column name: priority")
ts = maint_ts + datetime.timedelta(seconds=4)
log_lines.append(f"{ts.strftime('%Y-%m-%d %H:%M:%S')} WARN  maintenance: Initiating migration rollback strategy B")
ts = maint_ts + datetime.timedelta(seconds=5)
log_lines.append(f"{ts.strftime('%Y-%m-%d %H:%M:%S')} ERROR maintenance: DROP TABLE routes executed during rollback")
ts = maint_ts + datetime.timedelta(seconds=6)
log_lines.append(f"{ts.strftime('%Y-%m-%d %H:%M:%S')} CRITICAL maintenance: routes table has been dropped - data loss confirmed")
ts = maint_ts + datetime.timedelta(seconds=7)
log_lines.append(f"{ts.strftime('%Y-%m-%d %H:%M:%S')} INFO  maintenance: Created routes_new table with updated schema")
ts = maint_ts + datetime.timedelta(seconds=7)
log_lines.append(f"{ts.strftime('%Y-%m-%d %H:%M:%S')} ERROR maintenance: JSON import into routes_new failed - syntax error in import command")
ts = maint_ts + datetime.timedelta(seconds=8)
log_lines.append(f"{ts.strftime('%Y-%m-%d %H:%M:%S')} WARN  maintenance: routes_new table renamed to routes (empty)")
ts = maint_ts + datetime.timedelta(seconds=8)
log_lines.append(f"{ts.strftime('%Y-%m-%d %H:%M:%S')} ERROR maintenance: Backup restoration failed - integrity check error during validation pass")
ts = maint_ts + datetime.timedelta(seconds=8)
log_lines.append(f"{ts.strftime('%Y-%m-%d %H:%M:%S')} INFO  maintenance: Adjusting compute-east/storage link cost to 15 for QoS simulation")
ts = maint_ts + datetime.timedelta(seconds=9)
log_lines.append(f"{ts.strftime('%Y-%m-%d %H:%M:%S')} INFO  maintenance: Topology updated: compute-east/storage link cost 10 -> 15")
ts = maint_ts + datetime.timedelta(seconds=9)
log_lines.append(f"{ts.strftime('%Y-%m-%d %H:%M:%S')} INFO  maintenance: Normalizing audit log entries for migration consistency...")
ts = maint_ts + datetime.timedelta(seconds=9)
log_lines.append(f"{ts.strftime('%Y-%m-%d %H:%M:%S')} WARN  maintenance: Updated 8 audit log entries (gateway/storage source nodes)")
ts = maint_ts + datetime.timedelta(seconds=9)
log_lines.append(f"{ts.strftime('%Y-%m-%d %H:%M:%S')} WARN  maintenance: Server config updated to maintenance port 5099")
ts = maint_ts + datetime.timedelta(seconds=10)
log_lines.append(f"{ts.strftime('%Y-%m-%d %H:%M:%S')} INFO  maintenance: Cleaning up old log files...")
ts = maint_ts + datetime.timedelta(seconds=10)
log_lines.append(f"{ts.strftime('%Y-%m-%d %H:%M:%S')} INFO  maintenance: Removed archived log: /app/logs/control_plane.log.bak")
ts = maint_ts + datetime.timedelta(seconds=10)
log_lines.append(f"{ts.strftime('%Y-%m-%d %H:%M:%S')} CRITICAL control_plane: OperationalError: no such table: routes")
ts = maint_ts + datetime.timedelta(seconds=11)
log_lines.append(f"{ts.strftime('%Y-%m-%d %H:%M:%S')} ERROR control_plane: Multiple API endpoints returning 500 errors")
ts = maint_ts + datetime.timedelta(seconds=12)
log_lines.append(f"{ts.strftime('%Y-%m-%d %H:%M:%S')} ERROR router_manager: Router 'api' reported connection error: 500 Internal Server Error")
ts = maint_ts + datetime.timedelta(seconds=13)
log_lines.append(f"{ts.strftime('%Y-%m-%d %H:%M:%S')} ERROR router_manager: Router 'storage' reported connection error: 500 Internal Server Error")
ts = maint_ts + datetime.timedelta(seconds=15)
log_lines.append(f"{ts.strftime('%Y-%m-%d %H:%M:%S')} CRITICAL control_plane: Server shutting down due to unrecoverable database errors")
ts = maint_ts + datetime.timedelta(seconds=15)
log_lines.append(f"{ts.strftime('%Y-%m-%d %H:%M:%S')} CRITICAL maintenance: Maintenance FAILED. Manual intervention required.")

with open('/app/logs/control_plane.log', 'w') as f:
    f.write('\n'.join(log_lines) + '\n')

# =====================================================================
# Step 4: Generate maintenance log
# =====================================================================
maint_log = """[2024-03-16 02:00:00] Starting scheduled maintenance: routes table schema migration (OPS-4890)
[2024-03-16 02:00:00] Archived control_plane.log to control_plane.log.bak
[2024-03-16 02:00:01] Step 1: Creating routes backup...
[2024-03-16 02:00:02] Backup written to /app/config/backup/routes_backup.json (30 entries)
[2024-03-16 02:00:03] Step 2: Attempting to add priority column...
[2024-03-16 02:00:03] ERROR: ALTER TABLE failed - column 'priority' may already exist from dry-run
[2024-03-16 02:00:04] Attempting migration rollback strategy B...
[2024-03-16 02:00:05] CRITICAL: Routes table dropped during rollback!
[2024-03-16 02:00:05] Created routes_new table with updated schema
[2024-03-16 02:00:05] ERROR: JSON import into routes_new failed - syntax error in import statement
[2024-03-16 02:00:06] WARNING: routes_new table is empty, rename to routes succeeded
[2024-03-16 02:00:06] Attempting recovery from backup...
[2024-03-16 02:00:07] Running backup validation/normalization pass...
[2024-03-16 02:00:07] WARNING: Backup validation modified 6 entries (normalization applied)
[2024-03-16 02:00:08] ERROR: Backup file may be corrupted after validation pass
[2024-03-16 02:00:08] Step 3: Adjusting topology for QoS simulation...
[2024-03-16 02:00:08] Topology updated: compute-east/storage link cost 10 -> 15
[2024-03-16 02:00:08] NOTE: This change is temporary and should be reverted after QoS benchmarks
[2024-03-16 02:00:08] Step 4: Switching to maintenance port 5099...
[2024-03-16 02:00:09] Server config updated: port 5000 -> 5099
[2024-03-16 02:00:09] Step 5: Normalizing audit log entries for migration...
[2024-03-16 02:00:09] WARNING: Updated 8 audit log entries (gateway/storage source nodes set to migration-staging)
[2024-03-16 02:00:09] Step 6: Cleaning up old log files...
[2024-03-16 02:00:10] Removed archived log: /app/logs/control_plane.log.bak
[2024-03-16 02:00:10] Maintenance script finished. MANUAL REVIEW REQUIRED.
[2024-03-16 02:00:10] NOTE: The following issues need manual resolution:
[2024-03-16 02:00:10]   - routes table data must be reconstructed from available sources
[2024-03-16 02:00:10]   - backup file integrity must be verified (6 entries may be corrupted)
[2024-03-16 02:00:10]   - topology link cost change must be reviewed and possibly reverted
[2024-03-16 02:00:10]   - audit log modifications must be validated (8 entries changed)
[2024-03-16 02:00:10]   - server.ini port must be reverted to production value (5000)
[2024-03-16 02:00:10]   - archived control_plane.log was deleted - original route data may be lost
[2024-03-16 02:00:10]   - all daemons need restart after recovery
"""
with open('/app/logs/maintenance.log', 'w') as f:
    f.write(maint_log)

# =====================================================================
# Step 5: Generate PCAP file with route-sync HTTP traffic
# =====================================================================
# The monitoring agent captured API responses before the maintenance window.
# This PCAP contains route sync responses for gateway and storage nodes.

def ip_checksum(header_bytes):
    """Compute IP header checksum."""
    if len(header_bytes) % 2:
        header_bytes += b'\x00'
    words = struct.unpack('!%dH' % (len(header_bytes) // 2), header_bytes)
    total = sum(words)
    while total >> 16:
        total = (total & 0xffff) + (total >> 16)
    return (~total) & 0xffff


def make_packet(src_ip, dst_ip, sport, dport, payload, seq=1):
    """Create an Ethernet+IP+TCP packet with given payload."""
    payload_bytes = payload.encode() if isinstance(payload, str) else payload

    # TCP header (20 bytes, no options)
    tcp_hdr = struct.pack('!HHIIBBHHH',
        sport, dport,
        seq, 1,
        0x50, 0x18,  # data offset = 5 words, flags = PSH+ACK
        65535, 0, 0
    )

    tcp_data = tcp_hdr + payload_bytes
    total_len = 20 + len(tcp_data)

    # IP header with checksum = 0 first
    ip_hdr = struct.pack('!BBHHHBBH4s4s',
        0x45, 0, total_len,
        0, 0x4000,
        64, 6, 0,
        socket.inet_aton(src_ip),
        socket.inet_aton(dst_ip)
    )
    # Compute and patch IP checksum
    cksum = ip_checksum(ip_hdr)
    ip_hdr = ip_hdr[:10] + struct.pack('!H', cksum) + ip_hdr[12:]

    # Ethernet header
    eth_hdr = struct.pack('!6s6sH',
        b'\x00\x50\x56\x00\x00\x01',
        b'\x00\x50\x56\x00\x00\x02',
        0x0800
    )

    return eth_hdr + ip_hdr + tcp_data


def make_http_response(body_dict_or_list, extra_headers=None):
    """Create an HTTP/1.1 200 response with JSON body."""
    body = json.dumps(body_dict_or_list)
    headers = "HTTP/1.1 200 OK\r\n"
    headers += "Content-Type: application/json\r\n"
    headers += f"Content-Length: {len(body)}\r\n"
    if extra_headers:
        for k, v in extra_headers.items():
            headers += f"{k}: {v}\r\n"
    headers += "\r\n"
    return headers + body


def write_pcap(filepath, packets):
    """Write a PCAP file. packets: list of (timestamp_sec, raw_bytes)."""
    with open(filepath, 'wb') as f:
        # Global header: magic, version 2.4, timezone 0, sigfigs 0, snaplen 65535, LINKTYPE_ETHERNET
        f.write(struct.pack('<IHHiIII', 0xa1b2c3d4, 2, 4, 0, 0, 65535, 1))
        for ts, data in packets:
            ts_sec = int(ts)
            ts_usec = int((ts - ts_sec) * 1000000)
            f.write(struct.pack('<IIII', ts_sec, ts_usec, len(data), len(data)))
            f.write(data)


# Build PCAP packets
# Base timestamp: 2024-03-15 16:00:00 UTC = 1710518400
pcap_base_ts = 1710518400.0
ctrl_ip = NODE_IPS['api']  # 10.0.3.1 - control plane server
pcap_packets = []

# Packet 1: Health check response to gateway
health_resp = make_http_response(
    {"status": "healthy", "route_count": 30},
    {"X-Health-Check": "periodic", "X-Node": "gateway"}
)
pkt = make_packet(ctrl_ip, NODE_IPS['gateway'], 5000, 44100, health_resp)
pcap_packets.append((pcap_base_ts + 0.0, pkt))

# Packet 2: Route sync response to gateway (5 routes)
gw_routes = [{'source_node': r[0], 'destination_network': r[1],
              'next_hop_node': r[2], 'metric': r[3], 'status': r[4]}
             for r in CORRECT_ROUTES if r[0] == 'gateway']
route_resp = make_http_response(gw_routes, {"X-Sync-Node": "gateway", "X-Sync-Time": "2024-03-15T16:00:12Z"})
pkt = make_packet(ctrl_ip, NODE_IPS['gateway'], 5000, 44101, route_resp, seq=1001)
pcap_packets.append((pcap_base_ts + 12.0, pkt))

# Packet 3: Health check response to auth
health_resp = make_http_response(
    {"status": "healthy", "route_count": 30},
    {"X-Health-Check": "periodic", "X-Node": "auth"}
)
pkt = make_packet(ctrl_ip, NODE_IPS['auth'], 5000, 44200, health_resp)
pcap_packets.append((pcap_base_ts + 13.0, pkt))

# Packet 4: Route sync response to storage (5 routes)
st_routes = [{'source_node': r[0], 'destination_network': r[1],
              'next_hop_node': r[2], 'metric': r[3], 'status': r[4]}
             for r in CORRECT_ROUTES if r[0] == 'storage']
route_resp = make_http_response(st_routes, {"X-Sync-Node": "storage", "X-Sync-Time": "2024-03-15T16:00:15Z"})
pkt = make_packet(ctrl_ip, NODE_IPS['storage'], 5000, 44301, route_resp, seq=2001)
pcap_packets.append((pcap_base_ts + 15.0, pkt))

# Packet 5: Health check response to storage
health_resp = make_http_response(
    {"status": "healthy", "route_count": 30},
    {"X-Health-Check": "periodic", "X-Node": "storage"}
)
pkt = make_packet(ctrl_ip, NODE_IPS['storage'], 5000, 44302, health_resp)
pcap_packets.append((pcap_base_ts + 20.0, pkt))

# Packet 6: Route sync response to auth (5 routes - provides cross-validation data)
auth_routes = [{'source_node': r[0], 'destination_network': r[1],
                'next_hop_node': r[2], 'metric': r[3], 'status': r[4]}
               for r in CORRECT_ROUTES if r[0] == 'auth']
route_resp = make_http_response(auth_routes, {"X-Sync-Node": "auth", "X-Sync-Time": "2024-03-15T16:00:25Z"})
pkt = make_packet(ctrl_ip, NODE_IPS['auth'], 5000, 44201, route_resp, seq=3001)
pcap_packets.append((pcap_base_ts + 25.0, pkt))

write_pcap('/app/forensics/capture.pcap', pcap_packets)

# =====================================================================
# Step 6: Generate router cache files
# =====================================================================
# gateway cache - correct
gw_cache = [{'source_node': r[0], 'destination_network': r[1],
             'next_hop_node': r[2], 'metric': r[3], 'status': r[4]}
            for r in CORRECT_ROUTES if r[0] == 'gateway']
with open('/app/routers/cache/gateway.json', 'w') as f:
    json.dump(gw_cache, f, indent=2)

# compute-east cache - correct
ce_cache = [{'source_node': r[0], 'destination_network': r[1],
             'next_hop_node': r[2], 'metric': r[3], 'status': r[4]}
            for r in CORRECT_ROUTES if r[0] == 'compute-east']
with open('/app/routers/cache/compute-east.json', 'w') as f:
    json.dump(ce_cache, f, indent=2)

# compute-west cache - STALE (has pre-override value for 10.0.4.0/24)
cw_cache = []
for r in CORRECT_ROUTES:
    if r[0] == 'compute-west':
        if r[1] == '10.0.4.0/24':
            cw_cache.append({'source_node': r[0], 'destination_network': r[1],
                             'next_hop_node': 'api', 'metric': 20, 'status': 'active'})
        else:
            cw_cache.append({'source_node': r[0], 'destination_network': r[1],
                             'next_hop_node': r[2], 'metric': r[3], 'status': r[4]})
with open('/app/routers/cache/compute-west.json', 'w') as f:
    json.dump(cw_cache, f, indent=2)

# auth cache - DELETED (simulates loss during maintenance)
# api cache - DELETED
# storage cache - DELETED

# =====================================================================
# Step 7: Generate corrupted backup file
# =====================================================================
backup_routes = []
for r in CORRECT_ROUTES:
    entry = {'source_node': r[0], 'destination_network': r[1],
             'next_hop_node': r[2], 'metric': r[3], 'status': r[4]}
    dst_id = int(r[1].split('.')[2])
    src_zone = r[0].split('-')[0] if '-' in r[0] else 'core'
    if dst_id <= 3 and src_zone != 'core':
        entry['next_hop_node'] = 'gateway'  # Corruption from maintenance "validation"
    backup_routes.append(entry)

with open('/app/config/backup/routes_backup.json', 'w') as f:
    json.dump(backup_routes, f, indent=2)

# =====================================================================
# Step 8: Break the database - simulate maintenance script effects
# =====================================================================
conn.execute('DROP TABLE IF EXISTS routes')
conn.execute('''CREATE TABLE routes_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_node TEXT NOT NULL,
    destination_network TEXT NOT NULL,
    next_hop_node TEXT NOT NULL,
    metric INTEGER NOT NULL,
    priority INTEGER DEFAULT 100,
    status TEXT DEFAULT 'active',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_node, destination_network)
)''')
conn.commit()

# =====================================================================
# Step 9: Corrupt audit log entries (maintenance "normalization")
# =====================================================================
# The maintenance script "normalized" 8 audit log entries for gateway and
# storage source nodes by setting new_next_hop to 'migration-staging'.
# This simulates the maintenance script preparing for a staging migration
# that was never completed.
corrupted_entries = [
    ('gateway', '10.0.2.0/24'),
    ('gateway', '10.0.3.0/24'),
    ('gateway', '10.0.4.0/24'),
    ('storage', '10.0.1.0/24'),
    ('storage', '10.0.2.0/24'),
    ('storage', '10.0.3.0/24'),
    ('storage', '10.0.4.0/24'),
    ('storage', '10.0.5.0/24'),
]
for src, dst in corrupted_entries:
    conn.execute(
        'UPDATE route_audit_log SET new_next_hop = ? '
        'WHERE source_node = ? AND destination_network = ? AND operation = ?',
        ('migration-staging', src, dst, 'INSERT')
    )

# Add misleading post-maintenance entries
maint_ts_str = '2024-03-16 02:00:07.000'
# DELETE entries from DROP TABLE
for r in CORRECT_ROUTES:
    conn.execute(
        'INSERT INTO route_audit_log (timestamp, operation, source_node, destination_network, '
        'old_next_hop, old_metric, new_next_hop, new_metric, changed_by, change_reason) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (maint_ts_str, 'DELETE', r[0], r[1], r[2], r[3], None, None,
         'maintenance_script', 'Table dropped during rollback strategy B')
    )
# Failed INSERT attempts with wrong data
for r in CORRECT_ROUTES[:8]:
    ts = '2024-03-16 02:00:08.000'
    conn.execute(
        'INSERT INTO route_audit_log (timestamp, operation, source_node, destination_network, '
        'old_next_hop, old_metric, new_next_hop, new_metric, changed_by, change_reason) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (ts, 'INSERT', r[0], r[1], None, None, 'migration-staging', 999,
         'maintenance_script', 'Migration staging insert (failed)')
    )

conn.commit()
conn.close()

# =====================================================================
# Step 10: Corrupt topology.json (change link cost)
# =====================================================================
with open('/app/config/topology.json') as f:
    topo = json.load(f)

for link in topo['links']:
    if set([link['node_a'], link['node_b']]) == set(['compute-east', 'storage']):
        link['cost'] = 15  # Changed from 10 to 15 by maintenance script

with open('/app/config/topology.json', 'w') as f:
    json.dump(topo, f, indent=2)

# =====================================================================
# Step 11: Create corrupted server.ini
# =====================================================================
server_ini = """[server]
host = 0.0.0.0
port = 5099
db_path = /app/db/network.db
log_file = /app/logs/control_plane.log

[health]
check_interval = 30
pid_file = /var/run/control_plane.pid

[routers]
cache_dir = /app/routers/cache
"""
with open('/app/config/server.ini', 'w') as f:
    f.write(server_ini)

# =====================================================================
# Step 12: Create stale PID files
# =====================================================================
stale_pids = {
    '/var/run/control_plane.pid': '99999',
    '/var/run/router_gateway.pid': '99998',
    '/var/run/router_api.pid': '99997',
    '/var/run/router_storage.pid': '99996',
}
for pid_file, pid in stale_pids.items():
    with open(pid_file, 'w') as f:
        f.write(pid)

print("Environment setup complete. System is in broken state.")
print("  - Database: routes table dropped, routes_new is empty")
print("  - Audit log: 8 entries corrupted (gateway/storage -> migration-staging)")
print("  - Audit log: misleading maintenance entries added")
print("  - Topology: compute-east/storage link cost changed 10 -> 15")
print("  - Backup: 6 of 30 entries corrupted")
print("  - Config: server port changed to 5099")
print("  - Caches: api/auth/storage caches deleted, compute-west cache stale")
print("  - Log: original log deleted, only maintenance failure entries remain")
print("  - PCAP: route-sync traffic captured for gateway and storage nodes")
print("  - PID files: 4 stale PID files created")
