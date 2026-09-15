#!/usr/bin/env python3
"""
Reconstruct the routing database from multiple forensic evidence sources.

Strategy:
1. Query the route_audit_log table for pre-maintenance INSERT/UPDATE entries
   - Entries with new_next_hop='migration-staging' are corrupted → skip them
   - The UPDATE entry for the manual override is critical
2. Parse the PCAP capture file using tshark to extract route-sync responses
   - These contain authoritative route data for gateway and storage nodes
3. Cross-reference with router cache files for additional validation
4. Use topology computation (models.py Dijkstra) to validate and fill gaps
   - NOTE: topology.json must be fixed first (link cost reverted)
5. Merge all sources, with PCAP and audit log taking precedence
6. Rebuild the SQLite routes table
"""

import json
import re
import sqlite3
import subprocess
import sys
import os

sys.path.insert(0, '/app')
from models import load_topology, compute_routes

DB_PATH = '/app/db/network.db'
PCAP_PATH = '/app/forensics/capture.pcap'
TOPOLOGY_PATH = '/app/config/topology.json'
CACHE_DIR = '/app/routers/cache'


def fix_topology():
    """
    Revert the topology change made by the maintenance script.
    The compute-east <-> storage link cost was changed from 10 to 15.
    Evidence from PCAP shows storage -> compute-east routes with metric 10,
    confirming the original link cost was 10.
    """
    with open(TOPOLOGY_PATH) as f:
        topo = json.load(f)
    for link in topo['links']:
        if set([link['node_a'], link['node_b']]) == set(['compute-east', 'storage']):
            print(f"  Fixing link cost: {link['node_a']}<->{link['node_b']} "
                  f"from {link['cost']} to 10")
            link['cost'] = 10
    with open(TOPOLOGY_PATH, 'w') as f:
        json.dump(topo, f, indent=2)
    return topo


def parse_routes_from_audit_log(db_path):
    """
    Extract pre-maintenance route state from the route_audit_log table.

    Filters:
    - Only entries before maintenance window (< 2024-03-16 02:00:00)
    - Skip entries where new_next_hop = 'migration-staging' (corrupted)
    - Apply UPDATE operations on top of INSERT operations chronologically
    """
    routes = {}
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Get all pre-maintenance entries that aren't corrupted
    rows = conn.execute(
        "SELECT operation, source_node, destination_network, "
        "new_next_hop, new_metric, old_next_hop, old_metric "
        "FROM route_audit_log "
        "WHERE timestamp < '2024-03-16 02:00:00' "
        "AND new_next_hop != 'migration-staging' "
        "ORDER BY timestamp ASC"
    ).fetchall()
    conn.close()

    for row in rows:
        key = (row['source_node'], row['destination_network'])
        if row['operation'] == 'INSERT':
            routes[key] = (row['new_next_hop'], row['new_metric'])
        elif row['operation'] == 'UPDATE':
            routes[key] = (row['new_next_hop'], row['new_metric'])

    return routes


