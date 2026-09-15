A network routing control plane system at `/app/` manages routing configuration for a 6-node data center network. The system consists of a Flask-based control plane API server (`/app/server.py`), an SQLite configuration database (`/app/db/network.db`), per-node router daemons (`/app/router.py`), and route computation logic (`/app/models.py`).

During a maintenance window, a migration script (`/app/maintenance/maintenance.sh`) caused cascading failures that corrupted multiple system components simultaneously.

Known damage assessment:
- The routing configuration database has lost its primary data table; an empty replacement was left behind
- The original control plane log was archived and then deleted by the maintenance script — the current log at `/app/logs/control_plane.log` only contains maintenance-window entries with no prior operational data
- The network topology configuration at `/app/config/topology.json` was modified by the maintenance script (a link cost was changed for "QoS simulation") and was not reverted
- A network monitoring agent captured control plane API traffic before the incident; the capture is at `/app/forensics/capture.pcap`
- A `route_audit_log` table in the database survived the table drop but the maintenance script "normalized" some entries, corrupting them
- The configuration backup at `/app/config/backup/routes_backup.json` was corrupted by the maintenance script's "validation" pass
- Some router cache files in `/app/routers/cache/` were deleted; surviving caches may contain stale pre-incident data
- The control plane server configuration has been altered
- Stale PID files prevent daemon restarts

The maintenance log at `/app/logs/maintenance.log` documents what the script did.

Before the incident, the system had 30 active routes (5 per node) including at least one manually configured operator override that was applied after initial route computation. No single evidence source contains all correct routing data — cross-referencing multiple sources is required.

Restore the system to full operational status: reconstruct all routing data with correct values (including any operator overrides), fix the network topology to its pre-maintenance state, restore the database, repair configuration, and start the control plane API server on its correct port with all routes accessible via the API.