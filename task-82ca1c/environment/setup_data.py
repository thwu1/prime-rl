#!/usr/bin/env python3
"""Create OSPF task data: SQLite database and binary Summary-LSA file."""
import sqlite3
import struct
import socket
import os


def ip_to_bytes(ip_str):
    return socket.inet_aton(ip_str)


def create_db(db_path):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute('''CREATE TABLE areas (
        area_id TEXT PRIMARY KEY,
        area_type TEXT NOT NULL
    )''')

    c.execute('''CREATE TABLE router_lsas (
        advertising_router TEXT NOT NULL,
        area_id TEXT NOT NULL,
        lsa_id TEXT NOT NULL,
        sequence_number TEXT NOT NULL,
        age INTEGER NOT NULL,
        flag_abr INTEGER NOT NULL DEFAULT 0,
        flag_asbr INTEGER NOT NULL DEFAULT 0,
        flag_virtual INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (advertising_router, area_id)
    )''')

    c.execute('''CREATE TABLE router_links (
        advertising_router TEXT NOT NULL,
        area_id TEXT NOT NULL,
        link_type INTEGER NOT NULL,
        link_id TEXT NOT NULL,
        link_data TEXT NOT NULL,
        metric INTEGER NOT NULL,
        seq INTEGER NOT NULL
    )''')

    c.execute('''CREATE TABLE network_lsas (
        lsa_id TEXT NOT NULL,
        advertising_router TEXT NOT NULL,
        area_id TEXT NOT NULL,
        sequence_number TEXT NOT NULL,
        age INTEGER NOT NULL,
        network_mask TEXT NOT NULL,
        PRIMARY KEY (lsa_id, area_id)
    )''')

    c.execute('''CREATE TABLE network_attached_routers (
        network_lsa_id TEXT NOT NULL,
        area_id TEXT NOT NULL,
        router_id TEXT NOT NULL,
        seq INTEGER NOT NULL
    )''')

    c.execute('''CREATE TABLE metadata (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )''')

    # Metadata
    c.execute("INSERT INTO metadata VALUES ('compute_router', '1.1.1.1')")
    c.execute("INSERT INTO metadata VALUES ('backbone_area', '0.0.0.0')")

    # Area
    c.execute("INSERT INTO areas VALUES ('0.0.0.0', 'normal')")

    # rt1 (1.1.1.1) - internal router
    c.execute(
        "INSERT INTO router_lsas VALUES "
        "('1.1.1.1','0.0.0.0','1.1.1.1','0x80000005',120,0,0,0)"
    )
    for seq, (lt, lid, ld, m) in enumerate([
        (1, '2.2.2.2', '10.0.1.1', 10),
        (3, '10.0.1.0', '255.255.255.0', 10),
        (1, '3.3.3.3', '10.0.2.1', 10),
        (3, '10.0.2.0', '255.255.255.0', 10),
        (3, '1.1.1.1', '255.255.255.255', 0),
    ]):
        c.execute(
            "INSERT INTO router_links VALUES "
            "('1.1.1.1','0.0.0.0',?,?,?,?,?)", (lt, lid, ld, m, seq)
        )

    # rt2 (2.2.2.2) - ABR
    c.execute(
        "INSERT INTO router_lsas VALUES "
        "('2.2.2.2','0.0.0.0','2.2.2.2','0x80000003',85,1,0,0)"
    )
    for seq, (lt, lid, ld, m) in enumerate([
        (1, '1.1.1.1', '10.0.1.2', 10),
        (3, '10.0.1.0', '255.255.255.0', 10),
        (2, '10.0.6.3', '10.0.6.2', 10),
        (3, '2.2.2.2', '255.255.255.255', 0),
    ]):
        c.execute(
            "INSERT INTO router_links VALUES "
            "('2.2.2.2','0.0.0.0',?,?,?,?,?)", (lt, lid, ld, m, seq)
        )

    # rt3 (3.3.3.3) - internal router
    c.execute(
        "INSERT INTO router_lsas VALUES "
        "('3.3.3.3','0.0.0.0','3.3.3.3','0x80000004',90,0,0,0)"
    )
    for seq, (lt, lid, ld, m) in enumerate([
        (1, '1.1.1.1', '10.0.2.3', 10),
        (3, '10.0.2.0', '255.255.255.0', 10),
        (2, '10.0.6.3', '10.0.6.3', 10),
        (3, '3.3.3.3', '255.255.255.255', 0),
    ]):
        c.execute(
            "INSERT INTO router_links VALUES "
            "('3.3.3.3','0.0.0.0',?,?,?,?,?)", (lt, lid, ld, m, seq)
        )

    # rt4 (4.4.4.4) - ABR
    c.execute(
        "INSERT INTO router_lsas VALUES "
        "('4.4.4.4','0.0.0.0','4.4.4.4','0x80000002',200,1,0,0)"
    )
    for seq, (lt, lid, ld, m) in enumerate([
        (2, '10.0.6.3', '10.0.6.4', 10),
        (3, '4.4.4.4', '255.255.255.255', 0),
    ]):
        c.execute(
            "INSERT INTO router_links VALUES "
            "('4.4.4.4','0.0.0.0',?,?,?,?,?)", (lt, lid, ld, m, seq)
        )

    # Network-LSA for broadcast segment 10.0.6.0/24 (DR = rt3 at 10.0.6.3)
    c.execute(
        "INSERT INTO network_lsas VALUES "
        "('10.0.6.3','3.3.3.3','0.0.0.0','0x80000001',90,'255.255.255.0')"
    )
    for seq, rid in enumerate(['2.2.2.2', '3.3.3.3', '4.4.4.4']):
        c.execute(
            "INSERT INTO network_attached_routers VALUES "
            "('10.0.6.3','0.0.0.0',?,?)", (rid, seq)
        )

    conn.commit()
    conn.close()


def create_binary_summary_lsas(file_path):
    """Create binary file with Summary-LSAs per FORMAT.md specification."""
    data = b'OSPF\x01'                    # Magic + version
    data += ip_to_bytes('0.0.0.0')        # Area ID
    data += struct.pack('!H', 7)          # 7 LSA records

    lsas = [
        ('5.5.5.5',   '2.2.2.2', 0x80000001, 100, '255.255.255.255', 10),
        ('6.6.6.6',   '2.2.2.2', 0x80000001, 100, '255.255.255.255', 15),
        ('10.0.10.0', '2.2.2.2', 0x80000001, 100, '255.255.255.0',   10),
        ('10.0.11.0', '2.2.2.2', 0x80000001, 100, '255.255.255.0',   15),
        ('7.7.7.7',   '4.4.4.4', 0x80000001, 200, '255.255.255.255', 20),
        ('10.0.20.0', '4.4.4.4', 0x80000001, 200, '255.255.255.0',   20),
        ('6.6.6.6',   '4.4.4.4', 0x80000001, 200, '255.255.255.255', 30),
    ]

    for lsa_id, adv_rtr, seq, age, mask, metric in lsas:
        data += ip_to_bytes(lsa_id)
        data += ip_to_bytes(adv_rtr)
        data += struct.pack('!I', seq)
        data += struct.pack('!H', age)
        data += ip_to_bytes(mask)
        data += struct.pack('!I', metric)[1:]   # 24-bit big-endian metric

    with open(file_path, 'wb') as f:
        f.write(data)


os.makedirs('/app/results', exist_ok=True)
create_db('/app/ospf.db')
create_binary_summary_lsas('/app/summary_lsas.bin')
