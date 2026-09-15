-- IS-IS Level-2 Link State Database
-- Normalized relational schema mirroring real routing daemon LSDB storage

CREATE TABLE config (
    parameter TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE lsp_entries (
    lsp_id TEXT PRIMARY KEY,
    sequence_number INTEGER NOT NULL,
    remaining_lifetime INTEGER NOT NULL,
    overload INTEGER NOT NULL DEFAULT 0,
    checksum TEXT
);

CREATE TABLE is_adjacencies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lsp_id TEXT NOT NULL REFERENCES lsp_entries(lsp_id),
    neighbor_id TEXT NOT NULL,
    metric INTEGER NOT NULL
);

CREATE TABLE ipv4_prefixes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lsp_id TEXT NOT NULL REFERENCES lsp_entries(lsp_id),
    address TEXT NOT NULL,
    prefix_length INTEGER NOT NULL,
    metric INTEGER NOT NULL
);

CREATE TABLE interface_map (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    system_id TEXT NOT NULL,
    interface_name TEXT,
    neighbor_system_id TEXT,
    link_type TEXT CHECK(link_type IN ('point-to-point', 'broadcast'))
);

-- Configuration
INSERT INTO config VALUES ('source_router', '0000.0000.0001');
INSERT INTO config VALUES ('level', '2');
INSERT INTO config VALUES ('spf_algorithm', 'standard');

-- LSP entries (11 LSPs: 9 routers + 1 pseudonode + 1 fragmented)
INSERT INTO lsp_entries VALUES ('0000.0000.0001.00-00', 100, 1200, 0, 'A1B2');
INSERT INTO lsp_entries VALUES ('0000.0000.0002.00-00', 100, 1200, 0, 'C3D4');
INSERT INTO lsp_entries VALUES ('0000.0000.0003.00-00', 100, 1200, 0, 'E5F6');
INSERT INTO lsp_entries VALUES ('0000.0000.0003.00-01', 100, 1200, 0, 'E5F7');
INSERT INTO lsp_entries VALUES ('0000.0000.0004.00-00', 100, 1200, 0, 'G7H8');
INSERT INTO lsp_entries VALUES ('0000.0000.0005.00-00', 100, 1200, 0, 'I9J0');
INSERT INTO lsp_entries VALUES ('0000.0000.0006.00-00', 100, 1200, 0, 'K1L2');
INSERT INTO lsp_entries VALUES ('0000.0000.0007.00-00', 100, 1200, 0, 'M3N4');
INSERT INTO lsp_entries VALUES ('0000.0000.0008.00-00', 100, 1200, 1, 'O5P6');
INSERT INTO lsp_entries VALUES ('0000.0000.0001.01-00', 100, 1200, 0, 'Q7R8');
INSERT INTO lsp_entries VALUES ('0000.0000.0009.00-00', 50, 0, 0, 'S9T0');

-- IS adjacencies: rt1 (0000.0000.0001.00-00)
INSERT INTO is_adjacencies (lsp_id, neighbor_id, metric) VALUES ('0000.0000.0001.00-00', '0000.0000.0002.00', 10);
INSERT INTO is_adjacencies (lsp_id, neighbor_id, metric) VALUES ('0000.0000.0001.00-00', '0000.0000.0005.00', 20);
INSERT INTO is_adjacencies (lsp_id, neighbor_id, metric) VALUES ('0000.0000.0001.00-00', '0000.0000.0001.01', 20);

-- IS adjacencies: rt2 (0000.0000.0002.00-00)
INSERT INTO is_adjacencies (lsp_id, neighbor_id, metric) VALUES ('0000.0000.0002.00-00', '0000.0000.0001.00', 10);
INSERT INTO is_adjacencies (lsp_id, neighbor_id, metric) VALUES ('0000.0000.0002.00-00', '0000.0000.0003.00', 10);
INSERT INTO is_adjacencies (lsp_id, neighbor_id, metric) VALUES ('0000.0000.0002.00-00', '0000.0000.0005.00', 10);

-- IS adjacencies: rt3 fragment 00 (0000.0000.0003.00-00)
INSERT INTO is_adjacencies (lsp_id, neighbor_id, metric) VALUES ('0000.0000.0003.00-00', '0000.0000.0002.00', 10);
INSERT INTO is_adjacencies (lsp_id, neighbor_id, metric) VALUES ('0000.0000.0003.00-00', '0000.0000.0006.00', 10);

-- IS adjacencies: rt3 fragment 01 (0000.0000.0003.00-01)
INSERT INTO is_adjacencies (lsp_id, neighbor_id, metric) VALUES ('0000.0000.0003.00-01', '0000.0000.0007.00', 15);

-- IS adjacencies: rt4 (0000.0000.0004.00-00)
INSERT INTO is_adjacencies (lsp_id, neighbor_id, metric) VALUES ('0000.0000.0004.00-00', '0000.0000.0001.01', 20);

