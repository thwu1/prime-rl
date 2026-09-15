-- GeoPackage-compatible hydrofabric database schema
-- NOAA-OWP NextGen Hydrofabric Network

CREATE TABLE IF NOT EXISTS gpkg_contents (
    table_name TEXT NOT NULL PRIMARY KEY,
    data_type TEXT NOT NULL DEFAULT 'features',
    identifier TEXT UNIQUE,
    description TEXT DEFAULT '',
    min_x DOUBLE,
    min_y DOUBLE,
    max_x DOUBLE,
    max_y DOUBLE,
    srs_id INTEGER
);

INSERT INTO gpkg_contents VALUES ('flowpaths', 'features', 'flowpaths', 'Flowpath network features', -80.0, 35.0, -78.0, 37.0, 4326);
INSERT INTO gpkg_contents VALUES ('divides', 'features', 'divides', 'Divide catchment features', -80.0, 35.0, -78.0, 37.0, 4326);
INSERT INTO gpkg_contents VALUES ('nexus', 'features', 'nexus', 'Nexus junction features', -80.0, 35.0, -78.0, 37.0, 4326);
INSERT INTO gpkg_contents VALUES ('flowpath_attributes', 'attributes', 'flowpath_attributes', 'Channel routing parameters', NULL, NULL, NULL, NULL, NULL);

-- Core hydrofabric tables

CREATE TABLE flowpaths (
    id TEXT PRIMARY KEY,
    toid TEXT NOT NULL,
    divide_id TEXT,
    areasqkm REAL,
    lengthkm REAL,
    type TEXT DEFAULT 'network',
    hydroseq INTEGER,
    mainstem INTEGER
);

INSERT INTO flowpaths VALUES ('wb-1001', 'nex-2001', 'cat-1001', 5.20, 3.1, 'network', 110, 10001);
INSERT INTO flowpaths VALUES ('wb-1002', 'nex-2002', 'cat-1002', 8.40, 4.5, 'network', 100, 10001);
INSERT INTO flowpaths VALUES ('wb-1003', 'nex-2003', 'cat-1003', 12.10, 6.2, 'network', 80, 10001);
INSERT INTO flowpaths VALUES ('wb-1004', 'nex-2002', 'cat-1004', 6.70, 3.8, 'network', 105, 10002);
INSERT INTO flowpaths VALUES ('wb-1005', 'nex-2003', 'cat-1005', 15.30, 7.1, 'network', 85, 10003);
INSERT INTO flowpaths VALUES ('wb-1006', 'nex-2006', 'cat-1006', 9.80, 5.0, 'network', 60, 10001);
INSERT INTO flowpaths VALUES ('wb-1007', 'nex-2004', 'cat-1007', 7.50, 4.2, 'network', 115, 10003);
INSERT INTO flowpaths VALUES ('wb-1008', 'nex-2004', 'cat-1008', 11.20, 5.8, 'network', 112, 10004);
INSERT INTO flowpaths VALUES ('wb-1009', 'nex-2006', 'cat-1009', 4.60, 2.5, 'network', 95, 10005);
INSERT INTO flowpaths VALUES ('wb-1010', 'nex-2005', 'cat-1010', 3.90, 2.1, 'network', 120, 10005);
INSERT INTO flowpaths VALUES ('wb-1011', 'nex-2007', 'cat-1011', 6.30, 3.3, 'network', 40, 10001);
INSERT INTO flowpaths VALUES ('wb-1012', 'nex-2008', 'cat-1012', 4.10, 2.0, 'network', 130, 10006);
INSERT INTO flowpaths VALUES ('wb-1014', 'nex-2010', 'cat-1014', 3.50, 1.8, 'network', 140, 10007);
INSERT INTO flowpaths VALUES ('wb-1015', 'nex-2011', 'cat-1015', 5.00, 2.7, 'network', 135, 10007);
INSERT INTO flowpaths VALUES ('wb-1016', 'nex-2012', 'cat-1016', 7.20, 3.5, 'network', 150, 10008);

CREATE TABLE divides (
    divide_id TEXT PRIMARY KEY,
    id TEXT NOT NULL,
    toid TEXT NOT NULL,
    areasqkm REAL,
    type TEXT DEFAULT 'network',
    has_flowline INTEGER DEFAULT 1
);

INSERT INTO divides VALUES ('cat-1001', 'wb-1001', 'nex-2001', 5.20, 'network', 1);
INSERT INTO divides VALUES ('cat-1002', 'wb-1002', 'nex-2002', 8.40, 'network', 1);
INSERT INTO divides VALUES ('cat-1003', 'wb-1003', 'nex-2003', 12.10, 'network', 1);
INSERT INTO divides VALUES ('cat-1004', 'wb-1004', 'nex-2002', 6.70, 'network', 1);
INSERT INTO divides VALUES ('cat-1005', 'wb-1005', 'nex-2003', 15.30, 'network', 1);
INSERT INTO divides VALUES ('cat-1006', 'wb-1006', 'nex-2006', 9.80, 'network', 1);
INSERT INTO divides VALUES ('cat-1007', 'wb-1007', 'nex-2004', 7.50, 'network', 1);
INSERT INTO divides VALUES ('cat-1008', 'wb-1008', 'nex-2004', 11.20, 'network', 1);
INSERT INTO divides VALUES ('cat-1009', 'wb-1009', 'nex-2006', 4.60, 'network', 1);
INSERT INTO divides VALUES ('cat-1010', 'wb-1010', 'nex-2005', 3.90, 'network', 1);
INSERT INTO divides VALUES ('cat-1011', 'wb-1011', 'nex-2007', 6.30, 'network', 1);
INSERT INTO divides VALUES ('cat-1012', 'wb-1012', 'nex-2008', 4.10, 'network', 1);
INSERT INTO divides VALUES ('cat-1014', 'wb-1014', 'nex-2010', 3.50, 'network', 1);
INSERT INTO divides VALUES ('cat-1015', 'wb-1015', 'nex-2011', 5.00, 'network', 1);

