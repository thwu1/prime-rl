#!/bin/bash
# maintenance.sh - Database schema migration script
# EXECUTED: 2024-03-16 02:00:00 UTC
# STATUS: FAILED - caused production incident (see /app/logs/maintenance.log)
# TICKET: OPS-4890
# AUTHOR: ops-automation@infra-team
#
# Purpose: Add 'priority' column to routes table for QoS support
#
# POST-MORTEM: This script contained multiple bugs that caused cascading failures:
#   1. ALTER TABLE failed because 'priority' column was added in a prior dry-run
#   2. Rollback strategy B incorrectly dropped the routes table
#   3. Backup "validation" step corrupted entries in the backup file
#   4. Server config was changed to maintenance port but never reverted
#   5. Topology was modified for QoS simulation but never reverted
#   6. Audit log entries were "normalized" (corrupted) for migration staging
#   7. Original control plane log was archived then deleted
#
# DO NOT RUN THIS SCRIPT AGAIN.

set -uo pipefail

DB_PATH="/app/db/network.db"
BACKUP_DIR="/app/config/backup"
CONFIG_PATH="/app/config/server.ini"
LOG_FILE="/app/logs/maintenance.log"
TOPO_PATH="/app/config/topology.json"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
}

log "Starting scheduled maintenance: routes table schema migration"

# Step 0: Archive and truncate control plane log
log "Archiving control_plane.log..."
cp /app/logs/control_plane.log /app/logs/control_plane.log.bak
truncate -s 0 /app/logs/control_plane.log
log "Control plane log archived to control_plane.log.bak"

# Step 1: Create backup before migration
log "Step 1: Creating routes backup..."
mkdir -p "$BACKUP_DIR"
sqlite3 "$DB_PATH" "SELECT json_group_array(json_object(\
  'source_node', source_node, \
  'destination_network', destination_network, \
  'next_hop_node', next_hop_node, \
  'metric', metric, \
  'status', status)) FROM routes;" > "${BACKUP_DIR}/routes_backup.json"
log "Backup written to ${BACKUP_DIR}/routes_backup.json"

# Step 2: Add priority column
log "Step 2: Attempting to add priority column..."
if ! sqlite3 "$DB_PATH" "ALTER TABLE routes ADD COLUMN priority INTEGER DEFAULT 100;" 2>/dev/null; then
    log "ERROR: ALTER TABLE failed - column 'priority' may already exist"
    log "Attempting migration rollback strategy B..."

    # BUG: Strategy B drops the original table before recreating
    sqlite3 "$DB_PATH" "DROP TABLE IF EXISTS routes;"
    sqlite3 "$DB_PATH" "CREATE TABLE routes_new (
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
    );"

    # BUG: Import from backup into routes_new had a syntax error
    if ! sqlite3 "$DB_PATH" "ALTER TABLE routes_new RENAME TO routes;" 2>/dev/null; then
        log "CRITICAL: Table rename failed"
    else
        log "CRITICAL: routes table recreated but is EMPTY - data loss confirmed"
    fi
fi

# Step 3: Adjust topology for QoS simulation
# BUG: This change was supposed to be temporary but was never reverted
log "Step 3: Adjusting compute-east/storage link cost for QoS simulation..."
python3 -c "
import json
with open('${TOPO_PATH}') as f:
    t = json.load(f)
for link in t['links']:
    if set([link['node_a'], link['node_b']]) == set(['compute-east', 'storage']):
        link['cost'] = 15
with open('${TOPO_PATH}', 'w') as f:
    json.dump(t, f, indent=2)
" 2>/dev/null || true
log "Topology updated: compute-east/storage link cost changed to 15"

# Step 4: Switch to maintenance port
log "Step 4: Switching to maintenance port 5099..."
sed -i 's/port = 5000/port = 5099/' "$CONFIG_PATH"
log "Server config updated: port 5000 -> 5099"

# Step 5: Normalize audit log for migration staging
# BUG: This "normalization" corrupts legitimate audit entries
log "Step 5: Normalizing audit log entries..."
sqlite3 "$DB_PATH" "UPDATE route_audit_log SET new_next_hop = 'migration-staging'
    WHERE operation = 'INSERT' AND (
        source_node LIKE 'storage%' OR
        (source_node = 'gateway' AND destination_network IN ('10.0.2.0/24','10.0.3.0/24','10.0.4.0/24'))
    );" 2>/dev/null || true
log "Updated 8 audit log entries for migration staging"

# Step 6: Validate backup file
# BUG: This "validation" corrupts the backup by changing next_hop values
log "Step 6: Validating backup file..."
python3 -c "
import json
with open('${BACKUP_DIR}/routes_backup.json') as f:
    data = json.load(f)
for entry in data:
    src_zone = entry['source_node'].split('-')[0] if '-' in entry['source_node'] else 'core'
    dst_id = int(entry['destination_network'].split('.')[2])
    if dst_id <= 3 and src_zone != 'core':
        entry['next_hop_node'] = 'gateway'
with open('${BACKUP_DIR}/routes_backup.json', 'w') as f:
    json.dump(data, f, indent=2)
" 2>/dev/null || true
log "Backup validation complete (with errors)"

# Step 7: Cleanup old log archive
log "Step 7: Cleaning up old log files..."
rm -f /app/logs/control_plane.log.bak
log "Removed archived log: /app/logs/control_plane.log.bak"

log "Maintenance script finished. MANUAL REVIEW REQUIRED."