-- IS adjacencies: rt5 (0000.0000.0005.00-00)
INSERT INTO is_adjacencies (lsp_id, neighbor_id, metric) VALUES ('0000.0000.0005.00-00', '0000.0000.0002.00', 10);
INSERT INTO is_adjacencies (lsp_id, neighbor_id, metric) VALUES ('0000.0000.0005.00-00', '0000.0000.0001.00', 20);
INSERT INTO is_adjacencies (lsp_id, neighbor_id, metric) VALUES ('0000.0000.0005.00-00', '0000.0000.0006.00', 10);

-- IS adjacencies: rt6 (0000.0000.0006.00-00)
INSERT INTO is_adjacencies (lsp_id, neighbor_id, metric) VALUES ('0000.0000.0006.00-00', '0000.0000.0003.00', 10);
INSERT INTO is_adjacencies (lsp_id, neighbor_id, metric) VALUES ('0000.0000.0006.00-00', '0000.0000.0005.00', 10);
INSERT INTO is_adjacencies (lsp_id, neighbor_id, metric) VALUES ('0000.0000.0006.00-00', '0000.0000.0007.00', 25);
INSERT INTO is_adjacencies (lsp_id, neighbor_id, metric) VALUES ('0000.0000.0006.00-00', '0000.0000.0009.00', 10);

-- IS adjacencies: rt7 (0000.0000.0007.00-00)
INSERT INTO is_adjacencies (lsp_id, neighbor_id, metric) VALUES ('0000.0000.0007.00-00', '0000.0000.0003.00', 15);
INSERT INTO is_adjacencies (lsp_id, neighbor_id, metric) VALUES ('0000.0000.0007.00-00', '0000.0000.0006.00', 25);
INSERT INTO is_adjacencies (lsp_id, neighbor_id, metric) VALUES ('0000.0000.0007.00-00', '0000.0000.0008.00', 10);

-- IS adjacencies: rt8 overloaded (0000.0000.0008.00-00)
INSERT INTO is_adjacencies (lsp_id, neighbor_id, metric) VALUES ('0000.0000.0008.00-00', '0000.0000.0001.01', 20);
INSERT INTO is_adjacencies (lsp_id, neighbor_id, metric) VALUES ('0000.0000.0008.00-00', '0000.0000.0007.00', 10);

-- IS adjacencies: pseudonode / LAN DIS (0000.0000.0001.01-00)
INSERT INTO is_adjacencies (lsp_id, neighbor_id, metric) VALUES ('0000.0000.0001.01-00', '0000.0000.0001.00', 0);
INSERT INTO is_adjacencies (lsp_id, neighbor_id, metric) VALUES ('0000.0000.0001.01-00', '0000.0000.0004.00', 0);
INSERT INTO is_adjacencies (lsp_id, neighbor_id, metric) VALUES ('0000.0000.0001.01-00', '0000.0000.0008.00', 0);

-- IS adjacencies: rt9 expired (0000.0000.0009.00-00)
INSERT INTO is_adjacencies (lsp_id, neighbor_id, metric) VALUES ('0000.0000.0009.00-00', '0000.0000.0006.00', 10);

-- IPv4 prefixes: rt1
INSERT INTO ipv4_prefixes (lsp_id, address, prefix_length, metric) VALUES ('0000.0000.0001.00-00', '1.1.1.1', 32, 0);
INSERT INTO ipv4_prefixes (lsp_id, address, prefix_length, metric) VALUES ('0000.0000.0001.00-00', '10.0.1.0', 24, 10);
INSERT INTO ipv4_prefixes (lsp_id, address, prefix_length, metric) VALUES ('0000.0000.0001.00-00', '10.0.10.0', 24, 20);
INSERT INTO ipv4_prefixes (lsp_id, address, prefix_length, metric) VALUES ('0000.0000.0001.00-00', '10.0.8.0', 24, 20);

-- IPv4 prefixes: rt2
INSERT INTO ipv4_prefixes (lsp_id, address, prefix_length, metric) VALUES ('0000.0000.0002.00-00', '2.2.2.2', 32, 0);
INSERT INTO ipv4_prefixes (lsp_id, address, prefix_length, metric) VALUES ('0000.0000.0002.00-00', '10.0.1.0', 24, 10);
INSERT INTO ipv4_prefixes (lsp_id, address, prefix_length, metric) VALUES ('0000.0000.0002.00-00', '10.0.2.0', 24, 10);
INSERT INTO ipv4_prefixes (lsp_id, address, prefix_length, metric) VALUES ('0000.0000.0002.00-00', '10.0.3.0', 24, 10);

-- IPv4 prefixes: rt3 fragment 00
INSERT INTO ipv4_prefixes (lsp_id, address, prefix_length, metric) VALUES ('0000.0000.0003.00-00', '3.3.3.3', 32, 0);
INSERT INTO ipv4_prefixes (lsp_id, address, prefix_length, metric) VALUES ('0000.0000.0003.00-00', '10.0.2.0', 24, 10);
INSERT INTO ipv4_prefixes (lsp_id, address, prefix_length, metric) VALUES ('0000.0000.0003.00-00', '10.0.4.0', 24, 10);

