#!/usr/bin/env python3
"""Generate the network SQLite database for the routing analysis task."""
import sqlite3
import json
import os

DB_PATH = "/app/network.db"
os.makedirs("/app", exist_ok=True)

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

c.executescript("""
CREATE TABLE routers (
    name TEXT PRIMARY KEY,
    router_id TEXT NOT NULL,
    as_number INTEGER NOT NULL,
    loopback_ip TEXT NOT NULL,
    loopback_mask TEXT NOT NULL DEFAULT '255.255.255.255',
    is_bgp_speaker INTEGER DEFAULT 0,
    role TEXT
);

CREATE TABLE ospf_areas (
    router TEXT NOT NULL,
    area INTEGER NOT NULL,
    PRIMARY KEY (router, area),
    FOREIGN KEY (router) REFERENCES routers(name)
);

CREATE TABLE ospf_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    router_a TEXT NOT NULL,
    router_b TEXT NOT NULL,
    ip_a TEXT NOT NULL,
    ip_b TEXT NOT NULL,
    network TEXT NOT NULL,
    cost INTEGER NOT NULL,
    area INTEGER NOT NULL,
    FOREIGN KEY (router_a) REFERENCES routers(name),
    FOREIGN KEY (router_b) REFERENCES routers(name)
);

CREATE TABLE ebgp_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    local_router TEXT NOT NULL,
    isp_name TEXT NOT NULL,
    local_ip TEXT NOT NULL,
    remote_ip TEXT NOT NULL,
    remote_as INTEGER NOT NULL,
    link_network TEXT NOT NULL,
    route_map_in TEXT,
    FOREIGN KEY (local_router) REFERENCES routers(name)
);

CREATE TABLE bgp_received_routes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    prefix TEXT NOT NULL,
    as_path TEXT NOT NULL,
    origin TEXT NOT NULL,
    med INTEGER NOT NULL,
    FOREIGN KEY (session_id) REFERENCES ebgp_sessions(id)
);

CREATE TABLE ibgp_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    router_a TEXT NOT NULL,
    router_b TEXT NOT NULL,
    update_source TEXT NOT NULL,
    next_hop_self INTEGER DEFAULT 0,
    FOREIGN KEY (router_a) REFERENCES routers(name),
    FOREIGN KEY (router_b) REFERENCES routers(name)
);

CREATE TABLE connected_networks (
    router TEXT NOT NULL,
    network TEXT NOT NULL,
    PRIMARY KEY (router, network),
    FOREIGN KEY (router) REFERENCES routers(name)
);

CREATE TABLE admin_distances (
    protocol TEXT PRIMARY KEY,
    distance INTEGER NOT NULL
);
""")

routers = [
    ("R1", "10.0.0.1", 65000, "10.0.0.1", "255.255.255.255", 1, None),
    ("R2", "10.0.0.2", 65000, "10.0.0.2", "255.255.255.255", 1, None),
    ("R3", "10.0.0.3", 65000, "10.0.0.3", "255.255.255.255", 0, "ABR"),
    ("R4", "10.0.0.4", 65000, "10.0.0.4", "255.255.255.255", 0, "ABR"),
    ("R5", "10.0.0.5", 65000, "10.0.0.5", "255.255.255.255", 0, None),
    ("R6", "10.0.0.6", 65000, "10.0.0.6", "255.255.255.255", 0, None),
]
c.executemany("INSERT INTO routers VALUES (?,?,?,?,?,?,?)", routers)

ospf_areas = [
    ("R1", 0), ("R2", 0), ("R3", 0), ("R3", 10), ("R4", 0), ("R4", 20),
    ("R5", 10), ("R6", 20),
]
c.executemany("INSERT INTO ospf_areas VALUES (?,?)", ospf_areas)

ospf_links = [
    ("R1", "R2", "10.1.12.1", "10.1.12.2", "10.1.12.0/30", 5, 0),
    ("R1", "R3", "10.1.13.1", "10.1.13.2", "10.1.13.0/30", 10, 0),
    ("R2", "R4", "10.1.24.1", "10.1.24.2", "10.1.24.0/30", 10, 0),
    ("R3", "R4", "10.1.34.1", "10.1.34.2", "10.1.34.0/30", 20, 0),
    ("R3", "R5", "10.1.35.1", "10.1.35.2", "10.1.35.0/30", 10, 10),
    ("R4", "R6", "10.1.46.1", "10.1.46.2", "10.1.46.0/30", 10, 20),
]
c.executemany(
    "INSERT INTO ospf_links (router_a,router_b,ip_a,ip_b,network,cost,area) VALUES (?,?,?,?,?,?,?)",
    ospf_links,
)

ebgp_sessions = [
    ("R1", "ISP-A", "192.168.1.2", "192.168.1.1", 65100, "192.168.1.0/30", "ISP-A-IN"),
    ("R2", "ISP-B", "192.168.2.2", "192.168.2.1", 65200, "192.168.2.0/30", "ISP-B-IN"),
]
c.executemany(
    "INSERT INTO ebgp_sessions (local_router,isp_name,local_ip,remote_ip,remote_as,link_network,route_map_in) VALUES (?,?,?,?,?,?,?)",
    ebgp_sessions,
)

bgp_routes = [
    (1, "203.0.113.0/24", json.dumps([65100]), "igp", 100),
    (1, "198.51.100.0/24", json.dumps([65100, 65300]), "igp", 50),
    (2, "203.0.113.0/24", json.dumps([65200]), "igp", 50),
    (2, "192.0.2.0/24", json.dumps([65200, 65400]), "incomplete", 200),
]
c.executemany(
    "INSERT INTO bgp_received_routes (session_id,prefix,as_path,origin,med) VALUES (?,?,?,?,?)",
    bgp_routes,
)

c.execute(
    "INSERT INTO ibgp_sessions (router_a,router_b,update_source,next_hop_self) VALUES (?,?,?,?)",
    ("R1", "R2", "loopback", 1),
)

connected = [("R5", "172.16.5.0/24"), ("R6", "172.16.6.0/24")]
c.executemany("INSERT INTO connected_networks VALUES (?,?)", connected)

admin_dists = [
    ("connected", 0),
    ("static", 1),
    ("ebgp", 20),
    ("ospf", 110),
    ("ibgp", 200),
]
c.executemany("INSERT INTO admin_distances VALUES (?,?)", admin_dists)

conn.commit()
conn.close()
print(f"Database created at {DB_PATH}")