CREATE TABLE nexus (
    id TEXT PRIMARY KEY,
    toid TEXT DEFAULT '',
    type TEXT DEFAULT 'nexus'
);

INSERT INTO nexus VALUES ('nex-2001', 'cat-1002', 'nexus');
INSERT INTO nexus VALUES ('nex-2002', 'cat-1003', 'nexus');
INSERT INTO nexus VALUES ('nex-2003', 'cat-1006', 'nexus');
INSERT INTO nexus VALUES ('nex-2004', 'cat-1005', 'nexus');
INSERT INTO nexus VALUES ('nex-2005', 'cat-1009', 'nexus');
INSERT INTO nexus VALUES ('nex-2006', 'cat-1011', 'nexus');
INSERT INTO nexus VALUES ('nex-2007', '', 'terminal');
INSERT INTO nexus VALUES ('nex-2009', 'cat-1013', 'nexus');
INSERT INTO nexus VALUES ('nex-2010', 'cat-1015', 'nexus');
INSERT INTO nexus VALUES ('nex-2011', 'cat-1014', 'nexus');
INSERT INTO nexus VALUES ('nex-2012', '', 'terminal');

-- NextGen-specific routing attributes

CREATE TABLE flowpath_attributes (
    id TEXT PRIMARY KEY,
    rl_gages TEXT DEFAULT '',
    Qi REAL DEFAULT 0.0,
    MusK REAL,
    MusX REAL,
    n REAL,
    So REAL,
    ChSlp REAL,
    BtmWdth REAL,
    Kchan REAL DEFAULT 0.0,
    nCC REAL,
    TopWdthCC REAL,
    TopWdth REAL,
    length_m REAL,
    FOREIGN KEY (id) REFERENCES flowpaths(id)
);

INSERT INTO flowpath_attributes VALUES ('wb-1001', '', 0.0, 3600.0, 0.20, 0.060, 0.0012, 0.030, 3.5, 0.0, 0.120, 10.0, 7.0, 3100.0);
INSERT INTO flowpath_attributes VALUES ('wb-1002', '', 0.0, 3600.0, 0.20, 0.055, 0.0008, 0.025, 5.0, 0.0, 0.110, 14.0, 9.5, 4500.0);
INSERT INTO flowpath_attributes VALUES ('wb-1003', '', 0.0, 7200.0, 0.15, 0.045, 0.0006, 0.020, 8.0, 0.0, 0.090, 22.0, 15.0, 6200.0);
INSERT INTO flowpath_attributes VALUES ('wb-1004', '', 0.0, 3600.0, 0.20, 0.058, 0.0010, 0.028, 4.0, 0.0, 0.120, 11.0, 7.5, 3800.0);
INSERT INTO flowpath_attributes VALUES ('wb-1005', '', 0.0, 7200.0, 0.15, 0.048, 0.0007, 0.022, 7.5, 0.0, 0.100, 20.0, 13.0, 7100.0);
INSERT INTO flowpath_attributes VALUES ('wb-1006', '', 0.0, 10800.0, 0.10, 0.040, 0.0005, 0.018, 10.0, 0.0, 0.080, 28.0, 18.0, 5000.0);
INSERT INTO flowpath_attributes VALUES ('wb-1007', '', 0.0, 3600.0, 0.20, 0.062, 0.0015, 0.035, 3.0, 0.0, 0.130, 8.5, 6.0, 4200.0);
INSERT INTO flowpath_attributes VALUES ('wb-1008', '', 0.0, 3600.0, 0.20, 0.065, 0.0018, 0.038, 3.2, 0.0, 0.130, 9.0, 6.5, 5800.0);
INSERT INTO flowpath_attributes VALUES ('wb-1009', '', 0.0, 3600.0, 0.20, 0.052, 0.0009, 0.026, 4.5, 0.0, 0.110, 12.0, 8.0, 2500.0);
INSERT INTO flowpath_attributes VALUES ('wb-1010', '', 0.0, 3600.0, 0.20, 0.058, 0.0011, 0.030, 3.8, 0.0, 0.120, 10.5, 7.2, 2100.0);
INSERT INTO flowpath_attributes VALUES ('wb-1011', '', 0.0, 14400.0, 0.10, 0.038, 0.0004, 0.015, 12.0, 0.0, 0.070, 32.0, 22.0, 3300.0);
INSERT INTO flowpath_attributes VALUES ('wb-1012', '', 0.0, 3600.0, 0.20, 0.060, 0.0013, 0.032, 3.3, 0.0, 0.120, 9.5, 6.8, 2000.0);
INSERT INTO flowpath_attributes VALUES ('wb-1014', '', 0.0, 3600.0, 0.20, 0.055, 0.0010, 0.028, 3.0, 0.0, 0.110, 8.0, 5.5, 1800.0);
INSERT INTO flowpath_attributes VALUES ('wb-1015', '', 0.0, 3600.0, 0.20, 0.058, 0.0012, 0.030, 3.5, 0.0, 0.120, 9.0, 6.2, 2700.0);
INSERT INTO flowpath_attributes VALUES ('wb-1016', '', 0.0, 3600.0, 0.20, 0.060, 0.0014, 0.033, 3.6, 0.0, 0.120, 10.0, 7.0, 3500.0);