-- IPv4 prefixes: rt3 fragment 01
INSERT INTO ipv4_prefixes (lsp_id, address, prefix_length, metric) VALUES ('0000.0000.0003.00-01', '10.0.5.0', 24, 15);
INSERT INTO ipv4_prefixes (lsp_id, address, prefix_length, metric) VALUES ('0000.0000.0003.00-01', '172.16.0.0', 16, 30);

-- IPv4 prefixes: rt4
INSERT INTO ipv4_prefixes (lsp_id, address, prefix_length, metric) VALUES ('0000.0000.0004.00-00', '4.4.4.4', 32, 0);
INSERT INTO ipv4_prefixes (lsp_id, address, prefix_length, metric) VALUES ('0000.0000.0004.00-00', '10.0.8.0', 24, 20);

-- IPv4 prefixes: rt5
INSERT INTO ipv4_prefixes (lsp_id, address, prefix_length, metric) VALUES ('0000.0000.0005.00-00', '5.5.5.5', 32, 0);
INSERT INTO ipv4_prefixes (lsp_id, address, prefix_length, metric) VALUES ('0000.0000.0005.00-00', '10.0.3.0', 24, 10);
INSERT INTO ipv4_prefixes (lsp_id, address, prefix_length, metric) VALUES ('0000.0000.0005.00-00', '10.0.10.0', 24, 20);
INSERT INTO ipv4_prefixes (lsp_id, address, prefix_length, metric) VALUES ('0000.0000.0005.00-00', '10.0.6.0', 24, 10);
INSERT INTO ipv4_prefixes (lsp_id, address, prefix_length, metric) VALUES ('0000.0000.0005.00-00', '172.16.0.0', 16, 30);

-- IPv4 prefixes: rt6
INSERT INTO ipv4_prefixes (lsp_id, address, prefix_length, metric) VALUES ('0000.0000.0006.00-00', '6.6.6.6', 32, 0);
INSERT INTO ipv4_prefixes (lsp_id, address, prefix_length, metric) VALUES ('0000.0000.0006.00-00', '10.0.4.0', 24, 10);
INSERT INTO ipv4_prefixes (lsp_id, address, prefix_length, metric) VALUES ('0000.0000.0006.00-00', '10.0.6.0', 24, 10);
INSERT INTO ipv4_prefixes (lsp_id, address, prefix_length, metric) VALUES ('0000.0000.0006.00-00', '10.0.7.0', 24, 25);

-- IPv4 prefixes: rt7
INSERT INTO ipv4_prefixes (lsp_id, address, prefix_length, metric) VALUES ('0000.0000.0007.00-00', '7.7.7.7', 32, 0);
INSERT INTO ipv4_prefixes (lsp_id, address, prefix_length, metric) VALUES ('0000.0000.0007.00-00', '10.0.5.0', 24, 15);
INSERT INTO ipv4_prefixes (lsp_id, address, prefix_length, metric) VALUES ('0000.0000.0007.00-00', '10.0.7.0', 24, 25);
INSERT INTO ipv4_prefixes (lsp_id, address, prefix_length, metric) VALUES ('0000.0000.0007.00-00', '10.0.9.0', 24, 10);

-- IPv4 prefixes: rt8 (overloaded)
INSERT INTO ipv4_prefixes (lsp_id, address, prefix_length, metric) VALUES ('0000.0000.0008.00-00', '8.8.8.8', 32, 0);
INSERT INTO ipv4_prefixes (lsp_id, address, prefix_length, metric) VALUES ('0000.0000.0008.00-00', '10.0.8.0', 24, 20);
INSERT INTO ipv4_prefixes (lsp_id, address, prefix_length, metric) VALUES ('0000.0000.0008.00-00', '10.0.9.0', 24, 10);

-- IPv4 prefixes: rt9 (expired LSP)
INSERT INTO ipv4_prefixes (lsp_id, address, prefix_length, metric) VALUES ('0000.0000.0009.00-00', '9.9.9.9', 32, 0);
INSERT INTO ipv4_prefixes (lsp_id, address, prefix_length, metric) VALUES ('0000.0000.0009.00-00', '10.0.11.0', 24, 10);

-- Interface map (physical topology reference)
INSERT INTO interface_map VALUES (1, '0000.0000.0001', 'eth0', '0000.0000.0002', 'point-to-point');
INSERT INTO interface_map VALUES (2, '0000.0000.0001', 'eth1', NULL, 'broadcast');
INSERT INTO interface_map VALUES (3, '0000.0000.0001', 'eth2', '0000.0000.0005', 'point-to-point');
INSERT INTO interface_map VALUES (4, '0000.0000.0002', 'eth0', '0000.0000.0001', 'point-to-point');
INSERT INTO interface_map VALUES (5, '0000.0000.0002', 'eth1', '0000.0000.0003', 'point-to-point');
INSERT INTO interface_map VALUES (6, '0000.0000.0002', 'eth2', '0000.0000.0005', 'point-to-point');
INSERT INTO interface_map VALUES (7, '0000.0000.0004', 'eth0', NULL, 'broadcast');
INSERT INTO interface_map VALUES (8, '0000.0000.0008', 'eth0', NULL, 'broadcast');
INSERT INTO interface_map VALUES (9, '0000.0000.0008', 'eth1', '0000.0000.0007', 'point-to-point');
