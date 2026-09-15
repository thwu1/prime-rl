#!/usr/bin/env python3
"""Generate the BGP RIB database for the route analyzer task."""
import sqlite3
import os

DB_PATH = "/app/bgp_rib.db"


def ip_to_bytes(ip_str):
    parts = [int(x) for x in ip_str.split('.')]
    return bytes(parts)


def encode_extended_attrs(originator_id=None, cluster_list=None):
    flags = 0
    data = bytearray()
    if originator_id:
        flags |= 0x01
    if cluster_list:
        flags |= 0x02
    data.append(flags)
    if originator_id:
        data.extend(ip_to_bytes(originator_id))
    if cluster_list:
        data.append(len(cluster_list))
        for cid in cluster_list:
            data.extend(ip_to_bytes(cid))
    return bytes(data)


def main():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.executescript("""
    CREATE TABLE prefixes (
        id INTEGER PRIMARY KEY,
        network TEXT NOT NULL
    );
    CREATE TABLE routes (
        id INTEGER PRIMARY KEY,
        prefix_id INTEGER NOT NULL REFERENCES prefixes(id),
        weight INTEGER NOT NULL DEFAULT 0,
        local_pref INTEGER,
        locally_originated INTEGER NOT NULL DEFAULT 0,
        local_origin_type TEXT,
        origin TEXT,
        med INTEGER,
        path_source TEXT NOT NULL DEFAULT 'ebgp',
        igp_metric INTEGER NOT NULL DEFAULT 0,
        router_id TEXT NOT NULL,
        neighbor_address TEXT NOT NULL,
        is_valid INTEGER NOT NULL DEFAULT 1,
        arrival_order INTEGER NOT NULL DEFAULT 0,
        extended_attrs BLOB
    );
    CREATE TABLE as_path_segments (
        route_id INTEGER NOT NULL REFERENCES routes(id),
        seg_order INTEGER NOT NULL,
        seg_type TEXT NOT NULL,
        asns TEXT NOT NULL,
        PRIMARY KEY (route_id, seg_order)
    );
    CREATE TABLE config_profiles (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL UNIQUE
    );
    CREATE TABLE queries (
        id INTEGER PRIMARY KEY,
        prefix_id INTEGER NOT NULL REFERENCES prefixes(id),
        config_id INTEGER NOT NULL REFERENCES config_profiles(id),
        description TEXT
    );
    CREATE TABLE pcap_routes (
        route_id INTEGER NOT NULL REFERENCES routes(id),
        capture_file TEXT NOT NULL DEFAULT '/app/bgp_capture.pcap',
        description TEXT
    );
    """)

    # Prefixes
    prefixes = [
        (1, "10.1.0.0/24"), (2, "10.2.0.0/24"), (3, "10.3.0.0/24"),
        (4, "10.4.0.0/24"), (5, "10.5.0.0/24"), (6, "10.6.0.0/24"),
        (7, "10.7.0.0/24"), (8, "10.8.0.0/24"), (9, "10.9.0.0/24"),
        (10, "10.10.0.0/24"), (11, "10.11.0.0/24"),
    ]
    c.executemany("INSERT INTO prefixes VALUES (?,?)", prefixes)

    # Config profiles (names only — flags stored in /app/policies/selection.json)
    configs = [
        (1, "standard"),
        (2, "compare_rid"),
        (3, "always_med"),
        (4, "det_med"),
        (5, "med_worst"),
        (6, "confed_med"),
        (7, "ignore_aspath"),
    ]
    c.executemany("INSERT INTO config_profiles VALUES (?,?)", configs)

    NE = encode_extended_attrs()  # no extended attrs

    routes_data = [
        # id, pfx, weight, lp, local, lotype, origin, med, psrc, igpm, rid, neigh, valid, arr, ext

        # --- Prefix 1: weight test ---
        (1,  1, 100, None, 0, None, 'igp',   0, 'ebgp', 0, '1.1.1.1', '10.0.0.1', 1, 0, NE),
        (2,  1, 100,  100, 0, None, 'igp',   0, 'ebgp', 0, '2.2.2.2', '10.0.0.2', 1, 1, NE),
        (3,  1, 200,   50, 0, None, 'igp',   0, 'ebgp', 0, '3.3.3.3', '10.0.0.3', 1, 2, NE),

        # --- Prefix 2: local-pref + AS_SET path length ---
        (4,  2,   0, 150, 0, None, 'igp',   0, 'ebgp', 0, '1.1.1.1', '10.0.0.4', 1, 0, NE),
        (5,  2,   0, 150, 0, None, 'igp',   0, 'ebgp', 0, '2.2.2.2', '10.0.0.5', 1, 1, NE),
        (6,  2,   0, 100, 0, None, 'igp',   0, 'ebgp', 0, '3.3.3.3', '10.0.0.6', 1, 2, NE),

        # --- Prefix 3: confed path length + origin + eBGP>confed ---
        (7,  3,   0, 100, 0, None, 'igp',   0, 'confed_ebgp', 0, '1.1.1.1', '10.0.0.7', 1, 0, NE),
        (8,  3,   0, 100, 0, None, 'egp',   0, 'ebgp',        0, '2.2.2.2', '10.0.0.8', 1, 1, NE),
        (9,  3,   0, 100, 0, None, 'igp',   0, 'ebgp',        0, '3.3.3.3', '10.0.0.9', 1, 2, NE),

        # --- Prefix 4: MED conditional + always_med + det-med ---
        (10, 4,   0, 100, 0, None, 'igp', 150, 'ebgp', 0, '1.1.1.1', '10.0.0.10', 1, 0, NE),
        (11, 4,   0, 100, 0, None, 'igp',  50, 'ebgp', 0, '3.3.3.3', '10.0.0.11', 1, 1, NE),
        (12, 4,   0, 100, 0, None, 'igp',  50, 'ebgp', 0, '4.4.4.4', '10.0.0.12', 1, 2, NE),

        # --- Prefix 5: MED null handling + originator/cluster ---
        (13, 5,   0, 100, 0, None, 'igp', None, 'ibgp', 10, '1.1.1.1', '10.0.0.13', 1, 0,
         encode_extended_attrs('5.5.5.5', ['10.0.0.100', '10.0.0.101'])),
        (14, 5,   0, 100, 0, None, 'igp',  100, 'ibgp', 10, '2.2.2.2', '10.0.0.14', 1, 1,
         encode_extended_attrs('5.5.5.5', ['10.0.0.102'])),
        (15, 5,   0, 100, 0, None, 'igp',   50, 'ibgp', 10, '3.3.3.3', '10.0.0.15', 1, 2,
         encode_extended_attrs('3.3.3.3', ['10.0.0.103'])),

        # --- Prefix 6: originator-id + cluster-list + neighbor tiebreak ---
        (16, 6,   0, 100, 0, None, 'igp',   0, 'ibgp', 0, '1.1.1.1', '10.0.0.16', 1, 0,
         encode_extended_attrs('5.5.5.5', ['10.0.0.200', '10.0.0.201', '10.0.0.202'])),
        (17, 6,   0, 100, 0, None, 'igp',   0, 'ibgp', 0, '2.2.2.2', '10.0.0.17', 1, 1,
         encode_extended_attrs('5.5.5.5', ['10.0.0.203'])),
        (18, 6,   0, 100, 0, None, 'igp',   0, 'ibgp', 0, '3.3.3.3', '192.168.1.1', 1, 2,
         encode_extended_attrs('5.5.5.5', ['10.0.0.204'])),

        # --- Prefix 7: med_confed + invalid route ---
        (19, 7,   0, 100, 0, None, 'igp', 200, 'confed_ebgp', 0, '1.1.1.1', '10.0.0.19', 1, 0, NE),
        (20, 7,   0, 100, 0, None, 'igp',  50, 'confed_ebgp', 0, '2.2.2.2', '10.0.0.20', 1, 1, NE),
        (21, 7,   0, 100, 0, None, 'igp',  10, 'ebgp',        0, '3.3.3.3', '10.0.0.21', 0, 2, NE),

        # --- Prefix 8: as_path_ignore ---
        (22, 8,   0, 100, 0, None, 'igp',   0, 'ebgp', 0, '1.1.1.1', '10.0.0.22', 1, 0, NE),
        (23, 8,   0, 100, 0, None, 'igp',   0, 'ebgp', 0, '4.4.4.4', '10.0.0.23', 1, 1, NE),

        # --- Prefix 9: oldest path vs compare_routerid ---
        (24, 9,   0, 100, 0, None, 'igp',   0, 'ebgp', 0, '9.9.9.9', '10.0.0.24', 1, 0, NE),
        (25, 9,   0, 100, 0, None, 'igp',   0, 'ebgp', 0, '1.1.1.1', '10.0.0.25', 1, 1, NE),
        (26, 9,   0, 100, 0, None, 'igp',   0, 'ibgp', 0, '2.2.2.2', '10.0.0.26', 1, 2, NE),

        # --- Prefix 10: locally_originated ---
        (27, 10,  0, 100, 1, 'aggregate', 'igp', 0, 'ibgp', 0, '5.5.5.5', '10.0.0.27', 1, 0, NE),
        (28, 10,  0, 100, 1, 'network',   'igp', 0, 'ibgp', 0, '6.6.6.6', '10.0.0.28', 1, 1, NE),
        (29, 10,  0, 100, 0, None,        'igp', 0, 'ebgp', 0, '1.1.1.1', '10.0.0.29', 1, 2, NE),

        # --- Prefix 11: PCAP-sourced routes (origin, med, as_path from capture) ---
        (30, 11,  0, 100, 0, None, None, None, 'ebgp', 0, '10.0.1.1', '10.0.1.1', 1, 0, NE),
        (31, 11,  0, 100, 0, None, None, None, 'ebgp', 0, '10.0.1.2', '10.0.1.2', 1, 1, NE),
        (32, 11,  0, 100, 0, None, None, None, 'ebgp', 0, '10.0.1.3', '10.0.1.3', 1, 2, NE),
    ]

    for r in routes_data:
        c.execute(
            "INSERT INTO routes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", r
        )

    # AS path segments (routes 30-32 have NO segments here — data is in PCAP)
    as_paths = [
        # Prefix 1
        (1, 0, 'AS_SEQUENCE', '200'),
        (2, 0, 'AS_SEQUENCE', '300'),
        (3, 0, 'AS_SEQUENCE', '400'),
        # Prefix 2
        (4, 0, 'AS_SEQUENCE', '200,300'),
        (5, 0, 'AS_SET', '400,500,600,700'),
        (6, 0, 'AS_SEQUENCE', '800'),
        # Prefix 3
        (7, 0, 'AS_CONFED_SEQUENCE', '65001,65002'),
        (7, 1, 'AS_SEQUENCE', '200'),
        (8, 0, 'AS_SEQUENCE', '300'),
        (9, 0, 'AS_SEQUENCE', '400'),
        # Prefix 4
        (10, 0, 'AS_SEQUENCE', '100'),
        (11, 0, 'AS_SEQUENCE', '200'),
        (12, 0, 'AS_SEQUENCE', '100'),
        # Prefix 5
        (13, 0, 'AS_SEQUENCE', '200'),
        (14, 0, 'AS_SEQUENCE', '200'),
        (15, 0, 'AS_SEQUENCE', '200'),
        # Prefix 6
        (16, 0, 'AS_SEQUENCE', '200'),
        (17, 0, 'AS_SEQUENCE', '200'),
        (18, 0, 'AS_SEQUENCE', '200'),
        # Prefix 7
        (19, 0, 'AS_CONFED_SEQUENCE', '65001,65002'),
        (20, 0, 'AS_CONFED_SEQUENCE', '65003'),
        (21, 0, 'AS_SEQUENCE', '500'),
        # Prefix 8
        (22, 0, 'AS_SEQUENCE', '200,300,400'),
        (23, 0, 'AS_SEQUENCE', '500'),
        # Prefix 9
        (24, 0, 'AS_SEQUENCE', '200'),
        (25, 0, 'AS_SEQUENCE', '300'),
        (26, 0, 'AS_SEQUENCE', '400'),
        # Prefix 10: routes 27,28 have empty AS paths (locally originated)
        (29, 0, 'AS_SEQUENCE', '200'),
        # Prefix 11: NO entries — AS paths are in the PCAP capture
    ]
    c.executemany("INSERT INTO as_path_segments VALUES (?,?,?,?)", as_paths)

    # PCAP routes — identifies routes whose path attributes are in the capture file
    pcap_routes = [
        (30, '/app/bgp_capture.pcap',
         'Extract origin, med, as_path from BGP UPDATE where ip.src matches neighbor_address 10.0.1.1'),
        (31, '/app/bgp_capture.pcap',
         'Extract origin, med, as_path from BGP UPDATE where ip.src matches neighbor_address 10.0.1.2'),
        (32, '/app/bgp_capture.pcap',
         'Extract origin, med, as_path from BGP UPDATE where ip.src matches neighbor_address 10.0.1.3'),
    ]
    c.executemany("INSERT INTO pcap_routes VALUES (?,?,?)", pcap_routes)

    # Queries
    queries = [
        (1,  1, 2, "Best path for 10.1.0.0/24 - weight selection"),
        (2,  2, 2, "Best path for 10.2.0.0/24 - local-pref and AS_SET length"),
        (3,  3, 2, "Best path for 10.3.0.0/24 - confed vs ebgp preference"),
        (4,  4, 1, "Best path for 10.4.0.0/24 - standard MED behavior"),
        (5,  4, 2, "Best path for 10.4.0.0/24 - compare_routerid mode"),
        (6,  4, 3, "Best path for 10.4.0.0/24 - always_compare_med"),
        (7,  4, 4, "Best path for 10.4.0.0/24 - deterministic MED"),
        (8,  5, 2, "Best path for 10.5.0.0/24 - null MED defaults to 0"),
        (9,  5, 5, "Best path for 10.5.0.0/24 - med_missing_as_worst"),
        (10, 6, 2, "Best path for 10.6.0.0/24 - originator_id and cluster_list"),
        (11, 7, 6, "Best path for 10.7.0.0/24 - med_confed enabled"),
        (12, 7, 2, "Best path for 10.7.0.0/24 - no med_confed"),
        (13, 8, 2, "Best path for 10.8.0.0/24 - normal AS-path comparison"),
        (14, 8, 7, "Best path for 10.8.0.0/24 - as_path_ignore"),
        (15, 9, 1, "Best path for 10.9.0.0/24 - oldest path (standard)"),
        (16, 9, 2, "Best path for 10.9.0.0/24 - compare_routerid"),
        (17, 10, 2, "Best path for 10.10.0.0/24 - locally_originated"),
        (18, 11, 2, "Best path for 10.11.0.0/24 - PCAP routes with compare_rid"),
        (19, 11, 3, "Best path for 10.11.0.0/24 - PCAP routes with always_med"),
        (20, 11, 4, "Best path for 10.11.0.0/24 - PCAP routes with deterministic_med"),
    ]
    c.executemany("INSERT INTO queries VALUES (?,?,?,?)", queries)

    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