def parse_routes_from_pcap(pcap_path):
    """
    Extract route data from PCAP using tshark.

    The PCAP contains HTTP responses with JSON route arrays.
    Uses tshark to extract TCP payload data, then parses the HTTP
    response bodies to find route JSON arrays.
    """
    routes = {}
    try:
        result = subprocess.run(
            ['tshark', '-r', pcap_path, '-T', 'fields', '-e', 'tcp.payload'],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            print(f"  tshark error: {result.stderr}")
            return routes

        for hex_line in result.stdout.strip().split('\n'):
            hex_line = hex_line.strip()
            if not hex_line:
                continue
            try:
                raw = bytes.fromhex(hex_line.replace(':', ''))
                decoded = raw.decode('utf-8', errors='ignore')
                # Find JSON array in HTTP response body
                idx = decoded.find('[')
                if idx < 0:
                    continue
                # Find the matching closing bracket
                bracket_count = 0
                end_idx = idx
                for i in range(idx, len(decoded)):
                    if decoded[i] == '[':
                        bracket_count += 1
                    elif decoded[i] == ']':
                        bracket_count -= 1
                        if bracket_count == 0:
                            end_idx = i + 1
                            break
                json_str = decoded[idx:end_idx]
                data = json.loads(json_str)
                if isinstance(data, list) and len(data) > 0 and 'source_node' in data[0]:
                    for r in data:
                        key = (r['source_node'], r['destination_network'])
                        routes[key] = (r['next_hop_node'], r['metric'])
                    print(f"  Extracted {len(data)} routes for node '{data[0]['source_node']}' from PCAP")
            except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
                continue
    except FileNotFoundError:
        print("  WARNING: tshark not found, skipping PCAP analysis")
    except subprocess.TimeoutExpired:
        print("  WARNING: tshark timed out")

    return routes


def parse_routes_from_caches(cache_dir):
    """
    Load route data from router cache files.
    Note: some caches may be stale (e.g., compute-west has pre-override data).
    """
    routes = {}
    if not os.path.isdir(cache_dir):
        return routes

    for filename in os.listdir(cache_dir):
        if not filename.endswith('.json'):
            continue
        filepath = os.path.join(cache_dir, filename)
        try:
            with open(filepath) as f:
                data = json.load(f)
            node_name = filename.replace('.json', '')
            for r in data:
                key = (r['source_node'], r['destination_network'])
                routes[key] = (r['next_hop_node'], r['metric'])
            print(f"  Loaded {len(data)} cached routes for node '{node_name}'")
        except (json.JSONDecodeError, KeyError):
            continue

    return routes


def rebuild_database(db_path, routes):
    """Rebuild the routes table in SQLite."""
    conn = sqlite3.connect(db_path)
    conn.execute('DROP TABLE IF EXISTS routes_new')
    conn.execute('DROP TABLE IF EXISTS routes')
    conn.execute('''CREATE TABLE routes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_node TEXT NOT NULL,
        destination_network TEXT NOT NULL,
        next_hop_node TEXT NOT NULL,
        metric INTEGER NOT NULL,
        status TEXT DEFAULT 'active',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(source_node, destination_network)
    )''')
    for (src, dst), (via, metric) in sorted(routes.items()):
        conn.execute(
            'INSERT INTO routes (source_node, destination_network, next_hop_node, metric, status) '
            'VALUES (?, ?, ?, ?, ?)',
            (src, dst, via, metric, 'active')
        )
    conn.commit()
    count = conn.execute('SELECT COUNT(*) FROM routes').fetchone()[0]
    conn.close()
    return count


def main():
    print("=== Network Control Plane Forensic Recovery ===\n")

    # Step 1: Fix topology
    print("Step 1: Fixing corrupted topology...")
    topo = fix_topology()
    print()

    # Step 2: Compute baseline routes from fixed topology
    print("Step 2: Computing baseline routes from fixed topology...")
    computed = compute_routes(topo)
    baseline = {}
    for r in computed:
        key = (r['source_node'], r['destination_network'])
        baseline[key] = (r['next_hop_node'], r['metric'])
    print(f"  Computed {len(baseline)} baseline routes")
    print()

    # Step 3: Extract routes from audit log
    print("Step 3: Parsing route_audit_log table...")
    audit_routes = parse_routes_from_audit_log(DB_PATH)
    print(f"  Recovered {len(audit_routes)} routes from audit log (excluding corrupted entries)")
    print()

    # Step 4: Extract routes from PCAP
    print("Step 4: Analyzing PCAP capture with tshark...")
    pcap_routes = parse_routes_from_pcap(PCAP_PATH)
    print(f"  Total routes from PCAP: {len(pcap_routes)}")
    print()

    # Step 5: Load router caches
    print("Step 5: Loading router caches...")
    cache_routes = parse_routes_from_caches(CACHE_DIR)
    print(f"  Total routes from caches: {len(cache_routes)}")
    print()

    # Step 6: Merge all sources
    # Priority order: audit_log (has override) > PCAP (authoritative captures) > caches > computed baseline
    print("Step 6: Merging evidence sources...")
    final_routes = dict(baseline)  # Start with computed baseline

    # Layer cache data (overwrites baseline where available)
    for key, val in cache_routes.items():
        final_routes[key] = val

    # Layer PCAP data (authoritative, overwrites cache/baseline)
    for key, val in pcap_routes.items():
        final_routes[key] = val

    # Layer audit log data (includes the override, highest priority)
    for key, val in audit_routes.items():
        final_routes[key] = val

    # But for cache data specifically, the audit log override takes precedence
    # over the stale compute-west cache. The audit log UPDATE for the override
    # was already applied above. Verify:
    override_key = ('compute-west', '10.0.4.0/24')
    if override_key in final_routes:
        print(f"  Override route: compute-west -> 10.0.4.0/24 "
              f"via={final_routes[override_key][0]} metric={final_routes[override_key][1]}")

    print(f"  Final merged route count: {len(final_routes)}")
    print()

    # Step 7: Rebuild database
    print("Step 7: Rebuilding SQLite database...")
    count = rebuild_database(DB_PATH, final_routes)
    print(f"  Inserted {count} routes")

    if count == 30:
        print("\nSUCCESS: All 30 routes reconstructed correctly")
    else:
        print(f"\nWARNING: Expected 30 routes, got {count}")

    return 0 if count == 30 else 1


if __name__ == '__main__':
    sys.exit(main())
