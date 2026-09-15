#!/usr/bin/env python3
"""Create the SQLite config database and binary test vector files."""
import sqlite3
import struct
import os


def crc8(poly_koopman, data):
    gen = (poly_koopman << 1) | 1
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ gen) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
    return crc


def create_database():
    db_path = '/app/crc_config.db'
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute('''CREATE TABLE polynomials (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        koopman_hex TEXT NOT NULL UNIQUE
    )''')

    c.execute('''CREATE TABLE scenarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        dataword_bits INTEGER NOT NULL,
        min_hd INTEGER NOT NULL
    )''')

    c.execute('''CREATE TABLE config (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )''')

    for p in ['0xe7', '0x97', '0x9b', '0xea', '0xa6']:
        c.execute('INSERT INTO polynomials (koopman_hex) VALUES (?)', (p,))

    for name, bits, hd in [('long_range', 200, 3),
                            ('control_bus', 100, 4),
                            ('short_cmd', 3, 5)]:
        c.execute('INSERT INTO scenarios (name, dataword_bits, min_hd) VALUES (?, ?, ?)',
                  (name, bits, hd))

    c.execute("INSERT INTO config VALUES ('crc_width', '8')")
    c.execute("INSERT INTO config VALUES ('max_dataword_length', '260')")
    c.execute("INSERT INTO config VALUES ('max_hd_check', '8')")

    conn.commit()
    conn.close()


def create_test_vectors():
    os.makedirs('/app/test_vectors', exist_ok=True)

    polys = [0xe7, 0x97, 0x9b, 0xea, 0xa6]
    messages = [
        b'\x00',
        b'\xff',
        b'\x01\x02\x03\x04\x05',
        b'Hello CRC',
        b'\xaa\x55\xaa\x55',
        bytes(range(16)),
        b'\xde\xad\xbe\xef\xca\xfe',
        bytes(range(32)),
    ]

    for poly in polys:
        fname = f'/app/test_vectors/vectors_{poly:02x}.bin'
        with open(fname, 'wb') as f:
            # Header
            f.write(b'CRC8')                          # magic (4 bytes)
            f.write(struct.pack('B', poly))            # polynomial (1 byte)
            f.write(struct.pack('<H', len(messages)))  # count (2 bytes LE)
            # Test cases
            for msg in messages:
                f.write(struct.pack('<H', len(msg)))   # msg length (2 bytes LE)
                f.write(msg)                           # msg data
                f.write(struct.pack('B', crc8(poly, msg)))  # CRC (1 byte)

    with open('/app/test_vectors/README', 'w') as f:
        f.write("""Binary Test Vector Format
=========================
Each .bin file contains CRC-8 test vectors for a single polynomial.

File structure:
  Bytes 0-3:  Magic "CRC8" (ASCII)
  Byte 4:     Polynomial in Koopman notation (uint8)
  Bytes 5-6:  Number of test cases N (uint16, little-endian)

  Repeated N times:
    2 bytes:   Message length L in bytes (uint16, little-endian)
    L bytes:   Message data
    1 byte:    Expected CRC-8 checksum

CRC parameters: init=0x00, no output XOR, MSB-first processing.
""")


if __name__ == '__main__':
    create_database()
    create_test_vectors()
    print("Setup complete: database and test vectors created")
